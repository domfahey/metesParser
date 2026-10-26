"""Machine-readable command line interface."""

import argparse
import contextlib
import json
import sys
from pathlib import Path

from .api import review_file, verify_file


def main() -> None:
    parser = argparse.ArgumentParser(prog="metes-review")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("review", "verify"):
        command = commands.add_parser(name)
        command.add_argument("input", type=Path)
        command.add_argument("--output-dir", type=Path, required=True)
        command.add_argument("--area", type=float)
    corpus = commands.add_parser("corpus")
    corpus.add_argument("manifest", type=Path)
    corpus.add_argument("--output", type=Path)
    args = parser.parse_args()
    with contextlib.redirect_stdout(sys.stderr):
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
        else:
            operation = review_file if args.command == "review" else verify_file
            result = operation(args.input, output_dir=args.output_dir, stated_area_sq_ft=args.area)
    print(json.dumps(result, allow_nan=False))
    raise SystemExit(
        {"checks_passed": 0, "needs_review": 1, "passed": 0, "failed": 1, "error": 2}.get(
            result.get("status"), 2
        )
    )
