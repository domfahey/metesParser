"""Machine-readable command line interface."""

import argparse
import contextlib
import json
import sys
from pathlib import Path
from typing import Any

from .api import review_file, verify_file
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
    corpus = commands.add_parser("corpus")
    corpus.add_argument("manifest", type=Path)
    corpus.add_argument("--output", type=Path)
    corpus.add_argument("--settings", type=Path)
    args = parser.parse_args()
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
    status = result.get("status")
    exit_code = (
        {"checks_passed": 0, "needs_review": 1, "passed": 0, "failed": 1, "error": 2}.get(status, 2)
        if isinstance(status, str)
        else 2
    )
    raise SystemExit(exit_code)


def _execute(args: argparse.Namespace, settings: dict[str, Any]) -> dict[str, Any]:
    if args.command == "corpus":
        from .corpus import run_corpus, write_corpus_report

        try:
            result = run_corpus(args.manifest)
        except (OSError, ValueError) as exc:
            return {
                "schema_version": "1.0",
                "status": "error",
                "artifacts": {},
                "errors": [{"code": "invalid_manifest", "message": str(exc)}],
            }
        if args.output is not None:
            try:
                write_corpus_report(result, args.output)
            except (OSError, ValueError) as exc:
                return {
                    "schema_version": "1.0",
                    "status": "error",
                    "artifacts": {},
                    "errors": [{"code": "output_error", "message": str(exc)}],
                }
        return result
    operation = review_file if args.command == "review" else verify_file
    return operation(
        args.input,
        output_dir=output_path(settings, args.output_dir),
        stated_area_sq_ft=args.area,
    )
