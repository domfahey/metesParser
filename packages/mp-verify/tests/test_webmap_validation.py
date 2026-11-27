"""Shared web-map binding checks require no geographic or rendering libraries."""

import hashlib
import json
from pathlib import Path

import pytest
from mp_models.dashboard import DashboardBundle
from mp_models.webmap import WebMapArtifact, WebMapOptions
from mp_verify.dashboard import calculate_dashboard
from mp_verify.webmap import validate_web_map_artifact


def inputs():
    root = Path(__file__).resolve().parents[3]
    data = json.loads(
        (root / "packages/mp-review/tests/fixtures/dashboard-absolute.json").read_text()
    )
    data["schema_version"] = "1.1"
    data["scenes"] = [
        {"id": "scene", "name": "Synthetic", "kind": "projected", "crs": "EPSG:3857", "units": "m"}
    ]
    prepared = calculate_dashboard(DashboardBundle.model_validate(data))
    options = WebMapOptions()
    artifact = WebMapArtifact(
        scene_id="scene",
        input_hashes=tuple(
            (key, value)
            for key, value in prepared.manifest.model_dump().items()
            if key.endswith("_hash") and value is not None
        ),
        options=options,
        options_sha256=hashlib.sha256(
            json.dumps(
                options.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest(),
        availability="unavailable",
    )
    return prepared, artifact


def test_direct_validator_returns_revalidated_artifact():
    prepared, artifact = inputs()
    validated = validate_web_map_artifact(prepared, artifact)
    assert validated == artifact
    assert validated is not artifact


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("input_hashes", (), "input hashes"),
        ("options_sha256", "0" * 64, "options hash"),
        ("scene_id", "absent", "scene"),
    ],
)
def test_direct_validator_rejects_forged_bindings(field, value, message):
    prepared, artifact = inputs()
    with pytest.raises(ValueError, match=message):
        validate_web_map_artifact(prepared, artifact.model_copy(update={field: value}))


def test_direct_validator_recalculates_prepared_results():
    prepared, artifact = inputs()
    forged = prepared.model_copy(update={"calculations": ()})
    with pytest.raises(ValueError, match="deterministic inputs"):
        validate_web_map_artifact(forged, artifact)


def _sha256_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def test_direct_validator_revalidates_prepared_model():
    prepared, artifact = inputs()
    forged = prepared.model_copy(
        update={"manifest": prepared.manifest.model_copy(update={"cache_reused": "invalid"})}
    )
    with (
        pytest.warns(UserWarning, match="serializer warnings"),
        pytest.raises(ValueError, match="valid boolean"),
    ):
        validate_web_map_artifact(forged, artifact)


def test_shared_context_preserves_dashboard_manifest_hashes():
    from mp_verify.webmap import normalize_web_map_context

    prepared, artifact = inputs()
    context = normalize_web_map_context(prepared)
    assert context.input_hashes == artifact.input_hashes
    assert context.geometries == prepared.plots.geometries


def test_standalone_validator_uses_no_dashboard_or_projection(monkeypatch):
    from mp_models.webmap import StandaloneWebMapInput
    from mp_verify import webmap

    def forbidden(*args, **kwargs):
        raise AssertionError("standalone validation must not use a dashboard")

    monkeypatch.setattr(webmap, "validate_prepared_dashboard", forbidden)
    prepared = StandaloneWebMapInput(
        title="Local overlay input",
        scenes=({"id": "local", "name": "Local", "kind": "local", "units": "unknown_ft"},),
    )
    context = webmap.normalize_web_map_context(prepared)
    options = WebMapOptions()
    artifact = WebMapArtifact(
        scene_id="local",
        options=options,
        options_sha256=_sha256_json(options.model_dump(mode="json")),
        input_hashes=context.input_hashes,
        availability="unavailable",
    )
    assert validate_web_map_artifact(prepared, artifact) == artifact


