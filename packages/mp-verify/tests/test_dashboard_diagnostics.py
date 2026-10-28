"""Dashboard diagnosis binds to fresh geometry without changing record findings."""

import json
from pathlib import Path

import pytest
from mp_models.dashboard import DashboardBundle
from mp_verify.dashboard import (
    calculate_dashboard,
    diagnostic_request_from_dashboard,
    validate_prepared_dashboard,
)
from mp_verify.diagnostics import diagnose_closure

FIXTURES = Path(__file__).resolve().parents[3] / "packages/mp-review/tests/fixtures"


def data(kind="absolute"):
    return json.loads((FIXTURES / f"dashboard-{kind}.json").read_text())


def test_baseline_matches_standalone_request_and_retains_source_identity():
    bundle = DashboardBundle.model_validate(data())
    prepared = calculate_dashboard(bundle)
    diagnosis = prepared.diagnostics[0]
    req = diagnostic_request_from_dashboard(bundle, bundle.calculations[0])
    assert diagnosis.baseline == diagnose_closure(req)
    assert diagnosis.calculation_input_hash == prepared.manifest.calculation_input_hash
    source = diagnosis.baseline.request.calls[0].source_refs[0]
    assert source.occurrence_id == "occ-one"
    assert source.page_id == "page-one" and source.page == 1
    assert source.crop_id == "evidence-one"
    assert source.source_sha256 is None
    assert source.quote == bundle.calls[0].quote
    assert prepared.manifest.diagnostics_output_hash is not None


@pytest.mark.parametrize("kind", ["relative", "unknown"])
def test_unsupported_and_unknown_diagnosis_retains_original_results(kind):
    raw = data("relative" if kind == "relative" else "absolute")
    if kind == "unknown":
        raw["calls"][0].update(call=None, reading_status="unknown", reading_note="obscured digit")
    prepared = calculate_dashboard(DashboardBundle.model_validate(raw))
    diagnosis = prepared.diagnostics[0]
    assert diagnosis.availability == ("unsupported" if kind == "relative" else "incomplete")
    assert diagnosis.baseline is None
    assert diagnosis.limitations
    assert prepared.calculations[0].engine_verified is False


def test_changed_calls_invalidate_diagnosis_and_forged_outputs_are_rejected():
    raw = data()
    before = calculate_dashboard(DashboardBundle.model_validate(raw))
    raw["calls"][0]["call"]["distance_ft"] = 100.5
    changed = calculate_dashboard(DashboardBundle.model_validate(raw))
    assert changed.manifest.diagnostics_output_hash != before.manifest.diagnostics_output_hash
    assert changed.diagnostics[0].baseline.residual.magnitude_ft == pytest.approx(0.5)
    with pytest.raises(ValueError, match="deterministic"):
        validate_prepared_dashboard(changed.model_copy(update={"diagnostics": before.diagnostics}))
    assert before.diagnostics[0].baseline.residual.magnitude_ft < 1e-10


def test_source_uncertainty_is_not_chosen_from_closure():
    raw = data()
    raw["calls"][0].update(reading_status="uncertain", reading_note="Could be 100 or 100.5")
    prepared = calculate_dashboard(DashboardBundle.model_validate(raw))
    source = prepared.diagnostics[0].baseline.request.calls[0].source_refs[0]
    assert source.uncertainty == "Could be 100 or 100.5"
    assert prepared.calculations[0].source_review_complete is False
