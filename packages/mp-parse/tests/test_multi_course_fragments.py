"""No complete boundary course is ever lost inside one split call fragment.

After splitting, every call fragment is scanned for complete boundary courses (a
course-form bearing followed by a distance; chord and radial clause bearings and
lengths are curve elements, not courses). A fragment holding several is split on
';' when every piece is itself one complete course; otherwise strict extraction
raises and non-strict extraction records the fragment as a SkippedCourse.
Course-list headers also accept 'in the following', 'the next N courses' and
letter enumerators (a), (b), (c).
"""

from __future__ import annotations

from typing import NamedTuple

import pytest
from mp_models import SkippedCourse
from mp_parse import extract_calls, extract_single_call
from mp_parse.calls import _expand_compact_dms

STRICT = pytest.mark.parametrize("strict", [True, False], ids=["strict", "non-strict"])
POB = "BEGINNING at a point; "
SQUARE = [45.0, 135.0, 225.0, 315.0]


class Case(NamedTuple):
    text: str
    azimuths: list[float | None] | None  # None: the tract fails closed
    skipped: list[str] = []  # non-strict SkippedCourse error types


CASES = {
    "in-the-following-header": Case(
        POB + "THENCE in the following four courses: (1) N 45° E 100 feet; "
        "(2) S 45° E 100 feet; (3) S 45° W 100 feet; (4) N 45° W 100 feet",
        SQUARE,
    ),
    "next-n-courses-letter-enumerators": Case(
        POB + "THENCE the next two (2) courses: (a) N 45° E 100 feet; (b) S 45° E 100 feet; "
        "THENCE S 45° W 100 feet; THENCE N 45° W 100 feet",
        SQUARE,
    ),
    "letter-enumerators-after-thence": Case(
        POB + "THENCE (a) N 45° E 100 feet; (b) S 45° E 100 feet; (c) S 45° W 100 feet; "
        "THENCE N 45° W 100 feet",
        SQUARE,
    ),
    "semicolon-courses-in-one-thence": Case(
        POB + "THENCE N 45° E 100 feet; S 45° E 100 feet; THENCE S 45° W 100 feet",
        [45.0, 135.0, 225.0],
    ),
    "semicolon-courses-with-trailing-description": Case(
        POB + "THENCE N 45° E 100 feet to a pin; S 45° E 100 feet; along the road; "
        "THENCE S 45° W 100 feet",
        [45.0, 135.0, 225.0],
    ),
    "one-course-per-line": Case("N 45° E 100 ft\n\nS 45° W 100 ft", [45.0, 225.0]),
    "juxtaposed-courses-after-thence": Case(
        POB + "THENCE N 45° E 100 feet S 45° E 100 feet; THENCE S 45° W 100 feet",
        [45.0, 135.0, 225.0],
    ),
    # A tie to a point is not a second course (test_course_roles.py).
    "tie-to-a-point-is-not-a-course": Case(
        POB + "THENCE N 45° E 100 feet to a point which is S 10° E 25 feet from a stone; "
        "THENCE S 45° W 100 feet",
        [45.0, 225.0],
    ),
    "juxtaposed-after-a-tie-length-fails-closed": Case(
        POB + "THENCE N 61° E 10 feet to a point distant 10 feet S 27° E running parallel "
        "with the first course 158 feet to a pin; THENCE S 45° W 100 feet",
        None,
        ["MultipleCoursesError"],
    ),
    "out-of-sequence-enumerator-fails-closed": Case(
        POB + "THENCE the following courses: (1) N 45° E 100 feet; (2) S 45° E 100 feet; "
        "(10) S 45° W 100 feet",
        None,
        ["MultipleCoursesError"],
    ),
    "unsplittable-comma-courses-fail-closed": Case(
        POB + "THENCE N 45° E 100 feet, S 45° E 100 feet; THENCE S 45° W 100 feet",
        None,
        ["MultipleCoursesError"],
    ),
    "bearing-only-piece-fails-closed": Case(
        POB + "THENCE N 45° E 100 feet; S 45° E to a pin; S 45° W 100 feet; "
        "THENCE N 45° W 100 feet",
        None,
        ["MultipleCoursesError"],
    ),
    # Negatives: one course each, nothing split or rejected.
    "curve-with-chord-bearing-and-length": Case(
        POB + "THENCE along a curve to the right having a radius of 500.00 feet, an arc "
        "length of 100.00 feet, a chord bearing N 50° E and a chord length of 99.83 feet; "
        "THENCE S 45° W 100 feet",
        [None, 225.0],
    ),
    "tangent-curve-with-chord-clause": Case(
        POB + "THENCE N 45° E along a curve to the right having a radius of 500.00 feet, "
        "an arc length of 100.00 feet, the chord of which bears N 50° E 99.83 feet; "
        "THENCE S 45° W 100 feet",
        [45.0, 225.0],
    ),
    "curve-with-radial-clause": Case(
        POB + "THENCE along a curve to the left whose radius point bears N 10° W 300.00 feet, "
        "an arc distance of 50.00 feet; THENCE S 45° W 100 feet",
        [None, 225.0],
    ),
    "later-beginning-tie-is-not-a-course": Case(
        POB + "THENCE N 45° E 100 feet; THENCE S 45° W 100 feet to the point of beginning. "
        "Beginning at a point in the line of Lot 10, said point being N 32° W 81.33 feet "
        "from the corner",
        [45.0, 225.0],
    ),
    "witness-bearing-is-not-a-course": Case(
        POB + "THENCE N 45° E 100 feet to a stone from which a white oak bears S 10° E "
        "12 feet; THENCE S 45° W 100 feet",
        [45.0, 225.0],
    ),
}


