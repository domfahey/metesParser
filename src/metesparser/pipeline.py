"""Pipeline orchestrator that chains all stages."""

from __future__ import annotations

import inspect
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
from mp_models import (
    AuditContext,
    CheckResult,
    ClosureResult,
    DeedCall,
    ExtractionRecord,
    LegalDescription,
    LLMStageRecord,
    Tract,
    VerificationAudit,
)
from mp_ocr import (
    EscalationPolicy,
    EscalationReport,
    compare_call_readings,
    count_pdf_pages,
    is_escalated_subset_truncated,
    select_escalation_outcome,
    should_escalate_closure,
    validate_escalation_policy,
    validate_render_dpi,
)
from mp_verify import calculate_confidence_score, verify_closure

from . import pdf_processor as _pdf_processor_module
from .closure_checker import ClosureChecker
from .llm_clients import BaseLLMClient
from .models import AuditContext as MonolithAuditContext
from .models import ClosureResult as MonolithClosureResult
from .models import LegalDescription as MonolithLegalDescription
from .package_bridge import (
    monolith_audit_context,
    monolith_legal_description,
    package_audit_context,
    package_legal_description,
    package_result,
)
from .pdf_processor import PDFProcessor

_ORIGINAL_PDF_PROCESSOR: Any = _pdf_processor_module.PDFProcessor
_ORIGINAL_VERIFY_CLOSURE: Any = verify_closure
_ORIGINAL_CLOSURE_CHECKER_VERIFY: Any = ClosureChecker.__dict__["verify_closure"]

logger = structlog.get_logger(__name__)

_VALID_LLM_PROVIDERS: frozenset[str] = frozenset({"openai", "gemini", "openrouter"})


def _normalize_provider(provider: str, *, name: str = "provider") -> str:
    if not isinstance(provider, str) or not provider.strip():
        raise ValueError(
            f"Invalid {name} {provider!r}; expected one of: openai, gemini, openrouter"
        )
    normalized = provider.strip().lower()
    if normalized not in _VALID_LLM_PROVIDERS:
        raise ValueError(
            f"Invalid {name} {provider!r}; expected one of: openai, gemini, openrouter"
        )
    return normalized


def _safe_model_name(processor: Any) -> str | None:
    """Extract string model identifier from a processor or wrapped client without leaking mocks."""
    name = getattr(processor, "model_name", None)
    if isinstance(name, str) and name.strip():
        return name
    client: Any = getattr(processor, "client", None)
    seen: set[int] = set()
    for _ in range(8):
        if client is None or id(client) in seen:
            break
        seen.add(id(client))
        for attr in ("model_name", "model"):
            val = getattr(client, attr, None)
            if isinstance(val, str) and val.strip():
                return val
        client = getattr(client, "_client", None)
    return None


def _resolve_pdf_processor_cls() -> Any:
    """Honor direct monkeypatches on pipeline.PDFProcessor, else resolve pdf_processor.PDFProcessor."""
    if PDFProcessor is not _ORIGINAL_PDF_PROCESSOR:
        return PDFProcessor
    return _pdf_processor_module.PDFProcessor


def _call_process_deed_pdf(processor: Any, pdf_path: str, *, audit: bool) -> Any:
    """Invoke ``processor.process_deed_pdf``, preserving compatibility with legacy 1-arg test stubs."""
    fn = processor.process_deed_pdf
    if audit:
        return fn(pdf_path, audit=True)
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return fn(pdf_path, audit=False)
    if "audit" in params or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return fn(pdf_path, audit=False)
    return fn(pdf_path)


def _infer_processor_provider(processor: Any, fallback: str | None) -> str | None:
    """Infer the real provider of *processor*'s client so injected clients do not collide with default ``provider='openai'``."""
    from mp_ocr.clients import (
        GeminiClient as PkgGeminiClient,
    )
    from mp_ocr.clients import (
        OpenAIClient as PkgOpenAIClient,
    )
    from mp_ocr.clients import (
        OpenRouterClient as PkgOpenRouterClient,
    )

    from .llm_clients import GeminiClient, OpenAIClient, OpenRouterClient

    raw = getattr(processor, "client", None)
    for _ in range(4):
        if raw is None or not isinstance(getattr(raw, "_cache_dir", None), Path):
            break
        raw = getattr(raw, "_client", None)
    if raw is None:
        return fallback
    if isinstance(raw, (OpenRouterClient, PkgOpenRouterClient)):
        return "openrouter"
    if isinstance(raw, (OpenAIClient, PkgOpenAIClient)):
        return "openai"
    if isinstance(raw, (GeminiClient, PkgGeminiClient)):
        return "gemini"
    return fallback


