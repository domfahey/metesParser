"""Immutable plotting contracts; coordinates are XY, never implicit longitude/latitude."""

import base64
import hashlib
import math
from typing import Annotated, Literal, Self, cast

from pydantic import (
    Field,
    FiniteFloat,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from .base import _Model

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_.:-]*$")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
XY = tuple[FiniteFloat, FiniteFloat]
LinearUnit = Literal["international_ft", "us_survey_ft", "m", "unknown_ft"]
Ring = tuple[XY, ...]
Polygon = tuple[Ring, ...]
MultiPolygon = tuple[Polygon, ...]


class PlotScene(_Model):
    id: Identifier
    name: str
    kind: Literal["local", "projected"]
    crs: str | None = None
    units: LinearUnit
    axis_order: Literal["xy"] = "xy"
    basis: str = "local"

    @model_validator(mode="after")
    def _projected(self) -> Self:
        if self.kind == "local" and self.crs is not None:
            raise ValueError("local scene must not declare a CRS")
        if self.kind == "projected" and (not self.crs or self.units == "unknown_ft"):
            raise ValueError("projected scene requires explicit CRS and linear units")
        return self


class MapSource(_Model):
    id: Identifier
    label: str
    sha256: Digest
    filename: str | None = None
    url: str | None = None
    provider: str | None = None
    retrieved_at: str | None = None
    source_date: str | None = None
    native_crs: str | None = None
    native_units: LinearUnit | Literal["degree", "pixel"] = "unknown_ft"
    axis_order: Literal["xy"] = "xy"
    feature_ids: tuple[str, ...] = ()
    processing_history: tuple[str, ...] = ()
    data_base64: str | None = None

    @model_validator(mode="after")
    def _retained_bytes(self) -> Self:
        if self.data_base64 is not None:
            try:
                data = base64.b64decode(self.data_base64, validate=True)
            except ValueError as exc:
                raise ValueError("Map source content must be valid base64") from exc
            if len(data) > 20 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != self.sha256:
                raise ValueError("Map source content hash/size mismatch")
        return self


def _cross(a: XY, b: XY, c: XY) -> float:
    value = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    if not math.isfinite(value):
        raise ValueError("nonfinite polygon arithmetic")
    return value


def _on(a: XY, b: XY, p: XY) -> bool:
    return (
        _cross(a, b, p) == 0
        and min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
        and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])
    )


def _intersects(a: XY, b: XY, c: XY, d: XY) -> bool:
    x, y, z, w = _cross(a, b, c), _cross(a, b, d), _cross(c, d, a), _cross(c, d, b)
    return (x * y < 0 and z * w < 0) or any(
        (_on(a, b, c), _on(a, b, d), _on(c, d, a), _on(c, d, b))
    )


def _inside(p: XY, ring: Ring) -> bool:
    inside = False
    for a, b in zip(ring, ring[1:], strict=False):
        if _on(a, b, p):
            return False
        if (a[1] > p[1]) != (b[1] > p[1]) and p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (
            b[1] - a[1]
        ) + a[0]:
            inside = not inside
    return inside


def _rings_intersect(a: Ring, b: Ring) -> bool:
    return any(
        _intersects(p, q, r, s)
        for p, q in zip(a, a[1:], strict=False)
        for r, s in zip(b, b[1:], strict=False)
    )


def validate_polygon(polygon: Polygon) -> None:
    """Reject unsupported topology instead of silently repairing supplied evidence."""
    if not polygon:
        raise ValueError("polygon requires an exterior ring")
    for ring in polygon:
        if len(ring) < 4 or ring[0] != ring[-1] or len(set(ring[:-1])) < 3:
            raise ValueError("rings must be closed with at least three distinct vertices")
        if any(a == b for a, b in zip(ring, ring[1:], strict=False)):
            raise ValueError("ring contains duplicate adjacent vertices")
        # Translation before products avoids cancellation at large projected offsets.
        origin = ring[0]
        area = sum(_cross(origin, a, b) for a, b in zip(ring, ring[1:], strict=False))
        if area == 0:
            raise ValueError("degenerate ring has zero area")
        edges = list(zip(ring, ring[1:], strict=False))
        for i, (a, b) in enumerate(edges):
            for j, (c, d) in enumerate(edges):
                if j <= i + 1 or (i == 0 and j == len(edges) - 1):
                    continue
                if _intersects(a, b, c, d):
                    raise ValueError("self-intersecting ring")
    exterior, *holes = polygon
    for i, hole in enumerate(holes):
        if not _inside(hole[0], exterior) or _rings_intersect(hole, exterior):
            raise ValueError("hole must be strictly inside its exterior")
        for other in holes[:i]:
            if _rings_intersect(hole, other) or _inside(hole[0], other) or _inside(other[0], hole):
                raise ValueError("holes must not overlap or nest")


