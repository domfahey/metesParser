"""Independent geographic display controls; no provider or survey-status promotion."""

import json
import math
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from mp_models.dashboard import DashboardBundle, PreparedDashboard
from mp_models.webmap import WebMapOptions
from mp_review.dashboard import prepare_dashboard
from mp_review.webmap import prepare_web_map
from mp_review.webmap_projection import WebMapProjection, WebMapUnavailable
from mp_verify.dashboard import _hash

R = 6378137.0
FIXTURE = Path(__file__).parent / "fixtures/dashboard-absolute.json"


def mapped(
    *, units="m", native="international_ft", rotation=0, translation=(1000, 2000), edit=None
):
    data = json.loads(FIXTURE.read_text())
    data["schema_version"] = "1.1"
    data["calculations"][0]["frame"]["foot_definition"] = native
    data["scenarios"] = []
    if edit:
        edit(data)
    initial = prepare_dashboard(DashboardBundle.model_validate(data))
    proj_unit = {"m": "m", "international_ft": "ft", "us_survey_ft": "us-ft"}[units]
    # Spherical Mercator makes independent expected values elementary.
    data["scenes"] = [
        {
            "id": "grid",
            "name": "Synthetic",
            "kind": "projected",
            "units": units,
            "crs": f"+proj=webmerc +datum=WGS84 +units={proj_unit} +type=crs",
        }
    ]
    data["placements"] = [
        {
            "id": "placement",
            "calculation_id": "calc-one",
            "geometry_hash": initial.plots.geometries[0].geometry_hash,
            "scene_id": "grid",
            "rotation_deg": rotation,
            "translation": translation,
            "status": "approximate",
            "rationale": "Synthetic independent control",
        }
    ]
    return prepare_dashboard(DashboardBundle.model_validate(data))


def geographic(x, y):
    return math.degrees(x / R), math.degrees(2 * math.atan(math.exp(y / R)) - math.pi / 2)


def output(prepared, **kwargs):
    return prepare_web_map(prepared, scene_id="grid", options=WebMapOptions(**kwargs))


@pytest.mark.parametrize(
    "units,factor", [("m", 1), ("international_ft", 0.3048), ("us_survey_ft", 1200 / 3937)]
)
@pytest.mark.parametrize(
    "native,foot", [("international_ft", 0.3048), ("us_survey_ft", 1200 / 3937)]
)
def test_independent_units_rotation_axis_and_baseline(units, factor, native, foot):
    prepared = mapped(units=units, native=native, rotation=90)
    before = prepared.model_dump(mode="json")
    result = output(prepared)
    first = next(f for f in result.artifact.features if f.properties.call_id == "call-one")
    assert first.geometry.coordinates[0] == pytest.approx(
        geographic(1000 * factor, 2000 * factor), abs=1e-11
    )
    assert first.geometry.coordinates[-1] == pytest.approx(
        geographic(1000 * factor + 100 * foot, 2000 * factor), abs=1e-11
    )
    assert first.properties.page_id == "page-one"
    assert first.properties.placement_status == "approximate"
    assert result.artifact.options_sha256 == _hash(WebMapOptions().model_dump(mode="json"))
    assert prepared.model_dump(mode="json") == before
    assert output(prepared) == result
    cached = prepared.model_copy(
        update={"manifest": prepared.manifest.model_copy(update={"cache_reused": True})}
    )
    assert output(cached) == result
    with pytest.raises(FrozenInstanceError):
        result.assets = ()


def test_rotated_triangle_controls_are_independent():
    def triangle(data):
        data["calls"] = data["calls"][:3]
        for record, angle, distance in zip(data["calls"], (90, 0, 225), (30, 40, 50), strict=True):
            record["call"].update(bearing_azimuth_deg_from_north=angle, distance_ft=distance)

    result = output(mapped(rotation=30, edit=triangle))
    first = next(f for f in result.artifact.features if f.properties.call_id == "call-one")
    assert first.geometry.coordinates[-1] == pytest.approx(
        geographic(1000 + 30 * 0.3048 * math.cos(math.pi / 6), 2000 - 30 * 0.3048 * 0.5), abs=1e-11
    )


def test_partial_prefix_has_no_bridge_or_closure_gap():
    def missing(data):
        data["calls"][1]["call"]["bearing_azimuth_deg_from_north"] = None

    result = output(mapped(edit=missing))
    courses = [f for f in result.artifact.features if f.properties.kind == "recorded_course"]
    assert [f.properties.call_id for f in courses] == ["call-one"]
    assert not any(f.properties.kind == "closure_gap" for f in result.artifact.features)
    assert courses[0].properties.completeness == "partial"
    assert result.artifact.availability == "partial"


