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
def test_chord_only_curve_without_delta_or_arc_is_positioned_by_chord_only(parse):
    # Radius + chord without a stated delta or arc is ambiguous (minor vs major
    # arc): no delta, arc or tangent is derived. The course is kept, carries no
    # azimuth, and is positioned by its chord only.
    call = parse(
        "THENCE along a curve to the right having a radius of 100.00 feet, the chord of "
        "which bears N 45°00'00\" E 49.00 feet along the Northerly line of Pennbrook Drive "
        "to a point" + CLOSING,
        strict=True,
    )[0]
    assert call.bearing_azimuth_deg_from_north is None
    assert call.delta_deg is None
    assert call.arc_length_ft is None
    assert call.chord_length_ft == pytest.approx(49.0)
    assert call.is_indefinite is True
    assert "curve delta/arc not stated - positioned by chord only" in (call.notes or "")
    assert "delta computed from chord length" not in (call.notes or "")


@pytest.mark.parametrize("parse", PARSERS)
def test_chord_longer_than_diameter_is_kept_and_flagged(parse):
    call = parse(
        "THENCE along a curve to the right having a radius of 100.00 feet, the chord of "
        "which bears N 45°00'00\" E 249.00 feet to a point" + CLOSING,
        strict=True,
    )[0]
    assert call.bearing_azimuth_deg_from_north is None
    assert "chord length exceeds twice the radius" in (call.notes or "")


def _unparseable_chord(monkeypatch):
    """Make the chord bearing underivable so the tangent stays unstated."""
    import mp_parse.calls as package_calls

    import metesparser.call_extractor as monolith_calls

    monkeypatch.setattr(package_calls, "bearing_to_azimuth", lambda *_a, **_k: None)
    monkeypatch.setattr(
        monolith_calls.BearingConverter, "bearing_to_azimuth", staticmethod(lambda *_a, **_k: None)
    )


@pytest.mark.parametrize("parse", PARSERS)
def test_chord_only_curve_without_derivable_tangent_is_indefinite(parse, monkeypatch):
    # Delta is stated, but the chord azimuth cannot be resolved, so no tangent.
    text = (
        "THENCE along a curve to the right with a radius of 500 feet, a delta of 10°00'00\", "
        "chord bears N 45° E 100 feet to a point" + CLOSING
    )
    _unparseable_chord(monkeypatch)
    call = parse(text)[0]
    assert call.bearing_azimuth_deg_from_north is None
    assert "tangent bearing not stated - chord bearing only" in (call.notes or "")
    assert call.is_indefinite is True


@pytest.mark.parametrize("parse", PARSERS)
def test_derived_tangent_curve_stays_definite(parse):
    call = parse(ARC_CHORD.format(along="") + CLOSING)[0]
    assert call.bearing_azimuth_deg_from_north is not None
    assert call.is_indefinite is False


RADIAL_CLAUSES = [
    "whose radius point bears S 10° W,",
    "radial bearing of S 10° W,",
    "radial line bears S 10° W,",
    "to the center point which bears S 10° W,",
    "to the centre point which bears S 10° W,",
]
# left curve, arc 50 / radius 500 => delta 0.1 rad; tangent = chord + delta/2.
RADIAL_TANGENT_AZ = 80.0 + math.degrees(0.1) / 2.0


@pytest.mark.parametrize("parse", PARSERS)
@pytest.mark.parametrize("clause", RADIAL_CLAUSES)
def test_radial_bearing_is_not_a_stated_tangent(parse, clause):
    text = (
        f"THENCE along a non-tangent curve to the left {clause} having a radius of 500 feet, "
        "an arc length of 50 feet, chord bears N 80° E 49.9 feet to a point"
    )
    call = parse(text + CLOSING)[0]
    # Neither the chord nor the radial bearing is taken as the tangent.
    assert call.bearing_azimuth_deg_from_north == pytest.approx(RADIAL_TANGENT_AZ)
    assert call.bearing_quadrant is None
    assert "tangent bearing derived from chord bearing and delta" in (call.notes or "")