def _run(text: str, strict: bool):
    skipped: list[SkippedCourse] = []
    calls, _ = extract_calls(text, strict=strict, skipped_courses=skipped)
    return calls, skipped


@STRICT
@pytest.mark.parametrize("name", sorted(CASES))
def test_no_complete_course_is_lost(name: str, strict: bool) -> None:
    case = CASES[name]
    if case.azimuths is None:
        if strict:
            with pytest.raises(ValueError, match="fragment contains multiple courses"):
                _run(case.text, strict)
            return
        calls, skipped = _run(case.text, strict)
        assert [s.error_type for s in skipped] == case.skipped
        assert "fragment contains multiple courses" in skipped[0].error
        return
    calls, skipped = _run(case.text, strict)
    assert [c.bearing_azimuth_deg_from_north for c in calls] == case.azimuths
    assert [c.course for c in calls] == list(range(1, len(case.azimuths) + 1))
    assert [s.error_type for s in skipped] == case.skipped


def test_skipped_multi_course_fragment_keeps_its_text_and_number() -> None:
    _calls, skipped = _run(CASES["unsplittable-comma-courses-fail-closed"].text, False)
    assert skipped[0].course == 1
    assert skipped[0].source_excerpt == "N 45° E 100 feet, S 45° E 100 feet"


def test_extract_single_call_rejects_a_fragment_with_two_courses() -> None:
    with pytest.raises(ValueError, match="fragment contains multiple courses"):
        extract_single_call("N 45° E 100 feet, S 45° E 100 feet", 1)


def test_extract_single_call_keeps_a_curve_with_chord_and_radial_elements() -> None:
    call = extract_single_call(
        "along a curve to the left whose radius point bears N 10° W 300.00 feet, an arc "
        "distance of 50.00 feet, the chord of which bears N 50° E 49.9 feet",
        1,
    )
    assert call is not None and call.distance_ft == pytest.approx(50.0)


# --- dashed bearings: any lead word, except an identifier label ------------------------


@STRICT
@pytest.mark.parametrize("lead", ["northeasterly", "continuing", "still", "along", "running"])
def test_dashed_bearing_after_any_lead_word_is_read(lead: str, strict: bool) -> None:
    calls, skipped = _run(f"{POB}THENCE {lead} N 45-30 E 100 feet; THENCE S 45° W 100 feet", strict)
    assert [c.bearing_azimuth_deg_from_north for c in calls] == [45.5, 225.0]
    assert skipped == []


@pytest.mark.parametrize(
    "text",
    [
        "Lot N 12-3 E",
        "along Lot N 12-3 E",
        "Block S 4-15 W",
        "Route N 9-1 E",
        "No. N 12-3 E",
        "# S 2-10 W",
        "Parcel A N 12-3 E",
        "Section 12 N 1-2 E",
        "Book 1234 Page N 12-3 E",
    ],
)
def test_identifier_labels_are_never_dashed_bearings(text: str) -> None:
    assert _expand_compact_dms(text) == text


# --- course-count mismatch identifies the header -----------------------------------------

MISCOUNTED = (
    POB + "THENCE the following three courses: (1) N 45° E 100 feet; (2) S 45° E 100 feet; "
    "THENCE S 45° W 100 feet to the point of beginning"
)


def test_count_mismatch_strict_names_the_header_not_the_tract() -> None:
    with pytest.raises(ValueError) as raised:
        _run(MISCOUNTED, True)
    message = str(raised.value)
    assert "'THENCE the following three courses:'" in message
    assert "states 3 courses but 2 were found" in message
    assert "S 45° W 100 feet" not in message


def test_count_mismatch_record_excerpt_is_the_header() -> None:
    calls, skipped = _run(MISCOUNTED, False)
    assert len(calls) == 3
    (skip,) = skipped
    assert skip.error_type == "CourseCountMismatch"
    assert skip.source_excerpt == "THENCE the following three courses:"
    assert "states 3 courses but 2 were found" in skip.error
