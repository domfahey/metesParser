"""Machine-readable command line interface."""

import argparse
import contextlib
import json
import sys
from pathlib import Path
from typing import Any

from .api import review_file, verify_file
from .relative import review_relative_file
from .settings import SettingsError, output_path, read_settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="metes-review")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("review", "verify"):
        command = commands.add_parser(name)
        command.add_argument("input", type=Path)
        command.add_argument("--output-dir", type=Path)
        command.add_argument("--area", type=float)
        command.add_argument("--settings", type=Path)
    relative = commands.add_parser(
        "analyze-relative",
        help="Analyze explicit relative constraints; valid analyses retain needs_review (exit 1).",
    )
    relative.add_argument("input", type=Path)
    relative.add_argument("--output-dir", type=Path)
    relative.add_argument("--settings", type=Path)
    corpus = commands.add_parser("corpus")
    corpus.add_argument("manifest", type=Path)
    corpus.add_argument("--output", type=Path)
    corpus.add_argument("--settings", type=Path)
    args = parser.parse_args()
    result: dict[str, Any]
    with contextlib.redirect_stdout(sys.stderr):
        try:
            settings = read_settings(args.settings)
            if not settings["enabled"]:
                result = {
                    "schema_version": "1.0",
                    "status": "error",
                    "artifacts": {},
                    "errors": [
                        {"code": "plugin_disabled", "message": "Plugin disabled in local settings."}
                    ],
                }
            else:
                result = _execute(args, settings)
        except SettingsError as exc:
            result = {
                "schema_version": "1.0",
                "status": "error",
                "artifacts": {},
                "errors": [{"code": "invalid_settings", "message": str(exc)}],
            }
    print(json.dumps(result, allow_nan=False))
    raise SystemExit(
        {"checks_passed": 0, "needs_review": 1, "passed": 0, "failed": 1, "error": 2}.get(
            str(result.get("status")), 2
        )
    )


def _execute(args: argparse.Namespace, settings: dict[str, Any]) -> dict[str, Any]:
    if args.command == "corpus":
        from .corpus import run_corpus

        try:
            result = run_corpus(args.manifest, output_path=args.output)
        except (OSError, ValueError) as exc:
            result = {
                "schema_version": "1.0",
                "status": "error",
                "errors": [{"code": "invalid_manifest", "message": str(exc)}],
            }
    elif args.command == "analyze-relative":
        result = review_relative_file(args.input, output_dir=output_path(settings, args.output_dir))
    else:
        operation = review_file if args.command == "review" else verify_file
        result = operation(
            args.input,
            output_dir=output_path(settings, args.output_dir),
            stated_area_sq_ft=args.area,
        )
    return result
