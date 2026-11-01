"""Analytic intersections of finite straight segments and circular arc sweeps."""

from __future__ import annotations

import math
from dataclasses import dataclass

from mp_bearing import bearing_to_azimuth
from mp_models import DeedCall, Point

from .tangents import curve_sweep, curve_tangents, is_circular_curve

_TOL = 1e-7  # Feet: construction roundoff, not the traverse closure tolerance.
XY = tuple[float, float]


def _distance(a: XY, b: XY) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _is_curved(call: DeedCall) -> bool:
    return call.is_curve() or call.curve_type is not None


def _coordinate_roundoff(*points: XY) -> float:
    """Bound subtraction noise when local geometry has large global offsets."""
    return 16 * max(math.ulp(coordinate) for point in points for coordinate in point)


@dataclass(frozen=True)
class _Arc:
    center: XY
    radius: float
    start: float  # Mathematical polar angle, counterclockwise from east.
    sweep: float  # Positive angular magnitude.
    turn: int  # +1 counterclockwise (left), -1 clockwise (right).

    def contains(self, point: XY) -> bool:
        if abs(_distance(point, self.center) - self.radius) > _TOL:
            return False
        theta = math.atan2(point[1] - self.center[1], point[0] - self.center[0])
        progress = ((theta - self.start) * self.turn) % math.tau
        angular_tol = _TOL / self.radius
        return progress <= self.sweep + angular_tol or math.tau - progress <= angular_tol

    def point(self, theta: float) -> XY:
        return (
            self.center[0] + self.radius * math.cos(theta),
            self.center[1] + self.radius * math.sin(theta),
        )

    def intervals(self) -> list[tuple[float, float]]:
        if self.sweep >= math.tau:
            return [(0.0, math.tau)]
        start = (self.start if self.turn == 1 else self.start - self.sweep) % math.tau
        end = start + self.sweep
        return [(start, end)] if end <= math.tau else [(start, math.tau), (0.0, end - math.tau)]


def _make_arc(call: DeedCall, start: XY, end: XY) -> _Arc:
    if not is_circular_curve(call):
        raise ValueError("spiral geometry is not a circular arc")
    radius = call.radius_ft
    if radius is None or radius <= 0 or call.curve_dir not in ("left", "right"):
        raise ValueError("missing circular radius or direction")
    delta = curve_sweep(call)
    if delta is None:
        raise ValueError("missing or invalid circular sweep")
    sign = 1 if call.curve_dir == "right" else -1
    if call.chord_bearing is not None and bearing_to_azimuth(call.chord_bearing) is None:
        raise ValueError("invalid chord bearing")
    # Stated tangent, or the tangent fixed by chord bearing and sweep (never stored).
    tangents = curve_tangents(call)
    if tangents is None:
        raise ValueError("missing tangent or chord bearing")
    radians = math.radians(tangents[0])
    center = (
        start[0] + sign * radius * math.cos(radians),
        start[1] - sign * radius * math.sin(radians),
    )
    angle = math.atan2(start[1] - center[1], start[0] - center[0])
    arc = _Arc(center, radius, angle, math.radians(delta), -sign)
    expected_end = arc.point(angle + arc.turn * arc.sweep)
    if _distance(expected_end, end) > _TOL:
        raise ValueError("circular sweep does not match traverse endpoints")
    return arc


def _line_arc(a: XY, b: XY, arc: _Arc) -> list[XY]:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return [a] if arc.contains(a) else []
    # Project the center onto the infinite line, then restrict roots to the segment.
    t = ((arc.center[0] - a[0]) * dx + (arc.center[1] - a[1]) * dy) / length2
    foot = (a[0] + t * dx, a[1] + t * dy)
    distance2 = _distance(foot, arc.center) ** 2
    height2 = arc.radius**2 - distance2
    # Cancellation at an exact tangent must not invent two nearby crossings.
    uncertainty = _coordinate_roundoff(a, b, arc.center)
    roundoff = max(
        16 * math.ulp(max(arc.radius**2, distance2)), uncertainty * (2 * arc.radius + uncertainty)
    )
    if abs(height2) <= roundoff:
        height2 = 0.0
    if height2 < -_TOL * (2 * arc.radius + _TOL):
        return []
    offset = math.sqrt(max(0.0, height2) / length2)
    parameter_tol = _TOL / math.sqrt(length2)
    points = []
    for root in (t - offset, t + offset):
        if -parameter_tol <= root <= 1 + parameter_tol:
            point = (a[0] + root * dx, a[1] + root * dy)
            if arc.contains(point):
                points.append(point)
    return points


