"""Delivery GeoJSON availability is separate from scene-coordinate formats.

When no installed coordinate operation can serve the deed extent, only GeoJSON is
omitted (with a recorded whole-format reason); SVG/PDF/DXF still publish unless a
required layer or appearance would be lost. Derived corridor area checks use the
exported constructed polygon, and one publish builds the projection group once.
"""

import json
import math
from pathlib import Path

import pytest
from mp_models.delivery import DeliveryItem, DeliveryLayer, DeliveryRequest
from mp_models.plot import PlotPrimitive
from mp_review.delivery import load_delivery, prepare_delivery, publish_delivery

pytest.importorskip("pyproj")

_STORE = Path(__file__).with_name("test_delivery_store.py")


def _store():
    import importlib.util

    spec = importlib.util.spec_from_file_location("_delivery_store_unavailable", _STORE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _optional(request, **updates):
    data = request.model_dump(mode="json")
    for layer in data["layers"]:
        layer["required"] = False
    data.update(updates)
    return DeliveryRequest.model_validate(data)


@pytest.fixture
def unavailable(monkeypatch):
    import mp_review.webmap_projection as module

    calls = []

    def fail(scene, extent=None):
        calls.append(extent)
        raise module.WebMapUnavailable(
            "operation_unavailable", "No coordinate operation covers the placed display extent."
        )

    monkeypatch.setattr(module, "build_web_map_projection", fail)
    return calls


def test_unavailable_operation_omits_only_geojson(tmp_path, unavailable):
    bundle, revision, request = _store()._placed_case(tmp_path)
    request = _optional(request)
    result = publish_delivery(bundle, revision, request, tmp_path / "deliveries")
    assert result["status"] == "needs_review", result
    whole = [o for o in result["omissions"] if o["format"] == "geojson" and o["layer_id"] is None]
    assert any("No coordinate operation covers" in o["reason"] for o in whole), result
    directory = tmp_path / "deliveries" / request.id
    assert not (directory / "drawing.geojson").exists()
    assert "drawing.geojson" not in result["artifacts"]
    for name in ("drawing.svg", "drawing.pdf", "drawing.dxf"):
        assert (directory / name).is_file()
    manifest = json.loads((directory / "delivery-manifest.json").read_text())
    assert "drawing.geojson" not in manifest["artifacts"]
    # Replay reproduces and verifies the same omission outcome.
    snapshot = load_delivery(bundle, revision, directory)
    assert any(o.format == "geojson" and o.layer_id is None for o in snapshot.omissions)


def test_replay_accepts_recorded_geojson_omission_when_operation_becomes_available(
    tmp_path, monkeypatch
):
    # Replay trusts the recorded package: an operation that is installed on the
    # replay host does not invalidate a package published without it.
    import mp_review.webmap_projection as module

    real = module.build_web_map_projection

    def fail(scene, extent=None):
        raise module.WebMapUnavailable("missing_grid", "Required grids are unavailable locally.")

    monkeypatch.setattr(module, "build_web_map_projection", fail)
    bundle, revision, request = _store()._placed_case(tmp_path)
    request = _optional(request)
    result = publish_delivery(bundle, revision, request, tmp_path / "deliveries")
    assert result["status"] == "needs_review", result
    monkeypatch.setattr(module, "build_web_map_projection", real)
    snapshot = load_delivery(bundle, revision, tmp_path / "deliveries" / request.id)
    assert any(o.reason.startswith("GeoJSON omitted") for o in snapshot.omissions)


def test_required_layer_blocks_geojson_omission(tmp_path, unavailable):
    bundle, revision, request = _store()._placed_case(tmp_path)
    # The fixture marks the deed calculation and a context vector as required.
    result = publish_delivery(bundle, revision, request, tmp_path / "deliveries")
    assert result["status"] == "error", result
    assert any("No coordinate operation covers" in e for e in result["errors"]), result
    assert not (tmp_path / "deliveries" / request.id / "delivery-manifest.json").exists()


def test_required_appearance_blocks_geojson_omission(tmp_path, unavailable):
    bundle, revision, request = _store()._placed_case(tmp_path)
    data = _optional(request, required_appearance=True, labels=[]).model_dump(mode="json")
    data["layers"] = [layer for layer in data["layers"] if layer["kind"] != "raster"]
    request = DeliveryRequest.model_validate(data)
    with pytest.raises(ValueError, match="No coordinate operation covers"):
        prepare_delivery(bundle, revision, request)


def test_geojson_only_request_fails_when_operation_unavailable(tmp_path, unavailable):
    bundle, revision, request = _store()._placed_case(tmp_path)
    request = _optional(request, formats=["geojson"])
    with pytest.raises(ValueError, match="No coordinate operation covers"):
        prepare_delivery(bundle, revision, request)


def test_invalid_scene_still_fails(tmp_path, monkeypatch):
    import mp_review.webmap_projection as module

    def fail(scene, extent=None):
        raise module.WebMapUnavailable("invalid_scene", "Scene CRS, axes, or units are invalid.")

    monkeypatch.setattr(module, "build_web_map_projection", fail)
    bundle, revision, request = _store()._placed_case(tmp_path)
    with pytest.raises(ValueError, match="invalid"):
        prepare_delivery(bundle, revision, _optional(request))


def test_projection_group_is_built_once_per_publish(tmp_path, monkeypatch):
    import mp_review.webmap_projection as module

    real = module.build_web_map_projection
    calls = []

    def spy(scene, extent=None):
        calls.append(extent)
        return real(scene, extent=extent)

    monkeypatch.setattr(module, "build_web_map_projection", spy)
    bundle, revision, request = _store()._placed_case(tmp_path)
    result = publish_delivery(bundle, revision, request, tmp_path / "deliveries")
    assert result["status"] == "needs_review", result
    assert len(calls) == 1
    calls.clear()
    load_delivery(bundle, revision, tmp_path / "deliveries" / request.id)
    assert calls == []  # replay accepts the recorded operation/omissions; never rebuilds


def test_corridor_area_check_uses_exported_polygon_vertices(tmp_path, monkeypatch):
    """A cap arc whose bulge falls between coarse samples must still be checked."""
    import mp_review.webmap as webmap
    from mp_review.delivery import _geojson_area
    from mp_verify.plot import arc_point, transform_point

    bundle, revision, request = _store()._placed_case(tmp_path)
    snapshot = prepare_delivery(bundle, revision, request)
    scene = next(s for s in bundle.scenes if s.id == request.scene_id)
    deed = next(i for i in snapshot.items if i.selection.id == "calc-one")
    assert deed.plot is not None and deed.placement is not None
    radius = 500.0
    start_angle = math.radians(-20)
    start = (radius * math.cos(start_angle), radius * math.sin(start_angle))
    end = (-start[0], -start[1])
    arc = PlotPrimitive(
        kind="arc",
        call_id="cap",
        start=start,
        end=end,
        length_ft=math.pi * radius,
        center=(0.0, 0.0),
        radius_ft=radius,
        sweep_deg=180.0,
        curve_dir="left",
        start_tangent_deg=20.0,
    )
    line = PlotPrimitive(kind="line", call_id="chord", start=end, end=start, length_ft=2 * radius)
    geometry = deed.plot.geometry.model_copy(update={"primitives": (arc, line)})
    corridor = DeliveryItem(
        selection=DeliveryLayer(
            id="cap-corridor", kind="corridor", visible=True, opacity=1.0, required=False
        ),
        plot=deed.plot.model_copy(update={"geometry": geometry}),
        placement=deed.placement,
    )
    checked = {}
    real = webmap.require_area

    def spy(projection, extent):
        checked.setdefault("extents", []).append(extent)
        return real(projection, extent)

    monkeypatch.setattr(webmap, "require_area", spy)
    _geojson_area((*snapshot.items, corridor), scene, tolerance_m=request.geo_tolerance_m)
    dense = [
        transform_point(
            arc_point(arc, t / 2000),
            deed.placement,
            native_units=deed.plot.request.foot_definition,
            scene_units=scene.units,
        )
        for t in range(2001)
    ]
    corridor_extent = checked["extents"][-1]
    minx, miny, maxx, maxy = corridor_extent
    slack = 0.05  # exported vertices sit on the arc within the display tolerance
    assert maxx >= max(p[0] for p in dense) - slack
    assert maxy >= max(p[1] for p in dense) - slack
    assert minx <= min(p[0] for p in dense) + slack
    assert miny <= min(p[1] for p in dense) + slack
