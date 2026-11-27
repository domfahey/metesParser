"""Tests for Stage 3 normalization measurement-integrity guard in mp_ocr."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mp_ocr import PDFProcessor, has_legal_measurement_signals, verify_normalization_integrity


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

    def test_accepts_curly_quotes_mixed_fractions_leading_decimals_and_units(self) -> None:
        source = (
            "BEGINNING at a point; "
            "(1) S0uth 45° 12\u2018 and 30\u201c W, 100 1/2 US survey feet; "
            "(2) North 26 deg. 5 9 East, .50 feet along a 50-foot lane; "
            "(3) N 10° 05` 00\" E, 265.21feet and 1/2 foot, 12.5 metres, 4 engineer's chains; "
            "(4) curve right delta 15°30'00\", radius 200.00 feet."
        )
        normalized = (
            "BEGINNING at a point;\n"
            "(1) S 45°12'30\" W, 100.50 U.S. survey feet;\n"
            "(2) N 26°05'09\" E, 0.50 feet along a 50 foot lane;\n"
            "(3) N 10°05'00\" E, 265.21 feet and 0.5 feet, 12.5 meters, 4 engineer's chains;\n"
            "(4) curve right delta 15°30'00\", radius 200.00 feet."
        )
        ok, reasons = verify_normalization_integrity(source, normalized)
        assert ok is True, reasons
        assert reasons == []

    def test_rejects_engineers_chain_collapse_quadrant_flip_curve_flip_and_foot_mark_drift(
        self,
    ) -> None:
        # Engineer's chain (100 ft) must never collapse into Gunter's chain (66 ft)
        ok_eng, _ = verify_normalization_integrity("4 engineer's chains", "4 chains")
        assert ok_eng is False

        # N./S. dotted bearings: valid format normalization passes; 180-deg quadrant flip fails
        assert verify_normalization_integrity("N. 56° 40' 30\" W.", "N 56°40'30\" W")[0] is True
        assert (
            verify_normalization_integrity("N. 56° 40' 30\" W.", "S. 56° 40' 30\" E.")[0] is False
        )

        # Hyphenated DMS, assessor D/M/S, "and" separator, and hyphenated mixed fractions
        assert (
            verify_normalization_integrity(
                "N 56°-40'-30\" W, 100-1/2 feet", "N 56°40'30\" W, 100.5 feet"
            )[0]
            is True
        )
        assert verify_normalization_integrity("N 56-40-30 W", "N 56°40'30\" W")[0] is True
        assert verify_normalization_integrity("S 88D 25M 31S E", "S 88°25'31\" E")[0] is True
        assert (
            verify_normalization_integrity("North 45 degrees and 30 minutes East", "N 45°30' E")[0]
            is True
        )
        assert verify_normalization_integrity("100-1/2 feet", "900-1/2 feet")[0] is False

        # Due cardinal flip, curve direction flip, and foot-mark distance drift
        assert (
            verify_normalization_integrity("Due North 100.00 feet", "Due South 100.00 feet")[0]
            is False
        )
        assert (
            verify_normalization_integrity(
                "curve to the left 50.00 feet", "curve to the right 50.00 feet"
            )[0]
            is False
        )
        assert verify_normalization_integrity("N 10° E 125.26'", "N 10° E 999.99'")[0] is False

        # Cycle 2 regex edge cases: wrapped curve dir, right-of-way exclusion, Oxford comma,
        # trailing period on E./W., hyphen-joined distance, and Unicode prime foot marks
        assert (
            verify_normalization_integrity(
                "curving to the\nleft 50.00 feet", "curving to the\nright 50.00 feet"
            )[0]
            is False
        )
        assert (
            verify_normalization_integrity(
                "along a curve in the right-of-way line 50.00 feet",
                "along a curve in the R/W line 50.00 feet",
            )[0]
            is True
        )
        assert (
            verify_normalization_integrity(
                "North 45 degrees, 12 minutes, and 30 seconds East, 100.00 feet",
                "N 45°12'30\" E, 100.00 feet",
            )[0]
            is True
        )
        assert (
            verify_normalization_integrity(
                "N 45° E., 100.00 feet; N 56-40-30 W., 50.00 feet",
                "N 45° E, 100.00 feet; N 56°40'30\" W, 50.00 feet",
            )[0]
            is True
        )
        assert (
            verify_normalization_integrity(
                "S 45°12'30\" E-125.50 feet",
                "S 45°12'30\" E-999.00 feet",
            )[0]
            is False
        )
        assert (
            verify_normalization_integrity(
                "N 10° E 125.26\u2032; S 10° W 80.10\u2019",
                "N 10° E 999.99\u2032; S 10° W 80.10\u2019",
            )[0]
            is False
        )

    def test_redos_linear_time_and_large_fraction_overflow_safety(self) -> None:
        import time

        from mp_ocr import parse_located_pages

        for hostile in (
            "N 45° 10' 20" + (" " * 5000) + "X",
            "45° 10' 20" + (" " * 5000) + "X",
            "100" + (" " * 5000) + "X",
        ):
            t0 = time.monotonic()
            ok, _ = verify_normalization_integrity(hostile, hostile)
            assert ok is True
            # gstack-timing-ok: O(n^2) ReDoS regression guard on 5000-space hostile input
            assert (time.monotonic() - t0) < 2.0

        t_fence = time.monotonic()
        assert parse_located_pages("```json\n1" + (" " * 10000) + "x", 3) == [1, 2, 3]
        # gstack-timing-ok: O(n^2) fence-strip ReDoS regression guard on 10k-space hostile input
        assert (time.monotonic() - t_fence) < 2.0

        huge_den = f"1/{'9' * 4500} feet"
        ok_big, _ = verify_normalization_integrity(huge_den, huge_den)
        assert ok_big is True

        # Zero-denominator fraction ignored safely
        ok_zero, reasons_zero = verify_normalization_integrity(
            "1/0 feet and 10.00 feet", "10.00 feet"
        )
        assert ok_zero is True and reasons_zero == []

    def test_greedy_seconds_us_survey_feet_areas_unitless_curves_and_formats(self) -> None:
        # Red Team greedy-seconds fix: adjacent distance after comma is NEVER captured as seconds
        src_delta = "curving left, delta 12° 30', 45 feet along the arc"
        assert (
            verify_normalization_integrity(
                src_delta, "curving left, delta 12° 30' 45\", 45 feet along the arc"
            )[0]
            is False
        )
        assert (
            verify_normalization_integrity(
                src_delta, "curving left, delta 12° 30' 00\", 45 feet along the arc"
            )[0]
            is True
        )
        assert (
            verify_normalization_integrity(
                "curving left, delta 12° 30', 45.50' along the arc",
                "curving left, delta 12° 30', 99.50' along the arc",
            )[0]
            is False
        )

        # U.S. Survey Feet must not silently collapse to international feet
        assert (
            verify_normalization_integrity("5000.00 U.S. survey feet", "5000.00 feet")[0] is False
        )

        # Degree-only central/delta angle drift caught
        assert (
            verify_normalization_integrity(
                "delta angle of 45 degrees", "delta angle of 90 degrees"
            )[0]
            is False
        )

        # Unitless labelled curve dimensions (R=, radius of, arc length of) caught & format-tolerant
        assert (
            verify_normalization_integrity(
                "radius of 500, arc length of 120", "radius of 50, arc length of 120"
            )[0]
            is False
        )
        assert (
            verify_normalization_integrity("R = 250.00, L = 120.50", "R = 25.00, L = 120.50")[0]
            is False
        )
        assert verify_normalization_integrity("R = 250.00", "radius of 250.00")[0] is True

        # Stated area drift (acres & square feet) caught
        assert (
            verify_normalization_integrity("containing 2.50 acres", "containing 25.0 acres")[0]
            is False
        )
        assert verify_normalization_integrity("10,500 square feet", "1,500 sq. ft.")[0] is False

        # Curve direction flip beyond 40 chars and "turning to the left/right"
        long_curve_l = "along a curve of the northerly line of Pennbrook Drive having a radius of 200 feet curving to the left"
        long_curve_r = long_curve_l.replace("left", "right")
        assert verify_normalization_integrity(long_curve_l, long_curve_r)[0] is False
        assert (
            verify_normalization_integrity(
                "turning to the left 50 feet", "turning to the right 50 feet"
            )[0]
            is False
        )

        # Integer foot marks, due N, space-separated DMS, deg+sec without min, inches, Unicode fractions,
        # horizontal-only mixed fractions, and cardinal-only swaps
        assert verify_normalization_integrity("N 10° E 100'", "N 10° E 100 feet")[0] is True
        assert verify_normalization_integrity("N 10° E 100'", "N 10° E 180'")[0] is False
        assert verify_normalization_integrity("due N 100 feet", "due North 100 feet")[0] is True
        assert verify_normalization_integrity("due N 100 feet", "due S 100 feet")[0] is False
        assert (
            verify_normalization_integrity("N 45 30 15 E, 100 feet", "N 45°30'15\" E, 100 feet")[0]
            is True
        )
        assert verify_normalization_integrity('N 45° 30" E', 'N 45° 10" E')[0] is False
        assert verify_normalization_integrity("100 feet 6 inches", "100 feet 8 inches")[0] is False
        assert verify_normalization_integrity("100½ feet", "100.5 feet")[0] is True
        assert (
            verify_normalization_integrity("Section 12\n1/2 mile", "Section 12, 0.5 miles")[0]
            is True
        )
        assert (
            verify_normalization_integrity(
                "THENCE northerly 100 feet", "THENCE southerly 100 feet"
            )[0]
            is False
        )

    def test_cycle2_deg_only_eq_backtracking_line_unwrapping_and_linear_unicode_regex(
        self,
    ) -> None:
        import time

        # 1. Degree-only delta with = / : / Δ separator
        assert (
            verify_normalization_integrity(
                "curve to the right, R = 250.00, L = 120.50, delta = 27°",
                "curve to the right, R = 250.00, L = 120.50, delta = 28°",
            )[0]
            is False
        )
        assert verify_normalization_integrity("Δ = 27°", "delta: 27°")[0] is True
        assert verify_normalization_integrity("Δ = 27°", "Δ = 28°")[0] is False

        # 2. No digit backtracking before negative lookaheads (silent bypass & false rejections)
        assert (
            verify_normalization_integrity(
                "curving left, delta 12° 30' 45.50' along the arc",
                "curving left, delta 12° 30' 45.59' along the arc",
            )[0]
            is False
        )
        assert (
            verify_normalization_integrity(
                "curving left, delta 12° 30' 45 feet along the arc",
                "curving left, delta 12° 30' 00\", 45 feet along the arc",
            )[0]
            is True
        )
        assert verify_normalization_integrity("arc of 15°", "arc of 15°00'00\"")[0] is True

        # 3. Stage 3 single-line unwrapping across value/unit, N/S, due, curve label, and area
        assert (
            verify_normalization_integrity(
                "N 45°00'00\" E, 100.50\nfeet", "N 45°00'00\" E, 100.50 feet"
            )[0]
            is True
        )
        assert (
            verify_normalization_integrity(
                "North\n45° 12' 30\" East, 100.00 feet", "N 45°12'30\" E, 100.00 feet"
            )[0]
            is True
        )
        assert verify_normalization_integrity("due\nNorth 50 feet", "due North 50 feet")[0] is True
        assert (
            verify_normalization_integrity("containing 2.50\nacres", "containing 2.50 acres")[0]
            is True
        )
        assert verify_normalization_integrity("10,500 square\nfeet", "10,500 sq. ft.")[0] is True
        assert (
            verify_normalization_integrity("radius of\n250.00 feet", "radius of 250.00 feet")[0]
            is True
        )

        # 4. Unicode fraction regex must remain strictly O(n) on long space/hyphen runs
        t0 = time.monotonic()
        ok_spaces, _ = verify_normalization_integrity(" " * 20_000 + "X", " " * 20_000 + "X")
        ok_hyphens, _ = verify_normalization_integrity("-" * 20_000 + "X", "-" * 20_000 + "X")
        elapsed = time.monotonic() - t0
        assert ok_spaces is True and ok_hyphens is True
        assert elapsed < 1.0, f"Unicode fraction regex backtracking suspected: {elapsed:.3f}s"

        # 5. Sentence-ending periods, comma-grouped curve dimensions, and space-free "sq.ft."
        assert (
            verify_normalization_integrity(
                "Thence along a curve with a radius of 500. Thence N 10° E, 100 ft.",
                "Thence along a curve with a radius of 999. Thence N 10° E, 100 ft.",
            )[0]
            is False
        )
        assert (
            verify_normalization_integrity(
                "Thence along a curve with a radius of 500. Thence N 10° E, 100 ft.",
                "Thence along a curve with a radius of 500; Thence N 10° E, 100 ft.",
            )[0]
            is True
        )
        assert verify_normalization_integrity("R = 1,234.50.", "R = 1,999.99.")[0] is False
        assert (
            verify_normalization_integrity(
                "having a central angle of 45° 30' 15. Thence...",
                "having a central angle of 45° 30' 55. Thence...",
            )[0]
            is False
        )
        assert (
            verify_normalization_integrity(
                "having a central angle of 45° 30' 15. Thence...",
                "having a central angle of 45°30'15\". Thence...",
            )[0]
            is True
        )
        assert (
            verify_normalization_integrity(
                "having a central angle of 45° 30 15. Thence...",
                "having a central angle of 45°30'15\". Thence...",
            )[0]
            is True
        )
        assert (
            verify_normalization_integrity(
                "containing 10,000 sq.ft.", "containing 10,000 square feet"
            )[0]
            is True
        )
        assert (
            verify_normalization_integrity("containing 10,000 sq.ft.", "containing 99,000 sq.ft.")[
                0
            ]
            is False
        )

    def test_detects_standalone_curve_delta_angle_drift(self) -> None:
        source = "Curving right with a central angle of 15°30'00\", radius 200.00 feet."
        drifted = "Curving right with a central angle of 15°31'00\", radius 200.00 feet."
        ok, reasons = verify_normalization_integrity(source, drifted)
        assert ok is False
        assert any("angle_sequence_mismatch" in r for r in reasons)

    def test_rejects_partial_unit_and_malformed_decimal_false_matches(self) -> None:
        # "50 ft.a" and "3.14.5 feet" should not be treated as valid distance measurements
        ok, reasons = verify_normalization_integrity("Ref 50 ft.a and 3.14.5 feet", "clean text")
        assert ok is True
        assert reasons == []

    def test_has_legal_measurement_signals_rejects_stray_cover_sheet_distance(self) -> None:
        assert has_legal_measurement_signals("Property located 500 feet from Main St.") is False
        assert has_legal_measurement_signals("BEGINNING at a pin, 100 feet to corner.") is False
        assert (
            has_legal_measurement_signals(
                "BEGINNING at a pin; THENCE Northerly 100 feet; THENCE Easterly 50 feet."
            )
            is True
        )
        assert has_legal_measurement_signals("N 45°00'00\" E") is True


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
