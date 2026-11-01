"""One length-number grammar: fractions are read whole or not at all (PR #60 r36)."""

from __future__ import annotations

import re

import pytest
from mp_parse.calls import extract_calls, extract_curve_info, extract_single_call
from mp_parse.metadata import extract_distance, read_course_length
from mp_parse.units import LENGTH_NUMBER, parse_number

_BEARING = "N 45° E"

# --- units: parse_number and LENGTH_NUMBER --------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("100", 100.0),
        ("100.25", 100.25),
        ("1,200.50", 1200.5),
        ("100 1/2", 100.5),
        ("100-1/2", 100.5),
        ("100 - 1/2", 100.5),
        ("1,200 1/4", 1200.25),
        ("3/4", 0.75),
        ("1⁄2", 0.5),
        ("½", 0.5),
        ("¾", 0.75),
        ("⅛", 0.125),
        ("6½", 6.5),
        ("6 ¼", 6.25),
    ],
)
def test_parse_number_reads_every_number_form(text: str, value: float) -> None:
    assert parse_number(text) == pytest.approx(value)


@pytest.mark.parametrize("text", ["", "abc", "1/0", "100.5 1/2", "1/2/3", "100 1/2 3/4", "1/"])
def test_parse_number_rejects_fragments(text: str) -> None:
    with pytest.raises(ValueError):
        parse_number(text)


@pytest.mark.parametrize(
    ("text", "numbers"),
    [
        ("100 1/2 feet", ["100 1/2"]),
        ("100-1/2 feet", ["100-1/2"]),
        ("3/4 mile", ["3/4"]),
        ("6½ inches", ["6½"]),
        ("1,200 feet", ["1,200"]),
        # A half-read number is no number at all, never a fragment of one.
        ("100.5 1/2 feet", []),
        ("100.5  1/2 feet", []),
        ("1/2/3 feet", []),
        ("100 1/0 feet", []),
        ("100, 1/2 mile", ["100"]),
    ],
)
def test_length_number_never_starts_or_stops_inside_a_fraction(
    text: str, numbers: list[str]
) -> None:
    assert [m.group(0) for m in re.finditer(LENGTH_NUMBER, text)] == numbers


# --- straight-course lengths -----------------------------------------------------------

_COURSE_LENGTHS = [
    ("100 1/2 feet", 100.5),
    ("100-1/2 feet", 100.5),
    ("100 - 1/2 feet", 100.5),
    ("100½ feet", 100.5),
    ("1,200 1/4 feet", 1200.25),
    ("3/4 mile", 3960.0),
    ("½ mile", 2640.0),
    ("2 1/2 chains", 165.0),
    ("10 3/4 rods", 177.375),
    ("10 feet 6-1/2 inches", 10 + 6.5 / 12),
    ("10 feet 6 1/2 inches", 10 + 6.5 / 12),
    ("10 feet 6½ inches", 10 + 6.5 / 12),
    ("10 feet 6.5 inches", 10 + 6.5 / 12),
    ("100 feet 6 inches", 100.5),
    ('100 feet 6"', 100.5),
    ("100 feet 6″", 100.5),
    ('100 feet, 6"', 100.5),
    ('100 feet 6 1/2"', 100 + 6.5 / 12),
    ("100' 6\"", 100.5),
    ("100 1/2'", 100.5),
]


@pytest.mark.parametrize(("length", "feet"), _COURSE_LENGTHS)
def test_course_length_reads_the_whole_number(length: str, feet: float) -> None:
    call = extract_single_call(f"thence {_BEARING} {length} to a point", 1)
    assert call is not None
    assert call.distance_ft == pytest.approx(feet)


@pytest.mark.parametrize(
    ("text", "value", "unit"),
    [
        ("100 1/2 feet", 100.5, "feet"),
        ("3/4 mile", 0.75, "miles"),
        ("2¼ chains", 2.25, "chains"),
    ],
)
def test_extract_distance_reads_fractions(text: str, value: float, unit: str) -> None:
    assert extract_distance(f"{_BEARING} {text} to a point") == (pytest.approx(value), unit)


