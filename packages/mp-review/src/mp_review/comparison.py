"""Retain exact comparison requests and deterministic advisory results."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from mp_models.comparison import ComparisonManifest, ComparisonRequest
from mp_verify.comparison import compare_descriptions


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def compare_descriptions_file(input: Path | str, output_dir: Path | str) -> dict[str, Any]:
    """Compute before writing; never replace a directory or grant verified export."""
    response: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "needs_review",
        "verified_export_eligible": False,
        "boundary_established": False,
        "artifacts": {},
        "errors": [],
    }
    try:
        source, output = Path(input), Path(output_dir)
        if source.is_symlink() or not source.is_file():
            raise ValueError("request must be a regular input file")
        if output.exists() or output.is_symlink():
            raise ValueError("output must be a new directory")
        raw = source.read_bytes()
        request = ComparisonRequest.model_validate_json(raw)
        result = compare_descriptions(request)
        result_bytes = _json_bytes(result.model_dump(mode="json"))
        manifest = ComparisonManifest(
            request_sha256=hashlib.sha256(raw).hexdigest(),
            result_sha256=hashlib.sha256(result_bytes).hexdigest(),
            input_hash=result.input_hash,
            left_id=result.left_id,
            right_id=result.right_id,
        )
        files = {
            manifest.request_file: raw,
            manifest.result_file: result_bytes,
            "comparison-manifest.json": _json_bytes(manifest.model_dump(mode="json")),
        }
        output.mkdir(parents=True, exist_ok=False)
        for name, data in files.items():
            with (output / name).open("xb") as stream:
                stream.write(data)
            response["artifacts"][name] = str(output / name)
        response["input_hash"] = result.input_hash
    except (OSError, ValueError, TypeError, ArithmeticError):
        response["status"] = "error"
        response["errors"] = [
            {
                "code": "invalid_comparison_input",
                "message": "Supply a valid comparison request and a new output directory.",
            }
        ]
    return response
