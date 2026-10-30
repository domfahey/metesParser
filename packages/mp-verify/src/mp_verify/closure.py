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
from typing import overload

import structlog
from mp_models import (
    AuditContext,
    CheckResult,
    ClosureResult,
    DeedCall,
    Point,
    SkippedCourse,
    Tract,
    VerificationAudit,
)

from .checks import (
    block_curve_consistency,
    build_verification_checks,
    check_bearing_reversals,
    check_boundary_intersections,
    check_curve_consistency,
    check_distance_reasonableness,
    check_interior_angles,
    check_parallelism,
    chord_only_delta_detail,
    compare_double_entry,
    tangent_chord_issue,
)
from .confidence import calculate_confidence_score, score_call_quality
from .tangents import (
    curve_sweep,
    curve_tangents,
    has_determined_direction,
    is_circular_curve,
    is_spiral,
    stated_sweep,
    stated_tangent,
)
from .traverse import analyze_courses, traverse_positions

logger = structlog.get_logger(__name__)

CLOSURE_TOLERANCE_FT = 0.01


def compute_traverse(
    calls: list[DeedCall],
    start_point: Point | None = None,
) -> list[Point]:
    """Compute the traverse path from calls (vertices only)."""
    return traverse_positions(calls, start_point)[0]


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
        # Only an arc whose start is fixed (stated tangent, chord and sweep, or a
        # non-tangent curve's radial bearing) contributes a segment.
        tangentless = stated_tangent(call) is None
        if (
            not is_circular_curve(call)
            or (tangentless and curve_tangents(call) is None)
            or not call.is_curve()
        ):
            continue
        if call.radius_ft is None or call.curve_dir is None:
            continue
        delta = stated_sweep(call)
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
        elif (
            stated_tangent(call) is None
            and curve_tangents(call) is not None
            and (delta := curve_sweep(call)) is not None
            and call.radius_ft is not None
        ):
            # Tangent-less curve positioned by its chord (or a non-tangent curve by its
            # radial bearing): arc = R * delta is determined.
            perimeter += call.radius_ft * math.radians(delta)
        elif call.distance_ft is None:
            raise ValueError(f"Course {call.course}: distance not determined")
        else:
            perimeter += call.distance_ft
    return perimeter


def _calculate_exception_area(calls: list[DeedCall]) -> float:
    """Sum independently closed exception loops without mixing their winding.

    The flat call API has no tract identifiers. A return to the local origin
    ends one loop; an incomplete final loop cannot supply a net parcel area.
    """
    areas: list[float] = []
    pending: list[DeedCall] = []
    points = [Point(x=0, y=0)]
    for call in calls:
        if call.is_tie_in:
            continue
        # Exception loops are positioned exactly like main traverses: a tangent-less
        # curve fixed by chord bearing and sweep is determined, not incomplete.
        if not has_determined_direction(call):
            raise ValueError(
                f"Exception course {call.course} has an incomplete bearing; net area unavailable"
            )
        if call.is_chord_only_curve() or not is_circular_curve(call):
            raise ValueError(
                f"Exception course {call.course}: curve delta/arc not stated; net area unavailable"
            )
        vertices, positioned = traverse_positions([call], start_point=points[-1])
        if not all(positioned):
            raise ValueError(
                f"Exception course {call.course} cannot be positioned; net area unavailable"
            )
        points.extend(vertices[1:])
        pending.append(call)
        misclosure = math.hypot(points[-1].x, points[-1].y)
        if misclosure < CLOSURE_TOLERANCE_FT:
            intersections = check_boundary_intersections(pending, points)
            if intersections:
                raise ValueError(
                    f"Exception tract topology failed; net area unavailable: {intersections[0]}"
                )
            curves_passed, _ = check_curve_consistency(pending)
            if not curves_passed:
                raise ValueError(
                    f"Exception tract ending at course {call.course} has inconsistent curves; net area unavailable"
                )
            areas.append(calculate_area(points, calls=pending))
            pending = []
            points = [Point(x=0, y=0)]
    if pending:
        misclosure = math.hypot(points[-1].x, points[-1].y)
        raise ValueError(
            f"Exception tract ending at course {pending[-1].course} does not close "
            f"({misclosure:.4f} ft misclosure); net area unavailable"
        )
    return math.fsum(areas)