def test_feature_bound_to_unresolved_empty_geometry_is_rejected_as_stale():
    from mp_models.plot import PlotPlacement, PlotScene
    from mp_models.plot_request import PlotCall, PlotRequest
    from mp_models.webmap import (
        StandaloneWebMapInput,
        WebMapFeature,
        WebMapPoint,
        WebMapProjectionRecord,
        WebMapProperties,
    )
    from mp_verify.plot import prepare_plot
    from mp_verify.webmap import normalize_web_map_context

    empty_plot = prepare_plot(
        PlotRequest(
            title="Unresolved", calculation_id="calc-empty", calls=(PlotCall(id="c1", call=None),)
        )
    )
    scene = PlotScene(id="grid", name="Grid", kind="projected", crs="EPSG:3857", units="m")
    placement = PlotPlacement(
        id="pl-empty",
        calculation_id="calc-empty",
        geometry_hash=empty_plot.geometry.geometry_hash,
        scene_id="grid",
        status="approximate",
        rationale="manual",
    )
    standalone = StandaloneWebMapInput(
        title="Empty plot",
        plots=(empty_plot,),
        scenes=(scene,),
        placements=(placement,),
    )
    ctx = normalize_web_map_context(standalone)
    options = WebMapOptions()
    projection = WebMapProjectionRecord(source_crs_wkt="EPSG:3857", pipeline="+proj=noop")
    pob = WebMapFeature(
        id="f-pob",
        geometry=WebMapPoint(coordinates=(-75.0, 40.0)),
        properties=WebMapProperties(
            kind="pob",
            calculation_id="calc-empty",
            geometry_hash=empty_plot.geometry.geometry_hash,
            placement_id="pl-empty",
            placement_hash=_sha256_json(placement.model_dump(mode="json")),
            placement_status="approximate",
            completeness="unresolved",
        ),
    )
    artifact = WebMapArtifact(
        scene_id="grid",
        input_hashes=ctx.input_hashes,
        options=options,
        options_sha256=_sha256_json(options.model_dump(mode="json")),
        projection=projection,
        features=(pob,),
        availability="ready",
        bounds=(-75.0, 40.0, -75.0, 40.0),
    )
    with pytest.raises(ValueError, match="stale online marker binding"):
        validate_web_map_artifact(standalone, artifact)


