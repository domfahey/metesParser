#!/usr/bin/env python3
"""Backfill the run registry from ground truth JSON files.

Reads each .ground_truth.json in sample_deeds/, builds DeedCalls from
expected_calls, runs ClosureChecker.verify_closure(), and writes a
RunManifest to output/runs/.

Usage:
    uv run python scripts/backfill_run_registry.py
    uv run python scripts/backfill_run_registry.py --runs-dir output/runs
    uv run python scripts/backfill_run_registry.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import metesparser
from metesparser.closure_checker import ClosureChecker
from metesparser.models import DeedCall
from metesparser.run_registry import (
    RunManifest,
    RunResults,
    get_prompt_versions,
    write_run_manifest,
)

SAMPLE_DEEDS_DIR = Path(__file__).parent.parent / "sample_deeds"
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
DEFAULT_RUNS_DIR = Path(__file__).parent.parent / "output" / "runs"


def _build_calls(expected_calls: list[dict]) -> list[DeedCall]:
    """Build DeedCall objects from ground truth expected_calls."""
    calls: list[DeedCall] = []
    for raw in expected_calls:
        calls.append(
            DeedCall(
                course=raw["course"],
                direction_text=raw.get("direction_text", ""),
                bearing_quadrant=raw.get("bearing_quadrant"),
                bearing_azimuth_deg_from_north=raw.get("bearing_azimuth_deg_from_north"),
                distance_ft=raw.get("distance_ft"),
                along=raw.get("along"),
                to=raw.get("to"),
                notes=raw.get("notes"),
                curve_dir=raw.get("curve_dir"),
                radius_ft=raw.get("radius_ft"),
                delta_deg=raw.get("delta_deg"),
                arc_length_ft=raw.get("arc_length_ft"),
                chord_bearing=raw.get("chord_bearing"),
                chord_length_ft=raw.get("chord_length_ft"),
                curve_type=raw.get("curve_type"),
            )
        )
    return calls


def backfill(runs_dir: Path, *, dry_run: bool = False) -> int:
    """Backfill run registry from ground truth files.

    Returns the number of manifests written.
    """
    gt_files = sorted(SAMPLE_DEEDS_DIR.glob("*.ground_truth.json"))
    if not gt_files:
        print("No ground truth files found in sample_deeds/")
        return 0

    prompt_versions = get_prompt_versions(PROMPTS_DIR)
    written = 0
    # Stagger timestamps by 1 second each to avoid filename collisions
    base_time = datetime.now(UTC)

    for idx, gt_file in enumerate(gt_files):
        data = json.loads(gt_file.read_text())
        expected_calls = data.get("expected_calls", [])

        # Derive PDF filename from ground truth filename
        pdf_name = gt_file.name.replace(".ground_truth.json", ".pdf")

        if not expected_calls:
            # 0-call deeds (e.g., missing Schedule C) still get a manifest
            # so comparisons don't produce false regressions
            manifest = RunManifest(
                run_id=str(uuid.uuid4()),
                timestamp_utc=base_time + timedelta(seconds=idx),
                source_pdf=pdf_name,
                llm_provider="ground_truth",
                llm_model="human_verified",
                cache_enabled=False,
                prompt_versions=prompt_versions,
                results=RunResults(
                    call_count=0,
                    closure_passed=False,
                    misclosure_ft=0.0,
                    misclosure_available=False,
                    area_sq_ft=None,
                    confidence_score=0.0,
                    warnings=["No expected calls in ground truth"],
                ),
                parser_version=metesparser.__version__,
            )
        else:
            try:
                calls = _build_calls(expected_calls)
            except ValueError as exc:
                reason = " ".join(str(exc).split())
                print(f"  NOT BACKFILLABLE: {pdf_name} — {reason}; no run entry written")
                continue
            closure_result = ClosureChecker.verify_closure(calls)

            manifest = RunManifest(
                run_id=str(uuid.uuid4()),
                timestamp_utc=base_time + timedelta(seconds=idx),
                source_pdf=pdf_name,
                llm_provider="ground_truth",
                llm_model="human_verified",
                cache_enabled=False,
                prompt_versions=prompt_versions,
                results=RunResults.from_closure(closure_result, len(calls)),
                parser_version=metesparser.__version__,
            )

        if dry_run:
            status = "PASS" if manifest.results.closure_passed else "FAIL"
            misclosure = (
                f"{manifest.results.misclosure_ft:.4f} ft"
                if manifest.results.misclosure_available
                else "not determined"
            )
            print(
                f"  DRY RUN: {pdf_name} — {manifest.results.call_count} calls, "
                f"misclosure={misclosure}, {status}"
            )
        else:
            path = write_run_manifest(manifest, runs_dir)
            status = "PASS" if manifest.results.closure_passed else "FAIL"
            print(f"  WROTE: {path.name} — {manifest.results.call_count} calls, {status}")

        written += 1

    print(f"\nDone: {written} manifests {'(dry run)' if dry_run else 'written'}")
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill run registry from ground truth")
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=DEFAULT_RUNS_DIR,
        help="Directory to write manifests (default: output/runs/)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without writing",
    )
    args = parser.parse_args()

    count = backfill(args.runs_dir, dry_run=args.dry_run)
    if count == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
