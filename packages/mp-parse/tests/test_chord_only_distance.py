"""Chord-only curve distance and dashed-bearing context."""

import pytest
from mp_parse.calls import _expand_compact_dms, extract_single_call

CHORD_ONLY = [
    "curve to the right having a radius of 500 feet, the chord of which bears "
    "N 45 deg 30 min E, 100 feet",
    "THENCE along a curve to the left with a radius of 500 feet and a chord bearing of "
    "N 45°30' E and a chord length of 100 feet to a point",
]


@pytest.mark.parametrize("text", CHORD_ONLY)
def test_chord_only_curve_distance_is_the_chord_not_the_radius(text):
    call = extract_single_call(text, 1)
    assert call is not None and call.is_chord_only_curve()
    assert call.radius_ft == pytest.approx(500.0)
    assert call.chord_length_ft == pytest.approx(100.0)
    assert call.distance_ft == pytest.approx(100.0)


@pytest.mark.parametrize(
    "text", ["Lot N 12-3 E", "Block S 4-15 W", "Route N 9-1 E", "No. N 12-3 E", "# S 2-10 W"]
)
def test_identifier_dash_sequences_are_not_rewritten_as_bearings(text):
    assert _expand_compact_dms(text) == text


@pytest.mark.parametrize(
    "text", ["N 45-30 E", "THENCE N 45-30 E", "thence, S 44-30-30 W", "bears N 51-13-46 E"]
)
def test_dashed_bearings_in_bearing_context_are_still_rewritten(text):
    assert "-" not in _expand_compact_dms(text)


def test_bare_dashed_group_outside_bearing_context_is_left_alone():
    assert _expand_compact_dms("Parcel A N 12-3 E") == "Parcel A N 12-3 E"
    # Explicit degree/minute markers are bearings wherever they appear.
    assert _expand_compact_dms("Parcel A N 12d3m E") == "Parcel A N 12°3' E"
