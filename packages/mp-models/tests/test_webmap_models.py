"""Display contracts do not admit credentials or ambiguous geographic geometry."""

import pytest
from mp_models.webmap import (
    MapboxViewOptions,
    WebMapFeature,
    WebMapOptions,
    WebMapRequest,
)
from pydantic import ValidationError


def test_request_defaults_and_credentials_rejected():
    request = WebMapRequest(scene_id="nj-grid")
    assert request.display.tolerance_m == 0.05
    assert request.view.style == "standard"
    with pytest.raises(ValidationError):
        WebMapRequest(scene_id="nj-grid", token="not-a-real-token")
    with pytest.raises(ValidationError):
        MapboxViewOptions(access_token="not-a-real-token")
    with pytest.raises(ValidationError):
        request.scene_id = "changed"


@pytest.mark.parametrize(
    "field,value",
    [
        ("tolerance_m", float("nan")),
        ("tolerance_m", 0),
        ("max_vertices", 100001),
        ("max_depth", 21),
        ("max_raster_dimension", 4097),
        ("max_raster_pixels", 16777217),
        ("raster_pixel_size_m", -1),
    ],
)
def test_display_limits_are_bounded(field, value):
    with pytest.raises(ValidationError):
        WebMapOptions(**{field: value})


def test_feature_requires_geographic_coordinates_and_source_identity():
    feature = {
        "type": "Feature",
        "id": "course:one",
        "geometry": {"type": "LineString", "coordinates": [[-75, 40], [-75.001, 40.001]]},
        "properties": {
            "kind": "recorded_course",
            "calculation_id": "calc",
            "call_id": "one",
            "geometry_hash": "a" * 64,
            "placement_hash": "b" * 64,
            "placement_id": "placed",
            "placement_status": "approximate",
        },
    }
    assert WebMapFeature.model_validate(feature).geometry.coordinates[0] == (-75, 40)
    feature["geometry"]["coordinates"][0] = [400, 40]
    with pytest.raises(ValidationError):
        WebMapFeature.model_validate(feature)
    feature["geometry"]["coordinates"][0] = [-75, 40]
    feature["properties"].pop("call_id")
    with pytest.raises(ValidationError):
        WebMapFeature.model_validate(feature)


def test_gap_must_not_impersonate_recorded_call():
    with pytest.raises(ValidationError):
        WebMapFeature.model_validate(
            {
                "type": "Feature",
                "id": "gap",
                "geometry": {"type": "LineString", "coordinates": [[0, 0], [0.001, 0]]},
                "properties": {"kind": "closure_gap", "call_id": "invented"},
            }
        )


def test_view_has_closed_style_list_and_opacity_range():
    assert MapboxViewOptions(style="standard-satellite").provider == "mapbox"
    for fields in ({"style": "https://untrusted/style"}, {"raster_opacity": 2}):
        with pytest.raises(ValidationError):
            MapboxViewOptions(**fields)
