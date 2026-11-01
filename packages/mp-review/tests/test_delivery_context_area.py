"""Delivery GeoJSON picks its operation from deed geometry and omits out-of-area context.

Mirrors ``prepare_web_map``: context vector layers and derived (corridor/PLSS)
sources never choose the coordinate operation while deed geometry is present;
each is checked against the deed-selected operation's area of use individually.
"""

import json
import re
import types
from pathlib import Path

import pytest
from mp_models.delivery import DeliveryItem, DeliveryLayer, DeliveryRequest
from mp_review.delivery import load_delivery, prepare_delivery, publish_delivery

pytest.importorskip("pyproj")

_STORE = Path(__file__).with_name("test_delivery_store.py")


def _far_context_module():
    """Placed case in EPSG:24376 at (74E, 34N) plus a context layer at (80E, 20N).

    The deed-selected (northern Pakistan) operation does not cover (80E, 20N), and
    no operation covers the union of both extents.
    """
    from pyproj import Transformer

    to_grid = Transformer.from_crs(4326, 24376, always_xy=True)
    x0, y0 = to_grid.transform(74, 34)
    x0, y0 = x0 - 1000, y0 - 2000
    fx, fy = to_grid.transform(80, 20)
    source = _STORE.read_text()

    def shift(match):
        value = float(match.group(0))
        return repr(value + (x0 if value < 1500 else y0))

    source = re.sub(r"\b(?:99\d|10[0-5]\d|1000|199\d|20[0-4]\d|2000|2010)\.0\b", shift, source)
    source = source.replace('"crs": "EPSG:3857",', '"crs": "EPSG:24376",', 1)
    far = (
        '{"id": "far-context", "label": "Far context", "source_id": "context-source", '
        '"scene_id": "scene", "geometry_type": "Polygon", "coordinates": [['
        f"[{fx}, {fy}], [{fx + 50}, {fy}], [{fx + 50}, {fy + 50}], [{fx}, {fy + 50}], [{fx}, {fy}]"
        "]]}"
    )
    marker = 'data["vector_layers"] = [vector, vector | {"id": "hidden-context"}]'
    assert marker in source
    source = source.replace(
        marker, f'data["vector_layers"] = [vector, vector | {{"id": "hidden-context"}}, {far}]'
    )
    module = types.ModuleType("_delivery_store_far_context")
    module.__file__ = str(_STORE)
    exec(compile(source, module.__file__, "exec"), module.__dict__)  # noqa: S102
    return module


def _with_far_layer(request, *, required):
    data = request.model_dump(mode="json")
    data["layers"].append(
        {
            "id": "far-context",
            "kind": "vector",
            "visible": True,
            "opacity": 1.0,
            "required": required,
        }
    )
    return DeliveryRequest.model_validate(data)


def test_out_of_area_context_layer_is_omitted_not_fatal(tmp_path):
    bundle, revision, request = _far_context_module()._placed_case(tmp_path)
    request = _with_far_layer(request, required=False)
    result = publish_delivery(bundle, revision, request, tmp_path / "deliveries")
    assert result["status"] == "needs_review", result
    omitted = [
        o
        for o in result["omissions"]
        if o["layer_id"] == "far-context" and o["format"] == "geojson"
    ]
    assert len(omitted) == 1 and "area of use" in omitted[0]["reason"], result["omissions"]
    directory = tmp_path / "deliveries" / request.id
    features = json.loads((directory / "drawing.geojson").read_text())["features"]
    layers = {f["properties"]["delivery_layer_id"] for f in features}
    assert "far-context" not in layers
    assert {"calc-one", "context"} <= layers
    # Scene-coordinate formats are not projected; the layer stays in them.
    assert 'data-layer-id="far-context"' in (directory / "drawing.svg").read_text()
    snapshot = load_delivery(bundle, revision, directory)
    assert any(o.layer_id == "far-context" and o.format == "geojson" for o in snapshot.omissions)


def test_required_out_of_area_context_layer_fails_closed(tmp_path):
    bundle, revision, request = _far_context_module()._placed_case(tmp_path)
    request = _with_far_layer(request, required=True)
    result = publish_delivery(bundle, revision, request, tmp_path / "deliveries")
    assert result["status"] == "error", result
    assert any("far-context" in e and "area of use" in e for e in result["errors"]), result
    assert not (tmp_path / "deliveries" / request.id / "delivery-manifest.json").exists()


def test_operation_extent_excludes_context_layers(tmp_path, monkeypatch):
    import mp_review.webmap_projection as module

    seen = []
    real = module.build_web_map_projection

    def spy(scene, extent=None):
        seen.append(extent)
        return real(scene, extent=extent)

    monkeypatch.setattr(module, "build_web_map_projection", spy)
    bundle, revision, request = _far_context_module()._placed_case(tmp_path)
    request = _with_far_layer(request, required=False)
    publish_delivery(bundle, revision, request, tmp_path / "deliveries")
    assert seen
    for extent in seen:
        minx, miny, maxx, maxy = extent
        # Deed courses only: well under a kilometre, not the far context layer.
        assert maxx - minx < 1000 and maxy - miny < 1000


def test_out_of_area_derived_sources_are_checked_like_context(tmp_path):
    from mp_review.delivery import _geojson_area

    module = _far_context_module()
    bundle, revision, request = module._placed_case(tmp_path)
    snapshot = prepare_delivery(bundle, revision, request)
    scene = next(s for s in bundle.scenes if s.id == request.scene_id)
    far = next(v for v in bundle.vector_layers if v.id == "far-context")
    near = next(v for v in bundle.vector_layers if v.id == "context")

    def plss(layer_id, vector, required):
        return DeliveryItem(
            selection=DeliveryLayer(
                id=layer_id, kind="plss_reference", visible=True, opacity=1.0, required=required
            ),
            vector=vector,
        )

    deed = next(i for i in snapshot.items if i.selection.id == "calc-one")
    assert deed.placement is not None

    def corridor(layer_id, translation):
        return DeliveryItem(
            selection=DeliveryLayer(
                id=layer_id, kind="corridor", visible=True, opacity=1.0, required=False
            ),
            plot=deed.plot,
            placement=deed.placement.model_copy(update={"translation": translation}),
        )

    far_xy = far.coordinates[0][0]
    items = (
        *snapshot.items,
        plss("far-plss", far, False),
        plss("near-plss", near, False),
        corridor("far-corridor", (far_xy[0], far_xy[1])),
        corridor("near-corridor", deed.placement.translation),
    )
    outside = _geojson_area(items, scene).outside
    assert set(outside) == {"far-plss", "far-corridor"}


def test_shared_extent_helper_is_used_by_web_map_and_delivery():
    import inspect

    import mp_review.delivery as delivery
    import mp_review.webmap as webmap

    assert not hasattr(delivery, "_delivery_extent")
    assert "_primitive_point" not in inspect.getsource(delivery)
    assert "displayed_calculation_points" in inspect.getsource(webmap._display_extent)
    assert "operation_extent" in inspect.getsource(webmap._display_extent)
