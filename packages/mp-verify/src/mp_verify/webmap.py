"""Validate prepared web-map identities without deriving geographic coordinates."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass

from mp_models.dashboard import DashboardCall, PreparedDashboard
from mp_models.plot import (
    LinearUnit,
    MapSource,
    PlotGeometry,
    PlotPlacement,
    PlotScene,
    VectorLayer,
)
from mp_models.plot_request import PlotCall
from mp_models.raster import RasterLayer
from mp_models.webmap import (
    StandaloneWebMapInput,
    WebMapArtifact,
    WebMapFeature,
    WebMapLine,
    WebMapPoint,
    WebMapPolygon,
)

from mp_verify.dashboard import validate_prepared_dashboard
from mp_verify.plot import validate_plot_placement, validate_prepared_plot

Extent = tuple[float, float, float, float]


def bounds_of(points: Sequence[tuple[float, float]]) -> Extent | None:
    """Bounds of the finite points, or ``None``."""
    finite = [p for p in points if all(math.isfinite(v) for v in p)]
    if not finite:
        return None
    return (
        min(p[0] for p in finite),
        min(p[1] for p in finite),
        max(p[0] for p in finite),
        max(p[1] for p in finite),
    )


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


WebMapInput = PreparedDashboard | StandaloneWebMapInput


@dataclass(frozen=True)
class WebMapContext:
    """Validated shared evidence for display, with no synthetic dashboard entities."""

    title: str
    scenes: tuple[PlotScene, ...]
    map_sources: tuple[MapSource, ...]
    vector_layers: tuple[VectorLayer, ...]
    raster_layers: tuple[RasterLayer, ...]
    geometries: tuple[PlotGeometry, ...]
    placements: tuple[PlotPlacement, ...]
    calls: tuple[PlotCall | DashboardCall, ...]
    foot_definitions: tuple[tuple[str, LinearUnit], ...]
    input_hashes: tuple[tuple[str, str], ...]


def normalize_web_map_context(prepared: WebMapInput) -> WebMapContext:
    """Recompute every input geometry and preserve existing dashboard manifest hashes."""
    if isinstance(prepared, PreparedDashboard):
        prepared = PreparedDashboard.model_validate(prepared.model_dump())
        prepared = validate_prepared_dashboard(prepared)
        bundle = prepared.bundle
        return WebMapContext(
            title=bundle.title,
            scenes=bundle.scenes,
            map_sources=bundle.map_sources,
            vector_layers=bundle.vector_layers,
            raster_layers=bundle.raster_layers,
            geometries=prepared.plots.geometries,
            placements=prepared.plots.placements,
            calls=bundle.calls,
            foot_definitions=tuple((s.id, s.frame.foot_definition) for s in bundle.calculations),
            input_hashes=tuple(
                (key, value)
                for key, value in prepared.manifest.model_dump().items()
                if key.endswith("_hash") and value is not None
            ),
        )
    if not isinstance(prepared, StandaloneWebMapInput):
        raise TypeError("online map requires a prepared dashboard or standalone map input")
    standalone = StandaloneWebMapInput.model_validate(prepared.model_dump())
    plots = tuple(validate_prepared_plot(plot) for plot in standalone.plots)
    geometries = {plot.request.calculation_id: plot.geometry for plot in plots}
    units = {plot.request.calculation_id: plot.request.foot_definition for plot in plots}
    scenes = {scene.id: scene for scene in standalone.scenes}
    for placement in standalone.placements:
        validate_plot_placement(
            geometries[placement.calculation_id],
            placement,
            scenes[placement.scene_id],
            native_units=units[placement.calculation_id],
            orientation_supported=False,
            allow_unknown_units=True,
        )
    data = standalone.model_dump(mode="json")
    return WebMapContext(
        title=standalone.title,
        scenes=standalone.scenes,
        map_sources=standalone.map_sources,
        vector_layers=standalone.vector_layers,
        raster_layers=standalone.raster_layers,
        geometries=tuple(plot.geometry for plot in plots),
        placements=standalone.placements,
        calls=tuple(call for plot in plots for call in plot.request.calls),
        foot_definitions=tuple(units.items()),
        input_hashes=(
            ("standalone_input_hash", _digest(data)),
            ("plot_input_hash", _digest([plot.request.model_dump(mode="json") for plot in plots])),
            (
                "plot_output_hash",
                _digest([plot.geometry.model_dump(mode="json") for plot in plots]),
            ),
            (
                "map_input_hash",
                _digest(
                    {
                        key: data[key]
                        for key in ("scenes", "map_sources", "vector_layers", "raster_layers")
                    }
                ),
            ),
            ("placement_input_hash", _digest(data["placements"])),
        ),
    )


# Display coordinates are WGS84 degrees; 1e-9 degree is about 0.1 mm.
_COORDINATE_TOLERANCE_DEG = 1e-9
_NATIVE_JOIN_TOLERANCE = 1e-6
_CLOSURE_GAP_THRESHOLD = 1e-8


def _near(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return (
        abs(a[0] - b[0]) <= _COORDINATE_TOLERANCE_DEG
        and abs(a[1] - b[1]) <= _COORDINATE_TOLERANCE_DEG
    )


def feature_vertices(feature: WebMapFeature) -> list[tuple[float, float]]:
    geometry = feature.geometry
    if isinstance(geometry, WebMapPoint):
        return [geometry.coordinates]
    if isinstance(geometry, WebMapLine):
        return list(geometry.coordinates)
    if isinstance(geometry, WebMapPolygon):
        return [p for ring in geometry.coordinates for p in ring]
    return [p for polygon in geometry.coordinates for ring in polygon for p in ring]


def _validate_completeness(context: WebMapContext, artifact: WebMapArtifact, scene_id: str) -> None:
    """Require the complete expected feature set and internally consistent coordinates.

    Geographic coordinates cannot be re-derived here (no projection library), but
    the canonical geometry fixes which features must exist and how their endpoints
    must coincide, so omissions and moved vertices are rejected.
    """
    if artifact.projection is None:
        return  # Nothing is claimed as displayed.
    items = artifact.unavailable
    scene_level = any(item.kind == "scene" for item in items)
    omitted = {(item.kind, item.item_id): item.code for item in items}
    by_placement: dict[str, list[WebMapFeature]] = {}
    for feature in artifact.features:
        if feature.properties.placement_id is not None:
            by_placement.setdefault(feature.properties.placement_id, []).append(feature)
    if not scene_level:
        for geometry in context.geometries:
            placements = [
                p
                for p in context.placements
                if p.calculation_id == geometry.calculation_id and p.scene_id == scene_id
            ]
            shown = [
                f
                for f in artifact.features
                if f.properties.calculation_id == geometry.calculation_id
            ]
            if not shown:
                if ("calculation", geometry.calculation_id) not in omitted:
                    raise ValueError(
                        "online display is incomplete: calculation neither shown nor omitted"
                    )
                continue
            if (
                geometry.completeness != "complete"
                and omitted.get(("calculation", geometry.calculation_id)) != "partial_geometry"
            ):
                raise ValueError("online display is incomplete: partial geometry is not disclosed")
            for placement in placements:
                _validate_deed_set(geometry, by_placement.get(placement.id, []))
        shown_layers = {f.properties.layer_id for f in artifact.features}
        for layer in context.vector_layers:
            if (
                layer.scene_id == scene_id
                and layer.id not in shown_layers
                and ("vector", layer.id) not in omitted
            ):
                raise ValueError(
                    "online display is incomplete: vector layer neither shown nor omitted"
                )
        shown_rasters = {r.id for r in artifact.rasters}
        for raster in context.raster_layers:
            if (
                raster.scene_id == scene_id
                and raster.id not in shown_rasters
                and ("raster", raster.id) not in omitted
            ):
                raise ValueError("online display is incomplete: raster neither shown nor omitted")
    points = [p for f in artifact.features for p in feature_vertices(f)]
    points.extend(p for r in artifact.rasters for p in r.corners)
    expected = bounds_of(points)
    if expected is not None:
        if artifact.bounds is None or any(
            abs(a - b) > _COORDINATE_TOLERANCE_DEG
            for a, b in zip(artifact.bounds, expected, strict=True)
        ):
            raise ValueError("online display bounds do not match feature coordinates")


def _validate_deed_set(geometry: PlotGeometry, features: list[WebMapFeature]) -> None:
    courses = [f for f in features if f.properties.kind == "recorded_course"]
    pobs = [f for f in features if f.properties.kind == "pob"]
    gaps = [f for f in features if f.properties.kind == "closure_gap"]
    primitives = geometry.primitives
    first, last = primitives[0].start, primitives[-1].end
    wants_gap = (
        geometry.completeness == "complete"
        and math.hypot(last[0] - first[0], last[1] - first[1]) > _CLOSURE_GAP_THRESHOLD
    )
    if (
        sorted(f.properties.call_id or "" for f in courses) != sorted(p.call_id for p in primitives)
        or len(pobs) != 1
        or len(gaps) != (1 if wants_gap else 0)
    ):
        raise ValueError(
            "online display is incomplete: expected courses, point of beginning or closure gap"
        )
    by_call = {f.properties.call_id: f for f in courses}
    chain = [feature_vertices(by_call[p.call_id]) for p in primitives]
    if any(len(c) < 2 for c in chain):
        raise ValueError("online display coordinate mismatch: course has no extent")
    for (a, b), (ca, cb) in zip(
        zip(primitives, primitives[1:], strict=False),
        zip(chain, chain[1:], strict=False),
        strict=False,
    ):
        joined = math.hypot(a.end[0] - b.start[0], a.end[1] - b.start[1]) <= _NATIVE_JOIN_TOLERANCE
        if joined and not _near(ca[-1], cb[0]):
            raise ValueError("online display coordinate mismatch: chained courses do not meet")
    if not _near(feature_vertices(pobs[0])[0], chain[0][0]):
        raise ValueError("online display coordinate mismatch: point of beginning")
    if gaps:
        gap = feature_vertices(gaps[0])
        if not (_near(gap[0], chain[-1][-1]) and _near(gap[-1], chain[0][0])):
            raise ValueError("online display coordinate mismatch: closure gap endpoints")


def _validate_bindings(context: WebMapContext, artifact: WebMapArtifact) -> None:
    """Check upstream identities without recreating geographic coordinates.

    Coordinate derivation and derived PNG byte validation belong to preparation
    and staging; this validator independently rejects forged evidence bindings.
    """
    scene = next((item for item in context.scenes if item.id == artifact.scene_id), None)
    if scene is None:
        raise ValueError("online display scene does not exist")
    geometries = {item.calculation_id: item for item in context.geometries}
    placements = {item.id: item for item in context.placements}
    calls = {item.id: item for item in context.calls}
    vectors = {item.id: item for item in context.vector_layers}
    sources = {item.id for item in context.map_sources}
    for feature in artifact.features:
        props = feature.properties
        if props.kind == "parcel_context":
            vector = vectors.get(props.layer_id or "")
            if (
                vector is None
                or vector.scene_id != scene.id
                or props.source_id != vector.source_id
                or vector.source_id not in sources
                or feature.geometry.type != vector.geometry_type
            ):
                raise ValueError("stale online context binding")
            continue
        geometry = geometries.get(props.calculation_id or "")
        placement = placements.get(props.placement_id or "")
        if (
            geometry is None
            or placement is None
            or placement.scene_id != scene.id
            or placement.scenario_id is not None
            or placement.calculation_id != geometry.calculation_id
            or props.geometry_hash != geometry.geometry_hash
            or placement.geometry_hash != geometry.geometry_hash
            or props.placement_hash != _digest(placement.model_dump(mode="json"))
            or props.placement_status != placement.status
            or placement.status == "unplaced"
            or props.completeness != geometry.completeness
            or props.source_id is not None
            or props.layer_id is not None
        ):
            raise ValueError("stale online deed feature binding")
        if props.kind == "recorded_course":
            call = calls.get(props.call_id or "")
            primitive = next(
                (item for item in geometry.primitives if item.call_id == props.call_id), None
            )
            if (
                call is None
                or primitive is None
                or props.page_id != call.page_id
                or primitive.page_id != call.page_id
                or props.occurrence_id != call.occurrence_id
                or primitive.occurrence_id != call.occurrence_id
            ):
                raise ValueError("stale online recorded call binding")
        elif (
            not geometry.primitives
            or props.occurrence_id != geometry.occurrence_id
            or props.page_id is not None
            or (
                props.kind == "closure_gap"
                and (
                    geometry.completeness != "complete"
                    or geometry.misclosure_ft is None
                    or geometry.misclosure_ft <= 1e-8
                )
            )
        ):
            raise ValueError("stale online marker binding")
    _validate_completeness(context, artifact, scene.id)
    rasters = {item.id: item for item in context.raster_layers}
    projection_hash = (
        _digest(artifact.projection.model_dump(mode="json")) if artifact.projection else None
    )
    for raster in artifact.rasters:
        source = rasters.get(raster.id)
        if (
            source is None
            or source.scene_id != scene.id
            or raster.source_id != source.source_id
            or source.source_id not in sources
            or raster.source_sha256 != source.sha256
            or raster.registration_sha256 != _digest(source.registration.model_dump(mode="json"))
            or raster.projection_sha256 != projection_hash
            or raster.registration_status != source.registration.status
            or raster.fit_rms != source.registration.fit_rms
            or raster.checkpoint_rms != source.registration.checkpoint_rms
            or raster.residual_units != scene.units
        ):
            raise ValueError("stale online raster binding")


def validate_web_map_artifact(prepared: WebMapInput, artifact: WebMapArtifact) -> WebMapArtifact:
    """Revalidate models, canonical calculations, and display evidence bindings.

    This does not verify geographic coordinate derivation or derived PNG bytes;
    those checks belong to geographic preparation and asset staging upstream.
    """
    context = normalize_web_map_context(prepared)
    artifact = WebMapArtifact.model_validate(artifact.model_dump())
    if dict(artifact.input_hashes) != dict(context.input_hashes):
        raise ValueError("stale online display input hashes")
    if artifact.options_sha256 != _digest(artifact.options.model_dump(mode="json")):
        raise ValueError("stale online display options hash")
    _validate_bindings(context, artifact)
    return artifact