def _rich_standalone_webmap():
    """Build a valid standalone input with deed courses (open for closure_gap), vector, and raster."""
    import base64

    from mp_models import DeedCall
    from mp_models.plot import MapSource, PlotPlacement, PlotScene, VectorLayer
    from mp_models.plot_request import PlotCall, PlotRequest
    from mp_models.raster import RasterLayer, RasterRegistration
    from mp_models.webmap import (
        StandaloneWebMapInput,
        WebMapFeature,
        WebMapLine,
        WebMapPoint,
        WebMapPolygon,
        WebMapProjectionRecord,
        WebMapProperties,
        WebMapRaster,
    )
    from mp_verify import webmap
    from mp_verify.plot import prepare_plot

    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    png_sha = hashlib.sha256(png).hexdigest()
    png_b64 = base64.b64encode(png).decode()

    plot = prepare_plot(
        PlotRequest(
            title="Open lot",
            calculation_id="calc-1",
            foot_definition="international_ft",
            calls=(
                PlotCall(
                    id="c1",
                    call=DeedCall(
                        course=1,
                        direction_text="North",
                        bearing_azimuth_deg_from_north=0.0,
                        distance_ft=100.0,
                    ),
                ),
                PlotCall(
                    id="c2",
                    call=DeedCall(
                        course=2,
                        direction_text="East",
                        bearing_azimuth_deg_from_north=90.0,
                        distance_ft=100.0,
                    ),
                ),
            ),
        )
    )
    scene = PlotScene(id="grid", name="Grid", kind="projected", crs="EPSG:3857", units="m")
    vec_source = MapSource(id="vsrc", label="Parcels", sha256="1" * 64)
    ras_source = MapSource(id="rsrc", label="Scan", sha256=png_sha, data_base64=png_b64)
    vector = VectorLayer(
        id="vlayer",
        label="Parcel",
        source_id="vsrc",
        scene_id="grid",
        geometry_type="Polygon",
        coordinates=(((0, 0), (10, 0), (10, 10), (0, 10), (0, 0)),),
    )
    reg = RasterRegistration(matrix=(1, 0, 0, 0, -1, 0), method="supplied_affine")
    raster = RasterLayer(
        id="rlayer",
        label="Scan",
        source_id="rsrc",
        scene_id="grid",
        mime_type="image/png",
        width=1,
        height=1,
        sha256=png_sha,
        data_base64=png_b64,
        registration=reg,
    )
    placement = PlotPlacement(
        id="pl-1",
        calculation_id="calc-1",
        geometry_hash=plot.geometry.geometry_hash,
        scene_id="grid",
        status="approximate",
        rationale="manual",
    )
    standalone = StandaloneWebMapInput(
        title="Full standalone",
        plots=(plot,),
        scenes=(scene,),
        map_sources=(vec_source, ras_source),
        vector_layers=(vector,),
        raster_layers=(raster,),
        placements=(placement,),
    )
    context = webmap.normalize_web_map_context(standalone)
    options = WebMapOptions()
    projection = WebMapProjectionRecord(source_crs_wkt="EPSG:3857", pipeline="+proj=noop")
    placement_hash = _sha256_json(placement.model_dump(mode="json"))
    projection_hash = _sha256_json(projection.model_dump(mode="json"))
    reg_hash = _sha256_json(reg.model_dump(mode="json"))
    deed_common = {
        "calculation_id": "calc-1",
        "geometry_hash": plot.geometry.geometry_hash,
        "placement_id": "pl-1",
        "placement_hash": placement_hash,
        "placement_status": "approximate",
        "completeness": "complete",
    }
    features = (
        WebMapFeature(
            id="f-c1",
            geometry=WebMapLine(coordinates=((-75.0, 40.0), (-75.0, 40.001))),
            properties=WebMapProperties(kind="recorded_course", call_id="c1", **deed_common),
        ),
        WebMapFeature(
            id="f-c2",
            geometry=WebMapLine(coordinates=((-75.0, 40.001), (-74.999, 40.001))),
            properties=WebMapProperties(kind="recorded_course", call_id="c2", **deed_common),
        ),
        WebMapFeature(
            id="f-pob",
            geometry=WebMapPoint(coordinates=(-75.0, 40.0)),
            properties=WebMapProperties(kind="pob", **deed_common),
        ),
        WebMapFeature(
            id="f-gap",
            geometry=WebMapLine(coordinates=((-74.999, 40.001), (-75.0, 40.0))),
            properties=WebMapProperties(kind="closure_gap", **deed_common),
        ),
        WebMapFeature(
            id="f-ctx",
            geometry=WebMapPolygon(
                coordinates=(
                    ((-75.002, 39.999), (-74.998, 39.999), (-74.998, 40.002), (-75.002, 39.999)),
                )
            ),
            properties=WebMapProperties(kind="parcel_context", source_id="vsrc", layer_id="vlayer"),
        ),
    )
    wm_raster = WebMapRaster(
        id="rlayer",
        source_id="rsrc",
        source_sha256=png_sha,
        registration_sha256=reg_hash,
        projection_sha256=projection_hash,
        path="web-map-assets/scan.png",
        sha256="2" * 64,
        width=1,
        height=1,
        pixel_size_m=0.25,
        grid_affine=(1, 0, 0, 0, -1, 0),
        corners=((-75.002, 40.002), (-74.998, 40.002), (-74.998, 39.999), (-75.002, 39.999)),
        residual_units="m",
    )
    artifact = WebMapArtifact(
        scene_id="grid",
        input_hashes=context.input_hashes,
        options=options,
        options_sha256=_sha256_json(options.model_dump(mode="json")),
        projection=projection,
        features=features,
        rasters=(wm_raster,),
        availability="ready",
        bounds=(-75.002, 39.999, -74.998, 40.002),
    )
    return standalone, artifact


def test_normalize_rejects_unknown_input_type_and_feature_vertices_covers_multipolygon():
    from mp_models.webmap import WebMapFeature, WebMapMultiPolygon, WebMapProperties
    from mp_verify.webmap import feature_vertices, normalize_web_map_context

    with pytest.raises(TypeError, match="prepared dashboard or standalone"):
        normalize_web_map_context("not-an-input")  # type: ignore[arg-type]

    mp = WebMapFeature(
        id="mp",
        geometry=WebMapMultiPolygon(
            coordinates=((((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 0.0)),),)
        ),
        properties=WebMapProperties(kind="parcel_context", source_id="s", layer_id="l"),
    )
    assert len(feature_vertices(mp)) == 4


