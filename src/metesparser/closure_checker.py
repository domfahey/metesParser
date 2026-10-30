"""Closure verification, traverse calculations, and quality scoring.

Implements the 6 verification guardrails from the playbook:
A) Traverse closure
B) Interior angle validation
C) Parallelism checks
D) Curve consistency
E) Area reasonableness
F) Double-entry validation

Plus supplementary validation checks:
G) Bearing reversal detection
H) Distance reasonableness

Quality and confidence scoring:
- Per-call quality rating (high/medium/low)
- Overall confidence score (0.0–1.0)
"""

import math
import statistics
from typing import overload

from .bearing_converter import BearingConverter
from .models import (
    PERMANENT_MONUMENTS,
    AuditContext,
    CheckResult,
    ClosureResult,
    DeedCall,
    Point,
    Tract,
    VerificationAudit,
)


class ClosureChecker:
    """Verify traverse closure and perform validation checks."""

    CLOSURE_TOLERANCE_FT = 0.01

    @classmethod
    def verify_tract(
        cls,
        calls: list[DeedCall],
        *,
        stated_area_sq_ft: float = 0.0,
        closure_tolerance_ft: float | None = None,
        audit_context: AuditContext | None = None,
    ) -> ClosureResult:
        """Check one independent tract using every standard verification guardrail."""
        boundary = [call.model_copy(update={"is_exception": False}) for call in calls]
        return cls.verify_closure(
            boundary,
            stated_area_sq_ft=stated_area_sq_ft,
            closure_tolerance_ft=closure_tolerance_ft,
            audit_context=audit_context,
        )

    @overload
    @classmethod
    def verify_closure(
        cls,
        calls: list[DeedCall],
        stated_area_sq_ft: float = ...,
        closure_tolerance_ft: float | None = ...,
        double_entry_calls: list[DeedCall] | None = ...,
        audit_context: AuditContext | None = ...,
        *,
        tracts: None = None,
    ) -> ClosureResult: ...

    @overload
    @classmethod
    def verify_closure(
        cls,
        calls: list[DeedCall],
        stated_area_sq_ft: float = ...,
        closure_tolerance_ft: float | None = ...,
        double_entry_calls: list[DeedCall] | None = ...,
        audit_context: AuditContext | None = ...,
        *,
        tracts: list[Tract],
    ) -> list[ClosureResult]: ...

    @classmethod
    def verify_closure(
        cls,
        calls: list[DeedCall],
        stated_area_sq_ft: float = 0.0,
        closure_tolerance_ft: float | None = None,
        double_entry_calls: list[DeedCall] | None = None,
        audit_context: AuditContext | None = None,
        *,
        tracts: list[Tract] | None = None,
    ) -> ClosureResult | list[ClosureResult]:
        """Verify traverse closure and perform all validation checks.

        Args:
            calls: List of DeedCall objects
            stated_area_sq_ft: Stated area from deed (optional, for comparison)
            closure_tolerance_ft: Custom closure tolerance (default: 0.01 ft)
            double_entry_calls: Optional independently-entered call set for guardrail F

        Returns:
            ClosureResult with all checks, computed values, and confidence_score.
            If tracts provided, returns list[ClosureResult] with one per tract.
        """
        if tracts is not None:
            if audit_context is not None:
                # Reflect only the latest multi-tract run: drop the single-tract audit too.
                audit_context.verification_audit = None
                audit_context.tract_verification_audits = []
            results: list[ClosureResult] = []
            for tract in tracts:
                # Scratch context per tract so tracts never overwrite each other's audit.
                scratch = (
                    audit_context.model_copy(update={"verification_audit": None})
                    if audit_context is not None
                    else None
                )
                result = cls.verify_tract(
                    tract.calls,
                    stated_area_sq_ft=tract.stated_area_sq_ft or 0.0,
                    closure_tolerance_ft=closure_tolerance_ft,
                    audit_context=scratch,
                )
                if audit_context is not None and scratch is not None and scratch.verification_audit:
                    audit_context.tract_verification_audits.append(
                        scratch.verification_audit.model_copy(update={"tract_label": tract.label})
                    )
                results.append(result)
            return results

        tolerance = (
            closure_tolerance_ft if closure_tolerance_ft is not None else cls.CLOSURE_TOLERANCE_FT
        )

        main_calls = [c for c in calls if not c.is_exception and not c.is_tie_in]
        exception_calls = [c for c in calls if c.is_exception]

        # An unparseable chord bearing is never guessed: block the curve check and
        # traverse the course without its chord so the result is reported, not raised.
        # Tracked by position: course numbers may repeat, and only the offending call loses its chord.
        bad_chord_indices = [
            i
            for i, c in enumerate(main_calls)
            if c.is_curve()
            and c.chord_bearing is not None
            and BearingConverter.bearing_to_azimuth(c.chord_bearing) is None
        ]
        bad_chord_courses = [main_calls[i].course for i in bad_chord_indices]
        # Without its chord, a curve with no delta or arc has no determinable endpoint:
        # it is left unpositioned (no bearing), never run along its tangent.
        unpositioned_indices = [
            i
            for i in bad_chord_indices
            if main_calls[i].delta_deg is None and main_calls[i].arc_length_ft is None
        ]
        # A chord longer than the diameter fits no circle of that radius: never positioned by it.
        infeasible_chord_indices = [
            i
            for i, c in enumerate(main_calls)
            if i not in bad_chord_indices
            and c.is_chord_only_curve()
            and c.chord_length_ft is not None
            and c.radius_ft is not None
            and c.chord_length_ft > 2.0 * abs(c.radius_ft)
        ]
        unpositioned_indices = unpositioned_indices + infeasible_chord_indices
        unpositioned_courses = [main_calls[i].course for i in unpositioned_indices]
        bad_chord_texts = {i: main_calls[i].chord_bearing for i in bad_chord_indices}
        main_calls = [
            c.model_copy(update={"chord_bearing": None, "bearing_azimuth_deg_from_north": None})
            if i in unpositioned_indices
            else c
            for i, c in enumerate(main_calls)
        ]
        points = cls.compute_traverse(
            [
                c.model_copy(update={"chord_bearing": None}) if i in bad_chord_indices else c
                for i, c in enumerate(main_calls)
            ]
        )

        chord_only_indices = [
            i
            for i, c in enumerate(main_calls)
            if c.is_chord_only_curve() and i not in bad_chord_indices
        ]
        # A chord-only curve whose stated tangent disagrees with its chord and radius
        # is reported as inconsistent, not merely as lacking a delta/arc.
        inconsistent_chord_indices = {
            i for i in chord_only_indices if cls.curve_consistency_issues([main_calls[i]])
        }
        chord_only_courses = [main_calls[i].course for i in chord_only_indices]
        inconsistent_chord_courses = [
            main_calls[i].course for i in chord_only_indices if i in inconsistent_chord_indices
        ]
        delta_not_stated_courses = [
            main_calls[i].course for i in chord_only_indices if i not in inconsistent_chord_indices
        ]

        # Check for degenerate traverse: no calls contributed azimuths
        computable_calls = sum(
            1 for c in main_calls if c.bearing_azimuth_deg_from_north is not None
        )
        has_computable_traverse = computable_calls > 0

        misclosure_x = points[-1].x - points[0].x
        misclosure_y = points[-1].y - points[0].y
        misclosure = math.sqrt(misclosure_x**2 + misclosure_y**2)

        warnings = []

        for i in bad_chord_indices:
            warnings.append(
                f"Course {main_calls[i].course}: unparseable chord bearing {bad_chord_texts[i]!r}; "
                "curve geometry blocked"
            )
        for i in unpositioned_indices:
            if i in infeasible_chord_indices:
                warnings.append(
                    f"Course {main_calls[i].course}: curve cannot be positioned (chord length "
                    "exceeds twice the radius); closure, area and perimeter are not determined"
                )
            else:
                warnings.append(
                    f"Course {main_calls[i].course}: curve cannot be positioned (no parseable "
                    "chord, delta or arc); closure, area and perimeter are not determined"
                )

        if not has_computable_traverse:
            warnings.append(
                "No computable traverse — all calls lack bearings (cardinal-only or empty)"
            )

        for i in chord_only_indices:
            reason = (
                "stated tangent, chord and radius are inconsistent"
                if i in inconsistent_chord_indices
                else "curve delta/arc not stated"
            )
            warnings.append(
                f"Course {main_calls[i].course}: {reason} - positioned by chord only; "
                "arc, area and perimeter are not determined"
            )

        area_available = (
            bool(main_calls)
            and all(call.is_complete_bearing() for call in main_calls)
            and not chord_only_courses
            and not unpositioned_courses
        )
        try:
            main_area_sq_ft = cls.calculate_area(points, calls=main_calls)

            exception_area_sq_ft = 0.0
            exception_area_available = True
            if exception_calls:
                warnings.append(
                    f"Found {len(exception_calls)} exception calls - calculating exception area to subtract"
                )
                try:
                    exception_area_sq_ft = cls._calculate_exception_area(exception_calls)
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

        perimeter_available = not chord_only_courses and not unpositioned_courses
        perimeter = cls.calculate_perimeter(main_calls) if perimeter_available else 0.0

        closure_passed = (
            has_computable_traverse and misclosure < tolerance and not unpositioned_courses
        )

        # Warn when closure only passes because of a relaxed tolerance
        if (
            closure_passed
            and tolerance > cls.CLOSURE_TOLERANCE_FT
            and misclosure >= cls.CLOSURE_TOLERANCE_FT
        ):
            warnings.append(
                f"Closure passes with relaxed tolerance "
                f"({misclosure:.4f} ft misclosure vs {tolerance:.4f} ft threshold)"
            )

        angle_check_passed = cls.check_interior_angles(main_calls)
        curve_issues = cls.curve_consistency_issues(main_calls)
        curve_consistency_passed = not curve_issues

        parallel_warnings = cls.check_parallelism(main_calls)
        warnings.extend(parallel_warnings)

        intersection_warnings = cls.check_boundary_intersections(main_calls, points)
        warnings.extend(intersection_warnings)

        reversal_warnings = cls.check_bearing_reversals(main_calls)
        warnings.extend(reversal_warnings)

        distance_warnings = cls.check_distance_reasonableness(main_calls)
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
            discrepancies = cls.compare_double_entry(calls, double_entry_calls)
            warnings.extend(
                f"Double-entry discrepancy: {discrepancy}" for discrepancy in discrepancies
            )

        if stated_area_sq_ft > 0 and area_available:
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

        from mp_models import DeedCall as PackageCall
        from mp_verify.checks import block_curve_consistency, build_verification_checks

        package_calls = [PackageCall.model_construct(**call.model_dump()) for call in main_calls]
        package_check_results = build_verification_checks(
            package_calls,
            closure_passed=closure_passed,
            misclosure=misclosure,
            tolerance=tolerance,
            curve_consistency_passed=curve_consistency_passed,
            parallel_warnings=parallel_warnings,
            intersection_warnings=intersection_warnings,
            reversal_warnings=reversal_warnings,
            distance_warnings=distance_warnings,
            stated_area_sq_ft=stated_area_sq_ft,
            area_sq_ft=area_sq_ft,
            area_available=area_available,
            double_entry_performed=double_entry_calls is not None,
            discrepancies=discrepancies,
            curve_issues=curve_issues,
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
                    "Curve delta/arc not stated (minor or major arc ambiguous); "
                    "positioned by chord only on course(s) "
                    + ", ".join(str(c) for c in delta_not_stated_courses),
                )
            )
        if bad_chord_courses:
            curve_blocks.append(
                (
                    "invalid_chord_bearing",
                    "Unparseable chord bearing on course(s) "
                    + ", ".join(str(c) for c in bad_chord_courses),
                )
            )
        if curve_blocks:
            package_check_results = block_curve_consistency(package_check_results, curve_blocks)
            curve_consistency_passed = False
        check_results = [
            CheckResult.model_validate(check.model_dump()) for check in package_check_results
        ]

        closure_result = ClosureResult(
            misclosure_x_ft=misclosure_x,
            misclosure_y_ft=misclosure_y,
            misclosure_ft=misclosure,
            area_sq_ft=area_sq_ft,
            area_acres=area_acres,
            perimeter_ft=perimeter,
            perimeter_available=perimeter_available,
            area_available=area_available,
            closure_passed=closure_passed,
            angle_check_passed=angle_check_passed,
            curve_consistency_passed=curve_consistency_passed,
            checks=check_results,
            warnings=warnings,
            points=points,
            precision_ratio=misclosure / perimeter if perimeter else None,
        )

        confidence = cls.calculate_confidence_score(closure_result, calls)
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
                    "misclosure_ft": misclosure,
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

    @classmethod
    def compute_traverse(
        cls, calls: list[DeedCall], start_point: Point | None = None
    ) -> list[Point]:
        """Compute the traverse path from calls.

        Args:
            calls: List of DeedCall objects
            start_point: Starting point (default: origin)

        Returns:
            List of Point objects representing vertices
        """
        if start_point is None:
            start_point = Point(x=0, y=0)
        points = [start_point]
        current = start_point

        for call in calls:
            if call.is_chord_only_curve():
                # Radius + chord without delta/arc: the arc is ambiguous (minor or
                # major), but the stated chord fixes the endpoint displacement exactly.
                assert call.chord_bearing is not None and call.chord_length_ft is not None
                assert call.radius_ft is not None
                if call.chord_length_ft > 2.0 * abs(call.radius_ft):
                    # No circle of this radius has such a chord; leave it unpositioned.
                    continue
                chord_azimuth = BearingConverter.bearing_to_azimuth(call.chord_bearing)
                if chord_azimuth is None:
                    raise ValueError(f"Course {call.course}: invalid chord bearing")
                dx, dy = BearingConverter.calculate_deltas(chord_azimuth, call.chord_length_ft)
                current = Point(x=current.x + dx, y=current.y + dy)
                points.append(current)
                continue

            if call.bearing_azimuth_deg_from_north is None:
                continue

            if call.is_curve():
                next_point: Point | None = None

                if call.radius_ft is not None and call.curve_dir is not None:
                    delta_deg = call.delta_deg
                    if (
                        delta_deg is None
                        and call.arc_length_ft is not None
                        and call.radius_ft > 0.0
                    ):
                        delta_deg = math.degrees(call.arc_length_ft / call.radius_ft)

                    if delta_deg is not None and abs(delta_deg) > 1e-9:
                        if call.chord_bearing is not None:
                            chord_azimuth = BearingConverter.bearing_to_azimuth(call.chord_bearing)
                            if chord_azimuth is None:
                                raise ValueError(f"Course {call.course}: invalid chord bearing")
                            # A chord bearing already describes the endpoint vector.
                            # Only tangent bearings need rotation by half the delta.
                            chord_length = (
                                2 * call.radius_ft * math.sin(math.radians(delta_deg) / 2)
                            )
                            dx, dy = BearingConverter.calculate_deltas(chord_azimuth, chord_length)
                            next_point = Point(x=current.x + dx, y=current.y + dy)
                        else:
                            next_point = BearingConverter.compute_curve_endpoint(
                                current,
                                call.bearing_azimuth_deg_from_north,
                                call.radius_ft,
                                delta_deg,
                                call.curve_dir,
                            )

                if next_point is None:
                    dx, dy = BearingConverter.calculate_deltas(
                        call.bearing_azimuth_deg_from_north,
                        call.distance_ft,
                    )
                    next_point = Point(x=current.x + dx, y=current.y + dy)
            else:
                dx, dy = BearingConverter.calculate_deltas(
                    call.bearing_azimuth_deg_from_north,
                    call.distance_ft,
                )
                next_point = Point(x=current.x + dx, y=current.y + dy)

            points.append(next_point)
            current = next_point

        return points

    @classmethod
    def calculate_area(cls, points: list[Point], *, calls: list[DeedCall] | None = None) -> float:
        """Calculate polygon area, including circular segments when calls are supplied.

        Args:
            points: List of Point objects forming a polygon
            calls: Optional traverse calls for signed circular-segment corrections

        Returns:
            Area in square feet

        Raises:
            ValueError: If fewer than 3 points provided without a curved boundary
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

    @classmethod
    def _calculate_exception_area(cls, calls: list[DeedCall]) -> float:
        """Sum closed exception loops independently of their winding.

        The flat call API has no tract identifiers. A return to the local
        origin ends a loop; an incomplete final loop makes net area unavailable.
        """
        areas: list[float] = []
        pending: list[DeedCall] = []
        points = [Point(x=0, y=0)]
        for call in calls:
            if call.is_tie_in:
                continue
            if call.bearing_azimuth_deg_from_north is None:
                raise ValueError(
                    f"Exception course {call.course} has an incomplete bearing; net area unavailable"
                )
            points.extend(cls.compute_traverse([call], start_point=points[-1])[1:])
            pending.append(call)
            misclosure = math.hypot(points[-1].x, points[-1].y)
            if misclosure < cls.CLOSURE_TOLERANCE_FT:
                intersections = cls.check_boundary_intersections(pending, points)
                if intersections:
                    raise ValueError(
                        f"Exception tract topology failed; net area unavailable: {intersections[0]}"
                    )
                if not cls.check_curve_consistency(pending):
                    raise ValueError(
                        f"Exception tract ending at course {call.course} has inconsistent curves; net area unavailable"
                    )
                areas.append(cls.calculate_area(points, calls=pending))
                pending = []
                points = [Point(x=0, y=0)]
        if pending:
            misclosure = math.hypot(points[-1].x, points[-1].y)
            raise ValueError(
                f"Exception tract ending at course {pending[-1].course} does not close "
                f"({misclosure:.4f} ft misclosure); net area unavailable"
            )
        return math.fsum(areas)

    @classmethod
    def calculate_perimeter(cls, calls: list[DeedCall]) -> float:
        """Calculate total perimeter from calls.

        Args:
            calls: List of DeedCall objects

        Returns:
            Perimeter in feet
        """
        perimeter = 0.0
        for call in calls:
            if call.is_curve() and call.arc_length_ft is not None and call.arc_length_ft > 0.0:
                perimeter += call.arc_length_ft
            else:
                perimeter += call.distance_ft
        return perimeter

    @classmethod
    def check_interior_angles(cls, calls: list[DeedCall]) -> bool:
        """Check if interior angles sum correctly: (n-2) * 180°.

        This check only applies to all-straight polygons (no curves).

        Note: This is a simplified check that verifies the sum of signed exterior
        angles equals +/-360°, which is mathematically equivalent to checking
        interior angles sum to (n-2)*180°.

        Args:
            calls: List of DeedCall objects

        Returns:
            True if angles sum correctly (within tolerance)
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

    @classmethod
    def check_boundary_intersections(
        cls, calls: list[DeedCall], coordinates: list[Point]
    ) -> list[str]:
        """Use the shared straight/circular checker for the legacy model API."""
        from mp_models import DeedCall as PackageCall
        from mp_models import Point as PackagePoint
        from mp_verify.checks import check_boundary_intersections

        # Preserve incomplete model-copy inputs so the checker can report gaps.
        package_calls = [
            PackageCall.model_construct(**call.model_dump(mode="json")) for call in calls
        ]
        points = [PackagePoint(x=point.x, y=point.y) for point in coordinates]
        return check_boundary_intersections(package_calls, points)

    @classmethod
    def check_straight_boundary_intersections(
        cls, calls: list[DeedCall], coordinates: list[Point]
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
                    (
                        on_segment(a, b, c),
                        on_segment(a, b, d),
                        on_segment(c, d, a),
                        on_segment(c, d, b),
                    )
                ):
                    warnings.append(
                        f"Courses {first.course}-{second.course}: straight boundary self-intersection "
                        "(crossing, overlap, or nonadjacent touch)"
                    )
        return warnings

    @classmethod
    def check_parallelism(cls, calls: list[DeedCall]) -> list[str]:
        """Check for parallel lines that should have matching bearings.

        Args:
            calls: List of DeedCall objects

        Returns:
            List of warning messages for parallelism issues
        """
        warnings = []

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
                            f"from previous ({diff:.1f}° difference)"
                        )

        return warnings

    @classmethod
    def curve_consistency_issues(cls, calls: list[DeedCall]) -> list[str]:
        """Return the curve-math inconsistencies found by the canonical package check.

        Delegates to ``mp_verify.checks.check_curve_consistency`` (L ~ R*delta,
        chord ~ 2R*sin(delta/2), and stated tangent vs chord bearing and radius),
        so the compatibility path applies the same rules and shared tolerances.
        """
        from mp_models import DeedCall as PackageCall
        from mp_verify.checks import check_curve_consistency

        package_calls = [PackageCall.model_construct(**call.model_dump()) for call in calls]
        passed, warnings = check_curve_consistency(package_calls)
        return [] if passed else warnings or ["Curve math inconsistency detected"]

    @classmethod
    def check_curve_consistency(cls, calls: list[DeedCall]) -> bool:
        """Check curve math consistency: L ≈ R*Δ, chord ≈ 2R*sin(Δ/2), tangent vs chord.

        When delta_deg is not provided but both radius_ft and arc_length_ft
        are present, the implied delta is derived from arc/radius and used
        for consistency checks (including chord validation).

        Args:
            calls: List of DeedCall objects

        Returns:
            True if all curves are consistent (within tolerance)
        """
        return not cls.curve_consistency_issues(calls)

    @classmethod
    def check_bearing_reversals(cls, calls: list[DeedCall]) -> list[str]:
        """Check for adjacent courses with bearings ~180 degrees apart.

        This pattern often indicates a quadrant transcription error in straight
        courses. Curve bearings may describe tangents or chords; comparing them
        directly does not establish a reversal, so pairs involving arcs are skipped.

        Args:
            calls: List of DeedCall objects

        Returns:
            List of warning messages
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
                    f"({diff:.1f}° apart, near 180°)"
                )

        return warnings

    @classmethod
    def check_distance_reasonableness(cls, calls: list[DeedCall]) -> list[str]:
        """Check for suspiciously short, long, or dominant distances.

        Flags:
        - Distances < 0.5 ft (suspiciously short)
        - Distances > 10x the median (unusually long)
        - Single course > 90% of total perimeter

        Args:
            calls: List of DeedCall objects

        Returns:
            List of warning messages
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
                warnings.append(
                    f"Course {call.course}: suspiciously short distance ({dist:.2f} ft)"
                )

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

    @classmethod
    def score_call_quality(cls, call: DeedCall) -> str:
        """Rate individual call quality as high/medium/low.

        Scoring logic:
        - low: incomplete bearing (no azimuth) OR indefinite call
        - medium: complete bearing but has meander flag or non-permanent monument
        - high: complete bearing with permanent or no monument, no flags

        Args:
            call: DeedCall to score

        Returns:
            "high", "medium", or "low"
        """
        if not call.is_complete_bearing() or call.is_indefinite:
            return "low"

        if call.is_meander:
            return "medium"

        if call.monument_type and call.monument_type not in PERMANENT_MONUMENTS:
            return "medium"

        return "high"

    @classmethod
    def calculate_confidence_score(cls, result: ClosureResult, calls: list[DeedCall]) -> float:
        """Calculate overall confidence score (0.0–1.0) for a closure result.

        Weighted components:
        - Closure quality (30%): based on misclosure distance and pass/fail
        - Verification checks (20%): angle + curve consistency
        - Bearing completeness (25%): ratio of calls with complete bearings
        - Call quality (15%): ratio of high-quality calls
        - Warning penalty (10%): deducted per warning

        Args:
            result: ClosureResult from verify_closure()
            calls: List of DeedCall objects

        Returns:
            Score between 0.0 and 1.0 (inclusive)
        """
        if not calls:
            return 0.0

        # Closure quality (30%)
        if result.closure_passed:
            if result.misclosure_ft < 0.001:
                closure_score = 1.0
            elif result.misclosure_ft < 0.01:
                closure_score = 0.9
            elif result.misclosure_ft < 0.1:
                closure_score = 0.7
            else:
                closure_score = 0.5
        else:
            closure_score = max(0.0, 0.3 - result.misclosure_ft * 0.02)

        # Verification checks (20%)
        if result.checks:
            checks_passed = sum(
                check.status == "passed"
                for check in result.checks
                if check.name in {"interior_angles", "curve_consistency"}
            )
        else:
            checks_passed = sum([result.angle_check_passed, result.curve_consistency_passed])
        checks_score = checks_passed / 2.0

        # Bearing completeness (25%)
        complete = sum(1 for c in calls if c.is_complete_bearing())
        bearing_score = complete / len(calls)

        # Call quality (15%)
        qualities = [cls.score_call_quality(c) for c in calls]
        quality_weights = {"high": 1.0, "medium": 0.6, "low": 0.2}
        quality_score = sum(quality_weights[q] for q in qualities) / len(calls)

        # Warning penalty (10%)
        warning_score = max(0.0, 1.0 - len(result.warnings) * 0.2)

        weighted = (
            closure_score * 0.30
            + checks_score * 0.20
            + bearing_score * 0.25
            + quality_score * 0.15
            + warning_score * 0.10
        )

        return max(0.0, min(1.0, weighted))

    @classmethod
    def compare_double_entry(cls, calls1: list[DeedCall], calls2: list[DeedCall]) -> list[str]:
        """Compare two entry sets for discrepancies (double-entry validation).

        Args:
            calls1: First set of calls
            calls2: Second set of calls

        Returns:
            List of discrepancy messages
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

    @classmethod
    def get_closure_summary(
        cls,
        result: ClosureResult,
        calls: list[DeedCall] | None = None,
    ) -> str:
        """Generate a human-readable closure summary.

        Args:
            result: ClosureResult object
            calls: Optional list of DeedCall objects for per-call quality breakdown

        Returns:
            Formatted summary string
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
        summary.append(
            f"Source review: {result.source_review_status} (independent of geometry checks)"
        )
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
                q = call.quality or cls.score_call_quality(call)
                quality_counts[q] += 1
            summary.append("")
            summary.append("Quality Breakdown:")
            for level in ("high", "medium", "low"):
                count = quality_counts[level]
                if count > 0:
                    summary.append(f"  {level}: {count} call(s)")

        summary.append("")
        summary.append(
            f"Status: {'FULLY VERIFIED ✓' if result.is_fully_verified() else 'NEEDS REVIEW'}"
        )
        summary.append("=" * 60)

        return "\n".join(summary)
