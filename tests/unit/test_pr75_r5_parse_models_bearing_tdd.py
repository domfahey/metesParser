"""Strict Red-Green TDD regressions for PR #75 R5 (Track 1: parse, models, bearing)."""

from __future__ import annotations

import io
import json
import logging
import time
from typing import Any

import mp_bearing
import mp_models
import pytest
from mp_models import INVALID_STATED_AREA_NOTE_PREFIX, split_notes
from mp_models.base import _NoBoolFloatModel
from mp_models.envelope import ClosureResultMessage, RawTextMessage, _Message, parse_message
from mp_parse import metadata as mp_metadata
from mp_parse.calls import (
    _attach_invalid_stated_area_note,
    _uncovered_text_gaps,
    extract_calls,
    extract_curve_info,
)
from mp_parse.metadata import (
    _has_malformed_foot_mark,
    extract_area_statement,
    extract_distance,
    extract_plss_metadata,
    extract_pob,
    extract_prior_conveyance,
    extract_subdivision_reference,
    extract_witness_trees,
    is_abbreviation_period,
    read_course_length,
)
from mp_parse.normalizer import (
    clean_ocr_errors,
    expand_assessor_abbreviations,
    normalize_legal_description,
    split_comma_joined_courses,
    standardize_cardinal_directions,
)
from mp_parse.parcels import detect_parcel_markers, split_into_parcels
from mp_review.api import review_text
from mp_verify import verify_closure
from pydantic import ValidationError

from metesparser import models as monolith_models
from metesparser.bearing_converter import BearingConverter

MODEL_IMPLS = [("package", mp_models), ("monolith", monolith_models)]
BEARING_IMPLS = [("package", mp_bearing), ("monolith", BearingConverter)]


# ---------------------------------------------------------------------------
# 1. Replace _TH_COURSE_STARTER allowlist with OCR-split denylist + qualified survey refs
# ---------------------------------------------------------------------------


class TestThOcrSplitDenylistAndSurveyRefs:
    def test_th_in_the_northerly_direction_not_dropped_into_preamble(self) -> None:
        deed = (
            "BEG TH IN THE NORTHERLY DIRECTION 100FT, "
            "TH N 0D 00M 00S E 100FT, "
            "TH N 90D 00M 00S E 100FT, "
            "TH S 0D 00M 00S W 100FT, "
            "TH N 90D 00M 00S W 100FT POB"
        )
        normalized = normalize_legal_description(deed)
        assert "thence in the northerly direction" in normalized.lower()

        calls, _ = extract_calls(normalized)
        assert len(calls) == 5
        assert calls[0].bearing_azimuth_deg_from_north is None

        closure = verify_closure(calls)
        assert not closure.is_fully_verified()

        result = review_text(deed)
        assert result["status"] == "needs_review"
        assert len(result["calls"]) == 5

    def test_th_the_curve_and_reverse_curve_and_parallel_expand_and_extract(self) -> None:
        curve_deed = "BEG TH THE CURVE TO THE RIGHT RADIUS 50FT ARC LENGTH 20FT TH N0D E 100FT"
        calls, _ = extract_calls(normalize_legal_description(curve_deed))
        assert len(calls) == 2
        assert calls[0].curve_dir == "right"
        assert calls[0].radius_ft == pytest.approx(50.0)
        assert calls[0].arc_length_ft == pytest.approx(20.0)

        parallel_deed = "TH PARALLEL WITH SAID LINE N0D E 50FT TH N0D E 100FT"
        p_calls, _ = extract_calls(normalize_legal_description(parallel_deed))
        assert len(p_calls) == 2
        assert p_calls[0].distance_ft == pytest.approx(50.0)
        assert p_calls[1].distance_ft == pytest.approx(100.0)

        rev_deed_shorthand = (
            "BEG AT PIN TH REVERSE CURVE TO RIGHT R 100FT DELTA 90D ARC 157.08FT "
            "TH N 90D W 100FT POB"
        )
        rev_norm = normalize_legal_description(rev_deed_shorthand)
        assert "thence reverse curve" in rev_norm.lower()
        # Shorthand curve course is retained (not silently dropped into preamble) and fails closed.
        with pytest.raises(ValueError, match="Malformed course 1"):
            extract_calls(rev_norm, strict=True)
        skipped: list[mp_models.SkippedCourse] = []
        r_non_strict, _ = extract_calls(rev_norm, strict=False, skipped_courses=skipped)
        assert len(skipped) == 1
        assert skipped[0].course == 1
        assert len(r_non_strict) == 1
        assert review_text(rev_deed_shorthand)["status"] == "error"

        rev_deed_full = (
            "BEG AT PIN TH REVERSE CURVE TO THE RIGHT RADIUS 100FT DELTA 90D ARC 157.08FT "
            "TH N 90D W 100FT POB"
        )
        r_calls, _ = extract_calls(normalize_legal_description(rev_deed_full))
        assert len(r_calls) == 2
        assert r_calls[0].curve_type == "reverse"
        assert r_calls[0].radius_ft == pytest.approx(100.0)
        assert r_calls[0].delta_deg == pytest.approx(90.0)

    @pytest.mark.parametrize(
        "text",
        [
            "BEG TH 100 FT N 45 E",
            "BEG TH FROM SAID PIN N 45 E 100 FT",
            "BEG TH PASSING AN IRON PIN N 45 E 100 FT",
            "BEG TH (1) N 45 E 100 FT",
            "BEG TH S'LY 100 FT",
            "BEG AT NE COR LOT NO 4 TH N0D E 100FT",
            "BEG AT NE COR LOT NO. 4 TH N0D E 100FT",
            "BEG AT NE COR LOT NO 4 TH PARALLEL WITH SAID LINE 100FT",
            "BEG AT NE COR LOT NO. 4 TH PARALLEL WITH SAID LINE 100FT",
            "BEG AT NE COR LOT NUMBER 4 TH PARALLEL WITH SAID LINE 100FT",
            "TRACT #2 TH S 45D E 100FT",
            "TRACT #2 TH IN THE NORTHERLY DIRECTION 100FT",
            "FROM POINT 12 TH N 45 E 100FT",
            "BEG AT POINT 12 TH IN THE NORTHERLY DIRECTION 100FT",
            "BEG AT STATION 5 TH IN THE EASTERLY DIRECTION 100FT",
            "BEG AT REBAR 3 TH IN THE WESTERLY DIRECTION 100FT",
            "BEG TH E ALONG SAID LINE 100FT",
            "BEG TH E. ALONG SAID LINE 100FT",
            "BEG TH E 100FT",
            "BEG TH E, 100FT",
            "BEG TH E 100FT ALONG ALLEY",
            "BEG TH E",
            "BEG TH AT 45° 100FT",
            "BEG TH AT 45 DEG 100FT",
            "BEG TH AT 45D 100FT",
            "BEG TH AT A RIGHT ANGLE 100FT",
            "BEG TH AT RIGHT ANGLES 100FT",
            "BEG TH AT AN ANGLE OF 30° 100FT",
            "BEG AT PIN Th. N 45° E 100FT",
            "BEG AT PIN Th. North 45° E 100FT",
            "BEG AT PIN Th. Northerly 100FT",
            "BEG AT PIN Th. Due East 100FT",
        ],
    )
    def test_valid_th_courses_and_qualified_survey_refs_expand(self, text: str) -> None:
        out = expand_assessor_abbreviations(text)
        assert "thence " in out.lower()

    @pytest.mark.parametrize(
        "text",
        [
            "4 TH STREET",
            "20 th day",
            "5 TH AVENUE",
            "3 TH LINE",
            "10 TH TO 12 TH",
            "ALONG TH E LINE",
            "TO TH E CORNER",
            "TO TH E POINT",
            "TO TH AT CORNER",
            "OF TH IS TRACT",
            "PART TH EREOF",
            "LYING TH EREIN",
            "FROM TH ERE",
            "AS TH EY RUN",
            "AND TH EN RUNS",
            "RUNS TH ENCE",
            "MORE TH AN 10",
            "ALL TH OSE LOTS",
            "ALL TH ESE LANDS",
            "TO TH EM",
            "ON TH EIR LINE",
            "RUNS TH ROUGH WOODS",
            "PASSING TH ROU LOT",
            "AND TH US BOUNDED",
            "ANY TH ING ELSE",
            "AL TH OUGH SHOWN",
            "BEING TH IRTY FEET",
            "BEING TH IRTEEN FEET",
            "BEING TH REE ACRES",
            "BEING TH IRD LOT",
            "ONE TH OUSAND FEET",
            "along TH E 20 foot alley to a pin",
            "to lands of Th. Smith",
            "on TH E line",
            "in TH E northerly line",
            "TH E 20 foot alley to a pin",
            "TH E 10 ft strip",
            "TH E 30 foot easement",
            "TH E 25 ft. st.",
            "TH AT 50 feet",
            "TO TH AT 50 feet point",
            "conveyed to Th. Smith",
            "Th. Jones, Grantor",
            "Th. A. Smith",
        ],
    )
    def test_ocr_word_splits_and_ordinals_stay_unexpanded(self, text: str) -> None:
        out = expand_assessor_abbreviations(text)
        assert "thence" not in out.lower()

    def test_point_12_th_incomplete_bearing_fails_closed(self) -> None:
        deed = (
            "BEG AT POINT 12 TH IN THE NORTHERLY DIRECTION 100FT, "
            "TH N 0D 00M 00S E 100FT, "
            "TH N 90D 00M 00S E 100FT, "
            "TH S 0D 00M 00S W 100FT, "
            "TH N 90D 00M 00S W 100FT POB"
        )
        result = review_text(deed)
        assert result["status"] == "needs_review"
        assert len(result["calls"]) == 5
        assert result["calls"][0]["bearing_azimuth_deg_from_north"] is None

    def test_th_e_20_foot_alley_does_not_fabricate_phantom_east_course(self) -> None:
        deed = (
            "BEGINNING at a pin; "
            "THENCE N 0°00'00\" E 100.00 feet along TH E 20 foot alley to a pin; "
            "THENCE N 90°00'00\" E 100.00 feet; "
            "THENCE S 0°00'00\" W 100.00 feet; "
            "THENCE N 90°00'00\" W 100.00 feet to the point of beginning."
        )
        normalized = normalize_legal_description(deed)
        assert "due east" not in normalized.lower()
        assert normalized.lower().count("thence ") == 4
        # Without "wide", the OCR-broken "TH E 20 foot alley" fails closed instead of
        # fabricating a phantom due East 20 ft course.
        res = review_text(deed)
        assert res["status"] != "checks_passed"
        assert not any(
            c.get("direction_text", "").lower() == "due east" for c in res.get("calls", [])
        )

        # With "wide", the width modifier is recognised and exactly 4 courses extract.
        deed_wide = deed.replace("20 foot alley", "20 foot wide alley")
        calls, _ = extract_calls(normalize_legal_description(deed_wide))
        assert len(calls) == 4

    def test_th_standalone_east_no_redos_backtracking(self) -> None:
        adversarial = "BEG TH E" + (" " * 25000) + "X"
        start = time.perf_counter()
        out = expand_assessor_abbreviations(adversarial)
        elapsed = time.perf_counter() - start
        assert elapsed < 0.5
        assert "thence" not in out.lower()

    def test_north_south_symbol_dms_sentence_and_comma_course_splitting(self) -> None:
        sentence_split = split_comma_joined_courses(
            "100 feet to a point. North 0°00'00\" East 100 feet"
        )
        assert ". thence North 0°00'00\" East 100 feet" in sentence_split

        comma_split = split_comma_joined_courses(
            "85.33 feet, North 0°00'00\" East, 100.0 feet; thence"
        )
        assert " thence North 0°00'00\" East, 100.0 feet" in comma_split

        deed_sentence = (
            "BEGINNING at a pin; "
            "THENCE North 0°00'00\" East 100.00 feet to a point. "
            "North 90°00'00\" East 100.00 feet to a point. "
            "South 0°00'00\" West 100.00 feet to a point. "
            "North 90°00'00\" West 100.00 feet to the point of beginning."
        )
        calls, _ = extract_calls(normalize_legal_description(deed_sentence))
        assert len(calls) == 4
        assert [c.distance_ft for c in calls] == pytest.approx([100.0, 100.0, 100.0, 100.0])

        deed_comma = (
            "BEGINNING at a pin; "
            "THENCE South 16°54'36\" West, 85.33 feet, "
            "North 73°05'24\" West, 128.0 feet; "
            "THENCE North 16°54'36\" East, 85.33 feet to the point of beginning."
        )
        comma_calls, _ = extract_calls(normalize_legal_description(deed_comma))
        assert [c.distance_ft for c in comma_calls] == pytest.approx([85.33, 128.0, 85.33])

        # standardize_cardinal_directions must still leave North/South symbol-DMS verbatim
        assert standardize_cardinal_directions("North 45°East") == "North 45°East"