def test_rich_standalone_artifact_validates_and_rejects_binding_or_coordinate_tampering():
    from mp_models.webmap import WebMapLine, WebMapPoint, WebMapUnavailableItem

    standalone, artifact = _rich_standalone_webmap()
    assert validate_web_map_artifact(standalone, artifact) == artifact

    # Broken chain between c1 and c2 fails coordinate continuity check.
    bad_chain = list(artifact.features)
    bad_chain[1] = bad_chain[1].model_copy(
        update={"geometry": WebMapLine(coordinates=((-75.0, 40.0015), (-74.999, 40.001)))}
    )
    with pytest.raises(ValueError, match="chained courses do not meet"):
        validate_web_map_artifact(
            standalone, artifact.model_copy(update={"features": tuple(bad_chain)})
        )

    # Misplaced POB fails POB coordinate check.
    bad_pob = list(artifact.features)
    bad_pob[2] = bad_pob[2].model_copy(
        update={"geometry": WebMapPoint(coordinates=(-75.0005, 40.0))}
    )
    with pytest.raises(ValueError, match="point of beginning"):
        validate_web_map_artifact(
            standalone, artifact.model_copy(update={"features": tuple(bad_pob)})
        )

    # Misplaced closure gap fails closure gap endpoint check.
    bad_gap = list(artifact.features)
    bad_gap[3] = bad_gap[3].model_copy(
        update={"geometry": WebMapLine(coordinates=((-74.999, 40.001), (-75.0005, 40.0)))}
    )
    with pytest.raises(ValueError, match="closure gap endpoints"):
        validate_web_map_artifact(
            standalone, artifact.model_copy(update={"features": tuple(bad_gap)})
        )

    # Missing closure gap fails completeness check.
    no_gap = tuple(f for f in artifact.features if f.id != "f-gap")
    with pytest.raises(ValueError, match="expected courses, point of beginning or closure gap"):
        validate_web_map_artifact(standalone, artifact.model_copy(update={"features": no_gap}))

    # Bounds mismatch rejected.
    with pytest.raises(ValueError, match="bounds do not match"):
        validate_web_map_artifact(
            standalone, artifact.model_copy(update={"bounds": (-76.0, 39.0, -74.0, 41.0)})
        )

    # Undisclosed missing vector layer rejected.
    no_ctx = tuple(f for f in artifact.features if f.id != "f-ctx")
    with pytest.raises(ValueError, match="vector layer neither shown nor omitted"):
        validate_web_map_artifact(standalone, artifact.model_copy(update={"features": no_ctx}))

    # Undisclosed missing raster rejected.
    with pytest.raises(ValueError, match="raster neither shown nor omitted"):
        validate_web_map_artifact(standalone, artifact.model_copy(update={"rasters": ()}))

    # Undisclosed missing calculation rejected; disclosing it as unavailable passes.
    only_ctx = (artifact.features[-1],)
    with pytest.raises(ValueError, match="calculation neither shown nor omitted"):
        validate_web_map_artifact(standalone, artifact.model_copy(update={"features": only_ctx}))
    omitted_calc = artifact.model_copy(
        update={
            "features": only_ctx,
            "availability": "partial",
            "unavailable": (
                WebMapUnavailableItem(
                    item_id="calc-1", kind="calculation", code="unplaced", reason="omitted"
                ),
            ),
        }
    )
    assert validate_web_map_artifact(standalone, omitted_calc) == omitted_calc

    # Stale bindings rejected: context, deed feature, recorded call, marker, and raster.
    bad_ctx = list(artifact.features)
    bad_ctx[4] = bad_ctx[4].model_copy(
        update={"properties": bad_ctx[4].properties.model_copy(update={"layer_id": "other"})}
    )
    with pytest.raises(ValueError, match="stale online context binding"):
        validate_web_map_artifact(
            standalone, artifact.model_copy(update={"features": tuple(bad_ctx)})
        )

    bad_deed = list(artifact.features)
    bad_deed[0] = bad_deed[0].model_copy(
        update={"properties": bad_deed[0].properties.model_copy(update={"geometry_hash": "0" * 64})}
    )
    with pytest.raises(ValueError, match="stale online deed feature binding"):
        validate_web_map_artifact(
            standalone, artifact.model_copy(update={"features": tuple(bad_deed)})
        )

    bad_call = list(artifact.features)
    bad_call[0] = bad_call[0].model_copy(
        update={"properties": bad_call[0].properties.model_copy(update={"call_id": "unknown-call"})}
    )
    with pytest.raises(ValueError, match="stale online recorded call binding"):
        validate_web_map_artifact(
            standalone, artifact.model_copy(update={"features": tuple(bad_call)})
        )

    bad_marker = list(artifact.features)
    bad_marker[2] = bad_marker[2].model_copy(
        update={"properties": bad_marker[2].properties.model_copy(update={"page_id": "p1"})}
    )
    with pytest.raises(ValueError, match="stale online marker binding"):
        validate_web_map_artifact(
            standalone, artifact.model_copy(update={"features": tuple(bad_marker)})
        )

    bad_raster = (artifact.rasters[0].model_copy(update={"source_sha256": "0" * 64}),)
    with pytest.raises(ValueError, match="stale online raster binding"):
        validate_web_map_artifact(standalone, artifact.model_copy(update={"rasters": bad_raster}))


