"""Offline GIS import regressions with independently known controls."""

import json

import pytest
from mp_review.overlays import import_overlay


def geo(coords=None):
    return json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": "parcel-7",
                    "properties": {},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": coords or [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
                    },
                }
            ],
        }
    ).encode()


def test_geojson_fixed_lonlat_and_xy_control():
    result = import_overlay(geo(), input_format="geojson", target_crs="EPSG:3857")
    assert result.layers[0].coordinates[0][1] == pytest.approx((111319.49079327357, 0), abs=1e-6)
    assert result.layers[0].coordinates[0][2][1] == pytest.approx(111325.1428663851, abs=1e-6)
    assert result.source.feature_ids == ("parcel-7",)
    assert result.original_bytes == geo()
    assert result.scene.units == "m"
    assert result.operation["network_enabled"] is False
    with pytest.raises(ValueError, match="fixed"):
        import_overlay(
            geo(), input_format="geojson", target_crs="EPSG:3857", source_crs="EPSG:2260"
        )


@pytest.mark.parametrize(
    "unit,crs,expected",
    [
        ("international_ft", "+proj=merc +datum=WGS84 +units=ft +type=crs", 30.48),
        ("us_survey_ft", "+proj=merc +datum=WGS84 +units=us-ft +type=crs", 100 * 1200 / 3937),
    ],
)
def test_explicit_foot_definitions(unit, crs, expected):
    data = json.dumps(
        {
            "source_crs": crs,
            "units": unit,
            "axis_order": "xy",
            "features": [
                {
                    "id": "feet",
                    "geometry_type": "Polygon",
                    "coordinates": [[[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]]],
                }
            ],
        }
    ).encode()
    result = import_overlay(
        data,
        input_format="projected-layer",
        target_crs="+proj=merc +datum=WGS84 +units=m +type=crs",
    )
    assert result.layers[0].coordinates[0][1][0] == pytest.approx(expected, abs=1e-8)


@pytest.mark.parametrize(
    ("changes", "expected_error"),
    [
        ({"source_crs": None}, "Projected-layer source CRS is required"),
        (
            {"units": "unknown_ft"},
            "Projected layer requires explicit XY axes and unambiguous units",
        ),
        (
            {"axis_order": "yx"},
            "Projected layer requires explicit XY axes and unambiguous units",
        ),
        ({"basis": "ground"}, "Ground coordinates require a documented ground/grid conversion"),
    ],
)
def test_projected_metadata_fails_closed(changes, expected_error):
    value = {"source_crs": "EPSG:3857", "units": "m", "axis_order": "xy", "features": []} | changes
    with pytest.raises(ValueError, match=expected_error):
        import_overlay(
            json.dumps(value).encode(), input_format="projected-layer", target_crs="EPSG:3857"
        )


def test_invalid_geojson_and_missing_extra(monkeypatch):
    import mp_review.overlays as module

    for coords, expected_error in (
        ([[[0, 0], [1, 1], [0, 1], [1, 0], [0, 0]]], "degenerate ring has zero area"),
        (
            [[[500, 0], [501, 0], [501, 1], [500, 0]]],
            "RFC 7946 longitude/latitude outside supported range",
        ),
    ):
        with pytest.raises(ValueError, match=expected_error):
            import_overlay(geo(coords), input_format="geojson", target_crs="EPSG:3857")
    monkeypatch.setattr(
        module, "_projection", lambda: (_ for _ in ()).throw(ValueError("Install mp-review[geo]"))
    )
    with pytest.raises(ValueError, match="geo"):
        import_overlay(geo(), input_format="geojson", target_crs="EPSG:3857")


def test_holes_multipolygons_ids_round_trip_and_supported_geometry():
    from mp_review.overlays import import_overlay

    hole = [
        [[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]],
        [[0.002, 0.002], [0.004, 0.002], [0.004, 0.004], [0.002, 0.004], [0.002, 0.002]],
    ]
    value = json.loads(geo(hole))
    value["features"][0]["geometry"] = {
        "type": "MultiPolygon",
        "coordinates": [hole, [[[0.02, 0], [0.03, 0], [0.03, 0.01], [0.02, 0.01], [0.02, 0]]]],
    }
    result = import_overlay(
        json.dumps(value).encode(), input_format="geojson", target_crs="EPSG:3857"
    )
    assert len(result.layers[0].coordinates) == 2
    assert len(result.layers[0].coordinates[0]) == 2
    # Reverse projection independently verifies both axis directions within 1e-9 degrees.
    import pyproj

    transformer = pyproj.Transformer.from_crs(3857, 4326, always_xy=True)
    assert transformer.transform(*result.layers[0].coordinates[0][1][0]) == pytest.approx(
        (0.002, 0.002), abs=1e-9
    )
    value["features"][0]["geometry"]["type"] = "LineString"
    with pytest.raises(ValueError, match="Polygon"):
        import_overlay(json.dumps(value).encode(), input_format="geojson", target_crs="EPSG:3857")
    with pytest.raises(ValueError, match="projected"):
        import_overlay(geo(), input_format="geojson", target_crs="EPSG:4326")


