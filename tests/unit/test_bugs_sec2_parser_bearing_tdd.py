"""Red-Green TDD regression tests for Section 2: Bearing & Parser Edge Cases and Package Parity."""

from __future__ import annotations

import math
import re

import pytest
from mp_bearing import (
    QUADRANT_PATTERN,
    calculate_missing_curve_elements,
    parse_quadrant_bearing,
    quadrant_to_azimuth,
)
from mp_parse import (
    calls as pkg_calls,
)
from mp_parse import (
    metadata as pkg_metadata,
)
from mp_parse import (
    normalizer as pkg_normalizer,
)
from mp_parse import (
    parcels as pkg_parcels,
)
from mp_parse import (
    tracts as pkg_tracts,
)

from metesparser.bearing_converter import BearingConverter
from metesparser.call_extractor import CallExtractor
from metesparser.text_parser import TextParser


def _pkg_extract_calls_flat(text: str, distance_unit: str = "feet", *, strict: bool = True):
    calls, _ = pkg_calls.extract_calls(text, distance_unit=distance_unit, strict=strict)
    return calls


PARSERS = (_pkg_extract_calls_flat, CallExtractor.extract_calls)
NORMALIZERS = (
    pkg_normalizer.expand_assessor_abbreviations,
    TextParser.expand_assessor_abbreviations,
)
DISTANCE_EXTRACTORS = (pkg_metadata.extract_distance, TextParser.extract_distance)
ALONG_TO_EXTRACTORS = (pkg_metadata.extract_along_to_fields, TextParser.extract_along_to_fields)
MEANDER_DETECTORS = (pkg_metadata.detect_meander, TextParser.detect_meander)


# ---------------------------------------------------------------------------
# 1. QUADRANT_PATTERN word boundary & quadrant_to_azimuth validation
# ---------------------------------------------------------------------------


class TestItem1QuadrantPatternAndValidation:
    def test_runs_west_does_not_match_quadrant_pattern(self) -> None:
        assert QUADRANT_PATTERN.search("RUNS 45° WEST") is None
        assert BearingConverter.QUADRANT_PATTERN.search("RUNS 45° WEST") is None
        assert parse_quadrant_bearing("RUNS 45° WEST") is None
        assert BearingConverter.parse_quadrant_bearing("RUNS 45° WEST") is None

    def test_valid_quadrant_with_boundary_still_matches(self) -> None:
        assert parse_quadrant_bearing("N 45°30'15\" E") is not None
        assert BearingConverter.parse_quadrant_bearing("N 45°30'15\" E") is not None

    @pytest.mark.parametrize("fn", [quadrant_to_azimuth, BearingConverter.quadrant_to_azimuth])
    def test_quadrant_to_azimuth_normalizes_whitespace_and_case(self, fn) -> None:
        assert fn(" n ", 45.0, " e ") == pytest.approx(45.0)
        assert fn(" s ", 30.0, " w ") == pytest.approx(210.0)

    @pytest.mark.parametrize("fn", [quadrant_to_azimuth, BearingConverter.quadrant_to_azimuth])
    @pytest.mark.parametrize("bad_deg", [-0.1, 90.1, float("nan"), float("inf"), float("-inf")])
    def test_quadrant_to_azimuth_rejects_invalid_degrees(self, fn, bad_deg: float) -> None:
        with pytest.raises(ValueError):
            fn("N", bad_deg, "E")


# ---------------------------------------------------------------------------
# 2. degree_of_curvature monolith parity
# ---------------------------------------------------------------------------


class TestItem2DegreeOfCurvatureParity:
    def test_monolith_calculate_missing_curve_elements_accepts_degree_of_curvature(self) -> None:
        pkg_res = calculate_missing_curve_elements(degree_of_curvature=2.0, delta_deg=30.0)
        mono_res = BearingConverter.calculate_missing_curve_elements(
            degree_of_curvature=2.0, delta_deg=30.0
        )
        assert mono_res["radius_ft"] == pytest.approx(pkg_res["radius_ft"])
        assert mono_res["arc_length_ft"] == pytest.approx(pkg_res["arc_length_ft"])
        assert mono_res["chord_length_ft"] == pytest.approx(pkg_res["chord_length_ft"])


