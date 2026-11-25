"""Pipeline orchestrator that chains all stages."""

from __future__ import annotations

from pathlib import Path

from mp_models import AuditContext, ClosureResult, LegalDescription
from mp_verify import verify_closure

from .models import AuditContext as MonolithAuditContext
from .models import LegalDescription as MonolithLegalDescription
from .package_bridge import package_audit_context, package_legal_description
from .pdf_processor import PDFProcessor


class Pipeline:
    """Chain mp-ocr → mp-parse → mp-verify → mp-export."""

    def __init__(
        self,
        provider: str = "openai",
        *,
        cache: bool = True,
        audit: bool = False,
    ) -> None:
        self.provider = provider
        self.cache = cache
        self.audit = audit

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
        processor = PDFProcessor(provider=self.provider, cache=self.cache)
        result = processor.process_deed_pdf(str(pdf_path), audit=self.audit)

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

        if legal_desc.tracts:
            stated_area: float | None = getattr(legal_desc, "stated_area_sq_ft", None)
            if stated_area is not None:
                results = verify_closure(
                    legal_desc.all_calls,
                    tracts=legal_desc.tracts,
                    stated_area_sq_ft=stated_area,
                    audit_context=audit_ctx,
                )
            else:
                results = verify_closure(
                    legal_desc.all_calls,
                    tracts=legal_desc.tracts,
                    audit_context=audit_ctx,
                )
            if self.audit:
                assert audit_ctx is not None
                return results, audit_ctx
            return results

        closure_result = verify_closure(
            legal_desc.calls,
            stated_area_sq_ft=legal_desc.stated_area_sq_ft or 0.0,
            audit_context=audit_ctx,
        )

        if self.audit:
            assert audit_ctx is not None
            return closure_result, audit_ctx
        return closure_result
