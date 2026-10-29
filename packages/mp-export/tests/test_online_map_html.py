"""Online shell contracts, with no provider or geographic computation."""

import hashlib
import html
import json
import re
from pathlib import Path

import pytest
from mp_export.online_map_html import online_renderer_fingerprint, render_online_map
from mp_models.dashboard import DashboardBundle
from mp_models.webmap import MapboxViewOptions, WebMapArtifact, WebMapOptions
from mp_verify.dashboard import calculate_dashboard

ROOT = Path(__file__).resolve().parents[3]


def prepared_and_artifact(unsafe=False):
    data = json.loads(
        (ROOT / "packages/mp-review/tests/fixtures/dashboard-absolute.json").read_text()
    )
    data["schema_version"] = "1.1"
    data["calculations"][0]["frame"]["foot_definition"] = "international_ft"
    data["scenes"] = [
        {
            "id": "scene-one",
            "name": "Synthetic scene",
            "kind": "projected",
            "crs": "EPSG:3857",
            "units": "m",
        }
    ]
    data["map_sources"] = [
        {
            "id": "source-one",
            "label": "Synthetic context",
            "sha256": "a" * 64,
            "filename": "synthetic.json",
            "native_units": "m",
        }
    ]
    data["vector_layers"] = [
        {
            "id": "context-layer",
            "label": "Supplied outline",
            "source_id": "source-one",
            "scene_id": "scene-one",
            "geometry_type": "Polygon",
            "coordinates": [[[0, 0], [100, 0], [100, 100], [0, 0]]],
        }
    ]
    if unsafe:
        data["title"] = "</script><img onerror=x>&\u2028\u2029"
        data["calls"][0]["quote"] = data["title"]
    geometry = calculate_dashboard(DashboardBundle.model_validate(data)).plots.geometries[0]
    data["placements"] = [
        {
            "id": "placed",
            "calculation_id": geometry.calculation_id,
            "geometry_hash": geometry.geometry_hash,
            "scene_id": "scene-one",
            "rationale": "Synthetic <placement> & evidence",
        }
    ]
    prepared = calculate_dashboard(DashboardBundle.model_validate(data))
    options = WebMapOptions()
    hashes = tuple(
        (key, value)
        for key, value in prepared.manifest.model_dump().items()
        if key.endswith("_hash") and value is not None
    )
    artifact = WebMapArtifact(
        scene_id="scene-one",
        input_hashes=hashes,
        options=options,
        options_sha256=hashlib.sha256(
            json.dumps(
                options.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest(),
        availability="unavailable",
    )
    return prepared, artifact


def test_safe_deterministic_shell_and_frozen_selectors():
    prepared, artifact = prepared_and_artifact(True)
    before = prepared.model_dump_json(), artifact.model_dump_json()
    result = render_online_map(prepared, artifact, view=MapboxViewOptions())
    assert result == render_online_map(prepared, artifact, view=MapboxViewOptions())
    assert before == (prepared.model_dump_json(), artifact.model_dump_json())
    for selector in (
        "map-connect",
        "map-disconnect",
        "map-status",
        "map-style",
        "map-source-panel",
        "offline-link",
    ):
        assert f'data-testid="{selector}"' in result
    payload = re.search(
        r'<script type="application/json" id="online-map-data">(.*?)</script>', result, re.S
    )[1]
    assert (
        "<" not in payload
        and "&" not in payload
        and "\u2028" not in payload
        and "\u2029" not in payload
    )
    assert json.loads(payload)["bundle"]["title"] == prepared.bundle.title
    assert 'data-map-call="' in result
    assert "Source image unavailable" in result
    assert "Geographic display unavailable" in result
    assert "<script src=" not in result and "<link " not in result
    assert "wasm-unsafe-eval" in result and "worker-src blob:" in result
    assert "localStorage" not in result and "sessionStorage" not in result


def test_stale_artifact_rejected():
    prepared, artifact = prepared_and_artifact()
    artifact = artifact.model_copy(update={"input_hashes": ()})
    with pytest.raises(ValueError, match="stale"):
        render_online_map(prepared, artifact, view=MapboxViewOptions())


def test_map_summary_preserves_calculation_frame_and_bearing_basis():
    prepared, artifact = prepared_and_artifact()
    result = render_online_map(prepared, artifact, view=MapboxViewOptions())
    frame = prepared.bundle.calculations[0].frame
    assert f"Bearing basis: {frame.basis}" in result
    assert f"Frame: {frame.name}" in result
    assert "foot definition: international_ft" in result
    assert "numerical placement uncertainty is unknown" in result


def test_active_raster_control_escapes_long_malicious_labels_without_mutating_evidence():
    from io import BytesIO

    from mp_models.plot import PlotScene
    from mp_models.raster import RasterRegistration
    from mp_review.raster_registration import image_layer
    from mp_review.webmap import prepare_web_map
    from PIL import Image

    prepared, _ = prepared_and_artifact()
    data = prepared.bundle.model_dump(mode="json")
    image = BytesIO()
    Image.new("RGBA", (2, 2), (40, 80, 240, 180)).save(image, format="PNG")
    image_bytes = image.getvalue()
    layer, source = image_layer(
        image_bytes,
        scene=PlotScene.model_validate(data["scenes"][0]),
        registration=RasterRegistration(method="supplied_affine", matrix=(1, 0, 0, 0, 1, 0)),
        filename="synthetic.png",
    )
    label = (
        '<img src=x onerror="window.scanLabelInjected=true"> & "quoted" ' + "LongScanLabel" * 100
    )
    data["map_sources"].append(source.model_dump(mode="json"))
    data["raster_layers"] = [{**layer.model_dump(mode="json"), "label": label}]
    prepared = calculate_dashboard(DashboardBundle.model_validate(data))
    artifact = prepare_web_map(prepared, scene_id="scene-one", options=WebMapOptions()).artifact
    assert len(artifact.rasters) == 1
    before = prepared.model_dump_json(), artifact.model_dump_json()
    rendered = render_online_map(prepared, artifact, view=MapboxViewOptions())
    assert f"<legend>{html.escape(label)}</legend>" in rendered
    assert f'aria-label="Raise {html.escape(label, quote=True)}"' in rendered
    assert label not in rendered
    assert before == (prepared.model_dump_json(), artifact.model_dump_json())


def test_fingerprint_includes_descriptor_and_both_assets(monkeypatch):
    baseline = online_renderer_fingerprint()
    original = Path.read_bytes
    for filename in ("online_map.js", "online_map.css", "mapbox-sdk.json"):
        with monkeypatch.context() as patch:
            patch.setattr(
                Path,
                "read_bytes",
                lambda p, target=filename: original(p) + (b" " if p.name == target else b""),
            )
            assert baseline != online_renderer_fingerprint()


def test_exact_descriptor_is_embedded_without_remote_resource_tags():
    prepared, artifact = prepared_and_artifact()
    result = render_online_map(prepared, artifact, view=MapboxViewOptions())
    descriptor = json.loads(
        (ROOT / "packages/mp-export/src/mp_export/dashboard_assets/mapbox-sdk.json").read_text()
    )
    for item in descriptor["files"].values():
        assert item["url"] in result and item["integrity"] in result
    assert "mapbox://styles/mapbox/standard-satellite" in result


def test_ready_context_is_serialized_without_geographic_computation():
    from mp_models.webmap import (
        WebMapFeature,
        WebMapPolygon,
        WebMapProjectionRecord,
        WebMapProperties,
    )

    prepared, artifact = prepared_and_artifact()
    feature = WebMapFeature(
        id="context-one",
        geometry=WebMapPolygon(coordinates=(((1.0, 1.0), (1.01, 1.0), (1.01, 1.01), (1.0, 1.0)),)),
        properties=WebMapProperties(
            kind="parcel_context",
            source_id="source-one",
            layer_id="context-layer",
            label="Supplied outline",
        ),
    )
    artifact = artifact.model_copy(
        update={
            "features": (feature,),
            "projection": WebMapProjectionRecord(source_crs_wkt="synthetic", pipeline="synthetic"),
            "availability": "ready",
            "bounds": (1.0, 1.0, 1.01, 1.01),
        }
    )
    result = render_online_map(
        prepared, artifact, view=MapboxViewOptions(style="standard-satellite")
    )
    payload = re.search(
        r'<script type="application/json" id="online-map-data">(.*?)</script>', result, re.S
    )[1]
    assert json.loads(payload)["artifact"]["features"][0] == feature.model_dump(mode="json")
    assert "Disconnected. Connect to load the basemap." in result
    assert 'data-map-layer="parcel_context"' in result
    assert (
        "mp_review"
        not in (ROOT / "packages/mp-export/src/mp_export/online_map_html.py").read_text()
    )


def test_referrer_and_provider_disclosure_precede_connection():
    prepared, artifact = prepared_and_artifact()
    result = render_online_map(prepared, artifact, view=MapboxViewOptions())
    assert '<meta name="referrer" content="strict-origin">' in result
    disclosure = "Mapbox receives your public token and viewed map area"
    assert disclosure in result
    assert result.index(disclosure) < result.index('<form id="map-connection">')
    assert "does not upload deed records or scan files to Mapbox" in result


def test_review_layers_have_collision_free_ids_and_documented_style_config():
    import shutil
    import subprocess

    node = shutil.which("node")
    assert node, "Node is required for renderer layer adapter regression"
    script = (ROOT / "packages/mp-export/src/mp_export/dashboard_assets/online_map.js").read_text()
    function = (
        "function ensureReviewLayers() {"
        + script.split("function ensureReviewLayers() {", 1)[1].split("  function fit()", 1)[0]
    )
    harness = """
const assert = require('node:assert/strict');
let config = [], sourceIDs = [], layerIDs = [];
let baseline = {view:{style:'standard'}};
let artifact = {features:[],rasters:[{id:'selection',path:'x',corners:[]},{id:'parcel_context',path:'y',corners:[]}]};
let mapError = false;
const rasterOrder=['selection','parcel_context'];
const rasterOpacity={selection:0.5,parcel_context:0.5};
const visibility = {"raster-selection":true,"raster-parcel_context":true,parcel_context:true,recorded_course:true,pob:true,closure_gap:true};
const layerId = kind => `review-${kind}`;
const rasterId = id => `review-raster-${id}`;
const collection = features => ({type:'FeatureCollection',features});
const selectionData = () => collection([]);
const status = () => {};
const $ = () => ({value:baseline.view.style});
const map = {setProjection(){},setTerrain(){},setPitch(){},setConfigProperty(...args){config.push(args)},
getSource(id){return sourceIDs.includes(id)},getLayer(id){return layerIDs.includes(id)},
addSource(id){sourceIDs.push(id)},addLayer(layer){layerIDs.push(layer.id)}};
"""
    assertions = """
ensureReviewLayers();
assert(sourceIDs.includes('review-raster-selection'));
assert(sourceIDs.includes('review-raster-parcel_context'));
assert(sourceIDs.includes('review-selection'));
assert.deepEqual(config, [['basemap','show3dObjects',false]]);
assert(layerIDs.indexOf('review-raster-selection') < layerIDs.indexOf('review-parcel_context'));
assert(layerIDs.indexOf('review-parcel_context') < layerIDs.indexOf('review-recorded_course'));
assert.equal(layerIDs.at(-1), 'review-selection');
const count = layerIDs.length; ensureReviewLayers(); assert.equal(layerIDs.length,count);
config=[]; baseline.view.style='standard-satellite'; ensureReviewLayers(); assert.deepEqual(config,[]);
"""
    subprocess.run(
        [node, "-e", harness + function + assertions], check=True, capture_output=True, text=True
    )


def deed_artifact(prepared, artifact, kind="recorded_course"):
    from mp_models.webmap import (
        WebMapFeature,
        WebMapLine,
        WebMapPoint,
        WebMapProjectionRecord,
        WebMapProperties,
    )

    geometry = prepared.plots.geometries[0]
    placement = prepared.plots.placements[0]
    call = prepared.bundle.calls[0]
    props = WebMapProperties(
        kind=kind,
        calculation_id=geometry.calculation_id,
        occurrence_id=geometry.occurrence_id,
        geometry_hash=geometry.geometry_hash,
        placement_id=placement.id,
        placement_hash=hashlib.sha256(
            json.dumps(
                placement.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest(),
        placement_status=placement.status,
        completeness=geometry.completeness,
        call_id=call.id if kind == "recorded_course" else None,
        page_id=call.page_id if kind == "recorded_course" else None,
    )
    feature = WebMapFeature(
        id="synthetic-feature",
        properties=props,
        geometry=WebMapPoint(coordinates=(1, 1))
        if kind == "pob"
        else WebMapLine(coordinates=((1, 1), (1.01, 1.01))),
    )
    return artifact.model_copy(
        update={
            "features": (feature,),
            "availability": "ready",
            "bounds": (1, 1, 1.01, 1.01),
            "projection": WebMapProjectionRecord(source_crs_wkt="synthetic", pipeline="synthetic"),
        }
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("calculation_id", "absent"),
        ("placement_id", "absent"),
        ("geometry_hash", "0" * 64),
        ("placement_hash", "0" * 64),
        ("placement_status", "referenced"),
        ("completeness", "partial"),
        ("occurrence_id", "absent"),
    ],
)
@pytest.mark.parametrize("kind", ["recorded_course", "pob", "closure_gap"])
def test_forged_deed_feature_provenance_rejected(field, value, kind):
    prepared, artifact = prepared_and_artifact()
    artifact = deed_artifact(prepared, artifact, kind)
    feature = artifact.features[0]
    feature = feature.model_copy(
        update={"properties": feature.properties.model_copy(update={field: value})}
    )
    artifact = artifact.model_copy(update={"features": (feature,)})
    with pytest.raises(ValueError, match="binding"):
        render_online_map(prepared, artifact, view=MapboxViewOptions())


def test_unknown_scene_rejected():
    prepared, artifact = prepared_and_artifact()
    with pytest.raises(ValueError, match="scene"):
        render_online_map(
            prepared, artifact.model_copy(update={"scene_id": "absent"}), view=MapboxViewOptions()
        )


@pytest.mark.parametrize("kind", ["recorded_course", "pob"])
def test_genuine_deed_bindings_are_accepted(kind):
    prepared, artifact = prepared_and_artifact()
    render_online_map(prepared, deed_artifact(prepared, artifact, kind), view=MapboxViewOptions())


@pytest.mark.parametrize("field,value", [("source_id", "absent"), ("layer_id", "absent")])
def test_context_binding_rejects_missing_sources(field, value):
    prepared, artifact = prepared_and_artifact()
    from mp_models.webmap import (
        WebMapFeature,
        WebMapPolygon,
        WebMapProjectionRecord,
        WebMapProperties,
    )

    feature = WebMapFeature(
        id="context",
        geometry=WebMapPolygon(coordinates=(((1, 1), (2, 1), (2, 2), (1, 1)),)),
        properties=WebMapProperties(
            kind="parcel_context", source_id="source-one", layer_id="context-layer"
        ),
    )
    feature = feature.model_copy(
        update={"properties": feature.properties.model_copy(update={field: value})}
    )
    artifact = artifact.model_copy(
        update={
            "features": (feature,),
            "availability": "ready",
            "bounds": (1, 1, 2, 2),
            "projection": WebMapProjectionRecord(source_crs_wkt="synthetic", pipeline="synthetic"),
        }
    )
    with pytest.raises(ValueError, match="binding"):
        render_online_map(prepared, artifact, view=MapboxViewOptions())


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_id", "absent"),
        ("source_sha256", "0" * 64),
        ("registration_sha256", "0" * 64),
        ("projection_sha256", "0" * 64),
        ("fit_rms", 1.0),
        ("residual_units", "international_ft"),
    ],
)
def test_raster_provenance_rejects_stale_bindings(field, value):
    from mp_models.webmap import WebMapProjectionRecord, WebMapRaster

    prepared, artifact = prepared_and_artifact()
    data = prepared.bundle.model_dump(mode="json")
    image = data["pages"][0]
    data["map_sources"].append(
        {
            "id": "scan-source",
            "label": "Scan",
            "sha256": image["image_sha256"],
            "native_units": "pixel",
        }
    )
    data["raster_layers"] = [
        {
            "id": "scan",
            "label": "Scan",
            "source_id": "scan-source",
            "scene_id": "scene-one",
            "mime_type": "image/png",
            "width": 1,
            "height": 1,
            "sha256": image["image_sha256"],
            "data_base64": image["image"].split(",")[1],
            "registration": {"method": "supplied_affine", "matrix": [1, 0, 0, 0, 1, 0]},
        }
    ]
    prepared = calculate_dashboard(DashboardBundle.model_validate(data))
    projection = WebMapProjectionRecord(source_crs_wkt="synthetic", pipeline="synthetic")

    def digest(value):
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    raster = WebMapRaster(
        id="scan",
        source_id="scan-source",
        source_sha256=image["image_sha256"],
        registration_sha256=digest(
            prepared.bundle.raster_layers[0].registration.model_dump(mode="json")
        ),
        projection_sha256=digest(projection.model_dump(mode="json")),
        path="web-map-assets/scan.png",
        sha256="a" * 64,
        width=1,
        height=1,
        pixel_size_m=1,
        grid_affine=(1, 0, 0, 0, -1, 1),
        corners=((1, 2), (2, 2), (2, 1), (1, 1)),
        residual_units="m",
    )
    hashes = tuple(
        (key, value)
        for key, value in prepared.manifest.model_dump().items()
        if key.endswith("_hash") and value is not None
    )
    artifact = artifact.model_copy(
        update={
            "rasters": (raster,),
            "input_hashes": hashes,
            "projection": projection,
            "availability": "ready",
            "bounds": (1, 1, 2, 2),
        }
    )
    render_online_map(prepared, artifact, view=MapboxViewOptions())
    artifact = artifact.model_copy(update={"rasters": (raster.model_copy(update={field: value}),)})
    with pytest.raises(ValueError, match="binding"):
        render_online_map(prepared, artifact, view=MapboxViewOptions())