def test_partial_geometry_must_be_disclosed_and_degenerate_course_rejected():
    from mp_models import DeedCall
    from mp_models.plot import PlotPlacement, PlotScene
    from mp_models.plot_request import PlotCall, PlotRequest
    from mp_models.webmap import (
        StandaloneWebMapInput,
        WebMapFeature,
        WebMapLine,
        WebMapPoint,
        WebMapProjectionRecord,
        WebMapProperties,
    )
    from mp_verify import webmap
    from mp_verify.plot import prepare_plot

    partial_plot = prepare_plot(
        PlotRequest(
            title="Partial",
            calculation_id="calc-p",
            foot_definition="international_ft",
            calls=(
                PlotCall(
                    id="c1",
                    call=DeedCall(
                        course=1,
                        direction_text="North",
                        bearing_azimuth_deg_from_north=0.0,
                        distance_ft=100.0,
                    ),
                ),
                PlotCall(id="c2", call=None),
            ),
        )
    )
    scene = PlotScene(id="grid", name="Grid", kind="projected", crs="EPSG:3857", units="m")
    placement = PlotPlacement(
        id="pl-p",
        calculation_id="calc-p",
        geometry_hash=partial_plot.geometry.geometry_hash,
        scene_id="grid",
        status="approximate",
        rationale="manual",
    )
    standalone = StandaloneWebMapInput(
        title="Partial standalone",
        plots=(partial_plot,),
        scenes=(scene,),
        placements=(placement,),
    )
    ctx = webmap.normalize_web_map_context(standalone)
    options = WebMapOptions()
    projection = WebMapProjectionRecord(source_crs_wkt="EPSG:3857", pipeline="+proj=noop")
    props_common = {
        "calculation_id": "calc-p",
        "geometry_hash": partial_plot.geometry.geometry_hash,
        "placement_id": "pl-p",
        "placement_hash": _sha256_json(placement.model_dump(mode="json")),
        "placement_status": "approximate",
        "completeness": "partial",
    }
    features = (
        WebMapFeature(
            id="f-c1",
            geometry=WebMapLine(coordinates=((-75.0, 40.0), (-75.0, 40.001))),
            properties=WebMapProperties(kind="recorded_course", call_id="c1", **props_common),
        ),
        WebMapFeature(
            id="f-pob",
            geometry=WebMapPoint(coordinates=(-75.0, 40.0)),
            properties=WebMapProperties(kind="pob", **props_common),
        ),
    )
    artifact = WebMapArtifact(
        scene_id="grid",
        input_hashes=ctx.input_hashes,
        options=options,
        options_sha256=_sha256_json(options.model_dump(mode="json")),
        projection=projection,
        features=features,
        availability="ready",
        bounds=(-75.0, 40.0, -75.0, 40.001),
    )
    with pytest.raises(ValueError, match="partial geometry is not disclosed"):
        validate_web_map_artifact(standalone, artifact)

    # A recorded course forged via model_construct with Point geometry is rejected on revalidation.
    degenerate_course = WebMapFeature.model_construct(
        type="Feature",
        id="f-deg",
        geometry=WebMapPoint(coordinates=(-75.0, 40.0)),
        properties=WebMapProperties(kind="recorded_course", call_id="c1", **props_common),
    )
    with pytest.raises(
        ValueError, match="recorded course requires call identity and line geometry"
    ):
        validate_web_map_artifact(
            standalone,
            artifact.model_copy(update={"features": (degenerate_course, features[1])}),
        )
