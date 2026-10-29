import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "run-review.py"
SPEC = importlib.util.spec_from_file_location("metesparser_launcher", SCRIPT)
launcher = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(launcher)


def make_runtime(tmp_path: Path) -> Path:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    contents = {
        "pyproject.toml": b"[project]\n",
        "uv.lock": b"version = 1\n",
        "wheels/engine.whl": b"wheel",
    }
    hashes = {}
    for relative, data in contents.items():
        path = runtime / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        hashes[relative] = hashlib.sha256(data).hexdigest()
    fingerprint = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    (runtime / "engine.json").write_text(
        json.dumps({"fingerprint": fingerprint, "sha256": hashes}), encoding="utf-8"
    )
    return runtime


def setup_launcher(monkeypatch, runtime):
    monkeypatch.setattr(launcher, "RUNTIME", runtime)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/fake/uv")


def test_rejects_fingerprint_tampering_before_uv(monkeypatch, tmp_path, capsys):
    runtime = make_runtime(tmp_path)
    (runtime / "wheels/engine.whl").write_bytes(b"modified")
    setup_launcher(monkeypatch, runtime)
    monkeypatch.setattr(
        launcher.subprocess, "run", lambda *args, **kwargs: pytest.fail("uv must not run")
    )

    assert launcher.main(["review", "deed.txt"]) == 2
    response = json.loads(capsys.readouterr().out)
    assert response["status"] == "error"
    assert "hash mismatch" in response["errors"][0]["message"]


def test_bootstrap_failure_returns_structured_json(monkeypatch, tmp_path, capsys):
    runtime = make_runtime(tmp_path)
    setup_launcher(monkeypatch, runtime)
    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=2, stdout="", stderr="uv: locked sync failed"
        ),
    )

    assert launcher.main(["verify", "calls.csv"]) == 2
    response = json.loads(capsys.readouterr().out)
    assert response["status"] == "error"
    assert "locked sync failed" in response["errors"][0]["message"]


def test_preserves_engine_json_and_status(monkeypatch, tmp_path, capsys):
    runtime = make_runtime(tmp_path)
    setup_launcher(monkeypatch, runtime)
    engine_output = (
        json.dumps({"status": "needs_review", "errors": ["open traverse"], "artifacts": []}) + "\n"
    )
    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=engine_output, stderr=""),
    )

    assert launcher.main(["verify", "calls.csv"]) == 1
    assert capsys.readouterr().out == engine_output


def test_relative_analysis_reaches_engine_without_promoting_status(monkeypatch, tmp_path, capsys):
    runtime = make_runtime(tmp_path)
    setup_launcher(monkeypatch, runtime)
    commands = []
    engine_output = (
        json.dumps(
            {"status": "needs_review", "analysis": {"status": "analyzed", "engine_verified": False}}
        )
        + "\n"
    )

    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=1, stdout=engine_output, stderr="")

    monkeypatch.setattr(launcher.subprocess, "run", run)
    assert launcher.main(["analyze-relative", "angles.json"]) == 1
    assert commands[0][-4:-2] == ["analyze-relative", "angles.json"]
    assert capsys.readouterr().out == engine_output


def test_rejects_runtime_hash_map_path_escape(monkeypatch, tmp_path, capsys):
    runtime = make_runtime(tmp_path)
    metadata = json.loads((runtime / "engine.json").read_text())
    metadata["sha256"]["../outside"] = "0" * 64
    metadata["fingerprint"] = hashlib.sha256(
        json.dumps(metadata["sha256"], sort_keys=True).encode()
    ).hexdigest()
    (runtime / "engine.json").write_text(json.dumps(metadata))
    setup_launcher(monkeypatch, runtime)

    assert launcher.main(["review", "deed.txt"]) == 2
    response = json.loads(capsys.readouterr().out)
    assert "escapes runtime directory" in response["errors"][0]["message"]


@pytest.mark.parametrize("command", ["dashboard", "mapbox-mcp"])
def test_dashboard_reaches_engine_without_promoting_status(command, monkeypatch, tmp_path, capsys):
    setup_launcher(monkeypatch, make_runtime(tmp_path))
    commands = []
    engine_output = '{"status":"needs_review","artifacts":{"dashboard":"dashboard.html"}}\n'

    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=1, stdout=engine_output, stderr="")

    monkeypatch.setattr(launcher.subprocess, "run", run)
    assert launcher.main([command, "bundle.json", "--output-dir", "stages"]) == 1
    assert commands[0][-6:-2] == [command, "bundle.json", "--output-dir", "stages"]
    assert capsys.readouterr().out == engine_output


