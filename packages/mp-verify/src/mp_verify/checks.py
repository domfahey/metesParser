"""Individual verification checks for metes and bounds traverses.

Each check is a module-level function returning warnings or pass/fail results.
"""

from __future__ import annotations

import math
import statistics
from typing import Literal

from mp_models import CheckResult, DeedCall, Point

from .topology import check_curved_boundary_intersections


def check_boundary_intersections(calls: list[DeedCall], coordinates: list[Point]) -> list[str]:
    """Check straight and circular boundaries without substituting chords for arcs."""
    return check_straight_boundary_intersections(
        calls, coordinates
    ) + check_curved_boundary_intersections(calls, coordinates)


def evaluate_interior_angles(calls: list[DeedCall]) -> CheckResult:
    """Report whether the straight-polygon angle test actually ran."""
    missing = [str(call.course) for call in calls if not call.is_complete_bearing()]
    if missing:
        return CheckResult(
            name="interior_angles",
            status="blocked",
            reason="missing_bearings",
            detail=f"Required bearings missing for courses {', '.join(missing)}",
        )
    if any(call.is_curve() for call in calls):
        return CheckResult(
            name="interior_angles",
            status="not_applicable",
            reason="curved_boundary",
            detail="Straight-polygon angle sum does not apply to curved boundaries",
        )
    if len(calls) < 3:
        return CheckResult(
            name="interior_angles",
            status="blocked",
            reason="insufficient_courses",
            detail="At least three straight courses are required for an angle sum",
        )
    actual_sum = sum(
        (
            (calls[(i + 1) % len(calls)].bearing_azimuth_deg_from_north or 0)
            - (call.bearing_azimuth_deg_from_north or 0)
            + 180
        )
        % 360
        - 180
        for i, call in enumerate(calls)
    )
    passed = abs(abs(actual_sum) - 360) < 5
    return CheckResult(
        name="interior_angles",
        status="passed" if passed else "failed",
        reason="angle_sum_within_tolerance" if passed else "angle_sum_mismatch",
        detail=f"Signed exterior angle sum: {actual_sum:.4f} degrees; expected +/-360 within 5 degrees",
        inputs={"signed_angle_sum_deg": actual_sum, "tolerance_deg": 5.0},
    )


