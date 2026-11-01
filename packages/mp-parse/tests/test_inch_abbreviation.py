"""An abbreviated inch component ('in', 'in.') is never silently dropped.

'in' and 'in.' are inches only as the trailing component of a descending compound
("100 feet 6 in."): directly after a larger-unit length and followed by the end of
the course, punctuation, "to", "thence", "along" or "more or less". A preposition
'in' ("100 feet in a northerly direction") is never inches. A foot-mark length
followed by an inch mark ("100' 6\"") is one measurement only in that same
position (never after a bearing, whose 6" is seconds). A number with an inch-like
token left unread next to the course length fails closed rather than being dropped,
and the reading never depends on trailing punctuation removed by call splitting.
"""

from __future__ import annotations

import pytest
from mp_models.units import ConversionFactors
from mp_parse.calls import extract_calls, extract_single_call
from mp_parse.metadata import read_course_length
from mp_verify.closure import verify_closure

_CLOSE = (
    "; thence S 80°00' E 100.00 feet to a pin; thence S 10°00' W 100.00 feet to a pin; "
    "thence N 80°00' W 100.00 feet to the point of beginning."
)

_INCH_COMPOUNDS = [
    "thence N 10°00' E 100 feet 6 in.",
    "thence N 10°00' E 100 feet 6 in",
    "thence N 10°00' E 100 ft 6 in.",
    "thence N 10°00' E 100 ft 6 in",
    "thence N 10°00' E 100 feet 6 in. to a pin",
    "thence N 10°00' E 100 feet 6 in to a pin",
    "thence N 10°00' E 100 ft 6 in. to a pin",
    "thence N 10°00' E 100 ft. 6 in, to a pin",
    "thence N 10°00' E 100 feet 6 in along the line of Smith",
    "thence N 10°00' E 100 feet 6 in. more or less to a pin",
    "thence N 10°00' E 100' 6\" to a pin",
    "thence N 10°00' E 100' 6\"",
]

_PREPOSITIONS = [
    "thence N 10°00' E 100 feet in a northerly direction to a pin",
    "thence N 10°00' E 100 feet in the line of Smith",
    "thence N 10°00' E 100 feet in.",
]

_UNREAD_INCH = [
    "thence N 10°00' E 100 feet 6 in the line of Smith",
    "thence N 10°00' E 100' 6\" E to a pin",
]


def _description(course: str) -> str:
    return "BEGINNING at a pin; " + course + _CLOSE


def _feet(text: str) -> float:
    reading = read_course_length(text)
    return ConversionFactors.convert_to_feet(reading.value, reading.unit)


@pytest.mark.parametrize("text", _INCH_COMPOUNDS)
def test_read_course_length_sums_an_abbreviated_inch_component(text):
    assert _feet(text) == pytest.approx(100.5)
    assert _feet(text.rstrip(".")) == pytest.approx(100.5)


@pytest.mark.parametrize("text", _INCH_COMPOUNDS)
def test_single_call_sums_an_abbreviated_inch_component(text):
    call = extract_single_call(text, 1)
    assert call is not None
    assert call.distance_ft == pytest.approx(100.5)


@pytest.mark.parametrize("strict", [True, False])
@pytest.mark.parametrize("text", _INCH_COMPOUNDS)
def test_extract_calls_sums_an_abbreviated_inch_component(text, strict):
    skipped: list = []
    calls, _ = extract_calls(_description(text), strict=strict, skipped_courses=skipped)
    assert skipped == []
    assert [round(call.distance_ft, 6) for call in calls] == [100.5, 100.0, 100.0, 100.0]


@pytest.mark.parametrize("text", _PREPOSITIONS)
def test_preposition_in_is_never_inches(text):
    assert _feet(text) == pytest.approx(100.0)
    call = extract_single_call(text, 1)
    assert call is not None
    assert call.distance_ft == pytest.approx(100.0)
    calls, _ = extract_calls(_description(text), strict=True)
    assert calls[0].distance_ft == pytest.approx(100.0)


@pytest.mark.parametrize("text", _UNREAD_INCH)
def test_unread_inch_component_fails_closed(text):
    reading = read_course_length(text)
    assert reading.value == 0.0
    assert reading.ambiguous
    with pytest.raises(ValueError, match="course length ambiguous"):
        extract_single_call(text, 1)
    with pytest.raises(ValueError, match="course length ambiguous"):
        extract_calls(_description(text), strict=True)
    skipped: list = []
    calls, _ = extract_calls(_description(text), strict=False, skipped_courses=skipped)
    assert [skip.course for skip in skipped] == [1]
    assert [call.course for call in calls] == [2, 3, 4]


def test_bearing_seconds_are_not_inches_after_a_bearing():
    call = extract_single_call("thence N 10°00'6\" E 100 feet to a pin", 1)
    assert call is not None
    assert call.distance_ft == pytest.approx(100.0)


@pytest.mark.parametrize("tail", ["", " to a pin"])
def test_square_with_dropped_inches_does_not_verify(tail):
    text = (
        "BEGINNING at a point; thence N 0° E 100 feet 6 in." + tail + "; thence S 90° E 100 "
        "feet; thence S 0° E 100 feet; thence N 90° W 100 feet to the point of beginning."
    )
    calls, _ = extract_calls(text, strict=True)
    assert [round(call.distance_ft, 6) for call in calls] == [100.5, 100.0, 100.0, 100.0]
    result = verify_closure(calls)
    assert result.misclosure_ft == pytest.approx(0.5)
    assert not result.is_fully_verified()
