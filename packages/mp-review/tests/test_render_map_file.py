"""Standalone map stages preserve source bytes and never grant verification."""

import hashlib
import json

import pytest
from mp_models import DeedCall
from mp_models.plot import PlotPlacement, PlotScene
from mp_models.plot_request import PlotCall, PlotRequest
from mp_models.webmap import StandaloneWebMapInput, WebMapRequest
from mp_review.online_map import render_map_file
from mp_verify.dashboard import _hash
from mp_verify.plot import prepare_plot


def source_input():
    plot = prepare_plot(
        PlotRequest(
            title="Recorded rectangle",
            calculation_id="boundary",
            foot_definition="international_ft",
            calls=tuple(
                PlotCall(
                    id=f"course-{i}",
                    quote=f"Original course {i} <unchanged>",
                    source_reference=f"Book 10, page 2, course {i}",
                    call=DeedCall(
                        course=i,
                        direction_text=f"Original course {i} <unchanged>",
                        bearing_azimuth_deg_from_north=az,
                        distance_ft=100,
                    ),
                )
                for i, az in enumerate((90, 180, 270, 0), 1)
            ),
        )
    )
    return StandaloneWebMapInput(
        title="Standalone evidence",
        plots=(plot,),
        scenes=(
            PlotScene(
                id="grid", name="Supplied grid", kind="projected", crs="EPSG:3857", units="m"
            ),
        ),
        placements=(
            PlotPlacement(
                id="supplied-anchor",
                calculation_id="boundary",
                geometry_hash=plot.geometry.geometry_hash,
                scene_id="grid",
                translation=(-8236050, 4975300),
                rationale="Synthetic supplied control for test",
                position_evidence=("Synthetic control",),
                orientation_evidence=("Synthetic grid rotation",),
            ),
        ),
    )


def run_map(tmp_path, data=None):
    source = tmp_path / "input.json"
    source.write_text(json.dumps(data or source_input().model_dump(mode="json"), indent=3) + "\n")
    output = tmp_path / "map"
    result = render_map_file(source, output, online_map=WebMapRequest(scene_id="grid"))
    return result, source, output


def test_standalone_stages_exact_source_and_honest_offline_fallback(tmp_path):
    result, source, output = run_map(tmp_path)
    assert result["status"] == "needs_review", result
    assert result["online_map_availability"] == "ready"
    for key in ("source_review_complete", "engine_verified", "verified_export_eligible"):
        assert result[key] is False
    assert (output / "source-map.json").read_bytes() == source.read_bytes()
    assert not (output / "source.json").exists()
    assert not (output / "dashboard.html").exists()
    assert not (output / "stage-manifest.json").exists()
    assert "map-evidence.html" in (output / "online-map.html").read_text()
    assert "Original course 1" in (output / "map-evidence.html").read_text()
    manifest = json.loads((output / "web-map-manifest.json").read_text())
    assert manifest["source_kind"] == "standalone"
    assert manifest["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert set(manifest["files"]) == {"online-map.html", "map-evidence.html"}
    for name, digest in manifest["files"].items():
        assert digest == hashlib.sha256((output / name).read_bytes()).hexdigest()
    artifact = json.loads((output / "web-map.json").read_text())
    request = json.loads((output / "web-map-request.json").read_text())
    assert manifest["artifact_sha256"] == _hash(artifact)
    assert manifest["request_sha256"] == _hash(request)
    assert manifest["input_hashes"] == dict(artifact["input_hashes"])


def test_standalone_missing_placement_preserves_local_plot_and_reports_omission(tmp_path):
    data = source_input().model_dump(mode="json")
    data["placements"] = []
    result, _, output = run_map(tmp_path, data)
    assert result["status"] == "needs_review", result
    assert result["online_map_availability"] == "unavailable"
    artifact = json.loads((output / "web-map.json").read_text())
    assert not artifact["features"]
    assert artifact["bounds"] is None
    assert artifact["unavailable"][0]["code"] == "missing_placement"
    assert "Original course 1" in (output / "map-evidence.html").read_text()


@pytest.mark.parametrize("mutation", ["plot", "placement", "secret"])
def test_invalid_standalone_rejected_before_creating_output_without_echo(tmp_path, mutation):
    data = source_input().model_dump(mode="json")
    if mutation == "plot":
        data["plots"][0]["geometry"]["area_sq_ft"] = 123
    elif mutation == "placement":
        data["placements"][0]["geometry_hash"] = "a" * 64
    else:
        data["token"] = "sk.sensitive-sentinel"
    result, _, output = run_map(tmp_path, data)
    assert result["status"] == "error"
    assert result["artifacts"] == {}
    assert "sk.sensitive-sentinel" not in json.dumps(result)
    assert not output.exists()


def test_existing_output_refused_without_overwrite(tmp_path):
    result, source, output = run_map(tmp_path)
    assert result["status"] == "needs_review", result
    before = {p.name: p.read_bytes() for p in output.iterdir() if p.is_file()}
    rejected = render_map_file(source, output, online_map=WebMapRequest(scene_id="grid"))
    assert rejected["status"] == "error"
    assert before == {p.name: p.read_bytes() for p in output.iterdir() if p.is_file()}
