"""Advisory routes respect shared settings without touching output directories."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "command,extra",
    [
        ("validate-source", []),
        ("inspect-artifacts", ["--requested-stage", "review"]),
        ("diagnose-closure", []),
        ("compare-descriptions", []),
    ],
)
def test_advisory_commands_honor_disabled_settings(command, extra, tmp_path):
    settings = tmp_path / "settings.md"
    settings.write_text("---\nenabled: false\n---\n")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mp_review",
            command,
            str(tmp_path),
            *extra,
            "--settings",
            str(settings),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    response = json.loads(result.stdout)
    assert response["errors"][0]["code"] == "plugin_disabled"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["settings.md"]


@pytest.mark.parametrize(
    "command,fixture",
    [
        ("diagnose-closure", "diagnostics/request.json"),
        ("compare-descriptions", "comparison-synthetic.json"),
    ],
)
def test_advisory_file_command_retains_exact_input_and_uses_exit_one(command, fixture, tmp_path):
    source = Path(__file__).parent / "fixtures" / fixture
    output = tmp_path / "result"
    result = subprocess.run(
        [sys.executable, "-m", "mp_review", command, str(source), "--output-dir", str(output)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1, result.stderr
    response = json.loads(result.stdout)
    assert response["status"] == "needs_review"
    retained = "comparison-request.json" if command == "compare-descriptions" else "request.json"
    assert (output / retained).read_bytes() == source.read_bytes()
    assert not list(output.glob("*verified*"))
    again = subprocess.run(
        [sys.executable, "-m", "mp_review", command, str(source), "--output-dir", str(output)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert again.returncode == 2
    assert json.loads(again.stdout)["status"] == "error"


@pytest.mark.parametrize(
    "command,extra",
    [
        ("validate-source", []),
        ("inspect-artifacts", ["--requested-stage", "extract"]),
    ],
)
def test_readonly_commands_ignore_configured_output_and_preserve_bundle(command, extra, tmp_path):
    bundle = tmp_path / "source"
    shutil.copytree(Path(__file__).parent / "fixtures/source_handoff", bundle)
    before = {p.relative_to(bundle): p.read_bytes() for p in bundle.rglob("*") if p.is_file()}
    settings = tmp_path / "settings.md"
    output = tmp_path / "must-not-exist"
    settings.write_text("---\noutput_dir: must-not-exist\n---\n")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mp_review",
            command,
            str(bundle),
            *extra,
            "--settings",
            str(settings),
        ],
        text=True,
        capture_output=True,
        check=False,
        cwd=tmp_path,
    )
    assert result.returncode == 1, result.stderr
    assert json.loads(result.stdout)["status"] == "needs_review"
    assert not output.exists()
    assert before == {
        p.relative_to(bundle): p.read_bytes() for p in bundle.rglob("*") if p.is_file()
    }
