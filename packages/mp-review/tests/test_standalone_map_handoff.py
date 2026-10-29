"""Standalone online-map stages can be reused for MCP and local preview."""

import hashlib
import json
from pathlib import Path

import pytest
from mp_models import DeedCall
from mp_models.plot import PlotPlacement, PlotScene
from mp_models.plot_request import PlotCall, PlotRequest
from mp_models.webmap import StandaloneWebMapInput, WebMapRequest
from mp_review.map_preview import _display_files
from mp_review.online_map import render_map_file
from mp_review.webmap import prepare_web_map
from mp_verify.dashboard import _hash, _json
from mp_verify.plot import prepare_plot
from mp_verify.webmap import normalize_web_map_context


def standalone_input() -> StandaloneWebMapInput:
    plot = prepare_plot(
        PlotRequest(
            title="Supplied description",
            calculation_id="survey",
            foot_definition="international_ft",
            calls=(
                PlotCall(
                    id="course-a",
                    call=DeedCall(
                        course=1,
                        direction_text="East 100 feet",
                        bearing_azimuth_deg_from_north=90,
                        distance_ft=100,
                    ),
                ),
            ),
        )
    )
    scene = PlotScene(id="grid", name="Grid", kind="projected", crs="EPSG:3857", units="m")
    placement = PlotPlacement(
        id="anchor",
        calculation_id="survey",
        geometry_hash=plot.geometry.geometry_hash,
        scene_id=scene.id,
        translation=(1000, 2000),
        rationale="User supplied control",
        position_evidence=("User supplied position",),
        orientation_evidence=("Approximate rotation supplied",),
    )
    return StandaloneWebMapInput(
        title="Standalone",
        plots=(plot,),
        scenes=(scene,),
        placements=(placement,),
    )


def staged_standalone(directory: Path) -> Path:
    value = standalone_input()
    request = WebMapRequest(scene_id="grid")
    prepared = prepare_web_map(value, scene_id=request.scene_id, options=request.display)
    source_data = value.model_dump(mode="json")
    request_data = request.model_dump(mode="json")
    artifact_data = prepared.artifact.model_dump(mode="json")
    files = {
        "online-map.html": b"<html>online standalone view</html>",
        "map-evidence.html": b"<html>source and course evidence</html>",
        **dict(prepared.assets),
    }
    directory.mkdir()
    (directory / "source-map.json").write_text(_json(source_data), encoding="utf-8")
    (directory / "web-map-request.json").write_text(_json(request_data), encoding="utf-8")
    (directory / "web-map.json").write_text(_json(artifact_data), encoding="utf-8")
    for name, content in files.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    from mp_export.online_map_html import online_renderer_fingerprint

    manifest = {
        "schema_version": "1.0",
        "source_kind": "standalone",
        "source_sha256": hashlib.sha256((directory / "source-map.json").read_bytes()).hexdigest(),
        "input_hashes": dict(normalize_web_map_context(value).input_hashes),
        "request_sha256": _hash(request_data),
        "artifact_sha256": _hash(artifact_data),
        "renderer_sha256": online_renderer_fingerprint(),
        "files": {name: hashlib.sha256(content).hexdigest() for name, content in files.items()},
    }
    (directory / "web-map-manifest.json").write_text(_json(manifest), encoding="utf-8")
    return directory


def stage_with_real_renderer(directory: Path) -> Path:
    source = directory.parent / "standalone-input.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(_json(standalone_input().model_dump(mode="json")), encoding="utf-8")
    result = render_map_file(source, directory, online_map=WebMapRequest(scene_id="grid"))
    assert result["status"] == "needs_review", result
    assert result["online_map_availability"] == "ready", result
    return directory