def build_verification_checks(
    calls: list[DeedCall],
    *,
    closure_passed: bool,
    misclosure: float,
    tolerance: float,
    curve_consistency_passed: bool,
    parallel_warnings: list[str],
    intersection_warnings: list[str],
    reversal_warnings: list[str],
    distance_warnings: list[str],
    stated_area_sq_ft: float,
    area_sq_ft: float,
    area_available: bool,
    double_entry_performed: bool,
    discrepancies: list[str],
) -> list[CheckResult]:
    """Build auditable engine outcomes without turning unavailable checks into passes."""
    incomplete = any(not call.is_complete_bearing() for call in calls)
    missing = incomplete or not calls
    curves = [call for call in calls if call.is_curve()]

    def outcome(
        name: str,
        issues: list[str],
        *,
        applicable: bool = True,
        blocked: bool = False,
        detail: str,
        inputs: dict[str, float | str | bool] | None = None,
    ) -> CheckResult:
        status: Literal["passed", "failed", "not_applicable", "blocked"] = (
            "failed"
            if issues
            else "blocked"
            if blocked
            else "passed"
            if applicable
            else "not_applicable"
        )
        return CheckResult(
            name=name,
            status=status,
            reason=(
                "issues_detected"
                if issues
                else "missing_required_inputs"
                if blocked
                else "check_passed"
                if applicable
                else "no_applicable_inputs"
            ),
            detail="; ".join(issues) if issues else detail,
            inputs=inputs or {},
        )

    curve_incomplete = any(
        call.curve_dir is None
        or call.radius_ft is None
        or call.radius_ft <= 0
        or not ((call.delta_deg or 0) > 0 or (call.arc_length_ft or 0) > 0)
        for call in curves
    )
    redundant_curves = [
        call
        for call in curves
        if (call.delta_deg is not None and call.arc_length_ft is not None)
        or call.chord_length_ft is not None
    ]
    insufficient_topology = not curves and len(calls) < 3
    continuing = [
        i
        for i, call in enumerate(calls)
        if call.along and ("continuing" in call.along.lower() or "same line" in call.along.lower())
    ]
    # A continuation on course 0 names a line that cannot be identified: blocked, not skipped.
    orphan_continuation = 0 in continuing
    parallel_blocked = orphan_continuation or any(
        not calls[i].is_complete_bearing() or not calls[i - 1].is_complete_bearing()
        for i in continuing
        if i > 0
    )
    straight_pairs = [
        (first, second)
        for first, second in zip(calls, calls[1:], strict=False)
        if not first.is_curve() and not second.is_curve()
    ]
    reversals_blocked = any(
        not first.is_complete_bearing() or not second.is_complete_bearing()
        for first, second in straight_pairs
    )
    area_issues = []
    if stated_area_sq_ft > 0 and area_available and not missing:
        if abs(area_sq_ft - stated_area_sq_ft) / stated_area_sq_ft > 0.05:
            area_issues.append(
                f"Computed area differs from stated area by more than 5% ({area_sq_ft:.2f} vs {stated_area_sq_ft:.2f} sq ft)"
            )
    unavailable_intersections = any("unavailable" in issue for issue in intersection_warnings)
    intersection_failures = [issue for issue in intersection_warnings if "unavailable" not in issue]
    checks = [
        CheckResult(
            name="traverse_closure",
            status="blocked" if missing else "passed" if closure_passed else "failed",
            reason="missing_bearings"
            if missing
            else "within_tolerance"
            if closure_passed
            else "misclosure_exceeds_tolerance",
            detail=(
                "Traverse closure requires a bearing for every boundary course"
                if missing
                else f"misclosure: {misclosure:.4f} ft; tolerance: {tolerance} ft"
            ),
            inputs={"misclosure_total_ft": misclosure, "tolerance_ft": tolerance},
        ),
        evaluate_interior_angles(calls),
        outcome(
            "curve_consistency",
            [] if curve_consistency_passed else ["Curve math inconsistency detected"],
            applicable=bool(curves) and len(redundant_curves) == len(curves),
            blocked=curve_incomplete,
            detail=(
                "Curve geometry requires direction, positive radius, and positive delta or arc length"
                if curve_incomplete
                else "No curved courses"
                if not curves
                else "Some curves lack a redundant measure for an independent consistency check"
                if len(redundant_curves) != len(curves)
                else "All supplied redundant curve elements are consistent"
            ),
        ),
        outcome(
            "parallelism",
            parallel_warnings,
            applicable=bool(continuing),
            blocked=parallel_blocked,
            detail=(
                "Continuing-line check requires both adjacent bearings"
                if parallel_blocked
                else "Continuing lines checked"
                if continuing
                else "No continuing-line constraints"
            ),
        ),
        outcome(
            "boundary_intersections",
            ["Straight-segment and circular-arc checks: " + "; ".join(intersection_failures)]
            if intersection_failures
            else [],
            blocked=missing or unavailable_intersections or insufficient_topology,
            detail=(
                "Boundary topology requires complete bearings"
                if missing
                else "At least three straight courses are required for boundary topology"
                if insufficient_topology
                else "; ".join(intersection_warnings)
                if unavailable_intersections
                else "Straight-segment and circular-arc checks found no intersections"
            ),
        ),
        outcome(
            "area_reasonableness",
            area_issues,
            applicable=stated_area_sq_ft > 0,
            blocked=stated_area_sq_ft > 0 and (missing or not area_available),
            detail="Area comparison requires complete boundary and exception geometry"
            if stated_area_sq_ft > 0 and (missing or not area_available)
            else "Computed area within 5% of stated area"
            if stated_area_sq_ft > 0
            else "No stated area to compare",
            inputs={"area_available": area_available},
        ),
        outcome(
            "double_entry",
            discrepancies,
            applicable=double_entry_performed,
            detail="Independent entries match"
            if double_entry_performed
            else "No independent second entry supplied",
        ),
        outcome(
            "bearing_reversals",
            reversal_warnings,
            applicable=bool(straight_pairs),
            blocked=reversals_blocked,
            detail="Reversal check requires complete adjacent bearings"
            if reversals_blocked
            else "Adjacent straight courses checked"
            if straight_pairs
            else "No adjacent straight-course pairs",
        ),
        outcome(
            "distance_reasonableness",
            distance_warnings,
            blocked=not calls,
            detail="Boundary distances checked",
        ),
    ]
    if orphan_continuation:
        checks = [
            check.model_copy(
                update={
                    "reason": "continuation_without_predecessor",
                    "detail": "Continuing-line check has no predecessor course to continue",
                }
            )
            if check.name == "parallelism" and check.status == "blocked"
            else check
            for check in checks
        ]
    return checks


