"""Chord-only curves: perimeter, unparseable chords and infeasible plot chords."""

import pytest
from mp_models import DeedCall
from mp_models.plot_request import PlotCall, PlotRequest
from mp_verify.closure import get_closure_summary, verify_closure
from mp_verify.plot import prepare_plot


def _line(course, azimuth, distance=100.0):
    return DeedCall(
        course=course,
        direction_text="recorded",
        bearing_azimuth_deg_from_north=azimuth,
        distance_ft=distance,
    )


def _chord_curve(course=2, chord_length=100.0, azimuth=None, chord_bearing="S 90° E"):
    return DeedCall(
        course=course,
        direction_text="recorded",
        bearing_azimuth_deg_from_north=azimuth,
        distance_ft=chord_length,
        curve_dir="right",
        radius_ft=500.0,
        chord_bearing=chord_bearing,
        chord_length_ft=chord_length,
        is_indefinite=azimuth is None,
    )


def _square(curve):
    return [_line(1, 0.0), curve, _line(3, 180.0), _line(4, 270.0)]


@pytest.mark.parametrize("azimuth", [None, 85.0], ids=["no-tangent", "stated-tangent"])
def test_chord_only_curve_perimeter_is_not_determined(azimuth):
    result = verify_closure(_square(_chord_curve(azimuth=azimuth)))
    assert result.perimeter_available is False
    assert result.perimeter_ft == 0.0
    assert result.precision_ratio is None
    assert "Perimeter: not determined" in get_closure_summary(result)


def test_ordinary_traverse_perimeter_remains_available():
    result = verify_closure([_line(1, 0.0), _line(2, 90.0), _line(3, 180.0), _line(4, 270.0)])
    assert result.perimeter_available is True
    assert result.perimeter_ft == pytest.approx(400.0)


def test_unparseable_chord_on_chord_only_curve_is_not_positioned():
    # A stated tangent but no delta/arc: without its chord the endpoint is unknown,
    # so the traverse must not run the tangent for distance_ft.
    curve = _chord_curve(azimuth=85.0, chord_bearing="northeasterly")
    result = verify_closure(_square(curve))
    assert result.closure_passed is False
    checks = {c.name: c for c in result.checks}
    assert checks["traverse_closure"].status == "blocked"
    assert checks["curve_consistency"].status == "blocked"
    assert checks["area_reasonableness"].inputs["area_available"] is False
    assert result.perimeter_available is False
    assert result.geometry_verified is False
    # No vertex is fabricated along the tangent for the unpositioned course.
    assert all(abs(p.x - 99.6194698) > 1e-3 for p in result.points)
    assert any("cannot be positioned" in w for w in result.warnings)


def test_unparseable_chord_with_stated_delta_still_traverses_by_tangent():
    curve = DeedCall(
        course=2,
        direction_text="recorded",
        bearing_azimuth_deg_from_north=90.0,
        distance_ft=100.0,
        curve_dir="right",
        radius_ft=500.0,
        delta_deg=10.0,
        chord_bearing="northeasterly",
    )
    result = verify_closure(_square(curve))
    assert len(result.points) == 5
    assert {c.name: c.status for c in result.checks}["curve_consistency"] == "blocked"


def _plot(calls):
    request = PlotRequest(
        title="Chord only",
        calls=tuple(PlotCall(id=f"c{c.course}", call=c) for c in calls),
    )
    return prepare_plot(request).geometry


def test_plot_infeasible_chord_is_unresolved_and_stops_the_chain():
    geometry = _plot(_square(_chord_curve(chord_length=1001.0)))
    assert [p.call_id for p in geometry.primitives] == ["c1"]
    reasons = {u.call_id: u.reason for u in geometry.unresolved}
    assert "exceeds twice the radius" in reasons["c2"]
    assert reasons["c3"] == "unpositioned after unresolved displacement"
    assert reasons["c4"] == "unpositioned after unresolved displacement"


def test_plot_non_finite_chord_displacement_is_unresolved_not_raised():
    curve = _chord_curve(chord_length=1e308).model_copy(update={"radius_ft": 1e308})
    first = _line(1, 90.0, distance=1e308)
    geometry = _plot([first, curve, _line(3, 180.0)])
    reasons = {u.call_id: u.reason for u in geometry.unresolved}
    assert reasons["c2"] == "nonfinite plot arithmetic"
    assert reasons["c3"] == "unpositioned after unresolved displacement"