# ---------------------------------------------------------------------------
# 3. expand_assessor_abbreviations safety
# ---------------------------------------------------------------------------


class TestItem3AssessorNormalizerSafety:
    @pytest.mark.parametrize("fn", NORMALIZERS)
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("NODE", "NODE"),
            ("SOD", "SOD"),
            ("LOT 2D", "LOT 2D"),
            ("LOT 12 SEC 4", "LOT 12 SEC 4"),
            ("THE NODE OF LOT 2D IN SEC 4", "THE NODE OF LOT 2D IN SEC 4"),
        ],
    )
    def test_ordinary_words_and_lot_section_ids_not_corrupted(
        self, fn, text: str, expected: str
    ) -> None:
        assert fn(text) == expected

    @pytest.mark.parametrize("fn", NORMALIZERS)
    def test_real_assessor_patterns_still_work(self, fn) -> None:
        assert "12 degrees 30 minutes" in fn("N 12D 30M E")
        assert "N12E" in fn("N12E")
        assert "S45-30W" in fn("S45-30W")
        assert "degrees" in fn("NODEG 49M E")


# ---------------------------------------------------------------------------
# 4. parcels.py & tracts.py false splits & unification
# ---------------------------------------------------------------------------


class TestItem4ParcelsAndTractsFalseSplits:
    def test_adjoining_parcel_semicolon_does_not_split_parcels_or_tracts(self) -> None:
        text = (
            "BEGINNING at a point; "
            "THENCE N 0°00' E 100.00 feet along the west line of Parcel A; "
            "THENCE S 90°00' E 100.00 feet to a tract a distance of 100 feet; "
            "THENCE S 0°00' W 100.00 feet; "
            "THENCE N 90°00' W 100.00 feet to the point of beginning."
        )
        assert pkg_parcels.detect_parcel_markers(text) == []
        assert len(pkg_parcels.split_into_parcels(text)) == 1
        assert pkg_tracts.find_tract_markers(text) == []
        tracts = pkg_tracts.split_into_tracts(text)
        assert len(tracts) == 1

    def test_dead_common_words_removed_from_tracts(self) -> None:
        assert not hasattr(pkg_tracts, "_COMMON_WORDS")

    def test_tract_no_and_parcel_no_consistent_between_parcels_and_tracts(self) -> None:
        text = (
            "Parcel No. 1 (North): BEGINNING at a pin; THENCE N 0° E 100 feet.\n"
            "Parcel No. 2 (South): BEGINNING at a pin; THENCE S 0° W 100 feet."
        )
        parcel_markers = pkg_parcels.detect_parcel_markers(text)
        tract_markers = pkg_tracts.find_tract_markers(text)
        assert len(parcel_markers) == 2
        assert len(tract_markers) == 2
        assert [m["label"] for m in parcel_markers] == [m[1] for m in tract_markers]


# ---------------------------------------------------------------------------
# 5. mp_parse __init__ exports & Tract metadata
# ---------------------------------------------------------------------------


class TestItem5MpParseExportsAndTractMetadata:
    @pytest.mark.parametrize(
        "symbol",
        [
            "split_into_parcels",
            "detect_parcel_markers",
            "split_into_tracts",
            "find_tract_markers",
            "normalize_legal_description",
            "expand_assessor_abbreviations",
            "extract_calls",
            "extract_single_call",
            "extract_poc_and_pob",
            "extract_area_statement",
            "extract_along_to_fields",
            "detect_meander",
            "classify_monument",
            "classify_monument_status",
        ],
    )
    def test_public_symbols_exported_at_package_root(self, symbol: str) -> None:
        import mp_parse

        assert hasattr(mp_parse, symbol)
        assert symbol in mp_parse.__all__

    def test_extract_calls_preserves_tract_pob_area_and_tie_ins(self) -> None:
        text = (
            "TRACT 1: COMMENCING at an iron rod; "
            "THENCE N 0°00' E 50.00 feet to the POINT OF BEGINNING at an iron pin; "
            "THENCE N 90°00' E 100.00 feet; "
            "THENCE S 0°00' W 100.00 feet; "
            "THENCE N 90°00' W 100.00 feet; "
            "THENCE N 0°00' E 100.00 feet to the POINT OF BEGINNING. "
            "CONTAINING 10,000 square feet. "
            "TRACT 2: BEGINNING at a concrete monument; "
            "THENCE N 90°00' E 50.00 feet; "
            "THENCE S 0°00' W 50.00 feet; "
            "THENCE N 90°00' W 50.00 feet; "
            "THENCE N 0°00' E 50.00 feet to the POINT OF BEGINNING. "
            "CONTAINING 2,500 square feet."
        )
        _, tracts = pkg_calls.extract_calls(text)
        assert len(tracts) == 2
        assert tracts[0].pob_description is not None
        assert "iron pin" in tracts[0].pob_description.lower()
        assert tracts[0].stated_area_sq_ft == pytest.approx(10000.0)
        assert tracts[0].calls[0].is_tie_in is True
        assert all(not c.is_tie_in for c in tracts[0].calls[1:])

        assert tracts[1].pob_description is not None
        assert "concrete monument" in tracts[1].pob_description.lower()
        assert tracts[1].stated_area_sq_ft == pytest.approx(2500.0)


