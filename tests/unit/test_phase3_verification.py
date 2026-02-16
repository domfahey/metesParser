"""Phase 3: Enhanced Verification & Parsing tests.

Covers:
- Area statement extraction
- Found/Set monument distinction
- Abbreviation expansion
- Bearing reversal check
- Distance reasonableness check
"""

from pathlib import Path

import pytest

from metesparser.call_extractor import MonumentClassifier
from metesparser.csv_builder import CSVBuilder
from metesparser.models import ConversionFactors, DeedCall, LegalDescription
from metesparser.text_parser import TextParser

# ── Step 1: Area Statement Extraction ──────────────────────────────────────


class TestExtractAreaStatement:
    """Tests for TextParser.extract_area_statement()."""

    def test_square_feet_simple(self) -> None:
        text = "CONTAINING 7,500 square feet"
        result = TextParser.extract_area_statement(text)
        assert result is not None
        assert result["value_sq_ft"] == pytest.approx(7500.0)
        assert result["unit"] == "sq_ft"
        assert result["approximate"] is False

    def test_acres_simple(self) -> None:
        text = "containing 5 acres"
        result = TextParser.extract_area_statement(text)
        assert result is not None
        assert result["value_sq_ft"] == pytest.approx(5 * ConversionFactors.ACRE_TO_SQ_FEET)
        assert result["unit"] == "acres"
        assert result["approximate"] is False

    def test_acres_more_or_less(self) -> None:
        text = "0.1722 acres more or less"
        result = TextParser.extract_area_statement(text)
        assert result is not None
        assert result["value_sq_ft"] == pytest.approx(0.1722 * ConversionFactors.ACRE_TO_SQ_FEET)
        assert result["unit"] == "acres"
        assert result["approximate"] is True

    def test_containing_approximately(self) -> None:
        text = "containing approximately 5 acres"
        result = TextParser.extract_area_statement(text)
        assert result is not None
        assert result["value_sq_ft"] == pytest.approx(5 * ConversionFactors.ACRE_TO_SQ_FEET)
        assert result["approximate"] is True

    def test_sq_ft_abbreviated(self) -> None:
        text = "CONTAINING 7,500 sq ft"
        result = TextParser.extract_area_statement(text)
        assert result is not None
        assert result["value_sq_ft"] == pytest.approx(7500.0)
        assert result["unit"] == "sq_ft"

    def test_sq_ft_with_period(self) -> None:
        text = "CONTAINING 7,500 sq. ft."
        result = TextParser.extract_area_statement(text)
        assert result is not None
        assert result["value_sq_ft"] == pytest.approx(7500.0)

    def test_dual_area_statement(self) -> None:
        text = "CONTAINING 7,500 square feet, or 0.1722 acres, more or less"
        result = TextParser.extract_area_statement(text)
        assert result is not None
        # Should pick up the first area value
        assert result["value_sq_ft"] == pytest.approx(7500.0)
        assert result["approximate"] is True  # "more or less" applies

    def test_no_area_statement(self) -> None:
        text = "THENCE S 56°40' W 125.26 feet to an iron pin"
        result = TextParser.extract_area_statement(text)
        assert result is None

    def test_large_comma_separated_number(self) -> None:
        text = "CONTAINING 1,234,567 square feet"
        result = TextParser.extract_area_statement(text)
        assert result is not None
        assert result["value_sq_ft"] == pytest.approx(1234567.0)

    def test_decimal_acres(self) -> None:
        text = "containing 2.5 acres"
        result = TextParser.extract_area_statement(text)
        assert result is not None
        assert result["value_sq_ft"] == pytest.approx(2.5 * ConversionFactors.ACRE_TO_SQ_FEET)
        assert result["approximate"] is False

    def test_approx_tilde(self) -> None:
        text = "containing ~5 acres"
        result = TextParser.extract_area_statement(text)
        assert result is not None
        assert result["approximate"] is True

    def test_approx_abbreviation(self) -> None:
        text = "containing approx. 3 acres"
        result = TextParser.extract_area_statement(text)
        assert result is not None
        assert result["approximate"] is True


