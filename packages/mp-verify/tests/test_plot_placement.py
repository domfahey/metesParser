"""Rigid clockwise transforms never refit or scale native deed metrics."""

import math

import pytest
from mp_models.plot import PlotPlacement, PointCorrespondence
from mp_verify.plot import compare_points, derive_scenario_placement, transform_point


def placement(**kwargs):
    data = {
        "id": "p",
        "calculation_id": "calc",
        "geometry_hash": "a" * 64,
        "scene_id": "scene",
        "rationale": "Manual assessment context",
    }
    data.update(kwargs)
    return PlotPlacement(**data)


def test_rigid_clockwise_rotation_and_translation():
    p = placement(rotation_deg=90, translation=(1000, 2000))
    assert transform_point((0, 10), p) == pytest.approx((1010, 2000))
    assert transform_point((0, 0), p) == pytest.approx((1000, 2000))


def test_placement_preserves_native_metrics():
    p = placement(rotation_deg=37, translation=(1e9, 2e9))
    points = [transform_point(v, p) for v in [(0, 0), (100, 0), (100, 60), (0, 60)]]
    assert sum(
        math.dist(a, b) for a, b in zip(points, points[1:] + points[:1], strict=False)
    ) == pytest.approx(320, abs=1e-6)
    assert math.dist(points[0], points[1]) == pytest.approx(100, abs=1e-6)


def test_anchor_fit_does_not_scale_deed():
    result = compare_points(
        placement(),
        (
            PointCorrespondence(id="first", deed_point=(0, 0), map_point=(0, 0)),
            PointCorrespondence(id="second", deed_point=(100, 0), map_point=(100.2, 0)),
        ),
        native_units="international_ft",
        scene_units="international_ft",
    )
    assert result.residuals[1].dx == pytest.approx(0.2)
    assert result.maximum == pytest.approx(0.2)
    assert result.rms == pytest.approx(0.2 / math.sqrt(2))


def test_identically_named_local_frames_are_not_aligned():
    result = compare_points(
        placement(status="unplaced"), (), native_units="unknown_ft", scene_units="unknown_ft"
    )
    assert result.status == "not_comparable"
    with pytest.raises(ValueError, match="unit"):
        transform_point(
            (1, 2), placement(), native_units="unknown_ft", scene_units="international_ft"
        )


def test_scenario_keeps_baseline_placement():
    p = placement(rotation_deg=90, translation=(1000, 2000))
    scenario = derive_scenario_placement(p, "b" * 64, "scenario")
    assert scenario.baseline_geometry_hash == p.geometry_hash
    assert scenario.geometry_hash == "b" * 64
    assert transform_point((0, 120), scenario) == pytest.approx((1120, 2000))


def test_declared_units_convert_at_boundary():
    assert transform_point(
        (100, 0), placement(), native_units="international_ft", scene_units="m"
    ) == pytest.approx((30.48, 0))
    assert transform_point(
        (100, 0), placement(), native_units="us_survey_ft", scene_units="m"
    ) == pytest.approx((100 * 1200 / 3937, 0))


def test_nonfinite_arithmetic_is_rejected():
    with pytest.raises(ValueError):
        transform_point((float("inf"), 0), placement())


def test_unknown_foot_definition_blocks_map_residual_claims():
    result = compare_points(
        placement(), (PointCorrespondence(id="point", deed_point=(0, 0), map_point=(0, 0)),)
    )
    assert result.status == "not_comparable"
    assert result.rms is None


def test_unrepresentable_translation_is_rejected():
    with pytest.raises(ValueError, match="precision|represent"):
        transform_point((100, 0), placement(translation=(1e20, 1e20)))


def placed_bundle(*, translation=(0, 0), comparison_specs=()):
    import json
    from pathlib import Path

    from mp_models.dashboard import DashboardBundle
    from mp_verify.dashboard import _calculate
    from mp_verify.plot import build_dashboard_plots

    data = json.loads(
        (Path(__file__).parents[2] / "mp-review/tests/fixtures/dashboard-absolute.json").read_text()
    )
    data["schema_version"] = "1.1"
    data["calculations"][0]["frame"]["foot_definition"] = "international_ft"
    bundle = DashboardBundle.model_validate(data)
    results = tuple(_calculate(bundle, s) for s in bundle.calculations)
    geom = build_dashboard_plots(bundle, results).geometries[0]
    data["scenes"] = [
        {"id": "scene", "name": "explicit local", "kind": "local", "units": "international_ft"}
    ]
    data["placements"] = [
        {
            "id": "placement",
            "calculation_id": geom.calculation_id,
            "geometry_hash": geom.geometry_hash,
            "scene_id": "scene",
            "rationale": "explicit manual placement",
            "translation": translation,
        }
    ]
    if comparison_specs:
        data["comparison_specs"] = comparison_specs
    return DashboardBundle.model_validate(data), results


def test_staged_primitives_reject_unrepresentable_placement():
    from mp_verify.plot import build_dashboard_plots

    bundle, results = placed_bundle(translation=(1e20, 1e20))
    with pytest.raises(ValueError, match="precision|represent"):
        build_dashboard_plots(bundle, results)


def test_named_comparisons_are_prepared_offline_from_bundle():
    from mp_verify.plot import build_dashboard_plots

    bundle, results = placed_bundle(
        comparison_specs=[
            {
                "id": "comparison",
                "placement_id": "placement",
                "correspondences": [
                    {"id": "first", "deed_point": [0, 0], "map_point": [0, 0]},
                    {"id": "second", "deed_point": [100, 0], "map_point": [100.2, 0]},
                ],
            }
        ]
    )
    before = bundle.model_dump_json()
    derived = build_dashboard_plots(bundle, results)
    comparison = derived.comparisons[0]
    assert comparison.comparison_id == "comparison"
    assert comparison.residuals[1].dx == pytest.approx(0.2)
    assert comparison.rms == pytest.approx(0.2 / math.sqrt(2))
    assert comparison.maximum == pytest.approx(0.2)
    assert bundle.model_dump_json() == before