def test_missing_grids_and_nonfinite_operations_fail_closed(monkeypatch):
    import mp_review.overlays as module

    pyproj, _ = module._projection()

    class Group:
        best_available = False
        transformers = []

    monkeypatch.setattr(module, "_projection", lambda: (pyproj, lambda *a, **k: Group()))
    with pytest.raises(ValueError, match="grids"):
        import_overlay(geo(), input_format="geojson", target_crs="EPSG:3857")

    class BadTransformer:
        def transform(self, *_, **__):
            return float("inf"), float("nan")

    Group.best_available = True
    Group.transformers = [BadTransformer()]
    with pytest.raises(ValueError, match="nonfinite"):
        import_overlay(geo(), input_format="geojson", target_crs="EPSG:3857")


def test_overlay_input_size_json_format_coordinate_and_crs_guardrails(monkeypatch):
    import sys

    import mp_review.overlays as module

    # Size limit (verify default constant, then monkeypatch to avoid 20 MiB test allocation)
    assert module.MAX_IMPORT_BYTES == 20 * 1024 * 1024
    monkeypatch.setattr(module, "MAX_IMPORT_BYTES", 1024)
    with pytest.raises(ValueError, match="20 MiB"):
        import_overlay(
            b"x" * (module.MAX_IMPORT_BYTES + 1), input_format="geojson", target_crs="EPSG:3857"
        )
    monkeypatch.undo()

    # Malformed JSON & non-object JSON
    with pytest.raises(ValueError, match="JSON"):
        import_overlay(b"{not-json", input_format="geojson", target_crs="EPSG:3857")
    with pytest.raises(ValueError, match="object"):
        import_overlay(b"[]", input_format="geojson", target_crs="EPSG:3857")

    # Unsupported GeoJSON type & unsupported input_format & empty features
    with pytest.raises(ValueError, match="Feature or FeatureCollection"):
        import_overlay(
            b'{"type":"Point","coordinates":[0,0]}', input_format="geojson", target_crs="EPSG:3857"
        )
    with pytest.raises(ValueError, match="Supported formats"):
        import_overlay(b"{}", input_format="shapefile", target_crs="EPSG:3857")
    with pytest.raises(ValueError, match="at least one feature"):
        import_overlay(
            b'{"type":"FeatureCollection","features":[]}',
            input_format="geojson",
            target_crs="EPSG:3857",
        )

    # Non-object feature & duplicate feature IDs
    with pytest.raises(ValueError, match="Feature must be an object"):
        import_overlay(
            b'{"type":"FeatureCollection","features":[123]}',
            input_format="geojson",
            target_crs="EPSG:3857",
        )
    dup = json.loads(geo())
    dup["features"].append(dict(dup["features"][0]))
    with pytest.raises(ValueError, match="Duplicate feature IDs"):
        import_overlay(json.dumps(dup).encode(), input_format="geojson", target_crs="EPSG:3857")

    # Empty coordinates, non-XY / bool positions, antimeridian crossing ring
    empty_coords = json.loads(geo())
    empty_coords["features"][0]["geometry"]["coordinates"] = []
    with pytest.raises(ValueError, match="Empty or invalid"):
        import_overlay(
            json.dumps(empty_coords).encode(), input_format="geojson", target_crs="EPSG:3857"
        )
    for bad_coords in (
        [[[0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 0, 1]]],
        [[[True, 0], [1, 0], [1, 1], [True, 0]]],
    ):
        with pytest.raises(ValueError, match="finite XY"):
            import_overlay(geo(bad_coords), input_format="geojson", target_crs="EPSG:3857")
    antimeridian = [[[175, 0], [-175, 0], [-175, 1], [175, 1], [175, 0]]]
    with pytest.raises(ValueError, match="Antimeridian"):
        import_overlay(geo(antimeridian), input_format="geojson", target_crs="EPSG:3857")

    # Projected-layer conflicting source_crs override & conflicting declared units vs CRS
    proj_payload = {
        "source_crs": "EPSG:3857",
        "units": "m",
        "axis_order": "xy",
        "features": [
            {
                "id": "p1",
                "geometry_type": "Polygon",
                "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
            }
        ],
    }
    with pytest.raises(ValueError, match="Conflicting source CRS"):
        import_overlay(
            json.dumps(proj_payload).encode(),
            input_format="projected-layer",
            target_crs="EPSG:3857",
            source_crs="EPSG:2260",
        )
    wrong_units = {**proj_payload, "units": "international_ft"}
    with pytest.raises(ValueError, match="Declared units conflict"):
        import_overlay(
            json.dumps(wrong_units).encode(),
            input_format="projected-layer",
            target_crs="EPSG:3857",
        )

    # Transformer raising an error during coordinate transformation
    pyproj, _ = module._projection()

    class ExplodingTransformer:
        def transform(self, *_, **__):
            raise RuntimeError("proj failure")

    class GoodGroup:
        best_available = True
        transformers = [ExplodingTransformer()]

    monkeypatch.setattr(module, "_projection", lambda: (pyproj, lambda *a, **k: GoodGroup()))
    with pytest.raises(ValueError, match="CRS transformation failed"):
        import_overlay(geo(), input_format="geojson", target_crs="EPSG:3857")

    # Missing pyproj inside real _projection()
    monkeypatch.undo()
    monkeypatch.setitem(sys.modules, "pyproj", None)
    with pytest.raises(ValueError, match="mp-review\\[geo\\]"):
        module._projection()
