"""Deeply nested JSON in any command's non-positional JSON input is invalid_input_json (exit 2)."""

import json
from pathlib import Path

import pytest
from mp_review import cli

BUNDLE = str(Path(__file__).parent / "fixtures/dashboard-absolute.json")
DEEP = "[" * 100000 + "]" * 100000

# Placeholders: D deep file, OK '{}' file, IMG image bytes, DIR_D directory holding deep files,
# OUT/OUT2 fresh paths.
CASES = {
    "import-overlay": ["import-overlay", "D", "--format", "geojson", "--target-crs", "EPSG:3857"]
    + ["--output", "OUT"],
    "register-raster-controls": ["register-raster", "IMG", "--controls", "D", "--output", "OUT"],
    "pick-raster-controls": ["pick-raster", "IMG", "--controls", "D", "--output-dir", "OUT"],
    "corpus-manifest": ["corpus", "D"],
    "render-map-config": ["render-map", "OK", "--online-map-config", "D", "--output-dir", "OUT"],
    "dashboard-config": ["dashboard", BUNDLE, "--online-map-config", "D", "--output-dir", "OUT"],
    "export-review-request": ["export-review", BUNDLE, "--revision-dir", "OUT2", "--request", "D"],
    "save-revision-revision": ["save-revision", BUNDLE, "--revision", "D", "--output-dir", "OUT"],
    "compose-map-layer": ["compose-map", "PLOT", "--layer", "D", "--output-dir", "OUT"],
    "compose-dashboard-layer": ["compose-dashboard", BUNDLE, "--layer", "D", "--output-dir", "OUT"],
    "validate-source-acquisition": ["validate-source", "DIR_D", "--acquisition", "D"],
    "validate-source-selection": ["validate-source", "DIR_D", "--selection", "D"],
    "validate-source-default-records": ["validate-source", "DIR_D"],
    "mapbox-mcp-manifest": ["mapbox-mcp", "DIR_D", "--output-dir", "OUT"],
    "serve-map-manifest": ["serve-map", "DIR_D"],
}


@pytest.mark.parametrize("case", CASES)
def test_deep_json_in_every_json_input_is_invalid_input_json(case, tmp_path, monkeypatch, capsys):
    deep = tmp_path / "deep.json"
    deep.write_text(DEEP)
    ok = tmp_path / "ok.json"
    ok.write_text("{}")
    image = tmp_path / "image.png"
    image.write_bytes(b"not an image")
    directory = tmp_path / "dir"
    directory.mkdir()
    names_deep = (
        "web-map-manifest.json",
        "revision.json",
        "source-acquisition.json",
        "description-selection.json",
    )
    for name in names_deep:
        (directory / name).write_text(DEEP)
    from mp_review.plot import plot_file

    calls = tmp_path / "calls.json"
    calls.write_text(
        json.dumps(
            [
                {
                    "course": 1,
                    "direction_text": "East",
                    "distance_ft": 100,
                    "bearing_azimuth_deg_from_north": 90,
                }
            ]
        )
    )
    plot_dir = tmp_path / "plot"
    plot_file(calls, output_dir=plot_dir)
    names = {
        "PLOT": plot_dir,
        "D": deep,
        "OK": ok,
        "IMG": image,
        "DIR_D": directory,
        "OUT": tmp_path / "out",
        "OUT2": tmp_path / "out2",
    }
    argv = [str(names.get(a, a)) for a in CASES[case]]
    monkeypatch.setattr("sys.argv", ["metes-review", *argv])
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    result = json.loads(capsys.readouterr().out)
    assert exit_info.value.code == 2, result
    assert result["errors"][0]["code"] == "invalid_input_json", result


def test_inspect_artifacts_reports_deep_json_without_internal_recursion(
    tmp_path, monkeypatch, capsys
):
    (tmp_path / "source.json").write_text(DEEP)
    argv = ["inspect-artifacts", str(tmp_path), "--requested-stage", "plot"]
    monkeypatch.setattr("sys.argv", ["metes-review", *argv])
    with pytest.raises(SystemExit):
        cli.main()
    assert "internal_recursion_error" not in capsys.readouterr().out