def _close_processor_client(processor: Any) -> None:
    """Best-effort close of an SDK-backed HTTP client pool created by ``Pipeline.run()``."""
    client = getattr(processor, "client", None)
    # Unwrap bounded cache wrapper layers (real CachedLLMClient has a Path _cache_dir).
    for _ in range(4):
        if client is None or not isinstance(getattr(client, "_cache_dir", None), Path):
            break
        client = getattr(client, "_client", None)
    if client is None:
        return
    for target in (client, getattr(client, "_client", None)):
        close_fn = getattr(target, "close", None)
        if callable(close_fn):
            try:
                close_fn()
            except Exception:
                pass


def _coerce_package_llm_stages(stages: list[Any]) -> list[LLMStageRecord]:
    """Convert monolith or package LLMStageRecord objects into ``mp_models.LLMStageRecord``."""
    out: list[LLMStageRecord] = []
    for stage in stages:
        if isinstance(stage, LLMStageRecord):
            out.append(stage)
        else:
            out.append(LLMStageRecord.model_validate(stage.model_dump()))
    return out


def _is_escalated_truncated(
    primary_desc: LegalDescription,
    primary_calls: list[Any],
    esc_desc: LegalDescription,
    esc_calls: list[Any],
) -> bool:
    """Return True if an escalated subset lost tracts, per-tract calls, area, or tail note categories."""
    return is_escalated_subset_truncated(
        primary_calls=primary_calls,
        escalated_calls=esc_calls,
        primary_tracts=primary_desc.tracts or None,
        escalated_tracts=esc_desc.tracts or None,
        primary_stated_area_sq_ft=primary_desc.stated_area_sq_ft,
        escalated_stated_area_sq_ft=esc_desc.stated_area_sq_ft,
    )


def _sync_verification_audit(v_audit: VerificationAudit, res: ClosureResult) -> VerificationAudit:
    summary = dict(v_audit.closure_summary)
    if res.confidence_score is not None:
        summary["confidence_score"] = res.confidence_score
    summary["status"] = res.get_closure_status()
    summary["geometry_verified"] = res.geometry_verified
    return VerificationAudit(
        checks=list(res.checks),
        closure_summary=summary,
        tract_label=v_audit.tract_label,
    )


def _to_package_result(res: ClosureResult | MonolithClosureResult) -> ClosureResult:
    return res if isinstance(res, ClosureResult) else package_result(res)


def _verify_legal_desc(
    legal_desc: LegalDescription,
    audit_ctx: AuditContext | None,
) -> ClosureResult | list[ClosureResult]:
    if (
        verify_closure is _ORIGINAL_VERIFY_CLOSURE
        and ClosureChecker.__dict__.get("verify_closure") is not _ORIGINAL_CLOSURE_CHECKER_VERIFY
    ):
        mono_ld = monolith_legal_description(legal_desc)
        mono_audit = monolith_audit_context(audit_ctx) if audit_ctx is not None else None
        verify_kwargs: dict[str, Any] = {
            "stated_area_sq_ft": mono_ld.stated_area_sq_ft or 0.0,
        }
        if mono_audit is not None:
            verify_kwargs["audit_context"] = mono_audit
        if mono_ld.tracts:
            verify_kwargs["tracts"] = mono_ld.tracts
            mono_calls = mono_ld.all_calls
        else:
            mono_calls = mono_ld.calls
        checker_fn: Any = ClosureChecker.verify_closure
        raw_res: Any = checker_fn(mono_calls, **verify_kwargs)
        if audit_ctx is not None and mono_audit is not None:
            synced = package_audit_context(mono_audit)
            audit_ctx.verification_audit = synced.verification_audit
            audit_ctx.tract_verification_audits = synced.tract_verification_audits
        if isinstance(raw_res, list):
            return [_to_package_result(r) for r in raw_res]
        return _to_package_result(raw_res)

    if legal_desc.tracts:
        stated_area: float | None = getattr(legal_desc, "stated_area_sq_ft", None)
        if stated_area is not None:
            return verify_closure(
                legal_desc.all_calls,
                tracts=legal_desc.tracts,
                stated_area_sq_ft=stated_area,
                audit_context=audit_ctx,
            )
        return verify_closure(
            legal_desc.all_calls,
            tracts=legal_desc.tracts,
            audit_context=audit_ctx,
        )
    return verify_closure(
        legal_desc.calls,
        stated_area_sq_ft=legal_desc.stated_area_sq_ft or 0.0,
        audit_context=audit_ctx,
    )


