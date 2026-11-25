"""Distribution regressions for the plugin's independent runtime."""

import csv
import importlib.util
import io
import json
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_builder():
    path = REPO_ROOT / "scripts/build_claude_plugin.py"
    spec = importlib.util.spec_from_file_location("plugin_builder", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_lockfile(root: Path, packages: list[dict]) -> None:
    lines = ["version = 1", ""]
    for pkg in packages:
        lines.append("[[package]]")
        lines.append(f'name = "{pkg["name"]}"')
        lines.append(f'version = "{pkg["version"]}"')
        deps = pkg.get("dependencies", [])
        if deps:
            dep_items = ", ".join(f'{{ name = "{d}" }}' for d in deps)
            lines.append(f"dependencies = [{dep_items}]")
        lines.append("")
    (root / "uv.lock").write_text("\n".join(lines), encoding="utf-8")


def test_runtime_links_every_local_wheel_as_direct_dependency():
    builder = load_builder()
    wheels = [Path(name.replace("-", "_") + "-1.0.0-py3-none-any.whl") for name in builder.PACKAGES]
    project = tomllib.loads(builder.runtime_project(wheels))
    dependencies = project["project"]["dependencies"]
    for name in builder.PACKAGES:
        assert f"{name}==1.0.0" in dependencies
        assert name in project["tool"]["uv"]["sources"]
    assert not any("ocr" in dependency or "openai" in dependency for dependency in dependencies)


def test_runtime_uses_wheel_version_when_lock_differs(monkeypatch, tmp_path):
    builder = load_builder()
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    lock_packages = [
        {
            "name": name,
            "version": "1.0.0",
            "dependencies": ["pydantic"] if name == "mp-models" else [],
        }
        for name in builder.PACKAGES
    ]
    lock_packages.append({"name": "pydantic", "version": "2.12.0", "dependencies": []})
    _write_lockfile(tmp_path, lock_packages)

    wheels = [
        Path(
            name.replace("-", "_")
            + ("-2.3.4" if name == "mp-models" else "-1.0.0")
            + "-py3-none-any.whl"
        )
        for name in builder.PACKAGES
    ]
    project = tomllib.loads(builder.runtime_project(wheels))
    dependencies = project["project"]["dependencies"]
    assert "mp-models==2.3.4" in dependencies
    assert "mp-models==1.0.0" not in dependencies
    assert "pydantic==2.12.0" in dependencies


def test_runtime_raises_on_conflicting_duplicate_lock_entries(monkeypatch, tmp_path):
    builder = load_builder()
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    lock_packages = [
        {
            "name": name,
            "version": "1.0.0",
            "dependencies": ["pydantic"] if name == "mp-models" else [],
        }
        for name in builder.PACKAGES
    ]
    lock_packages.extend(
        [
            {"name": "pydantic", "version": "2.10.0", "dependencies": []},
            {"name": "pydantic", "version": "2.12.0", "dependencies": []},
        ]
    )
    _write_lockfile(tmp_path, lock_packages)

    wheels = [Path(name.replace("-", "_") + "-1.0.0-py3-none-any.whl") for name in builder.PACKAGES]
    with pytest.raises(ValueError, match="Conflicting versions.*pydantic"):
        builder.runtime_project(wheels)


def test_runtime_resolves_nonconflicting_duplicate_lock_entries(monkeypatch, tmp_path):
    builder = load_builder()
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    lock_packages = [
        {
            "name": name,
            "version": "1.0.0",
            "dependencies": ["pydantic"] if name == "mp-models" else [],
        }
        for name in builder.PACKAGES
    ]
    lock_packages.extend(
        [
            {"name": "pydantic", "version": "2.12.0", "dependencies": ["annotated-types"]},
            {"name": "pydantic", "version": "2.12.0", "dependencies": ["typing-extensions"]},
            {"name": "annotated-types", "version": "0.7.0", "dependencies": []},
            {"name": "typing-extensions", "version": "4.12.2", "dependencies": []},
            # Unrelated package with conflicting versions must not affect runtime.
            {"name": "openai", "version": "1.0.0", "dependencies": []},
            {"name": "openai", "version": "2.0.0", "dependencies": []},
        ]
    )
    _write_lockfile(tmp_path, lock_packages)

    wheels = [Path(name.replace("-", "_") + "-1.0.0-py3-none-any.whl") for name in builder.PACKAGES]
    project = tomllib.loads(builder.runtime_project(wheels))
    dependencies = project["project"]["dependencies"]
    assert "pydantic==2.12.0" in dependencies
    assert "annotated-types==0.7.0" in dependencies
    assert "typing-extensions==4.12.2" in dependencies
    assert not any(dep.startswith("openai==") for dep in dependencies)


def test_build_cache_is_absolute_when_subprocess_changes_directory(monkeypatch, tmp_path):
    builder = load_builder()
    monkeypatch.setenv("UV_CACHE_DIR", ".uv-cache")
    calls = []
    monkeypatch.setattr(builder.subprocess, "run", lambda *args, **kwargs: calls.append(kwargs))
    builder.run(["uv", "lock"], cwd=tmp_path)
    assert Path(calls[0]["env"]["UV_CACHE_DIR"]).is_absolute()
    assert calls[0]["env"]["UV_CACHE_DIR"] != str(tmp_path / ".uv-cache")


def test_plugin_eval_cases_schema_and_square_csv():
    from mp_export.csv_writer import FIELDNAMES

    cases_path = REPO_ROOT / "plugins/metesparser/evals/cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    assert len(cases) == 8

    expected_keys = {
        "id",
        "skill",
        "request",
        "input",
        "expected_status",
        "expected",
        "must",
        "must_not",
    }
    for case in cases:
        assert set(case.keys()) == expected_keys
        assert isinstance(case["input"], dict)
        assert "kind" in case["input"]

    square = next(c for c in cases if c["id"] == "analytic-square-traverse")
    assert square["input"]["kind"] == "csv"
    csv_text = "\n".join(square["input"]["lines"])
    rows = list(csv.reader(io.StringIO(csv_text)))
    assert rows[0] == FIELDNAMES
    assert len(rows) == 5
    for row in rows[1:]:
        assert len(row) == len(FIELDNAMES)


def test_plugin_skill_versions_match_plugin_manifest():
    manifest = json.loads(
        (REPO_ROOT / "plugins/metesparser/.claude-plugin/plugin.json").read_text(encoding="utf-8")
    )
    expected_version = manifest["version"]
    skill_files = sorted((REPO_ROOT / "plugins/metesparser/skills").glob("*/SKILL.md"))
    assert len(skill_files) == 5
    for skill_file in skill_files:
        text = skill_file.read_text(encoding="utf-8")
        assert f'version: "{expected_version}"' in text, (
            f"{skill_file} missing version {expected_version}"
        )
