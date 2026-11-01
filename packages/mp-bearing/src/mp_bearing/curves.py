"""Curve calculation utilities for metes and bounds parsing.

Computes curve properties (arc length, chord, tangent, etc.) from radius
and central angle, fills in missing curve elements, and calculates chord
bearings and curve endpoints.
"""

from __future__ import annotations

import math

from mp_models import Point

from .deltas import calculate_deltas

# Redundant curve elements (stated arc vs R*delta, stated chord vs 2R*sin(delta/2),
# delta vs twice the tangent-to-chord deflection) are compared within the rounding
# of the stated values, propagated through the curve formulas. Verification
# (mp_verify.checks) and plotting (mp_verify.plot) use these helpers so a curve
# accepted by one is never rejected by the other. The parser does not compare
# curve elements.
#
# DeedCall carries decimal degrees, so the stated precision is inferred from the
# value: lengths are taken as stated to the hundredth (+/-0.005 ft); an angle whose
# seconds component is zero and whose minutes are not (e.g. 12 deg 34') is taken as
# stated to the minute (+/-30"); any other angle, including a whole degree, to the
# second (+/-0.5"). A whole degree is not widened: +/-30' would be far too lenient,
# and the whole-degree fixtures (N 90 deg E, delta 12 deg) are generated to the second.
STATED_LENGTH_HALF_UNIT_FT = 0.005
STATED_ANGLE_HALF_UNIT_RAD = math.radians(0.5 / 3600)
STATED_MINUTE_HALF_UNIT_RAD = math.radians(30.0 / 3600)
_WHOLE_MINUTE_SECONDS_EPS = 1e-6

# Floor so small curves keep a usable tolerance. There is no linear cap: the
# propagated tolerance (R*d(delta), up to ~0.7 ft at R=5000 for a minute-stated
# delta) already bounds gross errors, and a fixed cap would reject correctly
# rounded minute-stated curves at large radii. The angular cap only guards tiny
# radii where an arc's rounding would otherwise dominate.
CURVE_ELEMENT_TOLERANCE_FT = 0.01
TANGENT_CHORD_TOLERANCE_DEG = 1.5 / 3600
TANGENT_CHORD_TOLERANCE_CAP_DEG = 0.1


def angle_half_unit_rad(angle_deg: float) -> float:
    """Return the rounding half-unit of a stated angle, inferred from its value."""
    total_seconds = abs(angle_deg) * 3600.0
    seconds = total_seconds % 60.0
    on_whole_minute = min(seconds, 60.0 - seconds) <= _WHOLE_MINUTE_SECONDS_EPS
    on_whole_degree = min(total_seconds % 3600.0, 3600.0 - total_seconds % 3600.0) <= (
        _WHOLE_MINUTE_SECONDS_EPS
    )
    if on_whole_minute and not on_whole_degree:
        return STATED_MINUTE_HALF_UNIT_RAD
    return STATED_ANGLE_HALF_UNIT_RAD


def delta_uncertainty_rad(
    *,
    delta_deg: float | None = None,
    arc_length_ft: float | None = None,
    radius_ft: float | None = None,
) -> float:
    """Return the rounding uncertainty of a curve's delta, in radians.

    A stated delta (no arc and radius given) carries its inferred half-unit
    (30" for a whole minute that is not a whole degree, else 0.5"). A delta derived as arc / R carries the
    stated arc's and radius's rounding: d(delta) = d(arc)/R + arc*d(R)/R**2.
    """
    if arc_length_ft is None or radius_ft is None or radius_ft <= 0.0:
        if delta_deg is None:
            return STATED_ANGLE_HALF_UNIT_RAD
        return angle_half_unit_rad(delta_deg)
    return (
        STATED_LENGTH_HALF_UNIT_FT / radius_ft
        + abs(arc_length_ft) * STATED_LENGTH_HALF_UNIT_FT / radius_ft**2
    )


def bearing_difference_uncertainty_rad(*angles_deg: float) -> float:
    """Return the combined rounding of stated bearings/azimuths that are differenced."""
    return sum(angle_half_unit_rad(angle) for angle in angles_deg)


