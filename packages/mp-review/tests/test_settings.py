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


def test_read_settings_defaults_empty_frontmatter_and_project_root_resolution(tmp_path):
    from mp_review.settings import output_path, read_settings

    assert read_settings(None) == {"enabled": True}
    assert read_settings(tmp_path / "missing.md") == {"enabled": True}

    empty_fm = tmp_path / "empty.md"
    empty_fm.write_text("---\n---\nBody only\n", encoding="utf-8")
    assert read_settings(empty_fm) == {"enabled": True}

    # Settings directly inside project dir (not inside .claude) resolve relative to its parent.
    direct = tmp_path / "local.md"
    direct.write_text("---\noutput_dir: sub/out\n---\n", encoding="utf-8")
    parsed_direct = read_settings(direct)
    assert parsed_direct == {"enabled": True, "output_dir": (tmp_path / "sub/out").resolve()}

    # Settings inside .claude/ resolve relative to the owning project root (parent of .claude).
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    in_claude = claude_dir / "metesparser.local.md"
    in_claude.write_text("---\nenabled: true\noutput_dir: review-out\n---\n", encoding="utf-8")
    parsed_claude = read_settings(in_claude)
    assert parsed_claude["output_dir"] == (tmp_path / "review-out").resolve()

    # output_path creates unique review-<hex> children when no explicit path is provided.
    first = output_path(parsed_claude, None)
    second = output_path(parsed_claude, None)
    assert first.parent == parsed_claude["output_dir"]
    assert first.name.startswith("review-") and len(first.name) == len("review-") + 32
    assert first != second
    explicit = tmp_path / "explicit"
    assert output_path(parsed_claude, explicit) == explicit


@pytest.mark.parametrize(
    ("content", "match"),
    [
        ("no frontmatter", "frontmatter"),
        ("---\nenabled: true\n", "Invalid settings"),
        ("---\n- not-a-mapping\n---\n", "mapping"),
        ("---\n1: true\n---\n", "unique strings"),
        ("---\nenabled: true\nenabled: false\n---\n", "unique strings"),
        ("---\nunknown_key: 1\n---\n", "Unsupported settings"),
        ("---\nenabled: 1\n---\n", "YAML boolean"),
        ('---\nenabled: "true"\n---\n', "YAML boolean"),
        ('---\noutput_dir: ""\n---\n', "non-empty project-relative"),
        ('---\noutput_dir: "   "\n---\n', "non-empty project-relative"),
        ("---\noutput_dir: /etc/passwd\n---\n", "non-empty project-relative"),
        ("---\noutput_dir: ../outside\n---\n", "within the project directory"),
    ],
)
def test_read_settings_validation_and_traversal_errors(tmp_path, content, match):
    from mp_review.settings import SettingsError, read_settings

    settings_file = tmp_path / ".claude/metesparser.local.md"
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(content, encoding="utf-8")
    with pytest.raises(SettingsError, match=match):
        read_settings(settings_file)


def test_read_settings_rejects_symlink_escape_unreadable_file_and_missing_output_dir(tmp_path):
    from mp_review.settings import SettingsError, output_path, read_settings

    outside = tmp_path / "outside"
    outside.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    escape = project / "link"
    escape.symlink_to(outside, target_is_directory=True)
    settings_file = project / ".claude/metesparser.local.md"
    settings_file.parent.mkdir()
    settings_file.write_text("---\noutput_dir: link/sub\n---\n", encoding="utf-8")
    with pytest.raises(SettingsError, match="within the project directory"):
        read_settings(settings_file)

    # Passing a directory triggers OSError -> wrapped SettingsError
    with pytest.raises(SettingsError, match="Invalid settings"):
        read_settings(project)

    # output_path without explicit dir or configured output_dir fails closed
    with pytest.raises(SettingsError, match="--output-dir"):
        output_path({"enabled": True}, None)
