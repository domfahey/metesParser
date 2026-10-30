"""Curve sweep and tangent directions derived from stated curve elements.

Values computed here are internal to verification and are never stored on a
``DeedCall``: a curve without a stated tangent keeps ``None`` as its bearing.
"""

from __future__ import annotations

import math

from mp_bearing import bearing_to_azimuth  # type: ignore[import-untyped]
from mp_models import DeedCall


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
    if call.curve_type == "spiral":
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