def arc_length_tolerance_ft(radius_ft: float, delta_deg: float) -> float:
    """Return the tolerance for a stated arc against R*delta (stated R and delta).

    d(arc) = R*d(delta) + d(R)*delta + rounding of the stated arc itself.
    """
    tolerance = (
        radius_ft * angle_half_unit_rad(delta_deg)
        + STATED_LENGTH_HALF_UNIT_FT * abs(math.radians(delta_deg))
        + STATED_LENGTH_HALF_UNIT_FT
    )
    return max(tolerance, CURVE_ELEMENT_TOLERANCE_FT)


def chord_length_tolerance_ft(radius_ft: float, delta_deg: float, delta_error_rad: float) -> float:
    """Return the tolerance for a stated chord against 2R*sin(delta/2).

    d(chord) = R*|cos(delta/2)|*d(delta) + 2*|sin(delta/2)|*d(R) + rounding of the
    stated chord. ``delta_error_rad`` is the uncertainty of the delta used.
    """
    half = math.radians(delta_deg) / 2.0
    tolerance = (
        radius_ft * abs(math.cos(half)) * delta_error_rad
        + 2.0 * abs(math.sin(half)) * STATED_LENGTH_HALF_UNIT_FT
        + STATED_LENGTH_HALF_UNIT_FT
    )
    return max(tolerance, CURVE_ELEMENT_TOLERANCE_FT)


def tangent_chord_tolerance_deg(
    delta_error_rad: float, deflection_error_rad: float | None = None
) -> float:
    """Return the tolerance for tangent-to-chord deflection against delta / 2.

    The deflection differences two stated bearings (``deflection_error_rad``,
    default half a second each); half the delta carries half the delta's
    uncertainty.
    """
    if deflection_error_rad is None:
        deflection_error_rad = 2.0 * STATED_ANGLE_HALF_UNIT_RAD
    tolerance = math.degrees(deflection_error_rad) + math.degrees(delta_error_rad) / 2
    return min(max(tolerance, TANGENT_CHORD_TOLERANCE_DEG), TANGENT_CHORD_TOLERANCE_CAP_DEG)


def deflection_chord_tolerance_ft(
    radius_ft: float, deflection_deg: float, deflection_error_rad: float | None = None
) -> float:
    """Return the tolerance for a stated chord against 2R*sin(deflection).

    The deflection differences two stated bearings, so the equivalent delta
    (twice the deflection) carries twice their combined rounding.
    """
    if deflection_error_rad is None:
        deflection_error_rad = 2.0 * STATED_ANGLE_HALF_UNIT_RAD
    return chord_length_tolerance_ft(radius_ft, 2.0 * deflection_deg, 2.0 * deflection_error_rad)


def tangent_chord_deflection(tangent_az: float, chord_az: float, curve_dir: str) -> float:
    """Return the chord's deflection from the tangent, positive toward the curve.

    The chord of a right curve turns clockwise from the tangent by half the
    delta, and a left curve's counterclockwise. A zero or negative result means
    the stated bearings put the chord on the wrong side of the tangent.
    """
    deflection = (chord_az - tangent_az + 180.0) % 360.0 - 180.0
    return -deflection if curve_dir == "left" else deflection


