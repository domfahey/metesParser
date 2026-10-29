"""Standalone plotting composes with existing artifacts and respects scope/settings."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from mp_export.csv_writer import calls_to_csv
from mp_models import DeedCall


def run_plot(*args):
    return subprocess.run(
        [sys.executable, "-m", "mp_review", "plot", *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
    )


def rectangle():
    return [
        DeedCall(
            course=i + 1,
            direction_text=direction,
            bearing_azimuth_deg_from_north=azimuth,
            distance_ft=distance,
        )
        for i, (direction, azimuth, distance) in enumerate(
            [("North", 0, 50), ("East", 90, 100), ("South", 180, 50), ("West", 270, 100)]
        )
    ]


@pytest.mark.parametrize("suffix", [".csv", ".json"])
def test_plot_existing_calls_preserves_input_and_has_no_dashboard_or_verified_export(
    tmp_path, suffix
):
    source = tmp_path / ("calls" + suffix)
    if suffix == ".csv":
        calls_to_csv(rectangle(), str(source))
    else:
        source.write_text(json.dumps([c.model_dump(mode="json") for c in rectangle()]))
    original = source.read_bytes()
    output = tmp_path / "plot"
    completed = run_plot(source, "--output-dir", output)
    assert completed.returncode == 1, completed.stderr
    result = json.loads(completed.stdout)
    assert len(completed.stdout.splitlines()) == 1
    assert result["status"] == "needs_review"
    assert result["verified_export_eligible"] is False
    assert result["errors"] == []
    assert result["input"]["sha256"] == hashlib.sha256(original).hexdigest()
    assert (output / ("source" + suffix)).read_bytes() == original
    assert source.read_bytes() == original
    geometry = json.loads((output / "plot-geometry.json").read_text())
    assert geometry["completeness"] == "complete"
    assert geometry["misclosure_ft"] < 1e-10
    assert geometry["perimeter_ft"] == pytest.approx(300)
    assert len(geometry["primitives"]) == 4
    assert (output / "plot.html").is_file()
    assert not (output / "dashboard.html").exists()
    assert not list(output.glob("*_verified.csv"))

    repeated = tmp_path / "repeated"
    reused = run_plot(
        output / "plot-input.json", "--input-format", "plot", "--output-dir", repeated
    )
    assert reused.returncode == 1, reused.stderr
    assert json.loads((repeated / "plot-geometry.json").read_text()) == geometry


def test_relative_plot_keeps_recorded_bearings_unknown(tmp_path):
    root = Path(__file__).resolve().parents[3]
    source = (
        root
        / "plugins/metesparser/skills/deed-closure-dashboard/references/relative-rectangle.json"
    )
    output = tmp_path / "relative"
    completed = run_plot(source, "--input-format", "relative", "--output-dir", output)
    assert completed.returncode == 1, completed.stderr
    request = json.loads((output / "plot-input.json").read_text())
    assert all(c["call"]["bearing_azimuth_deg_from_north"] is None for c in request["calls"])
    geometry = json.loads((output / "plot-geometry.json").read_text())
    assert geometry["completeness"] == "complete"
    assert geometry["misclosure_ft"] < 1e-10


def test_plot_honors_disabled_settings_before_reading_input(tmp_path):
    settings = tmp_path / "settings.md"
    settings.write_text("---\nenabled: false\n---\n")
    output = tmp_path / "plot"
    completed = run_plot(tmp_path / "missing.json", "--settings", settings, "--output-dir", output)
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["errors"][0]["code"] == "plugin_disabled"
    assert not output.exists()


def test_plot_uses_configured_fresh_output_directory(tmp_path):
    settings = tmp_path / ".claude/metesparser.local.md"
    settings.parent.mkdir()
    settings.write_text("---\noutput_dir: plots\n---\n")
    source = tmp_path / "calls.json"
    source.write_text(json.dumps([c.model_dump(mode="json") for c in rectangle()]))
    completed = run_plot(source, "--settings", settings)
    assert completed.returncode == 1, completed.stderr
    assert len(list((tmp_path / "plots").glob("review-*/plot.html"))) == 1


def test_plot_rejects_format_mismatch_and_keeps_existing_output(tmp_path):
    source = tmp_path / "calls.json"
    source.write_text(json.dumps([c.model_dump(mode="json") for c in rectangle()]))
    output = tmp_path / "existing"
    output.mkdir()
    sentinel = output / "plot.html"
    sentinel.write_text("Keep existing result")
    completed = run_plot(source, "--output-dir", output)
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["status"] == "error"
    assert sentinel.read_text() == "Keep existing result"
    completed = run_plot(source, "--input-format", "relative", "--output-dir", tmp_path / "wrong")
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["status"] == "error"
