"""Curve sweep and tangent directions derived from stated curve elements.

Values computed here are internal to verification and are never stored on a
``DeedCall``: a curve without a stated tangent keeps ``None`` as its bearing.
"""

from __future__ import annotations

import math

from mp_bearing import bearing_to_azimuth  # type: ignore[import-untyped]
from mp_models import DeedCall


def is_spiral(call: DeedCall) -> bool:
    """Return True for a spiral, decided by its curve type alone.

    A spiral is never a circular arc and never a straight line, even when it states
    no radius or curve direction (``DeedCall.is_curve()`` is then False). It is
    positioned only by a stated chord bearing and chord length; otherwise unpositioned.
    """
    return call.curve_type == "spiral"


def is_circular_curve(call: DeedCall) -> bool:
    """Return False for curve types whose shape is not a circular arc (spirals).

    The single predicate deciding whether circular-arc geometry (chord 2R*sin(d/2),
    circular segment area, R*delta perimeter, arc tangents) may be derived.
    """
    return not is_spiral(call)


def is_curved_course(call: DeedCall) -> bool:
    """Return True for any course that is not a straight line (circular curve or spiral)."""
    return call.is_curve() or is_spiral(call)


def line_distance(call: DeedCall) -> float:
    """Return a course's recorded distance, refusing one that is not determined.

    Only a spiral with no stated length has ``distance_ft=None``; such a course is
    never measured as a line.
    """
    if call.distance_ft is None:
        raise ValueError(f"Course {call.course}: course distance not determined")
    return call.distance_ft


def chord_is_feasible(call: DeedCall) -> bool:
    """Return False when a stated chord exceeds the diameter 2*|radius| (no such circle)."""
    if call.chord_length_ft is None or call.radius_ft is None:
        return True
    return call.chord_length_ft <= 2.0 * abs(call.radius_ft)


def curve_sweep(call: DeedCall) -> float | None:
    """Return the stated sweep in degrees (delta, else arc / radius) when valid."""
    if call.curve_dir not in ("left", "right") or call.radius_ft is None or call.radius_ft <= 0:
        return None
    delta = call.delta_deg
    if delta is None and call.arc_length_ft is not None:
        delta = math.degrees(call.arc_length_ft / call.radius_ft)
    if delta is None or not math.isfinite(delta) or not 0.0 < delta <= 360.0:
        return None
    return delta


def chord_positioned_delta(call: DeedCall) -> float | None:
    """Return the sweep (deg) when a tangent-less curve is positioned by its chord.

    Mirrors mp_verify.plot._arc: radius, direction and a sweep from delta or
    arc length (0 < sweep <= 360) with a parseable chord bearing. The chord is
    then 2R*sin(delta/2), computed here and never stored.
    """
    if not is_circular_curve(call):
        return None
    if call.chord_bearing is None or bearing_to_azimuth(call.chord_bearing) is None:
        return None
    return curve_sweep(call)


def curve_tangents(call: DeedCall) -> tuple[float, float] | None:
    """Return (tangent-in, tangent-out) azimuths for a fully determined circular curve.

    A parseable chord bearing with a sweep fixes both tangents
    (chord -/+ dir * delta / 2, right = +1), matching how the traverse and the
    topology check position the arc. Otherwise a stated tangent with a sweep is
    used. Chord-only curves (no delta or arc) and spirals return None.
    """
    if not is_circular_curve(call):
        return None
    delta = curve_sweep(call)
    if delta is None:
        return None
    sign = 1.0 if call.curve_dir == "right" else -1.0
    chord = bearing_to_azimuth(call.chord_bearing) if call.chord_bearing is not None else None
    if chord is not None:
        tangent_in = chord - sign * delta / 2.0
    elif call.bearing_azimuth_deg_from_north is not None:
        tangent_in = call.bearing_azimuth_deg_from_north
    else:
        return None
    if not math.isfinite(tangent_in):
        return None
    return tangent_in % 360.0, (tangent_in + sign * delta) % 360.0


def has_determined_direction(call: DeedCall) -> bool:
    """Return True when the course direction is stated or fixed by stated curve elements."""
    return call.is_complete_bearing() or curve_tangents(call) is not None
