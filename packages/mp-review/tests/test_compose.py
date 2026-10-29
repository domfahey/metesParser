"""Deterministic artifact composition retains evidence and validates render handoffs."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from mp_models.dashboard import DashboardBundle
from mp_models.webmap import WebMapRequest
from mp_review.dashboard import dashboard_file
from mp_review.online_map import render_map_file
from mp_review.plot import plot_file

FIXTURES = Path(__file__).parent / "fixtures"


def write(path, value):
    path.write_text(json.dumps(value))
    return path


def layer(tmp_path):
    return write(
        tmp_path / "layer.json",
        {
            "schema_version": "1.1",
            "scenes": [
                {
                    "id": "grid",
                    "name": "Supplied grid",
                    "kind": "projected",
                    "crs": "EPSG:3857",
                    "units": "m",
                }
            ],
            "operation": {"purpose": "retained preparation provenance"},
        },
    )


def plot(tmp_path, relative=False):
    if relative:
        source = (
            Path(__file__).resolve().parents[3]
            / "plugins/metesparser/skills/deed-closure-dashboard/references/relative-rectangle.json"
        )
    else:
        source = write(
            tmp_path / "calls.json",
            [
                {
                    "course": 1,
                    "direction_text": "  East 100 feet  ",
                    "bearing_azimuth_deg_from_north": 90,
                    "distance_ft": 100,
                    "along": "  Original line  ",
                }
            ],
        )
    output = tmp_path / "plot"
    result = plot_file(source, output, input_format="relative" if relative else "calls")
    assert result["status"] == "needs_review", result
    return output


def compose(command, source, output, *layers):
    args = [sys.executable, "-m", "mp_review", command, str(source), "--output-dir", str(output)]
    for path in layers:
        args.extend(["--layer", str(path)])
    completed = subprocess.run(args, capture_output=True, text=True, check=False)
    assert len(completed.stdout.splitlines()) == 1, completed.stderr
    return completed.returncode, json.loads(completed.stdout)


@pytest.mark.parametrize("relative", [False, True])
def test_compose_map_preserves_plot_and_prepared_layer_and_hands_off_to_render(tmp_path, relative):
    source = plot(tmp_path, relative)
    prepared_layer = layer(tmp_path)
    output = tmp_path / "composed"
    code, result = compose("compose-map", source, output, prepared_layer)
    assert code == 1, result
    assert result["status"] == "needs_review"
    assert all(
        result[key] is False
        for key in ("engine_verified", "verified_export_eligible", "source_review_complete")
    )
    value = json.loads((output / "map-input.json").read_text())
    request = json.loads((source / "plot-input.json").read_text())
    assert value["plots"][0]["request"] == request
    assert value["placements"] == []
    assert result["geometry_hashes"] == {
        request["calculation_id"]: value["plots"][0]["geometry"]["geometry_hash"]
    }
    assert (output / "inputs/plot/plot-manifest.json").read_bytes() == (
        source / "plot-manifest.json"
    ).read_bytes()
    assert (output / "inputs/layer-1.json").read_bytes() == prepared_layer.read_bytes()
    assert not (output / "dashboard.html").exists()
    rendered = render_map_file(
        output / "map-input.json", tmp_path / "rendered", online_map=WebMapRequest(scene_id="grid")
    )
    assert rendered["status"] == "needs_review", rendered


@pytest.mark.parametrize("kind", ["absolute", "relative"])
def test_compose_dashboard_retains_source_ledger_and_hands_off_to_render(tmp_path, kind):
    source = FIXTURES / f"dashboard-{kind}.json"
    original = DashboardBundle.model_validate_json(source.read_bytes()).model_dump(mode="json")
    output = tmp_path / "composed"
    code, result = compose("compose-dashboard", source, output, layer(tmp_path))
    assert code == 1, result
    value = json.loads((output / "bundle.json").read_text())
    for key in ("calls", "occurrences", "calculations", "pages"):
        assert value[key] == original[key]
    assert value["schema_version"] == "1.1"
    assert result["geometry_hashes"]
    assert (output / "inputs/base-bundle.json").read_bytes() == source.read_bytes()
    assert dashboard_file(output / "bundle.json", tmp_path / "rendered")["status"] == "needs_review"


@pytest.mark.parametrize(
    "damage", ["geometry", "input_hash", "source", "manifest", "duplicate_json"]
)
def test_compose_map_rejects_damaged_plot_before_creating_output(tmp_path, damage):
    source = plot(tmp_path)
    if damage == "geometry":
        path = source / "plot-geometry.json"
        value = json.loads(path.read_text())
        value["geometry_hash"] = "0" * 64
        write(path, value)
    elif damage in {"input_hash", "manifest"}:
        path = source / "plot-manifest.json"
        value = json.loads(path.read_text())
        value["input_hash" if damage == "input_hash" else "geometry_hash"] = "0" * 64
        write(path, value)
    elif damage == "source":
        (source / "source.json").write_text("[]")
    else:
        (source / "plot-input.json").write_text('{"title": "a", "title": "b"}')
    output = tmp_path / "composed"
    code, result = compose("compose-map", source, output, layer(tmp_path))
    assert code == 2 and result["status"] == "error"
    assert not output.exists()


@pytest.mark.parametrize("command", ["compose-map", "compose-dashboard"])
@pytest.mark.parametrize(
    "damage", ["collision", "malformed_layer", "malformed_source", "existing_output", "symlink"]
)
def test_composition_rejects_malformed_colliding_or_existing_inputs(tmp_path, command, damage):
    source = plot(tmp_path) if command == "compose-map" else FIXTURES / "dashboard-absolute.json"
    prepared_layer = layer(tmp_path)
    output = tmp_path / "composed"
    layers = [prepared_layer]
    if damage == "collision":
        layers.append(prepared_layer)
    elif damage == "malformed_layer":
        write(prepared_layer, {"scenes": "grid"})
    elif damage == "malformed_source":
        source = write(tmp_path / "invalid.json", {"unexpected": True})
    elif damage == "symlink":
        output.symlink_to(tmp_path / "absent", target_is_directory=True)
    else:
        output.mkdir()
        (output / "keep").write_text("preserved")
    code, result = compose(command, source, output, *layers)
    assert code == 2 and result["status"] == "error", result
    if damage == "existing_output":
        assert (output / "keep").read_text() == "preserved"
    else:
        assert not output.exists()


def test_compose_dashboard_rejects_stale_placement(tmp_path):
    value = json.loads((FIXTURES / "dashboard-absolute.json").read_text())
    value.update(schema_version="1.1", scenes=json.loads(layer(tmp_path).read_text())["scenes"])
    value["placements"] = [
        {
            "id": "placement",
            "calculation_id": value["calculations"][0]["id"],
            "geometry_hash": "0" * 64,
            "scene_id": "grid",
            "rationale": "Supplied evidence",
        }
    ]
    source = write(tmp_path / "stale.json", value)
    code, result = compose("compose-dashboard", source, tmp_path / "composed")
    assert code == 2 and result["status"] == "error"
    assert not (tmp_path / "composed").exists()


def test_composition_reuses_imported_map_provenance_without_reimport_or_render(
    tmp_path, monkeypatch
):
    from mp_models.webmap import StandaloneWebMapInput
    from mp_review import overlays
    from mp_review.compose import compose_map_file

    original = b'{"type":"Feature","id":"parcel","geometry":{"type":"Polygon","coordinates":[[[0,0],[0.01,0],[0.01,0.01],[0,0]]]},"properties":{}}'
    prepared_layer = overlays.import_overlay(
        original, input_format="geojson", target_crs="EPSG:3857"
    ).to_dict()
    imported = write(tmp_path / "imported.json", prepared_layer)
    source = plot(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("composition must reuse preparation without imports or rendering")

    monkeypatch.setattr(overlays, "import_overlay", forbidden)
    import mp_export.dashboard_html
    import mp_export.plot_html

    monkeypatch.setattr(mp_export.plot_html, "render_plot", forbidden)
    monkeypatch.setattr(mp_export.dashboard_html, "render_dashboard", forbidden)
    output = tmp_path / "composed"
    result = compose_map_file(source, output, layers=[imported])
    assert result["status"] == "needs_review", result
    value = StandaloneWebMapInput.model_validate_json((output / "map-input.json").read_bytes())
    assert value.map_sources[0].model_dump(mode="json") == prepared_layer["map_sources"][0]
    assert value.vector_layers[0].model_dump(mode="json") == prepared_layer["vector_layers"][0]
    assert (output / "inputs/layer-1.json").read_bytes() == imported.read_bytes()


def test_composition_recomputes_geometry_even_when_manifest_digests_are_updated(tmp_path):
    import hashlib

    source = plot(tmp_path)
    geometry_path = source / "plot-geometry.json"
    value = json.loads(geometry_path.read_text())
    value["geometry_hash"] = "0" * 64
    write(geometry_path, value)
    path = source / "plot-manifest.json"
    manifest = json.loads(path.read_text())
    manifest["geometry_hash"] = "0" * 64
    manifest["plot_geometry_sha256"] = hashlib.sha256(geometry_path.read_bytes()).hexdigest()
    write(path, manifest)
    code, result = compose("compose-map", source, tmp_path / "composed", layer(tmp_path))
    assert code == 2 and result["status"] == "error"
    assert not (tmp_path / "composed").exists()


def test_dashboard_composition_without_layers_recomputes_own_hashes(tmp_path):
    from mp_models.dashboard import DashboardBundle
    from mp_review.dashboard import prepare_dashboard

    source = FIXTURES / "dashboard-relative.json"
    code, result = compose("compose-dashboard", source, tmp_path / "composed")
    assert code == 1, result
    fresh = prepare_dashboard(DashboardBundle.model_validate_json(source.read_bytes()))
    assert result["geometry_hashes"] == {
        g.calculation_id: g.geometry_hash for g in fresh.plots.geometries
    }


@pytest.mark.parametrize("command", ["compose-map", "compose-dashboard"])
def test_composition_honors_disabled_settings_before_input_access(tmp_path, command):
    settings = tmp_path / "settings.md"
    settings.write_text("---\nenabled: false\n---\n")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "mp_review",
            command,
            str(tmp_path / "missing"),
            "--output-dir",
            str(tmp_path / "composed"),
            "--settings",
            str(settings),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["errors"][0]["code"] == "plugin_disabled"
    assert not (tmp_path / "composed").exists()


def test_text_plot_composes_map_with_verbatim_source_txt(tmp_path):
    source = tmp_path / "supplied-description.txt"
    original = "  Beginning at an iron pin; thence N 45° E 100 feet to a stone.  \n"
    source.write_text(original, encoding="utf-8")
    plotted = tmp_path / "text-plot"
    plot_result = plot_file(source, plotted, input_format="text")
    assert plot_result["status"] == "needs_review", plot_result
    assert (plotted / "source.txt").read_text(encoding="utf-8") == original
    output = tmp_path / "composed"
    code, result = compose("compose-map", plotted, output, layer(tmp_path))
    assert code == 1, result
    assert (output / "inputs/plot/source.txt").read_bytes() == source.read_bytes()
    value = json.loads((output / "map-input.json").read_text())
    assert value["plots"][0]["request"] == json.loads((plotted / "plot-input.json").read_text())
    assert value["plots"][0]["request"]["calls"][0]["quote"]
    assert (
        render_map_file(
            output / "map-input.json",
            tmp_path / "rendered",
            online_map=WebMapRequest(scene_id="grid"),
        )["status"]
        == "needs_review"
    )
