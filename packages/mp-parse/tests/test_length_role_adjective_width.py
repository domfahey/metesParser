"""Adjective widths and monument depths are not course lengths."""

from __future__ import annotations

import pytest
from mp_parse.metadata import read_course_length

_RESOLVED = [
    "a 50 foot road",
    "a 16.5 foot right of way",
    "a 16.5 foot right-of-way",
    "a 20 foot alley",
    "a 50-foot wide street",
    "a fifty (50) foot road",
    "a 10 ft. easement",
    "a 33 foot strip",
    "a 20 foot wide public utility easement",
    "a 30 foot private drive",
]


@pytest.mark.parametrize("way", _RESOLVED)
def test_adjective_width_is_not_course_length(way: str) -> None:
    text = f"THENCE N 45° E 100 feet to a point in the center line of {way}"
    reading = read_course_length(text)
    assert (reading.value, reading.ambiguous) == (100.0, ())


@pytest.mark.parametrize(
    "tail",
    [
        "0.5 feet below grade",
        "6 inches below the surface",
        "1 foot above grade",
        "3 feet deep",
        "set 2 feet back",
        "4 feet high",
    ],
)
def test_monument_depth_is_not_course_length(tail: str) -> None:
    text = f"THENCE N 45° E 100.00 feet to a 3/4 inch pipe found {tail}"
    reading = read_course_length(text)
    assert (reading.value, reading.ambiguous) == (100.0, ())


@pytest.mark.parametrize(
    "text",
    [
        "THENCE N 45° E 100 feet then 50 feet to a stake",
        "THENCE N 45° E 100 feet to a street 50 feet to a stake",
        "THENCE N 45° E 100 feet 50 feet distant from the corner",
        "THENCE N 45° E 100 feet along a 50 feet line to the road",
    ],
)
def test_genuine_ambiguity_still_fails_closed(text: str) -> None:
    assert read_course_length(text).ambiguous
