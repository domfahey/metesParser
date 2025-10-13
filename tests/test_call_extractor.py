"""Tests for call_extractor.py - Parsing deed calls."""

import math

from metesparser.call_extractor import CallExtractor


class TestCallExtractorCurves:
    """Ensure curve calls are preserved even without explicit bearings."""

    def test_curve_without_bearing_preserved(self):
        """Curve lacking a quadrant bearing should still produce a call."""
        call_text = (
            "along a curve to the right having a radius of 50.00 feet "
            "and an arc length of 78.54 feet to an iron pin"
        )
        call = CallExtractor.extract_single_call(call_text, course=1)

        assert call is not None
        assert call.direction_text.startswith("along a curve")
        assert call.bearing_quadrant is None
        assert math.isclose(call.distance_ft, 78.54, abs_tol=0.01)
        assert math.isclose(call.arc_length_ft or 0.0, 78.54, abs_tol=0.01)
        assert math.isclose(call.radius_ft or 0.0, 50.0, abs_tol=0.01)
        assert call.to == "an iron pin"
        assert call.along.startswith("a curve to the right")
        assert call.notes == "incomplete bearing"

    def test_curve_without_arc_length_uses_computed_value(self):
        """When only radius and delta are supplied, compute the arc length."""
        call_text = (
            "along a curve to the left having a radius of 100.00 feet "
            "and a delta angle of 45°00' to a point"
        )
        call = CallExtractor.extract_single_call(call_text, course=1)

        assert call is not None
        expected_arc = 100.0 * math.radians(45.0)
        assert math.isclose(call.distance_ft, expected_arc, abs_tol=0.01)
        assert math.isclose(call.arc_length_ft or 0.0, expected_arc, abs_tol=0.01)
        assert call.notes == "incomplete bearing"
