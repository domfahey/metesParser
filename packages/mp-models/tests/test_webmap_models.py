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
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        WebMapRequest(scene_id="nj-grid", token="not-a-real-token")
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        MapboxViewOptions(access_token="not-a-real-token")
    with pytest.raises(ValidationError, match="Instance is frozen"):
        request.scene_id = "changed"


@pytest.mark.parametrize(
    ("field", "value", "expected_match"),
    [
        ("tolerance_m", float("nan"), "finite number"),
        ("tolerance_m", 0, "greater than 0"),
        ("max_vertices", 100001, "less than or equal to 100000"),
        ("max_depth", 21, "less than or equal to 20"),
        ("max_raster_dimension", 4097, "less than or equal to 4096"),
        ("max_raster_pixels", 16777217, "less than or equal to 16777216"),
        ("raster_pixel_size_m", -1, "greater than 0"),
    ],
)
def test_display_limits_are_bounded(field, value, expected_match):
    with pytest.raises(ValidationError, match=expected_match):
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
    with pytest.raises(ValidationError, match="less than or equal to 180"):
        WebMapFeature.model_validate(feature)
    feature["geometry"]["coordinates"][0] = [-75, 40]
    feature["properties"].pop("call_id")
    with pytest.raises(
        ValidationError, match="recorded course requires call identity and line geometry"
    ):
        WebMapFeature.model_validate(feature)


def test_gap_requires_deed_identity_and_must_not_impersonate_recorded_call():
    base_gap = {
        "type": "Feature",
        "id": "gap",
        "geometry": {"type": "LineString", "coordinates": [[0, 0], [0.001, 0]]},
        "properties": {"kind": "closure_gap", "call_id": "invented"},
    }
    with pytest.raises(
        ValidationError, match="deed display requires canonical geometry and placement identity"
    ):
        WebMapFeature.model_validate(base_gap)
    base_gap["properties"].update(
        calculation_id="calc",
        geometry_hash="a" * 64,
        placement_id="placed",
        placement_hash="b" * 64,
        placement_status="approximate",
    )
    with pytest.raises(ValidationError, match="must not impersonate recorded calls"):
        WebMapFeature.model_validate(base_gap)


def test_view_has_closed_style_list_and_opacity_range():
    assert MapboxViewOptions(style="standard-satellite").provider == "mapbox"
    for fields, expected_match in (
        (
            {"style": "https://untrusted/style"},
            "Input should be 'standard' or 'standard-satellite'",
        ),
        ({"raster_opacity": 2}, "less than or equal to 1"),
    ):
        with pytest.raises(ValidationError, match=expected_match):
            MapboxViewOptions(**fields)


def test_webmap_polygons_features_and_artifact_consistency_invariants():
    from mp_models.webmap import (
        WebMapArtifact,
        WebMapLine,
        WebMapMultiPolygon,
        WebMapPoint,
        WebMapPolygon,
        WebMapProjectionRecord,
        WebMapProperties,
    )

    ring = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 0.0))
    assert WebMapPolygon(coordinates=(ring,)).type == "Polygon"
    assert WebMapMultiPolygon(coordinates=((ring,),)).type == "MultiPolygon"

    # Empty polygon or unclosed/short ring rejected.
    with pytest.raises(ValidationError, match="exterior ring"):
        WebMapMultiPolygon(coordinates=((),))
    with pytest.raises(ValidationError, match="must be closed"):
        WebMapPolygon(coordinates=(((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.5, 0.5)),))

    # Parcel context feature requires source_id, layer_id, and Polygon/MultiPolygon geometry.
    ctx_feat = WebMapFeature(
        id="ctx",
        geometry=WebMapPolygon(coordinates=(ring,)),
        properties=WebMapProperties(kind="parcel_context", source_id="s1", layer_id="l1"),
    )
    assert ctx_feat.properties.kind == "parcel_context"
    with pytest.raises(ValidationError, match="parcel context requires source/layer"):
        WebMapFeature(
            id="ctx-bad",
            geometry=WebMapPoint(coordinates=(0.0, 0.0)),
            properties=WebMapProperties(kind="parcel_context", source_id="s1", layer_id="l1"),
        )

    # Marker features reject call_id and mismatched geometry types.
    deed_ids = {
        "calculation_id": "c",
        "geometry_hash": "a" * 64,
        "placement_id": "pl",
        "placement_hash": "b" * 64,
        "placement_status": "approximate",
    }
    with pytest.raises(ValidationError, match="must not impersonate recorded calls"):
        WebMapFeature(
            id="p-bad",
            geometry=WebMapPoint(coordinates=(0.0, 0.0)),
            properties=WebMapProperties(kind="pob", call_id="c1", **deed_ids),
        )
    with pytest.raises(ValidationError, match="closure gap requires line geometry"):
        WebMapFeature(
            id="g-pt",
            geometry=WebMapPoint(coordinates=(0.0, 0.0)),
            properties=WebMapProperties(kind="closure_gap", **deed_ids),
        )
    with pytest.raises(ValidationError, match="POB requires point geometry"):
        WebMapFeature(
            id="p-line",
            geometry=WebMapLine(coordinates=((0.0, 0.0), (1.0, 0.0))),
            properties=WebMapProperties(kind="pob", **deed_ids),
        )

    # WebMapArtifact consistency guards.
    proj = WebMapProjectionRecord(source_crs_wkt="EPSG:3857", pipeline="+proj=noop")
    base_art = {
        "scene_id": "s1",
        "input_hashes": (("h1", "a" * 64),),
        "options": WebMapOptions(),
        "options_sha256": "b" * 64,
    }
    with pytest.raises(ValidationError, match="availability does not match"):
        WebMapArtifact(**base_art, availability="ready")
    with pytest.raises(ValidationError, match="requires projection provenance and bounds"):
        WebMapArtifact(**base_art, features=(ctx_feat,), availability="ready")
    with pytest.raises(ValidationError, match="cannot invent bounds"):
        WebMapArtifact(**base_art, availability="unavailable", bounds=(0.0, 0.0, 1.0, 1.0))
    with pytest.raises(ValidationError, match="ordered and must not span antimeridian"):
        WebMapArtifact(
            **base_art,
            projection=proj,
            features=(ctx_feat,),
            availability="ready",
            bounds=(1.0, 0.0, 0.0, 1.0),
        )
    with pytest.raises(ValidationError, match="display IDs must be unique"):
        WebMapArtifact(
            **base_art,
            projection=proj,
            features=(ctx_feat, ctx_feat),
            availability="ready",
            bounds=(0.0, 0.0, 1.0, 1.0),
        )
    with pytest.raises(ValidationError, match="input hash names must be unique"):
        WebMapArtifact(
            **(base_art | {"input_hashes": (("h1", "a" * 64), ("h1", "b" * 64))}),
            availability="unavailable",
        )
