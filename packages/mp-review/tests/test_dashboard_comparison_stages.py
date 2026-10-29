"""Comparison caches never trust stale derived content."""

import json
from pathlib import Path

from mp_models.dashboard import DashboardBundle
from mp_review.dashboard import dashboard_file, prepare_dashboard

FIXTURE = Path(__file__).parent / "fixtures/dashboard-comparison.json"


def test_comparison_stage_cache_replay_and_tamper_recalculation(tmp_path):
    bundle = DashboardBundle.model_validate_json(FIXTURE.read_bytes())
    cache = tmp_path / "cache"
    baseline = prepare_dashboard(bundle, cache_dir=cache)
    assert not baseline.manifest.cache_reused
    reused = prepare_dashboard(bundle, cache_dir=cache)
    assert reused.manifest.cache_reused
    assert baseline.description_comparisons == reused.description_comparisons
    (cache / "description-comparisons.json").write_text("[]")
    after = prepare_dashboard(bundle, cache_dir=cache)
    assert not after.manifest.cache_reused
    assert after.description_comparisons == baseline.description_comparisons
    assert json.loads((cache / "description-comparisons.json").read_bytes())


def test_dashboard_stages_comparison_and_source_without_mutating(tmp_path):
    source_before = FIXTURE.read_bytes()
    output = tmp_path / "dashboard"
    response = dashboard_file(FIXTURE, output)
    assert response["status"] == "needs_review"
    assert (output / "source.json").read_bytes() == source_before
    assert (
        json.loads((output / "description-comparisons.json").read_bytes())[0]["comparison"][
            "boundary_established"
        ]
        is False
    )
    assert "description-comparisons.json" in response["artifacts"]
    assert FIXTURE.read_bytes() == source_before
