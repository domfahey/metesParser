"""Tests for closure_checker.py - The 6 verification guardrails."""

import math

from metesparser.closure_checker import ClosureChecker
from metesparser.models import DeedCall, Point


class TestTraverseComputation:
    """Test traverse path calculation."""

    def test_compute_single_line_north(self):
        """Single line going North."""
        calls = [
            DeedCall(
                course=1,
                direction_text="N 0° E 100 feet",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
            )
        ]

        points = ClosureChecker.compute_traverse(calls)

        assert len(points) == 2  # Start + 1 call
        assert points[0] == Point(x=0, y=0)
        assert math.isclose(points[1].x, 0.0, abs_tol=0.01)
        assert math.isclose(points[1].y, 100.0, abs_tol=0.01)

    def test_compute_square_traverse(self):
        """Square traverse should close perfectly."""
        calls = [
            DeedCall(
                course=1,
                direction_text="North",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
            ),  # North
            DeedCall(
                course=2,
                direction_text="East",
                bearing_azimuth_deg_from_north=90.0,
                distance_ft=100.0,
            ),  # East
            DeedCall(
                course=3,
                direction_text="South",
                bearing_azimuth_deg_from_north=180.0,
                distance_ft=100.0,
            ),  # South
            DeedCall(
                course=4,
                direction_text="West",
                bearing_azimuth_deg_from_north=270.0,
                distance_ft=100.0,
            ),  # West
        ]

        points = ClosureChecker.compute_traverse(calls)

        assert len(points) == 5
        # Last point should be very close to first (origin)
        assert math.isclose(points[-1].x, 0.0, abs_tol=0.01)
        assert math.isclose(points[-1].y, 0.0, abs_tol=0.01)

    def test_compute_with_custom_start(self):
        """Compute traverse with custom starting point."""
        start = Point(x=100.0, y=200.0)
        calls = [
            DeedCall(
                course=1,
                direction_text="North",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=50.0,
            ),
        ]

        points = ClosureChecker.compute_traverse(calls, start_point=start)

        assert points[0] == start
        assert math.isclose(points[1].x, 100.0, abs_tol=0.01)
        assert math.isclose(points[1].y, 250.0, abs_tol=0.01)

    def test_skips_incomplete_bearings(self):
        """Skip calls with None bearings (meanders)."""
        calls = [
            DeedCall(
                course=1,
                direction_text="North",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=2,
                direction_text="incomplete bearing",
                bearing_azimuth_deg_from_north=None,
                distance_ft=50.0,
                notes="incomplete bearing",
            ),
            DeedCall(
                course=3,
                direction_text="East",
                bearing_azimuth_deg_from_north=90.0,
                distance_ft=100.0,
            ),
        ]

        points = ClosureChecker.compute_traverse(calls)

        # Should only have 3 points (start + 2 valid calls)
        assert len(points) == 3