class VectorLayer(_Model):
    id: Identifier
    label: str
    source_id: Identifier
    scene_id: Identifier
    geometry_type: Literal["Polygon", "MultiPolygon"]
    coordinates: Polygon | MultiPolygon
    feature_id: str | None = None

    @model_validator(mode="after")
    def _topology(self) -> Self:
        polygons = cast(
            MultiPolygon,
            (self.coordinates,) if self.geometry_type == "Polygon" else self.coordinates,
        )
        if not polygons:
            raise ValueError("layer requires polygon coordinates")
        for poly in polygons:
            # Union types can coerce nesting; the geometry type fixes expected depth.
            if not poly or not poly[0] or not isinstance(poly[0][0], tuple):
                raise ValueError("coordinates nesting must match geometry_type")
            validate_polygon(poly)
        for i, poly in enumerate(polygons):
            for other in polygons[:i]:
                if (
                    any(_rings_intersect(a, b) for a in poly for b in other)
                    or (
                        _inside(poly[0][0], other[0])
                        and not any(_inside(poly[0][0], h) for h in other[1:])
                    )
                    or (
                        _inside(other[0][0], poly[0])
                        and not any(_inside(other[0][0], h) for h in poly[1:])
                    )
                ):
                    raise ValueError("multipolygon members overlap or intersect")
        return self


class PlotPlacement(_Model):
    id: Identifier
    calculation_id: Identifier
    geometry_hash: Digest
    scene_id: Identifier
    rotation_deg: FiniteFloat = 0.0
    translation: XY = (0.0, 0.0)
    status: Literal["unplaced", "approximate", "referenced"] = "approximate"
    rationale: str = Field(min_length=1)
    evidence_ids: tuple[Identifier, ...] = ()
    position_evidence: tuple[str, ...] = ()
    orientation_evidence: tuple[str, ...] = ()
    baseline_geometry_hash: Digest | None = None
    baseline_placement_id: Identifier | None = None
    scenario_id: Identifier | None = None

    @model_validator(mode="after")
    def _referenced(self) -> Self:
        if self.status == "referenced" and (
            not self.position_evidence
            or not self.orientation_evidence
            or not all(e.strip() for e in self.position_evidence + self.orientation_evidence)
        ):
            raise ValueError("referenced placement requires position and orientation evidence")
        if self.scenario_id and (not self.baseline_geometry_hash or not self.baseline_placement_id):
            raise ValueError("scenario placement requires frozen baseline references")
        return self


class PlotView(_Model):
    """Viewport is scene XY (min_x, min_y, width, height); presentation only."""

    visible_layer_ids: tuple[Identifier, ...] = ()
    opacity: tuple[tuple[Identifier, Annotated[FiniteFloat, Field(ge=0, le=1)]], ...] = ()
    labels: tuple[Literal["course", "bearing", "distance"], ...] = ("course",)
    viewport: (
        tuple[
            FiniteFloat,
            FiniteFloat,
            Annotated[FiniteFloat, Field(gt=0)],
            Annotated[FiniteFloat, Field(gt=0)],
        ]
        | None
    ) = None


class PlotPrimitive(_Model):
    kind: Literal["line", "arc"]
    call_id: Identifier
    occurrence_id: Identifier | None = None
    page_id: Identifier | None = None
    start: XY
    end: XY
    length_ft: Annotated[FiniteFloat, Field(gt=0)]
    center: XY | None = None
    radius_ft: Annotated[FiniteFloat, Field(gt=0)] | None = None
    sweep_deg: Annotated[FiniteFloat, Field(gt=0, le=360)] | None = None
    curve_dir: Literal["left", "right"] | None = None
    start_tangent_deg: FiniteFloat | None = None

    @model_validator(mode="after")
    def _arc(self) -> Self:
        if self.kind == "arc" and any(
            v is None
            for v in (
                self.center,
                self.radius_ft,
                self.sweep_deg,
                self.curve_dir,
                self.start_tangent_deg,
            )
        ):
            raise ValueError("arc requires analytic circular geometry")
        return self


