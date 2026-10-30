"""Traverse positioning shared by closure verification and its checks.

One source of truth for which courses a traverse actually positions: closure,
area, exception loops and check fallbacks all derive positioning from here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from mp_bearing import (  # type: ignore[import-untyped]
    calculate_deltas,
    compute_curve_endpoint,
)
from mp_models import DeedCall, Point

from .tangents import (
    chord_is_feasible,
    curve_sweep,
    has_determined_direction,
    is_curved_course,
    is_spiral,
    parse_chord,
    radial_tangent_in,
    stated_sweep,
    stated_tangent,
)


def _advance(call: DeedCall, current: Point, chord_azimuth: float | None) -> Point | None:
    """Return the endpoint of ``call`` from ``current``, or None when it is unpositioned.

    ``chord_azimuth`` is the call's chord bearing, parsed once by the caller.
    """
    if is_curved_course(call) and call.chord_bearing is not None and chord_azimuth is None:
        # A stated but unreadable chord makes the course's geometry suspect: it is
        # never positioned by a tangent or radial bearing instead (plot agrees).
        return None

    if is_spiral(call):
        # Decided by curve type alone, even without radius or direction: a spiral's
        # shape is unknown, so only a stated chord bearing and length fix its endpoint
        # exactly. Otherwise it is unpositioned - never a circular arc, never run as
        # a straight line along its bearing and distance, and never tested against
        # the circular chord <= 2R bound.
        if call.chord_length_ft is None or call.chord_bearing is None:
            return None
        assert chord_azimuth is not None
        dx, dy = calculate_deltas(chord_azimuth, call.chord_length_ft)
        return Point(x=current.x + dx, y=current.y + dy)

    if call.is_chord_only_curve():
        # Radius + chord without delta/arc: the arc is ambiguous (minor or
        # major), but the stated chord fixes the endpoint displacement exactly.
        assert call.chord_length_ft is not None and call.radius_ft is not None
        if not chord_is_feasible(call):
            # No circle of this radius has such a chord; leave it unpositioned.
            return None
        assert chord_azimuth is not None
        dx, dy = calculate_deltas(chord_azimuth, call.chord_length_ft)
        return Point(x=current.x + dx, y=current.y + dy)

    tangent = stated_tangent(call)
    if tangent is None:
        # A curve without a stated tangent (none given, or a non-tangent curve whose
        # course bearing is not its tangent) is positioned by its chord bearing and
        # the deterministic chord 2R*sin(delta/2), else by a non-tangent curve's
        # stated radial bearing: exactly what plotting accepts.
        delta = curve_sweep(call)
        if delta is None or call.radius_ft is None:
            return None
        if chord_azimuth is not None:
            chord_length = 2 * call.radius_ft * math.sin(math.radians(delta) / 2)
            dx, dy = calculate_deltas(chord_azimuth, chord_length)
            return Point(x=current.x + dx, y=current.y + dy)
        if call.chord_bearing is not None:
            return None
        radial_in = radial_tangent_in(call)
        if radial_in is None:
            return None
        radial_end: Point = compute_curve_endpoint(
            current, radial_in, call.radius_ft, delta, call.curve_dir
        )
        return radial_end

    if call.is_curve() and call.radius_ft is not None and call.curve_dir is not None:
        stated = stated_sweep(call)
        if stated is not None and abs(stated) > 1e-9:
            # The same sweep rule as topology, tangents and area: invalid is unpositioned.
            delta_deg = curve_sweep(call)
            if delta_deg is None:
                return None
            if call.chord_bearing is not None:
                assert chord_azimuth is not None
                # A chord bearing already describes the endpoint vector.
                # Only tangent bearings need rotation by half the delta.
                chord_length = 2 * call.radius_ft * math.sin(math.radians(delta_deg) / 2)
                dx, dy = calculate_deltas(chord_azimuth, chord_length)
                return Point(x=current.x + dx, y=current.y + dy)
            endpoint: Point = compute_curve_endpoint(
                current,
                tangent,
                call.radius_ft,
                delta_deg,
                call.curve_dir,
            )
            return endpoint

    if call.distance_ft is None:
        # No determined length: the endpoint is unknown, never invented.
        return None
    dx, dy = calculate_deltas(tangent, call.distance_ft)
    return Point(x=current.x + dx, y=current.y + dy)


@dataclass(frozen=True)
class CourseAnalysis:
    """How verification treats one boundary call, decided in a single pass.

    Attributes:
        index: Position of the call in the boundary (course numbers may repeat).
        call: The stated call, never modified.
        bad_chord: A curve whose stated chord bearing cannot be parsed; never guessed.
        chord_only: A curve stated by radius and chord without delta or arc.
        feasible_chord: False when a chord-only chord exceeds the diameter.
        arc_undetermined: Positioned by a stated chord only (chord-only curve or
            spiral): the arc shape, area and perimeter are not determined.
        positioned: The traverse actually produced a vertex for this call.
        determined_direction: The direction is stated or fixed by curve elements.
    """

    index: int
    call: DeedCall
    bad_chord: bool
    chord_only: bool
    feasible_chord: bool
    arc_undetermined: bool
    positioned: bool
    determined_direction: bool

    @property
    def chord_positioned(self) -> bool:
        """A stated chord alone positions the course with no known tangent.

        A course whose direction evidence conflicts (the parser's cardinal/chord
        conflict leaves it indefinite) does not state a direction.
        """
        return (
            self.positioned
            and self.arc_undetermined
            and not self.determined_direction
            and not self.call.is_indefinite
        )


def analyze_courses(
    calls: list[DeedCall], start_point: Point | None = None
) -> tuple[list[Point], list[CourseAnalysis]]:
    """Traverse boundary calls as verification does and record each call's analysis.

    An unparseable chord bearing is never guessed and never replaced by a tangent or
    radial bearing: that curve is unpositioned (blocked), exactly as plotting treats
    it. The stated calls themselves are never modified.
    """
    current = start_point if start_point is not None else Point(x=0, y=0)
    points = [current]
    records: list[CourseAnalysis] = []
    for index, call in enumerate(calls):
        chord_azimuth = parse_chord(call)
        bad_chord = (
            is_curved_course(call) and call.chord_bearing is not None and chord_azimuth is None
        )
        # A spiral is never a chord-only circular curve (minor/major arc ambiguity).
        chord_only = call.is_chord_only_curve() and not is_spiral(call)
        feasible_chord = not (chord_only and not chord_is_feasible(call))
        endpoint = _advance(call, current, chord_azimuth)
        if endpoint is not None:
            current = endpoint
            points.append(current)
        records.append(
            CourseAnalysis(
                index=index,
                call=call,
                bad_chord=bad_chord,
                chord_only=chord_only,
                feasible_chord=feasible_chord,
                arc_undetermined=chord_only or (endpoint is not None and is_spiral(call)),
                positioned=endpoint is not None,
                determined_direction=has_determined_direction(call),
            )
        )
    return points, records


def traverse_positions(
    calls: list[DeedCall],
    start_point: Point | None = None,
) -> tuple[list[Point], list[bool]]:
    """Compute the traverse path and which calls it actually advanced through.

    Returns (vertices, positioned) where positioned[i] is True only when calls[i]
    produced a vertex. Callers derive unpositioned courses from this outcome.
    """
    points, records = analyze_courses(calls, start_point)
    return points, [record.positioned for record in records]


def chord_positioned_flags(calls: list[DeedCall]) -> list[bool]:
    """Per call: is it positioned by a stated chord alone (one traverse pass)?

    Positioning is independent of earlier courses, so this equals calling
    is_chord_positioned on each call.
    """
    _, records = analyze_courses(calls)
    return [record.chord_positioned for record in records]


def is_chord_positioned(call: DeedCall) -> bool:
    """Return True when a stated chord alone positions a course with no known tangent.

    A chord-only circular curve or spiral whose chord bearing and length the traverse
    uses: its direction is stated (by the chord) although its tangent direction and
    arc are not determined. Decided by the traverse itself, never predicted. An
    indefinite call (including a cardinal word that conflicts with the chord) does not
    state a direction.
    """
    return chord_positioned_flags([call])[0]
