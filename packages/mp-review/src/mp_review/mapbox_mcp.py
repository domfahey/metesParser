"""Prepare an optional MCP request from an intact, existing geographic display."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from mp_models.dashboard import DashboardBundle, DashboardManifest
from mp_models.webmap import StandaloneWebMapInput, WebMapArtifact, WebMapRequest
from mp_verify.dashboard import _hash, _json, calculate_dashboard
from mp_verify.webmap import WebMapInput, normalize_web_map_context, validate_web_map_artifact

from .dashboard import _atomic, _load
from .map_preview import _display_files


def _read_stage(directory: Path, name: str) -> Any:
    path = directory / name
    if path.is_symlink() or not path.is_file():
        raise ValueError("Missing or linked dashboard stage")
    return _load(path)


def _read_stage_bytes(directory: Path, name: str) -> bytes:
    path = directory / name
    if path.is_symlink() or not path.is_file():
        raise ValueError("Missing or linked standalone map stage")
    return path.read_bytes()


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
        manifest = _read_stage(source, "web-map-manifest.json")
        request_data = _read_stage(source, "web-map-request.json")
        request = WebMapRequest.model_validate(request_data)
        artifact_data = _read_stage(source, "web-map.json")
        artifact = WebMapArtifact.model_validate(artifact_data)
        if not isinstance(manifest, dict) or manifest.get("schema_version") != "1.0":
            raise ValueError("Invalid online-map manifest")
        source_kind = manifest.get("source_kind", "dashboard")
        prepared: WebMapInput
        if source_kind == "standalone":
            source_bytes = _read_stage_bytes(source, "source-map.json")
            source_map = StandaloneWebMapInput.model_validate(_load(source / "source-map.json"))
            context = normalize_web_map_context(source_map)
            hashes = dict(context.input_hashes)
            from mp_export.online_map_html import online_renderer_fingerprint

            valid_standalone = (
                manifest.get("source_sha256") == hashlib.sha256(source_bytes).hexdigest()
                and manifest.get("input_hashes") == hashes
                and manifest.get("request_sha256") == _hash(request_data)
                and manifest.get("artifact_sha256") == _hash(artifact_data)
                and manifest.get("renderer_sha256") == online_renderer_fingerprint()
                and dict(artifact.input_hashes) == hashes
                and request.scene_id == artifact.scene_id
                and request.display == artifact.options
            )
            if not valid_standalone:
                raise ValueError("Standalone map stages changed; regenerate the geographic display")
            # Revalidate supplied plot geometry, explicit placements, and artifact bindings;
            # this path intentionally does not repeat projection or raster warping.
            validate_web_map_artifact(source_map, artifact)
            prepared = source_map
            source_review_complete = False
            engine_verified = False
            evidence_name = "map-evidence.html"
            evidence_key = "evidence"
        elif source_kind == "dashboard":
            bundle = DashboardBundle.model_validate(_read_stage(source, "source.json"))
            stage = DashboardManifest.model_validate(_read_stage(source, "stage-manifest.json"))
            # Recompute only canonical planar calculations; reuse geographic coordinates.
            prepared = calculate_dashboard(bundle)
            hashes = {
                key: value
                for key, value in prepared.manifest.model_dump().items()
                if key.endswith("_hash") and value is not None
            }
            if (
                manifest.get("artifact_sha256") != _hash(artifact_data)
                or manifest.get("request_sha256") != _hash(request_data)
                or manifest.get("input_hashes") != hashes
                or stage.model_dump(exclude={"cache_reused"})
                != prepared.manifest.model_dump(exclude={"cache_reused"})
                or request.scene_id != artifact.scene_id
                or request.display != artifact.options
            ):
                raise ValueError("Dashboard stages changed; regenerate the geographic display")
            source_review_complete = prepared.manifest.source_review_complete
            engine_verified = all(r.engine_verified for r in prepared.calculations)
            evidence_name = "dashboard.html"
            evidence_key = "dashboard"
        else:
            raise ValueError("Unsupported online-map source kind")
        # The handoff promises these local views for scans and source review.
        display_files = _display_files(source)
        if source_kind == "standalone":
            expected_display_names = {
                "online-map.html",
                "map-evidence.html",
                *(raster.path for raster in artifact.rasters),
            }
            actual_display_names = {name.lstrip("/") for name in display_files}
            if actual_display_names != expected_display_names:
                raise ValueError("Standalone display files differ from the prepared artifact")
            for raster in artifact.rasters:
                data = display_files.get("/" + raster.path)
                if data is None or hashlib.sha256(data).hexdigest() != raster.sha256:
                    raise ValueError("Standalone raster bytes differ from the prepared artifact")
        handoff = build_mapbox_mcp_handoff(
            prepared, artifact, style=request.view.style if style is None else style
        )
        arguments = handoff.pop("arguments")
        handoff["local_review"] = {
            evidence_key: str((source / evidence_name).resolve()),
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
            source_review_complete=source_review_complete,
            engine_verified=engine_verified,
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
