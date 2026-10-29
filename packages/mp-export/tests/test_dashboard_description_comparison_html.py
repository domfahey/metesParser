"""Comparison rendering keeps immutable findings and source-owned links."""

import json
import math
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


def test_arc_comparison_exposes_shape_components_with_explicit_criteria():
    data = json.loads(FIXTURE.read_text())
    for item in data["calls"]:
        if item["id"] in {"call-one", "call-one-v2"}:
            item["call"].update(
                curve_dir="right",
                radius_ft=40,
                delta_deg=90,
                arc_length_ft=20 * math.pi,
                distance_ft=20 * math.pi,
                chord_length_ft=40 * math.sqrt(2),
                chord_bearing="N 45°00'00\" E",
                bearing_azimuth_deg_from_north=0,
            )
    data["description_comparison_specs"][0]["tolerances"].update(radius=0.01, sweep_deg=0.01)
    html = render_dashboard(calculate_dashboard(DashboardBundle.model_validate(data)))
    for label in ("Radius", "Sweep", "Turn"):
        assert f"<th>{label}</th>" in html
    assert "Categorical" in html