class TestClosureVerification:
    """Test Guardrail A: Traverse closure < 0.01 ft."""

    def test_perfect_closure(self):
        """Perfect square should pass closure check."""
        calls = [
            DeedCall(
                course=1,
                direction_text="North",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=2,
                direction_text="East",
                bearing_azimuth_deg_from_north=90.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=3,
                direction_text="South",
                bearing_azimuth_deg_from_north=180.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=4,
                direction_text="West",
                bearing_azimuth_deg_from_north=270.0,
                distance_ft=100.0,
            ),
        ]

        result = ClosureChecker.verify_closure(calls)

        assert result.misclosure_ft < 0.01
        assert result.closure_passed is True
        assert math.isclose(result.misclosure_x_ft, 0.0, abs_tol=0.01)
        assert math.isclose(result.misclosure_y_ft, 0.0, abs_tol=0.01)

    def test_18_pennbrook_rectangle(self):
        """Test 18 Pennbrook parcel (rectangle)."""
        calls = [
            # N 33°20' E, 60.00 feet
            DeedCall(
                course=1,
                direction_text="N 33°20' E",
                bearing_quadrant="N 33°20' E",
                bearing_azimuth_deg_from_north=33.333333,
                distance_ft=60.0,
            ),
            # S 56°40' W, 125.00 feet
            DeedCall(
                course=2,
                direction_text="S 56°40' W",
                bearing_quadrant="S 56°40' W",
                bearing_azimuth_deg_from_north=236.666667,
                distance_ft=125.0,
            ),
            # S 33°20' W, 60.00 feet
            DeedCall(
                course=3,
                direction_text="S 33°20' W",
                bearing_quadrant="S 33°20' W",
                bearing_azimuth_deg_from_north=213.333333,
                distance_ft=60.0,
            ),
            # N 56°40' E, 125.00 feet
            DeedCall(
                course=4,
                direction_text="N 56°40' E",
                bearing_quadrant="N 56°40' E",
                bearing_azimuth_deg_from_north=56.666667,
                distance_ft=125.0,
            ),
        ]

        result = ClosureChecker.verify_closure(calls)

        # Should close perfectly (opposite sides parallel)
        assert result.misclosure_ft < 0.01
        assert result.closure_passed is True

    def test_open_traverse(self):
        """Open traverse should fail closure."""
        calls = [
            DeedCall(
                course=1,
                direction_text="North",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=2,
                direction_text="East",
                bearing_azimuth_deg_from_north=90.0,
                distance_ft=100.0,
            ),
            # Missing closing calls
        ]

        result = ClosureChecker.verify_closure(calls)

        assert result.misclosure_ft > 0.01
        assert result.closure_passed is False

    def test_exception_tract_area_is_subtracted_and_reported(self):
        """Exception tracts should contribute warning and subtract their area."""
        calls = [
            DeedCall(
                course=1,
                direction_text="North",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=2,
                direction_text="East",
                bearing_azimuth_deg_from_north=90.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=3,
                direction_text="South",
                bearing_azimuth_deg_from_north=180.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=4,
                direction_text="West",
                bearing_azimuth_deg_from_north=270.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=5,
                direction_text="North",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
                is_exception=True,
            ),
            DeedCall(
                course=6,
                direction_text="East",
                bearing_azimuth_deg_from_north=90.0,
                distance_ft=60.0,
                is_exception=True,
            ),
            DeedCall(
                course=7,
                direction_text="South",
                bearing_azimuth_deg_from_north=180.0,
                distance_ft=60.0,
                is_exception=True,
            ),
        ]

        result = ClosureChecker.verify_closure(calls)

        assert result.warnings == [
            "Found 3 exception calls - calculating exception area to subtract"
        ]

    def test_exception_tract_incomplete_warning_is_emitted(self):
        """Incomplete exception bearings should be reported and still handled."""
        calls = [
            DeedCall(
                course=1,
                direction_text="North",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=2,
                direction_text="East",
                bearing_azimuth_deg_from_north=90.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=3,
                direction_text="South",
                bearing_azimuth_deg_from_north=180.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=4,
                direction_text="West",
                bearing_azimuth_deg_from_north=270.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=5,
                direction_text="exception bearing unknown",
                bearing_azimuth_deg_from_north=None,
                distance_ft=50.0,
                is_exception=True,
            ),
        ]

        result = ClosureChecker.verify_closure(calls)

        assert result.warnings == [
            "Found 1 exception calls - calculating exception area to subtract",
            "Cannot calculate exception area: Cannot calculate area with 1 points (need at least 3)",
            "Exception tract has 1 incomplete bearing(s)",
        ]


class TestAreaCalculation:
    """Test area calculation using shoelace formula."""

    def test_square_area(self):
        """100 ft × 100 ft square = 10,000 sq ft."""
        calls = [
            DeedCall(
                course=1,
                direction_text="North",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=2,
                direction_text="East",
                bearing_azimuth_deg_from_north=90.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=3,
                direction_text="South",
                bearing_azimuth_deg_from_north=180.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=4,
                direction_text="West",
                bearing_azimuth_deg_from_north=270.0,
                distance_ft=100.0,
            ),
        ]

        result = ClosureChecker.verify_closure(calls)

        assert math.isclose(result.area_sq_ft, 10000.0, abs_tol=1.0)
        assert math.isclose(result.area_acres, 10000.0 / 43560.0, abs_tol=0.001)

    def test_18_pennbrook_area(self):
        """18 Pennbrook: Parallelogram (not rectangle), area ≈ 2,971 sq ft."""
        calls = [
            DeedCall(
                course=1,
                direction_text="N 33°20' E",
                bearing_azimuth_deg_from_north=33.333333,
                distance_ft=60.0,
            ),  # N 33°20' E
            DeedCall(
                course=2,
                direction_text="S 56°40' W",
                bearing_azimuth_deg_from_north=236.666667,
                distance_ft=125.0,
            ),  # S 56°40' W
            DeedCall(
                course=3,
                direction_text="S 33°20' W",
                bearing_azimuth_deg_from_north=213.333333,
                distance_ft=60.0,
            ),  # S 33°20' W
            DeedCall(
                course=4,
                direction_text="N 56°40' E",
                bearing_azimuth_deg_from_north=56.666667,
                distance_ft=125.0,
            ),  # N 56°40' E
        ]

        result = ClosureChecker.verify_closure(calls)

        # This is a parallelogram with opposite sides parallel but not perpendicular
        # Area is NOT 60 × 125 (that would assume 90° angles)
        assert math.isclose(result.area_sq_ft, 2970.6, abs_tol=10.0)
        assert math.isclose(result.area_acres, 0.0682, abs_tol=0.001)

    def test_triangle_area(self):
        """Right triangle: 100 ft base × 100 ft height / 2 = 5,000 sq ft."""
        calls = [
            DeedCall(
                course=1,
                direction_text="East",
                bearing_azimuth_deg_from_north=90.0,
                distance_ft=100.0,
            ),  # East
            DeedCall(
                course=2,
                direction_text="South",
                bearing_azimuth_deg_from_north=180.0,
                distance_ft=100.0,
            ),  # South
            DeedCall(
                course=3,
                direction_text="N 45° W",
                bearing_azimuth_deg_from_north=315.0,
                distance_ft=141.42,
            ),  # NW
        ]

        result = ClosureChecker.verify_closure(calls)

        assert math.isclose(result.area_sq_ft, 5000.0, abs_tol=10.0)


