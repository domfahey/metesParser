"""A course's length is only a length the course states as its own (round 43).

When every length in a course is an offset, tie, width or monument depth, the
course states no length and fails closed ("Missing boundary course distance"):
no fallback takes the first "N feet" as the course length. A length followed by
"back", "deep", "high", "above" or "below" is a monument's depth or position
only with monument context (a monument noun or "found"/"set" just before it, or
"grade"/"surface"/"ground" after "below"/"above"); otherwise "100 feet back to
the place of beginning" and "150 feet deep" (a lot depth) are course lengths.
"""

from __future__ import annotations

import pytest
from mp_models import SkippedCourse
from mp_parse import extract_calls, extract_single_call
from mp_parse.calls import extract_distance_alternate
from mp_parse.metadata import read_course_length

from metesparser.call_extractor import CallExtractor

STRICT = pytest.mark.parametrize("strict", [True, False], ids=["strict", "non-strict"])
SINGLE = pytest.mark.parametrize(
    "single", [extract_single_call, CallExtractor.extract_single_call], ids=["pkg", "mono"]
)
POB = "BEGINNING at a point; THENCE S 45° W 100 feet to a point; "
MISSING = "Missing boundary course distance"
AMBIGUOUS = "course length ambiguous"

# Every stated length is a non-course length: the course states no length.
NO_COURSE_LENGTH = {
    "monument-set-below-grade": (
        "thence N 45° W to an iron pin set 0.5 feet below grade at the point of beginning"
    ),
    "offset-off-fence": (
        "thence N 45° W along the line of Smith, 3 feet off the fence, to the point of beginning"
    ),
    "offset-distant-from": (
        "thence N 45° W along a line 25 feet distant from the fence to the point of beginning"
    ),
    "directed-tie": "thence N 45° W to a point 68 feet southeastwardly from a stone",
    "way-width": "thence N 45° W along a 50 feet wide right of way to the point of beginning",
    "distance-from-offset": "thence N 45° W at a distance of 50 feet from Main Street to a pin",
    "passing-station": "thence N 45° W passing a pin at 30 feet to a stone",
}
# Two course lengths ("2 feet from a fence" is not an offset): none is chosen.
AMBIGUOUS_CASES = {
    "from-fence-then-back": (
        "thence N 45° W along the line of Smith 2 feet from a fence 100 feet back "
        "to the point of beginning"
    ),
}
FAILS = {
    **{name: (text, MISSING) for name, text in NO_COURSE_LENGTH.items()},
    **{name: (text, AMBIGUOUS) for name, text in AMBIGUOUS_CASES.items()},
}
# "back"/"deep" without monument context: the course's own length.
COURSES = {
    "offset-then-deep": (
        "thence N 45° W along the line of Smith, 3 feet off the fence, 100 feet deep "
        "to the point of beginning",
        100.0,
    ),
    "back-to-beginning": ("thence N 45° W 100 feet back to the place of beginning", 100.0),
    "lot-depth": ("thence N 45° W 150 feet deep to a stake", 150.0),
    "monument-found-below-grade": (
        "thence N 45° W 100 feet to an iron pin found 0.5 feet below grade",
        100.0,
    ),
    "monument-noun-high": ("thence N 45° W 100 feet to a stone 4 feet high", 100.0),
    "monument-set-back": ("thence N 45° W 100 feet to a stake set 2 feet back", 100.0),
    # Lot-dimension idiom (15 E Euclid Ave ground truth): the stated breadth along
    # the line is the course length, as "in length or depth" is.
    "width-or-breadth": (
        "thence N 45° W along the Northwesterly line of Euclid Avenue 80 feet in width or breadth",
        80.0,
    ),
    # The first length, "at a distance of N feet" without "from": the course's own
    # length (formerly read only by the removed fallback).
    "at-a-distance-of": ("thence N 45° W at a distance of 100 feet to a pin", 100.0),
    "comma-at-a-distance-of": ("thence N 45° W, at a distance of 100.00 feet, to a stake", 100.0),
    "below-the-surface": (
        "thence N 45° W 100 feet to a point 3 feet below the surface",
        100.0,
    ),
}


@SINGLE
@pytest.mark.parametrize("name", sorted(FAILS))
def test_single_call_fails_closed(single, name: str) -> None:
    text, match = FAILS[name]
    with pytest.raises(ValueError, match=match):
        single(text, 1)


@pytest.mark.parametrize("name", sorted(FAILS))
def test_description_fails_closed(name: str) -> None:
    text, match = FAILS[name]
    with pytest.raises(ValueError, match=match):
        extract_calls(POB + text + ".", strict=True)
    skipped: list[SkippedCourse] = []
    calls, _ = extract_calls(POB + text + ".", strict=False, skipped_courses=skipped)
    assert [s.course for s in skipped] == [2]
    assert match in skipped[0].error
    assert [c.distance_ft for c in calls] == [100.0]


@SINGLE
@pytest.mark.parametrize("name", sorted(COURSES))
def test_single_call_reads_course_length(single, name: str) -> None:
    text, expected = COURSES[name]
    call = single(text, 1)
    assert call is not None
    assert call.distance_ft == expected


@STRICT
@pytest.mark.parametrize("name", sorted(COURSES))
def test_description_reads_course_length(name: str, strict: bool) -> None:
    text, expected = COURSES[name]
    calls, _ = extract_calls(POB + text + ".", strict=strict)
    assert [c.distance_ft for c in calls] == [100.0, expected]


@pytest.mark.parametrize("name", sorted(COURSES))
def test_read_course_length_reads_back_and_deep_by_context(name: str) -> None:
    text, expected = COURSES[name]
    reading = read_course_length(text)
    assert (reading.value, reading.ambiguous) == (expected, ())


@pytest.mark.parametrize("name", sorted(NO_COURSE_LENGTH))
def test_alternate_reader_respects_roles(name: str) -> None:
    assert extract_distance_alternate(NO_COURSE_LENGTH[name]) == 0.0
    assert CallExtractor.extract_distance_alternate(NO_COURSE_LENGTH[name]) == 0.0