# ---------------------------------------------------------------------------
# 6. Non-tangent radial_bearing must NOT become course azimuth
# ---------------------------------------------------------------------------


class TestItem6RadialBearingNotCourseAzimuth:
    @pytest.mark.parametrize("parse", PARSERS)
    def test_radial_only_nontangent_curve_leaves_course_azimuth_none(self, parse) -> None:
        text = (
            "THENCE along a non-tangent curve to the right, radial line bears N 15°22' E, "
            "radius of 300.00 feet, delta angle of 25°30', arc length of 133.52 feet to an iron pin"
        )
        calls = parse(text)
        assert len(calls) == 1
        call = calls[0]
        assert call.non_tangent is True
        assert call.radial_bearing == "N 15°22' E"
        assert call.bearing_quadrant is None
        assert call.bearing_azimuth_deg_from_north is None

    @pytest.mark.parametrize("parse", PARSERS)
    def test_nontangent_curve_with_radial_and_chord_uses_chord_not_radial(self, parse) -> None:
        text = (
            "THENCE along a non-tangent curve to the right, radial line bears N 15°22' E, "
            "radius of 300.00 feet, delta angle of 25°30', arc length of 133.52 feet, "
            "chord of which bears S 34°57' E to an iron pin"
        )
        calls = parse(text)
        assert len(calls) == 1
        call = calls[0]
        assert call.non_tangent is True
        assert call.radial_bearing == "N 15°22' E"
        assert call.chord_bearing == "S 34°57' E"
        assert call.bearing_azimuth_deg_from_north == pytest.approx(145.05, abs=0.01)


# ---------------------------------------------------------------------------
# 7. Preserve seconds in bearing_quadrant formatting
# ---------------------------------------------------------------------------


class TestItem7PreserveSecondsInBearingQuadrant:
    @pytest.mark.parametrize("parse", PARSERS)
    def test_seconds_preserved_in_bearing_quadrant(self, parse) -> None:
        calls = parse("THENCE N 45°30'15\" E 100.00 feet to an iron pin")
        assert len(calls) == 1
        assert calls[0].bearing_quadrant == "N 45°30'15\" E"

    @pytest.mark.parametrize("parse", PARSERS)
    def test_zero_seconds_omitted_in_bearing_quadrant(self, parse) -> None:
        calls = parse("THENCE N 45°30'00\" E 100.00 feet to an iron pin")
        assert len(calls) == 1
        assert calls[0].bearing_quadrant == "N 45°30' E"


# ---------------------------------------------------------------------------
# 8. Delta + arc-only curves in has_curve
# ---------------------------------------------------------------------------


