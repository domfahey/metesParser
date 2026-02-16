"""Phase 4: Geometric Completeness tests.

Covers:
- Meander/water boundary detection
- Compound/reverse curve detection
- Missing curve element calculation
- Tie-in call separation
- Indefinite call flagging
"""

from pathlib import Path

import pytest

from metesparser.bearing_converter import BearingConverter
from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker
from metesparser.csv_builder import CSVBuilder
from metesparser.models import DeedCall
from metesparser.text_parser import TextParser


class TestDeedCallPhase4Fields:
    """Tests for new Phase 4 fields on DeedCall."""

    def test_is_meander_default_false(self) -> None:
        call = DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0)
        assert call.is_meander is False

    def test_is_meander_set_true(self) -> None:
        call = DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0, is_meander=True)
        assert call.is_meander is True

    def test_is_tie_in_default_false(self) -> None:
        call = DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0)
        assert call.is_tie_in is False

    def test_is_tie_in_set_true(self) -> None:
        call = DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0, is_tie_in=True)
        assert call.is_tie_in is True

    def test_is_indefinite_default_false(self) -> None:
        call = DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0)
        assert call.is_indefinite is False

    def test_is_indefinite_set_true(self) -> None:
        call = DeedCall(
            course=1, direction_text="southwesterly", distance_ft=100.0, is_indefinite=True
        )
        assert call.is_indefinite is True

    def test_curve_type_default_none(self) -> None:
        call = DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0)
        assert call.curve_type is None

    def test_curve_type_simple(self) -> None:
        call = DeedCall(
            course=1,
            direction_text="N 45° E",
            distance_ft=100.0,
            curve_dir="left",
            radius_ft=200.0,
            delta_deg=30.0,
            curve_type="simple",
        )
        assert call.curve_type == "simple"

    def test_curve_type_compound(self) -> None:
        call = DeedCall(
            course=1,
            direction_text="N 45° E",
            distance_ft=100.0,
            curve_dir="left",
            radius_ft=200.0,
            delta_deg=30.0,
            curve_type="compound",
        )
        assert call.curve_type == "compound"

    def test_curve_type_reverse(self) -> None:
        call = DeedCall(
            course=1,
            direction_text="N 45° E",
            distance_ft=100.0,
            curve_dir="right",
            radius_ft=200.0,
            delta_deg=30.0,
            curve_type="reverse",
        )
        assert call.curve_type == "reverse"

    def test_curve_type_invalid_rejected(self) -> None:
        with pytest.raises(ValueError):
            DeedCall(
                course=1,
                direction_text="N 45° E",
                distance_ft=100.0,
                curve_dir="left",
                radius_ft=200.0,
                delta_deg=30.0,
                curve_type="spiral",
            )


class TestPhase4CSVSchema:
    """Tests for Phase 4 CSV schema changes."""

    def test_fieldnames_count_21(self) -> None:
        assert len(CSVBuilder.FIELDNAMES) == 21

    def test_is_meander_in_fieldnames(self) -> None:
        assert "is_meander" in CSVBuilder.FIELDNAMES

    def test_is_tie_in_in_fieldnames(self) -> None:
        assert "is_tie_in" in CSVBuilder.FIELDNAMES

    def test_is_meander_after_is_exception(self) -> None:
        exc_idx = CSVBuilder.FIELDNAMES.index("is_exception")
        meander_idx = CSVBuilder.FIELDNAMES.index("is_meander")
        assert meander_idx == exc_idx + 1

    def test_is_tie_in_after_is_meander(self) -> None:
        meander_idx = CSVBuilder.FIELDNAMES.index("is_meander")
        tie_in_idx = CSVBuilder.FIELDNAMES.index("is_tie_in")
        assert tie_in_idx == meander_idx + 1

    def test_csv_round_trip_meander(self, tmp_path: Path) -> None:
        output_path = tmp_path / "meander.csv"
        calls = [
            DeedCall(course=1, direction_text="northerly", distance_ft=100.0, is_meander=True),
        ]
        CSVBuilder.calls_to_csv(calls, str(output_path))
        loaded = CSVBuilder.csv_to_calls(str(output_path))
        assert len(loaded) == 1
        assert loaded[0].is_meander is True

    def test_csv_round_trip_tie_in(self, tmp_path: Path) -> None:
        output_path = tmp_path / "tie_in.csv"
        calls = [
            DeedCall(course=1, direction_text="N 45° E", distance_ft=200.0, is_tie_in=True),
        ]
        CSVBuilder.calls_to_csv(calls, str(output_path))
        loaded = CSVBuilder.csv_to_calls(str(output_path))
        assert len(loaded) == 1
        assert loaded[0].is_tie_in is True


