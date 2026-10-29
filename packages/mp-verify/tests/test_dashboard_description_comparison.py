"""Source-owned dashboard comparisons remain independent from canonical findings."""

import copy
import json
from pathlib import Path

import pytest
from mp_models.dashboard import DashboardBundle
from mp_verify.comparison import compare_descriptions
from mp_verify.dashboard import calculate_dashboard, validate_prepared_dashboard

FIXTURE = Path(__file__).resolve().parents[2] / "mp-review/tests/fixtures/dashboard-comparison.json"


def data():
    return json.loads(FIXTURE.read_bytes())


def test_dashboard_matches_standalone_and_retains_both_source_occurrences():
    raw = data()
    prepared = calculate_dashboard(DashboardBundle.model_validate(raw))
    advisory = prepared.description_comparisons[0]
    assert advisory.comparison == compare_descriptions(advisory.request)
    assert advisory.calculation_input_hash == prepared.manifest.calculation_input_hash
    assert advisory.left_occurrence_id == "occ-one"
    assert advisory.right_occurrence_id == "occ-two"
    pair = advisory.comparison.pairs[0]
    assert pair.left_sources[0].page_id == "page-one"
    assert pair.right_sources[0].page_id == "page-two"
    assert pair.displacement.outcome == "not_comparable"
    assert any(
        d.kind == "changed" and "to" in d.changed_fields for d in advisory.comparison.structural
    )
    assert prepared.manifest.description_comparisons_output_hash
    baseline = copy.deepcopy(raw)
    del baseline["description_comparison_specs"]
    original = calculate_dashboard(DashboardBundle.model_validate(baseline))
    assert prepared.calculations == original.calculations
    assert prepared.diagnostics == original.diagnostics
    assert prepared.plots == original.plots


def test_changed_sources_recompute_hashes_and_forged_advisory_rejected():
    raw = data()
    before = calculate_dashboard(DashboardBundle.model_validate(raw))
    raw["calls"][-4]["quote"] = "A changed source occurrence excerpt"
    after = calculate_dashboard(DashboardBundle.model_validate(raw))
    assert (
        before.manifest.description_comparisons_input_hash
        != after.manifest.description_comparisons_input_hash
    )
    assert (
        before.manifest.description_comparisons_output_hash
        != after.manifest.description_comparisons_output_hash
    )
    with pytest.raises(ValueError, match="deterministic"):
        validate_prepared_dashboard(
            after.model_copy(update={"description_comparisons": before.description_comparisons})
        )


def test_cross_occurrence_explicit_pair_and_unknown_calculation_rejected():
    raw = data()
    raw["description_comparison_specs"][0]["pairs"][0]["right"]["call_ids"] = ["call-one"]
    with pytest.raises(ValueError):
        DashboardBundle.model_validate(raw)
    raw = data()
    raw["description_comparison_specs"][0]["right_calculation_id"] = "unknown"
    with pytest.raises(ValueError):
        DashboardBundle.model_validate(raw)


def test_scenarios_do_not_change_comparison_baseline():
    raw = data()
    before = calculate_dashboard(DashboardBundle.model_validate(raw))
    raw["scenarios"][0]["edits"][0]["distance_ft"] = 100.75
    after = calculate_dashboard(DashboardBundle.model_validate(raw))
    assert before.description_comparisons == after.description_comparisons
    assert (
        before.manifest.description_comparisons_output_hash
        == after.manifest.description_comparisons_output_hash
    )


def test_dashboard_positions_bind_to_fresh_identical_primitive_geometry():
    raw = data()
    raw["scenes"] = [
        {
            "id": "comparison-scene",
            "name": "explicit local scene",
            "kind": "local",
            "units": "international_ft",
        }
    ]
    for side in ("left", "right"):
        raw["description_comparison_specs"][0][side + "_bearing_basis"].update(
            identity="recorded-grid", source_references=["recorded survey basis"]
        )
    fresh = calculate_dashboard(DashboardBundle.model_validate(raw))
    raw["placements"] = [
        {
            "id": g.calculation_id + "-placement",
            "calculation_id": g.calculation_id,
            "geometry_hash": g.geometry_hash,
            "scene_id": "comparison-scene",
            "rationale": "explicit synthetic origin",
            "status": "approximate",
        }
        for g in fresh.plots.geometries
    ]
    spec = raw["description_comparison_specs"][0]
    spec.update(
        scene_id="comparison-scene",
        left_placement_id="calc-one-placement",
        right_placement_id="calc-two-placement",
    )
    prepared = calculate_dashboard(DashboardBundle.model_validate(raw))
    advisory = prepared.description_comparisons[0]
    assert advisory.comparison.pairs[0].position.outcome == "agree"
    assert len(advisory.placement_bindings) == 2
    original = raw["placements"][0]
    assert advisory.placement_bindings[0][1] == original["geometry_hash"]
    assert advisory.placement_bindings[0][2] == advisory.request.left.placement.geometry_hash
    assert original["geometry_hash"] != advisory.request.left.placement.geometry_hash
    assert prepared.bundle.placements[0].geometry_hash == original["geometry_hash"]
    raw["placements"][0]["geometry_hash"] = "a" * 64
    with pytest.raises(ValueError, match="stale"):
        calculate_dashboard(DashboardBundle.model_validate(raw))
