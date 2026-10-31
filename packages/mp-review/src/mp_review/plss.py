"""Exact request retention and advisory supplied-reference PLSS artifacts."""

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

from mp_models.plss import PLSSDerivationRequest, PLSSDerivationResult
from mp_verify.plss import derive_plss

from .json_input import parse_json


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def _artifacts(raw: bytes, result: PLSSDerivationResult) -> dict[str, bytes]:
    files = {"request.json": raw, "plss-result.json": _json(result.model_dump(mode="json"))}
    if result.availability == "computed":
        files["prepared-layer.json"] = _json(
            {
                "schema_version": "1.1",
                "scenes": [s.model_dump(mode="json") for s in result.scenes],
                "map_sources": [s.model_dump(mode="json") for s in result.map_sources],
                "vector_layers": [s.model_dump(mode="json") for s in result.vector_layers],
                "original_base64": base64.b64encode(raw).decode(),
                "operation": {
                    "type": "computed_reference_geometry",
                    "rule": result.rule,
                    "input_hash": result.input_hash,
                    "dataset_hash": result.dataset_hash,
                    "source_hash": result.source_hash,
                    "request_sha256": hashlib.sha256(raw).hexdigest(),
                },
            }
        )
    return files


def _manifest(
    request: PLSSDerivationRequest, result: PLSSDerivationResult, files: dict[str, bytes]
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "publication_status": "complete",
        "status": "needs_review",
        "availability": result.availability,
        "purpose": "computed_reference_geometry",
        "input_hash": result.input_hash,
        "dataset_hash": result.dataset_hash,
        "source_hash": result.source_hash,
        "selected_dataset_id": request.selected_dataset_id,
        "selected_reference_id": request.selected_reference_id,
        "sha256": {name: hashlib.sha256(value).hexdigest() for name, value in files.items()},
    }


def prepare_plss_file(input: Path | str, output_dir: Path | str) -> dict[str, Any]:
    """Publish manifest last; unsupported reference evidence stays needs_review."""
    response: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "needs_review",
        "availability": None,
        "engine_verified": False,
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
        data = parse_json(raw, object_pairs_hook=_unique)
        request = PLSSDerivationRequest.model_validate(data)
        result = derive_plss(request)
        files = _artifacts(raw, result)
        manifest = _manifest(request, result, files)
        output.mkdir(parents=True, exist_ok=False)
        for name, value in files.items():
            with (output / name).open("xb") as stream:
                stream.write(value)
            response["artifacts"][name] = str(output / name)
        manifest_name = "plss-manifest.json"
        with (output / manifest_name).open("xb") as stream:
            stream.write(_json(manifest))
        response["artifacts"][manifest_name] = str(output / manifest_name)
        response.update(
            availability=result.availability, reason=result.reason, input_hash=result.input_hash
        )
    except (OSError, ValueError, TypeError, ArithmeticError) as exc:
        response["status"] = "error"
        response["errors"] = [{"code": "invalid_plss_input_or_output", "message": str(exc)}]
    return response


def replay_plss(directory: Path | str) -> PLSSDerivationResult:
    """Read-only replay of exact request, fresh derivation and every published artifact."""
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("PLSS bundle must be a regular directory")

    def read(name: str) -> bytes:
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("PLSS bundle requires regular, complete artifact files")
        return path.read_bytes()

    raw = read("request.json")
    request = PLSSDerivationRequest.model_validate(parse_json(raw, object_pairs_hook=_unique))
    result = derive_plss(request)
    expected = _artifacts(raw, result)
    manifest = parse_json(read("plss-manifest.json"), object_pairs_hook=_unique)
    if manifest != _manifest(request, result, expected):
        raise ValueError("PLSS manifest differs from fresh source/reference derivation")
    for name, data in expected.items():
        if read(name) != data:
            raise ValueError(f"PLSS artifact {name} differs from fresh source/reference derivation")
    if result.availability != "computed" and (directory / "prepared-layer.json").exists():
        raise ValueError("Unsupported PLSS result cannot contain a prepared layer")
    return result
