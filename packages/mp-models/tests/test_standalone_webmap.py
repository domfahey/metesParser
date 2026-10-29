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