def test_real_recorded_closing_call_and_separate_gap():
    closed = output(mapped())
    assert len([f for f in closed.artifact.features if f.properties.kind == "recorded_course"]) == 4
    assert not any(f.properties.kind == "closure_gap" for f in closed.artifact.features)

    def open_end(data):
        data["calls"][3]["call"]["distance_ft"] = 49

    opened = output(mapped(edit=open_end))
    gap = next(f for f in opened.artifact.features if f.properties.kind == "closure_gap")
    assert gap.properties.call_id is None
    assert len([f for f in opened.artifact.features if f.properties.kind == "recorded_course"]) == 4


@pytest.mark.parametrize("sweep", [90, 270])
def test_arc_analytic_bulge_endpoints_and_withheld_error(sweep):
    def arc(data):
        data["calls"] = data["calls"][:1]
        data["calls"][0]["call"].update(
            curve_dir="right",
            radius_ft=100,
            delta_deg=sweep,
            arc_length_ft=100 * math.radians(sweep),
        )

    result = output(mapped(edit=arc), tolerance_m=0.01)
    feature = next(f for f in result.artifact.features if f.properties.kind == "recorded_course")
    coords = [
        (R * math.radians(lon), R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))
        for lon, lat in feature.geometry.coordinates
    ]
    assert len(coords) > 8
    assert coords[0] == pytest.approx((1000, 2000), abs=1e-7)
    assert coords[-1] == pytest.approx(
        (
            1000 + 100 * 0.3048 * (1 - math.cos(math.radians(sweep))),
            2000 + 100 * 0.3048 * math.sin(math.radians(sweep)),
        ),
        abs=1e-7,
    )
    for i in range(1, 100):
        angle = math.radians(sweep * i / 100)
        point = (1000 + 30.48 * (1 - math.cos(angle)), 2000 + 30.48 * math.sin(angle))
        assert (
            min(segment_distance(point, a, b) for a, b in zip(coords, coords[1:], strict=False))
            <= 0.010001
        )


def segment_distance(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = (
        max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
        if dx or dy
        else 0
    )
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def fake_projection(forward):
    return WebMapProjection(
        source_crs_wkt="synthetic",
        pipeline="synthetic",
        accuracy=None,
        versions=(),
        _forward=lambda x, y: forward(x, y),
        _geographic=lambda x, y: geographic(x, y),
    )


def test_nonlinear_line_and_quarter_samples(monkeypatch):
    # Midpoint lies on the chord; quarter points expose this bend.
    projection = fake_projection(
        lambda x, y: (x + 2 * math.sin(2 * math.pi * (y - 2000) / 30.48), y)
    )
    monkeypatch.setattr("mp_review.webmap.build_web_map_projection", lambda _: projection)
    result = output(mapped(), tolerance_m=0.01)
    first = next(f for f in result.artifact.features if f.properties.call_id == "call-one")
    coords = [
        (R * math.radians(lon), R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))
        for lon, lat in first.geometry.coordinates
    ]
    assert len(coords) > 2
    for i in range(1, 100):
        y = 2000 + 30.48 * i / 100
        p = projection.to_mercator((1000, y))
        assert (
            min(segment_distance(p, a, b) for a, b in zip(coords, coords[1:], strict=False))
            <= 0.010001
        )


@pytest.mark.parametrize("settings", [{"max_vertices": 2}, {"max_depth": 1, "tolerance_m": 1e-8}])
def test_limit_failure_omits_entire_calculation(monkeypatch, settings):
    projection = fake_projection(lambda x, y: (x + (y - 2000) ** 2, y))
    monkeypatch.setattr("mp_review.webmap.build_web_map_projection", lambda _: projection)
    result = output(mapped(), **settings)
    assert not result.artifact.features
    assert result.artifact.availability == "unavailable"
    assert result.artifact.unavailable[0].code in {"vertex_limit", "sampling_limit"}


def test_polygon_holes_multipolygon_and_source_identity():
    prepared = mapped()
    data = prepared.bundle.model_dump(mode="json")
    data["map_sources"] = [{"id": "source", "label": "Synthetic", "sha256": "0" * 64}]
    exterior = [[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]]
    hole = [[20, 20], [20, 40], [40, 40], [40, 20], [20, 20]]
    other = [[200, 0], [210, 0], [210, 10], [200, 10], [200, 0]]
    data["vector_layers"] = [
        {
            "id": "parcels",
            "label": "Parcel context",
            "source_id": "source",
            "scene_id": "grid",
            "geometry_type": "MultiPolygon",
            "coordinates": [[exterior, hole], [other]],
        }
    ]
    result = output(prepare_dashboard(DashboardBundle.model_validate(data)))
    feature = next(f for f in result.artifact.features if f.properties.kind == "parcel_context")
    assert feature.properties.source_id == "source"
    assert feature.properties.layer_id == "parcels"
    assert [len(p) for p in feature.geometry.coordinates] == [2, 1]
    assert feature.geometry.coordinates[0][1][0] == pytest.approx(geographic(20, 20), abs=1e-11)


