"""Web map and delivery share raster-corner and displayed-point rules (PR #60 review)."""

import importlib.util
import math
from pathlib import Path

import mp_review.raster_registration as registration
import mp_review.webmap as webmap
import pytest


def _load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


layer_for = _load("test_webmap_raster").layer_for
_context = _load("test_delivery_context_area")
_far_context_module, _with_far_layer = _context._far_context_module, _context._with_far_layer


def test_raster_extent_matches_registered_outer_corners():
    raster = layer_for([[0, 1], [2, 3], [4, 5]], matrix=(2, 0.5, 100, 0.25, -3, 900))
    corners = registration.outer_corners(raster.registration, raster.width, raster.height)
    assert webmap._raster_extent(raster) == webmap.bounds_of(corners)


def test_raster_extent_uses_transform_pixel_nonfinite_handling():
    raster = layer_for([[0, 1], [2, 3]])
    bad = raster.model_copy(
        update={
            "registration": raster.registration.model_copy(
                update={"matrix": (math.inf, 0, 0, 0, 1, 0)}
            )
        }
    )
    with pytest.raises(ValueError, match="Nonfinite"):
        webmap._raster_extent(bad)


def test_raster_extent_delegates_to_registration_corners(monkeypatch):
    raster = layer_for([[0, 1], [2, 3]])
    seen = []
    original = registration.outer_corners

    def spy(*args):
        seen.append(args)
        return original(*args)

    monkeypatch.setattr(registration, "outer_corners", spy)
    webmap._raster_extent(raster)
    assert len(seen) == 1


def test_web_map_and_delivery_select_points_through_one_helper(tmp_path, monkeypatch):
    from mp_review.delivery import publish_delivery

    assert hasattr(webmap, "displayed_calculation_points")
    calls = []
    original = webmap.displayed_calculation_points

    def spy(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(webmap, "displayed_calculation_points", spy)
    bundle, revision, request = _far_context_module()._placed_case(tmp_path)
    request = _with_far_layer(request, required=False)
    assert publish_delivery(bundle, revision, request, tmp_path / "d")["status"] != "error"
    assert calls, "delivery GeoJSON area must use the shared helper"
    before = len(calls)
    partial = _load("test_webmap_partial_area")

    partial._run(partial._bundle())
    assert len(calls) > before, "web-map display extent must use the shared helper"
