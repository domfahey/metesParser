"""MCP handoffs reuse staged evidence without projection or provider activity."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from mp_models.dashboard import DashboardBundle
from mp_models.webmap import WebMapRequest
from mp_review.dashboard import dashboard_file, prepare_dashboard

FIXTURE = Path(__file__).parent / "fixtures/dashboard-absolute.json"


@pytest.fixture
def staged(tmp_path):
    data = json.loads(FIXTURE.read_text())
    data["schema_version"] = "1.1"
    data["calculations"][0]["frame"]["foot_definition"] = "international_ft"
    initial = prepare_dashboard(DashboardBundle.model_validate(data))
    data["scenes"] = [
        {"id": "grid", "name": "Synthetic", "kind": "projected", "units": "m", "crs": "EPSG:3857"}
    ]
    data["placements"] = [
        {
            "id": "placed",
            "calculation_id": "calc-one",
            "geometry_hash": initial.plots.geometries[0].geometry_hash,
            "scene_id": "grid",
            "rotation_deg": 0,
            "translation": [1000, 2000],
            "status": "approximate",
            "rationale": "Synthetic test control",
        }
    ]
    source = tmp_path / "input.json"
    source.write_text(json.dumps(data))
    directory = tmp_path / "dashboard"
    result = dashboard_file(source, directory, online_map=WebMapRequest(scene_id="grid"))
    assert result["online_map_availability"] == "ready", result
    return directory


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "mp_review", "mapbox-mcp", *map(str, args)],
        capture_output=True,
        text=True,
    )


def test_handoff_preserves_staged_geometry_without_reprojection(staged, tmp_path, monkeypatch):
    from mp_review import webmap, webmap_projection, webmap_raster
    from mp_review.mapbox_mcp import mapbox_mcp_file
    from pyproj import Transformer

    before = {p.name: p.read_bytes() for p in staged.iterdir() if p.is_file()}

    def no_preparation(*args, **kwargs):
        pytest.fail("MCP handoff must not repeat geographic preparation")

    monkeypatch.setattr(webmap, "prepare_web_map", no_preparation)
    monkeypatch.setattr(webmap_projection, "build_web_map_projection", no_preparation)
    monkeypatch.setattr(webmap_raster, "prepare_web_map_raster", no_preparation)
    monkeypatch.setattr(Transformer, "from_crs", no_preparation)
    monkeypatch.setattr(Transformer, "from_pipeline", no_preparation)
    directory = tmp_path / "handoff"
    result = mapbox_mcp_file(staged, directory, style="standard-satellite")
    assert result["status"] == "needs_review", result
    assert result["verified_export_eligible"] is False
    arguments = json.loads((directory / "mapbox-mcp-arguments.json").read_text())
    report = json.loads((directory / "mapbox-mcp-handoff.json").read_text())
    assert arguments["baseStyle"] == "standard-satellite"
    assert (
        report["arguments_sha256"]
        == hashlib.sha256((directory / "mapbox-mcp-arguments.json").read_bytes()).hexdigest()
    )
    actual = {
        f["id"]: f["geometry"] for layer in arguments["layers"] for f in layer["data"]["features"]
    }
    expected = {f["id"]: f["geometry"] for f in json.loads(before["web-map.json"])["features"]}
    assert actual == expected
    assert "arguments" not in report
    assert before == {p.name: p.read_bytes() for p in staged.iterdir() if p.is_file()}


@pytest.mark.parametrize(
    ("filename", "edit"),
    [
        (
            "web-map.json",
            lambda d: d["features"][0]["geometry"]["coordinates"][0].__setitem__(0, 10),
        ),
        ("web-map-request.json", lambda d: d.__setitem__("scene_id", "other")),
        ("source.json", lambda d: d.__setitem__("title", "Changed source")),
        ("stage-manifest.json", lambda d: d.__setitem__("calculation_output_hash", "0" * 64)),
        ("web-map-manifest.json", lambda d: d.__setitem__("input_hashes", {})),
    ],
)
def test_changed_staged_input_rejected_before_writing(staged, tmp_path, filename, edit):
    from mp_review.mapbox_mcp import mapbox_mcp_file

    path = staged / filename
    data = json.loads(path.read_text())
    edit(data)
    path.write_text(json.dumps(data))
    output = tmp_path / "handoff"
    result = mapbox_mcp_file(staged, output)
    assert result["status"] == "error"
    assert result["errors"][0]["code"] == "invalid_mapbox_mcp_input"
    assert not output.exists()


def test_cli_keeps_needs_review_and_never_overwrites(staged, tmp_path):
    output = tmp_path / "handoff"
    completed = run_cli(staged, "--output-dir", output)
    assert completed.returncode == 1, completed.stderr
    assert json.loads(completed.stdout)["status"] == "needs_review"
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    repeated = run_cli(staged, "--output-dir", output)
    assert repeated.returncode == 2
    assert json.loads(repeated.stdout)["status"] == "error"
    assert before == {p.name: p.read_bytes() for p in output.iterdir()}


def test_cli_disabled_and_error_values_are_not_echoed(staged, tmp_path):
    settings = tmp_path / "settings.md"
    settings.write_text("---\nenabled: false\n---\n")
    output = tmp_path / "handoff"
    disabled = run_cli(staged, "--output-dir", output, "--settings", settings)
    assert disabled.returncode == 2
    assert json.loads(disabled.stdout)["errors"][0]["code"] == "plugin_disabled"
    source = staged / "web-map-request.json"
    source.write_text('{"scene_id":"grid","token":"sk.DO_NOT_ECHO"}')
    invalid = run_cli(staged, "--output-dir", output)
    assert invalid.returncode == 2
    assert json.loads(invalid.stdout)["errors"][0]["code"] == "invalid_mapbox_mcp_input"
    assert "DO_NOT_ECHO" not in invalid.stdout + invalid.stderr
    assert not output.exists()


def test_unplaced_scene_writes_only_report_and_keeps_review_status(staged, tmp_path):
    data = json.loads((staged / "source.json").read_text())
    data["placements"] = []
    source = tmp_path / "unplaced.json"
    source.write_text(json.dumps(data))
    directory = tmp_path / "unplaced-dashboard"
    dashboard_file(source, directory, online_map=WebMapRequest(scene_id="grid"))
    output = tmp_path / "handoff"
    completed = run_cli(directory, "--output-dir", output)
    assert completed.returncode == 1, completed.stderr
    result = json.loads(completed.stdout)
    assert result["availability"] == "unavailable"
    assert result["verified_export_eligible"] is False
    assert not (output / "mapbox-mcp-arguments.json").exists()
    assert (output / "mapbox-mcp-handoff.json").is_file()


def test_missing_geographic_stage_cannot_trigger_repreparation(staged, tmp_path):
    (staged / "web-map.json").unlink()
    output = tmp_path / "handoff"
    completed = run_cli(staged, "--output-dir", output)
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["errors"][0]["code"] == "invalid_mapbox_mcp_input"
    assert not output.exists()


@pytest.mark.parametrize("filename", ["dashboard.html", "online-map.html"])
@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_local_review_fallback_must_match_manifest(staged, tmp_path, filename, damage):
    from mp_review.mapbox_mcp import mapbox_mcp_file

    path = staged / filename
    if damage == "missing":
        path.unlink()
    else:
        path.write_text("Changed display")
    output = tmp_path / "handoff"
    result = mapbox_mcp_file(staged, output)
    assert result["status"] == "error"
    assert not output.exists()