def _apply_disagreement_check(
    res: ClosureResult,
    calls: list[Any],
    extra_warnings: list[str],
    disagreement_check: CheckResult,
) -> ClosureResult:
    updated = res.model_copy(
        update={
            "warnings": [*res.warnings, *extra_warnings],
            "checks": [*res.checks, disagreement_check],
        }
    )
    confidence = calculate_confidence_score(updated, calls)
    return updated.model_copy(update={"confidence_score": confidence})


def _sync_audit_with_escalation(
    results: ClosureResult | list[ClosureResult],
    legal_desc: LegalDescription,
    report: EscalationReport,
    audit_ctx: AuditContext | None,
    *,
    failure_detail: str | None = None,
) -> ClosureResult | list[ClosureResult]:
    """Attach OCR disagreement/failure checks & warnings and keep VerificationAudit & RunMetadata in sync."""
    extra_warnings = list(report.review_warnings)
    check_reason = "ocr_escalation_disagreement"
    if report.triggered and not report.agrees and not extra_warnings:
        check_reason = report.selection_reason
        suffix = f": {failure_detail}" if failure_detail else ""
        extra_warnings.append(
            f"OCR escalation did not complete agreement ({report.selection_reason}{suffix}) "
            "— manual source verification required"
        )
    final_results: ClosureResult | list[ClosureResult] = results

    if extra_warnings:
        disagreement_check = CheckResult(
            name="ocr_escalation_agreement",
            status="failed",
            reason=check_reason,
            detail="; ".join(extra_warnings),
            inputs={"disagreement_count": len(report.disagreements)},
        )
        if isinstance(results, ClosureResult):
            updated_single = _apply_disagreement_check(
                results, legal_desc.calls, extra_warnings, disagreement_check
            )
            final_results = updated_single
            if audit_ctx is not None and audit_ctx.verification_audit is not None:
                audit_ctx.verification_audit = _sync_verification_audit(
                    audit_ctx.verification_audit, updated_single
                )
        else:
            updated_list: list[ClosureResult] = []
            for idx, res in enumerate(results):
                tract_calls = (
                    legal_desc.tracts[idx].calls
                    if idx < len(legal_desc.tracts)
                    else legal_desc.all_calls
                )
                updated_res = _apply_disagreement_check(
                    res, tract_calls, extra_warnings, disagreement_check
                )
                updated_list.append(updated_res)
                if audit_ctx is not None and idx < len(audit_ctx.tract_verification_audits):
                    audit_ctx.tract_verification_audits[idx] = _sync_verification_audit(
                        audit_ctx.tract_verification_audits[idx], updated_res
                    )
            final_results = updated_list

    if audit_ctx is not None and report.policy != "never":
        cfg = dict(audit_ctx.run_metadata.config)
        cfg["escalation_policy"] = report.policy
        cfg["escalation_triggered"] = report.triggered
        cfg["escalation_agrees"] = report.agrees
        cfg["escalation_selected"] = report.selected
        cfg["escalation_selection_reason"] = report.selection_reason
        cfg["escalation_disagreement_count"] = len(report.disagreements)
        if failure_detail:
            cfg["escalation_error"] = failure_detail
        if report.primary_model:
            cfg["primary_model"] = report.primary_model
        if report.escalation_model:
            cfg["escalation_model"] = report.escalation_model
        if report.legal_pages:
            cfg["escalation_legal_pages"] = ",".join(str(p) for p in report.legal_pages)
        audit_ctx.run_metadata = type(audit_ctx.run_metadata).model_validate(
            {**audit_ctx.run_metadata.model_dump(), "config": cfg}
        )

    return final_results


