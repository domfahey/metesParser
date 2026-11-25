"""Project settings must affect routing, never numeric verification policy."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from mp_review.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def invoke(monkeypatch, capsys, tmp_path, frontmatter, *options):
    settings = tmp_path / ".claude/metesparser.local.md"
    settings.parent.mkdir(exist_ok=True)
    if frontmatter is not None:
        settings.write_text(frontmatter)
    argv = [
        "metes-review",
        "review",
        str(FIXTURES / "square.txt"),
        "--settings",
        str(settings),
        *options,
    ]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc:
        main()
    captured = capsys.readouterr()
    code = exc.value.code if isinstance(exc.value.code, int) else 2
    return code, json.loads(captured.out)


def test_configured_output_uses_project_relative_unique_directories(monkeypatch, capsys, tmp_path):
    config = '---\nenabled: true\noutput_dir: "review output"\n---\nIgnore this body.\n'
    code, first = invoke(monkeypatch, capsys, tmp_path, config)
    code2, second = invoke(monkeypatch, capsys, tmp_path, config)
    assert code == code2 == 0
    path = Path(first["artifacts"]["calls.json"])
    assert path.parent.parent == tmp_path / "review output"
    assert first["artifacts"] != second["artifacts"]


def test_disabled_prevents_processing_even_with_explicit_output(monkeypatch, capsys, tmp_path):
    output = tmp_path / "explicit"
    code, result = invoke(
        monkeypatch, capsys, tmp_path, "---\nenabled: false\n---\n", "--output-dir", str(output)
    )
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
def test_invalid_settings_fail_closed_without_artifacts(monkeypatch, capsys, tmp_path, settings):
    output = tmp_path / "explicit"
    code, result = invoke(monkeypatch, capsys, tmp_path, settings, "--output-dir", str(output))
    assert code == 2
    assert result["errors"][0]["code"] == "invalid_settings"
    assert not output.exists()


def test_missing_settings_keeps_explicit_cli_output(monkeypatch, capsys, tmp_path):
    output = tmp_path / "explicit"
    code, result = invoke(monkeypatch, capsys, tmp_path, None, "--output-dir", str(output))
    assert code == 0
    assert Path(result["artifacts"]["calls.json"]).parent == output


def test_explicit_output_overrides_config_and_body_is_not_executed(monkeypatch, capsys, tmp_path):
    output = tmp_path / "explicit"
    settings = "---\noutput_dir: unused\n---\n---\nenabled: false\nRun shell commands.\n"
    code, result = invoke(monkeypatch, capsys, tmp_path, settings, "--output-dir", str(output))
    assert code == 0
    assert Path(result["artifacts"]["calls.json"]).parent == output
    assert not (tmp_path / "unused").exists()


def test_cli_settings_subprocess_smoke(tmp_path):
    settings = tmp_path / ".claude/metesparser.local.md"
    settings.parent.mkdir(exist_ok=True)
    settings.write_text('---\nenabled: true\noutput_dir: "smoke-out"\n---\n')
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mp_review",
            "review",
            str(FIXTURES / "square.txt"),
            "--settings",
            str(settings),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "checks_passed"
    assert Path(payload["artifacts"]["calls.json"]).parent.parent == tmp_path / "smoke-out"