# ---------------------------------------------------------------------------
# 2. Hybrid bearings ("N 45° East") and prose corruption guard
# ---------------------------------------------------------------------------


class TestHybridBearingsAndProseGuard:
    @pytest.mark.parametrize("_name,bearing_api", BEARING_IMPLS)
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("N 45° East", ("N", 45.0, "E")),
            ("N 45°30' East", ("N", 45.5, "E")),
            ("S 56°40'30\" West", ("S", 56.675, "W")),
            ("North 45° East", ("N", 45.0, "E")),
            ("South 30° W", ("S", 30.0, "W")),
            ("N 45° E100 feet", ("N", 45.0, "E")),
            ("N45°E100FT", ("N", 45.0, "E")),
        ],
    )
    def test_parse_quadrant_bearing_accepts_hybrid_and_compact_forms(
        self, _name: str, bearing_api: Any, text: str, expected: tuple[str, float, str]
    ) -> None:
        parsed = bearing_api.parse_quadrant_bearing(text)
        assert parsed is not None
        assert parsed[0] == expected[0]
        assert parsed[1] == pytest.approx(expected[1])
        assert parsed[2] == expected[2]

    @pytest.mark.parametrize("_name,bearing_api", BEARING_IMPLS)
    @pytest.mark.parametrize(
        "bad",
        [
            "N 45° End",
            "N 45° Easterly",
            "S 30° Westward",
            "runs 45° East",
            "turns 45°30' east",
            "bearing is 45°30' W",
        ],
    )
    def test_parse_quadrant_bearing_rejects_words_and_prose(
        self, _name: str, bearing_api: Any, bad: str
    ) -> None:
        assert bearing_api.parse_quadrant_bearing(bad) is None

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("N 45° East", "N 45° E"),
            ("N 45°30' East", "N 45°30' E"),
            ("S 56°40'30\" West", "S 56°40'30\" W"),
            ("North 45° East", "North 45° East"),
            ("South 30°15' W", "South 30°15' W"),
        ],
    )
    def test_standardize_cardinal_directions_normalizes_hybrid_bearings(
        self, raw: str, expected: str
    ) -> None:
        assert standardize_cardinal_directions(raw) == expected

    @pytest.mark.parametrize(
        "prose",
        [
            "runs 45° East",
            "turns 45°30' east",
            "deflection 30° West",
            "bearing is 45°30' W",
            "bears 45° East",
            "N 45° End",
            "N 45° Easterly",
        ],
    )
    def test_standardize_cardinal_directions_does_not_corrupt_prose(self, prose: str) -> None:
        assert standardize_cardinal_directions(prose) == prose

    def test_clean_ocr_errors_respects_boundaries(self) -> None:
        assert clean_ocr_errors("N 45 0 30' E") == "N 45°30' E"
        assert clean_ocr_errors("runs 45 0 30' E") == "runs 45 0 30' E"
        assert clean_ocr_errors("N 45 0 30' End") == "N 45 0 30' End"

    def test_expand_assessor_d_supports_hybrid_full_words_and_guards_lot(self) -> None:
        assert normalize_legal_description("THENCE N 45D East 100FT") == "THENCE N 45° E 100 feet"
        assert normalize_legal_description("THENCE North 45D E 100FT") == "THENCE N 45° E 100 feet"
        assert expand_assessor_abbreviations("LOT 2D") == "LOT 2D"
        assert expand_assessor_abbreviations("runs 45D East") == "runs 45D East"


# ---------------------------------------------------------------------------
# 3. Non-positive stated area extraction & attachment
# ---------------------------------------------------------------------------