def _return_with_audit(
    results: ClosureResult | list[ClosureResult],
    audit_ctx: AuditContext,
) -> tuple[ClosureResult, AuditContext] | tuple[list[ClosureResult], AuditContext]:
    if isinstance(results, list):
        return results, audit_ctx
    return results, audit_ctx


@dataclass(frozen=True)
class PipelineResult:
    """Immutable, structured output of ``Pipeline.run_detailed()``.

    Exposes all stage outputs without writing CSV or audit files.
    """

    pdf_path: Path
    legal_description: LegalDescription
    closure: ClosureResult | tuple[ClosureResult, ...]
    audit_context: AuditContext | None = None
    escalation_report: EscalationReport | None = None
    provider: str | None = None
    primary_model: str | None = None
    prompts_dir: Path | None = None

    @property
    def is_multi_tract(self) -> bool:
        return isinstance(self.closure, tuple)

    @property
    def closure_results(self) -> tuple[ClosureResult, ...]:
        if isinstance(self.closure, tuple):
            return self.closure
        return (self.closure,)

    @property
    def calls(self) -> tuple[DeedCall, ...]:
        raw_calls = (
            self.legal_description.all_calls
            if self.legal_description.tracts
            else self.legal_description.calls
        )
        return tuple(raw_calls)

    @property
    def tract_results(self) -> tuple[tuple[Tract, ClosureResult], ...]:
        if isinstance(self.closure, tuple):
            return tuple(zip(self.legal_description.tracts, self.closure, strict=True))
        return ()

    @property
    def raw_llm_response(self) -> str | None:
        if self.audit_context is None or self.audit_context.extraction_record is None:
            return None
        return self.audit_context.extraction_record.raw_llm_response

    @property
    def normalized_text(self) -> str | None:
        if self.audit_context is None or self.audit_context.extraction_record is None:
            return None
        return self.audit_context.extraction_record.normalized_text


