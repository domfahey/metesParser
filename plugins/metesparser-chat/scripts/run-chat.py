#!/usr/bin/env python3
"""Explicit Chat setup and delegation to the unchanged review launcher."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from types import ModuleType
from typing import TypedDict, cast

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "references" / "uv-bootstrap.json"
UV_VERSION = "0.9.6"


class WheelRecord(TypedDict):
    url: str
    sha256: str
    binary_sha256: str
    size: int


def load_launcher() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "metesparser_chat_review_launcher", ROOT / "scripts" / "run-review.py"
    )
    if spec is None or spec.loader is None:
        raise ValueError("The bundled review launcher is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cache_root() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))


def platform_key() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    machine = {"amd64": "x86_64", "aarch64": "arm64"}.get(machine, machine)
    if system == "linux" and machine == "arm64":
        machine = "aarch64"
    key = f"{system}-{machine}"
    if key not in {"darwin-arm64", "darwin-x86_64", "linux-aarch64", "linux-x86_64"}:
        raise ValueError(f"Unsupported uv bootstrap platform: {key}; install uv on PATH")
    return key


def cached_uv() -> Path:
    return (
        cache_root()
        / "metesparser"
        / "chat-tools"
        / f"uv-{UV_VERSION}"
        / platform_key()
        / "bin"
        / "uv"
    )


def wheel_record() -> WheelRecord:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest["version"] != UV_VERSION:
        raise ValueError("Unsupported uv bootstrap manifest version")
    record = manifest["wheels"][platform_key()]
    if not isinstance(record, dict):
        raise ValueError("Invalid pinned uv wheel metadata")
    size, sha256, binary_sha256, url = (
        record["size"],
        record["sha256"],
        record["binary_sha256"],
        record["url"],
    )
    if (
        not isinstance(size, int)
        or not 0 < size < 100_000_000
        or not isinstance(sha256, str)
        or len(sha256) != 64
        or not isinstance(binary_sha256, str)
        or len(binary_sha256) != 64
        or not isinstance(url, str)
        or not url.startswith("https://files.pythonhosted.org/")
    ):
        raise ValueError("Invalid pinned uv wheel metadata")
    return {"size": size, "sha256": sha256, "binary_sha256": binary_sha256, "url": url}


def verified_cached_uv() -> Path | None:
    path = cached_uv()
    if not path.exists():
        return None
    if hashlib.sha256(path.read_bytes()).hexdigest() != wheel_record()[
        "binary_sha256"
    ] or not os.access(path, os.X_OK):
        raise ValueError(f"Cached uv failed integrity validation: {path}")
    return path


def download(record: WheelRecord) -> bytes:
    """Download only the pinned PyPI wheel, bounded by its declared byte size."""
    with urllib.request.urlopen(record["url"], timeout=60) as response:
        return cast(bytes, response.read(record["size"] + 1))


def atomic_write(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def install_uv() -> Path:
    record = wheel_record()
    data = download(record)
    if len(data) != record["size"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
        raise ValueError("Pinned uv wheel size or SHA256 verification failed; nothing installed")
    member = f"uv-{UV_VERSION}.data/scripts/uv"
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if archive.namelist().count(member) != 1:
            raise ValueError("Pinned uv wheel must contain exactly one uv executable")
        binary = archive.read(member)
    if hashlib.sha256(binary).hexdigest() != record["binary_sha256"]:
        raise ValueError("Pinned uv executable SHA256 verification failed; nothing installed")
    path = cached_uv()
    atomic_write(path, binary, 0o755)
    return path


def emit_error(message: str) -> int:
    print(
        json.dumps(
            {
                "status": "error",
                "errors": [{"code": "chat_runtime_error", "message": message}],
                "artifacts": {},
            }
        )
    )
    return 2


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if sys.version_info < (3, 11):  # noqa: UP036 - invoked by the host Python before setup
            raise ValueError("Python 3.11 or newer is required")
        launcher = load_launcher()
        fingerprint, error = launcher.validate_runtime(launcher.RUNTIME)
        if error:
            raise ValueError(error)
        setup = "--setup" in args
        if setup and (
            args[0] != "--setup" or any(arg not in {"--setup", "--offline"} for arg in args)
        ):
            raise ValueError("Usage: run-chat.py --setup [--offline]")
        uv = shutil.which("uv")
        if uv is None:
            cached = verified_cached_uv()
            if cached is not None:
                uv = str(cached)
        if uv is None and setup and "--offline" not in args:
            uv = str(install_uv())
        if uv is None:
            raise ValueError(
                f"uv is unavailable. Run python3 {str(Path(__file__).resolve())!r} --setup with network access, or install uv on PATH; --offline never downloads tools."
            )
        if setup:
            env = os.environ.copy()
            env["UV_PROJECT_ENVIRONMENT"] = str(cache_root() / "metesparser" / fingerprint / "venv")
            env["UV_CACHE_DIR"] = str(cache_root() / "metesparser" / "uv-cache")
            command = [uv, "sync", "--project", str(launcher.RUNTIME), "--locked"]
            if "--offline" in args:
                command.append("--offline")
            result = subprocess.run(command, env=env, check=False, capture_output=True, text=True)
            for output in (result.stdout, result.stderr):
                if output:
                    sys.stderr.write(output)
            if result.returncode:
                raise ValueError(
                    f"uv sync failed (exit {result.returncode}): {result.stderr.strip() or 'see setup diagnostics'}"
                )
            print(
                json.dumps(
                    {
                        "status": "ready",
                        "runtime": str(launcher.RUNTIME),
                        "uv": uv,
                        "environment": env["UV_PROJECT_ENVIRONMENT"],
                        "cache": env["UV_CACHE_DIR"],
                    }
                )
            )
            return 0
        previous = os.environ.get("PATH")
        os.environ["PATH"] = str(Path(uv).parent) + os.pathsep + (previous or "")
        try:
            return cast(int, launcher.main(args))
        finally:
            if previous is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = previous
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        return emit_error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