class TestNonPositiveStatedAreaExtractionAndAttachment:
    @pytest.mark.parametrize(
        ("text", "expected_sq_ft"),
        [
            ("containing -10000 sq. ft.", -10000.0),
            ("containing -5 acres", -5.0 * 43560.0),
            ("containing -.5 acres", -0.5 * 43560.0),
            ("containing -½ acres", -0.5 * 43560.0),
            ("containing -¼ sq. ft.", -0.25),
            ("containing \u2212¾ acres", -0.75 * 43560.0),
            ("-½ acres", -0.5 * 43560.0),
            ("containing -⅓ acres", -43560.0 / 3.0),
            ("containing \u22125 acres", -5.0 * 43560.0),
            ("-5 acres", -5.0 * 43560.0),
            ("containing -2 acres and 50 perches", -(2.0 * 43560.0 + 50.0 * 16.5**2)),
            ("Containing -2 acres and 50 feet of frontage.", -2.0 * 43560.0),
            ("Containing 0 acres and 50 feet of frontage.", 0.0),
            (
                "Containing 2 acres and 50 feet of frontage; also containing -1.0 acres.",
                -43560.0,
            ),
            ("containing 10,000 square feet or 0.00 acres", 0.0),
            ("containing 10,000 square feet (0.00 acres)", 0.0),
            ("containing 10,000 square feet or -0.23 acres", -0.23 * 43560.0),
        ],
    )
    def test_extract_area_statement_captures_negative_and_secondary_non_positive(
        self, text: str, expected_sq_ft: float
    ) -> None:
        info = extract_area_statement(text)
        assert info is not None
        assert info["value_sq_ft"] == pytest.approx(expected_sq_ft)

    @pytest.mark.parametrize(
        ("text", "expected_sq_ft"),
        [
            ("containing area - 5 acres", 5.0 * 43560.0),
            ("containing Lot 1-5 acres", 5.0 * 43560.0),
            ("containing 10,000 square feet (0.23 acres)", 10000.0),
            ("containing 10,000 square feet; parent tract containing 0 acres.", 10000.0),
            ("Being part of the parent tract. Containing 10 acres.", 10.0 * 43560.0),
        ],
    )
    def test_extract_area_statement_keeps_positive_dashes_dual_units_and_parent_filter(
        self, text: str, expected_sq_ft: float
    ) -> None:
        info = extract_area_statement(text)
        assert info is not None
        assert info["value_sq_ft"] == pytest.approx(expected_sq_ft)

    @pytest.mark.parametrize(
        "text",
        [
            "Being part of the parent tract containing approx. 10.0 acres.",
            "Being part of the larger parcel per Plat Bk. 2 containing 40 acres.",
            "Containing 10 acres m.o.l. of the parent tract.",
            "Being part of the original lot (5.5 acres) containing 10.0 acres.",
            "Containing 2 acres and 50 feet of frontage.",
        ],
    )
    def test_extract_area_statement_parent_abbrevs_and_unread_return_none(self, text: str) -> None:
        assert extract_area_statement(text) is None

    def test_uncovered_text_gaps_preserves_spliced_gap_and_handles_repeated_tail(self) -> None:
        # (a) Embedded spliced-out clause between two parts of a tract stays uncovered
        working_a = (
            "TRACT 1: BEGINNING at a pin; THENCE N 0° E 100 feet. "
            "Containing 0 acres. "
            "Containing 10 acres. "
            "THENCE N 90° E 100 feet to the point of beginning."
        )
        seg_a = (
            "TRACT 1: BEGINNING at a pin; THENCE N 0° E 100 feet. "
            "Containing 10 acres. "
            "THENCE N 90° E 100 feet to the point of beginning."
        )
        gaps_a = _uncovered_text_gaps(working_a, [(seg_a, "Tract 1", mp_models.TractType.MAIN)])
        assert gaps_a == ["Containing 0 acres."]
        gap_area = extract_area_statement(gaps_a[0])
        assert gap_area is not None and gap_area["value_sq_ft"] == 0.0

        # (b) Repeated tail ("to the point of beginning.") never ends coverage early
        working_b = (
            "TRACT 1: BEGINNING at a pin; THENCE N 0° E 100 feet to the point of beginning.\n"
            "THENCE N 90° E 100 feet; THENCE S 0° W 100 feet; "
            "THENCE N 90° W 100 feet to the point of beginning. Containing 0 acres. "
            "to the point of beginning."
        )
        seg_b = (
            "TRACT 1: BEGINNING at a pin; THENCE N 0° E 100 feet to the point of beginning. "
            "THENCE N 90° E 100 feet; THENCE S 0° W 100 feet; "
            "THENCE N 90° W 100 feet to the point of beginning. Containing 0 acres. "
            "to the point of beginning."
        )
        gaps_b = _uncovered_text_gaps(working_b, [(seg_b, "Tract 1", mp_models.TractType.MAIN)])
        assert gaps_b == []

    @pytest.mark.parametrize(
        "malformed",
        [
            "-100 feet",
            "\u2212100 feet",
            "THENCE N 0° E -100.00 feet",
            "1e2 feet",
            "1.5E+2 feet",
            "1e-2 feet",
            "THENCE N 0° E 1e2 feet",
            "-100'",
            "\u2212100'",
            "1e2'",
            "1.5E+2'",
        ],
    )
    def test_extract_distance_rejects_negative_and_scientific_notation(
        self, malformed: str
    ) -> None:
        assert extract_distance(malformed) == (0.0, "feet")

    def test_extract_distance_rejects_spaced_minus_and_review_fails_closed_on_malformed(
        self,
    ) -> None:
        assert extract_distance("N 45° E - 100 feet") == (0.0, "feet")

        for bad_dist in ("-100.00 feet", "1e2 feet", "- 100.00 feet", "\u2212 100.00 feet"):
            deed = (
                "BEGINNING at an iron pin; "
                f"THENCE N 0°00'00\" E, {bad_dist}; "
                "THENCE N 90°00'00\" E, 100.00 feet; "
                "THENCE S 0°00'00\" W, 100.00 feet; "
                "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning."
            )
            result = review_text(deed)
            assert result["status"] != "checks_passed"

    def test_attach_invalid_stated_area_marks_every_call_and_uses_split_notes(self) -> None:
        deed = (
            "COMMENCING at a stone; "
            "THENCE N 0°00'00\" E, 50.00 feet to the POINT OF BEGINNING; "
            "THENCE N 0°00'00\" E, 100.00 feet; "
            "THENCE N 90°00'00\" E, 100.00 feet; "
            "THENCE S 0°00'00\" W, 100.00 feet; "
            "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning, "
            "containing -10000 sq. ft."
        )
        calls, _ = extract_calls(deed)
        assert len(calls) == 5
        for call in calls:
            assert any(
                part.startswith(INVALID_STATED_AREA_NOTE_PREFIX) for part in split_notes(call.notes)
            )
        # Stripping calls[0] (tie-in) must NOT drop the invalid stated area blocker
        boundary_only = calls[1:]
        res = verify_closure(boundary_only)
        assert not res.is_fully_verified()
        assert any("invalid stated area" in w.lower() for w in res.warnings)

        # Idempotency via split_notes (not substring inside a verbatim note)
        verbatim_call = mp_models.DeedCall(
            course=1,
            direction_text="N 0° E",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=100.0,
            notes="parenthetical: (note mentions invalid stated area: 0.0 sq ft (acres))",
        )
        attached = _attach_invalid_stated_area_note([verbatim_call], 0.0, "acres")
        parts = split_notes(attached[0].notes)
        assert "invalid stated area: 0.0 sq ft (acres)" in parts
        attached_again = _attach_invalid_stated_area_note(attached, 0.0, "acres")
        assert attached_again[0].notes == attached[0].notes

    def test_multi_tract_deed_level_preamble_zero_area_blocks_all_tracts(self) -> None:
        deed = (
            "All those parcels containing 0 acres:\n"
            "TRACT 1: BEGINNING at an iron pin; "
            "THENCE N 0°00'00\" E, 100.00 feet; "
            "THENCE N 90°00'00\" E, 100.00 feet; "
            "THENCE S 0°00'00\" W, 100.00 feet; "
            "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning, "
            "containing 10,000 square feet.\n\n"
            "TRACT 2: BEGINNING at a concrete monument; "
            "THENCE N 0°00'00\" E, 100.00 feet; "
            "THENCE N 90°00'00\" E, 100.00 feet; "
            "THENCE S 0°00'00\" W, 100.00 feet; "
            "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning, "
            "containing 10,000 square feet."
        )
        all_calls, tracts = extract_calls(deed)
        assert len(tracts) == 2
        for tract in tracts:
            assert all(
                any(
                    part.startswith(INVALID_STATED_AREA_NOTE_PREFIX)
                    for part in split_notes(call.notes)
                )
                for call in tract.calls
            )
        assert all(
            any(
                part.startswith(INVALID_STATED_AREA_NOTE_PREFIX) for part in split_notes(call.notes)
            )
            for call in all_calls
        )
        results = verify_closure([], tracts=tracts)
        assert isinstance(results, list)
        assert all(not r.is_fully_verified() for r in results)

    def test_multi_tract_tract1_zero_area_does_not_leak_to_valid_tract2(self) -> None:
        deed = (
            "TRACT 1: BEGINNING at an iron pin; "
            "THENCE N 0°00'00\" E, 100.00 feet; "
            "THENCE N 90°00'00\" E, 100.00 feet; "
            "THENCE S 0°00'00\" W, 100.00 feet; "
            "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning, "
            "containing 0 acres.\n\n"
            "TRACT 2: BEGINNING at a concrete monument; "
            "THENCE N 0°00'00\" E, 100.00 feet; "
            "THENCE N 90°00'00\" E, 100.00 feet; "
            "THENCE S 0°00'00\" W, 100.00 feet; "
            "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning, "
            "containing 10,000 square feet."
        )
        _, tracts = extract_calls(deed)
        assert len(tracts) == 2
        assert all(
            INVALID_STATED_AREA_NOTE_PREFIX in (call.notes or "") for call in tracts[0].calls
        )
        assert not any(
            INVALID_STATED_AREA_NOTE_PREFIX in (call.notes or "") for call in tracts[1].calls
        )
        results = verify_closure([], tracts=tracts)
        assert isinstance(results, list)
        assert not results[0].is_fully_verified()
        assert results[1].is_fully_verified()


# ---------------------------------------------------------------------------
# 4. PLSS metadata & subdivision recital guards
# ---------------------------------------------------------------------------


class TestPlssAndSubdivisionGuards:
    @pytest.mark.parametrize(
        "text",
        [
            "N 1/2-IN PIPE, Section 12, T15N, R3E",
            "N 1/2 IN.PIPE, Section 12, T15N, R3E",
        ],
    )
    def test_plss_aliquot_rejects_hyphenated_and_glued_in_units(self, text: str) -> None:
        assert extract_plss_metadata(text)["aliquot"] is None

    def test_plss_aliquot_preserves_in_section(self) -> None:
        assert extract_plss_metadata("THE NW 1/4 IN SECTION 12, T15N, R3E")["aliquot"] == "NW 1/4"

    @pytest.mark.parametrize(
        "text",
        [
            "N 45 DEG 10 MIN 15 SEC 200 FT",
            "N 45 DEG 10 MIN 15 SEC 20 FT",
            "N 45 DEG 10 MIN 15 SEC 20",
            "15 SEC 12, T15N, R3E",
            "15.5 SEC 12",
            "15 SEC 200 FT",
            "SEC 45, T15N, R3E",
            "SEC 20 FEET",
            "SEC 12 RODS",
            "SEC 10 CHAINS",
        ],
    )
    def test_plss_sec_rejects_seconds_lengths_and_out_of_range(self, text: str) -> None:
        assert extract_plss_metadata(text)["section"] is None

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("SECTION 12, T15N, R3E", "12"),
            ("SEC. 12, T15N, R3E", "12"),
            ("SEC 4", "4"),
            ("LOT 12 SEC 4", "4"),
            ("PART OF SE 1/4 SEC 10", "10"),
        ],
    )
    def test_plss_sec_preserves_valid_sections(self, text: str, expected: str) -> None:
        assert extract_plss_metadata(text)["section"] == expected

    @pytest.mark.parametrize(
        "text",
        [
            "RECORDED AT 3 O CLOCK P.M.",
            "RECORDED AT 3 O'CLOCK P.M.",
            "RECORDED AT 12 NOON P.M.",
            "RECORDED AT 3 P.M.",
        ],
    )
    def test_plss_pm_rejects_clock_and_time_phrases(self, text: str) -> None:
        assert extract_plss_metadata(text)["principal_meridian"] is None

    def test_plss_pm_preserves_real_principal_meridians(self) -> None:
        assert (
            extract_plss_metadata("WILLAMETTE P.M.")["principal_meridian"]
            == "Willamette Principal Meridian"
        )
        assert extract_plss_metadata("6TH P.M.")["principal_meridian"] is not None

    @pytest.mark.parametrize(
        "text",
        [
            "Lot 1, THE NORTH HALF OF OAK PARK",
            "Lot 1, THE EAST LINE OF PINE SUBDIVISION",
            "Lot 1, THE SOUTH CORNER OF PINE HILLS",
            "Lot 1, THE WEST PART OF OAK ESTATES",
            "Lot 1, THE NORTH PORTION OF OAK ESTATES",
            "Lot 1, THE REMAINING ACRES",
            "Lot 1, THE NORTH QUARTER SUBDIVISION",
            "Lot 1, THE NORTH SAID SUBDIVISION",
            "Lot 1, THE EAST HALF THEREOF",
        ],
    )
    def test_subdivision_rejects_the_recital_phrases_even_with_suffix(self, text: str) -> None:
        ref = extract_subdivision_reference(text)
        assert ref is not None
        assert ref.subdivision_name is None

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Lot 1, THE OAKS SUBDIVISION", "THE OAKS SUBDIVISION"),
            ("Lot 2, Block 3, THE NORTH HILLS SUBDIVISION", "THE NORTH HILLS SUBDIVISION"),
            ("Lot 4, THE MEADOWS", "THE MEADOWS"),
        ],
    )
    def test_subdivision_preserves_valid_the_names(self, text: str, expected: str) -> None:
        ref = extract_subdivision_reference(text)
        assert ref is not None
        assert ref.subdivision_name == expected


# ---------------------------------------------------------------------------
# 5. parcels.py: "BEING Parcel A: ... BEING Parcel B: ..."
# ---------------------------------------------------------------------------


