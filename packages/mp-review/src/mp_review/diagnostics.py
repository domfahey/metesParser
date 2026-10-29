"""Retain exact requests and fresh, non-verifying closure diagnosis artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from mp_models.diagnostics import ClosureDiagnosticRequest
from mp_verify.diagnostics import diagnose_closure

from .dashboard import _atomic
from .plot import _finite_json
from .relative import _invalid_number, _unique_object


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"


def _sha(data: str | bytes) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def diagnose_closure_file(input: Path | str, output_dir: Path | str) -> dict[str, Any]:
    """Complete an advisory analysis in a new directory, preserving request bytes.

    ``needs_review`` includes unsupported/incomplete calculations; malformed requests
    and existing output directories return ``error`` without running export.
    """
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "needs_review",
        "engine_verified": False,
        "verified_export_eligible": False,
        "source_review_complete": False,
        "artifacts": {},
        "errors": [],
    }
    try:
        directory = Path(output_dir)
        if directory.is_symlink() or directory.exists():
            raise ValueError("Output must be a new directory")
        source_path = Path(input)
        if source_path.is_symlink() or not source_path.is_file():
            raise ValueError("Input must be an existing regular request file")
        data = source_path.read_bytes()
        payload = json.loads(data, object_pairs_hook=_unique_object, parse_constant=_invalid_number)
        _finite_json(payload)
        request = ClosureDiagnosticRequest.model_validate(payload)
        diagnostics = diagnose_closure(request)
        rendered = _json(diagnostics.model_dump(mode="json"))
        manifest = {
            "schema_version": "1.0",
            "artifact_kind": "closure_diagnostics",
            "algorithm_version": diagnostics.algorithm_version,
            "source_file": "request.json",
            "source_sha256": _sha(data),
            "request_sha256": diagnostics.request_sha256,
            "input_id": request.input_id,
            "request_id": request.request_id,
            "input_sha256": diagnostics.input_sha256,
            "diagnostics_file": "diagnostics.json",
            "diagnostics_sha256": _sha(rendered),
            "availability": diagnostics.availability,
            "engine_verified": False,
            "verified_export_eligible": False,
            "source_review_complete": False,
        }
        artifacts: dict[str, str | bytes] = {
            "request.json": data,
            "diagnostics.json": rendered,
            "diagnostics-manifest.json": _json(manifest),
        }
        directory.mkdir(parents=True, exist_ok=False)
        for name, content in artifacts.items():
            _atomic(directory / name, content)
            result["artifacts"][name] = str(directory / name)
        result.update(diagnostics=diagnostics.model_dump(mode="json"), manifest=manifest)
    except (OSError, ValueError, TypeError, ArithmeticError):
        result["status"] = "error"
        result["errors"] = [
            {
                "code": "invalid_diagnostics_input",
                "message": "Use a valid identity-bound diagnostics request and a new output directory.",
            }
        ]
    return result
