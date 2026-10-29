"""Operation selection must be area-aware and fail closed outside its area of use (#68)."""

import importlib.util
from pathlib import Path

import pytest
from mp_models.plot import PlotScene
from mp_models.webmap import WebMapOptions
from mp_review.webmap import prepare_web_map
from mp_review.webmap_projection import WebMapUnavailable, build_web_map_projection

pyproj = pytest.importorskip("pyproj")

_spec = importlib.util.spec_from_file_location(
    "_webmap_fixtures", Path(__file__).with_name("test_webmap.py")
)
_fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixtures)


def scene(crs):
    return PlotScene(id="grid", name="Grid", kind="projected", crs=crs, units="m", basis="grid")


def native(code, lon, lat):
    """Easting/northing (XY) of a geographic point, from an independent transformer."""
    return pyproj.Transformer.from_crs(4326, code, always_xy=True).transform(lon, lat)


def extent_around(code, lon, lat, half=50.0):
    x, y = native(code, lon, lat)
    return (x - half, y - half, x + half, y + half)


def test_operation_covering_the_extent_is_selected_not_first_listed():
    # Without an area of interest the first listed operation (3 m, Pakistan-south
    # area of use 68-71E, 24-28N) is chosen, which does not contain 74E, 34N.
    plain = build_web_map_projection(scene("EPSG:24376"))
    assert plain.accuracy == 3.0
    projection = build_web_map_projection(scene("EPSG:24376"), extent=extent_around(24376, 74, 34))
    assert projection.pipeline != plain.pipeline
    assert projection.accuracy is None  # the covering operation has unknown accuracy


def test_no_operation_covering_the_extent_fails_closed():
    with pytest.raises(WebMapUnavailable) as caught:
        build_web_map_projection(scene("EPSG:21419"), extent=extent_around(21419, 111.5, 40))
    assert caught.value.code == "operation_unavailable"


def test_extent_larger_than_operation_area_of_use_fails_closed():
    x0, y0 = native(24376, 74, 34)
    x1, y1 = native(24376, 80, 34)  # beyond the 77.83E limit of the covering operation
    with pytest.raises(WebMapUnavailable) as caught:
        build_web_map_projection(scene("EPSG:24376"), extent=(x0, y0, x1, y1 + 1))
    assert caught.value.code == "operation_unavailable"


def test_prepare_passes_placed_extent_to_projection(monkeypatch):
    import mp_review.webmap as module

    seen = {}
    real = module.build_web_map_projection

    def spy(scene_value, extent=None):
        seen["extent"] = extent
        return real(scene_value, extent=extent)

    monkeypatch.setattr(module, "build_web_map_projection", spy)
    prepared = _fixtures.mapped(translation=(1000, 2000))
    prepare_web_map(prepared, scene_id="grid", options=WebMapOptions())
    minx, miny, maxx, maxy = seen["extent"]
    assert minx <= 1000 <= maxx and miny <= 2000 <= maxy
    assert maxx - minx < 1000 and maxy - miny < 1000