class TestParcelsBeingHeadings:
    def test_being_parcel_colon_headings_are_detected_and_split(self) -> None:
        text = (
            "BEING Parcel A: BEGINNING at an iron pin; THENCE N 0° E 100 feet.\n"
            "BEING Parcel B: BEGINNING at a concrete monument; THENCE N 90° E 100 feet."
        )
        markers = detect_parcel_markers(text)
        assert [m["label"] for m in markers] == ["Parcel A", "Parcel B"]
        parcels = split_into_parcels(text)
        assert [p["label"] for p in parcels] == ["Parcel A", "Parcel B"]

    def test_being_numbered_parcel_colon_headings_are_detected(self) -> None:
        text = "BEING Parcel 1: BEGINNING at pin; ...\nBEING Parcel 2: BEGINNING at stake; ..."
        markers = detect_parcel_markers(text)
        assert [m["label"] for m in markers] == ["Parcel 1", "Parcel 2"]

    @pytest.mark.parametrize(
        "text",
        [
            "being the same parcel as Parcel A",
            "being the same parcel as Parcel A: conveyed in Book 12.",
            "being Parcel A - conveyed in Book 12.",
            "along the west line of Parcel A: 100 feet;",
            "being Parcel 1 - conveyed in Book 12.",
            "along the west line of Parcel 1: 100 feet;",
        ],
    )
    def test_back_references_remain_suppressed(self, text: str) -> None:
        assert detect_parcel_markers(text) == []


# ---------------------------------------------------------------------------
# 6. Bearing & curve math NaN/inf/bool guards (both mp_bearing & BearingConverter)
# ---------------------------------------------------------------------------


class TestBearingAndCurveMathGuards:
    @pytest.mark.parametrize("_name,bearing_api", BEARING_IMPLS)
    @pytest.mark.parametrize("bad", [True, False, float("nan"), float("inf"), float("-inf")])
    def test_calculate_curve_properties_rejects_bool_and_non_finite(
        self, _name: str, bearing_api: Any, bad: Any
    ) -> None:
        with pytest.raises(ValueError):
            bearing_api.calculate_curve_properties(bad, delta_deg=30.0)
        with pytest.raises(ValueError):
            bearing_api.calculate_curve_properties(100.0, delta_deg=bad)
        with pytest.raises(ValueError):
            bearing_api.calculate_curve_properties(100.0, arc_length_ft=bad)
        with pytest.raises(ValueError):
            bearing_api.calculate_curve_properties(100.0, delta_deg=30.0, arc_length_ft=bad)

    @pytest.mark.parametrize("_name,bearing_api", BEARING_IMPLS)
    @pytest.mark.parametrize("bad_doc", [0.0, -2.0, float("nan"), float("inf"), True, False])
    def test_calculate_missing_curve_elements_rejects_bad_doc_even_with_radius(
        self, _name: str, bearing_api: Any, bad_doc: Any
    ) -> None:
        with pytest.raises(ValueError):
            bearing_api.calculate_missing_curve_elements(
                radius_ft=100.0, delta_deg=30.0, degree_of_curvature=bad_doc
            )

    @pytest.mark.parametrize("_name,bearing_api", BEARING_IMPLS)
    @pytest.mark.parametrize("bad_bool", [True, False])
    def test_calculate_missing_curve_elements_rejects_bool_inputs(
        self, _name: str, bearing_api: Any, bad_bool: bool
    ) -> None:
        with pytest.raises(ValueError):
            bearing_api.calculate_missing_curve_elements(radius_ft=bad_bool, delta_deg=30.0)
        with pytest.raises(ValueError):
            bearing_api.calculate_missing_curve_elements(radius_ft=100.0, delta_deg=bad_bool)
        with pytest.raises(ValueError):
            bearing_api.calculate_missing_curve_elements(radius_ft=100.0, arc_length_ft=bad_bool)
        with pytest.raises(ValueError):
            bearing_api.calculate_missing_curve_elements(radius_ft=100.0, chord_length_ft=bad_bool)

    @pytest.mark.parametrize("_name,bearing_api", BEARING_IMPLS)
    @pytest.mark.parametrize("bad", [True, False, float("nan"), float("inf"), float("-inf")])
    def test_parse_packed_dms_and_quadrant_to_azimuth_reject_bool_and_non_finite(
        self, _name: str, bearing_api: Any, bad: Any
    ) -> None:
        with pytest.raises(ValueError):
            bearing_api.parse_packed_dms(bad)
        with pytest.raises(ValueError):
            bearing_api.quadrant_to_azimuth("N", bad, "E")
        with pytest.raises(ValueError):
            bearing_api.azimuth_to_quadrant(bad)

    @pytest.mark.parametrize("_name,bearing_api", BEARING_IMPLS)
    def test_quadrant_pattern_no_redos_backtracking(self, _name: str, bearing_api: Any) -> None:
        adversarial = "N 45°" + (" " * 1200) + "X"
        start = time.perf_counter()
        result = bearing_api.parse_quadrant_bearing(adversarial)
        elapsed = time.perf_counter() - start
        assert result is None
        assert elapsed < 0.25

    @pytest.mark.parametrize(
        ("impl_name", "bearing_api", "point_cls"),
        [
            ("package", mp_bearing, mp_models.Point),
            ("monolith", BearingConverter, monolith_models.Point),
        ],
    )
    @pytest.mark.parametrize(
        ("start_az", "radius", "delta", "curve_dir"),
        [
            (0.0, True, 30.0, "right"),
            (0.0, False, 30.0, "right"),
            (0.0, 0.0, 30.0, "right"),
            (0.0, -50.0, 30.0, "right"),
            (0.0, float("nan"), 30.0, "right"),
            (0.0, float("inf"), 30.0, "right"),
            (0.0, float("-inf"), 30.0, "right"),
            (0.0, 100.0, True, "right"),
            (0.0, 100.0, False, "right"),
            (0.0, 100.0, float("nan"), "right"),
            (0.0, 100.0, float("inf"), "right"),
            (0.0, 100.0, float("-inf"), "right"),
            (0.0, 100.0, -5.0, "right"),
            (0.0, 100.0, 365.0, "right"),
            (True, 100.0, 30.0, "right"),
            (False, 100.0, 30.0, "right"),
            (float("nan"), 100.0, 30.0, "right"),
            (float("inf"), 100.0, 30.0, "right"),
            (float("-inf"), 100.0, 30.0, "right"),
            (0.0, 100.0, 30.0, "straight"),
        ],
    )
    def test_compute_curve_endpoint_rejects_invalid_inputs(
        self,
        impl_name: str,
        bearing_api: Any,
        point_cls: Any,
        start_az: Any,
        radius: Any,
        delta: Any,
        curve_dir: str,
    ) -> None:
        del impl_name
        start = point_cls(x=0.0, y=0.0)
        with pytest.raises(ValueError):
            bearing_api.compute_curve_endpoint(start, start_az, radius, delta, curve_dir)


# ---------------------------------------------------------------------------
# 7. Reject bool on all numeric measurement fields (mp-models & monolith models)
# ---------------------------------------------------------------------------