def verify_tract(
    calls: list[DeedCall],
    *,
    stated_area_sq_ft: float = 0.0,
    closure_tolerance_ft: float | None = None,
    audit_context: AuditContext | None = None,
    skipped_courses: list[SkippedCourse] | None = None,
) -> ClosureResult:
    """Check one independent tract using every standard verification guardrail."""
    boundary = [call.model_copy(update={"is_exception": False}) for call in calls]
    return verify_closure(
        boundary,
        stated_area_sq_ft=stated_area_sq_ft,
        closure_tolerance_ft=closure_tolerance_ft,
        audit_context=audit_context,
        skipped_courses=skipped_courses,
    )


def _merge_skips(*groups: list[SkippedCourse]) -> list[SkippedCourse]:
    """Combine skip records from every source once, preserving order."""
    merged: list[SkippedCourse] = []
    for group in groups:
        merged.extend(skip for skip in group if skip not in merged)
    return merged


def skips_for_tract(
    tract: Tract, all_tracts: list[Tract], extra_skips: list[SkippedCourse]
) -> list[SkippedCourse]:
    """Every skip that applies to one tract of a multi-tract run.

    A tract's own skips apply, as do ``extra_skips`` labelled with it. A skip tied
    to no supplied tract cannot be placed, so it applies to every tract.
    """
    tract_labels = {t.label for t in all_tracts}
    unplaced = {skip.tract_label for skip in extra_skips} - tract_labels
    return _merge_skips(
        tract.skipped_courses,
        [skip for skip in extra_skips if skip.tract_label in (tract.label, *unplaced)],
    )


def _block_skipped_closure(
    checks: list[CheckResult], skipped: list[SkippedCourse]
) -> list[CheckResult]:
    """Block traverse closure: the extracted calls omit courses the deed states."""
    detail = "Traverse closure not determined: extraction skipped course(s) " + ", ".join(
        str(skip.course) for skip in skipped
    )
    return [
        CheckResult(
            name="traverse_closure",
            status="blocked",
            reason="skipped_courses",
            detail=detail,
            inputs={"skipped_course_count": len(skipped)},
        )
        if check.name == "traverse_closure"
        else check
        for check in checks
    ]


@overload
def verify_closure(
    calls: list[DeedCall],
    *,
    tracts: None = None,
    stated_area_sq_ft: float = ...,
    closure_tolerance_ft: float | None = ...,
    double_entry_calls: list[DeedCall] | None = ...,
    audit_context: AuditContext | None = ...,
    skipped_courses: list[SkippedCourse] | None = ...,
) -> ClosureResult: ...


@overload
def verify_closure(
    calls: list[DeedCall],
    *,
    tracts: list[Tract],
    stated_area_sq_ft: float = ...,
    closure_tolerance_ft: float | None = ...,
    double_entry_calls: list[DeedCall] | None = ...,
    audit_context: AuditContext | None = ...,
    skipped_courses: list[SkippedCourse] | None = ...,
) -> list[ClosureResult]: ...


