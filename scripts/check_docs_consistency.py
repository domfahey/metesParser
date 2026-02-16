#!/usr/bin/env python3
"""Lightweight docs consistency checks for live documentation.

This script validates high-impact invariants that frequently drift:
- Snapshot test counts in live docs match current pytest collection.
- API examples match current return types/flow.
- Architecture docs reference existing methods.
- Contributing guide does not overstate command equivalence.
- Key historical docs are clearly labeled as historical.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class CheckFailure(Exception):
    """Raised when one or more checks fail."""


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def collect_test_count() -> int:
    """Return current pytest collected test count without project addopts noise."""
    cmd = ["pytest", "--collect-only", "-q", "-o", "addopts="]
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    output = f"{proc.stdout}\n{proc.stderr}"
    match = re.search(r"(\d+)\s+tests collected", output)
    if not match:
        raise CheckFailure(
            "Unable to determine collected test count from pytest output. "
            "Run `pytest --collect-only -q -o addopts=` manually."
        )
    return int(match.group(1))


def require_snapshot_count(path: Path, actual_count: int, errors: list[str]) -> None:
    text = read_text(path)
    match = re.search(r"snapshot:\s*(\d+)\s+tests collected", text)
    if not match:
        errors.append(f"{path}: missing `snapshot: <N> tests collected` marker in live docs")
        return
    documented = int(match.group(1))
    if documented != actual_count:
        errors.append(
            f"{path}: documented snapshot count {documented} != current collected {actual_count}"
        )


def main() -> int:
    errors: list[str] = []

    docs_api = ROOT / "docs" / "API.md"
    docs_testing = ROOT / "docs" / "TESTING.md"
    docs_arch = ROOT / "docs" / "ARCHITECTURE.md"
    docs_contrib = ROOT / "docs" / "CONTRIBUTING.md"
    docs_workflow = ROOT / "docs" / "pennbrook_sample_workflow_diagrams.md"
    docs_compare = ROOT / "docs" / "31_pennbrook_extraction_comparison.md"

    try:
        test_count = collect_test_count()
    except CheckFailure as exc:
        errors.append(str(exc))
        test_count = -1

    if test_count >= 0:
        require_snapshot_count(docs_testing, test_count, errors)
        require_snapshot_count(docs_arch, test_count, errors)

    api_text = read_text(docs_api)
    if "legal_text = processor.process_deed_pdf(" in api_text:
        errors.append(
            "docs/API.md: complete example still treats process_deed_pdf() as text output"
        )
    if "normalize_legal_description(legal_text)" in api_text:
        errors.append(
            "docs/API.md: complete example still normalizes LegalDescription object as text"
        )

    arch_text = read_text(docs_arch)
    if "generate_text_with_pdf()" in arch_text:
        errors.append(
            "docs/ARCHITECTURE.md: references non-existent PDFProcessor.generate_text_with_pdf()"
        )

    contrib_text = read_text(docs_contrib)
    if "Equivalent to `make check`" in contrib_text:
        errors.append("docs/CONTRIBUTING.md: claims make pre-commit is equivalent to make check")

    workflow_text = read_text(docs_workflow)
    if "PP-->>CLI: return legal_desc + closure_result" in workflow_text:
        errors.append(
            "docs/pennbrook_sample_workflow_diagrams.md: assigns closure_result return to PDFProcessor"
        )

    compare_text = read_text(docs_compare)
    if "ground truth JSON needs to be regenerated" in compare_text:
        errors.append(
            "docs/31_pennbrook_extraction_comparison.md: still claims ground truth needs regeneration"
        )
    if "Historical snapshot" not in compare_text:
        errors.append(
            "docs/31_pennbrook_extraction_comparison.md: missing historical snapshot banner"
        )

    plan_files = sorted((ROOT / "docs" / "plans").glob("*.md"))
    for plan_file in plan_files:
        if "Historical snapshot" not in read_text(plan_file):
            errors.append(f"{plan_file}: missing historical snapshot banner")

    if errors:
        print("docs consistency check failed:")
        for err in errors:
            print(f"- {err}")
        return 1

    print(f"docs consistency check passed (collected tests: {test_count})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