# --- Step 3: Meander / Water Boundary Detection ---


class TestDetectMeander:
    """Tests for TextParser.detect_meander()."""

    def test_along_the_creek(self) -> None:
        assert TextParser.detect_meander("along the creek") is True

    def test_along_the_river(self) -> None:
        assert TextParser.detect_meander("along the river") is True

    def test_along_the_stream(self) -> None:
        assert TextParser.detect_meander("along the stream") is True

    def test_with_the_brook(self) -> None:
        assert TextParser.detect_meander("with the brook") is True

    def test_up_the_creek(self) -> None:
        assert TextParser.detect_meander("up the creek") is True

    def test_down_the_river(self) -> None:
        assert TextParser.detect_meander("down the river") is True

    def test_meander_line(self) -> None:
        assert TextParser.detect_meander("meander line along the shore") is True

    def test_meandering(self) -> None:
        assert TextParser.detect_meander("meandering along the shore") is True

    def test_along_the_shore(self) -> None:
        assert TextParser.detect_meander("along the shore") is True

    def test_along_the_pond(self) -> None:
        assert TextParser.detect_meander("along the pond") is True

    def test_along_the_lake(self) -> None:
        assert TextParser.detect_meander("along the lake") is True

    def test_along_the_branch(self) -> None:
        assert TextParser.detect_meander("along the branch") is True

    def test_the_kill(self) -> None:
        assert TextParser.detect_meander("along the kill") is True

    def test_thalweg(self) -> None:
        assert TextParser.detect_meander("along the thalweg") is True

    def test_thread_of_stream(self) -> None:
        assert TextParser.detect_meander("along the thread of the stream") is True

    def test_bank_of_river(self) -> None:
        assert TextParser.detect_meander("along the bank of the river") is True

    def test_run(self) -> None:
        assert TextParser.detect_meander("along the run") is True

    def test_not_meander_road(self) -> None:
        assert TextParser.detect_meander("along the road") is False

    def test_not_meander_lot_line(self) -> None:
        assert TextParser.detect_meander("along the lot line") is False

    def test_not_meander_iron_pin(self) -> None:
        assert TextParser.detect_meander("to an iron pin found") is False

    def test_none_text(self) -> None:
        assert TextParser.detect_meander("") is False

    def test_case_insensitive(self) -> None:
        assert TextParser.detect_meander("ALONG THE CREEK") is True


class TestMeanderClosureWarning:
    """Tests for meander warnings in ClosureChecker."""

    def test_meander_warning_present(self) -> None:
        calls = [
            DeedCall(
                course=1,
                direction_text="N 45° E",
                distance_ft=100.0,
                bearing_azimuth_deg_from_north=45.0,
                is_meander=True,
            ),
            DeedCall(
                course=2,
                direction_text="S 45° E",
                distance_ft=100.0,
                bearing_azimuth_deg_from_north=135.0,
            ),
            DeedCall(
                course=3,
                direction_text="S 45° W",
                distance_ft=100.0,
                bearing_azimuth_deg_from_north=225.0,
            ),
            DeedCall(
                course=4,
                direction_text="N 45° W",
                distance_ft=100.0,
                bearing_azimuth_deg_from_north=315.0,
            ),
        ]
        result = ClosureChecker.verify_closure(calls)
        assert any("meander" in w.lower() for w in result.warnings)

    def test_no_meander_no_warning(self) -> None:
        calls = [
            DeedCall(
                course=1,
                direction_text="N 45° E",
                distance_ft=100.0,
                bearing_azimuth_deg_from_north=45.0,
            ),
            DeedCall(
                course=2,
                direction_text="S 45° E",
                distance_ft=100.0,
                bearing_azimuth_deg_from_north=135.0,
            ),
            DeedCall(
                course=3,
                direction_text="S 45° W",
                distance_ft=100.0,
                bearing_azimuth_deg_from_north=225.0,
            ),
            DeedCall(
                course=4,
                direction_text="N 45° W",
                distance_ft=100.0,
                bearing_azimuth_deg_from_north=315.0,
            ),
        ]
        result = ClosureChecker.verify_closure(calls)
        assert not any("meander" in w.lower() for w in result.warnings)


