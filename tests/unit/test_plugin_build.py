"""Distribution regressions for the plugin's independent runtime."""

import importlib.util
import tomllib
from pathlib import Path


def load_builder():
    path = Path(__file__).resolve().parents[2] / "scripts/build_claude_plugin.py"
    spec = importlib.util.spec_from_file_location("plugin_builder", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_links_every_local_wheel_as_direct_dependency():
    builder = load_builder()
    wheels = [Path(name.replace("-", "_") + "-1.0.0-py3-none-any.whl") for name in builder.PACKAGES]
    project = tomllib.loads(builder.runtime_project(wheels))
    dependencies = project["project"]["dependencies"]
    for name in builder.PACKAGES:
        assert f"{name}==1.0.0" in dependencies
        assert name in project["tool"]["uv"]["sources"]
    assert not any("ocr" in dependency or "openai" in dependency for dependency in dependencies)


def test_build_cache_is_absolute_when_subprocess_changes_directory(monkeypatch, tmp_path):
    builder = load_builder()
    monkeypatch.setenv("UV_CACHE_DIR", ".uv-cache")
    calls = []
    monkeypatch.setattr(builder.subprocess, "run", lambda *args, **kwargs: calls.append(kwargs))
    builder.run(["uv", "lock"], cwd=tmp_path)
    assert Path(calls[0]["env"]["UV_CACHE_DIR"]).is_absolute()
    assert calls[0]["env"]["UV_CACHE_DIR"] != str(tmp_path / ".uv-cache")
