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
from metesparser.closure_checker import ClosureChecker
from metesparser.csv_builder import CSVBuilder
from metesparser.models import ConversionFactors, DeedCall, LegalDescription
from metesparser.text_parser import TextParser


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
        assert result["value_sq_ft"] == pytest.approx(7500.0)
        assert result["approximate"] is True

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

    def test_fieldnames_count_22(self) -> None:
        assert len(CSVBuilder.FIELDNAMES) == 22

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


class TestExpandAbbreviations:
    """Tests for TextParser.expand_abbreviations()."""

    @pytest.mark.parametrize(
        "abbrev, expected",
        [
            ("IPF", "iron pin found"),
            ("IPS", "iron pin set"),
            ("IRF", "iron rod found"),
            ("IRS", "iron rod set"),
            ("CIP", "capped iron pin"),
            ("CMP", "concrete monument placed"),
            ("R/W", "right-of-way"),
            ("ROW", "right-of-way"),
            ("N/F", "now or formerly"),
            ("PK", "pk nail"),
        ],
    )
    def test_single_abbreviation(self, abbrev: str, expected: str) -> None:
        result = TextParser.expand_abbreviations(f"to an {abbrev} in concrete")
        assert expected in result.lower()

    def test_con_mon_f(self) -> None:
        result = TextParser.expand_abbreviations("to a Con Mon F")
        assert "concrete monument found" in result.lower()

    def test_case_insensitive(self) -> None:
        result = TextParser.expand_abbreviations("to an ipf in concrete")
        assert "iron pin found" in result.lower()

    def test_multiple_abbreviations(self) -> None:
        result = TextParser.expand_abbreviations("from IPF along R/W to IRS")
        assert "iron pin found" in result.lower()
        assert "right-of-way" in result.lower()
        assert "iron rod set" in result.lower()

    def test_no_abbreviations(self) -> None:
        text = "along the southerly line to an iron pin"
        result = TextParser.expand_abbreviations(text)
        assert result == text

    def test_wired_into_normalize(self) -> None:
        text = "THENCE S 45° E 100 feet to an IPF"
        result = TextParser.normalize_legal_description(text)
        assert "iron pin found" in result.lower()


def _make_call(course: int, azimuth: float, distance: float = 100.0) -> DeedCall:
    """Helper to create a DeedCall with specific azimuth."""
    return DeedCall(
        course=course,
        direction_text=f"bearing {azimuth}",
        bearing_azimuth_deg_from_north=azimuth,
        distance_ft=distance,
    )


class TestCheckBearingReversals:
    """Tests for ClosureChecker.check_bearing_reversals()."""

    def test_exact_180_degree_reversal(self) -> None:
        calls = [_make_call(1, 45.0), _make_call(2, 225.0)]
        warnings = ClosureChecker.check_bearing_reversals(calls)
        assert len(warnings) == 1
        assert "1" in warnings[0] and "2" in warnings[0]

    def test_within_5_degree_threshold(self) -> None:
        calls = [_make_call(1, 45.0), _make_call(2, 228.0)]
        warnings = ClosureChecker.check_bearing_reversals(calls)
        assert len(warnings) == 1

    def test_outside_threshold_no_warning(self) -> None:
        calls = [_make_call(1, 45.0), _make_call(2, 235.0)]
        warnings = ClosureChecker.check_bearing_reversals(calls)
        assert len(warnings) == 0

    def test_non_adjacent_no_warning(self) -> None:
        calls = [_make_call(1, 45.0), _make_call(2, 90.0), _make_call(3, 225.0)]
        warnings = ClosureChecker.check_bearing_reversals(calls)
        assert len(warnings) == 0

    def test_single_call_no_warning(self) -> None:
        calls = [_make_call(1, 45.0)]
        warnings = ClosureChecker.check_bearing_reversals(calls)
        assert len(warnings) == 0

    def test_none_azimuth_skipped(self) -> None:
        call_with_none = DeedCall(course=2, direction_text="southwesterly", distance_ft=100.0)
        calls = [_make_call(1, 45.0), call_with_none, _make_call(3, 225.0)]
        warnings = ClosureChecker.check_bearing_reversals(calls)
        assert len(warnings) == 0

    def test_normal_polygon_no_warnings(self) -> None:
        calls = [
            _make_call(1, 0.0),
            _make_call(2, 90.0),
            _make_call(3, 180.0),
            _make_call(4, 270.0),
        ]
        warnings = ClosureChecker.check_bearing_reversals(calls)
        assert len(warnings) == 0

    def test_warning_message_includes_courses(self) -> None:
        calls = [_make_call(1, 0.0), _make_call(2, 180.0)]
        warnings = ClosureChecker.check_bearing_reversals(calls)
        assert len(warnings) == 1
        assert "reversal" in warnings[0].lower() or "180" in warnings[0]


class TestCheckDistanceReasonableness:
    """Tests for ClosureChecker.check_distance_reasonableness()."""

    def test_short_distance_warning(self) -> None:
        calls = [
            _make_call(1, 0.0, distance=0.3),
            _make_call(2, 90.0, distance=100.0),
            _make_call(3, 180.0, distance=100.0),
        ]
        warnings = ClosureChecker.check_distance_reasonableness(calls)
        assert any("short" in w.lower() for w in warnings)

    def test_long_distance_warning(self) -> None:
        calls = [
            _make_call(1, 0.0, distance=100.0),
            _make_call(2, 90.0, distance=100.0),
            _make_call(3, 180.0, distance=1500.0),
        ]
        warnings = ClosureChecker.check_distance_reasonableness(calls)
        assert any("long" in w.lower() or "10x" in w.lower() for w in warnings)

    def test_perimeter_dominance_warning(self) -> None:
        calls = [
            _make_call(1, 0.0, distance=950.0),
            _make_call(2, 90.0, distance=25.0),
            _make_call(3, 180.0, distance=25.0),
        ]
        warnings = ClosureChecker.check_distance_reasonableness(calls)
        assert any("90%" in w or "perimeter" in w.lower() for w in warnings)

    def test_normal_distances_no_warnings(self) -> None:
        calls = [
            _make_call(1, 0.0, distance=100.0),
            _make_call(2, 90.0, distance=120.0),
            _make_call(3, 180.0, distance=100.0),
            _make_call(4, 270.0, distance=120.0),
        ]
        warnings = ClosureChecker.check_distance_reasonableness(calls)
        assert len(warnings) == 0

    def test_single_call_no_warnings(self) -> None:
        calls = [_make_call(1, 0.0, distance=100.0)]
        warnings = ClosureChecker.check_distance_reasonableness(calls)
        assert len(warnings) == 0

    def test_two_calls_works(self) -> None:
        calls = [
            _make_call(1, 0.0, distance=100.0),
            _make_call(2, 90.0, distance=100.0),
        ]
        warnings = ClosureChecker.check_distance_reasonableness(calls)
        assert len(warnings) == 0

    def test_all_same_distance_no_warnings(self) -> None:
        calls = [
            _make_call(1, 0.0, distance=100.0),
            _make_call(2, 90.0, distance=100.0),
            _make_call(3, 180.0, distance=100.0),
        ]
        warnings = ClosureChecker.check_distance_reasonableness(calls)
        assert len(warnings) == 0

    def test_warning_includes_course_number(self) -> None:
        calls = [
            _make_call(1, 0.0, distance=0.1),
            _make_call(2, 90.0, distance=100.0),
            _make_call(3, 180.0, distance=100.0),
        ]
        warnings = ClosureChecker.check_distance_reasonableness(calls)
        assert any("1" in w for w in warnings)
