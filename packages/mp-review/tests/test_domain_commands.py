"""Published examples execute through the public advisory command boundary."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    "command,skill,manifest",
    [
        ("analyze-corridor", "plot-corridor", "corridor-manifest.json"),
        ("derive-plss", "plot-plss-reference", "plss-manifest.json"),
    ],
)
def test_domain_example_publishes_advisory_and_refuses_overwrite(
    command, skill, manifest, tmp_path
):
    source = ROOT / "plugins/metesparser/skills" / skill / "references/example.json"
    output = tmp_path / "output"
    args = [sys.executable, "-m", "mp_review", command, str(source), "--output-dir", str(output)]
    result = subprocess.run(args, text=True, capture_output=True, check=False)
    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "needs_review"
    assert payload["verified_export_eligible"] is False
    assert (output / manifest).is_file()
    assert (output / "request.json").read_bytes() == source.read_bytes()
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    retry = subprocess.run(args, text=True, capture_output=True, check=False)
    assert retry.returncode == 2
    assert {p.name: p.read_bytes() for p in output.iterdir()} == before
    assert not list(output.glob("*verified*"))


@pytest.mark.parametrize("command", ["analyze-corridor", "derive-plss"])
def test_domain_commands_honor_disabled_settings(command, tmp_path):
    settings = tmp_path / "settings.md"
    settings.write_text("---\nenabled: false\n---\n")
    result = subprocess.run(
        [sys.executable, "-m", "mp_review", command, "absent.json", "--settings", str(settings)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert json.loads(result.stdout)["errors"][0]["code"] == "plugin_disabled"
