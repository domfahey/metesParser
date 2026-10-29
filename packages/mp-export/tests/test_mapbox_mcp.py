"""Vector-only upstream handoff preserves prepared evidence without GIS work."""

import json
from pathlib import Path

import pytest
from mp_export.mapbox_mcp import build_mapbox_mcp_handoff
from mp_models.dashboard import DashboardBundle
from mp_models.webmap import WebMapArtifact, WebMapOptions
from mp_verify.dashboard import _hash, calculate_dashboard

ROOT = Path(__file__).resolve().parents[3]


def _features(geometry, prepared, placement):
    """A complete, internally consistent synthetic feature set (not real projections)."""
    calls = {c.id: c for c in prepared.bundle.calls}
    common = {
        "calculation_id": geometry.calculation_id,
        "geometry_hash": geometry.geometry_hash,
        "placement_id": placement.id,
        "placement_hash": _hash(placement.model_dump(mode="json")),
        "placement_status": placement.status,
        "completeness": geometry.completeness,
    }
    features = []
    for index, primitive in enumerate(geometry.primitives):
        call = calls[primitive.call_id]
        features.append(
            {
                "id": "course-one" if index == 0 else f"course-{index}",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[index, index], [index + 1, index + 1]],
                },
                "properties": {
                    **common,
                    "kind": "recorded_course",
                    "call_id": call.id,
                    "page_id": call.page_id,
                    "occurrence_id": call.occurrence_id,
                    "label": "SECRET SOURCE QUOTE",
                },
            }
        )
    marker = {**common, "occurrence_id": geometry.occurrence_id}
    features.append(
        {
            "id": "pob",
            "geometry": {"type": "Point", "coordinates": [0, 0]},
            "properties": {**marker, "kind": "pob"},
        }
    )
    first, last = geometry.primitives[0].start, geometry.primitives[-1].end
    if (
        geometry.completeness == "complete"
        and abs(first[0] - last[0]) + abs(first[1] - last[1]) > 1e-8
    ):
        n = len(geometry.primitives)
        features.append(
            {
                "id": "closure-gap",
                "geometry": {"type": "LineString", "coordinates": [[n, n], [0, 0]]},
                "properties": {**marker, "kind": "closure_gap"},
            }
        )
    return features


def evidence(edit=None):
    data = json.loads(
        (ROOT / "packages/mp-review/tests/fixtures/dashboard-absolute.json").read_text()
    )
    data["schema_version"] = "1.1"
    data["calculations"][0]["frame"]["foot_definition"] = "international_ft"
    data["scenes"] = [
        {"id": "grid", "name": "Synthetic", "kind": "projected", "units": "m", "crs": "EPSG:3857"}
    ]
    data["scenarios"] = []
    if edit:
        edit(data)
    initial = calculate_dashboard(DashboardBundle.model_validate(data))
    geometry = initial.plots.geometries[0]
    data["placements"] = [
        {
            "id": "placed",
            "calculation_id": geometry.calculation_id,
            "geometry_hash": geometry.geometry_hash,
            "scene_id": "grid",
            "status": "approximate",
            "rationale": "Synthetic only",
        }
    ]
    prepared = calculate_dashboard(DashboardBundle.model_validate(data))
    placement = prepared.plots.placements[0]
    options = WebMapOptions()
    artifact = WebMapArtifact.model_validate(
        {
            "scene_id": "grid",
            "input_hashes": [
                [key, value]
                for key, value in prepared.manifest.model_dump().items()
                if key.endswith("_hash") and value is not None
            ],
            "options": options.model_dump(),
            "options_sha256": _hash(options.model_dump(mode="json")),
            "projection": {"source_crs_wkt": "synthetic", "pipeline": "synthetic"},
            "availability": "ready",
            "bounds": [0, 0, len(geometry.primitives), len(geometry.primitives)],
            "features": _features(geometry, prepared, placement),
        }
    )
    return prepared, artifact