@pytest.mark.parametrize("mode", ["geometry", "manifest"])
def test_direct_tampered_prepared_input_is_error(mode):
    prepared = mapped()
    value = prepared.model_dump(mode="json")
    if mode == "geometry":
        value["plots"]["geometries"][0]["primitives"][0]["end"] = [10, 20]
    else:
        value["manifest"]["map_output_hash"] = "0" * 64
    with pytest.raises(ValueError, match="deterministic"):
        output(PreparedDashboard.model_validate(value))


def test_missing_placement_and_local_reference_are_explicit():
    prepared = mapped()
    data = prepared.bundle.model_dump(mode="json")
    data["placements"] = []
    assert (
        output(prepare_dashboard(DashboardBundle.model_validate(data))).artifact.unavailable[0].code
        == "missing_placement"
    )
    data["scenes"] = [{"id": "grid", "name": "Local", "kind": "local", "units": "unknown_ft"}]
    assert (
        output(prepare_dashboard(DashboardBundle.model_validate(data))).artifact.unavailable[0].code
        == "missing_georeference"
    )


@pytest.mark.parametrize("translation", [(math.pi * R + 100, 0), (0, math.pi * R + 100)])
def test_domain_failure_omits_whole_calculation(translation):
    result = output(mapped(translation=translation))
    assert not result.artifact.features
    assert result.artifact.unavailable[0].code == "projection_domain"


def test_dateline_jump_is_explicit(monkeypatch):
    projection = fake_projection(
        lambda x, y: ((179.999 if y < 2015 else -179.999) * math.pi * R / 180, y)
    )
    monkeypatch.setattr("mp_review.webmap.build_web_map_projection", lambda _: projection)
    result = output(mapped())
    assert not result.artifact.features
    assert result.artifact.unavailable[0].code == "antimeridian"


def test_missing_required_grid_is_explicit(monkeypatch):
    def unavailable(_):
        raise WebMapUnavailable("missing_grid", "Required grids unavailable.")

    monkeypatch.setattr("mp_review.webmap.build_web_map_projection", unavailable)
    result = output(mapped())
    assert result.artifact.unavailable[0].code == "missing_grid"
    assert not result.artifact.features


def test_real_nonlinear_projection_subdivides_straight_diagonal():
    def long_diagonal(data):
        data["calls"] = data["calls"][:1]
        data["calls"][0]["call"].update(distance_ft=500000, bearing_azimuth_deg_from_north=45)

    prepared = mapped(edit=long_diagonal, translation=(0, R * math.radians(40)))
    data = prepared.bundle.model_dump(mode="json")
    data["scenes"][0]["crs"] = "+proj=eqc +R=6378137 +nadgrids=@null +units=m +type=crs"
    prepared = prepare_dashboard(DashboardBundle.model_validate(data))
    result = output(prepared, tolerance_m=0.05)
    first = next(f for f in result.artifact.features if f.properties.call_id == "call-one")
    assert len(first.geometry.coordinates) > 2
    coords = [
        (R * math.radians(lon), R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))
        for lon, lat in first.geometry.coordinates
    ]
    displacement = 500000 * 0.3048 / math.sqrt(2)
    for i in range(1, 100):
        x = displacement * i / 100
        # Equirectangular is x=R*lambda, y=R*phi; independent Mercator y below.
        latitude = math.radians(40) + x / R
        expected = (x, R * math.log(math.tan(math.pi / 4 + latitude / 2)))
        assert (
            min(segment_distance(expected, a, b) for a, b in zip(coords, coords[1:], strict=False))
            <= 0.050001
        )


def test_polygon_display_vertex_budget_is_aggregate():
    prepared = mapped()
    data = prepared.bundle.model_dump(mode="json")
    data["placements"] = []
    data["map_sources"] = [{"id": "source", "label": "Synthetic", "sha256": "0" * 64}]
    data["vector_layers"] = [
        {
            "id": name,
            "label": name,
            "source_id": "source",
            "scene_id": "grid",
            "geometry_type": "Polygon",
            "coordinates": [[[x, 0], [x + 10, 0], [x + 10, 10], [x, 10], [x, 0]]],
        }
        for name, x in [("first", 0), ("second", 20)]
    ]
    result = output(prepare_dashboard(DashboardBundle.model_validate(data)), max_vertices=9)
    assert [f.properties.layer_id for f in result.artifact.features] == ["first"]
    assert any(
        u.item_id == "second" and u.code == "vertex_limit" for u in result.artifact.unavailable
    )


