"""Traverse positioning shared by closure verification and its checks.

One source of truth for which courses a traverse actually positions: closure,
area, exception loops and check fallbacks all derive positioning from here.
"""

from __future__ import annotations

import math

from mp_bearing import (  # type: ignore[import-untyped]
    bearing_to_azimuth,
    calculate_deltas,
    compute_curve_endpoint,
)
from mp_models import DeedCall, Point

from .tangents import chord_positioned_delta


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
    if start_point is None:
        start_point = Point(x=0, y=0)
    points = [start_point]
    current = start_point
    positioned: list[bool] = []

    for call in calls:
        if call.is_chord_only_curve():
            # Radius + chord without delta/arc: the arc is ambiguous (minor or
            # major), but the stated chord fixes the endpoint displacement exactly.
            assert call.chord_bearing is not None and call.chord_length_ft is not None
            assert call.radius_ft is not None
            if call.chord_length_ft > 2.0 * abs(call.radius_ft):
                # No circle of this radius has such a chord; leave it unpositioned.
                positioned.append(False)
                continue
            chord_azimuth = bearing_to_azimuth(call.chord_bearing)
            if chord_azimuth is None:
                raise ValueError(f"Course {call.course}: invalid chord bearing")
            dx, dy = calculate_deltas(chord_azimuth, call.chord_length_ft)
            current = Point(x=current.x + dx, y=current.y + dy)
            points.append(current)
            positioned.append(True)
            continue

        if call.bearing_azimuth_deg_from_north is None:
            # A curve without a tangent is positioned by its chord bearing and the
            # deterministic chord 2R*sin(delta/2): exactly what plotting accepts.
            delta = chord_positioned_delta(call)
            chord_azimuth = (
                bearing_to_azimuth(call.chord_bearing)
                if delta is not None and call.chord_bearing is not None
                else None
            )
            if delta is None or chord_azimuth is None or call.radius_ft is None:
                positioned.append(False)
                continue
            chord_length = 2 * call.radius_ft * math.sin(math.radians(delta) / 2)
            dx, dy = calculate_deltas(chord_azimuth, chord_length)
            current = Point(x=current.x + dx, y=current.y + dy)
            points.append(current)
            positioned.append(True)
            continue

        if call.is_curve():
            next_point: Point | None = None

            if call.radius_ft is not None and call.curve_dir is not None:
                delta_deg = call.delta_deg
                if delta_deg is None and call.arc_length_ft is not None and call.radius_ft > 0.0:
                    delta_deg = math.degrees(call.arc_length_ft / call.radius_ft)

                if delta_deg is not None and abs(delta_deg) > 1e-9:
                    if call.chord_bearing is not None:
                        chord_azimuth = bearing_to_azimuth(call.chord_bearing)
                        if chord_azimuth is None:
                            raise ValueError(f"Course {call.course}: invalid chord bearing")
                        # A chord bearing already describes the endpoint vector.
                        # Only tangent bearings need rotation by half the delta.
                        chord_length = 2 * call.radius_ft * math.sin(math.radians(delta_deg) / 2)
                        dx, dy = calculate_deltas(chord_azimuth, chord_length)
                        next_point = Point(x=current.x + dx, y=current.y + dy)
                    else:
                        next_point = compute_curve_endpoint(
                            current,
                            call.bearing_azimuth_deg_from_north,
                            call.radius_ft,
                            delta_deg,
                            call.curve_dir,
                        )

            if next_point is None:
                dx, dy = calculate_deltas(
                    call.bearing_azimuth_deg_from_north,
                    call.distance_ft,
                )
                next_point = Point(x=current.x + dx, y=current.y + dy)
        else:
            dx, dy = calculate_deltas(
                call.bearing_azimuth_deg_from_north,
                call.distance_ft,
            )
            next_point = Point(x=current.x + dx, y=current.y + dy)

        points.append(next_point)
        positioned.append(True)
        current = next_point

    return points, positioned


def has_unparseable_chord(call: DeedCall) -> bool:
    """A curve whose stated chord bearing cannot be parsed (never guessed)."""
    return (
        call.is_curve()
        and call.chord_bearing is not None
        and bearing_to_azimuth(call.chord_bearing) is None
    )


def traversable_call(call: DeedCall) -> DeedCall:
    """Return the call as traversed: an unparseable chord bearing is dropped.

    Without its chord, a curve with no delta or arc has no determinable endpoint,
    so it also loses its bearing for traversal and is never run along its tangent.
    The stated call itself is never modified.
    """
    if not has_unparseable_chord(call):
        return call
    if call.delta_deg is None and call.arc_length_ft is None:
        return call.model_copy(
            update={"chord_bearing": None, "bearing_azimuth_deg_from_north": None}
        )
    return call.model_copy(update={"chord_bearing": None})


def position_courses(calls: list[DeedCall]) -> tuple[list[Point], list[bool]]:
    """Traverse boundary calls as verification does, returning (vertices, positioned)."""
    return traverse_positions([traversable_call(call) for call in calls])