def calculate_curve_properties(
    radius_ft: float,
    *,
    delta_deg: float | None = None,
    arc_length_ft: float | None = None,
) -> dict[str, float]:
    """Calculate curve properties from radius and either delta or arc length.

    Given R and delta:
        L = R * delta (radians)
        chord = 2R * sin(delta/2)

    Given R and L:
        delta = L / R (radians)
        chord = 2R * sin(delta/2)

    Args:
        radius_ft: Radius in feet (must be > 0)
        delta_deg: Central angle in degrees (optional, 0-360)
        arc_length_ft: Arc length in feet (optional)

    Returns:
        Dict with keys: radius_ft, delta_deg, delta_rad, arc_length_ft,
        chord_length_ft, tangent_length_ft, external_distance_ft,
        middle_ordinate_ft

    Raises:
        ValueError: If radius <= 0, delta > 360, or neither delta/arc provided
    """
    if radius_ft <= 0:
        raise ValueError(f"Radius must be positive, got {radius_ft}")

    delta_rad = 0.0

    if delta_deg is not None:
        if not (0 <= delta_deg <= 360):
            raise ValueError(f"Delta angle must be 0-360 degrees, got {delta_deg}")

        delta_rad = math.radians(delta_deg)
        arc = radius_ft * delta_rad
        chord = 2 * radius_ft * math.sin(delta_rad / 2)
    elif arc_length_ft is not None:
        if arc_length_ft < 0:
            raise ValueError(f"Arc length must be non-negative, got {arc_length_ft}")

        delta_rad = arc_length_ft / radius_ft
        delta_deg = math.degrees(delta_rad)

        if delta_deg > 360:
            raise ValueError(
                f"Computed delta angle {delta_deg:.2f}\u00b0 exceeds 360\u00b0 "
                f"(arc={arc_length_ft}, radius={radius_ft})"
            )

        arc = arc_length_ft
        chord = 2 * radius_ft * math.sin(delta_rad / 2)
    else:
        raise ValueError("Must provide either delta_deg or arc_length_ft")

    cos_half = math.cos(delta_rad / 2)
    if abs(cos_half) < 1e-10:
        tangent_length_ft = float("inf")
        external_distance_ft = float("inf")
    else:
        tangent_length_ft = radius_ft * math.tan(delta_rad / 2)
        external_distance_ft = radius_ft * (1.0 / cos_half - 1.0)
    middle_ordinate_ft = radius_ft * (1.0 - math.cos(delta_rad / 2))

    return {
        "radius_ft": radius_ft,
        "delta_deg": delta_deg,
        "delta_rad": delta_rad,
        "arc_length_ft": arc,
        "chord_length_ft": chord,
        "tangent_length_ft": tangent_length_ft,
        "external_distance_ft": external_distance_ft,
        "middle_ordinate_ft": middle_ordinate_ft,
    }


def calculate_chord_bearing(
    tangent_azimuth: float,
    delta_deg: float,
    curve_dir: str,
) -> float:
    """Calculate chord bearing from tangent bearing and curve properties.

    The chord bearing is the tangent bearing rotated by +/-(delta/2) toward
    the curve.

    Args:
        tangent_azimuth: Azimuth of tangent at PC (degrees)
        delta_deg: Central angle (degrees)
        curve_dir: "left" or "right"

    Returns:
        Chord bearing azimuth (degrees)
    """
    half_delta = delta_deg / 2.0

    chord_azimuth = (
        tangent_azimuth - half_delta if curve_dir == "left" else tangent_azimuth + half_delta
    )

    return chord_azimuth % 360.0


def compute_curve_endpoint(
    start_point: Point,
    start_azimuth: float,
    radius_ft: float,
    delta_deg: float,
    curve_dir: str,
) -> Point:
    """Compute the endpoint of a curve given start point and curve parameters.

    This is an approximation using the chord. For precise work, use more
    sophisticated curve traversal methods.

    Args:
        start_point: Starting point
        start_azimuth: Tangent azimuth at start (degrees)
        radius_ft: Curve radius (feet, must be > 0)
        delta_deg: Central angle (degrees, 0-360)
        curve_dir: "left" or "right"

    Returns:
        Endpoint of curve

    Raises:
        ValueError: If radius <= 0 or delta out of range
    """
    if radius_ft <= 0:
        raise ValueError(f"Radius must be positive, got {radius_ft}")

    curve_props = calculate_curve_properties(radius_ft, delta_deg=delta_deg)
    chord_length = curve_props["chord_length_ft"]
    if chord_length is None:
        raise ValueError("Curve chord length could not be calculated.")

    chord_azimuth = calculate_chord_bearing(start_azimuth, delta_deg, curve_dir)
    dx, dy = calculate_deltas(chord_azimuth, chord_length)

    return Point(x=start_point.x + dx, y=start_point.y + dy)


