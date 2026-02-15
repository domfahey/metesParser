"""Closure verification and traverse calculations.

Implements the 6 verification guardrails from the playbook:
A) Traverse closure
B) Interior angle validation
C) Parallelism checks
D) Curve consistency
E) Area reasonableness
F) Double-entry validation
"""

import math

from .bearing_converter import BearingConverter
from .models import ClosureResult, DeedCall, Point


class ClosureChecker:
    """Verify traverse closure and perform validation checks."""

    # Closure tolerance (feet)
    CLOSURE_TOLERANCE_FT = 0.01

    @classmethod
    def verify_closure(
        cls,
        calls: list[DeedCall],
        stated_area_sq_ft: float = 0.0,
        closure_tolerance_ft: float | None = None,
    ) -> ClosureResult:
        """Verify traverse closure and perform all validation checks.

        Args:
            calls: List of DeedCall objects
            stated_area_sq_ft: Stated area from deed (optional, for comparison)
            closure_tolerance_ft: Custom closure tolerance (default: 0.01 ft)

        Returns:
            ClosureResult with all checks and computed values
        """
        # Use provided tolerance or default
        tolerance = (
            closure_tolerance_ft if closure_tolerance_ft is not None else cls.CLOSURE_TOLERANCE_FT
        )

        # Separate main tract from exception tracts
        main_calls = [c for c in calls if not c.is_exception]
        exception_calls = [c for c in calls if c.is_exception]

        # Compute traverse for main tract
        points = cls.compute_traverse(main_calls)

        # Calculate misclosure (difference between end and start points)
        # Should be zero for perfectly closed traverse
        misclosure_x = points[-1].x - points[0].x
        misclosure_y = points[-1].y - points[0].y
        misclosure = math.sqrt(misclosure_x**2 + misclosure_y**2)

        # Calculate area (shoelace formula)
        warnings = []
        try:
            main_area_sq_ft = cls.calculate_area(points)

            # Calculate exception areas if present
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

            # Net area = main area - exception area
            area_sq_ft = main_area_sq_ft - exception_area_sq_ft
            area_acres = area_sq_ft / 43560.0
        except ValueError as e:
            # Not enough points for area calculation
            area_sq_ft = 0.0
            area_acres = 0.0
            warnings.append(f"Cannot calculate area: {e}")

        # Calculate perimeter (main tract only)
        perimeter = cls.calculate_perimeter(main_calls)

        # Perform verification checks (main tract only)
        closure_passed = misclosure < tolerance
        angle_check_passed = cls.check_interior_angles(main_calls)
        curve_consistency_passed = cls.check_curve_consistency(main_calls)

        # Check parallelism
        parallel_warnings = cls.check_parallelism(calls)
        warnings.extend(parallel_warnings)

        # Check area reasonableness
        if stated_area_sq_ft > 0:
            area_diff_pct = abs(area_sq_ft - stated_area_sq_ft) / stated_area_sq_ft * 100
            if area_diff_pct > 5.0:
                warnings.append(
                    f"Computed area differs from stated by {area_diff_pct:.1f}% "
                    f"(computed: {area_sq_ft:.1f} sq ft, stated: {stated_area_sq_ft:.1f} sq ft)"
                )

        # Check for incomplete bearings (main tract)
        incomplete = [c for c in main_calls if not c.is_complete_bearing()]
        if incomplete:
            warnings.append(
                f"{len(incomplete)} call(s) have incomplete bearings (cardinal-only or meanders)"
            )

        # Warn about exception tracts
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
                # Skip incomplete bearings (meanders)
                continue

            if call.is_curve():
                # Handle curve (approximate with chord)
                if (
                    call.radius_ft is not None
                    and call.delta_deg is not None
                    and call.curve_dir is not None
                ):
                    next_point = BearingConverter.compute_curve_endpoint(
                        current,
                        call.bearing_azimuth_deg_from_north,
                        call.radius_ft,
                        call.delta_deg,
                        call.curve_dir,
                    )
                else:
                    # Incomplete curve info - skip
                    continue
            else:
                # Straight line
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
            Area in square feet (0.0 if < 3 points)

        Raises:
            ValueError: If fewer than 3 points provided
        """
        if len(points) < 3:
            # Cannot calculate area with < 3 points - this is an error condition
            # Silent return of 0 could mask issues
            raise ValueError(f"Cannot calculate area with {len(points)} points (need at least 3)")

        # Shoelace formula (Gauss's area formula)
        # Sum of (x[i] * y[i+1] - x[i+1] * y[i]) / 2
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
            if call.is_curve() and call.arc_length_ft:
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
        # Only check if all calls have bearings and no curves
        if any(not call.is_complete_bearing() or call.is_curve() for call in calls):
            # Can't check - curves or incomplete bearings
            return True

        n = len(calls)
        if n < 3:
            return True

        # Calculate deflection (exterior) angles
        # For a closed polygon, sum of exterior angles = 360°
        deflection_angles = []
        for i in range(n):
            current = calls[i]
            next_call = calls[(i + 1) % n]

            az1 = current.bearing_azimuth_deg_from_north or 0
            az2 = next_call.bearing_azimuth_deg_from_north or 0

            # Deflection angle (exterior angle)
            deflection = az2 - az1

            # Normalize to [0, 360)
            while deflection < 0:
                deflection += 360
            while deflection >= 360:
                deflection -= 360

            deflection_angles.append(deflection)

        # Sum of exterior angles should equal 360° for a closed polygon
        # This is mathematically equivalent to interior angles = (n-2)*180°
        actual_sum = sum(deflection_angles)

        # Allow 5 degree tolerance (relaxed due to measurement precision)
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

        # Look for "continuing along the same line" or "parallel to"
        for i, call in enumerate(calls):
            if not call.along:
                continue

            if "continuing" in call.along.lower() or "same line" in call.along.lower():
                # Should match previous bearing
                if (
                    i > 0
                    and calls[i - 1].bearing_azimuth_deg_from_north is not None
                    and call.bearing_azimuth_deg_from_north is not None
                ):
                    prev_az = calls[i - 1].bearing_azimuth_deg_from_north or 0
                    curr_az = call.bearing_azimuth_deg_from_north or 0

                    # Should be same or 180° apart
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

        Args:
            calls: List of DeedCall objects

        Returns:
            True if all curves are consistent (within tolerance)
        """
        for call in calls:
            if not call.is_curve():
                continue

            if call.radius_ft is None or call.delta_deg is None:
                # Incomplete curve info
                continue

            # Check L ≈ R * Δ (radians)
            delta_rad = math.radians(call.delta_deg)
            expected_arc = call.radius_ft * delta_rad

            if call.arc_length_ft is not None:
                arc_diff = abs(call.arc_length_ft - expected_arc)
                if arc_diff > 0.1:  # 0.1 ft tolerance
                    return False

            # Check chord ≈ 2R * sin(Δ/2)
            expected_chord = 2 * call.radius_ft * math.sin(delta_rad / 2)

            if call.chord_length_ft is not None:
                chord_diff = abs(call.chord_length_ft - expected_chord)
                if chord_diff > 0.1:  # 0.1 ft tolerance
                    return False

        return True

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