def raster_prepared(*, local=False):
    from io import BytesIO

    from mp_models.plot import PlotScene
    from mp_review.raster_registration import image_layer, supplied_affine
    from PIL import Image

    prepared = mapped()
    data = prepared.bundle.model_dump(mode="json")
    if local:
        data["placements"] = []
        data["scenes"] = [{"id": "grid", "name": "Local", "kind": "local", "units": "m"}]
    scene = PlotScene.model_validate(data["scenes"][0])
    stream = BytesIO()
    Image.new("RGBA", (2, 2), (255, 255, 255, 255)).save(stream, format="PNG")
    layer, source = image_layer(
        stream.getvalue(),
        scene=scene,
        registration=supplied_affine((1, 0, 1000, 0, -1, 2000)),
        filename="synthetic.png",
    )
    # Same source bytes, independently named registrations in one scene.
    first = layer.model_copy(update={"id": "scan-one"})
    second = layer.model_copy(update={"id": "scan-two"})
    data["map_sources"] = [source.model_dump(mode="json")]
    data["raster_layers"] = [first.model_dump(mode="json"), second.model_dump(mode="json")]
    return prepare_dashboard(DashboardBundle.model_validate(data))


def test_tampered_raster_cannot_hide_behind_missing_georeference():
    prepared = raster_prepared(local=True)
    data = prepared.model_dump(mode="json")
    import base64
    import hashlib

    damaged = base64.b64decode(data["bundle"]["raster_layers"][0]["data_base64"])[:24]
    digest = hashlib.sha256(damaged).hexdigest()
    for layer in data["bundle"]["raster_layers"]:
        layer.update(data_base64=base64.b64encode(damaged).decode(), sha256=digest)
    data["bundle"]["map_sources"][0].update(
        sha256=digest, data_base64=base64.b64encode(damaged).decode()
    )
    # Header and canonical hashes agree, but complete image decoding must fail.
    from mp_verify.dashboard import calculate_dashboard

    forged = calculate_dashboard(DashboardBundle.model_validate(data["bundle"]))
    with pytest.raises((ValueError, OSError)):
        output(forged)


def test_raster_budget_is_shared_and_originals_unchanged(monkeypatch):
    from types import SimpleNamespace

    from mp_models.webmap import WebMapRaster

    prepared = raster_prepared()
    before = prepared.model_dump(mode="json")
    calls = []

    def helper(layer, scene, *, projection, options):
        calls.append(options.max_raster_pixels)
        if options.max_raster_pixels < 4:
            raise WebMapUnavailable("raster_pixel_limit", "Raster pixel limit exceeded.")
        record = WebMapRaster(
            id=layer.id,
            source_id=layer.source_id,
            source_sha256=layer.sha256,
            registration_sha256="0" * 64,
            projection_sha256="1" * 64,
            path=f"web-map-assets/{layer.id}.png",
            sha256="2" * 64,
            width=2,
            height=2,
            pixel_size_m=1,
            grid_affine=(1, 0, 1000, 0, -1, 2000),
            corners=tuple(
                geographic(x, y)
                for x, y in [(1000, 2000), (1002, 2000), (1002, 1998), (1000, 1998)]
            ),
            residual_units="m",
        )
        return SimpleNamespace(record=record, data=b"synthetic-helper-result")

    monkeypatch.setattr("mp_review.webmap_raster.prepare_web_map_raster", helper)
    result = output(prepared, max_raster_pixels=6)
    assert calls == [6, 2]
    assert len(result.artifact.rasters) == 1
    assert result.assets == (("web-map-assets/scan-one.png", b"synthetic-helper-result"),)
    assert prepared.model_dump(mode="json") == before


def test_real_raster_helper_assets_integrate_with_canonical_vectors():
    import hashlib

    prepared = raster_prepared()
    before = prepared.model_dump(mode="json")
    result = output(prepared, raster_pixel_size_m=1)
    assert len(result.artifact.rasters) == 2
    assert len(result.assets) == 2
    assert result.artifact.availability == "ready"
    by_path = dict(result.assets)
    for raster in result.artifact.rasters:
        assert by_path[raster.path].startswith(b"\x89PNG\r\n\x1a\n")
        assert hashlib.sha256(by_path[raster.path]).hexdigest() == raster.sha256
        assert raster.projection_sha256 == _hash(result.artifact.projection.model_dump(mode="json"))
    assert prepared.model_dump(mode="json") == before


def test_delimited_source_identifiers_cannot_collide_in_feature_ids():
    def names(data):
        data["calls"][0]["id"] = "x:y"
        data["calls"][1]["id"] = "y"
        data["evidence"][0]["call_id"] = "x:y"

    prepared = mapped(edit=names)
    data = prepared.bundle.model_dump(mode="json")
    data["placements"][0]["id"] = "a"
    data["placements"].append(dict(data["placements"][0], id="a:x"))
    result = output(prepare_dashboard(DashboardBundle.model_validate(data)))
    assert len({f.id for f in result.artifact.features}) == len(result.artifact.features)