def test_exact_vectors_safe_properties_and_review_status():
    prepared, artifact = evidence()
    before = prepared.model_dump_json(), artifact.model_dump_json()
    result = build_mapbox_mcp_handoff(prepared, artifact)
    assert result["status"] == "needs_review"
    assert result["verified_export_eligible"] is False
    assert result["availability"] == "ready"
    assert result["tool_name"] == "render_map_tool"
    arguments = result["arguments"]
    assert set(arguments) == {"summary", "baseStyle", "layers", "legend"}
    feature = arguments["layers"][0]["data"]["features"][0]
    assert "geojson" not in arguments["layers"][0]
    assert feature["id"] == artifact.features[0].id
    assert feature["geometry"] == artifact.features[0].geometry.model_dump(mode="json")
    for key, value in feature["properties"].items():
        assert value == artifact.features[0].properties.model_dump(mode="json")[key]
    assert "SECRET SOURCE QUOTE" not in json.dumps(result)
    assert "approximate" in arguments["summary"]
    assert result["summary"] == arguments["summary"]
    assert "visualization" in arguments["summary"].lower()
    assert result["provenance"]["artifact_sha256"] == _hash(artifact.model_dump(mode="json"))
    assert before == (prepared.model_dump_json(), artifact.model_dump_json())
    feature["geometry"]["coordinates"][0][0] = 99
    assert before == (prepared.model_dump_json(), artifact.model_dump_json())


def test_unavailable_and_omissions_retained():
    prepared, artifact = evidence()
    value = artifact.model_dump(mode="json")
    value.update(
        features=[],
        availability="unavailable",
        bounds=None,
        unavailable=[
            {
                "item_id": "calc-one",
                "kind": "calculation",
                "code": "missing_placement",
                "reason": "Source-derived private text",
            }
        ],
    )
    result = build_mapbox_mcp_handoff(prepared, WebMapArtifact.model_validate(value))
    assert result["availability"] == "unavailable"
    assert result["arguments"] is None
    assert any(item["code"] == "missing_placement" for item in result["omissions"])


def test_stale_and_style_rejected():
    prepared, artifact = evidence()
    with pytest.raises(ValueError, match="stale"):
        build_mapbox_mcp_handoff(prepared, artifact.model_copy(update={"input_hashes": ()}))
    with pytest.raises(ValueError, match="style") as exc:
        build_mapbox_mcp_handoff(prepared, artifact, style="secret-token")
    assert "secret-token" not in str(exc.value)


def test_budget_refuses_all_without_simplification():
    prepared, artifact = evidence()
    data = artifact.model_dump(mode="json")
    # Keep the exact chained endpoint so only the vertex count changes.
    data["features"][0]["geometry"]["coordinates"] = [
        *([index / 100000, 0] for index in range(10000)),
        [1, 1],
    ]
    large = WebMapArtifact.model_validate(data)
    result = build_mapbox_mcp_handoff(prepared, large)
    assert result["availability"] == "unavailable"
    assert result["arguments"] is None
    assert any(item["code"] == "payload_too_large" for item in result["omissions"])
    assert len(large.features[0].geometry.coordinates) == 10001


def test_partial_does_not_add_a_bridge_or_closure():
    prepared, artifact = evidence()
    data = artifact.model_dump(mode="json")
    data.update(
        availability="partial",
        unavailable=[
            {
                "item_id": "calc-one",
                "kind": "calculation",
                "code": "partial_geometry",
                "reason": "Prefix only",
            }
        ],
    )
    result = build_mapbox_mcp_handoff(prepared, WebMapArtifact.model_validate(data))
    assert result["availability"] == "partial"
    assert [layer["type"] for layer in result["arguments"]["layers"]] == ["line", "circle"]
    assert "partial" in result["arguments"]["summary"].lower()
    kinds = {f.properties.kind for f in artifact.features}
    assert "closure_gap" not in kinds


