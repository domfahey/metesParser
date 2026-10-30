"""One inch token, one measurement-end rule and one monument-size exclusion."""

from __future__ import annotations

import pytest
from mp_parse.calls import extract_calls, extract_single_call
from mp_parse.metadata import read_course_length

_BEARING = "N 45° E"
_MONUMENT_SIZES = [
    '100.00 feet, 1" pipe',
    '100.00 feet, 1" iron pipe found',
    "100.00 feet 1 inch iron pipe found",
    '100.00 feet, 3/4" rebar',
    "100.00 feet, 1.5 in. pipe",
    "100.00 feet, 5/8 inch iron pin set",
    "100.00 feet, 1 in. iron rod",
    "100.00 feet, 1″ spike",
]


@pytest.mark.parametrize("tail", _MONUMENT_SIZES)
def test_monument_size_after_length_is_not_an_inch_component(tail: str) -> None:
    reading = read_course_length(f"{_BEARING} {tail}")
    assert reading.ambiguous == ()
    assert reading.value == 100.0


@pytest.mark.parametrize("tail", _MONUMENT_SIZES)
def test_monument_size_course_is_extracted(tail: str) -> None:
    call = extract_single_call(f"thence {_BEARING} {tail}", 1)
    assert call is not None
    assert call.distance_ft == 100.0


def test_monument_size_in_extract_calls() -> None:
    skipped: list = []
    calls, _ = extract_calls(
        'Beginning at a point; thence N 45° E 100.00 feet, 1" iron pipe found; '
        "thence S 45° E 50 feet to a pin.",
        skipped_courses=skipped,
    )
    assert skipped == []
    assert [c.distance_ft for c in calls] == [100.0, 50.0]


@pytest.mark.parametrize("end", ["thence", "more or less", "to a point", "along the line", ".", ""])
@pytest.mark.parametrize("pair", ["100' 6\"", "100' 6 in.", "100' 6 inches"])
def test_foot_inch_pair_ends_uniformly(pair: str, end: str) -> None:
    reading = read_course_length(f"N 45° 30' E {pair} {end}".strip())
    assert reading.ambiguous == ()
    assert reading.value == pytest.approx(100.5)


@pytest.mark.parametrize("end", ["thence", "more or less", "to a pin", ""])
def test_word_inches_still_sum_before_ends(end: str) -> None:
    reading = read_course_length(f"{_BEARING} 100 feet 6 inches {end}".strip())
    assert reading.value == pytest.approx(100.5)


def test_preposition_in_unchanged() -> None:
    reading = read_course_length(f"{_BEARING} 100 feet in a northerly direction")
    assert reading.value == 100.0


@pytest.mark.parametrize("tail", ["100' 1\" pipe", "100', 1\" iron pipe found"])
def test_foot_mark_course_with_monument_size(tail: str) -> None:
    reading = read_course_length(f"N 45° 30' E {tail}")
    assert reading.ambiguous == ()
    assert reading.value == 100.0
