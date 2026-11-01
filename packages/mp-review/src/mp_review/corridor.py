"""Standalone corridor artifacts retaining raw and canonical construction inputs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from mp_models.corridor import CorridorManifest, CorridorRequest, CorridorResult
from mp_verify.corridor import analyze_corridor, validate_corridor_result

from .dashboard import _atomic
from .plot import _finite_json
from .relative import _invalid_number, _unique_object


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def _sha(data: str | bytes) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def _read(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Corridor artifact must be an existing regular file")
    return path.read_bytes()


def _payload(data: bytes) -> Any:
    result = json.loads(data, object_pairs_hook=_unique_object, parse_constant=_invalid_number)
    _finite_json(result)
    return result


def analyze_corridor_file(input: Path | str, output_dir: Path | str) -> dict[str, Any]:
    """Publish advisory artifacts in a new directory; manifest is the final write.

    A valid but unsupported construction is a completed ``needs_review`` result.
    No input, centerline or width observation is replaced by the derived polygon.
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
        source = _read(Path(input))
        request = CorridorRequest.model_validate(_payload(source))
        corridor = analyze_corridor(request)
        canonical = _json(corridor.request.model_dump(mode="json"))
        rendered = _json(corridor.model_dump(mode="json"))
        artifacts: dict[str, str | bytes] = {
            "request.json": source,
            "corridor-request.json": canonical,
            "corridor.json": rendered,
        }
        metadata: dict[str, Any] = {
            "source_sha256": _sha(source),
            "canonical_request_sha256": _sha(canonical),
            "result_sha256": _sha(rendered),
            "input_sha256": corridor.input_sha256,
        }
        if corridor.centerline is not None:
            artifacts["centerline-prepared.json"] = _json(
                corridor.centerline.model_dump(mode="json")
            )
            metadata["centerline_plot_sha256"] = _sha(artifacts["centerline-prepared.json"])
        if corridor.boundary is not None:
            from mp_export.plot_html import (
                render_plot,
            )

            artifacts["boundary-prepared.json"] = _json(corridor.boundary.model_dump(mode="json"))
            artifacts["boundary.html"] = render_plot(corridor.boundary)
            metadata["boundary_plot_sha256"] = _sha(artifacts["boundary-prepared.json"])
            metadata["boundary_html_sha256"] = _sha(artifacts["boundary.html"])
        manifest = CorridorManifest.model_validate(metadata)
        directory.mkdir(parents=True, exist_ok=False)
        for name, data in artifacts.items():
            _atomic(directory / name, data)
            result["artifacts"][name] = str(directory / name)
        _atomic(directory / "corridor-manifest.json", _json(manifest.model_dump(mode="json")))
        result["artifacts"]["corridor-manifest.json"] = str(directory / "corridor-manifest.json")
        result.update(
            corridor=corridor.model_dump(mode="json"), manifest=manifest.model_dump(mode="json")
        )
    except (OSError, ValueError, TypeError, ArithmeticError):
        result["status"] = "error"
        result["errors"] = [
            {
                "code": "invalid_corridor_input",
                "message": "Use a valid source-bound corridor request and a new output directory.",
            }
        ]
    return result


def replay_corridor(directory: Path | str) -> CorridorResult:
    """Validate every retained artifact and rebuild geometry from the full request."""
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Corridor bundle must be a regular directory")
    manifest = CorridorManifest.model_validate(
        _payload(_read(directory / "corridor-manifest.json"))
    )
    source = _read(directory / manifest.source_file)
    canonical = _read(directory / manifest.canonical_request_file)
    result_bytes = _read(directory / manifest.result_file)
    if (_sha(source), _sha(canonical), _sha(result_bytes)) != (
        manifest.source_sha256,
        manifest.canonical_request_sha256,
        manifest.result_sha256,
    ):
        raise ValueError("Corridor artifact content differs from its manifest")
    request = CorridorRequest.model_validate(_payload(source))
    if request != CorridorRequest.model_validate(_payload(canonical)):
        raise ValueError("Canonical corridor definition differs from its exact source input")
    result = CorridorResult.model_validate(_payload(result_bytes))
    if result.request != request or result.input_sha256 != manifest.input_sha256:
        raise ValueError("Corridor identities differ from retained construction inputs")
    fresh = validate_corridor_result(result)
    for name, expected, model in (
        ("centerline-prepared.json", manifest.centerline_plot_sha256, fresh.centerline),
        ("boundary-prepared.json", manifest.boundary_plot_sha256, fresh.boundary),
    ):
        if model is None:
            if expected is not None or (directory / name).exists():
                raise ValueError("Unexpected prepared geometry for unsupported corridor")
        else:
            data = _read(directory / name)
            if (
                expected is None
                or _sha(data) != expected
                or _payload(data) != model.model_dump(mode="json")
            ):
                raise ValueError("Corridor prepared plot differs from fresh geometry")
    if manifest.boundary_html_sha256 is not None:
        from mp_export.plot_html import render_plot

        data = _read(directory / "boundary.html")
        if (
            fresh.boundary is None
            or _sha(data) != manifest.boundary_html_sha256
            or data.decode("utf-8") != render_plot(fresh.boundary)
        ):
            raise ValueError("Corridor display differs from fresh boundary geometry")
    elif fresh.boundary is not None or (directory / "boundary.html").exists():
        raise ValueError("Corridor display identity is missing or unexpected")
    return fresh
