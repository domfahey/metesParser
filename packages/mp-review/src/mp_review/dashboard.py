"""Atomic dashboard staging and intact cache reuse, with no document-reading claims."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from mp_models.dashboard import (
    DashboardBundle,
    DashboardDescriptionComparison,
    DashboardDiagnosis,
    DashboardManifest,
    DashboardResult,
    PreparedDashboard,
)
from mp_models.webmap import WebMapRequest
from mp_verify.dashboard import (
    _hash,
    _json,
    _source_data,
)
from mp_verify.dashboard import (
    validate_prepared_dashboard as validate_prepared_dashboard,
)

from .relative import _invalid_number, _unique_object


def _atomic(path: Path, content: str | bytes) -> None:
    """Publish a complete stage without exposing a partial JSON or HTML file."""
    if path.is_symlink():
        raise ValueError(f"Refusing symlink output: {path.name}")
    with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content.encode("utf-8") if isinstance(content, str) else content)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_unique_object,
        parse_constant=_invalid_number,
    )


def prepare_dashboard(
    bundle: DashboardBundle, cache_dir: Path | str | None = None
) -> PreparedDashboard:
    """Validate source ledger and compute record-only results, optionally reusing intact stages.

    The input schema accepts no engine flags/results. A cache hit requires matching source,
    assumptions, calculator version and hashes of both persisted source and calculation stages.
    Cache reuse preserves source review and persisted payloads; geometry is freshly checked
    even for cache hits. It never reruns extraction or document reading. Hashing a source
    never means that somebody reviewed it.
    """
    from mp_verify.dashboard import calculate_dashboard, map_stage

    fresh = calculate_dashboard(bundle)
    bundle = fresh.bundle
    if bundle.raster_layers:
        from .raster_registration import validate_raster_layer

        scenes = {scene.id: scene for scene in bundle.scenes}
        for layer in bundle.raster_layers:
            validate_raster_layer(layer, scenes[layer.scene_id])
    source = _source_data(bundle)
    directory = Path(cache_dir) if cache_dir is not None else None
    reused = False
    if directory is not None:
        if directory.is_symlink():
            raise ValueError("Cache directory must not be a symlink")
        directory.mkdir(parents=True, exist_ok=True)
        try:
            manifest = DashboardManifest.model_validate(_load(directory / "stage-manifest.json"))
            saved_source = _load(directory / "source-review.json")
            saved = _load(directory / "calculations.json")
            saved_diagnostics = _load(directory / "diagnostics.json")
            saved_comparisons = _load(directory / "description-comparisons.json")
            reused = (
                manifest.calculator_version == fresh.manifest.calculator_version
                and manifest.description_comparisons_input_hash
                == fresh.manifest.description_comparisons_input_hash
                and manifest.description_comparisons_output_hash
                == fresh.manifest.description_comparisons_output_hash
                == _hash(saved_comparisons)
                and tuple(
                    DashboardDescriptionComparison.model_validate(item)
                    for item in saved_comparisons
                )
                == fresh.description_comparisons
                and manifest.diagnostics_input_hash == fresh.manifest.diagnostics_input_hash
                and manifest.diagnostics_output_hash
                == fresh.manifest.diagnostics_output_hash
                == _hash(saved_diagnostics)
                and tuple(DashboardDiagnosis.model_validate(item) for item in saved_diagnostics)
                == fresh.diagnostics
                and manifest.calculation_input_hash == fresh.manifest.calculation_input_hash
                and manifest.source_review_hash
                == fresh.manifest.source_review_hash
                == _hash(saved_source)
                and manifest.calculation_output_hash == _hash(saved)
                and tuple(DashboardResult.model_validate(item) for item in saved)
                == fresh.calculations
            )
        except (OSError, ValueError, TypeError):
            pass  # Incomplete/tampered/old stages are recomputed, never trusted.
    manifest = fresh.manifest.model_copy(update={"cache_reused": reused})
    prepared = PreparedDashboard(
        bundle=bundle,
        calculations=fresh.calculations,
        manifest=manifest,
        plots=fresh.plots,
        diagnostics=fresh.diagnostics,
        description_comparisons=fresh.description_comparisons,
    )
    if directory is not None:
        stages = {
            "source-review.json": source,
            "diagnostics.json": [d.model_dump(mode="json") for d in prepared.diagnostics],
            "description-comparisons.json": [
                c.model_dump(mode="json") for c in prepared.description_comparisons
            ],
            "calculations.json": [r.model_dump(mode="json") for r in prepared.calculations],
            "plot-geometry.json": [g.model_dump(mode="json") for g in prepared.plots.geometries],
            "map-layers.json": map_stage(bundle),
            "placements.json": {
                "placements": [p.model_dump(mode="json") for p in prepared.plots.placements],
                "comparisons": [c.model_dump(mode="json") for c in prepared.plots.comparisons],
            },
            "stage-manifest.json": manifest.model_dump(mode="json"),
        }
        for name, data in stages.items():
            _atomic(directory / name, _json(data))
    return prepared


def dashboard_file(
    path: Path | str,
    output_dir: Path | str,
    *,
    cache_dir: Path | str | None = None,
    online_map: WebMapRequest | None = None,
) -> dict[str, Any]:
    """Stage an offline review and, when requested, a separate baseline online view."""
    from mp_export.dashboard_html import (
        render_dashboard,
        renderer_fingerprint,
    )
    from mp_verify.dashboard import map_stage

    result: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "needs_review",
        "errors": [],
        "artifacts": {},
    }
    try:
        if online_map is not None:
            online_map = WebMapRequest.model_validate(online_map.model_dump(mode="json"))
        source_path = Path(path)
        directory = Path(output_dir)
        if directory.is_symlink() or directory.exists():
            raise ValueError("Output directory must not already exist or be a symlink")
        source_path = source_path.resolve(strict=True)
        directory = directory.resolve()
        artifact_names = (
            "source.json",
            "dashboard.html",
            "source-review.json",
            "calculations.json",
            "stage-manifest.json",
            "render-manifest.json",
        )
        if any((directory / name).resolve() == source_path for name in artifact_names):
            raise ValueError("Output must not overwrite the original input bundle")
        source = source_path.read_bytes()
        result["input"] = {"name": source_path.name, "sha256": hashlib.sha256(source).hexdigest()}
        bundle = DashboardBundle.model_validate(
            json.loads(
                source.decode("utf-8"),
                object_pairs_hook=_unique_object,
                parse_constant=_invalid_number,
            )
        )
        directory.mkdir(parents=True, exist_ok=False)
        prepared = prepare_dashboard(bundle, cache_dir=cache_dir)
        output = render_dashboard(prepared)
        render_manifest = {
            "renderer_sha256": renderer_fingerprint(),
            "html_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
            "presentation_hash": prepared.manifest.presentation_hash,
        }
        artifacts: dict[str, str | bytes] = {
            "source.json": source,
            "diagnostics.json": _json([d.model_dump(mode="json") for d in prepared.diagnostics]),
            "description-comparisons.json": _json(
                [c.model_dump(mode="json") for c in prepared.description_comparisons]
            ),
            "dashboard.html": output,
            "source-review.json": _json(_source_data(bundle)),
            "calculations.json": _json([r.model_dump(mode="json") for r in prepared.calculations]),
            "stage-manifest.json": _json(prepared.manifest.model_dump(mode="json")),
            "render-manifest.json": _json(render_manifest),
            "plot-geometry.json": _json(
                [g.model_dump(mode="json") for g in prepared.plots.geometries]
            ),
            "map-layers.json": _json(map_stage(bundle)),
            "placements.json": _json(
                {
                    "placements": [p.model_dump(mode="json") for p in prepared.plots.placements],
                    "comparisons": [c.model_dump(mode="json") for c in prepared.plots.comparisons],
                }
            ),
        }
        online_manifest = None
        if online_map is not None:
            from mp_export.online_map_html import (
                online_renderer_fingerprint,
                render_online_map,
            )

            from .webmap import prepare_web_map

            web_map = prepare_web_map(
                prepared, scene_id=online_map.scene_id, options=online_map.display
            )
            online_html = render_online_map(prepared, web_map.artifact, view=online_map.view)
            request_data = online_map.model_dump(mode="json")
            display_data = web_map.artifact.model_dump(mode="json")
            artifacts.update(
                {
                    "web-map-request.json": _json(request_data),
                    "web-map.json": _json(display_data),
                    "online-map.html": online_html,
                    **dict(web_map.assets),
                }
            )
            display_files = {
                "dashboard.html": output.encode("utf-8"),
                "online-map.html": online_html.encode("utf-8"),
                **dict(web_map.assets),
            }
            online_manifest = {
                "schema_version": "1.0",
                "input_hashes": dict(web_map.artifact.input_hashes),
                "request_sha256": _hash(request_data),
                "artifact_sha256": _hash(display_data),
                "renderer_sha256": online_renderer_fingerprint(),
                "files": {
                    name: hashlib.sha256(data).hexdigest() for name, data in display_files.items()
                },
            }
            result["online_map_availability"] = web_map.artifact.availability
        for name, content in artifacts.items():
            if (directory / name).resolve() == Path(path).resolve():
                raise ValueError("Output must not overwrite the original input bundle")
            (directory / name).parent.mkdir(parents=True, exist_ok=True)
            _atomic(directory / name, content)
            result["artifacts"][name] = str(directory / name)
        # Publish the preview allowlist only after every declared display byte is present.
        if online_manifest is not None:
            _atomic(directory / "web-map-manifest.json", _json(online_manifest))
            result["artifacts"]["web-map-manifest.json"] = str(directory / "web-map-manifest.json")
        # Use validated IDs, never a supplied filename, for retained source bytes.
        originals = {
            item.id: base64.b64decode(item.data_base64, validate=True)
            for item in bundle.map_sources
            if item.data_base64 is not None
        }
        for layer in bundle.raster_layers:
            originals.setdefault(
                layer.source_id, base64.b64decode(layer.data_base64, validate=True)
            )
        if originals:
            (directory / "assets").mkdir()
        for source_id, data in originals.items():
            name = f"assets/{source_id}.bin"
            _atomic(directory / name, data)
            result["artifacts"][name] = str(directory / name)
        result.update(
            source_review_complete=prepared.manifest.source_review_complete,
            cache_reused=prepared.manifest.cache_reused,
            engine_verified=all(r.engine_verified for r in prepared.calculations),
            verified_export_eligible=False,
            manifest=prepared.manifest.model_dump(mode="json"),
            render_manifest=render_manifest,
        )
    except (ValueError, TypeError, OSError, ArithmeticError) as exc:
        result["status"] = "error"
        result["errors"].append({"code": "invalid_dashboard", "message": str(exc)})
    return result
