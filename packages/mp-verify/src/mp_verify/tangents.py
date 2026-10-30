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


def stated_sweep(call: DeedCall) -> float | None:
    """Return the stated sweep (delta, else arc / radius) with no validity check."""
    if call.delta_deg is not None:
        return call.delta_deg
    if call.arc_length_ft is not None and call.radius_ft is not None and call.radius_ft > 0:
        return math.degrees(call.arc_length_ft / call.radius_ft)
    return None


def curve_sweep(call: DeedCall) -> float | None:
    """Return the stated sweep in degrees (delta, else arc / radius) when valid."""
    if call.curve_dir not in ("left", "right") or call.radius_ft is None or call.radius_ft <= 0:
        return None
    delta = stated_sweep(call)
    if delta is None or not math.isfinite(delta) or not 0.0 < delta <= 360.0:
        return None
    return delta


def chord_delta(call: DeedCall, chord_azimuth: float | None) -> float | None:
    """Return the sweep (deg) positioning a tangent-less circular curve by its chord.

    ``chord_azimuth`` is the already-parsed chord bearing (None when absent or
    unparseable). Mirrors mp_verify.plot._arc: radius, direction and a sweep from
    delta or arc length (0 < sweep <= 360). The chord is then 2R*sin(delta/2),
    computed by callers and never stored.
    """
    if chord_azimuth is None or not is_circular_curve(call):
        return None
    return curve_sweep(call)


def chord_positioned_delta(call: DeedCall) -> float | None:
    """Return the chord-positioning sweep, parsing the call's chord bearing."""
    chord = bearing_to_azimuth(call.chord_bearing) if call.chord_bearing is not None else None
    return chord_delta(call, chord)


def is_non_tangent_curve(call: DeedCall) -> bool:
    """Return True for a circular curve the deed states is not tangent to the prior course."""
    return call.non_tangent and call.is_curve() and is_circular_curve(call)


def stated_tangent(call: DeedCall) -> float | None:
    """Return the course bearing when it states the course's starting direction.

    A non-tangent curve's course bearing does not establish its starting tangent:
    the deed says only that the curve is not tangent to the previous line, so the
    role of the stated bearing is ambiguous and it is never used as the tangent.
    """
    if is_non_tangent_curve(call):
        return None
    return call.bearing_azimuth_deg_from_north


def radial_tangent_in(call: DeedCall) -> float | None:
    """Return the tangent-in fixed by a non-tangent curve's stated radial bearing.

    The parser stores the radial bearing as the bearing from the curve's start
    toward its centre (radius point), and the centre lies to the curve's side of
    the tangent, so tangent-in = radial - dir * 90 (right = +1).
    """
    if not is_non_tangent_curve(call):
        return None
    return radial_implied_tangent(call)


def radial_implied_tangent(call: DeedCall) -> float | None:
    """Return the tangent-in implied by a stated radial bearing, tangent or not."""
    if call.radial_bearing is None or call.curve_dir not in ("left", "right"):
        return None
    radial: float | None = bearing_to_azimuth(call.radial_bearing)
    if radial is None or not math.isfinite(radial):
        return None
    sign = 1.0 if call.curve_dir == "right" else -1.0
    return (radial - sign * 90.0) % 360.0


def start_tangent(call: DeedCall, delta: float, chord_azimuth: float | None) -> float | None:
    """Return the azimuth at which a circular curve of sweep ``delta`` starts.

    A chord bearing with the sweep fixes it (chord - dir * delta / 2, right = +1);
    otherwise a non-tangent curve needs a stated radial bearing, and any other
    curve its stated tangent bearing. Shared by traverse, plotting and topology.
    """
    sign = 1.0 if call.curve_dir == "right" else -1.0
    if chord_azimuth is not None:
        tangent_in: float | None = chord_azimuth - sign * delta / 2.0
    elif is_non_tangent_curve(call):
        tangent_in = radial_tangent_in(call)
    else:
        tangent_in = call.bearing_azimuth_deg_from_north
    if tangent_in is None or not math.isfinite(tangent_in):
        return None
    return tangent_in


def curve_tangents(call: DeedCall) -> tuple[float, float] | None:
    """Return (tangent-in, tangent-out) azimuths for a fully determined circular curve.

    A parseable chord bearing with a sweep fixes both tangents
    (chord -/+ dir * delta / 2, right = +1), matching how the traverse and the
    topology check position the arc. Otherwise a stated tangent with a sweep is
    used; a non-tangent curve's course bearing is never its tangent, so it needs a
    stated radial bearing instead. Chord-only curves (no delta or arc) and spirals
    return None.
    """
    if not is_circular_curve(call):
        return None
    delta = curve_sweep(call)
    if delta is None:
        return None
    sign = 1.0 if call.curve_dir == "right" else -1.0
    chord = bearing_to_azimuth(call.chord_bearing) if call.chord_bearing is not None else None
    tangent_in = start_tangent(call, delta, chord)
    if tangent_in is None:
        return None
    return tangent_in % 360.0, (tangent_in + sign * delta) % 360.0


def has_determined_direction(call: DeedCall) -> bool:
    """Return True when the course direction is stated or fixed by stated curve elements."""
    return stated_tangent(call) is not None or curve_tangents(call) is not None