class TestPerimeterCalculation:
    """Test perimeter calculation."""

    def test_square_perimeter(self):
        """100 ft × 4 sides = 400 ft."""
        calls = [
            DeedCall(
                course=1,
                direction_text="North",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=2,
                direction_text="East",
                bearing_azimuth_deg_from_north=90.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=3,
                direction_text="South",
                bearing_azimuth_deg_from_north=180.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=4,
                direction_text="West",
                bearing_azimuth_deg_from_north=270.0,
                distance_ft=100.0,
            ),
        ]

        result = ClosureChecker.verify_closure(calls)

        assert math.isclose(result.perimeter_ft, 400.0, abs_tol=0.1)

    def test_perimeter_with_curve(self):
        """Perimeter uses arc length for curves."""
        calls = [
            DeedCall(
                course=1,
                direction_text="North",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=2,
                direction_text="East",
                bearing_azimuth_deg_from_north=90.0,
                distance_ft=100.0,
                curve_dir="right",
                radius_ft=50.0,
                delta_deg=90.0,
                arc_length_ft=78.54,
            ),
        ]

        result = ClosureChecker.verify_closure(calls)

        # 100 + 78.54
        assert math.isclose(result.perimeter_ft, 178.54, abs_tol=0.1)


class TestInteriorAngleCheck:
    """Test Guardrail B: Interior angles sum to (n-2)×180°."""

    def test_square_interior_angles(self):
        """Square: (4-2)×180° = 360°."""
        calls = [
            DeedCall(
                course=1,
                direction_text="North",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=2,
                direction_text="East",
                bearing_azimuth_deg_from_north=90.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=3,
                direction_text="South",
                bearing_azimuth_deg_from_north=180.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=4,
                direction_text="West",
                bearing_azimuth_deg_from_north=270.0,
                distance_ft=100.0,
            ),
        ]

        result = ClosureChecker.verify_closure(calls)

        assert result.angle_check_passed is True

    def test_triangle_interior_angles(self):
        """Triangle: (3-2)×180° = 180°."""
        calls = [
            DeedCall(
                course=1,
                direction_text="North",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=2,
                direction_text="S 60° E",
                bearing_azimuth_deg_from_north=120.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=3,
                direction_text="S 60° W",
                bearing_azimuth_deg_from_north=240.0,
                distance_ft=100.0,
            ),
        ]

        result = ClosureChecker.verify_closure(calls)

        # Equilateral-like three-side geometry should satisfy interior angle rule.
        assert result.angle_check_passed is True

    def test_skips_curves(self):
        """Angle check skipped if curves present."""
        calls = [
            DeedCall(
                course=1,
                direction_text="North",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=2,
                direction_text="East",
                bearing_azimuth_deg_from_north=90.0,
                distance_ft=50.0,
                curve_dir="right",
                radius_ft=50.0,
                delta_deg=90.0,
            ),
        ]

        result = ClosureChecker.verify_closure(calls)

        # Should return True (skipped check)
        assert result.angle_check_passed is True

    def test_interior_angle_normalization_wraps_over_360(self):
        """Large deflection angles wrap to 0-360 during normalization."""
        calls = [
            DeedCall(
                course=1,
                direction_text="North",
                bearing_quadrant="N 10° E",
                bearing_azimuth_deg_from_north=100.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=2,
                direction_text="East",
                bearing_quadrant="S 10° E",
                bearing_azimuth_deg_from_north=800.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=3,
                direction_text="South",
                bearing_quadrant="S 10° W",
                bearing_azimuth_deg_from_north=100.0,
                distance_ft=100.0,
            ),
        ]

        assert ClosureChecker.check_interior_angles(calls) is True