class TestModelsRejectBoolMeasurements:
    @pytest.mark.parametrize("_name,models", MODEL_IMPLS)
    @pytest.mark.parametrize("bad_bool", [True, False])
    def test_deedcall_rejects_bool_on_all_numeric_fields_and_keeps_flag_coercion(
        self, _name: str, models: Any, bad_bool: bool
    ) -> None:
        with pytest.raises(ValidationError):
            models.DeedCall(course=1, direction_text="N 0° E", distance_ft=bad_bool)
        with pytest.raises(ValidationError):
            models.DeedCall(
                course=1,
                direction_text="N 0° E",
                distance_ft=100.0,
                bearing_azimuth_deg_from_north=bad_bool,
            )
        with pytest.raises(ValidationError):
            models.DeedCall(
                course=1,
                direction_text="curve",
                distance_ft=100.0,
                curve_dir="right",
                radius_ft=bad_bool,
                delta_deg=30.0,
            )
        with pytest.raises(ValidationError):
            models.DeedCall(
                course=1,
                direction_text="curve",
                distance_ft=100.0,
                curve_dir="right",
                radius_ft=100.0,
                delta_deg=bad_bool,
            )
        with pytest.raises(ValidationError):
            models.DeedCall(
                course=1,
                direction_text="curve",
                distance_ft=100.0,
                curve_dir="right",
                radius_ft=100.0,
                arc_length_ft=bad_bool,
            )
        with pytest.raises(ValidationError):
            models.DeedCall(
                course=1,
                direction_text="curve",
                distance_ft=100.0,
                curve_dir="right",
                radius_ft=100.0,
                delta_deg=30.0,
                chord_length_ft=bad_bool,
            )

        # Boolean flags must STILL coerce string values (AGENTS.md invariant)
        call = models.DeedCall(
            course=1,
            direction_text="N 0° E",
            distance_ft=100.0,
            is_tie_in="true",
            is_meander="false",
        )
        assert call.is_tie_in is True
        assert call.is_meander is False

    @pytest.mark.parametrize("_name,models", MODEL_IMPLS)
    @pytest.mark.parametrize("bad_bool", [True, False])
    def test_legal_description_and_tract_reject_bool_stated_area(
        self, _name: str, models: Any, bad_bool: bool
    ) -> None:
        with pytest.raises(ValidationError):
            models.LegalDescription(stated_area_sq_ft=bad_bool)
        with pytest.raises(ValidationError):
            models.Tract(label="Tract 1", tract_type="main", stated_area_sq_ft=bad_bool)

    @pytest.mark.parametrize("_name,models", MODEL_IMPLS)
    @pytest.mark.parametrize(
        "field_name",
        [
            "misclosure_x_ft",
            "misclosure_y_ft",
            "misclosure_ft",
            "area_sq_ft",
            "area_acres",
            "perimeter_ft",
            "precision_ratio",
            "confidence_score",
        ],
    )
    @pytest.mark.parametrize("bad_bool", [True, False])
    def test_closure_result_rejects_bool_on_all_numeric_fields(
        self, _name: str, models: Any, field_name: str, bad_bool: bool
    ) -> None:
        kwargs: dict[str, Any] = {
            "misclosure_x_ft": 0.0,
            "misclosure_y_ft": 0.0,
            "misclosure_ft": 0.0,
            "area_sq_ft": 100.0,
            "area_acres": 100.0 / 43560.0,
            "perimeter_ft": 40.0,
            "closure_passed": True,
            "angle_check_passed": True,
            "curve_consistency_passed": True,
        }
        kwargs[field_name] = bad_bool
        with pytest.raises(ValidationError):
            models.ClosureResult(**kwargs)

    @pytest.mark.parametrize("_name,models", MODEL_IMPLS)
    @pytest.mark.parametrize("bad_bool", [True, False])
    def test_point_rejects_bool_coordinates(self, _name: str, models: Any, bad_bool: bool) -> None:
        with pytest.raises(ValidationError):
            models.Point(x=bad_bool, y=0.0)
        with pytest.raises(ValidationError):
            models.Point(x=0.0, y=bad_bool)

    @pytest.mark.parametrize("bad_bool", [True, False])
    def test_envelope_messages_reject_bool_and_negative_measurements(self, bad_bool: bool) -> None:
        with pytest.raises(ValidationError):
            RawTextMessage(
                source="deed.pdf",
                text="BEGINNING",
                llm_provider="openai",
                llm_model="gpt-5",
                confidence=bad_bool,
            )
        with pytest.raises(ValidationError):
            parse_message(
                json.dumps(
                    {
                        "type": "raw_text",
                        "source": "deed.pdf",
                        "text": "BEGINNING",
                        "llm_provider": "openai",
                        "llm_model": "gpt-5",
                        "confidence": bad_bool,
                    }
                )
            )
        with pytest.raises(ValidationError):
            ClosureResultMessage(
                source="deed.pdf",
                is_verified=False,
                misclosure_ft=bad_bool,
            )
        with pytest.raises(ValidationError):
            ClosureResultMessage(
                source="deed.pdf",
                is_verified=False,
                misclosure_ft=0.0,
                confidence=bad_bool,
            )
        with pytest.raises(ValidationError):
            ClosureResultMessage(
                source="deed.pdf",
                is_verified=False,
                misclosure_ft=0.0,
                area_sq_ft=bad_bool,
            )
        with pytest.raises(ValidationError):
            parse_message(
                json.dumps(
                    {
                        "type": "closure_result",
                        "source": "deed.pdf",
                        "is_verified": False,
                        "misclosure_ft": bad_bool,
                    }
                )
            )
        with pytest.raises(ValidationError):
            ClosureResultMessage(
                source="deed.pdf",
                is_verified=False,
                misclosure_ft=-0.01,
            )
        with pytest.raises(ValidationError):
            ClosureResultMessage(
                source="deed.pdf",
                is_verified=False,
                misclosure_ft=0.0,
                area_sq_ft=-100.0,
            )
        valid = ClosureResultMessage(
            source="deed.pdf",
            is_verified=True,
            misclosure_ft=0.0,
            area_sq_ft=0.0,
            confidence=None,
        )
        assert valid.misclosure_ft == 0.0
        assert valid.area_sq_ft == 0.0

    @pytest.mark.parametrize("_name,models", MODEL_IMPLS)
    def test_deed_call_json_schema_preserves_standard_numeric_bounds(
        self, _name: str, models: Any
    ) -> None:
        props = models.DeedCall.model_json_schema()["properties"]
        distance_num = next(
            item
            for item in props["distance_ft"]["anyOf"]
            if "type" in item and item["type"] == "number"
        )
        assert distance_num["exclusiveMinimum"] == 0
        assert "gt" not in distance_num
        az_num = next(
            item
            for item in props["bearing_azimuth_deg_from_north"]["anyOf"]
            if "type" in item and item["type"] == "number"
        )
        assert az_num["minimum"] == 0
        assert az_num["exclusiveMaximum"] == 360
        assert "ge" not in az_num
        assert "lt" not in az_num


# ---------------------------------------------------------------------------
# 8. Logging simplification A4 (mp_models.logging)
# ---------------------------------------------------------------------------


def test_logging_includes_metesparser_in_package_logger_names(
    isolate_logging_state: None,
) -> None:
    from mp_models import logging as pkg_logging

    assert "metesparser" in pkg_logging._PACKAGE_LOGGER_NAMES

    stream = io.StringIO()
    pkg_logging.configure_logging(level="WARNING", log_format="console", stream=stream)
    mono_logger = logging.getLogger("metesparser")
    assert mono_logger.propagate is False
    assert mono_logger.level == logging.WARNING
    assert len(mono_logger.handlers) == 1

    pkg_logging.configure_logging(
        level="INFO", log_format="console", stream=stream, take_over_root=True
    )
    assert mono_logger.propagate is True
    assert mono_logger.level == logging.NOTSET
    assert mono_logger.handlers == []


# ---------------------------------------------------------------------------
# 9. Cycle 3 Track 1: C1, C2, C3, C8(part 1), M4/A3, M9, M12
# ---------------------------------------------------------------------------


class TestCycle3MalformedLengthFailClosed:
    """C1: Malformed length tokens must fail closed instead of being silently dropped."""

    @pytest.mark.parametrize(
        "text",
        [
            "100 feet and -5 feet",
            "-100 feet to a pin 100 feet distant",
            "100 feet 1e2 feet",
            "100' and -5'",
            "100', -5'",
            "100' 1e2'",
            "100', 1e2'",
            "-100' to a pin 100' distant",
            "-100' to a pin, 100'",
            "100 feet and -5'",
        ],
    )
    def test_malformed_length_alongside_valid_length_fails_closed(self, text: str) -> None:
        assert extract_distance(text) == (0.0, "feet")
        assert read_course_length(text).value == 0.0

    def test_malformed_second_length_blocks_review(self) -> None:
        deed = (
            "BEGINNING at an iron pin; "
            "THENCE N 0°00'00\" E, 100 feet and -5 feet; "
            "THENCE N 90°00'00\" E, 100.00 feet; "
            "THENCE S 0°00'00\" W, 100.00 feet; "
            "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning."
        )
        assert review_text(deed)["status"] != "checks_passed"

    def test_valid_hyphenated_dms_mixed_fractions_and_label_dash_preserved(self) -> None:
        assert extract_distance("thence N 45-30'-15\" E 100 feet to a pin") == (100.0, "feet")
        assert extract_distance("100-1/2 feet") == (100.5, "feet")
        assert extract_distance("100 - 1/2 feet") == (100.5, "feet")
        assert extract_distance(
            "thence N 45° E 100 feet along Main Street (formerly Caldwell Avenue - 100.00 feet wide)"
        ) == (100.0, "feet")


class TestCycle3AreaStatementGuardsAndSimplification:
    """C2: Sentence-period bleed, conveyed-portion recitals, spaced minus, signed compounds, A2."""

    @pytest.mark.parametrize(
        ("text", "expected_sq_ft"),
        [
            ("containing 0 acres. Being part of the parent tract.", 0.0),
            ("containing -5 acres. Said land is part of the original parcel.", -5.0 * 43560.0),
            ("containing 5.00 acres. Being a portion of the larger tract.", 5.0 * 43560.0),
            ("containing 0 sq. ft. Being part of the parent tract.", 0.0),
            ("containing 500 sq. ft. Said land is part of the original parcel.", 500.0),
        ],
    )
    def test_sentence_period_does_not_bleed_into_next_sentence(
        self, text: str, expected_sq_ft: float
    ) -> None:
        info = extract_area_statement(text)
        assert info is not None
        assert info["value_sq_ft"] == pytest.approx(expected_sq_ft)

    @pytest.mark.parametrize(
        ("text", "expected_sq_ft"),
        [
            ("Containing 0 acres, being part of the original lot.", 0.0),
            ("Containing 500 square feet, being part of a larger parcel.", 500.0),
            ("Containing 5 acres, being a portion of the parent tract.", 5.0 * 43560.0),
            ("Containing 2.5 acres, part of the original lot.", 2.5 * 43560.0),
            ("Containing 500 square feet, more or less, being part of the larger parcel.", 500.0),
        ],
    )
    def test_conveyed_portion_recital_after_area_is_kept(
        self, text: str, expected_sq_ft: float
    ) -> None:
        info = extract_area_statement(text)
        assert info is not None
        assert info["value_sq_ft"] == pytest.approx(expected_sq_ft)

    @pytest.mark.parametrize(
        "text",
        [
            "part of a larger tract containing 100 acres",
            "out of the parent parcel of 50 acres",
            "originally containing 100 acres",
            "containing 100 acres of the parent tract",
            "parent tract of 100 acres",
            "containing 100 acres in the larger parcel",
        ],
    )
    def test_true_parent_area_references_remain_filtered(self, text: str) -> None:
        assert extract_area_statement(text) is None

    @pytest.mark.parametrize(
        ("text", "expected_sq_ft"),
        [
            ("Containing - 10,000 square feet.", -10000.0),
            ("Containing \u2212 5 acres", -5.0 * 43560.0),
            ("Area: - 5 acres", -5.0 * 43560.0),
            ("- 5 acres", -5.0 * 43560.0),
            ("Containing approximately - 5 acres", -5.0 * 43560.0),
            ("Containing approx. - 5 acres", -5.0 * 43560.0),
            ("Containing ~ - 5 acres", -5.0 * 43560.0),
        ],
    )
    def test_spaced_unary_minus_parses_negative(self, text: str, expected_sq_ft: float) -> None:
        info = extract_area_statement(text)
        assert info is not None
        assert info["value_sq_ft"] == pytest.approx(expected_sq_ft)

    def test_separator_dashes_remain_positive(self) -> None:
        for text in ("containing Lot 1 - 5 acres", "containing area - 5 acres"):
            info = extract_area_statement(text)
            assert info is not None
            assert info["value_sq_ft"] == pytest.approx(5.0 * 43560.0)

    @pytest.mark.parametrize(
        "text",
        [
            "Containing 2 acres and -50 perches",
            "Containing 2 acres and - 50 perches",
            "Containing 2 acres and \u2212 50 perches",
        ],
    )
    def test_negative_compound_component_fails_closed(self, text: str) -> None:
        info = extract_area_statement(text)
        assert info is not None
        assert info["value_sq_ft"] <= 0.0
        assert info["unit"] == "compound"

    def test_negative_compound_component_blocks_review_text(self) -> None:
        deed = (
            "BEGINNING at an iron pin; "
            "THENCE N 0°00'00\" E, 100.00 feet; "
            "THENCE N 90°00'00\" E, 100.00 feet; "
            "THENCE S 0°00'00\" W, 100.00 feet; "
            "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning. "
            "Containing 2 acres and -50 perches."
        )
        res = review_text(deed)
        assert res["status"] == "needs_review"
        assert any(INVALID_STATED_AREA_NOTE_PREFIX in (c.get("notes") or "") for c in res["calls"])

    def test_a2_is_abbreviation_period_accepts_custom_abbreviations(self) -> None:
        assert is_abbreviation_period("approx. 5 acres", 6, abbreviations=frozenset({"approx"}))
        assert not is_abbreviation_period("approx. 5 acres", 6)


