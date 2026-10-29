#!/usr/bin/env python3
"""Launch the bundled deterministic MetesParser engine in its locked runtime."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
RUNTIME = PLUGIN_ROOT / "runtime"
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")


def emit_error(message: str) -> int:
    print(
        json.dumps(
            {
                "status": "error",
                "errors": [{"code": "launcher_error", "message": message}],
                "artifacts": {},
            },
            ensure_ascii=False,
        )
    )
    return 2


def validate_runtime(runtime: Path) -> tuple[str | None, str | None]:
    """Verify the engine fingerprint and every bundled file listed in metadata."""
    try:
        metadata = json.loads((runtime / "engine.json").read_text(encoding="utf-8"))
        fingerprint = metadata["fingerprint"]
        hashes = metadata.get("sha256", metadata.get("files"))
        if not isinstance(fingerprint, str) or not FINGERPRINT_RE.fullmatch(fingerprint):
            raise ValueError("fingerprint must be 64 lowercase hexadecimal characters")
        if not isinstance(hashes, dict) or not hashes:
            raise ValueError("runtime file SHA256 map is missing or empty")
        encoded_hashes = json.dumps(hashes, sort_keys=True).encode("utf-8")
        if hashlib.sha256(encoded_hashes).hexdigest() != fingerprint:
            raise ValueError("fingerprint does not match the runtime SHA256 map")
        root = runtime.resolve()
        for relative_path, expected in hashes.items():
            if not isinstance(relative_path, str) or not isinstance(expected, str):
                raise ValueError("runtime SHA256 map must contain string paths and hashes")
            path = (runtime / relative_path).resolve()
            if not path.is_relative_to(root):
                raise ValueError(f"runtime file path escapes runtime directory: {relative_path}")
            if not FINGERPRINT_RE.fullmatch(expected):
                raise ValueError(f"invalid SHA256 for runtime file: {relative_path}")
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError(f"runtime file hash mismatch: {relative_path}")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return None, f"The plugin runtime fingerprint is invalid: {exc}"
    return fingerprint, None


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2 or args[0] not in {
        "review",
        "verify",
        "analyze-relative",
        "plot",
        "render-map",
        "compose-map",
        "compose-dashboard",
        "dashboard",
        "serve-map",
        "mapbox-mcp",
        "import-overlay",
        "register-raster",
        "fetch-parcel",
        "corpus",
        "validate-source",
        "inspect-artifacts",
        "diagnose-closure",
        "compare-descriptions",
    }:
        return emit_error(
            "Usage: run-review.py {review|verify|analyze-relative|plot|compose-map|compose-dashboard|render-map|dashboard|serve-map|mapbox-mcp|corpus|import-overlay|register-raster|fetch-parcel|validate-source|inspect-artifacts|diagnose-closure|compare-descriptions} [engine options]"
        )
    if not any(arg == "--settings" or arg.startswith("--settings=") for arg in args):
        args.extend(["--settings", str(Path.cwd() / ".claude" / "metesparser.local.md")])
    uv = shutil.which("uv")
    if uv is None:
        return emit_error("uv is required. Install uv, then rerun the MetesParser review.")
    if not (RUNTIME / "pyproject.toml").is_file() or not (RUNTIME / "uv.lock").is_file():
        return emit_error(
            "The plugin's locked runtime is incomplete (missing pyproject.toml or uv.lock)."
        )

    fingerprint, validation_error = validate_runtime(RUNTIME)
    if validation_error:
        return emit_error(validation_error)

    cache_root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    env = os.environ.copy()
    env["UV_PROJECT_ENVIRONMENT"] = str(cache_root / "metesparser" / fingerprint / "venv")
    env["UV_CACHE_DIR"] = str(cache_root / "metesparser" / "uv-cache")
    command = [
        uv,
        "run",
        "--project",
        str(RUNTIME),
        "--locked",
        "--",
        "python",
        "-m",
        "mp_review",
        *args,
    ]
    try:
        if args[0] == "serve-map":
            # Replace the launcher: stream the URL immediately and let uv forward signals.
            # All other commands retain their one-JSON-result capture contract.
            os.execvpe(uv, command, env)
            return 0
        result = subprocess.run(command, env=env, check=False, capture_output=True, text=True)
    except OSError as exc:
        return emit_error(f"Could not start uv: {exc}")
    if result.stdout:
        sys.stdout.write(result.stdout)
        if not result.stdout.endswith("\n"):
            sys.stdout.write("\n")
        if result.stderr:
            sys.stderr.write(result.stderr)
        return result.returncode
    if result.returncode:
        detail = (
            result.stderr.strip()
            or f"uv exited with status {result.returncode} without engine output"
        )
        return emit_error(f"Could not start the MetesParser engine: {detail}")
    if result.stderr:
        sys.stderr.write(result.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
