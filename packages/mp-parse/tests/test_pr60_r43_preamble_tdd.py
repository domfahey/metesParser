"""PR #60 round 43: a course before the first THENCE is never silently lost.

The text dropped as a BEGINNING/COMMENCING preamble (before the first THENCE, or a
fragment ``split_into_calls`` drops) is split exactly as the courses are and read by
the course parser itself:

* a course in its own clause (";", a numbered line, or after "running") is extracted;
* a course that cannot be separated from the BEGINNING clause fails closed
  (``CourseInPreamble``);
* wording the course parser reads as a tie locating the point is not a course.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mp_models import SkippedCourse
from mp_parse import calls as calls_module
from mp_parse.calls import _extract_calls_from_text, extract_calls
from mp_parse.metadata import CallFragment, split_call_fragments, split_into_calls
from mp_verify.closure import verify_closure

SQUARE = [45.0, 135.0, 225.0, 315.0]
REST = (
    "thence S 45° E 100 feet to a pin; thence S 45° W 100 feet to a pin; "
    "thence N 45° W 100 feet to the point of beginning."
)
SAMPLES = Path(__file__).resolve().parents[3] / "sample_deeds"


def _azimuths(calls):
    return [c.bearing_azimuth_deg_from_north for c in calls]


# --- 1. The tie wording of the BEGINNING clause does not hide a later course ------

TIE_WORD_BEFORE_COURSE = (
    "BEGINNING at an iron pin being the northeast corner of Lot 5; N 45° E 100 feet to a "
    "pin; " + REST
)


@pytest.mark.parametrize("strict", [True, False])
def test_course_after_a_beginning_clause_with_tie_wording_is_extracted(strict):
    skipped: list[SkippedCourse] = []
    calls, _ = extract_calls(TIE_WORD_BEFORE_COURSE, strict=strict, skipped_courses=skipped)
    assert _azimuths(calls) == SQUARE
    assert [c.course for c in calls] == [1, 2, 3, 4]
    assert skipped == []
    assert verify_closure(calls).misclosure_ft < 0.01


# --- 2. A preamble course needs no "to" destination ------------------------------

NO_DESTINATION_SEMICOLON = "BEGINNING at a pin; N 45° E 100 feet along Main Street; " + REST
NO_DESTINATION_RUNNING = "BEGINNING at a pin, running N 45° E 100 feet along Main Street, " + REST


@pytest.mark.parametrize("text", [NO_DESTINATION_SEMICOLON, NO_DESTINATION_RUNNING])
@pytest.mark.parametrize("strict", [True, False])
def test_course_without_destination_after_beginning_is_extracted(text, strict):
    skipped: list[SkippedCourse] = []
    calls, _ = extract_calls(text, strict=strict, skipped_courses=skipped)
    assert _azimuths(calls) == SQUARE
    assert calls[0].distance_ft == 100.0
    assert calls[0].along == "Main Street"
    assert skipped == []
    assert verify_closure(calls).misclosure_ft < 0.01


@pytest.mark.parametrize(
    "text",
    [
        "BEGINNING at a pin, running N 45° E 100 feet to a pin, " + REST,
        "BEGINNING at a pin and running; N 45° E 100 feet to a pin; " + REST,
        "BEGINNING at a pin; and running N 45° E 100 feet to a pin; " + REST,
    ],
)
def test_course_in_its_own_running_clause_is_course_one(text):
    calls = _extract_calls_from_text(text)
    assert _azimuths(calls) == SQUARE
    assert [c.course for c in calls] == [1, 2, 3, 4]
    assert calls[0].to == "a pin"


# --- 3. Numbered courses before the first THENCE (ground truth) -------------------

KINGS = "8 Kings Highway W - Deed Image (7489 - 772)"


def test_numbered_courses_before_the_first_thence_match_ground_truth():
    md = (SAMPLES / f"{KINGS}.md").read_text()
    truth = json.loads((SAMPLES / f"{KINGS}.ground_truth.json").read_text())["expected_calls"]
    calls, _ = extract_calls(md)
    assert [c.course for c in calls] == [t["course"] for t in truth]
    assert [c.distance_ft for c in calls] == [t["distance_ft"] for t in truth]
    assert [round(c.bearing_azimuth_deg_from_north, 4) for c in calls] == [
        t["bearing_azimuth_deg_from_north"] for t in truth
    ]
    assert calls[0].to == "a point in same"


# --- 4. Fail closed when the course cannot be separated; ties stay ties -----------


@pytest.mark.parametrize(
    "text",
    [
        "BEGINNING at a pin, N 45° E 100 feet along Main Street; thence S 45° E 100 feet to a pin.",
        "COMMENCING at a pin, N 45° E 100 feet; S 45° E 100 feet to a pin.",
    ],
)
def test_course_joined_to_the_beginning_clause_by_a_comma_fails_closed(text):
    with pytest.raises(ValueError, match="BEGINNING/COMMENCING clause states a course"):
        extract_calls(text)
    skipped: list[SkippedCourse] = []
    extract_calls(text, strict=False, skipped_courses=skipped)
    assert skipped[0].error_type == "CourseInPreamble"
    assert "N 45° E 100 feet" in skipped[0].source_excerpt


@pytest.mark.parametrize(
    "preamble",
    [
        "Beginning at a point in the line of Main Street; said point being S 59° W 163.90 "
        "feet from the corner of Lot 11; ",
        "BEGINNING at a point in the Northerly line of Main Street, distant 100 feet "
        "Westerly from the corner of Elm Street; ",
        "BEGINNING at a point distant N 2° W 955.85 feet from the East 1/4 corner; ",
        # MIWAYN-50020-01181 / MIWAYN-50510-00079: ties joined by "and" up to "from".
        "beginning at a point distant S 89° W 1,304.76 feet along the South line of said "
        "Section, and N 0° W 785.57 feet, and N 89° E 493.11 feet from the Southeast "
        "corner of Section 7, and proceeding ",
        "Beginning N 02° E, 924.11 feet and S 84° E, 60.09 feet from the West 1/4 corner "
        "of Section 28; ",
    ],
)
def test_tie_locating_the_point_of_beginning_is_not_a_course(preamble):
    text = preamble + "thence N 45° E 100 feet to a pin; " + REST
    calls, _ = extract_calls(text)
    assert _azimuths(calls) == SQUARE


TIE_SERIES = (
    "BEGINNING at a point in Main Street, said point being the following courses and "
    "distances from the corner of Lot 11: N 10° E 50 feet to a pin; S 20° E 40 feet to a "
    "pin; N 5° W 10 feet to the point of beginning; "
)


def test_tie_series_in_its_own_clauses_reaching_the_point_of_beginning_is_a_tie():
    calls, _ = extract_calls(TIE_SERIES + "thence N 45° E 100 feet to a pin; " + REST)
    assert _azimuths(calls) == SQUARE


def test_course_after_a_locating_clause_without_closing_fails_closed():
    # Tie or first course? The text does not say, so nothing is guessed.
    text = (
        "BEGINNING at a point distant 50 feet from the corner of Lot 11; N 10° E 50 feet "
        "to a pin; " + REST
    )
    with pytest.raises(ValueError, match="BEGINNING/COMMENCING clause states a course"):
        extract_calls(text)
    skipped: list[SkippedCourse] = []
    calls, _ = extract_calls(text, strict=False, skipped_courses=skipped)
    assert [(s.course, s.error_type) for s in skipped] == [(1, "CourseInPreamble")]
    assert [c.course for c in calls] == [2, 3, 4]


def test_malformed_course_in_its_own_clause_fails_closed():
    text = "BEGINNING at a pin; N 45° E 100 feet, 120 feet to a pin; " + REST
    with pytest.raises(ValueError, match="N 45° E 100 feet, 120 feet"):
        extract_calls(text)
    skipped: list[SkippedCourse] = []
    calls, _ = extract_calls(text, strict=False, skipped_courses=skipped)
    assert [s.course for s in skipped] == [1]
    assert [c.course for c in calls] == [2, 3, 4]


# --- 5. One splitter: split_into_calls reports the fragments it drops -------------


def test_split_call_fragments_reports_dropped_preamble_fragments():
    text = "BEGINNING at a pin, N 45° E 100 feet to a pin; S 45° E 100 feet to a pin"
    fragments = split_call_fragments(text)
    assert fragments == [
        CallFragment("BEGINNING at a pin, N 45° E 100 feet to a pin", preamble=True),
        CallFragment("S 45° E 100 feet to a pin", preamble=False),
    ]
    assert split_into_calls(text) == [f.text for f in fragments if not f.preamble]


def test_preamble_course_grammar_is_not_reimplemented():
    for name in ("_PREAMBLE_COURSE", "_PREAMBLE_NUMBERED_SPLIT", "_courses_in_preamble"):
        assert not hasattr(calls_module, name)
