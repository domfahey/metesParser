"""Deterministic source-bound centerline offsets with a linear error budget.

This constructs an explicitly requested ribbon. It neither closes the centerline
as a parcel nor applies canonical parcel verification to the derived polygon.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from typing import Any, Literal

from mp_models.corridor import (
    CorridorBoundaryEdge,
    CorridorErrorReport,
    CorridorRequest,
    CorridorResult,
    CorridorWidthInterval,
)
from mp_models.deed_call import DeedCall
from mp_models.plot import XY, PlotPrimitive, _intersects, validate_polygon
from mp_models.plot_request import PlotCall, PlotRequest

from .diagnostics import _curve_evidence, _supported_circular_arc
from .plot import arc_point, prepare_plot, unit_factor

CORRIDOR_VERSION = "corridor-1"
_Role = Literal["left_offset", "right_offset", "join", "start_cap", "end_cap"]
_Availability = Literal[
    "supported", "unsupported", "incomplete", "topology_failed", "topology_unavailable"
]
_LIMITS = (
    "Constructed corridor is advisory; open centerline analysis is separate from parcel closure or source/legal review.",
    "Widths are relative to stored forward centerline; reversing input requires reversing stations and swapping left/right endpoint widths.",
    "Step rows are constant internally and jump at their boundaries; taper widths vary linearly with centerline station, never per-course averages.",
    "Square caps extend by half the total endpoint width. Round caps use the left-to-right endpoint diameter; asymmetric cap centers may lie off the centerline.",
    "Boundary plot starts at its own origin; add boundary_origin_in_centerline_frame before applying a centerline placement.",
    "Approximation error bounds apply to constructed offset/cap geometry, not survey/source accuracy; no topology is repaired.",
)


class _Unavailable(ValueError):
    def __init__(self, reason: str, availability: _Availability = "unsupported") -> None:
        super().__init__(reason)
        self.availability = availability


@dataclass(frozen=True)
class _Sample:
    point: XY
    calls: tuple[str, ...]
    widths: tuple[str, ...]
    role: _Role


@dataclass(frozen=True)
class _Piece:
    primitive: PlotPrimitive
    row: CorridorWidthInterval
    f0: float
    f1: float
    left0: float
    left1: float
    right0: float
    right1: float


def corridor_input_hash(request: CorridorRequest) -> str:
    return hashlib.sha256(
        json.dumps(
            request.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _add(a: XY, b: XY) -> XY:
    point = (a[0] + b[0], a[1] + b[1])
    if not all(math.isfinite(v) for v in point):
        raise _Unavailable("nonfinite corridor arithmetic")
    return point


def _sub(a: XY, b: XY) -> XY:
    return a[0] - b[0], a[1] - b[1]


def _scale(a: XY, factor: float) -> XY:
    return a[0] * factor, a[1] * factor


def _cross(a: XY, b: XY) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _heading(primitive: PlotPrimitive, fraction: float) -> float:
    if primitive.kind == "line":
        return math.atan2(
            primitive.end[0] - primitive.start[0], primitive.end[1] - primitive.start[1]
        )
    assert primitive.start_tangent_deg is not None and primitive.sweep_deg is not None
    sign = 1 if primitive.curve_dir == "right" else -1
    return math.radians(primitive.start_tangent_deg + sign * primitive.sweep_deg * fraction)


def _centerpoint(primitive: PlotPrimitive, fraction: float) -> XY:
    if primitive.kind == "arc":
        return arc_point(primitive, fraction)
    return _add(primitive.start, _scale(_sub(primitive.end, primitive.start), fraction))


def _pieces(request: CorridorRequest, primitives: tuple[PlotPrimitive, ...]) -> list[_Piece]:
    lengths = [p.length_ft for p in primitives]
    stations = [0.0]
    for length in lengths:
        stations.append(math.fsum((stations[-1], length)))
    indexes = {primitive.call_id: i for i, primitive in enumerate(primitives)}
    factor = unit_factor(request.width_unit, request.centerline.foot_definition)

    def station(call_id: str, fraction: float) -> float:
        index = indexes[call_id]
        return stations[index] + fraction * lengths[index]

    cursor = 0.0
    pieces = []
    for row in request.widths:
        start = station(row.start.call_id, row.start.fraction)
        end = station(row.end.call_id, row.end.fraction)
        if end <= start:
            raise _Unavailable(f"{row.id}: zero or reversed width interval; ordering is explicit")
        if start < cursor:
            raise _Unavailable(
                f"{row.id}: overlapping or out-of-order width intervals; no precedence assumed"
            )
        if start > cursor:
            raise _Unavailable(f"{row.id}: missing width coverage", "incomplete")
        for i, primitive in enumerate(primitives):
            a, b = max(start, stations[i]), min(end, stations[i + 1])
            if b <= a:
                continue
            t0, t1 = (a - start) / (end - start), (b - start) / (end - start)

            def width(first: float, last: float, t: float) -> float:
                return (first + (last - first) * t) * factor

            pieces.append(
                _Piece(
                    primitive,
                    row,
                    min(1.0, max(0.0, (a - stations[i]) / lengths[i])),
                    min(1.0, max(0.0, (b - stations[i]) / lengths[i])),
                    width(row.left_start, row.left_end, t0),
                    width(row.left_start, row.left_end, t1),
                    width(row.right_start, row.right_end, t0),
                    width(row.right_start, row.right_end, t1),
                )
            )
        cursor = end
    if cursor != stations[-1]:
        raise _Unavailable("missing width coverage to the end of the centerline", "incomplete")
    return pieces


@dataclass
class _Sampler:
    tolerance: float
    limit: int
    maximum_bound: float = 0.0
    join_floating_point_bound: float = 0.0

    def count(self, second_derivative_bound: float) -> int:
        if not math.isfinite(second_derivative_bound):
            raise _Unavailable("nonfinite offset error bound")
        ratio = second_derivative_bound / (8 * self.tolerance)
        if not math.isfinite(ratio) or ratio > self.limit**2:
            raise _Unavailable("declared error budget requires more than max_segments")
        count = max(1, math.ceil(math.sqrt(ratio)))
        self.maximum_bound = max(self.maximum_bound, second_derivative_bound / (8 * count**2))
        return count

    def circle(
        self, start: _Sample, end: _Sample, center: XY, sweep: float, role: _Role
    ) -> list[_Sample]:
        radius = math.dist(start.point, center)
        count = self.count(radius * sweep**2)
        radial = _sub(start.point, center)
        points = []
        for i in range(count + 1):
            theta = sweep * i / count
            point = _add(
                center,
                (
                    radial[0] * math.cos(theta) - radial[1] * math.sin(theta),
                    radial[0] * math.sin(theta) + radial[1] * math.cos(theta),
                ),
            )
            points.append(
                _Sample(
                    point,
                    tuple(dict.fromkeys(start.calls + end.calls)),
                    tuple(dict.fromkeys(start.widths + end.widths)),
                    role,
                )
            )
        points[0] = replace(points[0], point=start.point)
        points[-1] = replace(points[-1], point=end.point)
        return points


def _offset(piece: _Piece, left: bool, sampler: _Sampler) -> list[_Sample]:
    primitive = piece.primitive
    first, last = (piece.left0, piece.left1) if left else (piece.right0, piece.right1)
    second_bound = 0.0
    if primitive.kind == "arc":
        assert primitive.radius_ft is not None and primitive.sweep_deg is not None
        inward = (primitive.curve_dir == "left") == left
        if inward and max(first, last) >= primitive.radius_ft:
            raise _Unavailable(
                f"{primitive.call_id}: inner offset reaches or crosses the curve center; cusp/collapse unsupported"
            )
        angle = math.radians(primitive.sweep_deg) * (piece.f1 - piece.f0)
        radii = [primitive.radius_ft + (-w if inward else w) for w in (first, last)]
        # For p(t)=(R+w(t))*unit(theta(t)), ||p''|| <= max|R+w|*theta'^2 + 2|w' theta'|.
        second_bound = max(radii) * angle**2 + 2 * abs(last - first) * angle
    count = sampler.count(second_bound)
    result = []
    for i in range(count + 1):
        t = i / count
        fraction = piece.f0 + (piece.f1 - piece.f0) * t
        heading = _heading(primitive, fraction)
        width = first + (last - first) * t
        normal = (
            (-math.cos(heading), math.sin(heading))
            if left
            else (math.cos(heading), -math.sin(heading))
        )
        result.append(
            _Sample(
                _add(_centerpoint(primitive, fraction), _scale(normal, width)),
                (primitive.call_id,),
                (piece.row.id,),
                "left_offset" if left else "right_offset",
            )
        )
    return result


def _join(
    previous: list[_Sample],
    following: list[_Sample],
    first: _Piece,
    second: _Piece,
    left: bool,
    request: CorridorRequest,
    sampler: _Sampler,
) -> list[_Sample]:
    h0, h1 = _heading(first.primitive, first.f1), _heading(second.primitive, second.f0)
    # Convert clockwise azimuth change into the mathematical (counterclockwise) turn.
    turn = -((h1 - h0 + math.pi) % math.tau - math.pi)
    angular_roundoff = 32 * math.ulp(max(abs(h0), abs(h1), 1.0))
    if abs(turn) <= angular_roundoff:
        return []
    if abs(abs(turn) - math.pi) <= angular_roundoff:
        raise _Unavailable(
            "180-degree centerline reversals require an explicit unsupported join construction"
        )
    if first.primitive.kind == "arc" or second.primitive.kind == "arc":
        raise _Unavailable(
            "non-tangent arc joins unsupported; no line-based replacement for curved offset intersections"
        )
    a, b = previous[-1], following[0]
    vertex = _centerpoint(first.primitive, first.f1)
    inside = (turn > 0) == left
    if not inside and request.join == "bevel":
        return []
    if not inside and request.join == "round":
        if not math.isclose(
            math.dist(a.point, vertex), math.dist(b.point, vertex), rel_tol=1e-12, abs_tol=1e-10
        ):
            raise _Unavailable(
                "round join requires equal side widths at its two endpoints; step-radius join unsupported"
            )
        return sampler.circle(a, b, vertex, turn, "join")[1:-1]
    u, v = _sub(a.point, previous[-2].point), _sub(following[1].point, b.point)
    length_u, length_v = math.hypot(*u), math.hypot(*v)
    if min(length_u, length_v) == 0:
        raise _Unavailable("offset join has no representable neighboring segment")
    unit_u = (u[0] / length_u, u[1] / length_u)
    unit_v = (v[0] / length_v, v[1] / length_v)
    coordinate_scale = max(
        abs(c)
        for p in (a.point, b.point, vertex, previous[-2].point, following[1].point)
        for c in p
    )
    widths = (
        (first.left0, first.left1, second.left0, second.left1)
        if left
        else (first.right0, first.right1, second.right0, second.right1)
    )
    if len(set(widths)) == 1:
        # Equal constant offsets meet on the angle bisector. Subtracting two
        # almost coincident offset endpoints before division loses the tiny
        # half-angle displacement even for representable requested budgets.
        denominator = 1 + math.cos(turn)
        if denominator <= 0:
            raise _Unavailable("offset join bisector is unrepresentable")
        sign = 1 if left else -1
        normal = (sign * (-math.cos(h0) - math.cos(h1)), sign * (math.sin(h0) + math.sin(h1)))
        intersection = _add(vertex, _scale(normal, widths[0] / denominator))
        t = (
            math.fsum(x * y for x, y in zip(_sub(intersection, a.point), unit_u, strict=True))
            / length_u
        )
        q = (
            math.fsum(x * y for x, y in zip(_sub(intersection, b.point), unit_v, strict=True))
            / length_v
        )
        join_roundoff = 128 * math.ulp(coordinate_scale) * (1 + 1 / denominator**2)
    else:
        denominator = _cross(unit_u, unit_v)
        if denominator == 0:
            raise _Unavailable("offset join lines have no unique intersection")
        delta = _sub(b.point, a.point)
        along_u, along_v = _cross(delta, unit_v) / denominator, _cross(delta, unit_u) / denominator
        t, q = along_u / length_u, along_v / length_v
        intersection = _add(a.point, _scale(unit_u, along_u))
        # Endpoint/direction perturbations are amplified by 1/sin(angle).
        # Accumulate this allowance across sequential trims rather than claiming
        # that reconstruction of the already rounded polygon certifies the join.
        join_roundoff = (
            256
            * math.ulp(coordinate_scale)
            * (1 + (length_u + length_v + math.hypot(*delta)) / min(length_u, length_v))
            / abs(denominator)
        )
    sampler.join_floating_point_bound += join_roundoff
    if (
        not math.isfinite(sampler.join_floating_point_bound)
        or sampler.join_floating_point_bound > sampler.tolerance
    ):
        raise _Unavailable("offset join conditioning exceeds the floating point error allocation")
    if inside and not (-1 - 1e-10 <= t <= 1e-10 and -1e-10 <= q <= 1 + 1e-10):
        raise _Unavailable("inside join cannot be trimmed within neighboring offset segments")
    if not inside:
        extent = max(math.dist(a.point, vertex), math.dist(b.point, vertex))
        if math.dist(intersection, vertex) > request.miter_limit * extent:
            raise _Unavailable("miter exceeds explicit miter_limit; no automatic join substitution")
    joined = _Sample(
        intersection,
        tuple(dict.fromkeys(a.calls + b.calls)),
        tuple(dict.fromkeys(a.widths + b.widths)),
        "join",
    )
    previous[-1] = following[0] = joined
    return []


def _side(
    pieces: list[_Piece], left: bool, request: CorridorRequest, sampler: _Sampler
) -> list[_Sample]:
    chunks = [_offset(piece, left, sampler) for piece in pieces]
    joins = []
    for i in range(len(chunks) - 1):
        joins.append(
            _join(chunks[i], chunks[i + 1], pieces[i], pieces[i + 1], left, request, sampler)
        )
    result = list(chunks[0])
    for i, chunk in enumerate(chunks[1:]):
        result.extend(joins[i])
        result.extend(chunk)
    return result


def _cap(
    start: _Sample, end: _Sample, heading: float, cap: str, role: _Role, sampler: _Sampler
) -> list[_Sample]:
    if cap == "butt":
        return []
    center = ((start.point[0] + end.point[0]) / 2, (start.point[1] + end.point[1]) / 2)
    if cap == "round":
        return sampler.circle(start, end, center, -math.pi, role)[1:-1]
    extension = math.dist(start.point, end.point) / 2
    vector = (extension * math.sin(heading), extension * math.cos(heading))
    return [
        replace(start, point=_add(start.point, vector), role=role),
        replace(end, point=_add(end.point, vector), role=role),
    ]


def _point_segment_distance(point: XY, start: XY, end: XY) -> float:
    direction = _sub(end, start)
    length = math.hypot(*direction)
    if length == 0:
        return math.dist(point, start)
    unit = _scale(direction, 1 / length)
    projection = max(
        0.0,
        min(length, math.fsum((unit[0] * (point[0] - start[0]), unit[1] * (point[1] - start[1])))),
    )
    return math.dist(point, _add(start, _scale(unit, projection)))


def _topology(ring: tuple[XY, ...], uncertainty: float) -> None:
    try:
        validate_polygon((ring,))
    except ValueError as exc:
        raise _Unavailable(f"corridor boundary topology failed: {exc}", "topology_failed") from exc
    if uncertainty == 0:
        return
    segments = list(zip(ring, ring[1:], strict=False))
    for i, (a, b) in enumerate(segments):
        for j in range(i + 2, len(segments)):
            if i == 0 and j == len(segments) - 1:
                continue
            c, d = segments[j]
            if (
                max(a[0], b[0]) + 2 * uncertainty < min(c[0], d[0])
                or max(c[0], d[0]) + 2 * uncertainty < min(a[0], b[0])
                or max(a[1], b[1]) + 2 * uncertainty < min(c[1], d[1])
                or max(c[1], d[1]) + 2 * uncertainty < min(a[1], b[1])
            ):
                continue
            if _intersects(a, b, c, d):
                raise _Unavailable("corridor boundary intersects", "topology_failed")
            distance = min(
                _point_segment_distance(a, c, d),
                _point_segment_distance(b, c, d),
                _point_segment_distance(c, a, b),
                _point_segment_distance(d, a, b),
            )
            if distance <= 2 * uncertainty:
                raise _Unavailable(
                    "topology clearance is within the declared approximation error; tighter budget required",
                    "topology_unavailable",
                )


def analyze_corridor(request: CorridorRequest) -> CorridorResult:
    """Analyze a new requested ribbon; unsupported constructions never expose an area."""
    request = CorridorRequest.model_validate(request.model_dump(mode="json"))
    common: dict[str, Any] = {
        "request": request,
        "input_sha256": corridor_input_hash(request),
        "limitations": _LIMITS,
    }
    prepared = None
    try:
        if request.centerline.foot_definition == "unknown_ft":
            raise _Unavailable("centerline requires an explicit foot definition")
        if request.centerline.relative is not None:
            raise _Unavailable("relative-only centerlines unsupported; no invented orientation")
        for record in request.centerline.calls:
            call = record.call
            if not record.source_reference or not record.source_reference.strip():
                raise _Unavailable(
                    f"{record.id}: centerline source reference required", "incomplete"
                )
            if call is None or call.is_indefinite:
                raise _Unavailable(f"{record.id}: incomplete centerline geometry", "incomplete")
            if call.is_tie_in or call.is_exception or call.is_meander:
                raise _Unavailable(
                    f"{record.id}: select centerline-only geometry; tie-ins/exception/meanders unsupported"
                )
            if _curve_evidence(call):
                _supported_circular_arc(call, record.id)
        prepared = prepare_plot(request.centerline)
        if prepared.geometry.completeness != "complete":
            raise _Unavailable(
                "centerline geometry is incomplete; no downstream offsets positioned", "incomplete"
            )
        primitives = prepared.geometry.primitives
        if math.dist(primitives[0].start, primitives[-1].end) <= 64 * max(
            math.ulp(c) for p in primitives for point in (p.start, p.end) for c in point
        ):
            raise _Unavailable(
                "closed centerlines require a ring/holes corridor contract; unsupported"
            )
        pieces = _pieces(request, primitives)
        tolerance = request.error_budget.max_error * unit_factor(
            request.error_budget.unit, request.centerline.foot_definition
        )
        if not math.isfinite(tolerance) or tolerance / 2 <= 0:
            raise _Unavailable(
                "converted error budget is outside representable positive arithmetic"
            )
        sampler = _Sampler(tolerance / 2, request.error_budget.max_segments)
        left, right = _side(pieces, True, request, sampler), _side(pieces, False, request, sampler)
        end_cap = _cap(
            left[-1],
            right[-1],
            _heading(pieces[-1].primitive, pieces[-1].f1),
            request.cap,
            "end_cap",
            sampler,
        )
        start_cap = _cap(
            right[0],
            left[0],
            _heading(pieces[0].primitive, pieces[0].f0) + math.pi,
            request.cap,
            "start_cap",
            sampler,
        )
        samples = left + end_cap + list(reversed(right)) + start_cap
        coordinate_scale = max(
            math.fsum(primitive.length_ft for primitive in primitives),
            max(abs(c) for sample in samples for c in sample.point),
        )
        roundoff = (
            64 * (len(primitives) + len(request.widths)) * math.ulp(coordinate_scale)
            + sampler.join_floating_point_bound
        )
        if roundoff > tolerance / 2:
            raise _Unavailable(
                "floating point coordinate resolution exceeds the declared error budget"
            )
        # Merge construction roundoff within its explicit budget, retaining all identities.
        unique: list[_Sample] = []
        for sample in samples:
            if unique and math.dist(unique[-1].point, sample.point) <= roundoff:
                previous = unique[-1]
                unique[-1] = replace(
                    previous,
                    calls=tuple(dict.fromkeys(previous.calls + sample.calls)),
                    widths=tuple(dict.fromkeys(previous.widths + sample.widths)),
                )
            else:
                unique.append(sample)
        if len(unique) > request.error_budget.max_segments:
            raise _Unavailable(
                "complete boundary exceeds max_segments; no partial polygon exported"
            )
        ring = tuple(sample.point for sample in unique) + (unique[0].point,)
        _topology(ring, sampler.maximum_bound + roundoff)
        records = []
        edges = []
        width_rows = {row.id: row for row in request.widths}
        for i, (first, last) in enumerate(zip(unique, unique[1:] + unique[:1], strict=True), 1):
            dx, dy = _sub(last.point, first.point)
            id = f"{request.id}:boundary-{i}"
            calls, widths = (
                tuple(dict.fromkeys(first.calls + last.calls)),
                tuple(dict.fromkeys(first.widths + last.widths)),
            )
            cap_roles = [
                role for role in (first.role, last.role) if role in {"start_cap", "end_cap"}
            ]
            role: _Role = (
                cap_roles[0] if cap_roles else first.role if first.role == last.role else "join"
            )
            if first.point == left[-1].point and last.point == right[-1].point:
                role = "end_cap"
            elif i == len(unique):
                role = "start_cap"
            reference = f"Derived corridor {request.id}; centerline {','.join(calls)}; width intervals {','.join(widths)}; {role}"
            records.append(
                PlotCall(
                    id=id,
                    source_reference=reference,
                    quote="Derived geometry; see retained canonical corridor request",
                    call=DeedCall(
                        course=i,
                        direction_text=reference,
                        distance_ft=math.hypot(dx, dy),
                        bearing_azimuth_deg_from_north=math.degrees(math.atan2(dx, dy)) % 360,
                    ),
                )
            )
            refs = (
                tuple(ref for width_id in widths for ref in width_rows[width_id].source_refs)
                + request.construction_source_refs
            )
            edges.append(
                CorridorBoundaryEdge(
                    call_id=id,
                    centerline_call_ids=calls,
                    width_interval_ids=widths,
                    role=role,
                    source_refs=refs,
                )
            )
        boundary = prepare_plot(
            PlotRequest(
                title=request.centerline.title + " — advisory constructed corridor",
                calculation_id=request.id + ":boundary",
                calls=tuple(records),
                foot_definition=request.centerline.foot_definition,
            )
        )
        if boundary.geometry.completeness != "complete":
            raise _Unavailable("derived boundary cannot be represented without precision loss")
        reconstruction = max(
            math.dist(_add(primitive.start, unique[0].point), sample.point)
            for primitive, sample in zip(boundary.geometry.primitives, unique, strict=True)
        )
        roundoff += reconstruction
        if roundoff > tolerance / 2:
            raise _Unavailable("reconstructed boundary exceeds the floating point error allocation")
        if reconstruction > 0:
            _topology(ring, sampler.maximum_bound + roundoff)
        factor = unit_factor(request.centerline.foot_definition, request.error_budget.unit)
        linearization_bound, floating_point_bound = (
            sampler.maximum_bound * factor,
            roundoff * factor,
        )
        error = CorridorErrorReport(
            unit=request.error_budget.unit,
            linearization_bound=linearization_bound,
            floating_point_bound=floating_point_bound,
            total_bound=math.nextafter(linearization_bound + floating_point_bound, math.inf),
            requested_max_error=request.error_budget.max_error,
            boundary_segments=len(records),
        )
        return CorridorResult(
            **common,
            availability="supported",
            centerline=prepared,
            boundary=boundary,
            boundary_origin_in_centerline_frame=unique[0].point,
            polygon=ring,
            boundary_edges=tuple(edges),
            error=error,
        )
    except (ValueError, ArithmeticError) as exc:
        availability = exc.availability if isinstance(exc, _Unavailable) else "unsupported"
        return CorridorResult(
            **(common | {"limitations": _LIMITS + (str(exc),)}),
            availability=availability,
            centerline=prepared,
        )


def validate_corridor_result(result: CorridorResult) -> CorridorResult:
    """Reject changed width/centerline definitions, stale caches or forged boundaries."""
    result = CorridorResult.model_validate(result.model_dump(mode="json"))
    fresh = analyze_corridor(result.request)
    if result != fresh:
        raise ValueError("Corridor result differs from fresh canonical input reconstruction")
    return fresh
