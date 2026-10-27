"""Explicit offline polygon import. CRS conversion is visualization evidence only."""

from __future__ import annotations

import base64
import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from mp_models.plot import LinearUnit, MapSource, PlotScene, VectorLayer
from mp_verify.scene import projected_crs_unit, validate_scene

MAX_IMPORT_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class ImportedOverlay:
    source: MapSource
    scene: PlotScene
    layers: tuple[VectorLayer, ...]
    operation: dict[str, Any]
    original_bytes: bytes

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.1",
            "map_sources": [self.source.model_dump(mode="json")],
            "scenes": [self.scene.model_dump(mode="json")],
            "vector_layers": [v.model_dump(mode="json") for v in self.layers],
            "operation": self.operation,
            "original_base64": base64.b64encode(self.original_bytes).decode(),
        }


def _projection() -> tuple[Any, Any]:
    try:
        import pyproj
        from pyproj.transformer import TransformerGroup
    except ImportError as exc:
        raise ValueError("Install mp-review[geo] to import coordinate overlays.") from exc
    return pyproj, TransformerGroup


def _linear_unit(crs: Any) -> LinearUnit:
    return projected_crs_unit(crs)


def _coordinates(value: Any, transform: Callable[..., Any], geographic: bool) -> Any:
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError("Empty or invalid geometry coordinates")
    if isinstance(value[0], (int, float)):
        if len(value) != 2 or any(isinstance(v, bool) or not math.isfinite(v) for v in value):
            raise ValueError("Positions must be finite XY pairs")
        if geographic and not (-180 <= value[0] <= 180 and -90 <= value[1] <= 90):
            raise ValueError("RFC 7946 longitude/latitude outside supported range")
        try:
            point = transform(value[0], value[1], errcheck=True)
        except Exception as exc:
            raise ValueError(f"CRS transformation failed: {exc}") from exc
        if len(point) != 2 or not all(math.isfinite(v) for v in point):
            raise ValueError("CRS transformation produced nonfinite coordinates")
        return tuple(point)
    converted = tuple(_coordinates(v, transform, geographic) for v in value)
    if geographic and isinstance(value[0][0], (int, float)):
        if any(abs(a[0] - b[0]) > 180 for a, b in zip(value, value[1:], strict=False)):
            raise ValueError("Antimeridian crossing rings require explicit preprocessing")
    return converted