def test_context_holes_gap_and_pob_have_distinct_layer_types():
    def change(data):
        data["calls"][-1]["call"]["distance_ft"] += 1
        data["map_sources"] = [
            {"id": "context", "label": "PRIVATE", "sha256": "a" * 64, "native_units": "m"}
        ]
        data["vector_layers"] = [
            {
                "id": "outline",
                "label": "PRIVATE",
                "source_id": "context",
                "scene_id": "grid",
                "geometry_type": "Polygon",
                "coordinates": [
                    [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
                    [[1, 1], [2, 1], [2, 2], [1, 1]],
                ],
            }
        ]

    prepared, artifact = evidence(change)
    value = artifact.model_dump(mode="json")
    context = {
        "id": "context-feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]],
                [[0.1, 0.1], [0.2, 0.1], [0.2, 0.2], [0.1, 0.1]],
            ],
        },
        "properties": {"kind": "parcel_context", "source_id": "context", "layer_id": "outline"},
    }
    value["features"].append(context)
    result = build_mapbox_mcp_handoff(prepared, WebMapArtifact.model_validate(value))
    layers = result["arguments"]["layers"]
    assert [layer["type"] for layer in layers] == ["fill", "line", "line", "circle"]
    assert layers[0]["data"]["features"][0]["geometry"] == context["geometry"]
    assert len(layers[0]["data"]["features"][0]["geometry"]["coordinates"]) == 2
    assert "line-dasharray" in layers[2]["paint"]
    assert all(
        layer["data"]["features"][0]["properties"]["kind"] != "closure_gap"
        for layer in layers
        if layer["type"] == "fill"
    )


@pytest.mark.parametrize("vectors", [False, True])
def test_rasters_are_explicitly_omitted_without_byte_leakage(vectors):
    from mp_models.webmap import WebMapRaster, WebMapUnavailableItem

    def change(data):
        image = data["pages"][0]
        data["map_sources"] = [
            {
                "id": "scan-source",
                "label": "Scan",
                "native_units": "pixel",
                "sha256": image["image_sha256"],
            }
        ]
        data["raster_layers"] = [
            {
                "id": "scan",
                "label": "Scan",
                "source_id": "scan-source",
                "scene_id": "grid",
                "mime_type": "image/png",
                "width": 1,
                "height": 1,
                "sha256": image["image_sha256"],
                "data_base64": image["image"].split(",")[1],
                "registration": {"method": "supplied_affine", "matrix": [1, 0, 0, 0, 1, 0]},
            }
        ]

    prepared, artifact = evidence(change)
    raster = WebMapRaster(
        id="scan",
        source_id="scan-source",
        source_sha256=prepared.bundle.raster_layers[0].sha256,
        registration_sha256=_hash(
            prepared.bundle.raster_layers[0].registration.model_dump(mode="json")
        ),
        projection_sha256=_hash(artifact.projection.model_dump(mode="json")),
        path="web-map-assets/scan.png",
        sha256="a" * 64,
        width=1,
        height=1,
        pixel_size_m=1,
        grid_affine=(1, 0, 0, 0, -1, 1),
        corners=((0, 1), (1, 1), (1, 0), (0, 0)),
        residual_units="m",
    )
    update = {"rasters": (raster,), "features": artifact.features if vectors else ()}
    if not vectors:
        update.update(
            availability="partial",
            bounds=(0, 0, 1, 1),
            unavailable=(
                WebMapUnavailableItem(
                    item_id="calc-one",
                    kind="calculation",
                    code="missing_placement",
                    reason="Synthetic omission",
                ),
            ),
        )
    artifact = artifact.model_copy(update=update)
    result = build_mapbox_mcp_handoff(prepared, artifact)
    assert result["availability"] == ("partial" if vectors else "unavailable")
    assert any(item["code"] == "mcp_raster_omitted" for item in result["omissions"])
    encoded = json.dumps(result)
    assert "data_base64" not in encoded and "web-map-assets" not in encoded
    if vectors:
        assert "Raster scans are omitted" in result["arguments"]["summary"]
    else:
        assert result["arguments"] is None


def test_exact_budget_accounts_for_upstream_default_markers(monkeypatch):
    import mp_export.mapbox_mcp as adapter

    prepared, artifact = evidence()
    first = build_mapbox_mcp_handoff(prepared, artifact)
    payload = {**first["arguments"], "markers": []}
    exact = len(adapter._compact(payload))
    monkeypatch.setattr(adapter, "MAX_PAYLOAD_BYTES", exact)
    assert build_mapbox_mcp_handoff(prepared, artifact)["arguments"] is not None
    monkeypatch.setattr(adapter, "MAX_PAYLOAD_BYTES", exact - 1)
    refused = build_mapbox_mcp_handoff(prepared, artifact)
    assert refused["arguments"] is None
    assert refused["arguments_sha256"] is None


def test_runtime_style_type_is_rejected_safely():
    prepared, artifact = evidence()
    with pytest.raises(ValueError, match="style"):
        build_mapbox_mcp_handoff(prepared, artifact, style=[])  # type: ignore[arg-type]
