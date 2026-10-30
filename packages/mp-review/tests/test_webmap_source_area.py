"""The area-of-use guard must also respect the source CRS's own area of use."""

from types import SimpleNamespace

import pytest
from mp_models.plot import PlotScene
from mp_review.webmap_projection import (
    WebMapUnavailable,
    _covers_both,
    build_web_map_projection,
)

pyproj = pytest.importorskip("pyproj")

NJ = (-74.4, 40.2)
TEXAS = (-97.0, 31.0)
LA = (-118.2, 34.0)


def scene(crs, units):
    return PlotScene(id="g", name="G", kind="projected", crs=crs, units=units, basis="grid")


def around(code, lon_lat, half=50.0):
    x, y = pyproj.Transformer.from_crs(4326, code, always_xy=True).transform(*lon_lat)
    return (x - half, y - half, x + half, y + half)


def test_nj_placement_in_nj_state_plane_6527_is_covered():
    extent = around(6527, NJ)
    projection = build_web_map_projection(scene("EPSG:6527", "us_survey_ft"), extent=extent)
    assert projection.covers(extent)


def test_texas_extent_is_outside_nj_state_plane_6527_even_if_operation_covers_it():
    projection = build_web_map_projection(
        scene("EPSG:6527", "us_survey_ft"), extent=around(6527, NJ)
    )
    assert not projection.covers(around(6527, TEXAS))


def test_deed_extent_far_from_zone_fails_closed():
    with pytest.raises(WebMapUnavailable) as caught:
        build_web_map_projection(scene("EPSG:6527", "us_survey_ft"), extent=around(6527, TEXAS))
    assert caught.value.code == "operation_unavailable"


def test_utm_18n_far_zone_is_outside():
    projection = build_web_map_projection(scene("EPSG:32618", "m"), extent=around(32618, NJ))
    assert projection.covers(around(32618, NJ))
    assert not projection.covers(around(32618, LA))
    with pytest.raises(WebMapUnavailable):
        build_web_map_projection(scene("EPSG:32618", "m"), extent=around(32618, LA))


def test_missing_source_area_falls_back_to_operation_area():
    op = SimpleNamespace(west=-180.0, south=-90.0, east=180.0, north=90.0)
    assert _covers_both(op, None, (-97.0, 30.0, -96.0, 31.0))
    src = SimpleNamespace(west=-80.0, south=38.0, east=-73.0, north=42.0)
    assert not _covers_both(op, src, (-97.0, 30.0, -96.0, 31.0))
    assert _covers_both(op, src, (-75.0, 39.0, -74.0, 40.0))