class TestCycle3ScientificNotationRejection:
    """C3: Reject scientific notation in stated areas and curve elements."""

    @pytest.mark.parametrize(
        ("text", "expected_unit_tag"),
        [
            ("Containing -1e2 acres", "acres"),
            ("Containing 1e2 acres", "acres"),
            ("Containing 1e-2 acres", "acres"),
            ("Containing 1.5e2 sq ft", "sq_ft"),
            ("Containing -.5e2 acres", "acres"),
            ("Containing -1e4 square feet.", "sq_ft"),
            ("Containing 1e6 square feet.", "sq_ft"),
            ("Containing 1e4 square feet.", "sq_ft"),
        ],
    )
    def test_extract_area_statement_fails_closed_on_scientific_notation(
        self, text: str, expected_unit_tag: str
    ) -> None:
        info = extract_area_statement(text)
        assert info is not None
        assert info["value_sq_ft"] == 0.0
        assert info["unit"] == f"unsupported scientific notation ({expected_unit_tag})"

    @pytest.mark.parametrize(
        "area_clause",
        [
            "Containing -1e4 square feet.",
            "Containing 1e6 square feet.",
            "Containing 1e4 square feet.",
            "Containing -1e2 acres.",
        ],
    )
    def test_review_text_blocks_scientific_notation_stated_area(self, area_clause: str) -> None:
        deed = (
            "BEGINNING at an iron pin; "
            "THENCE N 0°00'00\" E, 100.00 feet; "
            "THENCE N 90°00'00\" E, 100.00 feet; "
            "THENCE S 0°00'00\" W, 100.00 feet; "
            "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning. "
            f"{area_clause}"
        )
        res = review_text(deed)
        assert res["status"] == "needs_review"
        assert any(err["code"] == "invalid_stated_area" for err in res["errors"])
        assert any(INVALID_STATED_AREA_NOTE_PREFIX in (c.get("notes") or "") for c in res["calls"])

    def test_curve_radius_rejects_scientific_notation(self) -> None:
        curve_text = (
            "THENCE along a curve to the right having a radius of 1e2 feet "
            "and a delta of 90 degrees, arc length of 157.08 feet"
        )
        info = extract_curve_info(curve_text)
        assert info.get("radius_ft") is None
        assert info.get("arc_length_ft") == pytest.approx(157.08)

        deed = (
            f"BEGINNING at a pin; {curve_text}; "
            "THENCE S 0°00'00\" W 100 feet; "
            "THENCE N 90°00'00\" W 100 feet to the point of beginning."
        )
        with pytest.raises(ValueError, match="radius_ft"):
            extract_calls(deed, strict=True)
        assert review_text(deed)["status"] != "checks_passed"

    def test_curve_arc_and_chord_reject_scientific_notation(self) -> None:
        arc_text = (
            "THENCE along a curve to the right having a radius of 100 feet, arc length of 1e2 feet"
        )
        arc_info = extract_curve_info(arc_text)
        assert arc_info.get("arc_length_ft") is None
        with pytest.raises(ValueError):
            extract_calls(f"BEGINNING at a pin; {arc_text} to the point of beginning.", strict=True)

        chord_deed = (
            "BEGINNING at a pin; "
            "THENCE along a curve to the right having a radius of 100 feet, "
            "delta of 90 degrees, chord bearing N 45°00'00\" E, chord length of 1e2 feet; "
            "THENCE S 0°00'00\" W 100 feet; "
            "THENCE N 90°00'00\" W 100 feet to the point of beginning."
        )
        with pytest.raises(ValueError, match="chord_length_ft"):
            extract_calls(chord_deed, strict=True)
        skipped: list[mp_models.SkippedCourse] = []
        extract_calls(chord_deed, strict=False, skipped_courses=skipped)
        assert len(skipped) == 1
        assert review_text(chord_deed)["status"] != "checks_passed"

    def test_valid_east_bearings_and_foot_marks_still_parse(self) -> None:
        import re

        from mp_parse.units import LENGTH_NUMBER

        for sample in ("100 East", "100 E", "100' E"):
            m = re.search(LENGTH_NUMBER, sample)
            assert m is not None and m.group(0) == "100"
        assert extract_distance("100 feet East") == (100.0, "feet")
        assert extract_distance("100 feet E") == (100.0, "feet")
        assert extract_distance("100' to a pin") == (100.0, "feet")
        calls, _ = extract_calls("BEGINNING at a pin; THENCE N 0°00'00\" E 100 feet to a pin.")
        assert calls[0].distance_ft == pytest.approx(100.0)
        compact, _ = extract_calls("THENCE N45°E100FT to a pin")
        assert compact[0].distance_ft == pytest.approx(100.0)


class TestCycle3PerSegmentPocExtraction:
    """C8 (part 1): Populate Tract.poc_description per tract segment."""

    def test_multi_tract_extracts_poc_per_segment(self) -> None:
        deed = (
            "TRACT 1: COMMENCING at a stone monument; "
            "THENCE N 0°00'00\" E, 50.00 feet to the POINT OF BEGINNING; "
            "THENCE N 0°00'00\" E, 100.00 feet; "
            "THENCE N 90°00'00\" E, 100.00 feet; "
            "THENCE S 0°00'00\" W, 100.00 feet; "
            "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning.\n\n"
            "TRACT 2: COMMENCING at an iron pipe; "
            "THENCE S 90°00'00\" E, 25.00 feet to the POINT OF BEGINNING; "
            "THENCE N 0°00'00\" E, 80.00 feet; "
            "THENCE N 90°00'00\" E, 80.00 feet; "
            "THENCE S 0°00'00\" W, 80.00 feet; "
            "THENCE N 90°00'00\" W, 80.00 feet to the point of beginning.\n\n"
            "TRACT 3: BEGINNING at a concrete post; "
            "THENCE N 0°00'00\" E, 60.00 feet; "
            "THENCE N 90°00'00\" E, 60.00 feet; "
            "THENCE S 0°00'00\" W, 60.00 feet; "
            "THENCE N 90°00'00\" W, 60.00 feet to the point of beginning."
        )
        _, tracts = extract_calls(deed)
        assert len(tracts) == 3
        assert tracts[0].poc_description is not None
        assert "stone monument" in tracts[0].poc_description.lower()
        assert tracts[0].calls[0].is_tie_in is True
        assert all(not c.is_tie_in for c in tracts[0].calls[1:])

        assert tracts[1].poc_description is not None
        assert "iron pipe" in tracts[1].poc_description.lower()
        assert tracts[1].calls[0].is_tie_in is True
        assert all(not c.is_tie_in for c in tracts[1].calls[1:])

        assert tracts[2].poc_description is None
        assert all(not c.is_tie_in for c in tracts[2].calls)


class TestCycle3UncoveredTextGapsWordTokenAlignment:
    """M4 + A3: Word-token alignment without 1-char jumps."""

    def test_containing_inside_gap_not_split_by_stray_match(self) -> None:
        working = (
            "TRACT 1: BEGINNING at a pin; THENCE N 0° E 100 feet. "
            "Containing -5 acres. "
            "Containing 10 acres. "
            "THENCE N 90° E 100 feet to the point of beginning."
        )
        seg = (
            "TRACT 1: BEGINNING at a pin; THENCE N 0° E 100 feet. "
            "Containing 10 acres. "
            "THENCE N 90° E 100 feet to the point of beginning."
        )
        gaps = _uncovered_text_gaps(working, [(seg, "Tract 1", mp_models.TractType.MAIN)])
        assert gaps == ["Containing -5 acres."]
        area = extract_area_statement(gaps[0])
        assert area is not None and area["value_sq_ft"] == pytest.approx(-5.0 * 43560.0)

    def test_abbreviated_segment_with_stray_word_preserves_negative_area_gap(self) -> None:
        working = (
            "TRACT 1: BEGINNING at a pin; THENCE N 0° E 100 feet. "
            "Containing -5 acres, plus land. "
            "THENCE N 90° E 100 feet to the point of beginning."
        )
        seg = (
            "TRACT 1: BEGINNING at a pin; THENCE N 0° E 100 ft. "
            "Control zone. "
            "THENCE N 90° E 100 feet to the point of beginning."
        )
        gaps = _uncovered_text_gaps(working, [(seg, "Tract 1", mp_models.TractType.MAIN)])
        areas = [extract_area_statement(g) for g in gaps]
        assert any(
            a is not None and a["value_sq_ft"] == pytest.approx(-5.0 * 43560.0) for a in areas
        )

    def test_abbreviated_segment_does_not_leak_tract_local_invalid_area(self) -> None:
        working = (
            "TRACT 1: BEGINNING at a pin; THENCE N 0° E 100 feet. Containing 0 acres.\n"
            "TRACT 2: BEGINNING at a stake; THENCE N 90° E 100 feet. Containing 10,000 square feet."
        )
        seg1 = "TRACT 1: BEGINNING at a pin; THENCE N 0° E 100 ft. Containing 0 acres."
        seg2 = (
            "TRACT 2: BEGINNING at a stake; THENCE N 90° E 100 feet. Containing 10,000 square feet."
        )
        gaps = _uncovered_text_gaps(
            working,
            [
                (seg1, "Tract 1", mp_models.TractType.MAIN),
                (seg2, "Tract 2", mp_models.TractType.ADDITION),
            ],
        )
        assert not any(
            (a := extract_area_statement(g)) is not None and a["value_sq_ft"] <= 0 for g in gaps
        )


