"""Pipeline orchestrator that chains all stages."""

from __future__ import annotations

from pathlib import Path

from mp_models import ClosureResult, LegalDescription
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

    def run(self, pdf_path: Path) -> ClosureResult:
        """Run the full pipeline on a PDF.

        Args:
            pdf_path: Path to the deed PDF file.

        Returns:
            ClosureResult with verification status, misclosure, and area.
        """
        processor = PDFProcessor(provider=self.provider, cache=self.cache)
        result = processor.process_deed_pdf(str(pdf_path), audit=self.audit)

        if self.audit:
            legal_desc, _audit_ctx = result
        else:
            legal_desc = result  # type: ignore[assignment]

        assert isinstance(legal_desc, LegalDescription)
        closure_result = verify_closure(legal_desc.calls)
        return closure_result
