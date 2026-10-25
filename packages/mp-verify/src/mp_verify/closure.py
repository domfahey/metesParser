"""Core traverse computation and closure verification.

Implements the 8 verification guardrails:
A) Traverse closure
B) Interior angle validation
C) Parallelism checks
D) Curve consistency
E) Area reasonableness
F) Double-entry validation
G) Bearing reversal detection
H) Distance reasonableness

Quality and confidence scoring:
- Per-call quality rating (high/medium/low)
- Overall confidence score (0.0-1.0)
"""

from __future__ import annotations

import math

from mp_bearing import calculate_deltas, compute_curve_endpoint
from mp_models import (
    AuditContext,
    CheckResult,
    ClosureResult,
    DeedCall,
    Point,
    VerificationAudit,
)

from .checks import (
    check_bearing_reversals,
    check_curve_consistency,
    check_distance_reasonableness,
    check_interior_angles,
    check_parallelism,
    compare_double_entry,
)
from .confidence import calculate_confidence_score, score_call_quality

CLOSURE_TOLERANCE_FT = 0.01


def compute_traverse(
    calls: list[DeedCall],
    start_point: Point | None = None,
) -> list[Point]:
    """Compute the traverse path from calls.

    Args:
        calls: List of DeedCall objects.
        start_point: Starting point (default: origin).

    Returns:
        List of Point objects representing vertices.
    """
    if start_point is None:
        start_point = Point(x=0, y=0)
    points = [start_point]
    current = start_point

    for call in calls:
        if call.bearing_azimuth_deg_from_north is None:
            continue

        if call.is_curve():
            next_point: Point | None = None

            if call.radius_ft is not None and call.curve_dir is not None:
                delta_deg = call.delta_deg
                if delta_deg is None and call.arc_length_ft is not None and call.radius_ft > 0.0:
                    delta_deg = math.degrees(call.arc_length_ft / call.radius_ft)

                if delta_deg is not None and abs(delta_deg) > 1e-9:
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
        current = next_point

    return points


def calculate_area(points: list[Point], *, calls: list[DeedCall] | None = None) -> float:
    """Calculate polygon area, including circular segments when calls are supplied.

    Args:
        points: List of Point objects forming a polygon.
        calls: Optional traverse calls for signed circular-segment corrections.

    Returns:
        Area in square feet.

    Raises:
        ValueError: If fewer than 3 points provided without a curved boundary.
    """
    if len(points) < 2:
        raise ValueError(f"Cannot calculate area with {len(points)} points (need at least 3)")

    area = 0.0
    n = len(points)

    for i in range(n):
        j = (i + 1) % n
        area += points[i].x * points[j].y
        area -= points[j].x * points[i].y

    area /= 2.0
    curved_area = 0.0
    for call in calls or []:
        if call.bearing_azimuth_deg_from_north is None or not call.is_curve():
            continue
        if call.radius_ft is None or call.curve_dir is None:
            continue
        delta = call.delta_deg
        if delta is None and call.arc_length_ft is not None and call.radius_ft > 0:
            delta = math.degrees(call.arc_length_ft / call.radius_ft)
        if delta is None or abs(delta) <= 1e-9:
            continue
        theta = math.radians(delta)
        segment = call.radius_ft**2 * (theta - math.sin(theta)) / 2.0
        # Shoelace uses positive counterclockwise area; left arcs add area.
        curved_area += segment if call.curve_dir == "left" else -segment
    if len(points) < 3 and curved_area == 0.0:
        raise ValueError(f"Cannot calculate area with {len(points)} points (need at least 3)")
    return abs(area + curved_area)


def calculate_perimeter(calls: list[DeedCall]) -> float:
    """Calculate total perimeter from calls.

    Args:
        calls: List of DeedCall objects.

    Returns:
        Perimeter in feet.
    """
    perimeter = 0.0
    for call in calls:
        if call.is_curve() and call.arc_length_ft is not None and call.arc_length_ft > 0.0:
            perimeter += call.arc_length_ft
        else:
            perimeter += call.distance_ft
    return perimeter