# A chord-only curve (radius + chord, no delta/arc) is positioned by its chord but
# its minor/major arc is unknown, so it is listed as unresolved without stopping.
CHORD_ONLY_UNRESOLVED_REASON = (
    "curve delta/arc not stated - arc not drawn; positioned by chord only"
)
# A spiral with a stated chord bearing and length: the chord fixes the next start
# exactly (as verification positions it), but no line or circular arc is drawn.
SPIRAL_CHORD_UNRESOLVED_REASON = (
    "spiral geometry unsupported - not drawn; positioned by stated chord only"
)
# The only unresolved outcomes the plot builder positions without drawing.
POSITIONED_UNRESOLVED_REASONS = frozenset(
    {CHORD_ONLY_UNRESOLVED_REASON, SPIRAL_CHORD_UNRESOLVED_REASON}
)


class PlotUnresolved(_Model):
    call_id: Identifier
    reason: str

    @property
    def positioned(self) -> bool:
        """True when the course is positioned by its stated chord but not drawn.

        Derived (never serialized) so stored geometry, its ``geometry_hash`` and
        placements bound to it stay byte-identical to artifacts that predate it.
        """
        return self.reason in POSITIONED_UNRESOLVED_REASONS


class PlotGeometry(_Model):
    id: Identifier
    calculation_id: Identifier
    occurrence_id: Identifier | None = None
    frame_id: Identifier
    geometry_hash: Digest
    primitives: tuple[PlotPrimitive, ...] = ()
    unresolved: tuple[PlotUnresolved, ...] = ()
    chains: tuple[tuple[Identifier, ...], ...] = ()
    completeness: Literal["complete", "partial", "unresolved"]
    reasons: tuple[str, ...] = ()
    misclosure_ft: FiniteFloat | None = None
    area_sq_ft: FiniteFloat | None = None
    perimeter_ft: FiniteFloat | None = None
    # True traverse origin, recorded only when it differs from the first drawn
    # primitive's start (a leading chord-only curve is positioned but not drawn).
    point_of_beginning: XY | None = None

    @model_serializer(mode="wrap")
    def _omit_default_pob(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        data = handler(self)
        if data.get("point_of_beginning") is None:
            data.pop("point_of_beginning", None)
        return cast(dict[str, object], data)


def plot_point_of_beginning(geometry: PlotGeometry) -> XY | None:
    """Return the traverse origin in native units, or None when nothing is positioned."""
    if geometry.point_of_beginning is not None:
        return geometry.point_of_beginning
    return geometry.primitives[0].start if geometry.primitives else None


class PointCorrespondence(_Model):
    id: Identifier
    call_id: Identifier | None = None
    deed_point: XY
    map_point: XY


class PlotComparisonSpec(_Model):
    id: Identifier
    placement_id: Identifier
    correspondences: tuple[PointCorrespondence, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_points(self) -> Self:
        ids = [point.id for point in self.correspondences]
        if len(ids) != len(set(ids)):
            raise ValueError("point correspondence IDs must be unique")
        return self


class PlotResidual(_Model):
    id: Identifier
    dx: FiniteFloat
    dy: FiniteFloat
    norm: FiniteFloat


class PlotComparison(_Model):
    comparison_id: Identifier | None = None
    placement_id: Identifier
    status: Literal["compared", "not_comparable"]
    residuals: tuple[PlotResidual, ...] = ()
    rms: FiniteFloat | None = None
    maximum: FiniteFloat | None = None
    reason: str = ""


class DashboardPlots(_Model):
    builder_version: str = "plot-1.0.0"
    geometries: tuple[PlotGeometry, ...] = ()
    placements: tuple[PlotPlacement, ...] = ()
    comparisons: tuple[PlotComparison, ...] = ()