class TestCycle3RegexBacktrackingHardening:
    """M9: Eliminate catastrophic backtracking in prior conveyance and witness trees."""

    def test_extract_prior_conveyance_no_whitespace_backtracking(self) -> None:
        adversarial = "Deed Book 123" + (" " * 8000) + "!"
        start = time.perf_counter()
        result = extract_prior_conveyance(adversarial)
        elapsed = time.perf_counter() - start
        assert elapsed < 0.1
        assert result == "Deed Book 123"

        no_match_tail = "Deed Book 123" + (" " * 8000) + "\nnext line"
        start2 = time.perf_counter()
        _ = extract_prior_conveyance(no_match_tail)
        elapsed2 = time.perf_counter() - start2
        assert elapsed2 < 0.1

    def test_extract_witness_trees_no_cubic_backtracking(self) -> None:
        adversarial = ("oak " * 200) + ("bears " * 200) + "!"
        start = time.perf_counter()
        trees = extract_witness_trees(adversarial)
        elapsed = time.perf_counter() - start
        assert elapsed < 0.1
        assert trees == []


class TestCycle3SharedModelHelpersAndMessageBase:
    """M12 + #11/#17: Coverage of coerce_bool_field, stated_areas_match, model_rebuild, _Message."""

    @pytest.mark.parametrize("_name,models", MODEL_IMPLS)
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (True, True),
            (False, False),
            (None, False),
            (1, True),
            (0, False),
            (1.0, True),
            (0.0, False),
            ("true", True),
            (" YES ", True),
            ("1", True),
            ("y", True),
            ("on", True),
            ("false", False),
            ("", False),
            ("0", False),
            ("no", False),
            ("n", False),
            ("off", False),
        ],
    )
    def test_coerce_bool_field_valid_inputs(
        self, _name: str, models: Any, raw: object, expected: bool
    ) -> None:
        assert models.coerce_bool_field(raw) is expected

    @pytest.mark.parametrize("_name,models", MODEL_IMPLS)
    @pytest.mark.parametrize("bad", [2, -1, 0.5, "maybe", [], {}])
    def test_coerce_bool_field_rejects_invalid_inputs(
        self, _name: str, models: Any, bad: object
    ) -> None:
        with pytest.raises(ValueError, match="boolean"):
            models.coerce_bool_field(bad)

    @pytest.mark.parametrize("_name,models", MODEL_IMPLS)
    def test_stated_areas_match_tolerance_and_non_finite_bool_guards(
        self, _name: str, models: Any
    ) -> None:
        assert models.stated_areas_match(10000.0, 10000.0 + 1e-5)
        assert models.stated_areas_match(0.0, 5e-5)
        assert not models.stated_areas_match(0.0, 2e-4)
        assert models.stated_areas_match(1_000_000.0, 1_000_000.5)
        assert not models.stated_areas_match(1_000_000.0, 1_000_002.0)
        assert not models.stated_areas_match(10000.0, 10001.0)
        for bad in (True, False, float("nan"), float("inf"), float("-inf")):
            assert not models.stated_areas_match(bad, 1.0)
            assert not models.stated_areas_match(1.0, bad)

    @pytest.mark.parametrize("_name,models", MODEL_IMPLS)
    def test_legal_description_is_pydantic_complete_at_import(
        self, _name: str, models: Any
    ) -> None:
        # Ensure importing mp_models.Tract does not interfere with monolith LegalDescription.
        assert mp_models.Tract is not None
        assert models.LegalDescription.__pydantic_complete__ is True
        ld = models.LegalDescription(
            tracts=[models.Tract(label="Tract 1", tract_type=models.TractType.MAIN)]
        )
        assert len(ld.tracts) == 1

    def test_message_inherits_no_bool_float_model_and_preserves_json_schema(self) -> None:
        assert issubclass(_Message, _NoBoolFloatModel)
        raw_props = RawTextMessage.model_json_schema()["properties"]
        conf_num = next(
            item for item in raw_props["confidence"]["anyOf"] if item.get("type") == "number"
        )
        assert conf_num["minimum"] == 0.0
        assert conf_num["maximum"] == 1.0

        closure_props = ClosureResultMessage.model_json_schema()["properties"]
        assert closure_props["misclosure_ft"]["type"] == "number"
        assert closure_props["misclosure_ft"]["minimum"] == 0.0
        area_num = next(
            item for item in closure_props["area_sq_ft"]["anyOf"] if item.get("type") == "number"
        )
        assert area_num["minimum"] == 0.0


# ---------------------------------------------------------------------------
# 10. Cycle 3 Follow-up Track 1 (#4, #5, #6, #7, #8, #9, #10, #14, #16-#23)
# ---------------------------------------------------------------------------


class TestFollowUpDroppedEmptySegmentAndGaps:
    """#4: Dropped empty segment non-positive area & empty-interval _uncovered_text_gaps."""

    def test_dropped_trailing_empty_segment_negative_area_blocks_earlier_tract(self) -> None:
        deed = (
            "TRACT 1: BEGINNING at an iron pin; "
            "THENCE N 0°00'00\" E, 100.00 feet; "
            "THENCE N 90°00'00\" E, 100.00 feet; "
            "THENCE S 0°00'00\" W, 100.00 feet; "
            "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning, "
            "containing 10,000 square feet.\n\n"
            "TRACT 2: Being Lot 5 on Plat 1, containing -5 acres."
        )
        skipped: list[mp_models.SkippedCourse] = []
        all_calls, tracts = extract_calls(deed, strict=False, skipped_courses=skipped)
        assert len(tracts) == 1
        assert len(all_calls) == 4
        for call in tracts[0].calls:
            assert any(
                part.startswith(INVALID_STATED_AREA_NOTE_PREFIX) for part in split_notes(call.notes)
            )
        for call in all_calls:
            assert any(
                part.startswith(INVALID_STATED_AREA_NOTE_PREFIX) for part in split_notes(call.notes)
            )
        results = verify_closure([], tracts=tracts)
        assert isinstance(results, list)
        assert not results[0].is_fully_verified()

    def test_uncovered_text_gaps_empty_intervals_returns_working(self) -> None:
        working = "   TRACT 1: Containing -5 acres.   "
        assert _uncovered_text_gaps(working, []) == ["TRACT 1: Containing -5 acres."]
        assert _uncovered_text_gaps(
            working, [("UNRELATED SEGMENT TEXT", "Tract 1", mp_models.TractType.MAIN)]
        ) == ["TRACT 1: Containing -5 acres."]
        assert _uncovered_text_gaps("   \n\t  ", []) == []


class TestFollowUpMalformedCurveElementsFailClosed:
    """#5: Fail closed on negative and scientific-notation curve elements & angles."""

    def test_leading_decimal_sci_notation_prefix_and_distance_rejected(self) -> None:
        assert extract_distance(".5e2 feet") == (0.0, "feet")
        assert extract_distance("100 feet and .5e2 feet") == (0.0, "feet")
        assert mp_metadata._is_malformed_length_prefix(".5e2", 3) is True

    def test_central_angle_sci_notation_never_extracts_exponent_as_delta(self) -> None:
        curve_text = (
            "THENCE along a curve to the right having a radius of 100 feet, "
            "central angle of 9e90 degrees, arc length of 157.08 feet"
        )
        info = extract_curve_info(curve_text)
        assert info.get("delta_deg") is None
        assert "malformed_element_error" in info

    @pytest.mark.parametrize(
        "curve_course",
        [
            "THENCE along a curve to the right having a radius of 100 feet, delta of 90 degrees, arc length -100 feet",
            "THENCE along a curve to the right having a radius of 100 feet, delta of 90 degrees, arc length -50.00 feet",
            "THENCE along a curve to the right having a radius of 100 feet, delta of 90 degrees, arc length 1e2 feet",
            "THENCE along a curve to the right having a radius of 100 feet, delta of 90 degrees, arc length .5e2 feet",
            "THENCE along a curve to the right having a radius of 100 feet, delta of 90 degrees, arc length = -50",
            "THENCE along a curve to the right having a radius of 100 feet, delta of 90 degrees, chord bearing N 45°00'00\" E, chord length -500.00 feet",
            "THENCE along a curve to the right having a radius of 100 feet, delta of 90 degrees, chord = -50",
            "THENCE along a curve to the right having a radius of -100 feet, delta of 90 degrees, arc length of 157.08 feet",
            "THENCE along a curve to the right having a radius of \u2212100 feet, delta of 90 degrees, arc length of 157.08 feet",
            "THENCE along a curve to the right having a radius of - 100 feet, delta of 90 degrees, arc length of 157.08 feet",
            "THENCE along a curve to the right having a radius of 100 feet, delta angle of -30 degrees, arc length of 52.36 feet",
            "THENCE along a curve to the right having a radius of 100 feet, delta angle of 1e2 degrees, arc length of 174.53 feet",
            "THENCE along a curve to the right having a radius of 100 feet, central angle of 9e90 degrees, arc length of 157.08 feet",
            "THENCE along a curve to the right having a radius of 100 feet, delta of .5e2 degrees, arc length of 87.27 feet",
            "THENCE along a curve to the right having a radius of 100 feet, .5e2 degrees, arc length of 87.27 feet",
            "THENCE along a curve to the right, radius point bears N 90°00'00\" E -100 feet, delta of 90 degrees, arc length of 157.08 feet",
        ],
    )
    def test_malformed_curve_elements_fail_closed_end_to_end(self, curve_course: str) -> None:
        deed = (
            "BEGINNING at an iron pin; "
            "THENCE N 0°00'00\" E, 100.00 feet; "
            f"{curve_course}; "
            "THENCE S 0°00'00\" W, 100.00 feet; "
            "THENCE N 90°00'00\" W, 200.00 feet to the point of beginning."
        )
        with pytest.raises(ValueError):
            extract_calls(deed, strict=True)
        skipped: list[mp_models.SkippedCourse] = []
        calls, _ = extract_calls(deed, strict=False, skipped_courses=skipped)
        assert len(skipped) == 1
        assert skipped[0].course == 2
        assert len(calls) == 3
        assert review_text(deed)["status"] != "checks_passed"

    def test_valid_curve_and_dms_bearings_unaffected(self) -> None:
        import re

        from mp_parse.numbers import COMMA_NUMBER

        assert re.findall(COMMA_NUMBER, "45°30'15\"") == ["45", "30", "15"]
        assert re.findall(COMMA_NUMBER, "N 45 E") == ["45"]
        assert re.findall(COMMA_NUMBER, "central angle of 9e90 degrees") == []

        deed = (
            "BEGINNING at an iron pin; "
            "THENCE N 45°30'15\" E, 100.00 feet; "
            "THENCE North 45 degrees East, 100.00 feet; "
            "THENCE along a curve to the right having a radius of 100.00 feet, "
            "delta of 45°30'15\", arc length of 79.42 feet to the point of beginning."
        )
        calls, _ = extract_calls(deed, strict=True)
        assert len(calls) == 3
        assert calls[1].bearing_azimuth_deg_from_north == pytest.approx(45.0)
        assert calls[2].radius_ft == pytest.approx(100.0)
        assert calls[2].delta_deg == pytest.approx(45.0 + 30.0 / 60.0 + 15.0 / 3600.0)
        assert calls[2].arc_length_ft == pytest.approx(79.42)


