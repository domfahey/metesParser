"""Round 18: spiral curves are never given circular derived values; comma-grouped chords.

1. A spiral's chord deflection is not delta / 2, so no tangent (or other circular
   derived value) is derived for ``curve_type == "spiral"``; only stated values stay.
2. Chord lengths in the chord/radial grammar accept thousands separators.
"""

from __future__ import annotations

import math

import pytest
from mp_parse.calls import extract_single_call as package_single_call

from metesparser.call_extractor import CallExtractor
from tests.fixtures.package_parser import extract_calls as package_extract_calls

CLOSING = "; THENCE due South 50 feet; THENCE due West 50 feet to the point of beginning."


def _via_calls(extract):
    return lambda text: extract("thence " + text + CLOSING, strict=True)[0]


def _via_single(extract):
    return lambda text: extract(text, 1)


ENTRY_POINTS = {
    "package-calls": _via_calls(package_extract_calls),
    "monolith-calls": _via_calls(CallExtractor.extract_calls),
    "package-single": _via_single(package_single_call),
    "monolith-single": _via_single(CallExtractor.extract_single_call),
}


@pytest.fixture(params=sorted(ENTRY_POINTS))
def parse(request):
    return ENTRY_POINTS[request.param]


SPIRAL = (
    "along a spiral curve to the right having a radius of 1000.00 feet, a delta angle "
    "of 5 degrees 43 minutes 46 seconds, an arc length of 200.00 feet, a chord bearing "
    "of North 10 degrees East and a chord distance of 199.98 feet"
)


def test_spiral_without_stated_tangent_derives_nothing(parse):
    call = parse(SPIRAL)
    assert call.curve_type == "spiral"
    assert call.bearing_azimuth_deg_from_north is None
    assert "tangent bearing derived" not in (call.notes or "")
    assert "spiral tangent not stated - not derived" in (call.notes or "")
    assert call.chord_length_ft == pytest.approx(199.98)


def test_spiral_keeps_stated_tangent(parse):
    call = parse("North 20 degrees East " + SPIRAL)
    assert call.curve_type == "spiral"
    assert call.bearing_azimuth_deg_from_north == pytest.approx(20.0)
    assert "derived" not in (call.notes or "")


def test_spiral_without_arc_or_chord_does_not_derive_arc_from_delta(parse):
    text = (
        "along a spiral curve to the right having a radius of 1000.00 feet and a delta "
        "angle of 5 degrees"
    )
    try:
        call = parse(text)
    except (ValueError, IndexError):
        return
    assert call.distance_ft != pytest.approx(math.radians(5) * 1000.0, rel=1e-3)


def test_circular_curve_keeps_tangent_unstated(parse):
    # Round 21: a circular curve's tangent is no longer derived either; it is
    # positioned by its chord and delta in verification.
    call = parse(SPIRAL.replace("spiral curve", "curve"))
    assert call.curve_type != "spiral"
    assert call.bearing_azimuth_deg_from_north is None
    assert call.chord_bearing is not None
    assert (
        "tangent bearing not stated - curve positioned by chord and delta in verification"
        in call.notes
    )
    assert "tangent bearing derived" not in call.notes


@pytest.mark.parametrize(
    "clause",
    [
        "a chord of 1,097.78 feet bearing North 10 degrees East",
        "a chord bearing North 10 degrees East and a chord distance of 1,097.78 feet",
        "chord bearing North 10 degrees East, 1,097.78 feet",
    ],
)
def test_comma_grouped_chord_length(parse, clause):
    call = parse(
        "along a curve to the right having a radius of 5,000.00 feet, an arc length of "
        f"1,100.00 feet, {clause}"
    )
    assert call.chord_length_ft == pytest.approx(1097.78)
    assert call.chord_bearing is not None
    assert call.bearing_azimuth_deg_from_north is None


def test_comma_grouped_chord_without_arc(parse):
    call = parse(
        "North 5 degrees East along a curve to the right having a radius of 5,000.00 feet, "
        "a chord of 1,097.78 feet bearing North 10 degrees East"
    )
    assert call.chord_length_ft == pytest.approx(1097.78)
    assert call.distance_ft == pytest.approx(1097.78)
