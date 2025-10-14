"""Tests for bug fixes identified in code review.

Tests cover critical, high, and medium severity bugs fixed in:
- bearing_converter.py
- call_extractor.py
- closure_checker.py
"""

import math

import pytest

from metesparser.bearing_converter import BearingConverter
from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker
from metesparser.models import DeedCall


class TestCriticalBug1DivisionByZero:
    """Bug #1: Division by zero in curve calculations when radius = 0."""

    def test_zero_radius_with_delta(self):
        """Radius of 0 with delta should raise ValueError."""
        with pytest.raises(ValueError, match="Radius must be positive"):
            BearingConverter.calculate_curve_properties(radius_ft=0.0, delta_deg=90.0)

    def test_negative_radius(self):
        """Negative radius should raise ValueError."""
        with pytest.raises(ValueError, match="Radius must be positive"):
            BearingConverter.calculate_curve_properties(radius_ft=-50.0, delta_deg=90.0)

    def test_zero_radius_with_arc(self):
        """Radius of 0 with arc length should raise ValueError."""
        with pytest.raises(ValueError, match="Radius must be positive"):
            BearingConverter.calculate_curve_properties(radius_ft=0.0, arc_length_ft=78.54)


class TestCriticalBug2UnboundVariable:
    """Bug #2: Unbound variable risk in curve property calculation."""

    def test_neither_delta_nor_arc_provided(self):
        """Should raise ValueError when neither delta nor arc provided."""
        with pytest.raises(ValueError, match="Must provide either delta_deg or arc_length_ft"):
            BearingConverter.calculate_curve_properties(radius_ft=50.0)

    def test_delta_rad_initialized(self):
        """delta_rad should be in returned dict even for edge cases."""
        result = BearingConverter.calculate_curve_properties(radius_ft=50.0, delta_deg=90.0)
        assert "delta_rad" in result
        assert math.isclose(result["delta_rad"], math.radians(90.0), abs_tol=0.0001)


class TestHighBug3MinutesRounding:
    """Bug #3: Minutes rounding to 60 creates invalid bearings."""

    def test_bearing_rounds_to_60_minutes(self):
        """Bearing with 59.99 minutes should round to next degree, not 60 minutes."""
        # Test the rounding logic with a value that would round to 60 minutes
        # 45.999722° = 45°59'59.0" which might display seconds
        azimuth = 45.999722
        result = BearingConverter.azimuth_to_quadrant(azimuth)

        # Should not contain "60'" anywhere
        assert "60'" not in result
        # Should either be 46° or have valid seconds
        assert ("46°" in result) or ("45°59'" in result and "59" in result)

    def test_call_extractor_handles_rounding(self):
        """CallExtractor should handle minutes rounding edge case."""
        # Use a valid bearing that will be normalized
        text = "THENCE North 45 degrees East 100 feet"
        calls = CallExtractor.extract_calls(text)

        assert len(calls) == 1
        # Should have a valid bearing_quadrant
        assert calls[0].bearing_quadrant is not None
        # Should not have 60 minutes if present
        if "'" in calls[0].bearing_quadrant:
            assert "60'" not in calls[0].bearing_quadrant


class TestHighBug4And5InvalidDMS:
    """Bugs #4 & #5: Regex accepts invalid degrees/minutes/seconds."""

    def test_reject_degrees_over_90(self):
        """Bearings with degrees > 90 should not parse."""
        invalid_bearings = [
            "N 91°00' E",
            "S 95°30' W",
            "N 120°00' E",
        ]

        for bearing in invalid_bearings:
            result = BearingConverter.parse_quadrant_bearing(bearing)
            assert result is None, f"Should reject invalid bearing: {bearing}"

    def test_reject_minutes_over_59(self):
        """Bearings with minutes >= 60 should not parse."""
        invalid_bearings = [
            "N 45°60' E",
            "S 30°70' W",
            "N 89°99' E",
        ]

        for bearing in invalid_bearings:
            result = BearingConverter.parse_quadrant_bearing(bearing)
            assert result is None, f"Should reject invalid bearing: {bearing}"

    def test_reject_seconds_over_59(self):
        """Bearings with seconds >= 60 should not parse."""
        invalid_bearings = [
            'N 45°30\'60" E',
            'S 30°30\'70" W',
            'N 89°59\'99" E',
        ]

        for bearing in invalid_bearings:
            result = BearingConverter.parse_quadrant_bearing(bearing)
            assert result is None, f"Should reject invalid bearing: {bearing}"

    def test_accept_valid_edge_cases(self):
        """Valid edge cases should parse correctly."""
        valid_bearings = [
            ("N 90°00' E", 90.0),
            ("S 00°00' W", 0.0),
            ("N 45°59' E", 45.983333),
            ('S 89°59\'59" W', 89.999722),
        ]

        for bearing, expected_degrees in valid_bearings:
            result = BearingConverter.parse_quadrant_bearing(bearing)
            assert result is not None, f"Should accept valid bearing: {bearing}"
            _, degrees, _ = result
            assert math.isclose(degrees, expected_degrees, abs_tol=0.001)