def test_validate_source_reaches_engine_and_preserves_advisory_status(
    monkeypatch, tmp_path, capsys
):
    setup_launcher(monkeypatch, make_runtime(tmp_path))
    commands = []
    engine_output = '{"status":"needs_review","operation":"validate-source"}\n'

    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=1, stdout=engine_output, stderr="")

    monkeypatch.setattr(launcher.subprocess, "run", run)
    arguments = ["validate-source", "bundle", "--acquisition", "record.json"]
    assert launcher.main(arguments) == 1
    assert commands[0][-len(arguments) - 2 : -2] == arguments
    assert capsys.readouterr().out == engine_output


def test_settings_come_from_calling_project_not_plugin_install(monkeypatch, tmp_path, capsys):
    runtime = make_runtime(tmp_path)
    setup_launcher(monkeypatch, runtime)
    project = tmp_path / "project with spaces"
    project.mkdir()
    monkeypatch.chdir(project)
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout='{"status":"checks_passed"}\n', stderr="")

    monkeypatch.setattr(launcher.subprocess, "run", run)
    assert launcher.main(["review", "deed.txt"]) == 0
    assert commands[0][-2:] == ["--settings", str(project / ".claude/metesparser.local.md")]
    commands.clear()
    assert launcher.main(["review", "deed.txt", "--settings=alternate.md"]) == 0
    assert commands[0][-1] == "--settings=alternate.md"


@pytest.mark.parametrize("command", ["import-overlay", "register-raster", "fetch-parcel"])
def test_overlay_commands_reach_locked_engine(command, monkeypatch, tmp_path, capsys):
    runtime = make_runtime(tmp_path)
    setup_launcher(monkeypatch, runtime)
    commands = []

    def run(arguments, **kwargs):
        commands.append(arguments)
        return SimpleNamespace(returncode=0, stdout='{"status":"passed"}\n', stderr="")

    monkeypatch.setattr(launcher.subprocess, "run", run)
    assert launcher.main([command, "input.json", "--output", "new.json"]) == 0
    assert command in commands[0]


def test_standalone_plot_reaches_engine_and_preserves_nonverification(
    monkeypatch, tmp_path, capsys
):
    setup_launcher(monkeypatch, make_runtime(tmp_path))
    commands = []
    output = '{"status":"needs_review","verified_export_eligible":false}\n'

    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=1, stdout=output, stderr="")

    monkeypatch.setattr(launcher.subprocess, "run", run)
    arguments = ["plot", "calls.csv", "--input-format", "calls", "--output-dir", "plot-new"]
    assert launcher.main(arguments) == 1
    assert commands[0][-8:-2] == arguments
    assert capsys.readouterr().out == output


def test_standalone_online_map_reaches_engine_with_inputs_and_config(
    monkeypatch, tmp_path, capsys
):
    setup_launcher(monkeypatch, make_runtime(tmp_path))
    commands = []
    output = '{"status":"needs_review","online_map_availability":"ready"}\n'

    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=1, stdout=output, stderr="")

    monkeypatch.setattr(launcher.subprocess, "run", run)
    arguments = [
        "render-map",
        "prepared-map.json",
        "--online-map-config",
        "online-config.json",
        "--output-dir",
        "viewer-new",
        "--settings",
        "settings.md",
    ]
    assert launcher.main(arguments) == 1
    assert commands[0][-len(arguments) :] == arguments
    assert capsys.readouterr().out == output


def test_preview_executes_foreground_without_output_capture(monkeypatch, tmp_path):
    setup_launcher(monkeypatch, make_runtime(tmp_path))
    seen = []
    monkeypatch.setattr(
        launcher.os,
        "execvpe",
        lambda executable, command, env: seen.append((executable, command, env)),
    )
    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("Preview must stream, not capture output"),
    )
    assert launcher.main(["serve-map", "map-output", "--port", "8766"]) == 0
    assert seen[0][0] == "/fake/uv"
    assert seen[0][1][-6:-2] == ["serve-map", "map-output", "--port", "8766"]
    assert "UV_PROJECT_ENVIRONMENT" in seen[0][2]


def test_preview_start_failure_is_structured(monkeypatch, tmp_path, capsys):
    setup_launcher(monkeypatch, make_runtime(tmp_path))

    def fail(*args):
        raise OSError("unavailable")

    monkeypatch.setattr(launcher.os, "execvpe", fail)
    assert launcher.main(["serve-map", "map-output"]) == 2
    assert json.loads(capsys.readouterr().out)["errors"][0]["code"] == "launcher_error"
