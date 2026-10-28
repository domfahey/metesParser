"""Optional online staging preserves offline bytes and review-only decisions."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from mp_models.dashboard import DashboardBundle
from mp_models.webmap import WebMapRequest
from mp_review.dashboard import dashboard_file, prepare_dashboard

FIXTURE = Path(__file__).parent / "fixtures/dashboard-absolute.json"


def bundle_file(tmp_path):
    data = json.loads(FIXTURE.read_text())
    data["schema_version"] = "1.1"
    data["calculations"][0]["frame"]["foot_definition"] = "international_ft"
    prepared = prepare_dashboard(DashboardBundle.model_validate(data))
    data["scenes"] = [
        {"id": "grid", "name": "Synthetic", "kind": "projected", "units": "m", "crs": "EPSG:3857"}
    ]
    data["placements"] = [
        {
            "id": "placed",
            "calculation_id": "calc-one",
            "geometry_hash": prepared.plots.geometries[0].geometry_hash,
            "scene_id": "grid",
            "rotation_deg": 0,
            "translation": [1000, 2000],
            "status": "approximate",
            "rationale": "Synthetic control",
        }
    ]
    path = tmp_path / "input.json"
    path.write_text(json.dumps(data))
    return path


def test_online_staging_leaves_canonical_and_offline_bytes_identical(tmp_path):
    source = bundle_file(tmp_path)
    plain = dashboard_file(source, tmp_path / "plain")
    online = dashboard_file(source, tmp_path / "online", online_map=WebMapRequest(scene_id="grid"))
    assert plain["status"] == online["status"] == "needs_review"
    assert online["verified_export_eligible"] is False
    assert plain["manifest"] == online["manifest"]
    for name in plain["artifacts"]:
        assert (tmp_path / "plain" / name).read_bytes() == (tmp_path / "online" / name).read_bytes()
    assert online["online_map_availability"] == "ready"
    manifest = json.loads((tmp_path / "online/web-map-manifest.json").read_text())
    assert set(manifest["files"]) == {"dashboard.html", "online-map.html"}
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((tmp_path / "online" / name).read_bytes()).hexdigest() == digest
    assert (tmp_path / "online/web-map-request.json").is_file()
    assert (tmp_path / "online/web-map.json").is_file()
    assert not list((tmp_path / "plain").glob("*web-map*"))


def test_unavailable_online_scene_retains_offline_result(tmp_path):
    source = bundle_file(tmp_path)
    data = json.loads(source.read_text())
    data["scenes"][0].update(kind="local", crs=None)
    source.write_text(json.dumps(data))
    result = dashboard_file(source, tmp_path / "out", online_map=WebMapRequest(scene_id="grid"))
    assert result["status"] == "needs_review", result
    assert result["online_map_availability"] == "unavailable"
    assert (tmp_path / "out/dashboard.html").is_file()


def test_cli_rejects_credentials_without_echo_or_output(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"scene_id": "grid", "token": "sk.DO_NOT_ECHO"}))
    output = tmp_path / "output"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "mp_review",
            "dashboard",
            str(FIXTURE),
            "--online-map-config",
            str(config),
            "--output-dir",
            str(output),
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    response = json.loads(completed.stdout)
    assert response["errors"][0]["code"] == "invalid_online_map_config"
    assert "DO_NOT_ECHO" not in completed.stdout + completed.stderr
    assert not output.exists()


def test_cli_online_and_disabled_preview(tmp_path):
    source = bundle_file(tmp_path)
    config = tmp_path / "config.json"
    config.write_text('{"scene_id":"grid"}')
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "mp_review",
            "dashboard",
            str(source),
            "--online-map-config",
            str(config),
            "--output-dir",
            str(tmp_path / "online"),
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1, completed.stderr
    assert json.loads(completed.stdout)["online_map_availability"] == "ready"
    settings = tmp_path / "settings.md"
    settings.write_text("---\nenabled: false\n---\n")
    disabled = subprocess.run(
        [
            sys.executable,
            "-m",
            "mp_review",
            "serve-map",
            str(tmp_path / "missing"),
            "--settings",
            str(settings),
        ],
        capture_output=True,
        text=True,
    )
    assert disabled.returncode == 2
    assert json.loads(disabled.stdout)["errors"][0]["code"] == "plugin_disabled"


def test_staged_warp_is_hashed_and_only_display_assets_are_served(tmp_path):
    from io import BytesIO

    from mp_models.plot import PlotScene
    from mp_review.map_preview import _display_files
    from mp_review.raster_registration import image_layer, supplied_affine
    from PIL import Image

    source = bundle_file(tmp_path)
    data = json.loads(source.read_text())
    stream = BytesIO()
    Image.new("RGBA", (3, 2), (255, 0, 0, 128)).save(stream, format="PNG")
    layer, evidence = image_layer(
        stream.getvalue(),
        scene=PlotScene.model_validate(data["scenes"][0]),
        registration=supplied_affine((1, 0, 1000, 0, -1, 2000), ()),
        filename="tax.png",
    )
    data["map_sources"] = [evidence.model_dump(mode="json")]
    data["raster_layers"] = [layer.model_dump(mode="json")]
    source.write_text(json.dumps(data))
    result = dashboard_file(source, tmp_path / "out", online_map=WebMapRequest(scene_id="grid"))
    assert result["status"] == "needs_review", result
    assert result["online_map_availability"] == "ready"
    files = _display_files(tmp_path / "out")
    raster_names = [name for name in files if name.endswith(".png")]
    assert len(raster_names) == 1
    artifact = json.loads((tmp_path / "out/web-map.json").read_text())
    assert hashlib.sha256(files[raster_names[0]]).hexdigest() == artifact["rasters"][0]["sha256"]
    assert set(files) == {"/dashboard.html", "/online-map.html", raster_names[0]}