def import_overlay(
    data: bytes,
    *,
    input_format: str,
    target_crs: str,
    source_crs: str | None = None,
    filename: str = "supplied-overlay.json",
) -> ImportedOverlay:
    """Convert supplied polygons with fixed XY axes and PROJ networking disabled."""
    if len(data) > MAX_IMPORT_BYTES:
        raise ValueError("Overlay exceeds 20 MiB import limit")
    try:
        value = json.loads(data)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Overlay must contain JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("Overlay must be an object")
    geographic = input_format == "geojson"
    if geographic:
        if source_crs is not None or "crs" in value:
            raise ValueError(
                "RFC 7946 source CRS is fixed WGS84 longitude/latitude; overrides are forbidden"
            )
        source_crs = "EPSG:4326"
        if value.get("type") == "FeatureCollection":
            features = value.get("features")
        elif value.get("type") == "Feature":
            features = [value]
        else:
            raise ValueError("GeoJSON requires a Feature or FeatureCollection")
    elif input_format == "projected-layer":
        declared = value.get("source_crs")
        if source_crs and declared and source_crs != declared:
            raise ValueError("Conflicting source CRS override")
        source_crs = source_crs or declared
        if not source_crs:
            raise ValueError("Projected-layer source CRS is required")
        if value.get("axis_order") != "xy" or value.get("units") not in (
            "m",
            "international_ft",
            "us_survey_ft",
        ):
            raise ValueError("Projected layer requires explicit XY axes and unambiguous units")
        if value.get("basis", "grid") != "grid":
            raise ValueError(
                "Ground coordinates require a documented ground/grid conversion, not CRS relabeling"
            )
        features = value.get("features")
    else:
        raise ValueError("Supported formats: geojson and projected-layer")
    if not isinstance(features, list) or not features:
        raise ValueError("Overlay requires at least one feature")
    pyproj, group_type = _projection()
    pyproj.network.set_network_enabled(False)
    try:
        native = pyproj.CRS.from_user_input(source_crs)
        target = pyproj.CRS.from_user_input(target_crs)
        target_unit = _linear_unit(target)
        native_unit: LinearUnit | Literal["degree"] = (
            "degree" if geographic else _linear_unit(native)
        )
        if not geographic and native_unit != value["units"]:
            raise ValueError("Declared units conflict with source CRS")
        group = group_type(native, target, always_xy=True, allow_ballpark=False)
        if not group.best_available or not group.transformers:
            raise ValueError(
                "Required transformation grids unavailable locally; ballpark operations forbidden"
            )
        transformer = group.transformers[0]
    except Exception as exc:
        raise ValueError(f"Unsupported CRS operation: {exc}") from exc
    digest = hashlib.sha256(data).hexdigest()
    source_id = f"map-{digest[:16]}"
    scene = PlotScene(
        id=f"scene-{digest[:12]}",
        name=target.to_string(),
        kind="projected",
        crs=target.to_string(),
        units=target_unit,
        basis="grid",
    )
    validate_scene(scene)
    layers = []
    ids = []
    for index, feature in enumerate(features):
        if not isinstance(feature, dict):
            raise ValueError("Feature must be an object")
        geometry = (
            feature.get("geometry")
            if geographic
            else {"type": feature.get("geometry_type"), "coordinates": feature.get("coordinates")}
        )
        if not isinstance(geometry, dict) or geometry.get("type") not in (
            "Polygon",
            "MultiPolygon",
        ):
            raise ValueError("Only Polygon and MultiPolygon geometries are supported")
        feature_id = str(feature.get("id", f"feature-{index}"))
        if feature_id in ids:
            raise ValueError("Duplicate feature IDs")
        ids.append(feature_id)
        # Validate topology before transformation too: no repair or antimeridian wrapping.
        coords = _coordinates(geometry.get("coordinates"), lambda x, y, **_: (x, y), geographic)
        VectorLayer(
            id=f"check-{index}",
            label=feature_id,
            source_id=source_id,
            scene_id=scene.id,
            geometry_type=geometry["type"],
            coordinates=coords,
        )
        converted = _coordinates(coords, transformer.transform, geographic)
        layers.append(
            VectorLayer(
                id=f"layer-{digest[:12]}-{index}",
                label=feature_id,
                source_id=source_id,
                scene_id=scene.id,
                geometry_type=geometry["type"],
                coordinates=converted,
                feature_id=feature_id,
            )
        )
    operation = {
        "definition": transformer.definition,
        "description": transformer.description,
        "reported_accuracy_m": None if transformer.accuracy < 0 else transformer.accuracy,
        "pyproj_version": pyproj.__version__,
        "proj_version": pyproj.proj_version_str,
        "proj_database_sha256": hashlib.sha256(
            (Path(pyproj.datadir.get_data_dir()) / "proj.db").read_bytes()
        ).hexdigest(),
        "source_crs_wkt": native.to_wkt(),
        "target_crs_wkt": target.to_wkt(),
        "network_enabled": False,
        "always_xy": True,
        "allow_ballpark": False,
        "purpose": "visualization_only; does not establish deed datum or orientation",
    }
    source = MapSource(
        id=source_id,
        label=filename,
        filename=filename,
        sha256=digest,
        native_crs=native.to_string(),
        native_units=native_unit,
        feature_ids=tuple(ids),
        processing_history=(json.dumps(operation, sort_keys=True),),
        data_base64=base64.b64encode(data).decode(),
    )
    return ImportedOverlay(source, scene, tuple(layers), operation, data)


def write_new_artifact(path: Path, value: dict[str, Any]) -> None:
    """Exclusive creation never overwrites a supplied input or existing artifact."""
    content = json.dumps(value, indent=2, allow_nan=False).encode() + b"\n"
    with path.open("xb") as stream:
        stream.write(content)
