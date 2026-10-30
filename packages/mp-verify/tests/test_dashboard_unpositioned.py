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
