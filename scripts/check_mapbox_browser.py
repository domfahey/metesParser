"""Preflight explicit Mapbox gates; cache validation never downloads provider assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR = ROOT / "packages/mp-export/src/mp_export/dashboard_assets/mapbox-sdk.json"


def sdk_cache() -> dict[str, Path]:
    descriptor = json.loads(DESCRIPTOR.read_text())
    directory = ROOT / ".uv-cache/mapbox" / ("v" + descriptor["version"])
    result = {}
    for name, spec in descriptor["files"].items():
        path = directory / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != spec["sha256"]:
            raise ValueError(
                f"Pinned Mapbox SDK cache missing or incorrect: {path}. "
                "Fetch the exact descriptor assets explicitly before running this gate."
            )
        result[name] = path
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Also require a runtime public token")
    args = parser.parse_args()
    try:
        sdk_cache()
        if args.live:
            token = os.environ.get("MAPBOX_PUBLIC_TOKEN") or os.environ.get(
                "MAPBOX_ACCESS_TOKEN", ""
            )
            if not token.startswith("pk.") or any(c.isspace() for c in token):
                raise ValueError(
                    "Live gate requires MAPBOX_PUBLIC_TOKEN or MAPBOX_ACCESS_TOKEN from a secret environment facility."
                )
        from playwright.sync_api import sync_playwright

        with sync_playwright() as runtime:
            browser = runtime.chromium.launch()
            page = browser.new_page()
            usable = page.evaluate("""() => {
                const canvas = document.createElement('canvas');
                const gl = canvas.getContext('webgl2');
                if (!gl) return false;
                gl.getExtension('WEBGL_lose_context')?.loseContext();
                return true;
            }""")
            browser.close()
            if not usable:
                raise ValueError(
                    "Chromium WebGL2 is unavailable; actual-SDK acceptance cannot run."
                )
    except Exception as exc:
        # Do not echo exceptions with arbitrary browser/provider payloads or environment values.
        if isinstance(exc, ValueError):
            print(str(exc), file=sys.stderr)
        else:
            print(
                "Mapbox browser preflight failed: install browser-test dependencies and Chromium; verify browser launch permissions.",
                file=sys.stderr,
            )
        return 1
    print("Pinned Mapbox SDK cache and Chromium WebGL2 prerequisites passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
