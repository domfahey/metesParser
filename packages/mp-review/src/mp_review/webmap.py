"""Fresh, deterministic geographic display of recorded baseline evidence only."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Literal, cast

from mp_models.dashboard import PreparedDashboard
from mp_models.plot import XY, LinearUnit, PlotGeometry, PlotPlacement, PlotPrimitive, VectorLayer
from mp_models.webmap import (
    WebMapArtifact,
    WebMapFeature,
    WebMapLine,
    WebMapMultiPolygon,
    WebMapOptions,
    WebMapPoint,
    WebMapPolygon,
    WebMapProjectionRecord,
    WebMapProperties,
    WebMapRaster,
    WebMapUnavailableItem,
)
from mp_verify.dashboard import _hash, validate_prepared_dashboard
from mp_verify.plot import arc_point, transform_point

from .webmap_projection import WebMapProjection, WebMapUnavailable, build_web_map_projection

# Public tuple keys are the exact canonical manifest field names, for renderer/runtime
# validation. No cache state or separately reconstructed stage hash enters this mapping.
_INPUT_HASH_FIELDS = (
    "source_review_hash",
    "calculation_input_hash",
    "calculation_output_hash",
    "presentation_hash",
    "plot_input_hash",
    "plot_output_hash",
    "map_input_hash",
    "map_output_hash",
    "placement_input_hash",
    "placement_output_hash",
)


@dataclass(frozen=True)
class PreparedWebMap:
    artifact: WebMapArtifact
    assets: tuple[tuple[str, bytes], ...] = ()


@dataclass
class _Budget:
    remaining: int

    def take(self) -> None:
        if self.remaining <= 0:
            raise WebMapUnavailable("vertex_limit", "Scene vector vertex budget exceeded.")
        self.remaining -= 1


def _distance(point: XY, a: XY, b: XY) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    squared = dx * dx + dy * dy
    t = (
        max(0.0, min(1.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / squared))
        if squared
        else 0.0
    )
    return math.hypot(point[0] - a[0] - t * dx, point[1] - a[1] - t * dy)


def _dateline(a: XY, b: XY) -> None:
    if abs(a[0] - b[0]) > 180:
        raise WebMapUnavailable("antimeridian", "Antimeridian-spanning evidence is unsupported.")


def _sample(
    point: Callable[[float], XY],
    projection: WebMapProjection,
    options: WebMapOptions,
    budget: _Budget,
    *,
    count_start: bool = True,
) -> tuple[XY, ...]:
    """Bound chord deviations at quarter/mid/three-quarter positions, including lines."""
    start, end = projection.to_mercator(point(0)), projection.to_mercator(point(1))
    _dateline(projection.from_mercator(start), projection.from_mercator(end))
    if count_start:
        budget.take()
    result = [start]

    def refine(left: float, right: float, a: XY, b: XY, depth: int) -> None:
        fractions = tuple(left + (right - left) * ratio for ratio in (0.25, 0.5, 0.75))
        controls = tuple(projection.to_mercator(point(t)) for t in fractions)
        geographic = tuple(projection.from_mercator(p) for p in (a, *controls, b))
        for p, q in zip(geographic, geographic[1:], strict=False):
            _dateline(p, q)
        if max(_distance(p, a, b) for p in controls) <= options.tolerance_m:
            budget.take()
            result.append(b)
            return
        if depth >= options.max_depth:
            raise WebMapUnavailable(
                "sampling_limit", "Display tolerance exceeds subdivision limit."
            )
        middle = fractions[1]
        refine(left, middle, a, controls[1], depth + 1)
        refine(middle, right, controls[1], b, depth + 1)

    refine(0, 1, start, end, 0)
    return tuple(projection.from_mercator(p) for p in result)


def _line(a: XY, b: XY) -> Callable[[float], XY]:
    def point(t: float) -> XY:
        # Keep the exact canonical endpoints, even where floating arithmetic cancels.
        if t == 0:
            return a
        if t == 1:
            return b
        return a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])

    return point


def _primitive_point(primitive: PlotPrimitive, t: float) -> XY:
    if t == 0:
        return primitive.start
    if t == 1:
        return primitive.end
    return (
        arc_point(primitive, t)
        if primitive.kind == "arc"
        else _line(primitive.start, primitive.end)(t)
    )


def _deed_features(
    geometry: PlotGeometry,
    placement: PlotPlacement,
    native_units: LinearUnit,
    scene_units: LinearUnit,
    projection: WebMapProjection,
    options: WebMapOptions,
    budget: _Budget,
) -> list[WebMapFeature]:
    if native_units == "unknown_ft":
        raise WebMapUnavailable(
            "unknown_units", "Geographic display requires an explicit foot definition."
        )
    if not geometry.primitives:
        raise WebMapUnavailable(
            "unresolved_geometry", "No positioned recorded courses are available."
        )
    assert placement.status != "unplaced"

    def placed(p: XY) -> XY:
        return transform_point(p, placement, native_units=native_units, scene_units=scene_units)

    placement_hash = _hash(placement.model_dump(mode="json"))

    def properties(
        kind: Literal["recorded_course", "closure_gap", "pob"],
        *,
        call_id: str | None = None,
        page_id: str | None = None,
        label: str = "",
    ) -> WebMapProperties:
        return WebMapProperties(
            kind=kind,
            calculation_id=geometry.calculation_id,
            occurrence_id=geometry.occurrence_id,
            geometry_hash=geometry.geometry_hash,
            placement_hash=placement_hash,
            placement_id=placement.id,
            placement_status=cast(Literal["approximate", "referenced"], placement.status),
            completeness=geometry.completeness,
            call_id=call_id,
            page_id=page_id,
            label=label,
        )

    features = []
    for primitive in geometry.primitives:
        # Each canonical primitive stays separate. Chains never acquire a bridging segment.
        def sample_point(t: float, p: PlotPrimitive = primitive) -> XY:
            return placed(_primitive_point(p, t))

        coordinates = _sample(sample_point, projection, options, budget)
        features.append(
            WebMapFeature(
                id="course:" + _hash([placement.id, primitive.call_id]),
                geometry=WebMapLine(coordinates=coordinates),
                properties=properties(
                    "recorded_course",
                    call_id=primitive.call_id,
                    page_id=primitive.page_id,
                    label=primitive.call_id,
                ),
            )
        )
    budget.take()
    first, last = geometry.primitives[0].start, geometry.primitives[-1].end
    features.append(
        WebMapFeature(
            id=f"pob:{placement.id}",
            geometry=WebMapPoint(
                coordinates=projection.from_mercator(projection.to_mercator(placed(first)))
            ),
            properties=properties("pob", label="Point of beginning"),
        )
    )
    # Native numerical residue is not a meaningful closure annotation. A partial
    # prefix has no known full endpoint and must never acquire a closing segment.
    if (
        geometry.completeness == "complete"
        and math.hypot(last[0] - first[0], last[1] - first[1]) > 1e-8
    ):
        features.append(
            WebMapFeature(
                id=f"gap:{placement.id}",
                geometry=WebMapLine(
                    coordinates=_sample(
                        lambda t: placed(_line(last, first)(t)), projection, options, budget
                    )
                ),
                properties=properties("closure_gap", label="Closure gap; not a recorded course"),
            )
        )
    return features


def _vector_feature(
    layer: VectorLayer, projection: WebMapProjection, options: WebMapOptions, budget: _Budget
) -> WebMapFeature:
    polygons = (layer.coordinates,) if layer.geometry_type == "Polygon" else layer.coordinates
    converted = []
    for polygon in polygons:
        rings = []
        for ring in polygon:
            points: list[XY] = []
            for a, b in zip(ring, ring[1:], strict=False):
                edge = _sample(
                    _line(cast(XY, a), cast(XY, b)),
                    projection,
                    options,
                    budget,
                    count_start=not points,
                )
                points.extend(edge if not points else edge[1:])
            rings.append(tuple(points))
        converted.append(tuple(rings))
    geometry = (
        WebMapPolygon(coordinates=converted[0])
        if layer.geometry_type == "Polygon"
        else WebMapMultiPolygon(coordinates=tuple(converted))
    )
    return WebMapFeature(
        id=f"context:{layer.id}",
        geometry=geometry,
        properties=WebMapProperties(
            kind="parcel_context", source_id=layer.source_id, layer_id=layer.id, label=layer.label
        ),
    )


def _coordinates(feature: WebMapFeature) -> Iterator[XY]:
    geometry = feature.geometry
    if isinstance(geometry, WebMapPoint):
        yield geometry.coordinates
    elif isinstance(geometry, WebMapLine):
        yield from geometry.coordinates
    elif isinstance(geometry, WebMapPolygon):
        for ring in geometry.coordinates:
            yield from ring
    else:
        for polygon in geometry.coordinates:
            for ring in polygon:
                yield from ring


def prepare_web_map(
    prepared: PreparedDashboard, *, scene_id: str, options: WebMapOptions
) -> PreparedWebMap:
    """Prepare bounded display evidence after fresh canonical and raster validation.

    ``input_hashes`` maps exact manifest hash field names to their canonical values
    in ``_INPUT_HASH_FIELDS`` order. It includes presentation identity but excludes
    cache reuse. Assets are ordered ``(relative PNG path, exact PNG bytes)`` pairs.
    """
    options = WebMapOptions.model_validate(options.model_dump(mode="json"))
    validate_prepared_dashboard(prepared)
    scenes = {s.id: s for s in prepared.bundle.scenes}
    if scene_id not in scenes:
        raise ValueError("Requested web-map scene does not exist")
    # Validate ALL original rasters before classifying any supported omissions,
    # including when a scene is local or the selected operation is unavailable.
    if prepared.bundle.raster_layers:
        from .raster_registration import validate_raster_layer

        for original_raster in prepared.bundle.raster_layers:
            validate_raster_layer(original_raster, scenes[original_raster.scene_id])
    hashes = tuple(
        (name, value)
        for name in _INPUT_HASH_FIELDS
        if (value := getattr(prepared.manifest, name)) is not None
    )
    features: list[WebMapFeature] = []
    rasters: list[WebMapRaster] = []
    assets: list[tuple[str, bytes]] = []
    unavailable: list[WebMapUnavailableItem] = []
    projection_record = None

    def omit(
        item_id: str,
        kind: Literal["calculation", "raster", "vector", "scene"],
        error: WebMapUnavailable,
    ) -> None:
        unavailable.append(
            WebMapUnavailableItem(item_id=item_id, kind=kind, code=error.code, reason=str(error))
        )

    try:
        projection = build_web_map_projection(scenes[scene_id])
    except WebMapUnavailable as exc:
        omit(scene_id, "scene", exc)
    else:
        scene = scenes[scene_id]
        projection_record = WebMapProjectionRecord(
            source_crs_wkt=projection.source_crs_wkt,
            pipeline=projection.pipeline,
            accuracy_m=projection.accuracy,
            versions=projection.versions,
        )
        budget = _Budget(options.max_vertices)
        specs = {s.id: s for s in prepared.bundle.calculations}
        for geometry in sorted(prepared.plots.geometries, key=lambda g: g.calculation_id):
            placements = sorted(
                (
                    p
                    for p in prepared.plots.placements
                    if p.calculation_id == geometry.calculation_id and p.scene_id == scene_id
                ),
                key=lambda p: p.id,
            )
            if not placements:
                omit(
                    geometry.calculation_id,
                    "calculation",
                    WebMapUnavailable("missing_placement", "No placement in the selected scene."),
                )
                continue
            before = budget.remaining
            pending = []
            try:
                for placement in placements:
                    if placement.status == "unplaced":
                        raise WebMapUnavailable(
                            "unplaced", "Recorded geometry has no established placement."
                        )
                    pending.extend(
                        _deed_features(
                            geometry,
                            placement,
                            specs[geometry.calculation_id].frame.foot_definition,
                            scene.units,
                            projection,
                            options,
                            budget,
                        )
                    )
            except WebMapUnavailable as exc:
                budget.remaining = before
                omit(geometry.calculation_id, "calculation", exc)
            else:
                features.extend(pending)
                if geometry.completeness != "complete":
                    omit(
                        geometry.calculation_id,
                        "calculation",
                        WebMapUnavailable(
                            "partial_geometry",
                            "Only positioned recorded courses are included; unresolved calls are omitted.",
                        ),
                    )
        for layer in sorted(prepared.bundle.vector_layers, key=lambda item: item.id):
            if layer.scene_id != scene_id:
                continue
            before = budget.remaining
            try:
                feature = _vector_feature(layer, projection, options, budget)
            except WebMapUnavailable as exc:
                budget.remaining = before
                omit(layer.id, "vector", exc)
            else:
                features.append(feature)
        raster_pixels = 0
        for raster in sorted(prepared.bundle.raster_layers, key=lambda item: item.id):
            if raster.scene_id != scene_id:
                continue
            from .webmap_raster import prepare_web_map_raster

            try:
                remaining = options.max_raster_pixels - raster_pixels
                if remaining <= 0:
                    raise WebMapUnavailable(
                        "raster_pixel_limit", "Scene raster pixel budget exceeded."
                    )
                bounded = options.model_copy(update={"max_raster_pixels": remaining})
                derived = prepare_web_map_raster(
                    raster, scene, projection=projection, options=bounded
                )
                pixels = derived.record.width * derived.record.height
                if pixels > remaining:
                    raise WebMapUnavailable(
                        "raster_pixel_limit", "Scene raster pixel budget exceeded."
                    )
            except WebMapUnavailable as exc:
                omit(raster.id, "raster", exc)
            else:
                raster_pixels += pixels
                rasters.append(derived.record)
                assets.append((derived.record.path, derived.data))
    points = [p for feature in features for p in _coordinates(feature)]
    points.extend(p for raster in rasters for p in raster.corners)
    if points and max(p[0] for p in points) - min(p[0] for p in points) > 180:
        # Bounds spanning the dateline are unsupported even for disjoint evidence.
        features, rasters, assets, points = [], [], [], []
        omit(
            scene_id,
            "scene",
            WebMapUnavailable("antimeridian", "Scene evidence spans the unsupported antimeridian."),
        )
    bounds = (
        (
            min(p[0] for p in points),
            min(p[1] for p in points),
            max(p[0] for p in points),
            max(p[1] for p in points),
        )
        if points
        else None
    )
    return PreparedWebMap(
        artifact=WebMapArtifact(
            scene_id=scene_id,
            input_hashes=hashes,
            options=options,
            options_sha256=_hash(options.model_dump(mode="json")),
            projection=projection_record,
            features=tuple(features),
            rasters=tuple(rasters),
            unavailable=tuple(unavailable),
            availability="partial"
            if points and unavailable
            else "ready"
            if points
            else "unavailable",
            bounds=bounds,
        ),
        assets=tuple(assets),
    )
