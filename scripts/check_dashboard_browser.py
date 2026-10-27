"""Fail the explicit browser gate if Node or a usable Chromium is unavailable."""

import shutil
import sys


def main() -> int:
    if shutil.which("node") is None:
        print(
            "Browser gate requires Node.js for independent scenario math checks.", file=sys.stderr
        )
        return 1
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            browser.close()
    except Exception as exc:
        print(
            "Browser gate unavailable. Install with: uv sync --extra dev --extra browser-test; "
            "uv run --extra browser-test playwright install chromium\n" + str(exc),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
