"""Traverse positioning shared by closure verification and its checks.

One source of truth for which courses a traverse actually positions: closure,
area, exception loops and check fallbacks all derive positioning from here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from mp_bearing import (  # type: ignore[import-untyped]
    bearing_to_azimuth,
    calculate_deltas,
    compute_curve_endpoint,
)
from mp_models import DeedCall, Point

from .tangents import (
    chord_delta,
    chord_is_feasible,
    curve_sweep,
    has_determined_direction,
    is_curved_course,
    is_spiral,
    stated_sweep,
)


def _parse_chord(call: DeedCall) -> float | None:
    """Chord azimuth, or None when no chord bearing is stated or it cannot be parsed."""
    return bearing_to_azimuth(call.chord_bearing) if call.chord_bearing is not None else None


def _advance(call: DeedCall, current: Point, chord_azimuth: float | None) -> Point | None:
    """Return the endpoint of ``call`` from ``current``, or None when it is unpositioned.

    ``chord_azimuth`` is the call's chord bearing, parsed once by the caller.
    """
    if is_spiral(call):
        # Decided by curve type alone, even without radius or direction: a spiral's
        # shape is unknown, so only a stated chord bearing and length fix its endpoint
        # exactly. Otherwise it is unpositioned - never a circular arc, never run as
        # a straight line along its bearing and distance, and never tested against
        # the circular chord <= 2R bound.
        if call.chord_length_ft is None or call.chord_bearing is None:
            return None
        if chord_azimuth is None:
            raise ValueError(f"Course {call.course}: invalid chord bearing")
        dx, dy = calculate_deltas(chord_azimuth, call.chord_length_ft)
        return Point(x=current.x + dx, y=current.y + dy)

    if call.is_chord_only_curve():
        # Radius + chord without delta/arc: the arc is ambiguous (minor or
        # major), but the stated chord fixes the endpoint displacement exactly.
        assert call.chord_length_ft is not None and call.radius_ft is not None
        if not chord_is_feasible(call):
            # No circle of this radius has such a chord; leave it unpositioned.
            return None
        if chord_azimuth is None:
            raise ValueError(f"Course {call.course}: invalid chord bearing")
        dx, dy = calculate_deltas(chord_azimuth, call.chord_length_ft)
        return Point(x=current.x + dx, y=current.y + dy)

    if call.bearing_azimuth_deg_from_north is None:
        # A curve without a tangent is positioned by its chord bearing and the
        # deterministic chord 2R*sin(delta/2): exactly what plotting accepts.
        delta = curve_sweep(call) if chord_azimuth is not None else None
        if delta is None or chord_azimuth is None or call.radius_ft is None:
            return None
        chord_length = 2 * call.radius_ft * math.sin(math.radians(delta) / 2)
        dx, dy = calculate_deltas(chord_azimuth, chord_length)
        return Point(x=current.x + dx, y=current.y + dy)

    if call.is_curve() and call.radius_ft is not None and call.curve_dir is not None:
        stated = stated_sweep(call)
        if stated is not None and abs(stated) > 1e-9:
            # The same sweep rule as topology, tangents and area: invalid is unpositioned.
            delta_deg = curve_sweep(call)
            if delta_deg is None:
                return None
            if call.chord_bearing is not None:
                if chord_azimuth is None:
                    raise ValueError(f"Course {call.course}: invalid chord bearing")
                # A chord bearing already describes the endpoint vector.
                # Only tangent bearings need rotation by half the delta.
                chord_length = 2 * call.radius_ft * math.sin(math.radians(delta_deg) / 2)
                dx, dy = calculate_deltas(chord_azimuth, chord_length)
                return Point(x=current.x + dx, y=current.y + dy)
            endpoint: Point = compute_curve_endpoint(
                current,
                call.bearing_azimuth_deg_from_north,
                call.radius_ft,
                delta_deg,
                call.curve_dir,
            )
            return endpoint

    if call.distance_ft is None:
        # No determined length: the endpoint is unknown, never invented.
        return None
    dx, dy = calculate_deltas(call.bearing_azimuth_deg_from_north, call.distance_ft)
    return Point(x=current.x + dx, y=current.y + dy)


def traverse_positions(
    calls: list[DeedCall],
    start_point: Point | None = None,
) -> tuple[list[Point], list[bool]]:
    """Compute the traverse path and which calls it actually advanced through.

    Args:
        calls: List of DeedCall objects.
        start_point: Starting point (default: origin).

    Returns:
        (vertices, positioned) where positioned[i] is True only when calls[i]
        produced a vertex. Callers derive unpositioned courses from this outcome.
    """
    current = start_point if start_point is not None else Point(x=0, y=0)
    points = [current]
    positioned: list[bool] = []
    for call in calls:
        endpoint = _advance(call, current, _parse_chord(call))
        positioned.append(endpoint is not None)
        if endpoint is not None:
            current = endpoint
            points.append(current)
    return points, positioned


@dataclass(frozen=True)
class CourseAnalysis:
    """How verification treats one boundary call, decided in a single pass.

    Attributes:
        index: Position of the call in the boundary (course numbers may repeat).
        call: The stated call, never modified.
        chord_azimuth: Parsed chord bearing (None when absent or unparseable).
        bad_chord: A curve whose stated chord bearing cannot be parsed; never guessed.
        no_endpoint: A bad-chord curve with no delta or arc: no determinable endpoint.
        chord_only: A curve stated by radius and chord without delta or arc.
        feasible_chord: False when a chord-only chord exceeds the diameter.
        chord_positioned_delta: Sweep (deg) positioning a tangent-less curve by its chord.
        arc_undetermined: Positioned by a stated chord only (chord-only curve or
            spiral): the arc shape, area and perimeter are not determined.
        positioned: The traverse actually produced a vertex for this call.
        determined_direction: The direction is stated or fixed by curve elements.
    """

    index: int
    call: DeedCall
    chord_azimuth: float | None
    bad_chord: bool
    no_endpoint: bool
    chord_only: bool
    feasible_chord: bool
    chord_positioned_delta: float | None
    arc_undetermined: bool
    positioned: bool
    determined_direction: bool


def analyze_courses(calls: list[DeedCall]) -> tuple[list[Point], list[CourseAnalysis]]:
    """Traverse boundary calls as verification does and record each call's analysis.

    An unparseable chord bearing is never guessed: the course is traversed without
    its chord. Without its chord, a curve with no delta or arc has no determinable
    endpoint, so it also loses its bearing for traversal and is never run along its
    tangent. The stated calls themselves are never modified.
    """
    current = Point(x=0, y=0)
    points = [current]
    records: list[CourseAnalysis] = []
    for index, call in enumerate(calls):
        chord_azimuth = _parse_chord(call)
        bad_chord = (
            is_curved_course(call) and call.chord_bearing is not None and chord_azimuth is None
        )
        no_endpoint = bad_chord and call.delta_deg is None and call.arc_length_ft is None
        traversed = call
        if bad_chord:
            update: dict[str, object] = {"chord_bearing": None}
            if no_endpoint:
                update["bearing_azimuth_deg_from_north"] = None
            traversed = call.model_copy(update=update)
        # A spiral is never a chord-only circular curve (minor/major arc ambiguity).
        chord_only = call.is_chord_only_curve() and not is_spiral(call)
        feasible_chord = not (chord_only and not chord_is_feasible(call))
        endpoint = _advance(traversed, current, chord_azimuth)
        if endpoint is not None:
            current = endpoint
            points.append(current)
        records.append(
            CourseAnalysis(
                index=index,
                call=call,
                chord_azimuth=chord_azimuth,
                bad_chord=bad_chord,
                no_endpoint=no_endpoint,
                chord_only=chord_only,
                feasible_chord=feasible_chord,
                chord_positioned_delta=chord_delta(call, chord_azimuth),
                arc_undetermined=chord_only or (endpoint is not None and is_spiral(call)),
                positioned=endpoint is not None,
                determined_direction=has_determined_direction(call),
            )
        )
    return points, records


def position_courses(calls: list[DeedCall]) -> tuple[list[Point], list[bool]]:
    """Traverse boundary calls as verification does, returning (vertices, positioned)."""
    points, records = analyze_courses(calls)
    return points, [record.positioned for record in records]