def verify_closure(
    calls: list[DeedCall],
    *,
    stated_area_sq_ft: float = 0.0,
    closure_tolerance_ft: float | None = None,
    double_entry_calls: list[DeedCall] | None = None,
    audit_context: AuditContext | None = None,
) -> ClosureResult:
    """Verify traverse closure and perform all validation checks.

    Args:
        calls: List of DeedCall objects.
        stated_area_sq_ft: Stated area from deed (optional, for comparison).
        closure_tolerance_ft: Custom closure tolerance (default: 0.01 ft).
        double_entry_calls: Optional independently-entered call set for guardrail F.
        audit_context: Optional audit context for recording check results.

    Returns:
        ClosureResult with all checks, computed values, and confidence_score.
    """
    tolerance = closure_tolerance_ft if closure_tolerance_ft is not None else CLOSURE_TOLERANCE_FT

    main_calls = [c for c in calls if not c.is_exception and not c.is_tie_in]
    exception_calls = [c for c in calls if c.is_exception]

    points = compute_traverse(main_calls)

    # Check for degenerate traverse: no calls contributed azimuths
    computable_calls = sum(1 for c in main_calls if c.bearing_azimuth_deg_from_north is not None)
    has_computable_traverse = computable_calls > 0

    misclosure_x = points[-1].x - points[0].x
    misclosure_y = points[-1].y - points[0].y
    misclosure = math.sqrt(misclosure_x**2 + misclosure_y**2)

    warnings: list[str] = []

    if not has_computable_traverse:
        warnings.append(
            "No computable traverse \u2014 all calls lack bearings (cardinal-only or empty)"
        )

    try:
        main_area_sq_ft = calculate_area(points, calls=main_calls)

        exception_area_sq_ft = 0.0
        if exception_calls:
            warnings.append(
                f"Found {len(exception_calls)} exception calls - "
                "calculating exception area to subtract"
            )
            try:
                exception_points = compute_traverse(exception_calls)
                exception_area_sq_ft = calculate_area(exception_points, calls=exception_calls)
            except ValueError as e:
                warnings.append(f"Cannot calculate exception area: {e}")

        area_sq_ft = main_area_sq_ft - exception_area_sq_ft
        area_acres = area_sq_ft / 43560.0
    except ValueError as e:
        area_sq_ft = 0.0
        area_acres = 0.0
        warnings.append(f"Cannot calculate area: {e}")

    perimeter = calculate_perimeter(main_calls)

    closure_passed = has_computable_traverse and misclosure < tolerance

    # Warn when closure only passes because of a relaxed tolerance
    if closure_passed and tolerance > CLOSURE_TOLERANCE_FT and misclosure >= CLOSURE_TOLERANCE_FT:
        warnings.append(
            f"Closure passes with relaxed tolerance "
            f"({misclosure:.4f} ft misclosure vs {tolerance:.4f} ft threshold)"
        )

    angle_check_passed = check_interior_angles(main_calls, points)
    curve_consistency_passed_val, curve_warnings = check_curve_consistency(main_calls)
    warnings.extend(curve_warnings)

    parallel_warnings = check_parallelism(main_calls)
    warnings.extend(parallel_warnings)

    reversal_warnings = check_bearing_reversals(main_calls)
    warnings.extend(reversal_warnings)

    distance_warnings = check_distance_reasonableness(main_calls)
    warnings.extend(distance_warnings)

    meander_calls = [c for c in main_calls if c.is_meander]
    if meander_calls:
        course_nums = ", ".join(str(c.course) for c in meander_calls)
        warnings.append(
            f"{len(meander_calls)} meander/water boundary call(s) "
            f"(courses {course_nums}) may affect closure accuracy"
        )

    indefinite_calls = [c for c in main_calls if c.is_indefinite]
    if indefinite_calls:
        course_nums = ", ".join(str(c.course) for c in indefinite_calls)
        warnings.append(
            f"{len(indefinite_calls)} indefinite call(s) "
            f"(courses {course_nums}) have vague direction without precise bearing"
        )

    if double_entry_calls is not None:
        discrepancies = compare_double_entry(calls, double_entry_calls)
        warnings.extend(f"Double-entry discrepancy: {discrepancy}" for discrepancy in discrepancies)

    if stated_area_sq_ft > 0:
        area_diff_pct = abs(area_sq_ft - stated_area_sq_ft) / stated_area_sq_ft * 100
        if area_diff_pct > 5.0:
            warnings.append(
                f"Computed area differs from stated by {area_diff_pct:.1f}% "
                f"(computed: {area_sq_ft:.1f} sq ft, stated: {stated_area_sq_ft:.1f} sq ft)"
            )

    incomplete = [c for c in main_calls if not c.is_complete_bearing()]
    if incomplete:
        warnings.append(
            f"{len(incomplete)} call(s) have incomplete bearings (cardinal-only or meanders)"
        )

    if exception_calls:
        exception_incomplete = [c for c in exception_calls if not c.is_complete_bearing()]
        if exception_incomplete:
            warnings.append(
                f"Exception tract has {len(exception_incomplete)} incomplete bearing(s)"
            )

    closure_result = ClosureResult(
        misclosure_x_ft=misclosure_x,
        misclosure_y_ft=misclosure_y,
        misclosure_ft=misclosure,
        area_sq_ft=area_sq_ft,
        area_acres=area_acres,
        perimeter_ft=perimeter,
        closure_passed=closure_passed,
        angle_check_passed=angle_check_passed,
        curve_consistency_passed=curve_consistency_passed_val,
        warnings=warnings,
        points=points,
        precision_ratio=misclosure / perimeter if perimeter else None,
    )

    confidence = calculate_confidence_score(closure_result, calls)
    closure_result = closure_result.model_copy(update={"confidence_score": confidence})

    if audit_context is not None:
        check_results = [
            CheckResult(
                name="traverse_closure",
                passed=closure_passed,
                detail=(
                    f"misclosure: {misclosure:.4f} ft "
                    f"{'<' if closure_passed else '>='} {tolerance} ft tolerance"
                ),
                inputs={
                    "misclosure_x_ft": misclosure_x,
                    "misclosure_y_ft": misclosure_y,
                    "misclosure_total_ft": misclosure,
                    "tolerance_ft": tolerance,
                },
            ),
            CheckResult(
                name="interior_angles",
                passed=angle_check_passed,
                detail=(
                    "all-straight polygon angles sum correctly"
                    if angle_check_passed
                    else "skipped (curves present or incomplete bearings)"
                ),
                inputs={},
            ),
            CheckResult(
                name="curve_consistency",
                passed=curve_consistency_passed_val,
                detail=(
                    "all curves L \u2248 R*\u0394 within tolerance"
                    if curve_consistency_passed_val
                    else "curve math inconsistency detected"
                ),
                inputs={},
            ),
            CheckResult(
                name="bearing_reversals",
                passed=(len(reversal_warnings) == 0),
                detail=(
                    f"{len(reversal_warnings)} reversal(s) detected"
                    if reversal_warnings
                    else "no bearing reversals"
                ),
                inputs={},
            ),
            CheckResult(
                name="distance_reasonableness",
                passed=(len(distance_warnings) == 0),
                detail=(
                    f"{len(distance_warnings)} issue(s) detected"
                    if distance_warnings
                    else "all distances reasonable"
                ),
                inputs={},
            ),
        ]

        precision_ratio_str: str
        if perimeter and (misclosure / perimeter) > 1e-10:
            precision_ratio_str = f"1:{round(1.0 / (misclosure / perimeter))}"
        else:
            precision_ratio_str = "N/A"

        audit_context.verification_audit = VerificationAudit(
            checks=check_results,
            closure_summary={
                "misclosure_ft": misclosure,
                "precision_ratio": precision_ratio_str,
                "area_sq_ft": area_sq_ft,
                "area_acres": area_acres,
                "perimeter_ft": perimeter,
                "confidence_score": confidence,
                "status": closure_result.get_closure_status(),
            },
        )

    return closure_result


