"""Reopen an immutable revision into a separately published offline evidence view."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from mp_export.revision_html import render_revision
from mp_models.dashboard import DashboardBundle

from .dashboard import _atomic
from .json_input import parse_json
from .relative import _invalid_number, _unique_object
from .revisions import load_revision


def _json(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    ).encode()


def render_revision_file(
    bundle_path: Path | str, revision_dir: Path | str, output_dir: Path | str
) -> dict[str, Any]:
    """Replay before rendering; write a complete manifest only after all artifacts."""
    response: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "error",
        "artifacts": {},
        "errors": [],
        "engine_verified": False,
        "verified_export_eligible": False,
        "canonical_status_changed": False,
    }
    try:
        source, directory, output = Path(bundle_path), Path(revision_dir), Path(output_dir)
        if source.is_symlink() or not source.is_file():
            raise ValueError("Bundle must be a regular source file")
        if output.is_symlink() or output.exists():
            raise ValueError("Output must be a new directory")
        raw = source.read_bytes()
        bundle = DashboardBundle.model_validate(
            parse_json(raw, object_pairs_hook=_unique_object, parse_constant=_invalid_number)
        )
        prepared = load_revision(bundle, directory)
        draft = (directory / "revision.json").read_bytes()
        # The validated store bytes are retained for the download and offline audit.
        files = {
            "revision.json": draft,
            "prepared-revision.json": _json(prepared.model_dump(mode="json")),
            "revision.html": render_revision(bundle, prepared, draft_bytes=draft).encode(),
        }
        manifest = {
            "schema_version": "1.0",
            "publication_status": "complete",
            "status": "needs_review",
            "revision_id": prepared.revision.id,
            "generation": prepared.revision.generation,
            "state": prepared.state,
            "kind": prepared.revision.kind,
            "baseline": prepared.revision.baseline.model_dump(mode="json"),
            "bundle_sha256": hashlib.sha256(raw).hexdigest(),
            "revision_sha256": hashlib.sha256(draft).hexdigest(),
            "source_manifest_sha256": hashlib.sha256(
                (directory / "manifest.json").read_bytes()
            ).hexdigest(),
            "current_geometry": [
                {
                    "revision_id": g.revision_id,
                    "calculation_id": g.calculation_id,
                    "geometry_hash": g.plot.geometry.geometry_hash,
                }
                for g in prepared.current_geometry
            ],
            "last_valid_geometry": [
                {
                    "revision_id": g.revision_id,
                    "calculation_id": g.calculation_id,
                    "geometry_hash": g.plot.geometry.geometry_hash,
                }
                for g in prepared.last_valid_geometry
            ],
            "sha256": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
            "engine_verified": False,
            "verified_export_eligible": False,
        }
        output.mkdir(parents=True, exist_ok=False)
        for name, data in files.items():
            _atomic(output / name, data)
            response["artifacts"][name] = str(output / name)
        name = "revision-view-manifest.json"
        _atomic(output / name, _json(manifest))
        response["artifacts"][name] = str(output / name)
        response.update(
            status="needs_review",
            revision_id=prepared.revision.id,
            generation=prepared.revision.generation,
            state=prepared.state,
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        response["errors"] = [{"code": "invalid_revision_view", "message": str(exc)}]
    return response