def block_curve_consistency(
    checks: list[CheckResult],
    blocks: list[tuple[str, str]],
) -> list[CheckResult]:
    """Downgrade curve_consistency to blocked for every applicable (reason, detail) block.

    A failed curve check stays failed: a detected inconsistency is stronger than a
    missing input. Otherwise all supplied reasons and details are combined, so no
    block silently overwrites another.
    """
    if not blocks:
        return checks
    return [
        CheckResult(
            name="curve_consistency",
            status="blocked",
            reason=",".join(reason for reason, _ in blocks),
            detail="; ".join(detail for _, detail in blocks),
        )
        if check.name == "curve_consistency" and check.status != "failed"
        else check
        for check in checks
    ]


def check_interior_angles(calls: list[DeedCall], coordinates: list[Point]) -> bool:
    """Check if interior angles sum correctly: (n-2) * 180 degrees.

    This check only applies to all-straight polygons (no curves).

    Note: This is a simplified check that verifies the sum of signed exterior
    angles equals +/-360 degrees, which is mathematically equivalent to checking
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

        # Signed turns retain concave corners and either traversal orientation.
        deflection = (az2 - az1 + 180.0) % 360.0 - 180.0

        deflection_angles.append(deflection)

    actual_sum = sum(deflection_angles)

    return abs(abs(actual_sum) - 360.0) < 5.0


def check_straight_boundary_intersections(
    calls: list[DeedCall], coordinates: list[Point]
) -> list[str]:
    """Detect crossings, overlaps, and nonadjacent touches between straight edges.

    Arc intersections are not evaluated: curve endpoint chords are not arc
    geometry. Incomplete traverses cannot reliably map calls to coordinates.
    The 1e-7 ft tolerance absorbs floating-point noise, not survey misclosure.
    """
    if len(coordinates) != len(calls) + 1:
        return []

    tolerance_ft = 1e-7

    def side(a: Point, b: Point, p: Point) -> int:
        cross = (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x)
        tolerance = tolerance_ft * math.hypot(b.x - a.x, b.y - a.y)
        return 1 if cross > tolerance else -1 if cross < -tolerance else 0

    def on_segment(a: Point, b: Point, p: Point) -> bool:
        return (
            side(a, b, p) == 0
            and min(a.x, b.x) - tolerance_ft <= p.x <= max(a.x, b.x) + tolerance_ft
            and min(a.y, b.y) - tolerance_ft <= p.y <= max(a.y, b.y) + tolerance_ft
        )

    warnings: list[str] = []
    closed = (
        math.hypot(coordinates[-1].x - coordinates[0].x, coordinates[-1].y - coordinates[0].y)
        < 0.01
    )
    for i, first in enumerate(calls):
        if first.is_curve():
            continue
        a, b = coordinates[i], coordinates[i + 1]
        for j in range(i + 1, len(calls)):
            second = calls[j]
            if second.is_curve() or j == i + 1 or (closed and i == 0 and j == len(calls) - 1):
                continue
            c, d = coordinates[j], coordinates[j + 1]
            proper_crossing = (
                side(a, b, c) * side(a, b, d) < 0 and side(c, d, a) * side(c, d, b) < 0
            )
            if proper_crossing or any(
                (on_segment(a, b, c), on_segment(a, b, d), on_segment(c, d, a), on_segment(c, d, b))
            ):
                warnings.append(
                    f"Courses {first.course}-{second.course}: straight boundary self-intersection "
                    "(crossing, overlap, or nonadjacent touch)"
                )
    return warnings


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
                # No delta or arc: a radius and chord alone leave the arc ambiguous,
                # so only the chord's own feasibility can be checked.
                if call.chord_length_ft is not None and call.chord_length_ft > 2 * call.radius_ft:
                    warnings.append(
                        f"Course {call.course}: chord length exceeds twice the radius "
                        f"(chord: {call.chord_length_ft:.2f}, radius: {call.radius_ft:.2f})"
                    )
                    return False, warnings
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

    This pattern often indicates a quadrant transcription error in straight
    courses. Curve bearings may describe tangents or chords; comparing them
    directly does not establish a reversal, so pairs involving arcs are skipped.

    Args:
        calls: List of DeedCall objects.

    Returns:
        List of warning messages.
    """
    warnings: list[str] = []

    for i in range(len(calls) - 1):
        c1, c2 = calls[i], calls[i + 1]
        if c1.is_curve() or c2.is_curve():
            continue
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

        az1 = c1.bearing_azimuth_deg_from_north
        az2 = c2.bearing_azimuth_deg_from_north
        if az1 is None or az2 is None:
            if az1 != az2:
                discrepancies.append(f"Course {i}: Azimuth presence mismatch")
        elif abs((az1 - az2 + 180.0) % 360.0 - 180.0) > 0.0001:
            discrepancies.append(f"Course {i}: Azimuth mismatch - {az1:.6f} vs {az2:.6f}")

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