def get_closure_summary(
    result: ClosureResult,
    calls: list[DeedCall] | None = None,
) -> str:
    """Generate a human-readable closure summary.

    Args:
        result: ClosureResult object.
        calls: Optional list of DeedCall objects for per-call quality breakdown.

    Returns:
        Formatted summary string.
    """
    summary = []
    summary.append("=" * 60)
    summary.append("CLOSURE VERIFICATION SUMMARY")
    summary.append("=" * 60)
    summary.append(f"Misclosure: {result.misclosure_ft:.4f} ft ({result.get_closure_status()})")
    summary.append(f"  X: {result.misclosure_x_ft:.4f} ft")
    summary.append(f"  Y: {result.misclosure_y_ft:.4f} ft")

    if result.precision_ratio is not None and result.precision_ratio > 1e-10:
        ratio_inv = round(1.0 / result.precision_ratio)
        summary.append(f"  Precision: 1:{ratio_inv:,}")

    summary.append("")
    summary.append(f"Area: {result.area_sq_ft:,.2f} sq ft ({result.area_acres:.4f} acres)")
    summary.append(f"Perimeter: {result.perimeter_ft:,.2f} ft")

    if result.confidence_score is not None:
        summary.append(f"Confidence: {result.confidence_score:.2f}")

    summary.append("")
    summary.append("Verification Checks:")
    summary.append(f"  Closure: {'PASS' if result.closure_passed else 'FAIL'}")
    summary.append(f"  Angles: {'PASS' if result.angle_check_passed else 'FAIL'}")
    summary.append(f"  Curves: {'PASS' if result.curve_consistency_passed else 'FAIL'}")
    summary.append("")

    if result.warnings:
        summary.append(f"Warnings ({len(result.warnings)}):")
        for warning in result.warnings:
            summary.append(f"  - {warning}")
    else:
        summary.append("No warnings.")

    if calls:
        quality_counts = {"high": 0, "medium": 0, "low": 0}
        for call in calls:
            q = call.quality or score_call_quality(call)
            quality_counts[q] += 1
        summary.append("")
        summary.append("Quality Breakdown:")
        for level in ("high", "medium", "low"):
            count = quality_counts[level]
            if count > 0:
                summary.append(f"  {level}: {count} call(s)")

    summary.append("")
    checkmark = "\u2713"
    status = f"FULLY VERIFIED {checkmark}" if result.is_fully_verified() else "NEEDS REVIEW"
    summary.append(f"Status: {status}")
    summary.append("=" * 60)

    return "\n".join(summary)
