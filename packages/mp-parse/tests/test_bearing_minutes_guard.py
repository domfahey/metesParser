"""A foot mark before a compass letter is a bearing's minutes, never a length."""

from __future__ import annotations

import re

import pytest
from mp_parse.calls import _COURSE_DISTANCE, _states_complete_course, extract_calls
from mp_parse.metadata import extract_distance
from mp_parse.units import LENGTH_NUMBER_GUARD, LENGTH_UNIT

_LENGTH = re.compile(rf"{LENGTH_NUMBER_GUARD}\d[\d,.]*\s*{LENGTH_UNIT}", re.IGNORECASE)


@pytest.mark.parametrize(
    "text",
    ["N 45 30' E", "S 10 15′ W", "N 45 30' 15\" E", "S 5 20' West", "N 45 30' E,"],
)
def test_bearing_minutes_are_not_lengths(text):
    assert not _COURSE_DISTANCE.search(text)
    assert not _LENGTH.search(text)
    assert not _states_complete_course(text)


@pytest.mark.parametrize(
    "text",
    [
        "100.00'",
        "87.16′ to a pin",
        "100'; thence N 45° E",
        "100' N 45° E",
        "N 45 30' E 100 feet",
        "N 45 30' E 100'",
    ],
)
def test_genuine_foot_mark_lengths_still_count(text):
    assert _COURSE_DISTANCE.search(text)


def test_complete_course_with_minutes_bearing():
    assert _states_complete_course("N 45 30' E 100 feet")


def test_extract_distance_ignores_bearing_minutes():
    assert extract_distance("N 45 30' E 100 feet") == (100.0, "feet")


def test_unreadable_minutes_bearing_fails_closed_as_one_course():
    # No degree sign: the bearing is not computed (never fabricated), and the
    # text is one malformed course, not a second course from the minutes.
    with pytest.raises(ValueError, match="Malformed course 1"):
        extract_calls("thence N 45 30' E 100 feet to a pin")


def test_degree_minute_bearing_single_course():
    calls, _ = extract_calls("thence N 45\u00b0 30' E 100 feet to a pin")
    assert len(calls) == 1
    assert calls[0].distance_ft == 100.0
    assert calls[0].bearing_azimuth_deg_from_north == pytest.approx(45.5)
