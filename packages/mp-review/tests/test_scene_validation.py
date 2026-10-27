"""Supplied projected scenes must establish linear CRS semantics at every entry point."""

import builtins
import json
from pathlib import Path

import pytest
from mp_export.dashboard_html import render_dashboard
from mp_models.dashboard import DashboardBundle
from mp_review.dashboard import prepare_dashboard
from mp_verify.dashboard import calculate_dashboard, validate_prepared_dashboard

FIXTURE = Path(__file__).parent / "fixtures/dashboard-absolute.json"


def bundle(scene):
    data = json.loads(FIXTURE.read_text())
    data["schema_version"] = "1.1"
    data["scenes"] = [scene]
    return DashboardBundle.model_validate(data)


@pytest.mark.parametrize("crs,units", [("EPSG:4326", "m"), ("EPSG:3857", "us_survey_ft")])
@pytest.mark.parametrize("operation", ["prepare", "calculate", "validate", "render"])
def test_supplied_scene_cannot_claim_geographic_degrees_or_wrong_foot(
    crs, units, operation, monkeypatch
):
    scene = {
        "id": "map-scene",
        "name": "Supplied map",
        "kind": "projected",
        "crs": crs,
        "units": units,
    }
    supplied = bundle(scene)
    if operation in ("validate", "render"):
        # Model an untrusted payload whose author recomputed every derived hash.
        # Hash consistency alone must never establish the declared CRS semantics.
        with monkeypatch.context() as patch:
            patch.setattr("mp_verify.dashboard.validate_scene", lambda _: None)
            supplied_prepared = calculate_dashboard(supplied)

        def invoke():
            return (
                validate_prepared_dashboard(supplied_prepared)
                if operation == "validate"
                else render_dashboard(supplied_prepared)
            )
    else:

        def invoke():
            return (
                prepare_dashboard(supplied)
                if operation == "prepare"
                else calculate_dashboard(supplied)
            )

    with pytest.raises(ValueError, match="projected|units"):
        invoke()


def test_local_deed_only_does_not_load_optional_projection_dependency(monkeypatch):
    original_import = builtins.__import__

    def without_projection(name, *args, **kwargs):
        if name == "pyproj" or name.startswith("pyproj."):
            raise ImportError("optional dependency absent")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_projection)
    local = bundle({"id": "local-map", "name": "Local", "kind": "local", "units": "unknown_ft"})
    assert prepare_dashboard(local).calculations
    projected = bundle(
        {"id": "map", "name": "Projected", "kind": "projected", "crs": "EPSG:3857", "units": "m"}
    )
    with pytest.raises(ValueError, match=r"mp-review\[geo\]"):
        prepare_dashboard(projected)


@pytest.mark.parametrize(
    "crs,units",
    [
        ("EPSG:3857", "m"),
        ("EPSG:3424", "us_survey_ft"),
        ("+proj=merc +datum=WGS84 +units=ft +type=crs", "international_ft"),
    ],
)
def test_correct_projected_scene_units_survive_validation(crs, units):
    prepared = prepare_dashboard(
        bundle({"id": "map", "name": "Projected", "kind": "projected", "crs": crs, "units": units})
    )
    assert validate_prepared_dashboard(prepared) == prepared
