"""Prepare an optional MCP request from an intact, existing geographic display."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mp_models.dashboard import DashboardBundle, DashboardManifest
from mp_models.webmap import WebMapArtifact, WebMapRequest
from mp_verify.dashboard import _hash, _json, calculate_dashboard

from .dashboard import _atomic, _load
from .map_preview import _display_files


def _read_stage(directory: Path, name: str) -> Any:
    path = directory / name
    if path.is_symlink() or not path.is_file():
        raise ValueError("Missing or linked dashboard stage")
    return _load(path)


def mapbox_mcp_file(
    directory: Path | str,
    output_dir: Path | str,
    *,
    style: str | None = None,
) -> dict[str, Any]:
    """Stage exact tool arguments and a local provenance/omission report.

    No provider request, document reading, geographic projection or raster warp
    runs here. Hashes detect changed stages, not the authenticity of their source.
    """
    from mp_export.mapbox_mcp import build_mapbox_mcp_handoff

    result: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "needs_review",
        "verified_export_eligible": False,
        "artifacts": {},
        "errors": [],
    }
    try:
        source = Path(directory)
        output = Path(output_dir)
        if source.is_symlink() or not source.is_dir():
            raise ValueError("Input must be an existing dashboard directory")
        if output.is_symlink() or output.exists():
            raise ValueError("Output must be a new directory")
        bundle = DashboardBundle.model_validate(_read_stage(source, "source.json"))
        stage = DashboardManifest.model_validate(_read_stage(source, "stage-manifest.json"))
        request_data = _read_stage(source, "web-map-request.json")
        request = WebMapRequest.model_validate(request_data)
        artifact_data = _read_stage(source, "web-map.json")
        artifact = WebMapArtifact.model_validate(artifact_data)
        manifest = _read_stage(source, "web-map-manifest.json")
        # Recompute only canonical planar calculations; reuse geographic coordinates.
        prepared = calculate_dashboard(bundle)
        hashes = {
            key: value
            for key, value in prepared.manifest.model_dump().items()
            if key.endswith("_hash") and value is not None
        }
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema_version") != "1.0"
            or manifest.get("artifact_sha256") != _hash(artifact_data)
            or manifest.get("request_sha256") != _hash(request_data)
            or manifest.get("input_hashes") != hashes
            or stage.model_dump(exclude={"cache_reused"})
            != prepared.manifest.model_dump(exclude={"cache_reused"})
            or request.scene_id != artifact.scene_id
            or request.display != artifact.options
        ):
            raise ValueError("Dashboard stages changed; regenerate the geographic display")
        # The handoff promises these local views for scans and source review.
        _display_files(source)
        handoff = build_mapbox_mcp_handoff(
            prepared, artifact, style=request.view.style if style is None else style
        )
        arguments = handoff.pop("arguments")
        handoff["local_review"] = {
            "dashboard": str((source / "dashboard.html").resolve()),
            "online_map": str((source / "online-map.html").resolve()),
        }
        files = {"mapbox-mcp-handoff.json": _json(handoff)}
        if arguments is not None:
            files["mapbox-mcp-arguments.json"] = _json(arguments)
        output.mkdir(parents=True, exist_ok=False)
        for name, content in files.items():
            _atomic(output / name, content)
            result["artifacts"][name] = str(output / name)
        result.update(
            availability=handoff["availability"],
            tool_name=handoff["tool_name"],
            source_review_complete=prepared.manifest.source_review_complete,
            engine_verified=all(r.engine_verified for r in prepared.calculations),
        )
    except (OSError, ValueError, TypeError, ArithmeticError):
        # Validation details may contain a rejected pasted credential or source text.
        result["status"] = "error"
        result["errors"] = [
            {
                "code": "invalid_mapbox_mcp_input",
                "message": "Use an intact dashboard with online map stages, a supported style, and a new output directory. Regenerate changed or missing stages.",
            }
        ]
    return result
