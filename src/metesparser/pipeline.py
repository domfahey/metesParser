"""Pipeline orchestrator that chains all stages."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from mp_models import (
    DESCRIPTION_ROLES_NOTE,
    INVALID_STATED_AREA_NOTE_PREFIX,
    NON_BOUNDARY_NOTES,
    RIGHTS_RESERVED_NOTE_PREFIX,
    SEPARATE_EASEMENT_NOTE_PREFIX,
    UNAPPLIED_EXCEPTION_NOTE_PREFIX,
    AuditContext,
    CheckResult,
    ClosureResult,
    LegalDescription,
    VerificationAudit,
    split_notes,
)
from mp_ocr import (
    EscalationPolicy,
    EscalationReport,
    compare_call_readings,
    count_pdf_pages,
    select_escalation_outcome,
    should_escalate_closure,
    validate_escalation_policy,
    validate_render_dpi,
)
from mp_verify import calculate_confidence_score, verify_closure

from .llm_clients import BaseLLMClient
from .models import AuditContext as MonolithAuditContext
from .models import LegalDescription as MonolithLegalDescription
from .package_bridge import package_audit_context, package_legal_description
from .pdf_processor import PDFProcessor


def _safe_model_name(processor: Any) -> str | None:
    """Extract string ``model_name`` from a processor or stub without leaking mocks."""
    name = getattr(processor, "model_name", None)
    return name if isinstance(name, str) and name.strip() else None


def _client_supports_images(client: Any) -> bool:
    """Return True if the unwrapped client implements ``generate_text_with_images``."""
    inner = PDFProcessor._unwrap_client(client)
    return callable(getattr(inner, "generate_text_with_images", None))


_TAIL_BLOCKING_EXACT_NOTES: frozenset[str] = frozenset(
    note.lower() for note in (DESCRIPTION_ROLES_NOTE, *NON_BOUNDARY_NOTES)
)
_TAIL_BLOCKING_NOTE_PREFIXES: tuple[str, ...] = tuple(
    prefix.lower()
    for prefix in (
        UNAPPLIED_EXCEPTION_NOTE_PREFIX,
        INVALID_STATED_AREA_NOTE_PREFIX,
        RIGHTS_RESERVED_NOTE_PREFIX,
        SEPARATE_EASEMENT_NOTE_PREFIX,
    )
)


def _has_tail_blocking_note(calls: list[Any]) -> bool:
    """Return True if any call carries a deed/tail blocking or reservation/easement note."""
    for call in calls:
        for note in split_notes(call.notes):
            lowered = note.strip().lower()
            if lowered in _TAIL_BLOCKING_EXACT_NOTES or lowered.startswith(
                _TAIL_BLOCKING_NOTE_PREFIXES
            ):
                return True
    return False


def _is_escalated_truncated(
    primary_desc: LegalDescription,
    primary_calls: list[Any],
    esc_desc: LegalDescription,
    esc_calls: list[Any],
) -> bool:
    """Return True if an escalated subset lost tracts, per-tract calls, area, or tail blocking notes."""
    if primary_desc.tracts:
        if len(esc_desc.tracts) < len(primary_desc.tracts):
            return True
        for pri_t, esc_t in zip(primary_desc.tracts, esc_desc.tracts, strict=False):
            if pri_t.calls and len(esc_t.calls) < len(pri_t.calls):
                return True
    if primary_calls and len(esc_calls) < len(primary_calls):
        return True
    if primary_desc.stated_area_sq_ft is not None and esc_desc.stated_area_sq_ft is None:
        return True
    if _has_tail_blocking_note(primary_calls) and not _has_tail_blocking_note(esc_calls):
        return True
    return False


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


def _verify_legal_desc(
    legal_desc: LegalDescription,
    audit_ctx: AuditContext | None,
) -> ClosureResult | list[ClosureResult]:
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
) -> ClosureResult | list[ClosureResult]:
    """Attach OCR disagreement checks/warnings and keep VerificationAudit & RunMetadata in sync."""
    extra_warnings = report.review_warnings
    final_results: ClosureResult | list[ClosureResult] = results

    if extra_warnings:
        disagreement_check = CheckResult(
            name="ocr_escalation_agreement",
            status="failed",
            reason="ocr_escalation_disagreement",
            detail="; ".join(extra_warnings),
            inputs={"disagreement_count": len(extra_warnings)},
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


class Pipeline:
    """Chain mp-ocr → mp-parse → mp-verify → mp-export."""

    def __init__(
        self,
        provider: str = "openai",
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
        self.provider = provider
        self.cache = cache
        self.audit = audit
        self.client = client
        self.escalation_policy: EscalationPolicy = validated_policy
        self.escalation_provider = escalation_provider
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
        self.last_escalation_report = None
        processor = (
            PDFProcessor(provider=self.provider, cache=self.cache)
            if self.client is None
            else PDFProcessor(provider=self.provider, client=self.client, cache=self.cache)
        )
        primary_output = processor.process_deed_pdf(str(pdf_path), audit=self.audit)
        legal_desc, audit_ctx = self._convert_processor_output(primary_output)
        primary_results = _verify_legal_desc(legal_desc, audit_ctx)
        primary_calls = legal_desc.all_calls if legal_desc.tracts else legal_desc.calls

        should_esc, trigger_reasons = should_escalate_closure(
            primary_results,
            policy=self.escalation_policy,
            has_calls=bool(primary_calls),
        )
        if not should_esc:
            report = EscalationReport(
                triggered=False,
                policy=self.escalation_policy,
                primary_model=_safe_model_name(processor),
            )
            self.last_escalation_report = report
            final_primary = _sync_audit_with_escalation(
                primary_results, legal_desc, report, audit_ctx if self.audit else None
            )
            if self.audit:
                assert audit_ctx is not None
                return _return_with_audit(final_primary, audit_ctx)
            return final_primary

        esc_processor = (
            processor
            if self.escalation_client is None
            and (self.escalation_provider is None or self.escalation_provider == self.provider)
            else PDFProcessor(
                provider=self.escalation_provider or self.provider,
                client=self.escalation_client,
                cache=self.cache,
            )
        )
        locator = processor if _client_supports_images(processor.client) else esc_processor
        esc_stages: list[Any] = []

        def _run_escalation_pass(
            *,
            pages: list[int] | None,
            stage_prefix: str,
            pass_locator: PDFProcessor | None,
        ) -> tuple[LegalDescription | None, AuditContext | None, list[int], Exception | None]:
            esc_legal_text, esc_norm_text, pass_pages = (
                esc_processor.extract_legal_description_from_images(
                    str(pdf_path),
                    pages=pages,
                    dpi=self.escalation_dpi,
                    strip_watermark=self.strip_watermark,
                    crop_margins=self.crop_margins,
                    audit=self.audit,
                    stage_prefix=stage_prefix,
                    locator_processor=pass_locator,
                )
            )
            if self.audit:
                esc_stages.extend(esc_processor.pop_audit_stage_records())
            try:
                esc_output = esc_processor.process_legal_text(
                    str(pdf_path),
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
            (esc_legal_desc.all_calls if esc_legal_desc.tracts else esc_legal_desc.calls)
            if esc_legal_desc is not None
            else []
        )

        # If a located page subset failed strict parsing or dropped tracts/calls/area/notes,
        # retry across all pages before comparing against primary.
        truncated = parse_err is not None or (
            esc_legal_desc is not None
            and _is_escalated_truncated(legal_desc, primary_calls, esc_legal_desc, esc_calls)
        )
        if truncated:
            total_pages = count_pdf_pages(str(pdf_path))
            if len(legal_pages) < total_pages:
                all_pages = list(range(1, total_pages + 1))
                esc_legal_desc, esc_audit_ctx, legal_pages, parse_err = _run_escalation_pass(
                    pages=all_pages,
                    stage_prefix="escalation_fallback_",
                    pass_locator=None,
                )
                esc_calls = (
                    (esc_legal_desc.all_calls if esc_legal_desc.tracts else esc_legal_desc.calls)
                    if esc_legal_desc is not None
                    else []
                )

        if esc_legal_desc is None or parse_err is not None:
            report = EscalationReport(
                triggered=True,
                policy=self.escalation_policy,
                trigger_reasons=tuple(trigger_reasons),
                legal_pages=tuple(legal_pages),
                primary_model=_safe_model_name(processor),
                escalation_model=_safe_model_name(esc_processor),
                agrees=False,
                disagreements=(),
                selected="primary",
                selection_reason="escalated_parse_failed_fallback_to_primary",
            )
            self.last_escalation_report = report
            final_primary = _sync_audit_with_escalation(
                primary_results, legal_desc, report, audit_ctx if self.audit else None
            )
            if self.audit:
                assert audit_ctx is not None
                if audit_ctx.extraction_record is not None and esc_stages:
                    audit_ctx.extraction_record = audit_ctx.extraction_record.model_copy(
                        update={
                            "llm_stages": list(audit_ctx.extraction_record.llm_stages)
                            + list(esc_stages)
                        }
                    )
                return _return_with_audit(final_primary, audit_ctx)
            return final_primary

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
        )
        report = EscalationReport(
            triggered=True,
            policy=self.escalation_policy,
            trigger_reasons=tuple(trigger_reasons),
            legal_pages=tuple(legal_pages),
            primary_model=_safe_model_name(processor),
            escalation_model=_safe_model_name(esc_processor),
            agrees=not disagreements,
            disagreements=tuple(disagreements),
            selected=selected,
            selection_reason=selection_reason,
        )
        self.last_escalation_report = report

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
                combined_stages = (
                    list(other_ctx.extraction_record.llm_stages)
                    + list(final_ctx.extraction_record.llm_stages)
                    if selected == "escalated"
                    else list(final_ctx.extraction_record.llm_stages)
                    + list(other_ctx.extraction_record.llm_stages)
                )
                final_ctx.extraction_record = final_ctx.extraction_record.model_copy(
                    update={"llm_stages": combined_stages}
                )
            return _return_with_audit(final_results, final_ctx)
        return final_results
