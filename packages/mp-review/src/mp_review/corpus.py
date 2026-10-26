"""Deterministic, fixture-backed review corpus runner."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from mp_models import DeedCall

_EXPECTATION_KEYS = {
    "status",
    "call_count",
    "misclosure_ft",
    "misclosure_ft_tolerance",
    "area_sq_ft",
    "area_sq_ft_tolerance",
    "selected_calls",
    "numeric_tolerance",
    "error_code",
}
_CASE_KEYS = {"id", "input", "expect", "stated_area_sq_ft"}


def _read_case(case: dict[str, Any], base: Path) -> dict[str, Any]:
    spec = case["input"]
    kind = spec["kind"]
    expected_suffix = {"text": {".txt", ".md"}, "csv": {".csv"}, "json": {".json"}}.get(kind)
    if expected_suffix is None:
        raise ValueError(f"unsupported input kind: {kind}")
    path = (base / spec["path"]).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"input file not found: {spec['path']}")
    if path.suffix.lower() not in expected_suffix:
        raise ValueError(f"input kind {kind!r} requires one of {sorted(expected_suffix)}")
    from .api import review_file

    return review_file(path, stated_area_sq_ft=case.get("stated_area_sq_ft"))


def _assertions(result: dict[str, Any], expected: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def check(name: str, actual: Any, wanted: Any, tolerance: float = 0.0) -> None:
        if isinstance(wanted, (int, float)) and isinstance(actual, (int, float)):
            ok = math.isclose(float(actual), float(wanted), rel_tol=0.0, abs_tol=tolerance)
        else:
            ok = actual == wanted
        checks.append(
            {
                "assertion": name,
                "expected": wanted,
                "actual": actual,
                "tolerance": tolerance if isinstance(wanted, (int, float)) else None,
                "passed": ok,
            }
        )

    if "status" in expected:
        check("status", result.get("status"), expected["status"])
    if "call_count" in expected:
        check("call_count", len(result.get("calls", [])), expected["call_count"])
    verification = result.get("verification") or {}
    for key in ("misclosure_ft", "area_sq_ft"):
        if key in expected:
            check(key, verification.get(key), expected[key], expected.get(f"{key}_tolerance", 0.01))
    for index, fields in enumerate(expected.get("selected_calls", [])):
        calls = result.get("calls", [])
        actual_call = calls[index] if index < len(calls) else {}
        for field, wanted in fields.items():
            check(
                f"calls[{index}].{field}",
                actual_call.get(field),
                wanted,
                expected.get("numeric_tolerance", 0.001),
            )
    if "error_code" in expected:
        check(
            "error_code",
            [item.get("code") for item in result.get("errors", [])],
            expected["error_code"],
        )
    return checks


def _validate_case(case: Any) -> tuple[str, dict[str, Any]]:
    if not isinstance(case, dict):
        raise ValueError("case must be an object")
    case_id = str(case.get("id", "<unnamed>"))
    unknown_case_keys = set(case) - _CASE_KEYS
    if unknown_case_keys:
        raise ValueError(f"unknown case keys: {sorted(unknown_case_keys)}")
    expected = case.get("expect")
    if not isinstance(expected, dict) or not expected:
        raise ValueError("each corpus case requires explicit expectations")
    unknown_expectations = set(expected) - _EXPECTATION_KEYS
    if unknown_expectations:
        raise ValueError(f"unknown expectation keys: {sorted(unknown_expectations)}")
    if not any(
        key in expected
        for key in (
            "status",
            "call_count",
            "misclosure_ft",
            "area_sq_ft",
            "selected_calls",
            "error_code",
        )
    ):
        raise ValueError("expectations must contain at least one assertion")
    selected_calls = expected.get("selected_calls", [])
    if not isinstance(selected_calls, list):
        raise ValueError("selected_calls must be a list of field objects")
    if "selected_calls" in expected and not selected_calls:
        raise ValueError("selected_calls must contain at least one field assertion")
    known_call_fields = set(DeedCall.model_fields)
    for index, fields in enumerate(selected_calls):
        if not isinstance(fields, dict) or not fields:
            raise ValueError(f"selected_calls[{index}] must be a non-empty object")
        unknown_fields = set(fields) - known_call_fields
        if unknown_fields:
            raise ValueError(f"unknown selected call fields: {sorted(unknown_fields)}")
    return case_id, expected


def run_corpus(manifest_path: str | Path, output_path: str | Path | None = None) -> dict[str, Any]:
    """Run manifest cases independently and compare results with reviewed expectations."""
    manifest_file = Path(manifest_path).resolve()
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be an object")
    if manifest.get("schema_version") != "1.0" or not isinstance(manifest.get("cases"), list):
        raise ValueError("manifest requires schema_version '1.0' and a cases list")
    if not manifest["cases"]:
        raise ValueError("manifest cases must not be empty")
    basis = manifest.get("reviewed_basis")
    if not isinstance(basis, str) or not basis.strip():
        raise ValueError("manifest requires a non-empty reviewed_basis")
    outcomes: list[dict[str, Any]] = []
    for case in manifest["cases"]:
        case_id = str(case.get("id", "<unnamed>")) if isinstance(case, dict) else "<malformed>"
        try:
            case_id, expected = _validate_case(case)
            result = _read_case(case, manifest_file.parent)
            assertions = _assertions(result, expected)
            outcomes.append(
                {
                    "id": case_id,
                    "status": "passed" if all(item["passed"] for item in assertions) else "failed",
                    "assertions": assertions,
                    "result": result,
                }
            )
        except Exception as exc:  # isolate malformed cases so the rest of the corpus still runs
            outcomes.append(
                {
                    "id": case_id,
                    "status": "failed",
                    "assertions": [],
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                }
            )
    passed = sum(item["status"] == "passed" for item in outcomes)
    report = {
        "schema_version": "1.0",
        "status": "passed" if passed == len(outcomes) else "failed",
        "passed": passed,
        "failed": len(outcomes) - passed,
        "cases": outcomes,
    }
    if output_path is not None:
        dest = Path(output_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report
