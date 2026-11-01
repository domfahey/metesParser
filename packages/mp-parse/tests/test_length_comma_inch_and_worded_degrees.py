"""Comma-joined inches sum; a bearing's minutes/seconds are never read as a length."""

from __future__ import annotations

import pytest
from mp_parse.calls import extract_calls, extract_single_call
from mp_parse.metadata import extract_distance, read_course_length

_CLOSE = (
    "; thence S 80°00' E 100.00 feet to a pin; thence S 10°00' W 100.00 feet to a pin; "
    "thence N 80°00' W 100.00 feet to the point of beginning."
)

_COMMA_INCH = [
    "thence N 45° E 100 feet, 6 inches to a pin",
    "thence N 45° E 100 feet, 6 in. to a pin",
    "thence N 45° E 100 ft., 6 in. to a pin",
    "thence N 45° E 100', 6\" to a pin",
    "thence N 45° E 100', 6 in. to a pin",
]

_WORDED_DEGREES = [
    "thence North 45 degrees 30' 15\" East 100' to a pin",
    "thence N 45 deg. 30' 15\" E 100' to a pin",
    "thence N 45d 30' 15\" E 100' to a pin",
]


@pytest.mark.parametrize("text", _COMMA_INCH)
def test_comma_inch_sums(text):
    assert read_course_length(text).value == pytest.approx(100.5)
    assert read_course_length(text).ambiguous == ()
    assert extract_distance(text)[0] == pytest.approx(100.5)
    call = extract_single_call(text, 1)
    assert call is not None
    assert call.distance_ft == pytest.approx(100.5)
    calls, _ = extract_calls("BEGINNING at a pin; " + text + _CLOSE, strict=True)
    assert round(calls[0].distance_ft, 6) == 100.5


def test_comma_before_unrelated_measurement_does_not_sum():
    assert read_course_length("thence N 45° E 150 feet, 3 rods north of a pin").value == 150.0


@pytest.mark.parametrize("text", _WORDED_DEGREES)
def test_worded_degree_minutes_seconds_are_not_a_length(text):
    reading = read_course_length(text)
    assert (reading.value, reading.ambiguous) == (100.0, ())
    assert extract_distance(text) == (100.0, "feet")
    call = extract_single_call(text, 1)
    assert call is not None
    assert call.distance_ft == pytest.approx(100.0)
    calls, _ = extract_calls("BEGINNING at a pin; " + text + _CLOSE, strict=True)
    assert round(calls[0].distance_ft, 6) == 100.0


def test_text_parser_facade_matches():
    from metesparser.text_parser import TextParser

    for text in _WORDED_DEGREES:
        assert TextParser.extract_distance(text) == (100.0, "feet")


def test_hyphenated_dms_seconds_are_not_a_length():
    text = "thence N 45-30' 15\" E 100' to a pin"
    assert read_course_length(text).value == 100.0
    assert read_course_length(text).ambiguous == ()
