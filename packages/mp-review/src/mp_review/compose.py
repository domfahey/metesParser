"""Compose retained display inputs through the deterministic packaged runtime."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from mp_models.dashboard import DashboardBundle
from mp_models.plot_request import PreparedPlot
from mp_models.webmap import StandaloneWebMapInput
from mp_verify.plot import validate_prepared_plot
from mp_verify.scene import validate_scene
from mp_verify.webmap import normalize_web_map_context

from .dashboard import _atomic, prepare_dashboard
from .plot import _json

_MAP_FIELDS = ("scenes", "map_sources", "vector_layers", "raster_layers")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _retain(path: Path, name: str, files: dict[str, bytes]) -> Any:
    # Read once: the retained bytes must be exactly the bytes being validated.
    import json

    from .plot import _finite_json
    from .relative import _invalid_number, _unique_object

    content = path.read_bytes()
    value = json.loads(
        content.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_invalid_number
    )
    _finite_json(value)
    files[name] = content
    return value


def _append_layers(
    value: dict[str, Any], layers: Sequence[Path | str], files: dict[str, bytes]
) -> None:
    for index, path in enumerate(layers, 1):
        layer = _retain(Path(path), f"inputs/layer-{index}.json", files)
        if not isinstance(layer, dict) or not any(key in layer for key in _MAP_FIELDS):
            raise ValueError("Prepared layer must contain supported map arrays")
        for key in _MAP_FIELDS:
            supplied = layer.get(key, [])
            if not isinstance(supplied, list):
                raise ValueError(f"Prepared layer {key} must be an array")
            value[key] = value.get(key, []) + supplied


def _plot(directory: Path, files: dict[str, bytes]) -> PreparedPlot:
    request = _retain(directory / "plot-input.json", "inputs/plot/plot-input.json", files)
    geometry = _retain(directory / "plot-geometry.json", "inputs/plot/plot-geometry.json", files)
    manifest = _retain(directory / "plot-manifest.json", "inputs/plot/plot-manifest.json", files)
    if not isinstance(manifest, dict):
        raise ValueError("Plot manifest must be an object")
    for field, filename in (
        ("plot_input_sha256", "plot-input.json"),
        ("plot_geometry_sha256", "plot-geometry.json"),
    ):
        if manifest.get(field) != _sha(files[f"inputs/plot/{filename}"]):
            raise ValueError("Plot artifact does not match its manifest")
    source_paths = [
        p
        for name in ("source.json", "source.csv", "source.txt")
        if (p := directory / name).is_file()
    ]
    if len(source_paths) != 1:
        raise ValueError(
            "Plot stage requires exactly one retained source.json, source.csv or source.txt"
        )
    source = source_paths[0].read_bytes()
    if manifest.get("source_sha256") != _sha(source):
        raise ValueError("Plot source does not match its manifest")
    files[f"inputs/plot/{source_paths[0].name}"] = source
    fresh = validate_prepared_plot(
        PreparedPlot.model_validate(
            {"request": request, "geometry": geometry, "input_hash": manifest["input_hash"]}
        )
    )
    if manifest.get("geometry_hash") != fresh.geometry.geometry_hash:
        raise ValueError("Plot manifest geometry hash is stale")
    return fresh


def _compose(
    path: Path | str,
    output_dir: Path | str,
    layers: Sequence[Path | str],
    *,
    standalone: bool,
) -> dict[str, Any]:
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
        files: dict[str, bytes] = {}
        source: StandaloneWebMapInput | DashboardBundle
        if standalone:
            prepared_plot = _plot(Path(path), files)
            value = {
                "schema_version": "1.0",
                "title": prepared_plot.request.title,
                "plots": [prepared_plot.model_dump(mode="json")],
            }
            _append_layers(value, layers, files)
            source = StandaloneWebMapInput.model_validate(value)
            context = normalize_web_map_context(source)
            for scene in context.scenes:
                validate_scene(scene)
            if context.raster_layers:
                from .raster_registration import validate_raster_layer

                scenes = {scene.id: scene for scene in context.scenes}
                for raster in context.raster_layers:
                    validate_raster_layer(raster, scenes[raster.scene_id])
            geometries = context.geometries
            filename = "map-input.json"
        else:
            value = _retain(Path(path), "inputs/base-bundle.json", files)
            # Validate the original ledger before adapting its optional map fields.
            DashboardBundle.model_validate(value)
            value["schema_version"] = "1.1"
            _append_layers(value, layers, files)
            prepared = prepare_dashboard(DashboardBundle.model_validate(value))
            source = prepared.bundle
            geometries = prepared.plots.geometries
            filename = "bundle.json"
        hashes = {geometry.calculation_id: geometry.geometry_hash for geometry in geometries}
        manifest = {
            "schema_version": "1.0",
            "kind": "standalone-map" if standalone else "dashboard",
            "inputs": {name: _sha(content) for name, content in files.items()},
            "geometry_hashes": hashes,
            "engine_verified": False,
            "verified_export_eligible": False,
            "source_review_complete": False,
        }
        files[filename] = _json(source.model_dump(mode="json")).encode("utf-8")
        files["composition-manifest.json"] = _json(manifest).encode("utf-8")
        directory.mkdir(parents=True, exist_ok=False)
        for name, content in files.items():
            target = directory / name
            target.parent.mkdir(parents=True, exist_ok=True)
            _atomic(target, content)
            result["artifacts"][name] = str(target)
        result["geometry_hashes"] = hashes
    except (OSError, ValueError, TypeError, KeyError, ArithmeticError):
        # Validation errors can echo private deed text or pasted credentials.
        result["status"] = "error"
        result["errors"] = [
            {
                "code": "invalid_composition",
                "message": "Supply intact plot stages or a valid source bundle, supported prepared map arrays with unique IDs, and a new output directory. Regenerate stale geometry or placements.",
            }
        ]
    return result


def compose_map_file(
    plot_directory: Path | str,
    output_dir: Path | str,
    *,
    layers: Sequence[Path | str] = (),
) -> dict[str, Any]:
    """Compose one intact plot and explicit map arrays; no placements are inferred."""
    return _compose(plot_directory, output_dir, layers, standalone=True)


def compose_dashboard_file(
    path: Path | str,
    output_dir: Path | str,
    *,
    layers: Sequence[Path | str] = (),
) -> dict[str, Any]:
    """Extend a supplied source ledger and recompute dashboard geometry without rendering."""
    return _compose(path, output_dir, layers, standalone=False)
