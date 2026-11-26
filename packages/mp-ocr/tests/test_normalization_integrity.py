"""Tests for Stage 3 normalization measurement-integrity guard in mp_ocr."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mp_ocr import PDFProcessor, verify_normalization_integrity


class _StubClient:
    def __init__(self, response: str) -> None:
        self.response = response

    def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
        return self.response

    def generate_text_with_pdf(
        self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
    ) -> str:
        return ""


class TestVerifyNormalizationIntegrity:
    """Unit tests for deterministic Stage 3 bearing and distance verification."""

    def test_accepts_standard_format_only_normalization(self) -> None:
        source = (
            "BEGINNING at a point; "
            "(1) North 56 degrees, 44 minutes, 06 seconds West, 101.58 feet; "
            "(2) South 26 deg. 00 41 East, 120.00 ft. (recorded as South 26 deg. 03 00 East); "
            "(3) 5outh 33 DECREES 20 MINUTES West along sai1 line, 540.25. feet."
        )
        normalized = (
            "BEGINNING at a point;\n"
            "(1) N 56°44'06\" W, 101.58 feet;\n"
            "(2) S 26°00'41\" E, 120.00 feet (recorded as S 26°03'00\" E);\n"
            "(3) S 33°20'00\" W along said line, 540.25 feet."
        )
        ok, reasons = verify_normalization_integrity(source, normalized)
        assert ok is True
        assert reasons == []

    def test_detects_course_order_swap_from_219_berlin_regression(self) -> None:
        source = (
            "(8) North 32 degrees 36 minutes 00 seconds West, 62.57 feet to a point; thence\n"
            "(9) South 56 degrees 44 minutes 06 seconds West, 101.58 feet to a point; thence\n"
            "10) North 32 degrees 36 minutes 00 seconds West, 143.00 feet to a point; thence\n"
            "(11) South 56 degrees 44 minutes 05 seconds West, 140.00 feet to a point."
        )
        swapped = (
            "(8) N 32°36'00\" W, 62.57 feet to a point; thence\n"
            "10) N 32°36'00\" W, 143.00 feet to a point; thence\n"
            "(9) S 56°44'06\" W, 101.58 feet to a point; thence\n"
            "(11) S 56°44'05\" W, 140.00 feet to a point."
        )
        ok, reasons = verify_normalization_integrity(source, swapped)
        assert ok is False
        assert any("bearing_sequence_mismatch" in r for r in reasons)
        assert any("distance_sequence_mismatch" in r for r in reasons)

    def test_detects_dropped_course_and_numeric_drift(self) -> None:
        source = "(1) N 32°36'00\" W, 62.57 feet;\n(2) S 56°44'06\" W, 101.58 feet."
        dropped = "(1) N 32°36'00\" W, 62.57 feet."
        drifted_bearing = "(1) N 32°36'00\" W, 62.57 feet;\n(2) S 56°44'05\" W, 101.58 feet."
        drifted_distance = "(1) N 32°36'00\" W, 62.57 feet;\n(2) S 56°44'06\" W, 101.59 feet."

        assert verify_normalization_integrity(source, dropped)[0] is False
        assert verify_normalization_integrity(source, drifted_bearing)[0] is False
        assert verify_normalization_integrity(source, drifted_distance)[0] is False

    def test_detects_empty_normalized_output(self) -> None:
        ok, reasons = verify_normalization_integrity("BEGINNING at a point;", "   ")
        assert ok is False
        assert reasons == ["empty_normalized_output"]

    def test_allows_non_measurement_stub_text(self) -> None:
        ok, reasons = verify_normalization_integrity("BEGINNING at pin", "normalized text")
        assert ok is True
        assert reasons == []


class TestPDFProcessorNormalizationGuard:
    """PDFProcessor falls back to Stage 2 text while preserving audit evidence."""

    def test_falls_back_to_stage2_on_swap_and_keeps_raw_llm_stage_record(
        self, tmp_path: Path
    ) -> None:
        source = (
            "(9) South 56 degrees 44 minutes 06 seconds West, 101.58 feet;\n"
            "10) North 32 degrees 36 minutes 00 seconds West, 143.00 feet."
        )
        swapped = "10) N 32°36'00\" W, 143.00 feet;\n(9) S 56°44'06\" W, 101.58 feet."
        processor = PDFProcessor(client=_StubClient(swapped), cache=False)
        result = processor.normalize_legal_description(source, audit=True)

        assert result == source
        ctx: Any = processor._build_audit_context(
            pdf_path=str(tmp_path / "deed.pdf"),
            legal_desc_text=source,
            normalized_text=result,
            distance_unit="feet",
        )
        assert ctx.extraction_record.normalized_text == source
        assert len(ctx.extraction_record.llm_stages) == 1
        assert ctx.extraction_record.llm_stages[0].stage == "normalize_text"
        assert ctx.extraction_record.llm_stages[0].response == swapped

    def test_returns_normalized_text_when_measurements_match(self) -> None:
        source = "(1) South 56 degrees 44 minutes 06 seconds West, 101.58 feet."
        normalized = "(1) S 56°44'06\" W, 101.58 feet."
        processor = PDFProcessor(client=_StubClient(normalized), cache=False)
        assert processor.normalize_legal_description(source) == normalized