class TestFollowUpAreaSpacedMinusUnreadAndPerf:
    """#6 + #9: Broadened spaced minus, comma negative, leading-decimal unread, O(N) perf."""

    @pytest.mark.parametrize(
        ("text", "expected_sq_ft"),
        [
            ("Containing about - 10,000 square feet.", -10000.0),
            ("Containing nearly - 5 acres", -5.0 * 43560.0),
            ("Containing roughly \u2212 5 acres", -5.0 * 43560.0),
            ("Containing an area of - 5 acres", -5.0 * 43560.0),
            ("Containing a total of - 5 acres", -5.0 * 43560.0),
            ("Consisting of - 5 acres", -5.0 * 43560.0),
            ("Containing in all - 5 acres", -5.0 * 43560.0),
            ("Containing 10,000 sq ft or - 0.23 acres", -0.23 * 43560.0),
            ("Containing (- 5 acres)", -5.0 * 43560.0),
        ],
    )
    def test_broadened_spaced_minus_triggers(self, text: str, expected_sq_ft: float) -> None:
        info = extract_area_statement(text)
        assert info is not None
        assert info["value_sq_ft"] == pytest.approx(expected_sq_ft)

    @pytest.mark.parametrize(
        ("text", "expected_sq_ft"),
        [
            ("containing Lot 1 - 5 acres", 5.0 * 43560.0),
            ("containing Parcel A - 5 acres", 5.0 * 43560.0),
            ("containing area - 5 acres", 5.0 * 43560.0),
        ],
    )
    def test_separator_dashes_stay_positive(self, text: str, expected_sq_ft: float) -> None:
        info = extract_area_statement(text)
        assert info is not None
        assert info["value_sq_ft"] == pytest.approx(expected_sq_ft)

    def test_comma_spaced_negative_compound_component_fails_closed(self) -> None:
        info = extract_area_statement("Containing 10,000 sq ft, - 500 sq ft.")
        assert info is not None
        assert info["value_sq_ft"] <= 0.0
        assert info["unit"] == "compound"

    def test_leading_decimal_sci_notation_unread_component(self) -> None:
        info_area = extract_area_statement("Containing 10,000 sq ft and .5e4 sq ft.")
        assert info_area is None or info_area["value_sq_ft"] <= 0.0
        assert extract_area_statement("Containing 10,000 sq ft and .5e4 feet of frontage.") is None

    def test_extract_area_statement_linear_performance_on_3000_clauses(self) -> None:
        payload = "containing 1 acre; " * 3000
        start = time.perf_counter()
        info = extract_area_statement(payload)
        elapsed = time.perf_counter() - start
        assert info is not None
        assert info["value_sq_ft"] == pytest.approx(43560.0)
        assert elapsed < 0.05


class TestFollowUpSpacedUnaryMinusStraightDistances:
    """#7: Spaced unary minus in straight course distances fails closed."""

    @pytest.mark.parametrize(
        "text",
        [
            "N 0° E - 100 feet",
            "N 0° E \u2212 100 feet",
            "N 45°00'00\" E - 100.00 feet",
            "- 100 feet",
            "\u2212 100 feet",
            "- 100'",
            "\u2212 100'",
            "100' and - 5'",
            "100', - 5'",
            "100 feet and - 5 feet",
        ],
    )
    def test_spaced_unary_minus_distance_fails_closed(self, text: str) -> None:
        assert extract_distance(text) == (0.0, "feet")
        assert read_course_length(text).value == 0.0

    @pytest.mark.parametrize(
        "course", ["N 0°00'00\" E - 100.00 feet", "N 0°00'00\" E \u2212 100.00 feet"]
    )
    def test_spaced_unary_minus_blocks_review_text(self, course: str) -> None:
        deed = (
            "BEGINNING at an iron pin; "
            f"THENCE {course}; "
            "THENCE N 90°00'00\" E, 100.00 feet; "
            "THENCE S 0°00'00\" W, 100.00 feet; "
            "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning."
        )
        assert review_text(deed)["status"] != "checks_passed"


class TestFollowUpWindowedAlignmentAndBranches:
    """#8 + #14: Windowed linear alignment performance and branch coverage."""

    def test_large_multi_tract_spliced_easement_alignment_performance(self) -> None:
        def _make_tract(idx: int, courses: int, splice: str = "") -> tuple[str, str]:
            first_half = " ".join(
                "THENCE N 0°00'00\" E 100.00 feet;"
                if i % 2 == 0
                else "THENCE N 90°00'00\" E 100.00 feet;"
                for i in range(courses // 2)
            )
            second_half = " ".join(
                "THENCE S 0°00'00\" W 100.00 feet;"
                if i % 2 == 0
                else "THENCE N 90°00'00\" W 100.00 feet;"
                for i in range(courses // 2)
            )
            header = f"TRACT {idx}: BEGINNING at monument {idx};"
            tail = f"to the point of beginning of Tract {idx}."
            seg = f"{header} {first_half} {second_half} {tail}"
            full = f"{header} {first_half} {splice} {second_half} {tail}" if splice else seg
            return full, seg

        splice_text = "TOGETHER WITH an easement containing 0 acres across strip alpha beta gamma."
        full_parts: list[str] = []
        segments: list[tuple[str, str, mp_models.TractType]] = []
        for idx in range(1, 6):
            full, seg = _make_tract(idx, 200, splice=splice_text if idx == 1 else "")
            full_parts.append(full)
            segments.append((seg, f"Tract {idx}", mp_models.TractType.MAIN))
        working = "\n\n".join(full_parts)

        start = time.perf_counter()
        gaps = _uncovered_text_gaps(working, segments)
        elapsed = time.perf_counter() - start
        assert elapsed < 0.1
        assert any("containing 0 acres" in g.lower() for g in gaps)

    def test_alignment_branch_coverage_left_shift_out_of_order_and_trailing_gap(self) -> None:
        # Left-shift realignment across shared clause prefix
        working_left = "Alpha beta . Containing 0 acres . Containing 10 acres . Gamma delta ."
        seg_left = "Alpha beta . Containing 10 acres . Gamma delta ."
        assert _uncovered_text_gaps(
            working_left, [(seg_left, "Tract 1", mp_models.TractType.MAIN)]
        ) == ["Containing 0 acres ."]

        # Out-of-order fuzzy segment triggers from_zero retry
        working_ooo = (
            "TRACT 1: BEGINNING at pin alpha; THENCE N 0° E 100 feet to corner one. "
            "TRACT 2: BEGINNING at stake beta; THENCE N 90° E 200 feet to corner two. "
            "Containing -5 acres."
        )
        seg_two = "TRACT 2: BEGINNING at stake beta; THENCE N 90° E 200 ft to corner two."
        seg_one = "TRACT 1: BEGINNING at pin alpha; THENCE N 0° E 100 ft to corner one."
        gaps_ooo = _uncovered_text_gaps(
            working_ooo,
            [
                (seg_two, "Tract 2", mp_models.TractType.ADDITION),
                (seg_one, "Tract 1", mp_models.TractType.MAIN),
            ],
        )
        assert any("Containing -5 acres." in g for g in gaps_ooo)
        assert not any("BEGINNING at pin alpha" in g for g in gaps_ooo)


class TestFollowUpLinearRegexPerformance:
    """#10, #18, #19: Linear performance in prior conveyance, foot marks, and POB."""

    def test_extract_prior_conveyance_linear_on_all_three_adversarial_shapes(self) -> None:
        cases = [
            ("Deed Book 123 " * 3000 + ".5", "Deed Book 123"),
            ("Instrument Number 123 " * 3000 + "\nx", "Instrument Number 123"),
            ("BEING the same premises " * 3000 + "\nx", "BEING the same premises"),
        ]
        for payload, expected_prefix in cases:
            start = time.perf_counter()
            result = extract_prior_conveyance(payload)
            elapsed = time.perf_counter() - start
            assert elapsed < 0.02
            assert result is not None and result.startswith(expected_prefix)

    def test_has_malformed_foot_mark_linear_on_valid_foot_marks(self) -> None:
        payload = "100' " * 3000
        start = time.perf_counter()
        assert _has_malformed_foot_mark(payload) is False
        elapsed = time.perf_counter() - start
        assert elapsed < 0.05

    def test_extract_pob_linear_on_unterminated_repeated_openers(self) -> None:
        payload = "BEGINNING at 1.5 " * 3000 + "end"
        start = time.perf_counter()
        result = extract_pob(payload)
        elapsed = time.perf_counter() - start
        assert result == ""
        assert elapsed < 0.01


class TestFollowUpBearingEdgeCasesAndFiniteMessages:
    """#16, #22, #23: Tiny negative azimuth normalization and finite ValueError messages."""

    @pytest.mark.parametrize("_name,bearing_api", BEARING_IMPLS)
    def test_azimuth_to_quadrant_tiny_negative_normalizes_to_north_east(
        self, _name: str, bearing_api: Any
    ) -> None:
        assert bearing_api.azimuth_to_quadrant(-1e-17) == "N 0°00' E"

    @pytest.mark.parametrize("_name,bearing_api", BEARING_IMPLS)
    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_degree_of_curvature_and_missing_curve_elements_mention_finite(
        self, _name: str, bearing_api: Any, bad: float
    ) -> None:
        with pytest.raises(ValueError, match="finite"):
            bearing_api.degree_of_curvature_to_radius(bad)
        with pytest.raises(ValueError, match="finite"):
            bearing_api.calculate_missing_curve_elements(radius_ft=bad, delta_deg=30.0)
        with pytest.raises(ValueError, match="finite"):
            bearing_api.calculate_missing_curve_elements(radius_ft=100.0, arc_length_ft=bad)
        with pytest.raises(ValueError, match="finite"):
            bearing_api.calculate_missing_curve_elements(radius_ft=100.0, chord_length_ft=bad)