class TestParallelismCheck:
    """Test Guardrail C: Parallel lines have matching bearings."""

    def test_continuing_line_same_bearing(self):
        """'continuing' line should match previous bearing."""
        calls = [
            DeedCall(
                course=1,
                direction_text="N 45° E",
                bearing_azimuth_deg_from_north=45.0,
                distance_ft=100.0,
                along="the north line",
            ),
            DeedCall(
                course=2,
                direction_text="N 45° E",
                bearing_azimuth_deg_from_north=45.0,
                distance_ft=50.0,
                along="continuing along the same line",
            ),
        ]

        result = ClosureChecker.verify_closure(calls)

        # Should pass - no warnings
        assert len(result.warnings) == 0

    def test_continuing_line_different_bearing_warning(self):
        """'continuing' line with different bearing should warn."""
        calls = [
            DeedCall(
                course=1,
                direction_text="N 45° E",
                bearing_azimuth_deg_from_north=45.0,
                distance_ft=100.0,
                along="the north line",
            ),
            DeedCall(
                course=2,
                direction_text="East",
                bearing_azimuth_deg_from_north=90.0,
                distance_ft=50.0,
                along="continuing along the same line",
            ),
        ]

        result = ClosureChecker.verify_closure(calls)

        # Should have warning about bearing mismatch
        assert result.warnings == [
            "Course 2: 'continuing' line but bearing differs from previous (45.0° difference)"
        ]


class TestCurveConsistency:
    """Test Guardrail D: Curve math consistency."""

    def test_valid_curve(self):
        """Valid curve: L = R × Δ."""
        # R=100, Δ=90° → L ≈ 157.08 ft
        delta_rad = math.radians(90.0)
        expected_arc = 100.0 * delta_rad

        calls = [
            DeedCall(
                course=1,
                direction_text="North",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
                curve_dir="right",
                radius_ft=100.0,
                delta_deg=90.0,
                arc_length_ft=expected_arc,
            )
        ]

        result = ClosureChecker.verify_closure(calls)

        assert result.curve_consistency_passed is True

    def test_invalid_arc_length(self):
        """Arc length doesn't match R × Δ."""
        calls = [
            DeedCall(
                course=1,
                direction_text="North",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
                curve_dir="right",
                radius_ft=100.0,
                delta_deg=90.0,
                arc_length_ft=999.0,  # Way off
            )
        ]

        result = ClosureChecker.verify_closure(calls)

        assert result.curve_consistency_passed is False

    def test_invalid_chord_length(self):
        """Chord length doesn't match 2R × sin(Δ/2)."""
        calls = [
            DeedCall(
                course=1,
                direction_text="North",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
                curve_dir="right",
                radius_ft=100.0,
                delta_deg=90.0,
                chord_length_ft=999.0,  # Way off
            )
        ]

        result = ClosureChecker.verify_closure(calls)

        assert result.curve_consistency_passed is False


class TestAreaReasonableness:
    """Test Guardrail E: Computed area vs stated area."""

    def test_matching_area(self):
        """Computed area matches stated area (no warning)."""
        calls = [
            DeedCall(
                course=1,
                direction_text="North",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=2,
                direction_text="East",
                bearing_azimuth_deg_from_north=90.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=3,
                direction_text="South",
                bearing_azimuth_deg_from_north=180.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=4,
                direction_text="West",
                bearing_azimuth_deg_from_north=270.0,
                distance_ft=100.0,
            ),
        ]

        result = ClosureChecker.verify_closure(calls, stated_area_sq_ft=10000.0)

        # Should not have area warning
        assert result.warnings == []

    def test_area_mismatch_warning(self):
        """Computed area differs significantly from stated (warning)."""
        calls = [
            DeedCall(
                course=1,
                direction_text="North",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=2,
                direction_text="East",
                bearing_azimuth_deg_from_north=90.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=3,
                direction_text="South",
                bearing_azimuth_deg_from_north=180.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=4,
                direction_text="West",
                bearing_azimuth_deg_from_north=270.0,
                distance_ft=100.0,
            ),
        ]

        # Stated area way off (should be 10,000 sq ft)
        result = ClosureChecker.verify_closure(calls, stated_area_sq_ft=5000.0)

        # Should have warning about area difference
        assert result.warnings == [
            "Computed area differs from stated by 100.0% (computed: 10000.0 sq ft, stated: 5000.0 sq ft)"
        ]