# --- Step 4: Compound / Reverse Curve Detection ---


class TestCompoundReverseCurveDetection:
    """Tests for compound/reverse curve detection in extract_curve_info()."""

    def test_pcc_keyword(self) -> None:
        text = "curve to the left, radius of 200 feet, delta 30°, point of compound curvature"
        info = CallExtractor.extract_curve_info(text)
        assert info.get("curve_type") == "compound"

    def test_pcc_abbreviation(self) -> None:
        text = "curve to the right, radius of 150 feet, delta 45°, PCC"
        info = CallExtractor.extract_curve_info(text)
        assert info.get("curve_type") == "compound"

    def test_compound_curve_keyword(self) -> None:
        text = "compound curve to the left, radius of 200 feet, delta 30°"
        info = CallExtractor.extract_curve_info(text)
        assert info.get("curve_type") == "compound"

    def test_prc_keyword(self) -> None:
        text = "curve to the right, radius of 200 feet, delta 30°, point of reverse curvature"
        info = CallExtractor.extract_curve_info(text)
        assert info.get("curve_type") == "reverse"

    def test_prc_abbreviation(self) -> None:
        text = "curve to the left, radius of 300 feet, delta 20°, PRC"
        info = CallExtractor.extract_curve_info(text)
        assert info.get("curve_type") == "reverse"

    def test_reverse_curve_keyword(self) -> None:
        text = "reverse curve to the right, radius of 200 feet, delta 30°"
        info = CallExtractor.extract_curve_info(text)
        assert info.get("curve_type") == "reverse"

    def test_simple_curve_no_type(self) -> None:
        text = "curve to the left, radius of 200 feet, delta 30°"
        info = CallExtractor.extract_curve_info(text)
        assert info.get("curve_type") is None

    def test_no_curve_no_type(self) -> None:
        text = "N 45° E 100 feet to an iron pin"
        info = CallExtractor.extract_curve_info(text)
        assert info.get("curve_type") is None


# --- Step 5: Missing Curve Element Calculation ---


