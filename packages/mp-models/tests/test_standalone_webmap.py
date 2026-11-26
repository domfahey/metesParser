"""Standalone map identity and source constraints require no dashboard scaffold."""

import base64
import hashlib

import pytest
from mp_models import StandaloneWebMapInput
from pydantic import ValidationError

SCENE = {"id": "grid", "name": "Grid", "kind": "projected", "crs": "EPSG:3857", "units": "m"}


def test_overlay_input_requires_scene_but_no_dashboard_records():
    value = StandaloneWebMapInput(title="County", scenes=(SCENE,))
    assert not value.plots
    assert "documents" not in value.model_dump()
    with pytest.raises(ValidationError, match="scenes"):
        StandaloneWebMapInput(title="County", scenes=())


@pytest.mark.parametrize(
    "field", ["documents", "occurrences", "calculations", "scenarios", "evidence"]
)
def test_standalone_does_not_accept_dashboard_review_records(field):
    with pytest.raises(ValidationError, match="Extra inputs"):
        StandaloneWebMapInput.model_validate({"title": "Map", "scenes": [SCENE], field: []})


@pytest.mark.parametrize("duplicate_group", ["map_sources", "scenes"])
def test_standalone_ids_are_globally_unique(duplicate_group):
    data = {"title": "Map", "scenes": [SCENE]}
    if duplicate_group == "map_sources":
        data["map_sources"] = [{"id": "grid", "label": "Duplicate", "sha256": "a" * 64}]
    else:
        data["scenes"].append(SCENE)
    with pytest.raises(ValidationError, match="globally unique"):
        StandaloneWebMapInput.model_validate(data)


def test_standalone_raster_source_content_must_match():
    data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZ1UAAAAASUVORK5CYII="
    )
    raster = {
        "id": "image",
        "label": "Map image",
        "source_id": "source",
        "scene_id": "grid",
        "mime_type": "image/png",
        "width": 1,
        "height": 1,
        "sha256": hashlib.sha256(data).hexdigest(),
        "data_base64": base64.b64encode(data).decode(),
        "registration": {"matrix": [1, 0, 0, 0, -1, 0], "method": "supplied_affine"},
    }
    source = {
        "id": "source",
        "label": "Supplied source",
        "sha256": raster["sha256"],
        "data_base64": raster["data_base64"],
        "filename": "map.png",
    }
    value = StandaloneWebMapInput.model_validate(
        {"title": "Map", "scenes": [SCENE], "map_sources": [source], "raster_layers": [raster]}
    )
    assert value.map_sources[0].filename == "map.png"
    changed = value.model_dump(mode="json")
    changed["map_sources"][0]["sha256"] = "a" * 64
    changed["map_sources"][0]["data_base64"] = None
    with pytest.raises(ValidationError, match="match its map source"):
        StandaloneWebMapInput.model_validate(changed)


def test_standalone_layer_and_placement_reference_guards():
    from mp_models import DeedCall, PlotCall, PlotRequest
    from mp_models.plot import PlotGeometry
    from mp_models.plot_request import PreparedPlot

    # Layer referencing unknown scene or source rejected.
    with pytest.raises(ValidationError, match="unknown scene or map source"):
        StandaloneWebMapInput.model_validate(
            {
                "title": "Map",
                "scenes": [SCENE],
                "vector_layers": [
                    {
                        "id": "v1",
                        "label": "V",
                        "source_id": "missing-src",
                        "scene_id": "grid",
                        "geometry_type": "Polygon",
                        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
                    }
                ],
            }
        )

    call = PlotCall(
        id="c1",
        call=DeedCall(
            course=1, direction_text="N", bearing_azimuth_deg_from_north=0.0, distance_ft=10.0
        ),
    )
    req = PlotRequest(title="P", calculation_id="calc1", calls=(call,))
    geom = PlotGeometry(
        id="calc1",
        calculation_id="calc1",
        frame_id="calc1:native",
        geometry_hash="a" * 64,
        completeness="unresolved",
    )
    plot = PreparedPlot(request=req, geometry=geom, input_hash="b" * 64)
    base_pl = {
        "id": "pl1",
        "calculation_id": "calc1",
        "geometry_hash": "a" * 64,
        "scene_id": "grid",
        "rationale": "manual",
    }

    # Placement unknown calculation/scene.
    with pytest.raises(ValidationError, match="unknown calculation or scene"):
        StandaloneWebMapInput.model_validate(
            {
                "title": "Map",
                "scenes": [SCENE],
                "plots": [plot],
                "placements": [base_pl | {"scene_id": "absent"}],
            }
        )
    # Scenario/baseline fields unsupported in standalone mode.
    with pytest.raises(ValidationError, match="scenario or baseline fields"):
        StandaloneWebMapInput.model_validate(
            {
                "title": "Map",
                "scenes": [SCENE],
                "plots": [plot],
                "placements": [
                    base_pl
                    | {
                        "scenario_id": "sc1",
                        "baseline_geometry_hash": "c" * 64,
                        "baseline_placement_id": "pl0",
                    }
                ],
            }
        )
    # Dashboard evidence_ids unsupported in standalone mode.
    with pytest.raises(ValidationError, match="unsupported dashboard evidence"):
        StandaloneWebMapInput.model_validate(
            {
                "title": "Map",
                "scenes": [SCENE],
                "plots": [plot],
                "placements": [base_pl | {"evidence_ids": ["ev1"]}],
            }
        )
    # Referenced status unsupported in standalone mode without orientation frame.
    with pytest.raises(ValidationError, match="explicit orientation frame"):
        StandaloneWebMapInput.model_validate(
            {
                "title": "Map",
                "scenes": [SCENE],
                "plots": [plot],
                "placements": [
                    base_pl
                    | {
                        "status": "referenced",
                        "position_evidence": ["monument"],
                        "orientation_evidence": ["basis"],
                    }
                ],
            }
        )
