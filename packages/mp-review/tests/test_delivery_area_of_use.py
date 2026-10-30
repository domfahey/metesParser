"""Delivery GeoJSON selects its operation by delivered extent, like the online map (PR #60 review)."""

import types
from pathlib import Path

import pytest
from mp_review.delivery import publish_delivery

pytest.importorskip("pyproj")

_source = (Path(__file__).with_name("test_delivery_store.py")).read_text()
# Same placed case, but the scene frame is EPSG:24376 (whose first listed operation
# covers only southern Pakistan) instead of Web Mercator.
_module = types.ModuleType("_delivery_store_24376")
_module.__file__ = str(Path(__file__).with_name("test_delivery_store.py"))
exec(
    compile(
        _source.replace('"crs": "EPSG:3857",', '"crs": "EPSG:24376",', 1), _module.__file__, "exec"
    ),
    _module.__dict__,
)  # noqa: S102


def test_delivery_passes_deed_extent_to_projection(tmp_path, monkeypatch):
    import mp_review.webmap_projection as module

    seen = {}
    real = module.build_web_map_projection

    def spy(scene, extent=None):
        seen["extent"] = extent
        return real(scene, extent=extent)

    monkeypatch.setattr(module, "build_web_map_projection", spy)
    bundle, revision, request = _module._placed_case(tmp_path)
    publish_delivery(bundle, revision, request, tmp_path / "deliveries")
    minx, miny, maxx, maxy = seen["extent"]
    # Deed courses alone choose the operation, like prepare_web_map; the context
    # layer (990..1050, 1990..2040) is checked against it individually.
    assert minx <= 1000 <= maxx and miny <= 2000 <= maxy
    assert minx > 990 and maxy < 2040


def test_geojson_outside_operation_area_of_use_fails_closed(tmp_path):
    bundle, revision, request = _module._placed_case(tmp_path)
    result = publish_delivery(bundle, revision, request, tmp_path / "deliveries")
    assert result["status"] == "error", result
    assert any("operation" in e.lower() or "area" in e.lower() for e in result["errors"]), result
    assert not (tmp_path / "deliveries" / request.id / "delivery-manifest.json").exists()


def _shifted_module(x0, y0):
    """Same placed case translated so it sits at the given EPSG:24376 easting/northing."""
    import re

    def shift(match):
        value = float(match.group(0))
        return repr(value + (x0 if value < 1500 else y0))

    shifted = re.sub(r"\b(?:99\d|10[0-5]\d|1000|199\d|20[0-4]\d|2000|2010)\.0\b", shift, _source)
    shifted = shifted.replace('"crs": "EPSG:3857",', '"crs": "EPSG:24376",', 1)
    module = types.ModuleType("_delivery_store_shifted")
    module.__file__ = str(Path(__file__).with_name("test_delivery_store.py"))
    exec(compile(shifted, module.__file__, "exec"), module.__dict__)  # noqa: S102
    return module


def test_delivery_uses_the_same_covering_operation_as_prepare_web_map(tmp_path, monkeypatch):
    import json

    import mp_review.webmap_projection as module
    from mp_models.plot import PlotScene
    from pyproj import Transformer

    x0, y0 = Transformer.from_crs(4326, 24376, always_xy=True).transform(74, 34)
    case = _shifted_module(x0 - 1000, y0 - 2000)
    chosen = []
    real = module.build_web_map_projection

    def spy(scene, extent=None):
        projection = real(scene, extent=extent)
        chosen.append(projection.pipeline)
        return projection

    monkeypatch.setattr(module, "build_web_map_projection", spy)
    bundle, revision, request = case._placed_case(tmp_path)
    result = publish_delivery(bundle, revision, request, tmp_path / "deliveries")
    assert result["status"] == "needs_review", result
    scene = PlotScene(id="g", name="g", kind="projected", crs="EPSG:24376", units="m", basis="g")
    first_listed = real(scene).pipeline
    assert chosen and chosen[0] != first_listed  # not the Pakistan-south default operation
    geojson = json.loads((tmp_path / "deliveries" / request.id / "drawing.geojson").read_text())
    course = next(f for f in geojson["features"] if f["properties"]["kind"] == "recorded_course")
    lon, lat = course["geometry"]["coordinates"][0]
    assert (lon, lat) == pytest.approx((74, 34), abs=0.01)
