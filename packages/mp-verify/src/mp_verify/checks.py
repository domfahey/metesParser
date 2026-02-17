"""Individual verification checks for metes and bounds traverses.

Each check is a module-level function returning warnings or pass/fail results.
"""

from __future__ import annotations

import math
import statistics

from mp_models import DeedCall, Point


def check_interior_angles(calls: list[DeedCall], coordinates: list[Point]) -> bool:
    """Check if interior angles sum correctly: (n-2) * 180 degrees.

    This check only applies to all-straight polygons (no curves).

    Note: This is a simplified check that verifies the sum of exterior
    angles equals 360 degrees, which is mathematically equivalent to checking
    interior angles sum to (n-2)*180 degrees.

    Args:
        calls: List of DeedCall objects.
        coordinates: List of computed traverse points (unused but part of API).

    Returns:
        True if angles sum correctly (within tolerance).
    """
    if any(not call.is_complete_bearing() or call.is_curve() for call in calls):
        return True

    n = len(calls)
    if n < 3:
        return True

    deflection_angles = []
    for i in range(n):
        current = calls[i]
        next_call = calls[(i + 1) % n]

        az1 = current.bearing_azimuth_deg_from_north or 0
        az2 = next_call.bearing_azimuth_deg_from_north or 0

        deflection = az2 - az1

        while deflection < 0:
            deflection += 360
        while deflection >= 360:
            deflection -= 360

        deflection_angles.append(deflection)

    actual_sum = sum(deflection_angles)

    return abs(actual_sum - 360.0) < 5.0


def check_parallelism(calls: list[DeedCall]) -> list[str]:
    """Check for parallel lines that should have matching bearings.

    Args:
        calls: List of DeedCall objects.

    Returns:
        List of warning messages for parallelism issues.
    """
    warnings: list[str] = []

    for i, call in enumerate(calls):
        if not call.along:
            continue

        if "continuing" in call.along.lower() or "same line" in call.along.lower():
            if (
                i > 0
                and calls[i - 1].bearing_azimuth_deg_from_north is not None
                and call.bearing_azimuth_deg_from_north is not None
            ):
                prev_az = calls[i - 1].bearing_azimuth_deg_from_north or 0
                curr_az = call.bearing_azimuth_deg_from_north or 0

                diff = abs(curr_az - prev_az) % 360.0
                diff = min(diff, 360.0 - diff)
                if not (diff < 1.0 or abs(diff - 180.0) < 1.0):
                    warnings.append(
                        f"Course {call.course}: 'continuing' line but bearing differs "
                        f"from previous ({diff:.1f}\u00b0 difference)"
                    )

    return warnings


def check_curve_consistency(calls: list[DeedCall]) -> tuple[bool, list[str]]:
    """Check curve math consistency: L ~ R*delta, chord ~ 2R*sin(delta/2).

    When delta_deg is not provided but both radius_ft and arc_length_ft
    are present, the implied delta is derived from arc/radius and used
    for consistency checks (including chord validation).

    Args:
        calls: List of DeedCall objects.

    Returns:
        Tuple of (passed, warnings).
    """
    warnings: list[str] = []

    for call in calls:
        if not call.is_curve():
            continue

        if call.radius_ft is None:
            continue

        delta_deg = call.delta_deg
        tolerance_ft = 0.1

        # Derive delta from radius + arc when delta_deg is not explicit
        if delta_deg is None:
            if call.arc_length_ft is not None and call.radius_ft > 0.0:
                implied_delta_rad = call.arc_length_ft / call.radius_ft
                # Arc cannot exceed full circle (2*pi*radius)
                if implied_delta_rad > 2 * math.pi:
                    warnings.append(f"Course {call.course}: arc length exceeds full circle")
                    return False, warnings
                delta_deg = math.degrees(implied_delta_rad)
            else:
                # No delta and insufficient data to derive one -- skip
                continue

        delta_rad = math.radians(delta_deg)
        expected_arc = call.radius_ft * delta_rad

        if call.arc_length_ft is not None:
            arc_diff = abs(call.arc_length_ft - expected_arc)
            if arc_diff > tolerance_ft:
                warnings.append(
                    f"Course {call.course}: arc length inconsistency "
                    f"(given: {call.arc_length_ft:.2f}, expected: {expected_arc:.2f})"
                )
                return False, warnings

        expected_chord = 2 * call.radius_ft * math.sin(delta_rad / 2)

        if call.chord_length_ft is not None:
            chord_diff = abs(call.chord_length_ft - expected_chord)
            if chord_diff > tolerance_ft:
                warnings.append(
                    f"Course {call.course}: chord length inconsistency "
                    f"(given: {call.chord_length_ft:.2f}, expected: {expected_chord:.2f})"
                )
                return False, warnings

    return True, warnings


def check_bearing_reversals(calls: list[DeedCall]) -> list[str]:
    """Check for adjacent courses with bearings ~180 degrees apart.

    This pattern often indicates a quadrant transcription error.

    Args:
        calls: List of DeedCall objects.

    Returns:
        List of warning messages.
    """
    warnings: list[str] = []

    for i in range(len(calls) - 1):
        c1, c2 = calls[i], calls[i + 1]
        az1 = c1.bearing_azimuth_deg_from_north
        az2 = c2.bearing_azimuth_deg_from_north
        if az1 is None or az2 is None:
            continue

        course1, course2 = c1.course, c2.course

        diff = abs(az2 - az1) % 360.0
        diff = min(diff, 360.0 - diff)

        if abs(diff - 180.0) < 5.0:
            warnings.append(
                f"Courses {course1}-{course2}: possible bearing reversal "
                f"({diff:.1f}\u00b0 apart, near 180\u00b0)"
            )

    return warnings