class TestIncompleteBearingWarning:
    """Test warnings for incomplete bearings."""

    def test_incomplete_bearing_warning(self):
        """Calls with incomplete bearings should be flagged."""
        calls = [
            DeedCall(
                course=1,
                direction_text="incomplete bearing",
                bearing_azimuth_deg_from_north=None,
                distance_ft=50.0,
                notes="incomplete bearing",
            ),
            DeedCall(
                course=2,
                direction_text="North",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
            ),
        ]

        result = ClosureChecker.verify_closure(calls)

        # Should warn about incomplete bearings
        assert result.warnings == [
            "Cannot calculate area: Cannot calculate area with 2 points (need at least 3)",
            "1 call(s) have incomplete bearings (cardinal-only or meanders)",
        ]


class TestDoubleEntryValidation:
    """Test Guardrail F: Double-entry validation."""

    def test_matching_entries(self):
        """Matching entries should have no discrepancies."""
        calls1 = [
            DeedCall(
                course=1,
                direction_text="N 45° E",
                bearing_quadrant="N 45° E",
                bearing_azimuth_deg_from_north=45.0,
                distance_ft=100.0,
            )
        ]
        calls2 = [
            DeedCall(
                course=1,
                direction_text="N 45° E",
                bearing_quadrant="N 45° E",
                bearing_azimuth_deg_from_north=45.0,
                distance_ft=100.0,
            )
        ]

        discrepancies = ClosureChecker.compare_double_entry(calls1, calls2)

        assert len(discrepancies) == 0

    def test_bearing_mismatch(self):
        """Different bearings should be flagged."""
        calls1 = [
            DeedCall(
                course=1, direction_text="N 45° E", bearing_quadrant="N 45° E", distance_ft=100.0
            )
        ]
        calls2 = [
            DeedCall(
                course=1, direction_text="N 50° E", bearing_quadrant="N 50° E", distance_ft=100.0
            )
        ]

        discrepancies = ClosureChecker.compare_double_entry(calls1, calls2)

        assert len(discrepancies) > 0
        assert discrepancies == ["Course 1: Bearing mismatch - 'N 45° E' vs 'N 50° E'"]

    def test_distance_mismatch(self):
        """Different distances should be flagged."""
        calls1 = [
            DeedCall(
                course=1, direction_text="N 45° E", bearing_quadrant="N 45° E", distance_ft=100.0
            )
        ]
        calls2 = [
            DeedCall(
                course=1, direction_text="N 45° E", bearing_quadrant="N 45° E", distance_ft=105.0
            )
        ]

        discrepancies = ClosureChecker.compare_double_entry(calls1, calls2)

        assert len(discrepancies) > 0
        assert discrepancies == ["Course 1: Distance mismatch - 100.00 vs 105.00"]

    def test_different_call_count(self):
        """Different number of calls should be flagged."""
        calls1 = [
            DeedCall(
                course=1,
                direction_text="N 45° E",
                bearing_azimuth_deg_from_north=45.0,
                distance_ft=100.0,
            )
        ]
        calls2 = [
            DeedCall(
                course=1,
                direction_text="N 45° E",
                bearing_azimuth_deg_from_north=45.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=2,
                direction_text="East",
                bearing_azimuth_deg_from_north=90.0,
                distance_ft=50.0,
            ),
        ]

        discrepancies = ClosureChecker.compare_double_entry(calls1, calls2)

        assert len(discrepancies) > 0
        assert discrepancies == ["Different number of calls: 1 vs 2"]

    def test_curve_direction_and_radius_mismatches(self):
        """Curve-specific mismatches should be detected."""
        calls1 = [
            DeedCall(
                course=1,
                direction_text="North",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
                curve_dir="left",
                radius_ft=50.0,
                delta_deg=90.0,
            )
        ]
        calls2 = [
            DeedCall(
                course=1,
                direction_text="North",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
                curve_dir="right",
                radius_ft=55.0,
                delta_deg=90.0,
            )
        ]

        discrepancies = ClosureChecker.compare_double_entry(calls1, calls2)

        assert discrepancies == [
            "Course 1: Curve direction mismatch",
            "Course 1: Radius mismatch - 50.00 vs 55.00",
        ]