def verify_closure(
    calls: list[DeedCall],
    *,
    tracts: list[Tract] | None = None,
    stated_area_sq_ft: float = 0.0,
    closure_tolerance_ft: float | None = None,
    double_entry_calls: list[DeedCall] | None = None,
    audit_context: AuditContext | None = None,
    skipped_courses: list[SkippedCourse] | None = None,
) -> ClosureResult | list[ClosureResult]:
    """Verify traverse closure and perform all validation checks.

    Args:
        calls: List of DeedCall objects.
        tracts: Optional list of Tract objects for multi-tract verification.
        stated_area_sq_ft: Stated area from deed (optional, for comparison).
        closure_tolerance_ft: Custom closure tolerance (default: 0.01 ft).
        double_entry_calls: Optional independently-entered call set for guardrail F.
        audit_context: Optional audit context for recording check results; its
            ``skipped_courses`` are honoured like ``skipped_courses``.
        skipped_courses: Courses extraction could not parse. Any skip blocks
            traverse closure and leaves misclosure, area and perimeter undetermined;
            per tract, a tract's own skips and those labelled with it apply.

    Returns:
        ClosureResult when tracts is None (single-tract).
        list[ClosureResult] when tracts is provided (one per tract).
    """
    if tracts is not None:
        if audit_context is not None:
            # Reflect only the latest multi-tract run: drop the single-tract audit too.
            audit_context.verification_audit = None
            audit_context.tract_verification_audits = []
        results: list[ClosureResult] = []
        labelled = _merge_skips(
            skipped_courses or [], audit_context.skipped_courses if audit_context else []
        )
        for tract in tracts:
            # Scratch context per tract so tracts never overwrite each other's audit.
            scratch = (
                audit_context.model_copy(update={"verification_audit": None, "skipped_courses": []})
                if audit_context is not None
                else None
            )
            result = verify_tract(
                tract.calls,
                stated_area_sq_ft=tract.stated_area_sq_ft or 0.0,
                closure_tolerance_ft=closure_tolerance_ft,
                audit_context=scratch,
                skipped_courses=skips_for_tract(tract, tracts, labelled),
            )
            if audit_context is not None and scratch is not None and scratch.verification_audit:
                audit_context.tract_verification_audits.append(
                    scratch.verification_audit.model_copy(update={"tract_label": tract.label})
                )
            results.append(result)
        return results

    tolerance = closure_tolerance_ft if closure_tolerance_ft is not None else CLOSURE_TOLERANCE_FT
    # Courses the extractor skipped are missing from ``calls``: a traverse of the
    # rest is not the deed's boundary, so nothing derived from it is determined.
    skipped = _merge_skips(
        skipped_courses or [], audit_context.skipped_courses if audit_context else []
    )

    main_calls = [c for c in calls if not c.is_exception and not c.is_tie_in]
    exception_calls = [c for c in calls if c.is_exception]

    # One pass decides each call's chord, positioning and direction. Records are
    # tracked by position: course numbers may repeat, and only the offending call
    # loses its chord. Stated bearings are never erased to express positioning:
    # the traverse outcome is passed to the checks instead.
    points, records = analyze_courses(main_calls)
    positioned = [record.positioned for record in records]
    bad_chords = [record for record in records if record.bad_chord]
    unpositioned = [record for record in records if not record.positioned]
    # Once a course is unpositioned, every later vertex is relative to an unknown start.
    downstream_courses = (
        [record.call.course for record in records[unpositioned[0].index + 1 :]]
        if unpositioned
        else []
    )

    chord_only = [
        record
        for record in records
        if record.chord_only and not record.bad_chord and record.positioned
    ]
    # A chord-only curve whose stated tangent disagrees with its chord and radius
    # is reported as inconsistent, not merely as lacking a delta/arc.
    tangent_issues = {record.index: tangent_chord_issue(record.call) for record in chord_only}
    inconsistent_chord_indices = {i for i, issue in tangent_issues.items() if issue is not None}
    inconsistent_chord_courses = [
        record.call.course for record in chord_only if record.index in inconsistent_chord_indices
    ]
    # (course, tangent stated): a stated tangent fixes the arc; without one it is ambiguous.
    delta_not_stated_courses = [
        (
            record.call.course,
            stated_tangent(record.call) is not None,
        )
        for record in chord_only
        if record.index not in inconsistent_chord_indices
    ]

    # Degenerate traverse: no course was positioned (bearings or chord endpoints).
    has_computable_traverse = any(positioned)

    misclosure_x = points[-1].x - points[0].x
    misclosure_y = points[-1].y - points[0].y
    misclosure = math.sqrt(misclosure_x**2 + misclosure_y**2)
    misclosure_available = not unpositioned and not skipped
    if not misclosure_available:
        # A broken chain gives no absolute positions: report no misclosure, not a wrong one.
        misclosure_x = misclosure_y = misclosure = 0.0

    warnings: list[str] = [
        f"Course {skip.course}: skipped malformed course {skip.source_excerpt.strip()!r} "
        f"({skip.error_type}); closure, area and perimeter are not determined"
        for skip in skipped
    ]

    for record in bad_chords:
        warnings.append(
            f"Course {record.call.course}: unparseable chord bearing {record.call.chord_bearing!r}; "
            "curve geometry blocked"
        )
    for record in unpositioned:
        if is_spiral(record.call) and not record.bad_chord:
            warnings.append(
                f"Course {record.call.course}: spiral cannot be positioned (no stated chord "
                "bearing and length; never treated as a circular arc or straight line); "
                "closure, area and perimeter are not determined"
            )
        # A chord longer than the diameter fits no circle of that radius.
        elif not record.bad_chord and not record.feasible_chord:
            warnings.append(
                f"Course {record.call.course}: curve cannot be positioned (chord length "
                "exceeds twice the radius); closure, area and perimeter are not determined"
            )
        elif record.no_endpoint:
            warnings.append(
                f"Course {record.call.course}: curve cannot be positioned (no parseable "
                "chord, delta or arc); closure, area and perimeter are not determined"
            )
        else:
            warnings.append(
                f"Course {record.call.course}: course cannot be positioned (no usable "
                "bearing or endpoint); closure, area and perimeter are not determined"
            )
    if downstream_courses:
        warnings.append(
            f"Course(s) {', '.join(str(c) for c in downstream_courses)} follow an unpositioned "
            "course; absolute positions and misclosure are not determined"
        )

    if not has_computable_traverse:
        warnings.append(
            "No computable traverse \u2014 all calls lack bearings (cardinal-only or empty)"
        )

    for record in chord_only:
        reason = (
            "stated tangent, chord and radius are inconsistent"
            if record.index in inconsistent_chord_indices
            else "curve delta/arc not stated"
        )
        warnings.append(
            f"Course {record.call.course}: {reason} - positioned by chord only; "
            "arc, area and perimeter are not determined"
        )

    arc_undetermined = [r for r in records if r.arc_undetermined and not r.chord_only]
    for record in arc_undetermined:
        warnings.append(
            f"Course {record.call.course}: spiral positioned by its stated chord only - "
            "arc shape, area and perimeter are not determined"
        )
    area_available = (
        bool(records)
        and all(record.determined_direction for record in records)
        and not chord_only
        and not arc_undetermined
        and not unpositioned
        and not skipped
    )
    area_sq_ft = 0.0
    area_acres = 0.0
    # An already-unavailable area is not computed from a partial point list.
    if area_available:
        try:
            main_area_sq_ft = calculate_area(points, calls=main_calls)

            exception_area_sq_ft = 0.0
            exception_area_available = True
            if exception_calls:
                warnings.append(
                    f"Found {len(exception_calls)} exception calls - "
                    "calculating exception area to subtract"
                )
                try:
                    exception_area_sq_ft = _calculate_exception_area(exception_calls)
                except ValueError as e:
                    warnings.append(f"Cannot calculate exception area: {e}")
                    exception_area_available = False
                    area_available = False

            area_sq_ft = main_area_sq_ft - exception_area_sq_ft if exception_area_available else 0.0
            area_acres = area_sq_ft / 43560.0
        except ValueError as e:
            area_available = False
            area_sq_ft = 0.0
            area_acres = 0.0
            warnings.append(f"Cannot calculate area: {e}")

    perimeter_available = (
        not chord_only and not arc_undetermined and not unpositioned and not skipped
    )
    perimeter = calculate_perimeter(main_calls) if perimeter_available else 0.0

    closure_passed = has_computable_traverse and misclosure < tolerance and misclosure_available

    # Warn when closure only passes because of a relaxed tolerance
    if closure_passed and tolerance > CLOSURE_TOLERANCE_FT and misclosure >= CLOSURE_TOLERANCE_FT:
        warnings.append(
            f"Closure passes with relaxed tolerance "
            f"({misclosure:.4f} ft misclosure vs {tolerance:.4f} ft threshold)"
        )

    angle_check_passed = check_interior_angles(main_calls, points)
    curve_consistency_passed_val, curve_warnings = check_curve_consistency(
        main_calls, tangent_issues=tangent_issues
    )
    warnings.extend(curve_warnings)

    parallel_warnings = check_parallelism(main_calls)
    warnings.extend(parallel_warnings)

    intersection_warnings = check_boundary_intersections(main_calls, points)
    warnings.extend(intersection_warnings)

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

    discrepancies: list[str] = []
    if double_entry_calls is not None:
        discrepancies = compare_double_entry(calls, double_entry_calls)
        warnings.extend(f"Double-entry discrepancy: {discrepancy}" for discrepancy in discrepancies)

    if stated_area_sq_ft > 0 and area_available:
        area_diff_pct = abs(area_sq_ft - stated_area_sq_ft) / stated_area_sq_ft * 100
        if area_diff_pct > 5.0:
            warnings.append(
                f"Computed area differs from stated by {area_diff_pct:.1f}% "
                f"(computed: {area_sq_ft:.1f} sq ft, stated: {stated_area_sq_ft:.1f} sq ft)"
            )

    # Curves fixed by chord bearing and sweep have determined tangents, not incomplete ones.
    incomplete = [
        record for record in records if not record.determined_direction and not record.positioned
    ]
    if incomplete:
        warnings.append(
            f"{len(incomplete)} call(s) have incomplete bearings (cardinal-only or meanders)"
        )

    if exception_calls:
        exception_incomplete = [c for c in exception_calls if not has_determined_direction(c)]
        if exception_incomplete:
            warnings.append(
                f"Exception tract has {len(exception_incomplete)} incomplete bearing(s)"
            )

    check_results = build_verification_checks(
        main_calls,
        closure_passed=closure_passed,
        misclosure=misclosure,
        tolerance=tolerance,
        curve_consistency_passed=curve_consistency_passed_val,
        parallel_warnings=parallel_warnings,
        intersection_warnings=intersection_warnings,
        reversal_warnings=reversal_warnings,
        distance_warnings=distance_warnings,
        stated_area_sq_ft=stated_area_sq_ft,
        area_sq_ft=area_sq_ft,
        area_available=area_available,
        misclosure_available=misclosure_available,
        positioned=positioned,
        double_entry_performed=double_entry_calls is not None,
        discrepancies=discrepancies,
        curve_issues=curve_warnings,
    )

    curve_blocks: list[tuple[str, str]] = []
    if inconsistent_chord_courses:
        curve_blocks.append(
            (
                "curve_tangent_chord_inconsistent",
                "Stated tangent, chord and radius are inconsistent; "
                "positioned by chord only on course(s) "
                + ", ".join(str(c) for c in inconsistent_chord_courses),
            )
        )
    if delta_not_stated_courses:
        curve_blocks.append(
            (
                "curve_delta_not_stated",
                chord_only_delta_detail(delta_not_stated_courses),
            )
        )
    if bad_chords:
        curve_blocks.append(
            (
                "invalid_chord_bearing",
                "Unparseable chord bearing on course(s) "
                + ", ".join(str(record.call.course) for record in bad_chords),
            )
        )
    spiral_courses = [record.call.course for record in records if is_spiral(record.call)]
    if spiral_courses:
        # Circular L = R*delta and chord formulas do not apply to a spiral: never
        # passed or failed by them, its geometry is reported as unverified.
        curve_blocks.append(
            (
                "spiral_geometry_unverified",
                "Spiral geometry is not verified (circular curve formulas do not apply) "
                "on course(s) " + ", ".join(str(c) for c in spiral_courses),
            )
        )
    if curve_blocks:
        check_results = block_curve_consistency(check_results, curve_blocks)
        curve_consistency_passed_val = False
    if skipped:
        check_results = _block_skipped_closure(check_results, skipped)

    closure_result = ClosureResult(
        misclosure_x_ft=misclosure_x,
        misclosure_y_ft=misclosure_y,
        misclosure_ft=misclosure,
        misclosure_available=misclosure_available,
        area_sq_ft=area_sq_ft,
        area_acres=area_acres,
        perimeter_ft=perimeter,
        perimeter_available=perimeter_available,
        area_available=area_available,
        closure_passed=closure_passed,
        angle_check_passed=angle_check_passed,
        curve_consistency_passed=curve_consistency_passed_val,
        checks=check_results,
        warnings=warnings,
        points=points,
        precision_ratio=misclosure / perimeter if perimeter else None,
    )

    confidence = calculate_confidence_score(closure_result, calls)
    closure_result = closure_result.model_copy(update={"confidence_score": confidence})

    if audit_context is not None:
        # Reflect only the latest single-tract run: drop any multi-tract audits.
        audit_context.tract_verification_audits = []
        precision_ratio_str: str
        if perimeter and (misclosure / perimeter) > 1e-10:
            precision_ratio_str = f"1:{round(1.0 / (misclosure / perimeter))}"
        else:
            precision_ratio_str = "N/A"

        audit_context.verification_audit = VerificationAudit(
            checks=check_results,
            closure_summary={
                "misclosure_ft": misclosure if misclosure_available else "not determined",
                "precision_ratio": precision_ratio_str,
                "area_sq_ft": area_sq_ft if area_available else "not determined",
                "area_acres": area_acres if area_available else "not determined",
                "perimeter_ft": perimeter if perimeter_available else "not determined",
                "confidence_score": confidence,
                "status": closure_result.get_closure_status(),
                "geometry_verified": closure_result.geometry_verified,
                "source_review_status": closure_result.source_review_status,
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
    if result.misclosure_available:
        summary.append(f"Misclosure: {result.misclosure_ft:.4f} ft ({result.get_closure_status()})")
        summary.append(f"  X: {result.misclosure_x_ft:.4f} ft")
        summary.append(f"  Y: {result.misclosure_y_ft:.4f} ft")
    else:
        summary.append(f"Misclosure: not determined ({result.get_closure_status()})")

    if result.precision_ratio is not None and result.precision_ratio > 1e-10:
        ratio_inv = round(1.0 / result.precision_ratio)
        summary.append(f"  Precision: 1:{ratio_inv:,}")

    summary.append("")
    summary.append(
        f"Area: {result.area_sq_ft:,.2f} sq ft ({result.area_acres:.4f} acres)"
        if result.area_available
        else "Area: not determined"
    )
    summary.append(
        f"Perimeter: {result.perimeter_ft:,.2f} ft"
        if result.perimeter_available
        else "Perimeter: not determined"
    )

    if result.confidence_score is not None:
        summary.append(f"Confidence: {result.confidence_score:.2f}")

    summary.append("")
    summary.append("Verification Checks:")
    if result.checks:
        labels = {
            "traverse_closure": "Closure",
            "interior_angles": "Angles",
            "curve_consistency": "Curves",
        }
        statuses = {
            "passed": "PASS",
            "failed": "FAIL",
            "not_applicable": "NOT APPLICABLE",
            "blocked": "BLOCKED",
        }
        for check in result.checks:
            summary.append(
                f"  {labels.get(check.name, check.name)}: {statuses[check.status]} — {check.detail}"
            )
    else:
        summary.append(f"  Closure: {'PASS' if result.closure_passed else 'FAIL'}")
        summary.append(f"  Angles: {'PASS' if result.angle_check_passed else 'FAIL'}")
        summary.append(f"  Curves: {'PASS' if result.curve_consistency_passed else 'FAIL'}")
    summary.append(f"Source review: {result.source_review_status} (independent of geometry checks)")
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