def check_distance_reasonableness(calls: list[DeedCall]) -> list[str]:
    """Check for suspiciously short, long, or dominant distances.

    Flags:
    - Distances < 0.5 ft (suspiciously short)
    - Distances > 10x the median (unusually long)
    - Single course > 90% of total perimeter

    Args:
        calls: List of DeedCall objects.

    Returns:
        List of warning messages.
    """
    if len(calls) < 2:
        return []

    warnings: list[str] = []
    distances = [c.distance_ft for c in calls]
    median_dist = statistics.median(distances)
    total_perimeter = sum(distances)

    for call in calls:
        dist = call.distance_ft

        if dist < 0.5:
            warnings.append(f"Course {call.course}: suspiciously short distance ({dist:.2f} ft)")

        if median_dist > 0 and dist > 10 * median_dist:
            warnings.append(
                f"Course {call.course}: unusually long distance "
                f"({dist:.1f} ft, >10x median of {median_dist:.1f} ft)"
            )

        if total_perimeter > 0 and dist / total_perimeter > 0.90:
            warnings.append(
                f"Course {call.course}: dominates perimeter "
                f"({dist / total_perimeter * 100:.0f}% of {total_perimeter:.1f} ft, >90%)"
            )

    return warnings


def check_area_reasonableness(
    computed_area: float,
    stated_area: float,
    tolerance_pct: float = 5.0,
) -> list[str]:
    """Check if computed area is reasonably close to stated area.

    Args:
        computed_area: Computed area in square feet.
        stated_area: Stated area in square feet from the deed.
        tolerance_pct: Maximum acceptable percentage difference.

    Returns:
        List of warning messages.
    """
    if stated_area <= 0:
        return []

    diff_pct = abs(computed_area - stated_area) / stated_area * 100
    if diff_pct > tolerance_pct:
        return [
            f"Computed area differs from stated by {diff_pct:.1f}% "
            f"(computed: {computed_area:.1f} sq ft, stated: {stated_area:.1f} sq ft)"
        ]
    return []


def check_double_entry(calls: list[DeedCall]) -> list[str]:
    """Check for double-entry validation issues.

    This is a placeholder that returns an empty list when no
    independent double-entry data is provided.

    Args:
        calls: List of DeedCall objects.

    Returns:
        List of warning messages (empty without comparison data).
    """
    return []


def compare_double_entry(calls1: list[DeedCall], calls2: list[DeedCall]) -> list[str]:
    """Compare two entry sets for discrepancies (double-entry validation).

    Args:
        calls1: First set of calls.
        calls2: Second set of calls.

    Returns:
        List of discrepancy messages.
    """
    discrepancies: list[str] = []

    if len(calls1) != len(calls2):
        discrepancies.append(f"Different number of calls: {len(calls1)} vs {len(calls2)}")
        return discrepancies

    def compare_optional_float(
        course_num: int,
        label: str,
        value1: float | None,
        value2: float | None,
        tolerance: float = 0.01,
    ) -> None:
        if value1 is None and value2 is None:
            return
        if value1 is None or value2 is None:
            discrepancies.append(f"Course {course_num}: {label} presence mismatch")
            return
        if abs(value1 - value2) > tolerance:
            discrepancies.append(
                f"Course {course_num}: {label} mismatch - {value1:.2f} vs {value2:.2f}"
            )

    for i, (c1, c2) in enumerate(zip(calls1, calls2, strict=False), start=1):
        if c1.bearing_quadrant != c2.bearing_quadrant:
            discrepancies.append(
                f"Course {i}: Bearing mismatch - '{c1.bearing_quadrant}' vs '{c2.bearing_quadrant}'"
            )

        if abs(c1.distance_ft - c2.distance_ft) > 0.01:
            discrepancies.append(
                f"Course {i}: Distance mismatch - {c1.distance_ft:.2f} vs {c2.distance_ft:.2f}"
            )

        curve1 = c1.is_curve()
        curve2 = c2.is_curve()
        if curve1 != curve2:
            discrepancies.append(f"Course {i}: Curve geometry presence mismatch")

        if not (curve1 or curve2):
            continue

        if c1.curve_dir != c2.curve_dir:
            discrepancies.append(f"Course {i}: Curve direction mismatch")

        compare_optional_float(i, "Radius", c1.radius_ft, c2.radius_ft)
        compare_optional_float(i, "Delta", c1.delta_deg, c2.delta_deg, tolerance=0.0001)
        compare_optional_float(i, "Arc length", c1.arc_length_ft, c2.arc_length_ft)
        compare_optional_float(i, "Chord length", c1.chord_length_ft, c2.chord_length_ft)

        if c1.chord_bearing != c2.chord_bearing:
            discrepancies.append(
                f"Course {i}: Chord bearing mismatch - '{c1.chord_bearing}' vs '{c2.chord_bearing}'"
            )

    return discrepancies