class TestCalculateMissingCurveElements:
    """Tests for BearingConverter.calculate_missing_curve_elements()."""

    def test_radius_and_arc_gives_delta_and_chord(self) -> None:
        result = BearingConverter.calculate_missing_curve_elements(
            radius_ft=200.0,
            arc_length_ft=104.72,
        )
        assert result["delta_deg"] == pytest.approx(30.0, abs=0.1)
        assert result["chord_length_ft"] is not None
        assert result["chord_length_ft"] > 0

    def test_radius_and_delta_gives_arc_and_chord(self) -> None:
        result = BearingConverter.calculate_missing_curve_elements(
            radius_ft=200.0,
            delta_deg=30.0,
        )
        assert result["arc_length_ft"] == pytest.approx(104.72, abs=0.1)
        assert result["chord_length_ft"] is not None

    def test_radius_and_chord_gives_delta_and_arc(self) -> None:
        result = BearingConverter.calculate_missing_curve_elements(
            radius_ft=200.0,
            chord_length_ft=103.53,
        )
        assert result["delta_deg"] == pytest.approx(30.0, abs=0.5)
        assert result["arc_length_ft"] is not None

    def test_arc_and_delta_gives_radius_and_chord(self) -> None:
        result = BearingConverter.calculate_missing_curve_elements(
            arc_length_ft=104.72,
            delta_deg=30.0,
        )
        assert result["radius_ft"] == pytest.approx(200.0, abs=0.1)
        assert result["chord_length_ft"] is not None

    def test_chord_and_delta_gives_radius_and_arc(self) -> None:
        result = BearingConverter.calculate_missing_curve_elements(
            chord_length_ft=103.53,
            delta_deg=30.0,
        )
        assert result["radius_ft"] == pytest.approx(200.0, abs=0.5)
        assert result["arc_length_ft"] is not None

    def test_arc_and_zero_delta_raises(self) -> None:
        with pytest.raises(ValueError, match="Delta angle must be non-zero"):
            BearingConverter.calculate_missing_curve_elements(
                arc_length_ft=0.0,
                delta_deg=0.0,
            )

    def test_chord_and_zero_delta_raises(self) -> None:
        with pytest.raises(ValueError, match="Delta angle must be non-zero"):
            BearingConverter.calculate_missing_curve_elements(
                chord_length_ft=10.0,
                delta_deg=0.0,
            )

    def test_all_provided_returns_all(self) -> None:
        result = BearingConverter.calculate_missing_curve_elements(
            radius_ft=200.0,
            delta_deg=30.0,
            arc_length_ft=104.72,
            chord_length_ft=103.53,
        )
        assert result["radius_ft"] == pytest.approx(200.0)
        assert result["delta_deg"] == pytest.approx(30.0)

    def test_insufficient_data_raises(self) -> None:
        with pytest.raises(ValueError, match="at least two"):
            BearingConverter.calculate_missing_curve_elements(radius_ft=200.0)

    def test_no_data_raises(self) -> None:
        with pytest.raises(ValueError, match="at least two"):
            BearingConverter.calculate_missing_curve_elements()

    def test_chord_exceeds_diameter_raises(self) -> None:
        with pytest.raises(ValueError, match="exceeds diameter"):
            BearingConverter.calculate_missing_curve_elements(
                radius_ft=50.0,
                chord_length_ft=150.0,
            )

    def test_tangent_length_calculated(self) -> None:
        result = BearingConverter.calculate_missing_curve_elements(
            radius_ft=200.0,
            delta_deg=30.0,
        )
        assert "tangent_length_ft" in result
        assert result["tangent_length_ft"] == pytest.approx(53.59, abs=0.1)


# --- Step 6: Tie-In Call Separation ---


class TestMarkTieInCalls:
    """Tests for CallExtractor.mark_tie_in_calls()."""

    def test_no_poc_no_marking(self) -> None:
        calls = [
            DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0),
            DeedCall(course=2, direction_text="S 45° E", distance_ft=100.0),
        ]
        result = CallExtractor.mark_tie_in_calls(calls, poc_description=None)
        assert all(not c.is_tie_in for c in result)

    def test_poc_with_pob_terminus(self) -> None:
        calls = [
            DeedCall(
                course=1,
                direction_text="N 45° E",
                distance_ft=100.0,
                to="the point of beginning",
            ),
            DeedCall(course=2, direction_text="S 45° E", distance_ft=100.0),
            DeedCall(course=3, direction_text="S 45° W", distance_ft=100.0),
        ]
        result = CallExtractor.mark_tie_in_calls(
            calls,
            poc_description="NW corner of Section 12",
        )
        assert result[0].is_tie_in is True
        assert result[1].is_tie_in is False
        assert result[2].is_tie_in is False

    def test_multiple_tie_in_calls(self) -> None:
        calls = [
            DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0, to="a point"),
            DeedCall(
                course=2,
                direction_text="S 45° E",
                distance_ft=200.0,
                to="the POB",
            ),
            DeedCall(course=3, direction_text="S 45° W", distance_ft=100.0),
        ]
        result = CallExtractor.mark_tie_in_calls(
            calls,
            poc_description="intersection of Main and Oak",
        )
        assert result[0].is_tie_in is True
        assert result[1].is_tie_in is True
        assert result[2].is_tie_in is False

    def test_empty_poc_no_marking(self) -> None:
        calls = [
            DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0),
        ]
        result = CallExtractor.mark_tie_in_calls(calls, poc_description="")
        assert all(not c.is_tie_in for c in result)

    def test_no_pob_terminus_marks_none(self) -> None:
        calls = [
            DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0, to="an iron pin"),
            DeedCall(course=2, direction_text="S 45° E", distance_ft=100.0, to="a stone"),
        ]
        result = CallExtractor.mark_tie_in_calls(calls, poc_description="NW corner")
        assert all(not c.is_tie_in for c in result)


