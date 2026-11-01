"""Bundle the Claude plugin with the deterministic engine and a pinned uv runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import tomllib
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("mp-models", "mp-bearing", "mp-parse", "mp-verify", "mp-export", "mp-review")


def run(args: list[str], *, cwd: Path) -> None:
    env = dict(os.environ)
    env.setdefault("UV_CACHE_DIR", str(ROOT / ".uv-cache"))
    env["UV_CACHE_DIR"] = str(Path(env["UV_CACHE_DIR"]).resolve())
    subprocess.run(args, cwd=cwd, env=env, check=True)


def runtime_project(wheels: list[Path], *, geo: bool = True, web_map: bool = False) -> str:
    """Pin external dependencies to the versions already reviewed in the root lock."""
    if web_map and not geo:
        raise ValueError("web-map requires geo support")
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    indexed: dict[str, list[dict[str, Any]]] = {}
    for package in lock["package"]:
        indexed.setdefault(package["name"], []).append(package)
    external: set[str] = set()
    visited: set[tuple[str, tuple[str, ...]]] = set()

    def collect(name: str, extras: tuple[str, ...] = ()) -> None:
        key = (name, tuple(sorted(extras)))
        if key in visited:
            return
        visited.add(key)
        if name not in PACKAGES:
            external.add(name)
        for package in indexed[name]:
            requirements = list(package.get("dependencies", []))
            for extra in extras:
                requirements.extend(package.get("optional-dependencies", {}).get(extra, []))
            for dependency in requirements:
                collect(dependency["name"], tuple(dependency.get("extra", ())))

    for name in PACKAGES:
        if name in indexed:
            collect(name)
    collect(
        "mp-review",
        tuple(["delivery"] + (["geo"] if geo else []) + (["web-map"] if web_map else [])),
    )
    dependencies = []
    for name in [*PACKAGES, *sorted(external)]:
        for package in indexed[name]:
            requirement = f"{name}=={package['version']}"
            if len(indexed[name]) > 1:
                markers = package.get("resolution-markers", [])
                if not markers:
                    raise ValueError(f"Multiple locked {name} versions require resolution markers")
                requirement += "; " + " or ".join(f"({m})" for m in markers)
            dependencies.append(requirement)
    sources = []
    for wheel in sorted(wheels):
        name = wheel.name.split("-", 1)[0].replace("_", "-")
        sources.append(f'{name} = {{ path = "wheels/{wheel.name}" }}')
    return (
        '[project]\nname = "metesparser-plugin-runtime"\nversion = "0.1.0"\n'
        'requires-python = ">=3.11"\ndependencies = '
        + json.dumps(dependencies, indent=2)
        + "\n\n[tool.uv]\npackage = false\n\n[tool.uv.sources]\n"
        + "\n".join(sources)
        + "\n"
    )


FIXED_DATE = (1980, 1, 1, 0, 0, 0)


def zip_date() -> tuple[int, int, int, int, int, int]:
    """Return the archive timestamp: SOURCE_DATE_EPOCH when set, else a fixed date."""
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if not epoch:
        return FIXED_DATE
    stamp = time.gmtime(int(epoch))[:6]
    return stamp if stamp >= FIXED_DATE else FIXED_DATE


def build(output: Path, *, offline: bool = False, geo: bool = True, web_map: bool = False) -> Path:
    if web_map and not geo:
        raise ValueError("web-map requires geo support")
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
            ignore=shutil.ignore_patterns("__pycache__", ".DS_Store", "runtime", "tests", "evals"),
        )
        shutil.copyfile(ROOT / "LICENSE", plugin / "LICENSE")
        runtime = plugin / "runtime"
        wheel_dir = runtime / "wheels"
        wheel_dir.mkdir(parents=True)
        for package in PACKAGES:
            run(
                [uv, "build", "--package", package, "--wheel", "--out-dir", str(wheel_dir), *flags],
                cwd=ROOT,
            )
        wheels = list(wheel_dir.glob("*.whl"))
        (runtime / "pyproject.toml").write_text(runtime_project(wheels, geo=geo, web_map=web_map))
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
        # Fixed timestamps and permissions keep the archive byte-reproducible.
        staged_zip = Path(temporary) / "plugin.zip"
        date_time = zip_date()
        with zipfile.ZipFile(staged_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(plugin.rglob("*")):
                if path.is_file() and not any(
                    part in {".uv-cache", ".venv", "__pycache__"}
                    for part in path.relative_to(plugin).parts
                ):
                    entry = zipfile.ZipInfo(str(path.relative_to(plugin)), date_time=date_time)
                    entry.compress_type = zipfile.ZIP_DEFLATED
                    entry.create_system = 3
                    mode = 0o755 if os.access(path, os.X_OK) else 0o644
                    entry.external_attr = (0o100000 | mode) << 16
                    archive.writestr(entry, path.read_bytes())
        shutil.copyfile(staged_zip, output)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + ".sha256").write_text(f"{digest}  {output.name}\n")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/metesparser-plugin.zip")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument(
        "--without-geo", action="store_true", help="Omit optional map import dependencies"
    )
    parser.add_argument(
        "--with-web-map",
        action="store_true",
        help="Include optional online map preparation dependencies",
    )
    args = parser.parse_args()
    if args.with_web_map and args.without_geo:
        parser.error("--with-web-map requires geo; cannot combine with --without-geo")
    print(
        build(
            args.output, offline=args.offline, geo=not args.without_geo, web_map=args.with_web_map
        )
    )


if __name__ == "__main__":
    main()
