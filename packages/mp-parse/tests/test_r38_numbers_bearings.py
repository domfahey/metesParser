"""Comma grouping, decimal-degree bearings and bearing text as stated (PR #60 r38)."""

from __future__ import annotations

import pytest
from mp_parse.calls import extract_single_call
from mp_parse.units import LENGTH_NUMBER, parse_number


@pytest.mark.parametrize(
    ("text", "value"), [("1,200.50", 1200.5), ("1,200", 1200.0), ("12,345,678", 12345678.0)]
)
def test_valid_thousands_grouping_is_read(text: str, value: float) -> None:
    assert parse_number(text) == pytest.approx(value)


@pytest.mark.parametrize("text", ["1,2,3", "100,50", "1,23", "1234,567", "12,34,567"])
def test_malformed_comma_grouping_is_no_number(text: str) -> None:
    with pytest.raises(ValueError):
        parse_number(text)


@pytest.mark.parametrize("text", ["100,50", "1,2,3", "1234,567"])
def test_malformed_comma_number_never_matches_a_length(text: str) -> None:
    import re

    assert re.fullmatch(LENGTH_NUMBER, text) is None
    assert re.search(LENGTH_NUMBER, f"{text} feet") is None


def test_malformed_comma_distance_is_not_read_as_another_value() -> None:
    # No distance is read, so the course is rejected (existing fail-closed path).
    with pytest.raises(ValueError, match="Missing boundary course distance"):
        extract_single_call("THENCE N 45° E 100,50 feet to a point", 1)


def test_grouped_distance_still_read() -> None:
    call = extract_single_call("THENCE N 45° E 1,200.50 feet to a point", 1)
    assert call is not None
    assert call.distance_ft == pytest.approx(1200.5)


@pytest.mark.parametrize("bearing", ["N 45.5° E", "S 12.125° W", "N 0.7° E"])
def test_decimal_degrees_are_not_silently_read_as_packed(bearing: str) -> None:
    call = extract_single_call(f"THENCE {bearing} 100 feet to a point", 1)
    assert call is not None
    assert call.bearing_azimuth_deg_from_north is None
    assert call.bearing_quadrant is None
    assert "incomplete bearing - ambiguous decimal degrees" in (call.notes or "")


def test_four_digit_packed_dms_still_read() -> None:
    call = extract_single_call("THENCE N 46.1631° E 100 feet to a point", 1)
    assert call is not None
    assert call.bearing_azimuth_deg_from_north == pytest.approx(46.275277777)


def test_seconds_are_kept_and_never_round_into_next_degree() -> None:
    call = extract_single_call("THENCE S 89°59'59\" W 100 feet to a point", 1)
    assert call is not None
    assert call.bearing_quadrant == "S 89°59'59\" W"
    assert call.bearing_azimuth_deg_from_north == pytest.approx(269.99972222)


def test_bearing_without_seconds_keeps_existing_format() -> None:
    call = extract_single_call("THENCE N 45° 30' E 100 feet to a point", 1)
    assert call is not None
    assert call.bearing_quadrant == "N 45°30' E"
    call = extract_single_call("THENCE N 45° E 100 feet to a point", 1)
    assert call is not None
    assert call.bearing_quadrant == "N 45°00' E"
