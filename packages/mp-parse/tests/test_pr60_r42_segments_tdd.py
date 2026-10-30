"""PR #60 round 42: course segmentation never silently loses courses.

* Courses joined by "and" / "and running" after BEGINNING are separate courses.
* Text stating complete courses never yields zero calls without a raise or skip.
* Courses from COMMENCING to the point of beginning are tie-ins.
* A trailing separator conjunction is not part of a call's ``to``.
"""

from __future__ import annotations

import pytest
from mp_models import SkippedCourse
from mp_parse.calls import _extract_calls_from_text, _mark_commencement_tie_ins, extract_calls
from mp_parse.metadata import extract_along_to_fields
from mp_parse.normalizer import normalize_legal_description
from mp_verify.closure import verify_closure

AND_JOINED = (
    "BEGINNING at a pin and running N 45° E 100 feet to a pin and S 45° E 100 feet to a pin "
    "and S 45° W 100 feet to a pin and N 45° W 100 feet to the beginning."
)
SQUARE = [45.0, 135.0, 225.0, 315.0]


def _azimuths(calls):
    return [c.bearing_azimuth_deg_from_north for c in calls]


# --- 1a. "and" / "and running" after BEGINNING separates courses ---------------


def test_and_joined_courses_after_beginning_are_all_extracted_strict():
    calls, tracts = extract_calls(AND_JOINED)
    assert _azimuths(calls) == SQUARE
    assert [c.distance_ft for c in calls] == [100.0] * 4
    assert [c.to for c in calls] == ["a pin", "a pin", "a pin", "the beginning"]
    assert tracts == []
    assert verify_closure(calls).misclosure_ft < 0.01


def test_and_running_after_beginning_opens_the_first_course():
    text = (
        "BEGINNING at a pin and running N 45° E 100 feet to a pin; thence S 45° E 100 feet "
        "to a pin; thence S 45° W 100 feet to a pin; thence N 45° W 100 feet to the beginning."
    )
    calls, _ = extract_calls(text)
    assert _azimuths(calls) == SQUARE


def test_and_inside_along_or_to_wording_is_not_a_separator():
    text = (
        "BEGINNING at a pin and running N 45° E 100 feet along lands of Smith and Jones to a "
        "pin and S 45° E 100 feet to a pin and S 45° W 100 feet to a pin and N 45° W 100 feet "
        "to the beginning."
    )
    calls, _ = extract_calls(text)
    assert _azimuths(calls) == SQUARE
    assert calls[0].along == "lands of Smith and Jones"


def test_pob_tie_and_is_still_not_a_course():
    text = (
        "Beginning at a point distant N 2° W 955.85 feet along the East line of Section and "
        "S 87° W 1782.0 feet from the East 1/4 corner of Section 16, and proceeding thence "
        "S 87° W 138.0 feet; thence N 2° W 324.0 feet; thence N 87° E 138.0 feet; "
        "thence S 2° E 324.0 feet to the Point of Beginning."
    )
    normalized = normalize_legal_description(text)
    assert "Section and S 87° W" in normalized
    calls, _ = extract_calls(text)
    assert [c.distance_ft for c in calls] == [138.0, 324.0, 138.0, 324.0]


def test_and_running_normalization_is_idempotent():
    once = normalize_legal_description(AND_JOINED)
    assert normalize_legal_description(once) == once


# --- 1b. Complete courses never disappear without a raise or a skip ------------

HIDDEN_IN_BEGINNING = (
    "BEGINNING at a pin, N 45° E 100 feet to a pin; S 45° E 100 feet to a pin; "
    "S 45° W 100 feet to a pin; N 45° W 100 feet to the beginning."
)
HIDDEN_BEFORE_THENCE = (
    "BEGINNING at a pin, N 45° E 100 feet to a pin; thence S 45° E 100 feet to a pin; "
    "thence S 45° W 100 feet to a pin; thence N 45° W 100 feet to the beginning."
)


@pytest.mark.parametrize("text", [HIDDEN_IN_BEGINNING, HIDDEN_BEFORE_THENCE])
def test_course_inside_beginning_clause_raises_in_strict_mode(text):
    with pytest.raises(ValueError, match="BEGINNING"):
        extract_calls(text)
    with pytest.raises(ValueError, match="BEGINNING"):
        _extract_calls_from_text(text)


@pytest.mark.parametrize("text", [HIDDEN_IN_BEGINNING, HIDDEN_BEFORE_THENCE])
def test_course_inside_beginning_clause_is_skipped_in_non_strict_mode(text):
    skipped: list[SkippedCourse] = []
    calls, _ = extract_calls(text, strict=False, skipped_courses=skipped)
    assert skipped, "a course in the BEGINNING clause must be recorded"
    assert any("N 45° E 100 feet" in s.source_excerpt for s in skipped)
    assert all(s.error_type == "CourseInPreamble" for s in skipped)
    # A skipped course blocks closure verification.
    assert not verify_closure(calls, skipped_courses=skipped).geometry_verified


def test_numbered_courses_before_the_first_thence_are_extracted():
    # Sample 8 Kings Highway W (7489 - 772): courses 1 and 2 precede the first THENCE
    # and were silently stripped with the BEGINNING preamble. Round 42 failed closed;
    # round 43 splits the stripped preamble as the courses are, so each numbered course
    # is extracted, as the sample's ground truth expects.
    text = (
        "BEGINNING at a point in the line of Lot 10 and running;\n"
        "1. Along said line N 32° W, 41.23 feet to a point in same;\n"
        "2. Along the common line N 61° E, 82.47 feet to a point; thence\n"
        "3. Along said line S 28° E 36.73 feet to a point; thence\n"
        "4. Along said line S 58° W, 79.90 feet, to the point and place of BEGINNING."
    )
    calls, _ = extract_calls(text)
    assert [c.course for c in calls] == [1, 2, 3, 4]
    assert [c.distance_ft for c in calls] == [41.23, 82.47, 36.73, 79.9]
    skipped: list[SkippedCourse] = []
    extract_calls(text, strict=False, skipped_courses=skipped)
    assert skipped == []


