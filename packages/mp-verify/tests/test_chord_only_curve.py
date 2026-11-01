"""Radius + chord without a stated delta or arc: positioned by chord, never verified."""

import math

import pytest
from mp_models import DeedCall
from mp_models.plot_request import PlotCall, PlotRequest
from mp_verify.checks import check_curve_consistency
from mp_verify.closure import compute_traverse, verify_closure
from mp_verify.plot import prepare_plot


def _line(course, azimuth, distance=100.0):
    return DeedCall(
        course=course,
        direction_text="recorded",
        bearing_azimuth_deg_from_north=azimuth,
        distance_ft=distance,
    )


def _chord_curve(course=2, chord_length=100.0, azimuth=None):
    return DeedCall(
        course=course,
        direction_text="recorded",
        bearing_azimuth_deg_from_north=azimuth,
        distance_ft=chord_length,
        curve_dir="right",
        radius_ft=500.0,
        chord_bearing="S 90° E",
        chord_length_ft=chord_length,
        is_indefinite=azimuth is None,
    )


def _square(curve):
    return [_line(1, 0.0), curve, _line(3, 180.0), _line(4, 270.0)]


def test_chord_only_curve_endpoint_is_the_chord_displacement():
    points = compute_traverse([_chord_curve(course=1, chord_length=70.0)])
    assert len(points) == 2
    assert points[1].x == pytest.approx(70.0)
    assert points[1].y == pytest.approx(0.0, abs=1e-9)


def test_stated_tangent_does_not_replace_chord_positioning():
    # A stated tangent with no delta/arc still leaves the arc ambiguous; the chord
    # (not the tangent at distance_ft) fixes the endpoint.
    points = compute_traverse([_chord_curve(course=1, azimuth=80.0)])
    assert points[1].x == pytest.approx(100.0)
    assert points[1].y == pytest.approx(0.0, abs=1e-9)


# A tangent consistent with the 100 ft chord bearing due east on a 500 ft radius:
# the chord deflects asin(100 / 1000) to the right of it.
CONSISTENT_TANGENT = 90.0 - math.degrees(math.asin(0.1))


@pytest.mark.parametrize(
    "azimuth", [None, CONSISTENT_TANGENT], ids=["no-tangent", "stated-tangent"]
)
def test_chord_only_curve_blocks_curve_check_and_eligibility(azimuth):
    result = verify_closure(_square(_chord_curve(azimuth=azimuth)))
    assert result.misclosure_ft == pytest.approx(0.0, abs=1e-9)
    checks = {c.name: c for c in result.checks}
    assert checks["curve_consistency"].status == "blocked"
    assert checks["curve_consistency"].reason == "curve_delta_not_stated"
    assert result.curve_consistency_passed is False
    assert result.geometry_verified is False
    assert any("positioned by chord only" in w for w in result.warnings)


def test_chord_longer_than_diameter_fails_curve_consistency():
    passed, warnings = check_curve_consistency([_chord_curve(chord_length=1001.0)])
    assert passed is False
    assert any("chord length exceeds twice the radius" in w for w in warnings)
    result = verify_closure(_square(_chord_curve(chord_length=1001.0)))
    assert {c.name: c.status for c in result.checks}["curve_consistency"] == "failed"
    assert result.geometry_verified is False


def test_chord_within_diameter_alone_is_not_reported_as_consistent():
    passed, warnings = check_curve_consistency([_chord_curve(chord_length=100.0)])
    # Nothing to compare against: no failure, but the verifier blocks the check.
    assert passed is True
    assert warnings == []


def test_plot_draws_no_arc_but_positions_later_courses_by_the_chord():
    request = PlotRequest(
        title="Chord only",
        calls=tuple(
            PlotCall(id=f"c{c.course}", call=c) for c in _square(_chord_curve(azimuth=None))
        ),
    )
    geometry = prepare_plot(request).geometry
    # The minor/major arc is unknown, so no line or arc is drawn for the curve ...
    assert [p.call_id for p in geometry.primitives] == ["c1", "c3", "c4"]
    assert [u.call_id for u in geometry.unresolved] == ["c2"]
    assert "positioned by chord only" in geometry.unresolved[0].reason
    assert geometry.completeness == "partial"
    assert geometry.misclosure_ft is None
    # ... but the chord fixes where the next course starts.
    assert geometry.primitives[1].start == pytest.approx((100.0, 100.0))
    assert geometry.primitives[-1].end == pytest.approx((0.0, 0.0), abs=1e-9)
    assert geometry.chains == (("c1",), ("c3", "c4"))
