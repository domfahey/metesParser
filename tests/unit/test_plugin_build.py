"""Distribution regressions for the plugin's independent runtime."""

import importlib.util
import json
import tomllib
import zipfile
from pathlib import Path

import pytest


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
        pyproject = tomllib.loads((builder.ROOT / "packages" / name / "pyproject.toml").read_text())
        assert f"{name}=={pyproject['project']['version']}" in dependencies
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


def test_geo_runtime_pins_optional_import_dependencies():
    builder = load_builder()
    project = tomllib.loads(builder.runtime_project([], geo=True))
    dependencies = project["project"]["dependencies"]
    assert any(d.startswith("pyproj==") for d in dependencies)
    assert any(d.startswith("pillow==") for d in dependencies)
    assert not any(d.startswith("playwright") for d in dependencies)
    basic = tomllib.loads(builder.runtime_project([], geo=False))
    assert not any(d.startswith("pyproj==") for d in basic["project"]["dependencies"])


def test_delivery_runtime_follows_transitive_extra_dependencies_without_geo():
    builder = load_builder()
    dependencies = tomllib.loads(builder.runtime_project([], geo=False))["project"]["dependencies"]
    for name in ("reportlab", "ezdxf", "fonttools"):
        assert any(item.startswith(name + "==") for item in dependencies)
    assert not any(item.startswith("pyproj==") for item in dependencies)


def test_web_map_runtime_is_opt_in_and_pins_warp_dependencies():
    builder = load_builder()
    ordinary = tomllib.loads(builder.runtime_project([]))["project"]["dependencies"]
    assert not any(d.startswith("rasterio==") for d in ordinary)
    mapped = tomllib.loads(builder.runtime_project([], web_map=True))["project"]["dependencies"]
    for name in ("rasterio", "numpy", "pyproj", "pillow"):
        assert any(d.startswith(name + "==") for d in mapped)
    assert not any(d.startswith("playwright") for d in mapped)


def test_web_map_build_rejects_without_geo_before_building(tmp_path, monkeypatch):
    builder = load_builder()
    monkeypatch.setattr(builder, "run", lambda *a, **k: pytest.fail("must reject before building"))
    with pytest.raises(ValueError, match="requires geo"):
        builder.build(tmp_path / "invalid.zip", geo=False, web_map=True)
    assert not (tmp_path / "invalid.zip").exists()


def test_plugin_archive_includes_standalone_online_map_capability(tmp_path, monkeypatch):
    builder = load_builder()
    monkeypatch.setattr(builder.shutil, "which", lambda name: "/fake/uv")

    def fake_run(arguments, *, cwd):
        if arguments[1] == "build":
            output_dir = Path(arguments[arguments.index("--out-dir") + 1])
            package = arguments[arguments.index("--package") + 1]
            (output_dir / f"{package.replace('-', '_')}-1.0.0-py3-none-any.whl").write_bytes(
                b"wheel"
            )
        elif arguments[1] == "lock":
            (Path(arguments[arguments.index("--project") + 1]) / "uv.lock").write_text(
                "version = 1\n", encoding="utf-8"
            )

    monkeypatch.setattr(builder, "run", fake_run)
    archive_path = builder.build(tmp_path / "plugin.zip")

    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
    assert "skills/render-online-map/SKILL.md" in names
    assert "skills/render-online-map/README.md" in names
    assert "LICENSE" in names, "Plugin archive must carry the repository license at its root"
    assert not any(name.startswith("evals/") for name in names), (
        "Evaluator rubrics must not leak into packaged skills"
    )


def test_plugin_archive_license_matches_repository_root(tmp_path, monkeypatch):
    builder = load_builder()
    monkeypatch.setattr(builder.shutil, "which", lambda name: "/fake/uv")
    monkeypatch.setattr(builder, "run", lambda arguments, *, cwd: _write_fake_outputs(arguments))
    archive_path = builder.build(tmp_path / "plugin.zip")

    with zipfile.ZipFile(archive_path) as archive:
        assert archive.read("LICENSE") == (builder.ROOT / "LICENSE").read_bytes()


def test_plugin_archive_is_byte_reproducible(tmp_path, monkeypatch):
    builder = load_builder()
    monkeypatch.setattr(builder.shutil, "which", lambda name: "/fake/uv")
    monkeypatch.setattr(builder, "run", lambda arguments, *, cwd: _write_fake_outputs(arguments))
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1767225600")
    first = builder.build(tmp_path / "first" / "plugin.zip").read_bytes()
    second = builder.build(tmp_path / "second" / "plugin.zip").read_bytes()

    assert first == second
    with zipfile.ZipFile(tmp_path / "first" / "plugin.zip") as archive:
        assert {entry.date_time for entry in archive.infolist()} == {(2026, 1, 1, 0, 0, 0)}


def test_plugin_manifest_declares_license_repository_and_keywords():
    manifest_path = Path(__file__).resolve().parents[2] / (
        "plugins/metesparser/.claude-plugin/plugin.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["license"] == "MIT"
    assert manifest["repository"] == "https://github.com/domfahey/metesParser"
    assert manifest["homepage"] == "https://github.com/domfahey/metesParser"
    assert {"deed", "metes-and-bounds", "survey", "legal-description", "closure"} <= set(
        manifest["keywords"]
    )


def _write_fake_outputs(arguments):
    if arguments[1] == "build":
        output_dir = Path(arguments[arguments.index("--out-dir") + 1])
        package = arguments[arguments.index("--package") + 1]
        (output_dir / f"{package.replace('-', '_')}-1.0.0-py3-none-any.whl").write_bytes(b"wheel")
    elif arguments[1] == "lock":
        (Path(arguments[arguments.index("--project") + 1]) / "uv.lock").write_text(
            "version = 1\n", encoding="utf-8"
        )