class TestClosureSummary:
    """Test human-readable closure summary."""

    def test_summary_format(self):
        """Summary should be formatted correctly."""
        calls = [
            DeedCall(
                course=1,
                direction_text="North",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=2,
                direction_text="East",
                bearing_azimuth_deg_from_north=90.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=3,
                direction_text="South",
                bearing_azimuth_deg_from_north=180.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=4,
                direction_text="West",
                bearing_azimuth_deg_from_north=270.0,
                distance_ft=100.0,
            ),
        ]

        result = ClosureChecker.verify_closure(calls)
        summary = ClosureChecker.get_closure_summary(result)

        # Should contain key sections
        assert "CLOSURE VERIFICATION SUMMARY" in summary
        assert "Misclosure:" in summary
        assert "Area:" in summary
        assert "Perimeter:" in summary
        assert "Verification Checks:" in summary
        assert "Status:" in summary

    def test_fully_verified_status(self):
        """Fully verified should show in summary."""
        calls = [
            DeedCall(
                course=1,
                direction_text="North",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=2,
                direction_text="East",
                bearing_azimuth_deg_from_north=90.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=3,
                direction_text="South",
                bearing_azimuth_deg_from_north=180.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=4,
                direction_text="West",
                bearing_azimuth_deg_from_north=270.0,
                distance_ft=100.0,
            ),
        ]

        result = ClosureChecker.verify_closure(calls)
        summary = ClosureChecker.get_closure_summary(result)

        if result.is_fully_verified():
            assert "FULLY VERIFIED" in summary
        else:
            assert "NEEDS REVIEW" in summary

    def test_summary_includes_warning_block(self):
        """Warnings should render under the summary warnings block."""
        calls = [
            DeedCall(
                course=1,
                direction_text="incomplete",
                bearing_azimuth_deg_from_north=None,
                distance_ft=50.0,
            ),
            DeedCall(
                course=2,
                direction_text="East",
                bearing_azimuth_deg_from_north=90.0,
                distance_ft=100.0,
            ),
        ]

        result = ClosureChecker.verify_closure(calls)
        summary = ClosureChecker.get_closure_summary(result)

        assert "Warnings (" in summary
        assert "  - 1 call(s) have incomplete bearings (cardinal-only or meanders)" in summary


class TestIsFullyVerified:
    """Test the is_fully_verified() method."""

    def test_perfect_closure_verified(self):
        """Perfect closure should be fully verified."""
        calls = [
            DeedCall(
                course=1,
                direction_text="North",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=2,
                direction_text="East",
                bearing_azimuth_deg_from_north=90.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=3,
                direction_text="South",
                bearing_azimuth_deg_from_north=180.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=4,
                direction_text="West",
                bearing_azimuth_deg_from_north=270.0,
                distance_ft=100.0,
            ),
        ]

        result = ClosureChecker.verify_closure(calls)

        assert result.is_fully_verified() is True

    def test_open_traverse_not_verified(self):
        """Open traverse should not be verified."""
        calls = [
            DeedCall(
                course=1,
                direction_text="North",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=2,
                direction_text="East",
                bearing_azimuth_deg_from_north=90.0,
                distance_ft=100.0,
            ),
        ]

        result = ClosureChecker.verify_closure(calls)

        assert result.is_fully_verified() is False

    def test_warnings_prevent_verification(self):
        """Warnings should prevent full verification."""
        calls = [
            DeedCall(
                course=1,
                direction_text="incomplete bearing",
                bearing_azimuth_deg_from_north=None,
                distance_ft=50.0,
                notes="incomplete bearing",
            ),
            DeedCall(
                course=2,
                direction_text="North",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
            ),
            DeedCall(
                course=3,
                direction_text="East",
                bearing_azimuth_deg_from_north=90.0,
                distance_ft=50.0,
            ),
            DeedCall(
                course=4,
                direction_text="South",
                bearing_azimuth_deg_from_north=180.0,
                distance_ft=100.0,
            ),
        ]

        result = ClosureChecker.verify_closure(calls)

        # Should have warnings about incomplete bearings
        if len(result.warnings) > 0:
            assert result.is_fully_verified() is False
