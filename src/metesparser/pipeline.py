"""Pipeline orchestrator that chains all stages."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mp_models import AuditContext, ClosureResult, LegalDescription
from mp_ocr.escalation import (
    EscalationPolicy,
    EscalationReport,
    compare_call_readings,
    select_escalation_outcome,
    should_escalate_closure,
)
from mp_verify import verify_closure

from .llm_clients import BaseLLMClient
from .models import AuditContext as MonolithAuditContext
from .models import LegalDescription as MonolithLegalDescription
from .package_bridge import package_audit_context, package_legal_description
from .pdf_processor import PDFProcessor


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


def _attach_warnings(
    results: ClosureResult | list[ClosureResult],
    extra_warnings: list[str],
) -> ClosureResult | list[ClosureResult]:
    if not extra_warnings:
        return results
    if isinstance(results, ClosureResult):
        return results.model_copy(update={"warnings": [*results.warnings, *extra_warnings]})
    return [
        res.model_copy(update={"warnings": [*res.warnings, *extra_warnings]}) for res in results
    ]


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
        self.provider = provider
        self.cache = cache
        self.audit = audit
        self.client = client
        self.escalation_policy: EscalationPolicy = escalation_policy
        self.escalation_provider = escalation_provider
        self.escalation_client = escalation_client
        self.escalation_dpi = escalation_dpi
        self.strip_watermark = strip_watermark
        self.crop_margins = crop_margins
        self.last_escalation_report: EscalationReport | None = None

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

        should_esc, trigger_reasons = should_escalate_closure(
            primary_results, policy=self.escalation_policy
        )
        if not should_esc:
            self.last_escalation_report = EscalationReport(
                triggered=False,
                policy=self.escalation_policy,
                primary_model=getattr(processor, "model_name", None),
            )
            if self.audit:
                assert audit_ctx is not None
                return _return_with_audit(primary_results, audit_ctx)
            return primary_results

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
        esc_legal_text, esc_norm_text, legal_pages, esc_stages = (
            esc_processor.extract_legal_description_from_images(
                str(pdf_path),
                dpi=self.escalation_dpi,
                strip_watermark=self.strip_watermark,
                crop_margins=self.crop_margins,
                audit=self.audit,
                locator_processor=processor,
            )
        )
        esc_output = esc_processor.process_legal_text(
            str(pdf_path),
            legal_desc_text=esc_legal_text,
            normalized_text=esc_norm_text,
            llm_stage_records=esc_stages if self.audit else None,
            audit=self.audit,
        )
        esc_legal_desc, esc_audit_ctx = self._convert_processor_output(esc_output)
        esc_results = _verify_legal_desc(esc_legal_desc, esc_audit_ctx)

        primary_calls = legal_desc.all_calls if legal_desc.tracts else legal_desc.calls
        esc_calls = esc_legal_desc.all_calls if esc_legal_desc.tracts else esc_legal_desc.calls
        disagreements = compare_call_readings(primary_calls, esc_calls)
        selected, selection_reason = select_escalation_outcome(
            primary_calls=primary_calls,
            escalated_calls=esc_calls,
            primary_results=primary_results,
            escalated_results=esc_results,
            disagreements=disagreements,
        )
        report = EscalationReport(
            triggered=True,
            policy=self.escalation_policy,
            trigger_reasons=tuple(trigger_reasons),
            legal_pages=tuple(legal_pages),
            primary_model=getattr(processor, "model_name", None),
            escalation_model=getattr(esc_processor, "model_name", None),
            agrees=not disagreements,
            disagreements=tuple(disagreements),
            selected=selected,
            selection_reason=selection_reason,
        )
        self.last_escalation_report = report

        final_results = esc_results if selected == "escalated" else primary_results
        final_results = _attach_warnings(final_results, report.review_warnings)

        if self.audit:
            final_ctx = esc_audit_ctx if selected == "escalated" else audit_ctx
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
