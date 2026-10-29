"""Out-of-area context evidence is omitted per item; the deed decides the operation (PR #60 review)."""

import importlib.util
from io import BytesIO
from pathlib import Path

import pytest
from mp_models.dashboard import DashboardBundle
from mp_models.plot import PlotScene
from mp_models.webmap import WebMapOptions
from mp_review.dashboard import prepare_dashboard
from mp_review.webmap import prepare_web_map
from mp_verify.webmap import validate_web_map_artifact

pyproj = pytest.importorskip("pyproj")

_spec = importlib.util.spec_from_file_location(
    "_webmap_fixtures", Path(__file__).with_name("test_webmap.py")
)
_fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixtures)

CRS = "EPSG:24376"  # Kalianpur 1880 / India zone I; bounded area of use
FAR = 6_000_000  # metres east of the parcel: outside the CRS area of use


def _origin(lon, lat):
    return pyproj.Transformer.from_crs(4326, CRS, always_xy=True).transform(lon, lat)


def _square(x, y, half):
    ring = [[x - half, y - half], [x + half, y - half], [x + half, y + half], [x - half, y + half]]
    return [[*ring, ring[0]]]


def _bundle(lon=74.0, lat=34.0):
    prepared = _fixtures.mapped(translation=_origin(lon, lat))
    data = prepared.bundle.model_dump(mode="json")
    data["scenes"][0]["crs"] = CRS
    return data


def _vector_data(data, layers):
    data["map_sources"] = [{"id": "source", "label": "Synthetic", "sha256": "0" * 64}]
    data["vector_layers"] = [
        {
            "id": layer_id,
            "label": layer_id,
            "source_id": "source",
            "scene_id": "grid",
            "geometry_type": "Polygon",
            "coordinates": _square(x, y, half),
        }
        for layer_id, x, y, half in layers
    ]


def _run(data):
    prepared = prepare_dashboard(DashboardBundle.model_validate(data))
    artifact = prepare_web_map(prepared, scene_id="grid", options=WebMapOptions()).artifact
    return prepared, artifact


def test_out_of_area_vector_layer_is_omitted_and_parcel_kept():
    data = _bundle()
    x, y = _origin(74.0, 34.0)
    _vector_data(data, [("near", x, y, 500), ("far", x + FAR, y, 500)])
    prepared, artifact = _run(data)
    assert artifact.availability == "partial"
    layer_ids = {f.properties.layer_id for f in artifact.features}
    assert "near" in layer_ids and "far" not in layer_ids
    assert any(f.properties.call_id for f in artifact.features)
    omitted = [(i.kind, i.item_id) for i in artifact.unavailable]
    assert ("vector", "far") in omitted and ("scene", "grid") not in omitted
    assert validate_web_map_artifact(prepared, artifact) == artifact


def test_out_of_area_raster_is_omitted_and_parcel_kept():
    from mp_review.raster_registration import image_layer, supplied_affine
    from PIL import Image

    data = _bundle()
    x, y = _origin(74.0, 34.0)
    scene = PlotScene.model_validate(data["scenes"][0])
    stream = BytesIO()
    Image.new("RGBA", (2, 2), (255, 255, 255, 255)).save(stream, format="PNG")
    layers = []
    for layer_id, ox in (("scan-near", x), ("scan-far", x + FAR)):
        layer, source = image_layer(
            stream.getvalue(),
            scene=scene,
            registration=supplied_affine((1, 0, ox, 0, -1, y)),
            filename=f"{layer_id}.png",
        )
        layers.append(layer.model_copy(update={"id": layer_id}))
    data["map_sources"] = [source.model_dump(mode="json")]
    data["raster_layers"] = [layer.model_dump(mode="json") for layer in layers]
    prepared, artifact = _run(data)
    assert [r.id for r in artifact.rasters] == ["scan-near"]
    assert any(f.properties.call_id for f in artifact.features)
    omitted = [(i.kind, i.item_id) for i in artifact.unavailable]
    assert ("raster", "scan-far") in omitted and ("scene", "grid") not in omitted
    assert validate_web_map_artifact(prepared, artifact) == artifact


def test_parcel_outside_every_covering_operation_still_fails_closed():
    data = _bundle()
    x, y = _origin(74.0, 34.0)
    data["placements"][0]["translation"] = [x + FAR, y]  # parcel itself outside the area
    _vector_data(data, [("near", x, y, 500)])
    _, artifact = _run(data)
    assert artifact.availability == "unavailable"
    assert artifact.features == () and artifact.rasters == ()
    assert [(i.kind, i.item_id) for i in artifact.unavailable] == [("scene", "grid")]


def test_all_inside_scene_is_unchanged():
    data = _bundle()
    x, y = _origin(74.0, 34.0)
    _vector_data(data, [("near", x, y, 500)])
    prepared, artifact = _run(data)
    assert artifact.availability == "ready" and artifact.unavailable == ()
    assert validate_web_map_artifact(prepared, artifact) == artifact