def test_tie_locating_the_point_of_beginning_is_not_a_preamble_course():
    text = (
        "Beginning at a point in the line of Main Street, said point being S 59° W, a distance "
        "of 163.90 feet to a point in the line of Lot 11; thence N 45° E 100 feet to a pin; "
        "thence S 45° E 100 feet to a pin; thence S 45° W 100 feet to a pin; thence N 45° W "
        "100 feet to the point of beginning."
    )
    calls, _ = extract_calls(text)
    assert _azimuths(calls) == SQUARE


@pytest.mark.parametrize(
    "text",
    [
        AND_JOINED,
        HIDDEN_IN_BEGINNING,
        HIDDEN_BEFORE_THENCE,
        "COMMENCING at a pin, N 45° E 100 feet to a pin; S 45° E 100 feet to a pin.",
    ],
)
@pytest.mark.parametrize("strict", [True, False])
def test_complete_courses_never_yield_zero_calls_silently(text, strict):
    skipped: list[SkippedCourse] = []
    try:
        calls, _ = extract_calls(text, strict=strict, skipped_courses=skipped)
    except ValueError:
        assert strict
        return
    assert calls or skipped


# --- 2. COMMENCING tie-ins ------------------------------------------------------

COMMENCING = (
    "COMMENCING at the corner of X and Y; thence N 45° E 50 feet to the point of beginning; "
    "thence N 45° E 100 feet to a pin; thence S 45° E 100 feet to a pin; thence S 45° W 100 "
    "feet to a pin; thence N 45° W 100 feet to the point of beginning."
)


def test_commencing_courses_to_the_point_of_beginning_are_tie_ins():
    calls, _ = extract_calls(COMMENCING)
    assert [c.is_tie_in for c in calls] == [True, False, False, False, False]
    result = verify_closure(calls)
    assert result.misclosure_ft < 0.01


def test_commencing_tie_in_in_single_description_extraction():
    calls = _extract_calls_from_text(COMMENCING)
    assert [c.is_tie_in for c in calls] == [True, False, False, False, False]


def test_without_commencing_no_course_is_a_tie_in():
    text = COMMENCING.replace("COMMENCING at the corner of X and Y; thence N 45° E 50 feet", "")
    text = "BEGINNING at a pin" + text.removeprefix(" to the point of beginning")
    calls, _ = extract_calls(text)
    assert len(calls) == 4
    assert not any(c.is_tie_in for c in calls)


def test_no_tie_in_is_guessed_across_a_skipped_course():
    calls = _extract_calls_from_text(COMMENCING)
    unmarked = [c.model_copy(update={"is_tie_in": False}) for c in calls]
    marked = _mark_commencement_tie_ins(unmarked, COMMENCING, 1)
    assert [c.is_tie_in for c in marked] == [True, False, False, False, False]
    # Course 1 was skipped: the first call reaching the point of beginning may not be
    # the tie, so no boundary is guessed.
    gapped = [c.model_copy(update={"course": c.course + 1}) for c in unmarked]
    assert not any(c.is_tie_in for c in _mark_commencement_tie_ins(gapped, COMMENCING, 1))


def test_commencing_at_the_point_of_beginning_marks_no_tie_in():
    text = (
        "COMMENCING at a pin marking the point of beginning; thence N 45° E 100 feet to a pin; "
        "thence S 45° E 100 feet to a pin; thence S 45° W 100 feet to a pin; thence N 45° W "
        "100 feet to the point of beginning."
    )
    calls, _ = extract_calls(text)
    assert not any(c.is_tie_in for c in calls)


def test_commencing_tie_in_per_tract():
    text = (
        "TRACT 1: BEGINNING at a pin; thence N 45° E 100 feet to a pin; thence S 45° E 100 "
        "feet to a pin; thence S 45° W 100 feet to a pin; thence N 45° W 100 feet to the point "
        "of beginning. TRACT 2: " + COMMENCING
    )
    _, tracts = extract_calls(text)
    assert [c.is_tie_in for c in tracts[0].calls] == [False] * 4
    assert [c.is_tie_in for c in tracts[1].calls] == [True, False, False, False, False]


# --- 3. Trailing separator conjunction in "to" ---------------------------------


def test_trailing_and_before_thence_is_not_part_of_to():
    text = (
        "BEGINNING at a pin; thence N 45° E 100 feet to a pin; thence S 45° E 100 feet to a "
        "pin; thence S 45° W 100 feet to a pin and thence N 45° W 100 feet to the beginning."
    )
    calls, _ = extract_calls(text)
    assert [c.to for c in calls] == ["a pin", "a pin", "a pin", "the beginning"]


@pytest.mark.parametrize(
    ("call_text", "expected_to"),
    [
        ("S 45° W 100 feet to a pin and", "a pin"),
        ("S 45° W 100 feet to a pin, and running", "a pin"),
        ("S 45° W 100 feet to a pin &", "a pin"),
        ("S 45° W 100 feet to lands of Smith and Jones", "lands of Smith and Jones"),
        ("S 45° W 100 feet to a corner of Smith and Jones and", "a corner of Smith and Jones"),
    ],
)
def test_to_drops_only_the_trailing_separator(call_text, expected_to):
    assert extract_along_to_fields(call_text)[1] == expected_to
