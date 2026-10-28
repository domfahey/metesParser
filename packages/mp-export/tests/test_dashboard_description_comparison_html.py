"""Comparison rendering keeps immutable findings and source-owned links."""

from pathlib import Path

import pytest
from mp_export.dashboard_html import render_dashboard
from mp_models.dashboard import DashboardBundle
from mp_verify.dashboard import calculate_dashboard

FIXTURE = Path(__file__).resolve().parents[2] / "mp-review/tests/fixtures/dashboard-comparison.json"


def prepared():
    return calculate_dashboard(DashboardBundle.model_validate_json(FIXTURE.read_bytes()))


def test_comparison_html_retains_verbatim_changed_fields_and_two_version_links():
    value = prepared()
    before = value.model_dump(mode="json")
    html = render_dashboard(value)
    assert 'id="description-comparisons"' in html
    assert 'data-comparison-source="call-one"' in html
    assert 'data-comparison-source="call-one-v2"' in html
    assert "original iron pipe" in html and "replacement iron pin" in html
    assert "not_comparable" in html
    assert "Same physical or legal boundary is not established" in html
    assert value.model_dump(mode="json") == before


def test_forged_comparison_rejected_before_rendering():
    value = prepared()
    with pytest.raises(ValueError, match="deterministic"):
        render_dashboard(value.model_copy(update={"description_comparisons": ()}))
