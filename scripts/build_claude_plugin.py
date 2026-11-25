"""Bundle the Claude plugin with the deterministic engine and a pinned uv runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import tomllib
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("mp-models", "mp-bearing", "mp-parse", "mp-verify", "mp-export", "mp-review")


def run(args: list[str], *, cwd: Path) -> None:
    env = dict(os.environ)
    env.setdefault("UV_CACHE_DIR", str(ROOT / ".uv-cache"))
    env["UV_CACHE_DIR"] = str(Path(env["UV_CACHE_DIR"]).resolve())
    subprocess.run(args, cwd=cwd, env=env, check=True)


def _parse_wheel_name_and_version(wheel: Path) -> tuple[str, str]:
    if wheel.suffix != ".whl":
        raise ValueError(f"Expected a .whl file, got: {wheel.name}")
    parts = wheel.stem.split("-")
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Invalid wheel filename: {wheel.name}")
    return parts[0].replace("_", "-"), parts[1]


def runtime_project(wheels: list[Path]) -> str:
    """Pin external dependencies to the versions already reviewed in the root lock."""
    wheel_versions: dict[str, str] = {}
    sources: list[str] = []
    for wheel in sorted(wheels):
        name, version = _parse_wheel_name_and_version(wheel)
        if name in wheel_versions:
            raise ValueError(f"Duplicate wheel provided for package {name!r}")
        wheel_versions[name] = version
        sources.append(f'{name} = {{ path = "wheels/{wheel.name}" }}')

    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    packages_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pkg in lock.get("package", []):
        packages_by_name[pkg["name"]].append(pkg)

    external: set[str] = set()
    visited: set[str] = set()

    def _resolved_version(name: str) -> str:
        entries = packages_by_name.get(name, [])
        if not entries:
            raise ValueError(f"Required package {name!r} not found in uv.lock")
        versions = sorted({str(entry["version"]) for entry in entries})
        if len(versions) > 1:
            raise ValueError(
                f"Conflicting versions in uv.lock for required package {name!r}: "
                + ", ".join(versions)
            )
        return versions[0]

    def collect(name: str) -> None:
        if name in visited:
            return
        visited.add(name)
        entries = packages_by_name.get(name, [])
        if entries:
            _resolved_version(name)
        elif name not in PACKAGES:
            raise ValueError(f"Required package {name!r} not found in uv.lock")
        if name not in PACKAGES:
            external.add(name)
        for entry in entries:
            for dependency in entry.get("dependencies", []):
                collect(dependency["name"])

    for name in PACKAGES:
        if name in packages_by_name:
            collect(name)

    dependencies = [
        f"{name}=={wheel_versions[name] if name in wheel_versions else _resolved_version(name)}"
        for name in PACKAGES
    ] + [f"{name}=={_resolved_version(name)}" for name in sorted(external)]
    return (
        '[project]\nname = "metesparser-plugin-runtime"\nversion = "0.1.0"\n'
        'requires-python = ">=3.11"\ndependencies = '
        + json.dumps(dependencies, indent=2)
        + "\n\n[tool.uv]\npackage = false\n\n[tool.uv.sources]\n"
        + "\n".join(sources)
        + "\n"
    )


def build(output: Path, *, offline: bool = False) -> Path:
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv is required to build the plugin")
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    flags = ["--offline"] if offline else []
    with tempfile.TemporaryDirectory(prefix="metesparser-plugin-") as temporary:
        plugin = Path(temporary) / "metesparser"
        shutil.copytree(
            ROOT / "plugins" / "metesparser",
            plugin,
            ignore=shutil.ignore_patterns("__pycache__", ".DS_Store", "runtime", "tests"),
        )
        runtime = plugin / "runtime"
        wheel_dir = runtime / "wheels"
        wheel_dir.mkdir(parents=True)
        for package in PACKAGES:
            run(
                [uv, "build", "--package", package, "--wheel", "--out-dir", str(wheel_dir), *flags],
                cwd=ROOT,
            )
        wheels = list(wheel_dir.glob("*.whl"))
        (runtime / "pyproject.toml").write_text(runtime_project(wheels))
        run([uv, "lock", "--project", str(runtime), *flags], cwd=runtime)
        hashes = {
            str(path.relative_to(runtime)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [*sorted(wheels), runtime / "pyproject.toml", runtime / "uv.lock"]
        }
        fingerprint = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
        (runtime / "engine.json").write_text(
            json.dumps({"fingerprint": fingerprint, "sha256": hashes}, indent=2) + "\n"
        )
        # Publish only after every wheel and the runtime lock have been built successfully.
        staged_zip = Path(temporary) / "plugin.zip"
        with zipfile.ZipFile(staged_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(plugin.rglob("*")):
                if path.is_file() and not any(
                    part in {".uv-cache", ".venv", "__pycache__"}
                    for part in path.relative_to(plugin).parts
                ):
                    archive.write(path, str(path.relative_to(plugin)))
        shutil.copyfile(staged_zip, output)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + ".sha256").write_text(f"{digest}  {output.name}\n")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/metesparser-plugin.zip")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    print(build(args.output, offline=args.offline))


if __name__ == "__main__":
    main()
