"""The point of beginning is the traverse origin, even when course 1 is chord-only."""

import importlib.util
import math
import re
from pathlib import Path

import pytest
from mp_export.dashboard_html import render_dashboard
from mp_export.plot_html import render_plot
from mp_models.deed_call import DeedCall
from mp_models.plot_request import PlotCall, PlotRequest
from mp_models.webmap import WebMapOptions
from mp_review.webmap import prepare_web_map
from mp_verify.plot import prepare_plot
from mp_verify.webmap import validate_web_map_artifact

_spec = importlib.util.spec_from_file_location(
    "_webmap_fixtures", Path(__file__).with_name("test_webmap.py")
)
_fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixtures)
mapped = _fixtures.mapped

CHORD_FIRST = {
    "course": 1,
    "direction_text": "curve to the right",
    "distance_ft": 150,
    "curve_dir": "right",
    "radius_ft": 200,
    "chord_bearing": "N 10°00' E",
    "chord_length_ft": 150,
}


def _chord_first(data):
    data["calls"][0]["call"] = dict(CHORD_FIRST)


def _pob_circle(html):
    match = re.search(r'class="pob-marker" cx="([^"]+)" cy="([^"]+)"', html)
    return float(match[1]), float(match[2])


def test_plot_html_pob_is_origin_not_chord_end():
    chord = DeedCall(**CHORD_FIRST)
    line = DeedCall(course=2, direction_text="x", bearing_azimuth_deg_from_north=90, distance_ft=50)
    prepared = prepare_plot(
        PlotRequest(title="t", calls=(PlotCall(id="c1", call=chord), PlotCall(id="c2", call=line)))
    )
    assert prepared.geometry.primitives[0].start != (0.0, 0.0)
    assert _pob_circle(render_plot(prepared)) == (0.0, 0.0)


def test_dashboard_pob_is_origin_not_chord_end():
    prepared = mapped(edit=_chord_first)
    assert prepared.plots.geometries[0].primitives[0].start != (0.0, 0.0)
    # Same placement as the drawn-first fixture, so the POB circle is where it is there.
    assert _pob_circle(render_dashboard(prepared)) == pytest.approx(
        _pob_circle(render_dashboard(mapped())), abs=1e-9
    )


def _lonlat_shift(coord, dx_m, dy_m):
    radius = 6378137.0
    lon, lat = coord
    x = radius * math.radians(lon) + dx_m
    y = radius * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) + dy_m
    return (
        math.degrees(x / radius),
        math.degrees(2 * math.atan(math.exp(y / radius)) - math.pi / 2),
    )


def _build(edit=None):
    prepared = mapped(edit=edit)
    artifact = prepare_web_map(prepared, scene_id="grid", options=WebMapOptions()).artifact
    return prepared, artifact


def _pob(artifact):
    return next(f for f in artifact.features if f.properties.kind == "pob")


def test_webmap_pob_is_origin_and_validation_enforces_it():
    _, drawn = _build()
    prepared, artifact = _build(_chord_first)
    assert _pob(artifact).geometry.coordinates == pytest.approx(
        _pob(drawn).geometry.coordinates, abs=1e-12
    )
    assert validate_web_map_artifact(prepared, artifact) == artifact

    # The chord end (N 10 E 150 ft) is not the point of beginning.
    ft = 0.3048
    dx, dy = 150 * math.sin(math.radians(10)) * ft, 150 * math.cos(math.radians(10)) * ft
    wrong = _lonlat_shift(_pob(artifact).geometry.coordinates, dx, dy)
    features = tuple(
        f.model_copy(update={"geometry": type(f.geometry)(coordinates=wrong)})
        if f.properties.kind == "pob"
        else f
        for f in artifact.features
    )
    with pytest.raises(ValueError, match="point of beginning"):
        validate_web_map_artifact(prepared, artifact.model_copy(update={"features": features}))


def test_drawn_first_geometry_serialization_is_unchanged():
    geometry = mapped().plots.geometries[0]
    assert geometry.point_of_beginning is None
    assert "point_of_beginning" not in geometry.model_dump(mode="json")
    assert "point_of_beginning" not in geometry.model_dump_json()
    chord = mapped(edit=_chord_first).plots.geometries[0]
    assert chord.point_of_beginning == (0.0, 0.0)
    assert type(chord).model_validate(chord.model_dump(mode="json")) == chord