class TestTieInClosureFiltering:
    """Tests for tie-in call filtering in ClosureChecker."""

    def test_tie_in_calls_excluded_from_closure(self) -> None:
        calls = [
            DeedCall(
                course=1,
                direction_text="N 45° E",
                distance_ft=500.0,
                bearing_azimuth_deg_from_north=45.0,
                is_tie_in=True,
            ),
            DeedCall(
                course=2,
                direction_text="N 45° E",
                distance_ft=100.0,
                bearing_azimuth_deg_from_north=45.0,
            ),
            DeedCall(
                course=3,
                direction_text="S 45° E",
                distance_ft=100.0,
                bearing_azimuth_deg_from_north=135.0,
            ),
            DeedCall(
                course=4,
                direction_text="S 45° W",
                distance_ft=100.0,
                bearing_azimuth_deg_from_north=225.0,
            ),
            DeedCall(
                course=5,
                direction_text="N 45° W",
                distance_ft=100.0,
                bearing_azimuth_deg_from_north=315.0,
            ),
        ]
        result = ClosureChecker.verify_closure(calls)
        assert result.misclosure_ft < 0.01


# --- Step 7: Indefinite Call Flagging ---


class TestIsIndefiniteCall:
    """Tests for TextParser.is_indefinite_call()."""

    def test_northerly_is_indefinite(self) -> None:
        assert TextParser.is_indefinite_call("northerly", has_bearing=False) is True

    def test_southwesterly_is_indefinite(self) -> None:
        assert TextParser.is_indefinite_call("southwesterly", has_bearing=False) is True

    def test_along_road_as_it_runs(self) -> None:
        assert (
            TextParser.is_indefinite_call(
                "along the road as it now runs",
                has_bearing=False,
            )
            is True
        )

    def test_to_top_of_mountain(self) -> None:
        assert (
            TextParser.is_indefinite_call(
                "to the top of the mountain",
                has_bearing=False,
            )
            is True
        )

    def test_down_the_creek(self) -> None:
        assert (
            TextParser.is_indefinite_call(
                "down the creek to the old ford",
                has_bearing=False,
            )
            is True
        )

    def test_precise_bearing_not_indefinite(self) -> None:
        assert (
            TextParser.is_indefinite_call(
                "N 45° E 100 feet",
                has_bearing=True,
            )
            is False
        )

    def test_empty_text(self) -> None:
        assert TextParser.is_indefinite_call("", has_bearing=False) is False

    def test_wardly_suffix_is_indefinite(self) -> None:
        assert TextParser.is_indefinite_call("southwestwardly", has_bearing=False) is True

    def test_cardinal_with_bearing_not_indefinite(self) -> None:
        assert (
            TextParser.is_indefinite_call(
                "northerly",
                has_bearing=True,
            )
            is False
        )


class TestIndefiniteClosureWarning:
    """Tests for indefinite call warnings in ClosureChecker."""

    def test_indefinite_warning_present(self) -> None:
        calls = [
            DeedCall(
                course=1,
                direction_text="northerly",
                distance_ft=100.0,
                is_indefinite=True,
            ),
            DeedCall(
                course=2,
                direction_text="S 45° E",
                distance_ft=100.0,
                bearing_azimuth_deg_from_north=135.0,
            ),
            DeedCall(
                course=3,
                direction_text="S 45° W",
                distance_ft=100.0,
                bearing_azimuth_deg_from_north=225.0,
            ),
        ]
        result = ClosureChecker.verify_closure(calls)
        assert any("indefinite" in w.lower() for w in result.warnings)
