"""A record call never claims the course length, and a lone labelled pair is the course.

A bearing inside a parenthetical or bracketed record call ("(deed N 44° E)")
must not take the length of the bearing outside it. A fragment's only
bearing+length pair is the boundary course, whatever record label follows it; a
record label makes a pair a record call only when another boundary pair exists.
With "(R)"/"(M)" labels the measured or unlabelled pair is the course. Record
bearings and distances are kept verbatim in notes, never silently dropped.
"""

from __future__ import annotations

import pytest
from mp_parse import extract_calls, extract_single_call
from mp_parse.calls import MultipleCoursesError

POB = "BEGINNING at a point; "
CLOSING = "; THENCE S 45° W 100 feet to the point of beginning."
STRICT = pytest.mark.parametrize("strict", [True, False], ids=["strict", "non-strict"])

# fragment -> (azimuth, distance_ft, notes)
COURSES = {
    "paren-deed-bearing": (
        "thence N 45° E (deed N 44° E) 100 feet",
        45.0,
        100.0,
        "record call: (deed N 44° E)",
    ),
    "paren-record-bearing": (
        "thence N 45° E (record N 44° E) 100.00 feet to a pin",
        45.0,
        100.0,
        "record call: (record N 44° E)",
    ),
    "lone-per-deed": ("thence N 45° E 100 feet per deed to a pin", 45.0, 100.0, None),
    "lone-of-record": ("thence N 45° E 100 feet of record to a pin", 45.0, 100.0, None),
    "lone-R": ("thence N 45° E 100 feet (R) to a pin", 45.0, 100.0, None),
    "R-then-M": (
        "thence N 45°10' E 100.00 feet (R), N 45°05' E 100.05 feet (M) to a pin",
        45.0 + 5.0 / 60.0,
        100.05,
        "record call: N 45°10' E 100.00 feet (R)",
    ),
    "M-then-R": (
        "thence N 45°05' E 100.05 feet (M), N 45°10' E 100.00 feet (R) to a pin",
        45.0 + 5.0 / 60.0,
        100.05,
        "record call: N 45°10' E 100.00 feet (R)",
    ),
    "bracketed-deed": (
        "thence N 45° E 100 feet [N 44° E 99 feet deed] to a pin",
        45.0,
        100.0,
        "record call: [N 44° E 99 feet deed]",
    ),
    "paren-record-distance": (
        "thence N 45° E 100.00 feet (deed 99.5 feet) to a pin",
        45.0,
        100.0,
        "record call: (deed 99.5 feet)",
    ),
    "paren-formerly": (
        "thence N 45° E 100 feet (formerly N 44° E 99 feet) to a pin",
        45.0,
        100.0,
        "record call: (formerly N 44° E 99 feet)",
    ),
}


@pytest.mark.parametrize("name", sorted(COURSES))
def test_record_call_fragment_is_one_course(name: str) -> None:
    fragment, azimuth, distance, _ = COURSES[name]
    call = extract_single_call(fragment, 1)
    assert call is not None
    assert call.bearing_azimuth_deg_from_north == pytest.approx(azimuth)
    assert call.distance_ft == pytest.approx(distance)


@pytest.mark.parametrize("name", sorted(COURSES))
def test_record_call_wording_kept_in_notes(name: str) -> None:
    fragment, _, _, notes = COURSES[name]
    call = extract_single_call(fragment, 1)
    assert call is not None
    assert call.notes == notes


@STRICT
@pytest.mark.parametrize("name", sorted(COURSES))
def test_record_call_fragment_in_description(name: str, strict: bool) -> None:
    fragment, azimuth, distance, notes = COURSES[name]
    calls, _ = extract_calls(POB + fragment + CLOSING, strict=strict)
    assert len(calls) == 2
    assert calls[0].bearing_azimuth_deg_from_north == pytest.approx(azimuth)
    assert calls[0].distance_ft == pytest.approx(distance)
    assert calls[0].notes == notes


@pytest.mark.parametrize(
    "fragment",
    [
        "thence N 45° E 100 feet, N 50° E 80 feet to a pin",
        "thence N 45° E 100 feet (R), N 50° E 80 feet (R) to a pin",
    ],
)
def test_merged_courses_still_rejected(fragment: str) -> None:
    with pytest.raises(MultipleCoursesError):
        extract_single_call(fragment, 1)


def test_merged_courses_still_split_in_description() -> None:
    text = POB + "thence N 45° E 100 feet; N 50° E 80 feet to a pin" + CLOSING
    calls, _ = extract_calls(text, strict=True)
    assert [c.distance_ft for c in calls] == [100.0, 80.0, 100.0]


def test_tie_remains_a_tie() -> None:
    call = extract_single_call(
        "thence N 45° E 100 feet to a pin, which bears N 10° E 5 feet from a stone", 1
    )
    assert call is not None
    assert call.bearing_azimuth_deg_from_north == pytest.approx(45.0)
    assert call.distance_ft == pytest.approx(100.0)
    assert call.notes is None
    assert call.to == "a pin, which bears N 10° E 5 feet from a stone"


@pytest.mark.parametrize(
    "fragment",
    [
        "thence N 45° E 100 feet along Main Street (formerly Caldwell Avenue - 100.00 feet wide)",
        "thence N 45° E 100 feet to a point (see plan 12 feet) in the road",
    ],
)
def test_bracketed_widths_are_not_record_calls(fragment: str) -> None:
    call = extract_single_call(fragment, 1)
    assert call is not None
    assert call.distance_ft == pytest.approx(100.0)
    assert call.notes is None
