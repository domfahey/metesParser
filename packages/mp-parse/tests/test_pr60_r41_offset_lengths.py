"""Round 41: offset/separation distances are not the course length."""

from __future__ import annotations

import pytest
from mp_parse.metadata import extract_distance, read_course_length

OFFSETS = [
    "parallel to and 50 feet distant from Main Street",
    "parallel with and 50 feet distance from Main Street",
    "parallel to and 50.00 feet northerly from Main Street",
    "parallel with and 50 feet distant from the road",
    "50 feet southerly from Main Street",
    "at a distance of 50 feet from Main Street",
    "50 feet distant from Main Street",
    "50 feet off Main Street",
    "50 feet measured at right angles from Main Street",
    "50 feet at right angles from Main Street",
]


@pytest.mark.parametrize("offset", OFFSETS)
def test_course_length_before_offset(offset: str) -> None:
    joiner = "" if offset.startswith("parallel") else "along a line "
    text = f"thence N 45° E 100 feet {joiner}{offset} to a pin"
    assert extract_distance(text) == (100.0, "feet")


@pytest.mark.parametrize("offset", OFFSETS)
def test_course_length_after_offset(offset: str) -> None:
    text = f"thence N 45° E {offset}, 100 feet to a pin"
    assert extract_distance(text) == (100.0, "feet")


@pytest.mark.parametrize("offset", OFFSETS)
def test_offset_clause_before_bearing(offset: str) -> None:
    text = f"thence {offset}, N 45° E 100 feet to a pin"
    assert extract_distance(text) == (100.0, "feet")


def test_two_unlabelled_lengths_stay_ambiguous() -> None:
    reading = extract_distance("thence N 45° E 100 feet 50 feet to a pin")
    assert reading == (0.0, "feet")


@pytest.mark.parametrize(
    "offset",
    [
        "50 feet distant from X",
        "50 feet off X",
        "50 feet at right angles from X",
    ],
)
def test_adjacent_unjoined_offset_stays_ambiguous(offset: str) -> None:
    text = f"thence N 45° E 100 feet {offset} to a pin"
    assert extract_distance(text) == (0.0, "feet")
    assert read_course_length(text).ambiguous == ("100 feet", "50 feet")
