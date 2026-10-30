"""PR #60 round 3: chord-bearing degrees must never become a curve delta."""

from __future__ import annotations

import math

import pytest
from mp_parse.calls import extract_curve_info as package_extract_curve_info

from metesparser.call_extractor import CallExtractor
from tests.fixtures.package_parser import extract_calls as package_extract_calls

PARSERS = (package_extract_calls, CallExtractor.extract_calls)
CURVE_INFO = (package_extract_curve_info, CallExtractor.extract_curve_info)

CLOSING = "; THENCE due South 50 feet; THENCE due West 50 feet to the point of beginning."
ARC_CHORD = (
    "THENCE along a curve to the right having a radius of 100.00 feet, an arc length of "
    "50.00 feet, the chord of which bears N 45°00'00\" E 49.00 feet{along} to a point"
)
# delta = arc / radius = 0.5 rad; right curve tangent = chord - delta / 2.
ARC_DELTA_DEG = math.degrees(0.5)
ARC_TANGENT_AZ = 45.0 - ARC_DELTA_DEG / 2.0
ALONG = " along the Northerly line of Pennbrook Drive"


@pytest.mark.parametrize("curve_info", CURVE_INFO)
def test_chord_bearing_degrees_are_not_read_as_delta(curve_info):
    info = curve_info(ARC_CHORD.format(along=""))
    assert info.get("delta_deg") is None
    assert info["radius_ft"] == pytest.approx(100.0)
    assert info["arc_length_ft"] == pytest.approx(50.0)
    assert info["chord_bearing"] == "N 45°00'00\" E"


@pytest.mark.parametrize("curve_info", CURVE_INFO)
def test_explicit_delta_after_chord_bearing_is_still_read(curve_info):
    info = curve_info(
        "THENCE along a curve to the right having a radius of 100 feet, the chord of which "
        "bears N 45°00'00\" E 141.42 feet, a delta angle of 90°00'00\" to a point"
    )
    assert info["delta_deg"] == pytest.approx(90.0)


@pytest.mark.parametrize("parse", PARSERS)
@pytest.mark.parametrize("along", ["", ALONG])
def test_tangent_uses_delta_computed_from_arc_and_radius(parse, along):
    call = parse(ARC_CHORD.format(along=along) + CLOSING)[0]
    assert call.bearing_azimuth_deg_from_north == pytest.approx(ARC_TANGENT_AZ)
    assert call.bearing_quadrant is None
    assert call.delta_deg is None
    assert "tangent bearing derived from chord bearing and delta" in (call.notes or "")
    assert "delta computed from arc length and radius" in (call.notes or "")


@pytest.mark.parametrize("parse", PARSERS)
def test_chord_only_curve_without_delta_or_arc_is_not_given_a_tangent(parse):
    # No stated delta and no arc length: the tangent cannot be derived, so the
    # call must fail closed rather than reuse the chord or invent a delta.
    with pytest.raises(ValueError):
        parse(
            "THENCE along a curve to the right having a radius of 100.00 feet, the chord of "
            "which bears N 45°00'00\" E 49.00 feet along the Northerly line of Pennbrook Drive "
            "to a point" + CLOSING,
            strict=True,
        )