class TestAreaStatementModelFields:
    """Tests for stated_area fields on LegalDescription."""

    def test_stated_area_fields_default_none(self) -> None:
        ld = LegalDescription()
        assert ld.stated_area_sq_ft is None
        assert ld.stated_area_approximate is False

    def test_stated_area_fields_set(self) -> None:
        ld = LegalDescription(stated_area_sq_ft=7500.0, stated_area_approximate=True)
        assert ld.stated_area_sq_ft == 7500.0
        assert ld.stated_area_approximate is True


# ── Step 2: Found/Set Monument Distinction ─────────────────────────────────


class TestClassifyMonumentStatus:
    """Tests for MonumentClassifier.classify_monument_status()."""

    def test_found_keyword(self) -> None:
        assert MonumentClassifier.classify_monument_status("found iron rod") == "found"

    def test_set_keyword(self) -> None:
        assert MonumentClassifier.classify_monument_status("iron pin set") == "set"

    def test_fd_abbreviation(self) -> None:
        assert MonumentClassifier.classify_monument_status("FD iron rod") == "found"

    def test_fnd_abbreviation(self) -> None:
        assert MonumentClassifier.classify_monument_status("FND iron pin") == "found"

    def test_placed_keyword(self) -> None:
        assert MonumentClassifier.classify_monument_status("iron rod placed") == "set"

    def test_none_text(self) -> None:
        assert MonumentClassifier.classify_monument_status(None) is None

    def test_empty_text(self) -> None:
        assert MonumentClassifier.classify_monument_status("") is None

    def test_no_status(self) -> None:
        assert MonumentClassifier.classify_monument_status("iron rod") is None

    def test_case_insensitive(self) -> None:
        assert MonumentClassifier.classify_monument_status("FOUND iron rod") == "found"
        assert MonumentClassifier.classify_monument_status("SET iron pin") == "set"


class TestMonumentStatusOnDeedCall:
    """Tests for monument_status field on DeedCall model."""

    def test_monument_status_default_none(self) -> None:
        call = DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0)
        assert call.monument_status is None

    def test_monument_status_found(self) -> None:
        call = DeedCall(
            course=1, direction_text="N 45° E", distance_ft=100.0, monument_status="found"
        )
        assert call.monument_status == "found"

    def test_monument_status_set(self) -> None:
        call = DeedCall(
            course=1, direction_text="N 45° E", distance_ft=100.0, monument_status="set"
        )
        assert call.monument_status == "set"

    def test_monument_status_invalid_rejected(self) -> None:
        with pytest.raises(ValueError, match="monument_status"):
            DeedCall(
                course=1, direction_text="N 45° E", distance_ft=100.0, monument_status="unknown"
            )


class TestMonumentStatusCSV:
    """Tests for monument_status in CSV schema."""

    def test_fieldnames_count_19(self) -> None:
        assert len(CSVBuilder.FIELDNAMES) == 19

    def test_monument_status_in_fieldnames(self) -> None:
        assert "monument_status" in CSVBuilder.FIELDNAMES

    def test_monument_status_after_monument_type(self) -> None:
        mt_idx = CSVBuilder.FIELDNAMES.index("monument_type")
        ms_idx = CSVBuilder.FIELDNAMES.index("monument_status")
        assert ms_idx == mt_idx + 1

    def test_csv_round_trip_with_monument_status(self, tmp_path: Path) -> None:
        output_path = tmp_path / "monument_calls.csv"

        calls = [
            DeedCall(
                course=1,
                direction_text="N 45° E",
                distance_ft=100.0,
                monument_type="iron_rod",
                monument_status="found",
            ),
        ]
        CSVBuilder.calls_to_csv(calls, str(output_path))
        loaded = CSVBuilder.csv_to_calls(str(output_path))
        assert len(loaded) == 1
        assert loaded[0].monument_status == "found"
