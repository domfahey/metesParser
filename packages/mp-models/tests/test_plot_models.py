"""Independent contract tests for immutable plotting and supplied map evidence."""

import json
from pathlib import Path

import pytest
from mp_models.dashboard import DashboardBundle
from mp_models.plot import PlotPlacement, PlotScene, VectorLayer
from pydantic import ValidationError

FIXTURE = Path(__file__).parents[2] / "mp-review/tests/fixtures/dashboard-absolute.json"


def bundle_data():
    return json.loads(FIXTURE.read_text())


def layer(**changes):
    data = {
        "id": "layer",
        "label": "Synthetic",
        "source_id": "map",
        "scene_id": "scene",
        "geometry_type": "Polygon",
        "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
    }
    data.update(changes)
    return VectorLayer.model_validate(data)


def test_v1_bundle_renders_without_plot_options():
    bundle = DashboardBundle.model_validate(bundle_data())
    assert DashboardBundle.model_validate(bundle.model_dump(mode="json")) == bundle


def test_v1_rejects_v11_overlay_fields():
    data = bundle_data()
    data["scenes"] = []
    with pytest.raises(ValidationError, match="1.1"):
        DashboardBundle.model_validate(data)


def test_plot_inputs_are_immutable():
    scene = PlotScene(id="scene", name="Local", kind="local", units="unknown_ft")
    with pytest.raises(ValidationError):
        scene.name = "changed"
    assert isinstance(layer().coordinates, tuple)


def test_local_scene_rejects_a_crs():
    with pytest.raises(ValidationError, match="local.*CRS"):
        PlotScene(id="scene", name="Local", kind="local", units="m", crs="EPSG:4326")


@pytest.mark.parametrize(
    "coords",
    [
        [[[0, 0], [10, 0], [10, 10], [0, 10]]],
        [[[0, 0], [10, 10], [0, 10], [10, 0], [0, 0]]],
        [[[0, 0], [1, 0], [2, 0], [0, 0]]],
        [[[0, 0], [float("nan"), 0], [10, 10], [0, 0]]],
        [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]], [[20, 20], [21, 20], [21, 21], [20, 20]]],
    ],
)
def test_layer_rejects_nonfinite_invalid_rings_and_unknown_units(coords):
    with pytest.raises(ValidationError):
        layer(coordinates=coords)
    with pytest.raises(ValidationError):
        PlotScene(id="scene", name="Bad", kind="local", units="furlong")


def test_layer_preserves_holes_and_multipolygons():
    rings = [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]], [[2, 2], [3, 2], [3, 3], [2, 3], [2, 2]]]
    assert len(layer(coordinates=rings).coordinates) == 2
    assert len(layer(geometry_type="MultiPolygon", coordinates=[rings]).coordinates) == 1


@pytest.mark.parametrize("reverse", [False, True])
def test_multipolygon_rejects_members_crossing_another_members_hole(reverse):
    outer = ((0, 0), (10, 0), (10, 10), (0, 10), (0, 0))
    hole = ((3, 3), (7, 3), (7, 7), (3, 7), (3, 3))
    crossing = ((4, 4), (9, 4), (9, 6), (4, 6), (4, 4))
    polygons = ((outer, hole), (crossing,))
    with pytest.raises(ValidationError, match="multipolygon"):
        layer(
            geometry_type="MultiPolygon",
            coordinates=polygons[::-1] if reverse else polygons,
        )


def test_multipolygon_preserves_an_island_wholly_within_another_members_hole():
    outer = ((0, 0), (10, 0), (10, 10), (0, 10), (0, 0))
    hole = ((3, 3), (7, 3), (7, 7), (3, 7), (3, 3))
    island = ((4, 4), (6, 4), (6, 6), (4, 6), (4, 4))
    polygons = ((outer, hole), (island,))
    assert layer(geometry_type="MultiPolygon", coordinates=polygons).coordinates == polygons


def test_referenced_placement_requires_position_and_orientation_evidence():
    with pytest.raises(ValidationError, match="orientation"):
        PlotPlacement(
            id="p",
            calculation_id="calc",
            geometry_hash="a" * 64,
            scene_id="s",
            status="referenced",
            rationale="one point",
            position_evidence=("address",),
        )


@pytest.mark.parametrize("field", ["scale", "shear", "reflection"])
def test_placement_rejects_scale_shear_reflection(field):
    with pytest.raises(ValidationError):
        PlotPlacement(
            id="p",
            calculation_id="calc",
            geometry_hash="a" * 64,
            scene_id="s",
            rationale="manual",
            **{field: 1},
        )


def test_blank_evidence_does_not_establish_referenced_placement():
    with pytest.raises(ValidationError, match="evidence"):
        PlotPlacement(
            id="p",
            calculation_id="calc",
            geometry_hash="a" * 64,
            scene_id="s",
            status="referenced",
            rationale="claimed",
            position_evidence=(" ",),
            orientation_evidence=("",),
        )


def test_plot_references_resolve_to_same_occurrence():
    data = bundle_data()
    data["schema_version"] = "1.1"
    data["scenes"] = [{"id": "scene", "name": "Local", "kind": "local", "units": "unknown_ft"}]
    data["placements"] = [
        {
            "id": "placement",
            "calculation_id": data["calculations"][0]["id"],
            "geometry_hash": "a" * 64,
            "scene_id": "scene",
            "rationale": "manual",
            "evidence_ids": ["missing"],
        }
    ]
    with pytest.raises(ValidationError, match="cross-occurrence evidence"):
        DashboardBundle.model_validate(data)


@pytest.mark.parametrize("reference", ["placement", "call"])
def test_comparison_source_references_are_validated(reference):
    data = bundle_data()
    data["schema_version"] = "1.1"
    data["scenes"] = [{"id": "scene", "name": "Local", "kind": "local", "units": "unknown_ft"}]
    data["placements"] = [
        {
            "id": "placement",
            "calculation_id": data["calculations"][0]["id"],
            "geometry_hash": "a" * 64,
            "scene_id": "scene",
            "rationale": "manual",
        }
    ]
    point = {"id": "control", "deed_point": [0, 0], "map_point": [1, 1]}
    if reference == "call":
        other = dict(data["occurrences"][0], id="other-occurrence")
        data["occurrences"].append(other)
        data["calls"].append(dict(data["calls"][0], id="other-call", occurrence_id=other["id"]))
        point["call_id"] = "other-call"
    data["comparison_specs"] = [
        {
            "id": "comparison",
            "placement_id": "missing" if reference == "placement" else "placement",
            "correspondences": [point],
        }
    ]
    with pytest.raises(ValidationError, match="unknown placement|cross-occurrence call"):
        DashboardBundle.model_validate(data)


def test_v1_rejects_comparison_specs_even_when_empty():
    data = bundle_data()
    data["comparison_specs"] = []
    with pytest.raises(ValidationError, match="1.1"):
        DashboardBundle.model_validate(data)
