"""Project settings must affect routing, never numeric verification policy."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def invoke(tmp_path, frontmatter, *options):
    settings = tmp_path / ".claude/metesparser.local.md"
    settings.parent.mkdir(exist_ok=True)
    if frontmatter is not None:
        settings.write_text(frontmatter)
    command = [
        sys.executable,
        "-m",
        "mp_review",
        "review",
        str(FIXTURES / "square.txt"),
        "--settings",
        str(settings),
        *options,
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    return result.returncode, json.loads(result.stdout)


def test_configured_output_uses_project_relative_unique_directories(tmp_path):
    config = '---\nenabled: true\noutput_dir: "review output"\n---\nIgnore this body.\n'
    code, first = invoke(tmp_path, config)
    code2, second = invoke(tmp_path, config)
    assert code == code2 == 0
    path = Path(first["artifacts"]["calls.json"])
    assert path.parent.parent == tmp_path / "review output"
    assert first["artifacts"] != second["artifacts"]


def test_disabled_prevents_processing_even_with_explicit_output(tmp_path):
    output = tmp_path / "explicit"
    code, result = invoke(tmp_path, "---\nenabled: false\n---\n", "--output-dir", str(output))
    assert code == 2
    assert result["errors"][0]["code"] == "plugin_disabled"
    assert not output.exists()


@pytest.mark.parametrize(
    "settings",
    [
        '---\nenabled: "false"\n---\n',
        "---\nclosure_tolerance: 100\n---\n",
        "---\noutput_dir: ../escape\n---\n",
        "---\nenabled: true\nenabled: false\n---\n",
        "---\noutput_dir: [x]\n---\n",
        "---\nenabled: true\n",
        "enabled: true",
        "---\nenabled: !!python/object:builtins.object {}\n---\n",
    ],
)
def test_invalid_settings_fail_closed_without_artifacts(tmp_path, settings):
    output = tmp_path / "explicit"
    code, result = invoke(tmp_path, settings, "--output-dir", str(output))
    assert code == 2
    assert result["errors"][0]["code"] == "invalid_settings"
    assert not output.exists()


def test_missing_settings_keeps_explicit_cli_output(tmp_path):
    output = tmp_path / "explicit"
    code, result = invoke(tmp_path, None, "--output-dir", str(output))
    assert code == 0
    assert Path(result["artifacts"]["calls.json"]).parent == output


def test_explicit_output_overrides_config_and_body_is_not_executed(tmp_path):
    output = tmp_path / "explicit"
    settings = "---\noutput_dir: unused\n---\n---\nenabled: false\nRun shell commands.\n"
    code, result = invoke(tmp_path, settings, "--output-dir", str(output))
    assert code == 0
    assert Path(result["artifacts"]["calls.json"]).parent == output
    assert not (tmp_path / "unused").exists()
