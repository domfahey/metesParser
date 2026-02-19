"""Pipeline orchestrator that chains all stages."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from mp_models import AuditContext, ClosureResult, LegalDescription
from mp_verify import verify_closure

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

        audit_ctx: AuditContext | None = None
        if self.audit:
            assert isinstance(result, tuple)
            legal_desc = cast(LegalDescription, result[0])
            audit_ctx = cast(AuditContext, result[1])
        else:
            assert not isinstance(result, tuple)
            legal_desc = cast(LegalDescription, result)

        if legal_desc.tracts:
            results = verify_closure(
                legal_desc.all_calls,
                tracts=legal_desc.tracts,
                audit_context=audit_ctx,
            )
            if self.audit:
                assert audit_ctx is not None
                return results, audit_ctx
            return results

        closure_result = verify_closure(legal_desc.calls, audit_context=audit_ctx)

        if self.audit:
            assert audit_ctx is not None
            return closure_result, audit_ctx
        return closure_result