class TestItem8DeltaAndArcOnlyCurves:
    @pytest.mark.parametrize("parse", PARSERS)
    def test_delta_and_arc_without_radius_parses_curve(self, parse) -> None:
        text = (
            "THENCE along a curve to the right having a delta angle of 90°00' "
            "and an arc length of 157.0796 feet to an iron pin"
        )
        calls = parse(text)
        assert len(calls) == 1
        call = calls[0]
        assert call.curve_dir == "right"
        assert call.delta_deg == pytest.approx(90.0)
        assert call.arc_length_ft == pytest.approx(157.0796)
        assert call.radius_ft == pytest.approx(100.0, abs=0.01)
        assert call.chord_length_ft == pytest.approx(100.0 * math.sqrt(2), abs=0.01)

    @pytest.mark.parametrize(
        "extract_curve", [pkg_calls.extract_curve_info, CallExtractor.extract_curve_info]
    )
    def test_extract_curve_info_computes_radius_from_delta_and_arc_without_dir(
        self, extract_curve
    ) -> None:
        info = extract_curve(
            "curve having a delta angle of 90°00' and an arc length of 157.0796 feet"
        )
        assert info["delta_deg"] == pytest.approx(90.0)
        assert info["arc_length_ft"] == pytest.approx(157.0796)
        assert info["radius_ft"] == pytest.approx(100.0, abs=0.01)
        assert info["chord_length_ft"] == pytest.approx(100.0 * math.sqrt(2), abs=0.01)


# ---------------------------------------------------------------------------
# 9. extract_distance compound guard & COMMA_NUMBER
# ---------------------------------------------------------------------------


class TestItem9ExtractDistanceGuardAndCommaNumber:
    @pytest.mark.parametrize("extract", DISTANCE_EXTRACTORS)
    def test_monument_count_after_and_not_rejected(self, extract) -> None:
        dist, unit = extract("100 feet and 2 concrete monuments")
        assert dist == pytest.approx(100.0)
        assert unit == "feet"

    @pytest.mark.parametrize("parse", PARSERS)
    def test_call_with_monument_count_not_rejected(self, parse) -> None:
        calls = parse("THENCE N 45°00' E 100 feet and 2 concrete monuments")
        assert len(calls) == 1
        assert calls[0].distance_ft == pytest.approx(100.0)

    @pytest.mark.parametrize("extract", DISTANCE_EXTRACTORS)
    def test_compound_inches_still_guarded(self, extract) -> None:
        dist, _ = extract("100 feet and 6 inches")
        assert dist == 0.0

    def test_comma_number_rejects_malformed_commas(self) -> None:
        pkg_re = re.compile(pkg_metadata._COMMA_NUMBER)
        mono_re = re.compile(TextParser._COMMA_NUMBER)
        for pat in (pkg_re, mono_re):
            assert pat.fullmatch("1,200.50") is not None
            assert pat.fullmatch("100") is not None
            assert pat.fullmatch("500,") is None
            assert pat.fullmatch("1,,2") is None


# ---------------------------------------------------------------------------
# 10. extract_along_to_fields & detect_meander false positives
# ---------------------------------------------------------------------------


class TestItem10AlongToAndDetectMeander:
    @pytest.mark.parametrize("fn", ALONG_TO_EXTRACTORS)
    def test_common_to_and_parallel_to_not_split_as_to_endpoint(self, fn) -> None:
        along1, to1 = fn("N 45° E 100 feet along the line common to Lot 4 and Lot 5")
        assert "common to Lot 4 and Lot 5" in along1
        assert to1 == ""

        along2, to2 = fn("N 45° E 100 feet along a line parallel to Oak Street")
        assert "parallel to Oak Street" in along2
        assert to2 == ""

        along3, to3 = fn("N 45° E 100 feet parallel to Oak Street to an iron pin")
        assert along3 == ""
        assert to3 == "an iron pin"

    @pytest.mark.parametrize("fn", MEANDER_DETECTORS)
    @pytest.mark.parametrize(
        "text",
        [
            "N 45° E 100 feet along Lake Avenue",
            "THENCE N 10° E 200 feet along River Road to a pin",
            "THENCE S 80° W 150 feet along Creek Drive",
            "THENCE along Bay Street 100 feet",
            "THENCE along Spring Lane 100 feet",
            "THENCE along the lands of First National Bank 100 feet",
            "THENCE along Chase Bank property 100 feet",
            "THENCE along the property of Bank of America 100 feet",
        ],
    )
    def test_detect_meander_no_false_positives_on_streets_and_banks(self, fn, text: str) -> None:
        assert fn(text) is False

    @pytest.mark.parametrize("fn", MEANDER_DETECTORS)
    @pytest.mark.parametrize(
        "text",
        [
            "meandering along the creek 150 feet",
            "along the bank of the river 200 feet",
            "to the high water mark of the lake",
        ],
    )
    def test_detect_meander_detects_genuine_water_calls(self, fn, text: str) -> None:
        assert fn(text) is True
