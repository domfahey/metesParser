"""Packaged launchers forward composition through their validated locked runtime."""

import importlib.util
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("command", ["compose-map", "compose-dashboard"])
def test_launcher_forwards_composition_without_arbitrary_python(
    tmp_path, monkeypatch, command, capsys
):
    path = Path(__file__).resolve().parents[2] / "plugins/metesparser/scripts/run-review.py"
    spec = importlib.util.spec_from_file_location("compose_launcher", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    for name in ("pyproject.toml", "uv.lock"):
        (runtime / name).write_text("test")
    monkeypatch.setattr(module, "RUNTIME", runtime)
    monkeypatch.setattr(module, "validate_runtime", lambda _: ("a" * 64, None))
    monkeypatch.setattr(module.shutil, "which", lambda _: "/fake/uv")
    captured = []

    def run(args, **kwargs):
        captured.append(args)
        return subprocess.CompletedProcess(args, 1, '{"status":"needs_review"}\n', "")

    monkeypatch.setattr(module.subprocess, "run", run)
    arguments = [command, "source", "--layer", "layer.json", "--output-dir", "new"]
    assert module.main(arguments) == 1
    call = captured[0]
    assert call[:8] == [
        "/fake/uv",
        "run",
        "--project",
        str(runtime),
        "--locked",
        "--",
        "python",
        "-m",
    ]
    assert call[8 : 8 + len(arguments) + 1] == ["mp_review", *arguments]
    assert module.main(["python", "-c", "print('unsupported')"]) == 2
    assert len(captured) == 1