def test_standalone_stage_builds_mcp_handoff_without_reprojection(tmp_path, monkeypatch):
    from mp_review import webmap, webmap_projection, webmap_raster
    from mp_review.mapbox_mcp import mapbox_mcp_file
    from pyproj import Transformer

    staged = staged_standalone(tmp_path / "online")

    def no_geographic_preparation(*args, **kwargs):
        pytest.fail("MCP handoff must reuse prepared coordinates and raster bytes")

    monkeypatch.setattr(webmap, "prepare_web_map", no_geographic_preparation)
    monkeypatch.setattr(webmap_projection, "build_web_map_projection", no_geographic_preparation)
    monkeypatch.setattr(webmap_raster, "prepare_web_map_raster", no_geographic_preparation)
    monkeypatch.setattr(Transformer, "from_crs", no_geographic_preparation)
    monkeypatch.setattr(Transformer, "from_pipeline", no_geographic_preparation)

    output = tmp_path / "handoff"
    result = mapbox_mcp_file(staged, output)
    assert result["status"] == "needs_review", result
    assert result["source_review_complete"] is False
    assert result["engine_verified"] is False
    assert result["verified_export_eligible"] is False
    report = json.loads((output / "mapbox-mcp-handoff.json").read_text())
    assert report["local_review"] == {
        "evidence": str((staged / "map-evidence.html").resolve()),
        "online_map": str((staged / "online-map.html").resolve()),
    }
    arguments = json.loads((output / "mapbox-mcp-arguments.json").read_text())
    assert arguments["layers"]
    assert "dashboard" not in report["local_review"]


def test_real_standalone_writer_stage_feeds_mcp_handoff(tmp_path):
    from mp_review.mapbox_mcp import mapbox_mcp_file

    staged = stage_with_real_renderer(tmp_path / "online")
    output = tmp_path / "handoff"
    result = mapbox_mcp_file(staged, output)
    assert result["status"] == "needs_review", result
    report = json.loads((output / "mapbox-mcp-handoff.json").read_text())
    assert report["local_review"]["evidence"].endswith("/map-evidence.html")
    assert report["local_review"]["online_map"].endswith("/online-map.html")


def test_real_standalone_writer_stage_feeds_local_preview_allowlist(tmp_path):
    staged = stage_with_real_renderer(tmp_path / "online")
    files = _display_files(staged)
    assert "/online-map.html" in files
    assert "/map-evidence.html" in files
    assert "/dashboard.html" not in files


@pytest.mark.parametrize(
    "damage", ["source", "request", "artifact", "input_hashes", "renderer", "extra_asset"]
)
def test_standalone_stage_tampering_is_rejected_before_handoff(tmp_path, damage):
    from mp_review.mapbox_mcp import mapbox_mcp_file

    staged = staged_standalone(tmp_path / "online")
    if damage == "source":
        source = staged / "source-map.json"
        data = json.loads(source.read_text())
        data["title"] = "changed"
        source.write_text(json.dumps(data))
    elif damage == "request":
        request = staged / "web-map-request.json"
        data = json.loads(request.read_text())
        data["scene_id"] = "other"
        request.write_text(json.dumps(data))
    elif damage == "artifact":
        artifact = staged / "web-map.json"
        data = json.loads(artifact.read_text())
        data["features"][0]["geometry"]["coordinates"][0][0] += 0.01
        artifact.write_text(json.dumps(data))
    elif damage == "input_hashes" or damage == "renderer":
        manifest_path = staged / "web-map-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        if damage == "input_hashes":
            manifest["input_hashes"] = {}
        else:
            manifest["renderer_sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest))
    else:
        manifest_path = staged / "web-map-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        orphan = b"unreferenced raster"
        orphan_path = staged / "web-map-assets/orphan.png"
        orphan_path.parent.mkdir()
        orphan_path.write_bytes(orphan)
        manifest["files"]["web-map-assets/orphan.png"] = hashlib.sha256(orphan).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
    output = tmp_path / "handoff"
    result = mapbox_mcp_file(staged, output)
    assert result["status"] == "error"
    assert result["errors"][0]["code"] == "invalid_mapbox_mcp_input"
    assert not output.exists()


def test_standalone_preview_allowlist_requires_evidence_and_rejects_source_json(tmp_path):
    staged = staged_standalone(tmp_path / "online")
    files = _display_files(staged)
    assert "/online-map.html" in files
    assert "/map-evidence.html" in files
    assert "/dashboard.html" not in files

    manifest_path = staged / "web-map-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["source-map.json"] = hashlib.sha256(
        (staged / "source-map.json").read_bytes()
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="allowlist"):
        _display_files(staged)


def test_standalone_preview_rejects_missing_evidence_fallback(tmp_path):
    staged = staged_standalone(tmp_path / "online")
    (staged / "map-evidence.html").unlink()
    with pytest.raises(ValueError, match="regular file"):
        _display_files(staged)
