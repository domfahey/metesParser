"""extract_single_call fails closed on curve+course fragments and matches extract_calls."""

from __future__ import annotations

import pytest
from mp_parse.calls import MultipleCoursesError, extract_calls, extract_single_call

CURVE = "along a curve to the right having a radius of 100 feet, an arc length of 50 feet"
CURVE_CHORD = CURVE + ", a chord bearing of N 10° E and a chord of 49.74 feet"


@pytest.mark.parametrize(
    "text",
    [
        f"THENCE {CURVE}; THENCE N 20° E 10 feet",
        f"THENCE {CURVE_CHORD}; THENCE N 20° E 10 feet",
        f"THENCE {CURVE}; N 20° E 10 feet",
        f"THENCE N 20° E 10 feet; THENCE {CURVE}",
        f"THENCE {CURVE} THENCE S 20° E 10 feet",
        f"THENCE {CURVE}, thence along a curve to the left having a radius of 80 feet, "
        "an arc length of 20 feet",
    ],
)
def test_curve_with_following_course_raises(text: str) -> None:
    with pytest.raises(MultipleCoursesError):
        extract_single_call(text, 1)


def test_extract_calls_splits_curve_and_following_course() -> None:
    calls, _ = extract_calls(f"THENCE {CURVE}; THENCE N 20° E 10 feet")
    assert [c.distance_ft for c in calls] == [50.0, 10.0]
    assert calls[0].bearing_azimuth_deg_from_north is None
    assert calls[1].bearing_azimuth_deg_from_north == 20.0


def test_extract_calls_splits_without_thence_separator() -> None:
    calls, _ = extract_calls(f"THENCE {CURVE}; N 20° E 10 feet")
    assert [c.distance_ft for c in calls] == [50.0, 10.0]
    assert calls[0].bearing_azimuth_deg_from_north is None


def test_single_curve_with_tangent_and_chord_clauses_is_one_course() -> None:
    call = extract_single_call(
        f"THENCE N 45° E, {CURVE}; chord bearing N 10° E; chord 49.74 feet", 1
    )
    assert call is not None
    assert call.bearing_azimuth_deg_from_north == 45.0
    assert call.distance_ft == 50.0


@pytest.mark.parametrize(
    "bearing",
    ["N 91° E", "N 95° E", "N 91°30' E", "N 95-30' E", "N 91-30-00 E", "N 91 degrees E"],
)
@pytest.mark.parametrize("prefix", ["", "THENCE ", "thence "])
def test_out_of_range_bearing_matches_extract_calls(bearing: str, prefix: str) -> None:
    text = f"{prefix}{bearing} 100 feet"
    single = extract_single_call(text, 1)
    assert single is not None
    (listed,), _ = extract_calls(text)
    assert single.bearing_azimuth_deg_from_north is None
    assert single.notes == listed.notes == "incomplete bearing"
    assert single.distance_ft == listed.distance_ft == 100.0


@pytest.mark.parametrize(
    ("text", "along"),
    [
        (
            "THENCE along Main Street (50 feet wide) N 45° E 100 feet to a point",
            "Main Street (50 feet wide)",
        ),
        ("THENCE N 45° E along Main Street 100 feet to a point", "Main Street"),
    ],
)
def test_along_holds_only_the_adjoiner(text: str, along: str) -> None:
    call = extract_single_call(text, 1)
    assert call is not None
    assert call.along == along
    assert call.distance_ft == 100.0
    (listed,), _ = extract_calls(text)
    assert listed.along == along
