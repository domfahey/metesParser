"""Dashboard geometry never zips course records against a broken traverse."""

import json
from pathlib import Path

from mp_models.dashboard import DashboardBundle
from mp_verify.dashboard import calculate_dashboard

FIXTURES = Path(__file__).resolve().parents[3] / "packages/mp-review/tests/fixtures"


def _bundle_with_infeasible_curve() -> DashboardBundle:
    raw = json.loads((FIXTURES / "dashboard-absolute.json").read_text())
    # Stated tangent east, but a 50 ft chord fits no 10 ft radius circle.
    raw["calls"][1]["call"].update(
        curve_dir="right",
        radius_ft=10.0,
        chord_bearing="S 89°00'00\" E",
        chord_length_ft=50.0,
    )
    return DashboardBundle.model_validate(raw)


def test_unpositioned_course_is_not_analyzed_geometry():
    result = calculate_dashboard(_bundle_with_infeasible_curve()).calculations[0]
    assert result.geometry_status != "analyzed"
    assert result.courses == ()
    assert result.misclosure_ft is None
    assert result.engine_verified is False
    assert any("could not be positioned" in w for w in result.warnings)


def test_fully_positioned_traverse_is_still_analyzed():
    raw = json.loads((FIXTURES / "dashboard-absolute.json").read_text())
    result = calculate_dashboard(DashboardBundle.model_validate(raw)).calculations[0]
    assert result.geometry_status == "analyzed"
    assert len(result.courses) == len(raw["calls"])


def _bundle_with_curve(**curve) -> DashboardBundle:
    raw = json.loads((FIXTURES / "dashboard-absolute.json").read_text())
    call = raw["calls"][1]["call"]
    call.update(bearing_azimuth_deg_from_north=None, bearing_quadrant=None)
    call.update(curve_dir="right", radius_ft=50.0, chord_bearing="N 90°00'00\" E", **curve)
    return DashboardBundle.model_validate(raw)


def test_tangentless_curve_positioned_by_chord_and_delta_reaches_dashboard():
    from mp_verify import verify_closure
    from mp_verify.tangents import curve_tangents

    bundle = _bundle_with_curve(delta_deg=60.0, arc_length_ft=52.36, chord_length_ft=50.0)
    records = [c for c in bundle.calls if c.call is not None]
    verification = verify_closure([r.call for r in records])
    assert verification.is_fully_verified()
    result = calculate_dashboard(bundle).calculations[0]
    assert result.geometry_status == "analyzed"
    assert len(result.courses) == len(records)
    for course, a, b in zip(
        result.courses, verification.points, verification.points[1:], strict=False
    ):
        assert course.delta_x_ft == b.x - a.x
        assert course.delta_y_ft == b.y - a.y
    tangents = curve_tangents(records[1].call)
    assert tangents is not None
    assert result.courses[1].local_azimuth_deg == tangents[0]
    assert records[1].call.bearing_azimuth_deg_from_north is None


def test_chord_only_curve_stays_blocked():
    bundle = _bundle_with_curve(chord_length_ft=50.0)
    result = calculate_dashboard(bundle).calculations[0]
    assert result.geometry_status == "blocked"
    assert result.courses == ()