class Pipeline:
    """Chain mp-ocr → mp-parse → mp-verify → mp-export."""

    def __init__(
        self,
        provider: str | None = None,
        *,
        cache: bool = True,
        audit: bool = False,
        client: BaseLLMClient | None = None,
        escalation_policy: EscalationPolicy = "never",
        escalation_provider: str | None = None,
        escalation_client: BaseLLMClient | None = None,
        escalation_dpi: int = 300,
        strip_watermark: bool = True,
        crop_margins: bool = True,
    ) -> None:
        validated_policy = validate_escalation_policy(escalation_policy)
        validated_dpi = validate_render_dpi(escalation_dpi, name="escalation_dpi")
        self._provider_explicit = provider is not None
        raw_provider = "openai" if provider is None else provider
        validated_provider = (
            raw_provider.strip().lower()
            if isinstance(raw_provider, str) and raw_provider.strip()
            else raw_provider
        )
        validated_esc_provider = (
            _normalize_provider(escalation_provider, name="escalation_provider")
            if escalation_provider is not None
            else None
        )
        self.provider = validated_provider
        self.cache = cache
        self.audit = audit
        self.client = client
        self.escalation_policy: EscalationPolicy = validated_policy
        self.escalation_provider = validated_esc_provider
        self.escalation_client = escalation_client
        self.escalation_dpi = validated_dpi
        self.strip_watermark = strip_watermark
        self.crop_margins = crop_margins
        self._thread_state = threading.local()

    @property
    def last_escalation_report(self) -> EscalationReport | None:
        """Thread-local escalation report from the most recent ``run()`` call on this thread."""
        report: EscalationReport | None = getattr(
            self._thread_state, "last_escalation_report", None
        )
        return report

    @last_escalation_report.setter
    def last_escalation_report(self, value: EscalationReport | None) -> None:
        self._thread_state.last_escalation_report = value

    def _convert_processor_output(
        self, result: Any
    ) -> tuple[LegalDescription, AuditContext | None]:
        raw_legal_desc: LegalDescription | MonolithLegalDescription
        raw_audit_ctx: AuditContext | MonolithAuditContext | None = None
        if self.audit:
            assert isinstance(result, tuple)
            raw_legal_desc, raw_audit_ctx = result
        else:
            assert not isinstance(result, tuple)
            raw_legal_desc = result

        legal_desc = (
            raw_legal_desc
            if isinstance(raw_legal_desc, LegalDescription)
            else package_legal_description(raw_legal_desc)
        )
        audit_ctx = (
            None
            if raw_audit_ctx is None
            else (
                raw_audit_ctx
                if isinstance(raw_audit_ctx, AuditContext)
                else package_audit_context(raw_audit_ctx)
            )
        )
        return legal_desc, audit_ctx

    def run_detailed(self, pdf_path: Path | str) -> PipelineResult:
        """Run the full pipeline on a PDF and return a structured ``PipelineResult``.

        Executes OCR -> parse -> verify (plus optional blind escalation) without
        writing CSV, audit, or manifest files.

        Args:
            pdf_path: Path to the deed PDF file.

        Returns:
            Frozen ``PipelineResult`` with legal description, closure result(s),
            optional audit context, escalation report, and provider/model metadata.
        """
        pdf_path_obj = Path(pdf_path)
        self.last_escalation_report = None
        owned_processors: list[Any] = []
        try:
            processor_cls = _resolve_pdf_processor_cls()
            processor = (
                processor_cls(provider=self.provider, cache=self.cache)
                if self.client is None
                else processor_cls(provider=self.provider, client=self.client, cache=self.cache)
            )
            if self.client is None:
                owned_processors.append(processor)
            primary_output = _call_process_deed_pdf(processor, str(pdf_path_obj), audit=self.audit)
            raw_prompts_dir = getattr(processor, "prompts_dir", None)
            prompts_dir = raw_prompts_dir if isinstance(raw_prompts_dir, Path) else None
            legal_desc, audit_ctx = self._convert_processor_output(primary_output)
            primary_results = _verify_legal_desc(legal_desc, audit_ctx)
            primary_calls = legal_desc.all_calls if legal_desc.tracts else legal_desc.calls

            provider_fallback = (
                str(self.provider).strip().lower()
                if self._provider_explicit or self.client is None
                else None
            )
            primary_provider = _infer_processor_provider(processor, provider_fallback)
            resolved_provider = (
                primary_provider if primary_provider is not None else str(self.provider)
            )
            primary_model = _safe_model_name(processor)

            def _build_result(
                final_legal_desc: LegalDescription,
                final_results: ClosureResult | list[ClosureResult],
                final_ctx: AuditContext | None,
                report: EscalationReport,
            ) -> PipelineResult:
                self.last_escalation_report = report
                closure_out: ClosureResult | tuple[ClosureResult, ...] = (
                    tuple(final_results) if isinstance(final_results, list) else final_results
                )
                return PipelineResult(
                    pdf_path=pdf_path_obj,
                    legal_description=final_legal_desc,
                    closure=closure_out,
                    audit_context=final_ctx,
                    escalation_report=report,
                    provider=resolved_provider,
                    primary_model=primary_model,
                    prompts_dir=prompts_dir,
                )

            should_esc, trigger_reasons = should_escalate_closure(
                primary_results,
                policy=self.escalation_policy,
                has_calls=bool(primary_calls),
            )
            if not should_esc:
                report = EscalationReport(
                    triggered=False,
                    policy=self.escalation_policy,
                    primary_model=primary_model,
                )
                final_primary = _sync_audit_with_escalation(
                    primary_results, legal_desc, report, audit_ctx if self.audit else None
                )
                return _build_result(
                    legal_desc,
                    final_primary,
                    audit_ctx if self.audit else None,
                    report,
                )

            esc_processor: Any = None
            esc_stages: list[Any] = []
            legal_pages: list[int] = []

            def _fallback_primary_on_failure(
                selection_reason: str,
                exc: Exception,
            ) -> PipelineResult:
                err_summary = f"{type(exc).__name__}: {str(exc)[:200]}"
                logger.warning(
                    "OCR escalation failed; preserving primary result fail-closed",
                    selection_reason=selection_reason,
                    error=err_summary,
                )
                fail_report = EscalationReport(
                    triggered=True,
                    policy=self.escalation_policy,
                    trigger_reasons=tuple(trigger_reasons),
                    legal_pages=tuple(legal_pages),
                    primary_model=primary_model,
                    escalation_model=_safe_model_name(esc_processor),
                    agrees=False,
                    disagreements=(),
                    selected="primary",
                    selection_reason=selection_reason,
                )
                synced_primary = _sync_audit_with_escalation(
                    primary_results,
                    legal_desc,
                    fail_report,
                    audit_ctx if self.audit else None,
                    failure_detail=err_summary,
                )
                final_ctx: AuditContext | None = None
                if self.audit:
                    assert audit_ctx is not None
                    if audit_ctx.extraction_record is not None and esc_stages:
                        merged = list(
                            audit_ctx.extraction_record.llm_stages
                        ) + _coerce_package_llm_stages(esc_stages)
                        audit_ctx.extraction_record = ExtractionRecord.model_validate(
                            {**audit_ctx.extraction_record.model_dump(), "llm_stages": merged}
                        )
                    final_ctx = audit_ctx
                return _build_result(legal_desc, synced_primary, final_ctx, fail_report)

            try:
                if self.escalation_client is None and (
                    self.escalation_provider is None or self.escalation_provider == primary_provider
                ):
                    esc_processor = processor
                else:
                    esc_processor = processor_cls(
                        provider=self.escalation_provider or self.provider,
                        client=self.escalation_client,
                        cache=self.cache,
                    )
                    if self.escalation_client is None:
                        owned_processors.append(esc_processor)

                locator = processor if processor.supports_images else esc_processor
                rendered_by_page: dict[int, Path] = {}

                with tempfile.TemporaryDirectory(prefix="mp_ocr_pipe_esc_") as esc_tmpdir:
                    esc_work_dir = Path(esc_tmpdir)

                    def _run_escalation_pass(
                        *,
                        pages: list[int] | None,
                        stage_prefix: str,
                        pass_locator: Any,
                    ) -> tuple[
                        LegalDescription | None, AuditContext | None, list[int], Exception | None
                    ]:
                        assert esc_processor is not None
                        esc_legal_text, esc_norm_text, pass_pages = (
                            esc_processor.extract_legal_description_from_images(
                                str(pdf_path_obj),
                                pages=pages,
                                dpi=self.escalation_dpi,
                                strip_watermark=self.strip_watermark,
                                crop_margins=self.crop_margins,
                                audit=self.audit,
                                stage_prefix=stage_prefix,
                                locator_processor=pass_locator,
                                rendered_by_page=rendered_by_page,
                                work_dir=esc_work_dir,
                            )
                        )
                        if self.audit:
                            esc_stages.extend(esc_processor.pop_audit_stage_records())
                        try:
                            esc_output = esc_processor.process_legal_text(
                                str(pdf_path_obj),
                                legal_desc_text=esc_legal_text,
                                normalized_text=esc_norm_text,
                                llm_stage_records=list(esc_stages) if self.audit else None,
                                audit=self.audit,
                            )
                        except ValueError as exc:
                            return None, None, pass_pages, exc
                        desc, ctx_out = self._convert_processor_output(esc_output)
                        return desc, ctx_out, pass_pages, None

                    esc_legal_desc, esc_audit_ctx, legal_pages, parse_err = _run_escalation_pass(
                        pages=None,
                        stage_prefix="escalation_",
                        pass_locator=locator,
                    )
                    esc_calls = (
                        (
                            esc_legal_desc.all_calls
                            if esc_legal_desc.tracts
                            else esc_legal_desc.calls
                        )
                        if esc_legal_desc is not None
                        else []
                    )

                    # If a located page subset failed strict parsing or dropped tracts/calls/area/notes,
                    # retry across all pages before comparing against primary.
                    truncated = parse_err is not None or (
                        esc_legal_desc is not None
                        and _is_escalated_truncated(
                            legal_desc, primary_calls, esc_legal_desc, esc_calls
                        )
                    )
                    if truncated:
                        total_pages = count_pdf_pages(str(pdf_path_obj))
                        if len(legal_pages) < total_pages:
                            all_pages = list(range(1, total_pages + 1))
                            esc_legal_desc, esc_audit_ctx, legal_pages, parse_err = (
                                _run_escalation_pass(
                                    pages=all_pages,
                                    stage_prefix="escalation_fallback_",
                                    pass_locator=None,
                                )
                            )
                            esc_calls = (
                                (
                                    esc_legal_desc.all_calls
                                    if esc_legal_desc.tracts
                                    else esc_legal_desc.calls
                                )
                                if esc_legal_desc is not None
                                else []
                            )
            except Exception as runtime_exc:
                return _fallback_primary_on_failure(
                    "escalated_runtime_error_fallback_to_primary", runtime_exc
                )

            if esc_legal_desc is None or parse_err is not None:
                return _fallback_primary_on_failure(
                    "escalated_parse_failed_fallback_to_primary",
                    parse_err or ValueError("Escalation produced no legal description"),
                )

            esc_results = _verify_legal_desc(esc_legal_desc, esc_audit_ctx)

            disagreements = compare_call_readings(
                primary_calls,
                esc_calls,
                primary_tracts=legal_desc.tracts or None,
                escalated_tracts=esc_legal_desc.tracts or None,
                primary_stated_area_sq_ft=legal_desc.stated_area_sq_ft,
                escalated_stated_area_sq_ft=esc_legal_desc.stated_area_sq_ft,
            )
            selected, selection_reason = select_escalation_outcome(
                primary_calls=primary_calls,
                escalated_calls=esc_calls,
                primary_results=primary_results,
                escalated_results=esc_results,
                disagreements=disagreements,
                primary_tracts=legal_desc.tracts or None,
                escalated_tracts=esc_legal_desc.tracts or None,
                primary_stated_area_sq_ft=legal_desc.stated_area_sq_ft,
                escalated_stated_area_sq_ft=esc_legal_desc.stated_area_sq_ft,
            )
            report = EscalationReport(
                triggered=True,
                policy=self.escalation_policy,
                trigger_reasons=tuple(trigger_reasons),
                legal_pages=tuple(legal_pages),
                primary_model=primary_model,
                escalation_model=_safe_model_name(esc_processor),
                agrees=not disagreements,
                disagreements=tuple(disagreements),
                selected=selected,
                selection_reason=selection_reason,
            )

            final_legal_desc = esc_legal_desc if selected == "escalated" else legal_desc
            final_results = esc_results if selected == "escalated" else primary_results
            final_ctx = (
                (esc_audit_ctx if selected == "escalated" else audit_ctx) if self.audit else None
            )
            final_results = _sync_audit_with_escalation(
                final_results, final_legal_desc, report, final_ctx
            )

            if self.audit:
                other_ctx = audit_ctx if selected == "escalated" else esc_audit_ctx
                assert final_ctx is not None
                if (
                    final_ctx.extraction_record is not None
                    and other_ctx is not None
                    and other_ctx.extraction_record is not None
                ):
                    combined_stages = _coerce_package_llm_stages(
                        list(other_ctx.extraction_record.llm_stages)
                        + list(final_ctx.extraction_record.llm_stages)
                        if selected == "escalated"
                        else list(final_ctx.extraction_record.llm_stages)
                        + list(other_ctx.extraction_record.llm_stages)
                    )
                    final_ctx.extraction_record = ExtractionRecord.model_validate(
                        {**final_ctx.extraction_record.model_dump(), "llm_stages": combined_stages}
                    )
            return _build_result(final_legal_desc, final_results, final_ctx, report)
        finally:
            for proc in owned_processors:
                _close_processor_client(proc)

    def run(
        self, pdf_path: Path
    ) -> (
        ClosureResult
        | list[ClosureResult]
        | tuple[ClosureResult, AuditContext]
        | tuple[list[ClosureResult], AuditContext]
    ):
        """Run the full pipeline on a PDF.

        Args:
            pdf_path: Path to the deed PDF file.

        Returns:
            For single-tract deeds:
                ClosureResult when audit=False
                (ClosureResult, AuditContext) when audit=True
            For multi-tract deeds:
                list[ClosureResult] when audit=False
                (list[ClosureResult], AuditContext) when audit=True
        """
        detailed = self.run_detailed(pdf_path)
        results: ClosureResult | list[ClosureResult] = (
            list(detailed.closure) if isinstance(detailed.closure, tuple) else detailed.closure
        )
        if self.audit:
            assert detailed.audit_context is not None
            return _return_with_audit(results, detailed.audit_context)
        return results