class TestHighBug6DeltaValidation:
    """Bug #6: No validation for curve delta angles > 360°."""

    def test_reject_delta_over_360(self):
        """Delta angle > 360° should raise ValueError."""
        with pytest.raises(ValueError, match="Delta angle must be 0-360 degrees"):
            BearingConverter.calculate_curve_properties(radius_ft=50.0, delta_deg=450.0)

    def test_reject_negative_delta(self):
        """Negative delta should raise ValueError."""
        with pytest.raises(ValueError, match="Delta angle must be 0-360 degrees"):
            BearingConverter.calculate_curve_properties(radius_ft=50.0, delta_deg=-45.0)

    def test_computed_delta_over_360(self):
        """Computed delta from large arc/small radius should raise ValueError."""
        # arc = 10000 ft, radius = 10 ft => delta = 1000/10 = 100 radians ≈ 5730°
        with pytest.raises(ValueError, match="Computed delta angle.*exceeds 360"):
            BearingConverter.calculate_curve_properties(radius_ft=10.0, arc_length_ft=10000.0)

    def test_accept_valid_deltas(self):
        """Valid delta angles should work correctly."""
        valid_deltas = [0.0, 45.0, 90.0, 180.0, 270.0, 360.0]

        for delta in valid_deltas:
            result = BearingConverter.calculate_curve_properties(radius_ft=50.0, delta_deg=delta)
            assert result["delta_deg"] == delta


class TestMediumBug7AreaCalculation:
    """Bug #7: Area calculation silent failure for < 3 points."""

    def test_area_with_zero_points(self):
        """Zero points should raise ValueError."""
        from metesparser.models import Point

        points = []
        with pytest.raises(ValueError, match="Cannot calculate area with 0 points"):
            ClosureChecker.calculate_area(points)

    def test_area_with_one_point(self):
        """One point should raise ValueError."""
        from metesparser.models import Point

        points = [Point(x=0, y=0)]
        with pytest.raises(ValueError, match="Cannot calculate area with 1 points"):
            ClosureChecker.calculate_area(points)

    def test_area_with_two_points(self):
        """Two points should raise ValueError."""
        from metesparser.models import Point

        points = [Point(x=0, y=0), Point(x=100, y=0)]
        with pytest.raises(ValueError, match="Cannot calculate area with 2 points"):
            ClosureChecker.calculate_area(points)

    def test_verify_closure_handles_insufficient_points(self):
        """verify_closure should handle < 3 points gracefully with warning."""
        calls = [
            DeedCall(
                course=1,
                direction_text="North",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
            ),
        ]

        result = ClosureChecker.verify_closure(calls)

        # Should have warning about insufficient points
        assert any("Cannot calculate area" in w for w in result.warnings)
        # Area should be 0
        assert result.area_sq_ft == 0.0


class TestMediumBug13ConfigurableTolerance:
    """Bug #13: Hardcoded closure tolerance should be configurable."""

    def test_default_tolerance(self):
        """Default tolerance should be 0.01 ft."""
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
        assert result.closure_passed is True

    def test_custom_tolerance(self):
        """Custom tolerance should be respected."""
        # Create a nearly-closed square (off by 0.5 ft)
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
                distance_ft=99.5,  # 0.5 ft short
            ),
        ]

        # With default tolerance (0.01 ft), should fail
        result_strict = ClosureChecker.verify_closure(calls)
        assert result_strict.closure_passed is False

        # With 1.0 ft tolerance, should pass
        result_relaxed = ClosureChecker.verify_closure(calls, closure_tolerance_ft=1.0)
        assert result_relaxed.closure_passed is True


class TestEdgeCases:
    """Additional edge case tests for robustness."""

    def test_exact_90_degree_bearing(self):
        """90° bearing (due east) should parse correctly."""
        result = BearingConverter.parse_quadrant_bearing("N 90°00' E")
        assert result is not None
        _, degrees, _ = result
        assert math.isclose(degrees, 90.0, abs_tol=0.001)

    def test_zero_degree_bearing(self):
        """0° bearing should parse correctly."""
        result = BearingConverter.parse_quadrant_bearing("N 00°00' E")
        assert result is not None
        _, degrees, _ = result
        assert math.isclose(degrees, 0.0, abs_tol=0.001)

    def test_zero_delta_curve(self):
        """Zero delta curve should work (straight line)."""
        result = BearingConverter.calculate_curve_properties(radius_ft=50.0, delta_deg=0.0)
        assert result["arc_length_ft"] == 0.0
        assert result["chord_length_ft"] == 0.0

    def test_360_degree_curve(self):
        """360° curve (full circle) should work."""
        result = BearingConverter.calculate_curve_properties(radius_ft=50.0, delta_deg=360.0)
        expected_circumference = 2 * math.pi * 50.0
        assert math.isclose(result["arc_length_ft"], expected_circumference, abs_tol=0.01)

    def test_negative_arc_length(self):
        """Negative arc length should raise ValueError."""
        with pytest.raises(ValueError, match="Arc length must be non-negative"):
            BearingConverter.calculate_curve_properties(radius_ft=50.0, arc_length_ft=-10.0)
