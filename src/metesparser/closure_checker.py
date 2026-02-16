"""Closure verification and traverse calculations.

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
"""

import math
import statistics

from .bearing_converter import BearingConverter
from .models import ClosureResult, DeedCall, Point


class ClosureChecker:
    """Verify traverse closure and perform validation checks."""

    CLOSURE_TOLERANCE_FT = 0.01

    @classmethod
    def verify_closure(
        cls,
        calls: list[DeedCall],
        stated_area_sq_ft: float = 0.0,
        closure_tolerance_ft: float | None = None,
        double_entry_calls: list[DeedCall] | None = None,
    ) -> ClosureResult:
        """Verify traverse closure and perform all validation checks.

        Args:
            calls: List of DeedCall objects
            stated_area_sq_ft: Stated area from deed (optional, for comparison)
            closure_tolerance_ft: Custom closure tolerance (default: 0.01 ft)
            double_entry_calls: Optional independently-entered call set for guardrail F

        Returns:
            ClosureResult with all checks and computed values
        """
        tolerance = (
            closure_tolerance_ft if closure_tolerance_ft is not None else cls.CLOSURE_TOLERANCE_FT
        )

        main_calls = [c for c in calls if not c.is_exception and not c.is_tie_in]
        exception_calls = [c for c in calls if c.is_exception]

        points = cls.compute_traverse(main_calls)

        misclosure_x = points[-1].x - points[0].x
        misclosure_y = points[-1].y - points[0].y
        misclosure = math.sqrt(misclosure_x**2 + misclosure_y**2)

        warnings = []
        try:
            main_area_sq_ft = cls.calculate_area(points)

            exception_area_sq_ft = 0.0
            if exception_calls:
                warnings.append(
                    f"Found {len(exception_calls)} exception calls - calculating exception area to subtract"
                )
                try:
                    exception_points = cls.compute_traverse(exception_calls)
                    exception_area_sq_ft = cls.calculate_area(exception_points)
                except ValueError as e:
                    warnings.append(f"Cannot calculate exception area: {e}")

            area_sq_ft = main_area_sq_ft - exception_area_sq_ft
            area_acres = area_sq_ft / 43560.0
        except ValueError as e:
            area_sq_ft = 0.0
            area_acres = 0.0
            warnings.append(f"Cannot calculate area: {e}")

        perimeter = cls.calculate_perimeter(main_calls)

        closure_passed = misclosure < tolerance
        angle_check_passed = cls.check_interior_angles(main_calls)
        curve_consistency_passed = cls.check_curve_consistency(main_calls)

        parallel_warnings = cls.check_parallelism(main_calls)
        warnings.extend(parallel_warnings)

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

        if double_entry_calls is not None:
            discrepancies = cls.compare_double_entry(calls, double_entry_calls)
            warnings.extend(
                f"Double-entry discrepancy: {discrepancy}" for discrepancy in discrepancies
            )

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

        return ClosureResult(
            misclosure_x_ft=misclosure_x,
            misclosure_y_ft=misclosure_y,
            misclosure_ft=misclosure,
            area_sq_ft=area_sq_ft,
            area_acres=area_acres,
            perimeter_ft=perimeter,
            closure_passed=closure_passed,
            angle_check_passed=angle_check_passed,
            curve_consistency_passed=curve_consistency_passed,
            warnings=warnings,
            points=points,
            precision_ratio=misclosure / perimeter if perimeter else None,
        )

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
    def calculate_area(cls, points: list[Point]) -> float:
        """Calculate area using shoelace formula.

        Args:
            points: List of Point objects forming a polygon

        Returns:
            Area in square feet

        Raises:
            ValueError: If fewer than 3 points provided
        """
        if len(points) < 3:
            raise ValueError(f"Cannot calculate area with {len(points)} points (need at least 3)")

        area = 0.0
        n = len(points)

        for i in range(n):
            j = (i + 1) % n
            area += points[i].x * points[j].y
            area -= points[j].x * points[i].y

        area = abs(area) / 2.0
        return area

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

        Note: This is a simplified check that verifies the sum of exterior
        angles equals 360°, which is mathematically equivalent to checking
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

            deflection = az2 - az1

            while deflection < 0:
                deflection += 360
            while deflection >= 360:
                deflection -= 360

            deflection_angles.append(deflection)

        actual_sum = sum(deflection_angles)

        return abs(actual_sum - 360.0) < 5.0

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
    def check_curve_consistency(cls, calls: list[DeedCall]) -> bool:
        """Check curve math consistency: L ≈ R*Δ, chord ≈ 2R*sin(Δ/2).

        When delta_deg is not provided but both radius_ft and arc_length_ft
        are present, the implied delta is derived from arc/radius and used
        for consistency checks (including chord validation).

        Args:
            calls: List of DeedCall objects

        Returns:
            True if all curves are consistent (within tolerance)
        """
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
                        return False
                    delta_deg = math.degrees(implied_delta_rad)
                else:
                    # No delta and insufficient data to derive one — skip
                    continue

            delta_rad = math.radians(delta_deg)
            expected_arc = call.radius_ft * delta_rad

            if call.arc_length_ft is not None:
                arc_diff = abs(call.arc_length_ft - expected_arc)
                if arc_diff > tolerance_ft:
                    return False

            expected_chord = 2 * call.radius_ft * math.sin(delta_rad / 2)

            if call.chord_length_ft is not None:
                chord_diff = abs(call.chord_length_ft - expected_chord)
                if chord_diff > tolerance_ft:
                    return False

        return True

    @classmethod
    def check_bearing_reversals(cls, calls: list[DeedCall]) -> list[str]:
        """Check for adjacent courses with bearings ~180 degrees apart.

        This pattern often indicates a quadrant transcription error.

        Args:
            calls: List of DeedCall objects

        Returns:
            List of warning messages
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

    PERMANENT_MONUMENTS = frozenset({
        "iron_rod", "iron_pin", "iron_pipe", "concrete", "brass_cap",
        "rebar", "capped_pin", "capped_rod", "railroad_spike",
    })

    NON_PERMANENT_MONUMENTS = frozenset({
        "stone", "wooden_post", "nail", "pk_nail", "hub_and_tack",
        "monitoring_well", "txdot_monument", "tree", "rock",
        "natural_feature", "other",
    })

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

        if call.monument_type and call.monument_type not in cls.PERMANENT_MONUMENTS:
            return "medium"

        return "high"

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
    def get_closure_summary(cls, result: ClosureResult) -> str:
        """Generate a human-readable closure summary.

        Args:
            result: ClosureResult object

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
        summary.append("")
        summary.append(f"Area: {result.area_sq_ft:,.2f} sq ft ({result.area_acres:.4f} acres)")
        summary.append(f"Perimeter: {result.perimeter_ft:,.2f} ft")
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

        summary.append("")
        summary.append(
            f"Status: {'FULLY VERIFIED ✓' if result.is_fully_verified() else 'NEEDS REVIEW'}"
        )
        summary.append("=" * 60)

        return "\n".join(summary)
