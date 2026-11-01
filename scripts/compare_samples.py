#!/usr/bin/env python3
"""Compare result-level sample deed outputs between two git refs.

Default mode checks each ref out into a temporary detached worktree, syncs its uv
environment, runs this file in ``--collect`` mode inside that environment, and diffs
the two snapshots. The caller's checkout is never modified. Collection uses only the
APIs of the checked-out ref; attributes missing on older refs are read with defaults,
and any per-stage failure is recorded as an error rather than aborting.

Usage:
    uv run python scripts/compare_samples.py --ref-a origin/main --ref-b HEAD \
        [--output report.json]

The report always exits 0 once both snapshots are collected; a ref that cannot be
collected is printed and recorded in the output. Bad refs and bad arguments exit 2.
"""

from __future__ import annotations

import argparse
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
ERROR_MESSAGE_CHARS = 120
STAGES = ("extraction", "verification", "export")
CATEGORIES = (
    "sample_set",
    "verification_lost",
    "verification_gained",
    "export_lost",
    "export_gained",
    "course_values",
    "tract_changes",
    "verification_values",
    "errors",
)


# --- Diff and summary (pure) -------------------------------------------------------


def _section(record: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = record.get(name)
    return value if isinstance(value, Mapping) else {}


def _verified(record: Mapping[str, Any]) -> bool:
    return bool(_section(record, "verification").get("verified"))


def _exported(record: Mapping[str, Any]) -> bool:
    return bool(_section(record, "export").get("ok"))


def _course_detail(before: list[Any], after: list[Any]) -> dict[str, Any] | None:
    changed = []
    for index in range(max(len(before), len(after))):
        old = before[index] if index < len(before) else None
        new = after[index] if index < len(after) else None
        if old != new:
            changed.append({"index": index, "before": old, "after": new})
    if not changed:
        return None
    return {"call_count": {"before": len(before), "after": len(after)}, "changed": changed}


def _diff_record(old: Mapping[str, Any], new: Mapping[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {}
    if _verified(old) != _verified(new):
        category = "verification_lost" if _verified(old) else "verification_gained"
        entry[category] = {"before": _verified(old), "after": _verified(new)}
    if _exported(old) != _exported(new):
        category = "export_lost" if _exported(old) else "export_gained"
        entry[category] = {"before": _exported(old), "after": _exported(new)}
    courses = _course_detail(list(old.get("calls") or []), list(new.get("calls") or []))
    if courses is not None:
        entry["course_values"] = courses
    old_tracts, new_tracts = old.get("tracts") or [], new.get("tracts") or []
    if old_tracts != new_tracts:
        entry["tract_changes"] = {"before": old_tracts, "after": new_tracts}
    old_rows = _section(old, "verification").get("results") or []
    new_rows = _section(new, "verification").get("results") or []
    if old_rows != new_rows:
        entry["verification_values"] = {"before": old_rows, "after": new_rows}
    errors: dict[str, Any] = {}
    for stage in STAGES:
        old_error = _section(old, stage).get("error")
        new_error = _section(new, stage).get("error")
        if old_error != new_error:
            errors[stage] = {"before": old_error, "after": new_error}
    if errors:
        entry["errors"] = errors
    return entry


def diff_samples(
    before: Mapping[str, Mapping[str, Any]], after: Mapping[str, Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Return ``{sample key: {category: detail}}`` for every sample that changed."""
    changes: dict[str, dict[str, Any]] = {}
    for key in sorted(set(before) | set(after)):
        if key not in before or key not in after:
            changes[key] = {"sample_set": {"before": key in before, "after": key in after}}
            continue
        entry = _diff_record(before[key], after[key])
        if entry:
            changes[key] = entry
    return changes


def summarize(changes: Mapping[str, Mapping[str, Any]]) -> dict[str, list[str]]:
    """Group changed sample keys by category; every category is present, sorted."""
    grouped: dict[str, list[str]] = {category: [] for category in CATEGORIES}
    for key, entry in changes.items():
        for category in entry:
            grouped.setdefault(category, []).append(key)
    return {category: sorted(keys) for category, keys in grouped.items()}


def format_summary(ref_a: str, ref_b: str, total: int, summary: Mapping[str, list[str]]) -> str:
    """Render counts per category and the samples that lost verification or export."""
    changed = len({key for keys in summary.values() for key in keys})
    labels = {
        "sample_set": "sample set changed",
        "verification_lost": "verification lost",
        "verification_gained": "verification gained",
        "export_lost": "export lost",
        "export_gained": "export gained",
        "course_values": "course values changed",
        "tract_changes": "tract changes",
        "verification_values": "verification values changed",
        "errors": "errors changed",
    }
    lines = [f"Sample comparison: {ref_a} -> {ref_b}", f"Samples: {total} ({changed} changed)"]
    for category in CATEGORIES:
        lines.append(f"  {labels[category]:<30}{len(summary.get(category, [])):>5}")
    for category in ("verification_lost", "export_lost"):
        keys = summary.get(category, [])
        lines.append(f"{labels[category].capitalize()} ({len(keys)}):")
        lines.extend(f"  - {key}" for key in keys)
    return "\n".join(lines)


# --- Collection (runs inside each ref's worktree environment) ---------------------


def _error(exc: BaseException) -> dict[str, str]:
    return {"type": type(exc).__name__, "message": str(exc)[:ERROR_MESSAGE_CHARS]}


def _round(value: Any, digits: int) -> float | None:
    return None if value is None else round(float(value), digits)


def _plain(value: Any) -> Any:
    return getattr(value, "value", value)


def _call_row(call: Any) -> dict[str, Any]:
    return {
        "bearing_azimuth_deg_from_north": _round(
            getattr(call, "bearing_azimuth_deg_from_north", None), 6
        ),
        "distance_ft": _round(getattr(call, "distance_ft", None), 4),
        "is_tie_in": bool(getattr(call, "is_tie_in", False)),
        "is_exception": bool(getattr(call, "is_exception", False)),
    }


def _tract_row(tract: Any) -> dict[str, Any]:
    return {
        "label": getattr(tract, "label", None),
        "type": _plain(getattr(tract, "tract_type", None)),
        "role_basis": _plain(getattr(tract, "role_basis", None)),
    }


def _sample_texts(root: Path) -> Iterator[tuple[str, str]]:
    """Yield ``(key, text)``: ``<file>.md``, then ``<deed>::legal`` / ``::normalized``."""
    sample_dir = root / "sample_deeds"
    for path in sorted(sample_dir.glob("*.md")):
        yield path.name, path.read_text(encoding="utf-8")
    for path in sorted(sample_dir.glob("*.ground_truth.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        deed = path.name.removesuffix(".ground_truth.json")
        for field, tag in (
            ("expected_legal_description", "legal"),
            ("expected_normalized_text", "normalized"),
        ):
            value = data.get(field)
            if isinstance(value, str) and value:
                yield f"{deed}::{tag}", value


def _accepted(fn: Callable[..., Any], **kwargs: Any) -> dict[str, Any]:
    """Keep only the keyword arguments ``fn`` accepts, so older refs still collect."""
    params = inspect.signature(fn).parameters
    if any(param.kind is inspect.Parameter.VAR_KEYWORD for param in params.values()):
        return kwargs
    return {name: value for name, value in kwargs.items() if name in params}


def _extract(text: str, skips: list[Any]) -> tuple[list[Any], list[Any]]:
    from mp_parse.calls import extract_calls

    result: Any = extract_calls(
        text, **_accepted(extract_calls, strict=False, skipped_courses=skips)
    )
    if isinstance(result, tuple):
        calls, tracts = result
        return list(calls), list(tracts)
    return list(result), []


def _verify(calls: list[Any], tracts: list[Any], skips: list[Any]) -> tuple[list[Any], list[Any]]:
    from mp_verify.closure import verify_closure

    if tracts:
        out: Any = verify_closure(
            calls, **_accepted(verify_closure, tracts=tracts, skipped_courses=skips)
        )
        labels = [getattr(tract, "label", None) for tract in tracts]
    else:
        out = verify_closure(calls, **_accepted(verify_closure, skipped_courses=skips))
        labels = [None]
    return (out if isinstance(out, list) else [out]), labels


def _result_rows(results: list[Any], labels: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, result in enumerate(results):
        checker = getattr(result, "is_fully_verified", None)
        rows.append(
            {
                "tract": labels[index] if index < len(labels) else None,
                "misclosure_available": bool(getattr(result, "misclosure_available", True)),
                "misclosure": _round(getattr(result, "misclosure_ft", None), 4),
                "area": _round(getattr(result, "area_sq_ft", None), 2),
                "fully_verified": bool(checker()) if callable(checker) else None,
            }
        )
    return rows


def _export(
    calls: list[Any], results: list[Any], tracts: list[Any], skips: list[Any], work_dir: Path
) -> list[str]:
    from mp_export.csv_writer import export_verified_csv

    work_dir.mkdir(parents=True, exist_ok=True)
    tract_results = list(zip(tracts, results, strict=False)) if tracts else None
    paths = export_verified_csv(
        calls,
        results[0],
        str(work_dir / "export.csv"),
        **_accepted(export_verified_csv, tract_results=tract_results, skipped_courses=skips),
    )
    return sorted(Path(path).name for path in paths)


def _collect_record(text: str, work_dir: Path) -> dict[str, Any]:
    extraction: dict[str, Any] = {"error": None, "call_count": 0}
    verification: dict[str, Any] = {"error": None, "verified": False, "results": []}
    export: dict[str, Any] = {"error": None, "ok": False, "files": []}
    skips: list[Any] = []
    calls: list[Any] = []
    tracts: list[Any] = []
    try:
        calls, tracts = _extract(text, skips)
        extraction["call_count"] = len(calls)
    except Exception as exc:  # noqa: BLE001 - an extraction failure is recorded data
        extraction["error"] = _error(exc)
    extraction["skipped_count"] = len(skips)
    extraction["tract_skipped_count"] = sum(
        len(getattr(tract, "skipped_courses", None) or []) for tract in tracts
    )

    results: list[Any] = []
    if calls:
        try:
            results, labels = _verify(calls, tracts, skips)
            rows = _result_rows(results, labels)
            verification["results"] = rows
            verification["verified"] = bool(rows) and all(
                row["fully_verified"] is True for row in rows
            )
        except Exception as exc:  # noqa: BLE001 - a verification failure is recorded data
            verification["error"] = _error(exc)
            results = []

    if results:
        try:
            export["files"] = _export(calls, results, tracts, skips, work_dir)
            export["ok"] = bool(export["files"])
        except Exception as exc:  # noqa: BLE001 - the exporter's refusal is recorded data
            export["error"] = _error(exc)

    return {
        "extraction": extraction,
        "calls": [_call_row(call) for call in calls],
        "tracts": [_tract_row(tract) for tract in tracts],
        "verification": verification,
        "export": export,
    }


def collect(root: Path, out: Path) -> None:
    """Write ``{"samples": {key: record}}`` for the checkout at ``root``."""
    samples: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="compare-samples-export-") as tmp:
        for index, (key, text) in enumerate(_sample_texts(root)):
            samples[key] = _collect_record(text, Path(tmp) / str(index))
    out.write_text(json.dumps({"samples": samples}, indent=2, sort_keys=True), encoding="utf-8")


# --- Orchestration -----------------------------------------------------------------


def _git(args: list[str]) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _resolve(ref: str) -> str:
    return _git(["rev-parse", "--verify", f"{ref}^{{commit}}"])


@contextmanager
def _worktree(sha: str, path: Path) -> Iterator[Path]:
    try:
        _git(["worktree", "add", "--detach", str(path), sha])
        yield path
    finally:
        removed = subprocess.run(
            ["git", "worktree", "remove", "--force", str(path)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if removed.returncode != 0:
            shutil.rmtree(path, ignore_errors=True)
        subprocess.run(["git", "worktree", "prune"], cwd=REPO_ROOT, check=False)


def _run(cmd: list[str], cwd: Path, env: dict[str, str]) -> None:
    proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip()[-800:]
        raise RuntimeError(f"{' '.join(cmd[:3])} failed ({proc.returncode}): {tail}")


def _snapshot(ref: str, sha: str, work: Path, label: str) -> dict[str, Any]:
    meta: dict[str, Any] = {"ref": ref, "sha": sha}
    uv = shutil.which("uv")
    if uv is None:
        return {**meta, "error": "uv not found on PATH"}
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT")
    }
    try:
        with _worktree(sha, work / label) as path:
            _run([uv, "sync", "--all-extras", "--dev", "-q"], path, env)
            out = work / f"{label}.json"
            _run(
                [
                    uv,
                    "run",
                    "--no-sync",
                    "--project",
                    str(path),
                    "python",
                    str(Path(__file__).resolve()),
                    "--collect",
                    "--root",
                    str(path),
                    "--out",
                    str(out),
                ],
                path,
                env,
            )
            samples = json.loads(out.read_text(encoding="utf-8"))["samples"]
    except (RuntimeError, OSError, KeyError, ValueError) as exc:
        return {**meta, "error": str(exc)}
    return {**meta, "samples": samples}


def compare(ref_a: str, ref_b: str, output: Path | None) -> int:
    try:
        sha_a, sha_b = _resolve(ref_a), _resolve(ref_b)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    work = Path(tempfile.mkdtemp(prefix="compare-samples-"))
    try:
        snap_a = _snapshot(ref_a, sha_a, work, "a")
        snap_b = _snapshot(ref_b, sha_b, work, "b")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    failed = [snap for snap in (snap_a, snap_b) if "error" in snap]
    if failed:
        for snap in failed:
            print(f"ERROR collecting {snap['ref']} ({snap['sha'][:7]}): {snap['error']}")
        report: dict[str, Any] = {"ref_a": snap_a, "ref_b": snap_b}
    else:
        changes = diff_samples(snap_a["samples"], snap_b["samples"])
        summary = summarize(changes)
        total = len(set(snap_a["samples"]) | set(snap_b["samples"]))
        print(format_summary(f"{ref_a} ({sha_a[:7]})", f"{ref_b} ({sha_b[:7]})", total, summary))
        report = {
            "ref_a": {"ref": ref_a, "sha": sha_a},
            "ref_b": {"ref": ref_b, "sha": sha_b},
            "summary": dict(summary),
            "changes": changes,
        }
    if output is not None:
        output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(f"Full diff written to {output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare sample deed results between two refs.")
    parser.add_argument("--ref-a", default="origin/main", help="baseline git ref")
    parser.add_argument("--ref-b", default="HEAD", help="candidate git ref")
    parser.add_argument("--output", type=Path, help="write the full JSON diff here")
    parser.add_argument("--collect", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--out", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.collect:
        if args.root is None or args.out is None:
            parser.error("--collect requires --root and --out")
        collect(args.root, args.out)
        return 0
    return compare(args.ref_a, args.ref_b, args.output)


if __name__ == "__main__":
    sys.exit(main())