@pytest.mark.parametrize(
    "length",
    [
        "100.5 1/2 feet",
        "100 1/2/3 feet",
        "100 1/0 feet",
        "1/2/3 mile",
        "6 inches 10 feet",
        "6 1/2 inches 10 feet",
        '100 feet 15"',
        '100 feet and 6"',
    ],
)
def test_unreadable_or_ascending_length_fails_closed(length: str) -> None:
    text = f"thence {_BEARING} {length} to a point"
    reading = read_course_length(f"{_BEARING} {length} to a point")
    assert reading.value == 0.0
    with pytest.raises(ValueError):
        extract_single_call(text, 1)


def test_ascending_inch_compound_is_ambiguous() -> None:
    reading = read_course_length(f"{_BEARING} 6 inches 10 feet to a point")
    assert reading.ambiguous == ("6 inches", "10 feet")


def test_inch_mark_after_bearing_minutes_stays_seconds() -> None:
    call = extract_single_call("thence N 45° 30' 15\" E 100 feet to a point", 1)
    assert call is not None
    assert call.distance_ft == 100.0
    assert call.bearing_azimuth_deg_from_north == pytest.approx(45 + 30 / 60 + 15 / 3600)


def test_fractional_monument_size_is_not_a_length() -> None:
    for tail in ('100 feet to a 3/4" iron pipe', "100 feet to a 3/4 inch iron pipe"):
        call = extract_single_call(f"thence {_BEARING} {tail}", 1)
        assert call is not None
        assert call.distance_ft == 100.0


def test_fractional_lengths_in_extract_calls() -> None:
    skipped: list = []
    calls, _ = extract_calls(
        "Beginning at a point; thence N 45° E 100 1/2 feet to a pin; "
        "thence S 45° E 3/4 mile to a pin; thence S 45° W 10 feet 6-1/2 inches to a pin.",
        skipped_courses=skipped,
    )
    assert skipped == []
    assert [c.distance_ft for c in calls] == pytest.approx([100.5, 3960.0, 10 + 6.5 / 12])


def test_fractional_tie_length_is_not_the_course_length() -> None:
    call = extract_single_call(
        f"thence {_BEARING} 100 1/2 feet to a pin, said pin being 2 1/2 feet from a wall", 1
    )
    assert call is not None
    assert call.distance_ft == 100.5


# --- curve elements --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "curving to the right with a radius of 50 1/2 feet and a delta of 10°",
            {"radius_ft": 50.5, "delta_deg": 10.0},
        ),
        (
            "curving to the right with a radius of 50-1/2 feet, an arc length of 20 1/4 feet",
            {"radius_ft": 50.5, "arc_length_ft": 20.25},
        ),
        (
            "curving to the right, radius 50½ feet, arc length 20¼ feet",
            {"radius_ft": 50.5, "arc_length_ft": 20.25},
        ),
        (
            "curving to the left with a radius of 3/4 mile, chord bears N 10° E 19 3/4 feet",
            {"radius_ft": 3960.0, "chord_length_ft": 19.75},
        ),
        (
            "curving to the left with a radius of 50 1/2 feet, a chord length of 19 3/4 feet",
            {"radius_ft": 50.5, "chord_length_ft": 19.75},
        ),
    ],
)
def test_curve_elements_read_fractions(text: str, expected: dict[str, float]) -> None:
    info = extract_curve_info(text)
    for key, value in expected.items():
        assert info.get(key) == pytest.approx(value), key


def test_curve_radius_fragment_is_not_read() -> None:
    info = extract_curve_info("curving to the right with a radius of 50.5 1/2 feet")
    assert info.get("radius_ft") is None


@pytest.mark.parametrize(
    ("prefix", "is_course"),
    [
        ("North 1/2 of Section 5 ", False),
        ("NE 1/4 of the NW 1/4 ", False),
        ("Northerly 1/2 mile ", True),
        ("North 100 feet ", True),
    ],
)
def test_aliquot_fraction_is_not_an_initial_course(prefix: str, is_course: bool) -> None:
    from mp_parse.calls import _is_initial_course_prefix

    assert _is_initial_course_prefix(prefix) is is_course
