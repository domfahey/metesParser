"""Monolith parity tests for Stage 3 normalization measurement-integrity guard."""

from __future__ import annotations

from metesparser.pdf_processor import PDFProcessor as MonolithPDFProcessor


class _StubClient:
    def __init__(self, response: str) -> None:
        self.response = response

    def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
        return self.response

    def generate_text_with_pdf(
        self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
    ) -> str:
        return ""


def test_monolith_normalize_falls_back_to_stage2_on_course_swap() -> None:
    source = (
        "(9) South 56 degrees 44 minutes 06 seconds West, 101.58 feet;\n"
        "10) North 32 degrees 36 minutes 00 seconds West, 143.00 feet."
    )
    swapped = "10) N 32°36'00\" W, 143.00 feet;\n(9) S 56°44'06\" W, 101.58 feet."
    processor = MonolithPDFProcessor(client=_StubClient(swapped), cache=False)
    assert processor.normalize_legal_description(source) == source


def test_monolith_normalize_returns_clean_normalized_output() -> None:
    source = "(1) North 32 degrees 36 minutes 00 seconds West, 143.00 feet."
    normalized = "(1) N 32°36'00\" W, 143.00 feet."
    processor = MonolithPDFProcessor(client=_StubClient(normalized), cache=False)
    assert processor.normalize_legal_description(source) == normalized
