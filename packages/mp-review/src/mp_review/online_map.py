"""Stage a standalone online display and its offline evidence without a dashboard."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from mp_models.webmap import StandaloneWebMapInput, WebMapRequest
from mp_verify.dashboard import _hash, _json

from .dashboard import _atomic
from .json_input import parse_json
from .relative import _invalid_number, _unique_object


def render_map_file(
    path: Path | str,
    output_dir: Path | str,
    *,
    online_map: WebMapRequest,
) -> dict[str, Any]:
    """Prepare geographic display once, preserving exact source and explicit omissions.

    Prepared plots and placement bindings are revalidated by the shared preparer.
    Source reading, selection and canonical verification are never inferred from
    display availability. Invalid input is rejected before creating output.
    """
    from mp_export.map_evidence_html import render_map_evidence
    from mp_export.online_map_html import online_renderer_fingerprint, render_online_map

    from .webmap import prepare_web_map

    result: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "needs_review",
        "engine_verified": False,
        "verified_export_eligible": False,
        "source_review_complete": False,
        "errors": [],
        "artifacts": {},
    }
    try:
        directory = Path(output_dir)
        if directory.is_symlink() or directory.exists():
            raise ValueError("Output directory must be new")
        source_path = Path(path).resolve(strict=True)
        source = source_path.read_bytes()
        source_hash = hashlib.sha256(source).hexdigest()
        result["input"] = {"name": source_path.name, "sha256": source_hash}
        prepared = StandaloneWebMapInput.model_validate(
            parse_json(
                source.decode("utf-8"),
                object_pairs_hook=_unique_object,
                parse_constant=_invalid_number,
            )
        )
        request = WebMapRequest.model_validate(online_map.model_dump(mode="json"))
        web_map = prepare_web_map(prepared, scene_id=request.scene_id, options=request.display)
        evidence_html = render_map_evidence(prepared)
        online_html = render_online_map(prepared, web_map.artifact, view=request.view)
        request_data = request.model_dump(mode="json")
        artifact_data = web_map.artifact.model_dump(mode="json")
        display_files: dict[str, bytes] = {
            "map-evidence.html": evidence_html.encode("utf-8"),
            "online-map.html": online_html.encode("utf-8"),
            **dict(web_map.assets),
        }
        manifest = {
            "schema_version": "1.0",
            "source_kind": "standalone",
            "source_sha256": source_hash,
            "input_hashes": dict(web_map.artifact.input_hashes),
            "request_sha256": _hash(request_data),
            "artifact_sha256": _hash(artifact_data),
            "renderer_sha256": online_renderer_fingerprint(),
            "files": {
                name: hashlib.sha256(data).hexdigest() for name, data in display_files.items()
            },
        }
        artifacts: dict[str, str | bytes] = {
            "source-map.json": source,
            "web-map-request.json": _json(request_data),
            "web-map.json": _json(artifact_data),
            **display_files,
            # Publish the allowlist last, after every display byte is in place.
            "web-map-manifest.json": _json(manifest),
        }
        directory.mkdir(parents=True, exist_ok=False)
        for name, content in artifacts.items():
            target = directory / name
            target.parent.mkdir(parents=True, exist_ok=True)
            _atomic(target, content)
            result["artifacts"][name] = str(target)
        result["online_map_availability"] = web_map.artifact.availability
    except (OSError, ValueError, TypeError, ArithmeticError):
        # Pydantic errors can echo rejected credentials or private source text.
        result["status"] = "error"
        result["errors"] = [
            {
                "code": "invalid_online_map_input",
                "message": "Use valid standalone prepared plots and map inputs, a matching map configuration, and a new output directory. Regenerate stale geometry or placements.",
            }
        ]
    return result
