"""Dashboard CLI retains review-only status and preserves source artifacts."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "mp_review", "dashboard", *map(str, args)],
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize("fixture", ["dashboard-absolute.json", "dashboard-relative.json"])
def test_dashboard_cli_keeps_review_status_and_original_source(tmp_path, fixture):
    source = FIXTURES / fixture
    output = tmp_path / "result"
    completed = run_cli(source, "--output-dir", output, "--cache-dir", tmp_path / "cache")
    assert completed.returncode == 1, completed.stderr
    assert len(completed.stdout.splitlines()) == 1
    result = json.loads(completed.stdout)
    assert result["status"] == "needs_review"
    assert result["verified_export_eligible"] is False
    assert result["errors"] == []
    assert (output / "source.json").read_bytes() == source.read_bytes()
    assert result["input"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert "<!doctype html>" in (output / "dashboard.html").read_text()
    assert not list(output.glob("*.csv"))
    again = run_cli(source, "--output-dir", tmp_path / "warm", "--cache-dir", tmp_path / "cache")
    assert again.returncode == 1, again.stderr
    assert json.loads(again.stdout)["cache_reused"] is True
    assert (output / "dashboard.html").read_bytes() == (
        tmp_path / "warm/dashboard.html"
    ).read_bytes()


def test_dashboard_cli_honors_disabled_setting_without_creating_output(tmp_path):
    settings = tmp_path / "settings.md"
    settings.write_text("---\nenabled: false\n---\n")
    output = tmp_path / "result"
    completed = run_cli(tmp_path / "missing.json", "--settings", settings, "--output-dir", output)
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["errors"][0]["code"] == "plugin_disabled"
    assert not output.exists()


def test_dashboard_cli_refuses_existing_output_and_malformed_json(tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    sentinel = output / "dashboard.html"
    sentinel.write_text("preserve me")
    completed = run_cli(FIXTURES / "dashboard-absolute.json", "--output-dir", output)
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["status"] == "error"
    assert sentinel.read_text() == "preserve me"
    bad = tmp_path / "bad.json"
    bad.write_text('{"title":"first","title":"duplicate"}')
    completed = run_cli(bad, "--output-dir", tmp_path / "bad-output")
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["status"] == "error"


def test_dashboard_cli_uses_configured_output_root(tmp_path):
    config = tmp_path / ".claude"
    config.mkdir()
    settings = config / "metesparser.local.md"
    settings.write_text("---\noutput_dir: reviews\n---\n")
    completed = run_cli(FIXTURES / "dashboard-absolute.json", "--settings", settings)
    assert completed.returncode == 1, completed.stderr
    assert len(list((tmp_path / "reviews").glob("review-*/dashboard.html"))) == 1