def _arc_arc(first: _Arc, second: _Arc) -> tuple[list[XY], bool]:
    # Construct candidates from the smaller circle to avoid subtracting two
    # nearly equal large squared values and then missing its tiny circumference.
    if first.radius > second.radius:
        first, second = second, first
    distance = _distance(first.center, second.center)
    r1, r2 = first.radius, second.radius
    if distance <= _TOL and abs(r1 - r2) <= _TOL:
        # Coincident circles need interval overlap checks, not a two-root formula.
        overlap = any(
            (min(b, d) - max(a, c)) * min(r1, r2) > _TOL
            for a, b in first.intervals()
            for c, d in second.intervals()
        )
        endpoints = [
            arc.point(theta)
            for arc in (first, second)
            for theta in (arc.start, arc.start + arc.turn * arc.sweep)
        ]
        return [p for p in endpoints if first.contains(p) and second.contains(p)], overlap
    if distance == 0 or distance > r1 + r2 + _TOL or distance < abs(r1 - r2) - _TOL:
        return [], False
    along = ((distance - r2) * (distance + r2) + r1**2) / (2 * distance)
    height2 = r1**2 - along**2
    uncertainty = _coordinate_roundoff(first.center, second.center)
    roundoff = max(16 * math.ulp(max(r1**2, along**2)), uncertainty * (2 * r1 + uncertainty))
    if abs(height2) <= roundoff:
        height2 = 0.0
    if height2 < -_TOL * (2 * r1 + _TOL):
        return [], False
    height = math.sqrt(max(0.0, height2))
    ux = (second.center[0] - first.center[0]) / distance
    uy = (second.center[1] - first.center[1]) / distance
    base = (first.center[0] + along * ux, first.center[1] + along * uy)
    candidates = [
        (base[0] - height * uy, base[1] + height * ux),
        (base[0] + height * uy, base[1] - height * ux),
    ]
    return [p for p in candidates if first.contains(p) and second.contains(p)], False


def check_curved_boundary_intersections(
    calls: list[DeedCall], coordinates: list[Point]
) -> list[str]:
    """Report line–arc/arc–arc contacts beyond legitimate neighboring endpoints.

    Unsupported or incomplete arcs produce warnings rather than a false clear
    result. Ordinary straight–straight checks remain in checks.py.
    """
    if not any(_is_curved(call) for call in calls):
        return []
    if len(coordinates) != len(calls) + 1:
        return ["Boundary intersection check unavailable: incomplete traverse coordinates"]
    points = [(point.x, point.y) for point in coordinates]
    arcs: dict[int, _Arc] = {}
    warnings = []
    for index, call in enumerate(calls):
        if _is_curved(call):
            try:
                arcs[index] = _make_arc(call, points[index], points[index + 1])
                if arcs[index].sweep == math.tau and len(calls) > 1:
                    warnings.append(
                        f"Course {call.course}: curved boundary self-intersection "
                        "(full-circle loop closes before the remaining boundary)"
                    )
            except ValueError as exc:
                warnings.append(
                    f"Course {call.course}: boundary intersection check unavailable ({exc})"
                )
    closed = _distance(points[0], points[-1]) < 0.01
    for i, first in enumerate(calls):
        for j in range(i + 1, len(calls)):
            second = calls[j]
            if not _is_curved(first) and not _is_curved(second):
                continue
            if (_is_curved(first) and i not in arcs) or (_is_curved(second) and j not in arcs):
                continue
            overlap = False
            if i in arcs and j in arcs:
                intersections, overlap = _arc_arc(arcs[i], arcs[j])
            elif i in arcs:
                intersections = _line_arc(points[j], points[j + 1], arcs[i])
            else:
                intersections = _line_arc(points[i], points[i + 1], arcs[j])
            shared = []
            if j == i + 1:
                shared.append(points[j])
            if closed and i == 0 and j == len(calls) - 1:
                shared.append(points[0])
            if overlap or any(
                not any(_distance(p, endpoint) <= _TOL for endpoint in shared)
                for p in intersections
            ):
                warnings.append(
                    f"Courses {first.course}-{second.course}: curved boundary self-intersection "
                    "(crossing, overlap, or nonadjacent touch)"
                )
    return warnings