def calculate_missing_curve_elements(
    *,
    radius_ft: float | None = None,
    delta_deg: float | None = None,
    arc_length_ft: float | None = None,
    chord_length_ft: float | None = None,
    degree_of_curvature: float | None = None,
) -> dict[str, float]:
    """Calculate missing curve elements from provided values.

    Given at least 2 of: radius, delta, arc length, chord length,
    degree of curvature -- compute the missing elements.

    Args:
        radius_ft: Curve radius in feet
        delta_deg: Central angle in degrees
        arc_length_ft: Arc length in feet
        chord_length_ft: Chord length in feet
        degree_of_curvature: Degree of curvature (central angle for 100-ft arc)

    Returns:
        Dict with all curve elements: radius_ft, delta_deg,
        arc_length_ft, chord_length_ft, tangent_length_ft,
        external_distance_ft, middle_ordinate_ft

    Raises:
        ValueError: If fewer than 2 elements provided
    """
    # Convert degree of curvature to radius if provided
    if degree_of_curvature is not None and radius_ft is None:
        from .azimuth import degree_of_curvature_to_radius

        radius_ft = degree_of_curvature_to_radius(degree_of_curvature)

    provided = sum(
        1 for v in [radius_ft, delta_deg, arc_length_ft, chord_length_ft] if v is not None
    )
    if provided < 2:
        raise ValueError(f"Need at least two curve elements, got {provided}")

    if delta_deg is not None and delta_deg == 0:
        raise ValueError("Delta angle must be non-zero for curve element calculation")

    if radius_ft is not None and delta_deg is not None:
        pass
    elif radius_ft is not None and arc_length_ft is not None:
        delta_deg = math.degrees(arc_length_ft / radius_ft)
    elif radius_ft is not None and chord_length_ft is not None:
        ratio = chord_length_ft / (2 * radius_ft)
        if abs(ratio) > 1:
            raise ValueError(f"Chord ({chord_length_ft} ft) exceeds diameter ({2 * radius_ft} ft)")
        half_delta = math.asin(ratio)
        delta_deg = math.degrees(2 * half_delta)
    elif arc_length_ft is not None and delta_deg is not None:
        delta_rad = math.radians(delta_deg)
        radius_ft = arc_length_ft / delta_rad
    elif chord_length_ft is not None and delta_deg is not None:
        delta_rad = math.radians(delta_deg)
        radius_ft = chord_length_ft / (2 * math.sin(delta_rad / 2))
    elif arc_length_ft is not None and chord_length_ft is not None:
        if arc_length_ft <= 0:
            raise ValueError(f"Arc length must be positive, got {arc_length_ft}")
        if chord_length_ft < 0:
            raise ValueError(f"Chord must be non-negative, got {chord_length_ft}")
        if chord_length_ft >= arc_length_ft:
            raise ValueError(
                f"Chord ({chord_length_ft} ft) must be less than arc ({arc_length_ft} ft)"
            )
        # C/L = sin(theta/2)/(theta/2), monotone over one full circle.
        # Bisection also handles major arcs where a small-angle estimate fails.
        lower, upper = 0.0, math.pi
        ratio = chord_length_ft / arc_length_ft
        for _ in range(80):
            half_delta = (lower + upper) / 2.0
            if math.sin(half_delta) / half_delta > ratio:
                lower = half_delta
            else:
                upper = half_delta
        delta_rad = lower + upper
        delta_deg = math.degrees(delta_rad)
        radius_ft = arc_length_ft / delta_rad

    # Compute all elements from radius and delta
    delta_rad = math.radians(delta_deg)  # type: ignore[arg-type]
    if arc_length_ft is None:
        arc_length_ft = radius_ft * delta_rad  # type: ignore[operator]
    if chord_length_ft is None:
        chord_length_ft = 2 * radius_ft * math.sin(delta_rad / 2)  # type: ignore[operator]
    cos_half = math.cos(delta_rad / 2)
    if abs(cos_half) < 1e-10:
        tangent_length_ft = float("inf")
        external_distance_ft = float("inf")
    else:
        tangent_length_ft = radius_ft * math.tan(delta_rad / 2)  # type: ignore[operator]
        external_distance_ft = radius_ft * (1.0 / cos_half - 1.0)  # type: ignore[operator]
    middle_ordinate_ft = radius_ft * (1.0 - math.cos(delta_rad / 2))  # type: ignore[operator]

    return {
        "radius_ft": radius_ft,  # type: ignore[dict-item]
        "delta_deg": delta_deg,  # type: ignore[dict-item]
        "arc_length_ft": arc_length_ft,
        "chord_length_ft": chord_length_ft,
        "tangent_length_ft": tangent_length_ft,
        "external_distance_ft": external_distance_ft,
        "middle_ordinate_ft": middle_ordinate_ft,
    }
