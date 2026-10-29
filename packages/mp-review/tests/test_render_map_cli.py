"""The standalone map command validates config, forwards inputs, and retains review status."""

import json
import sys
import types

import pytest
from mp_models.webmap import WebMapRequest
from mp_review import cli


def invoke(monkeypatch, capsys, *args):
    monkeypatch.setattr(sys, "argv", ["metes-review", "render-map", *map(str, args)])
    with pytest.raises(SystemExit) as exited:
        cli.main()
    captured = capsys.readouterr()
    return exited.value.code, captured


def test_render_map_requires_config_before_writing(monkeypatch, capsys, tmp_path):
    output = tmp_path / "new"
    code, captured = invoke(monkeypatch, capsys, tmp_path / "missing.json", "--output-dir", output)
    assert code == 2
    assert "--online-map-config" in captured.err
    assert not output.exists()


@pytest.mark.parametrize(
    "contents",
    [
        '{"scene_id":"grid","token":"pk.PRIVATE_DONT_ECHO"}',
        "[]",
        "{broken",
        '{"scene_id":"pk.PRIVATE_DONT_ECHO","display":{"max_depth":0}}',
    ],
)
def test_render_map_rejects_bad_config_without_echo(monkeypatch, capsys, tmp_path, contents):
    config = tmp_path / "request.json"
    config.write_text(contents)
    output = tmp_path / "new"
    code, captured = invoke(
        monkeypatch,
        capsys,
        tmp_path / "input.json",
        "--online-map-config",
        config,
        "--output-dir",
        output,
    )
    assert code == 2
    assert json.loads(captured.out)["errors"][0]["code"] == "invalid_online_map_config"
    assert "PRIVATE_DONT_ECHO" not in captured.out + captured.err
    assert not output.exists()


def test_render_map_config_read_failure_is_safe(monkeypatch, capsys, tmp_path):
    code, captured = invoke(
        monkeypatch,
        capsys,
        tmp_path / "input.json",
        "--online-map-config",
        tmp_path / "absent.json",
        "--output-dir",
        tmp_path / "new",
    )
    assert code == 2
    assert json.loads(captured.out)["errors"][0]["code"] == "invalid_online_map_config"


@pytest.mark.parametrize("status,expected", [("needs_review", 1), ("error", 2)])
def test_render_map_forwards_request_and_preserves_review_exit(
    monkeypatch, capsys, tmp_path, status, expected
):
    calls = []
    result = {"schema_version": "1.0", "status": status, "artifacts": {}, "errors": []}

    def render(path, output_dir, *, online_map):
        calls.append((path, output_dir, online_map))
        return result

    monkeypatch.setitem(
        sys.modules, "mp_review.online_map", types.SimpleNamespace(render_map_file=render)
    )
    config = tmp_path / "request.json"
    config.write_text('{"scene_id":"grid","view":{"style":"standard-satellite"}}')
    source, output = tmp_path / "input.json", tmp_path / "new"
    code, captured = invoke(
        monkeypatch, capsys, source, "--online-map-config", config, "--output-dir", output
    )
    assert code == expected
    assert json.loads(captured.out) == result
    assert len(captured.out.splitlines()) == 1
    assert calls == [(source, output, WebMapRequest.model_validate_json(config.read_text()))]


def test_render_map_disabled_settings_precede_input_and_config(monkeypatch, capsys, tmp_path):
    settings = tmp_path / "settings.md"
    settings.write_text("---\nenabled: false\n---\n")
    code, captured = invoke(
        monkeypatch,
        capsys,
        tmp_path / "absent.json",
        "--online-map-config",
        tmp_path / "absent-config.json",
        "--output-dir",
        tmp_path / "new",
        "--settings",
        settings,
    )
    assert code == 2
    assert json.loads(captured.out)["errors"][0]["code"] == "plugin_disabled"
