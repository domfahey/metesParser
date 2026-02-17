"""Verify curve calculation functions."""

import math


def test_curve_properties_from_delta():
    from mp_bearing import calculate_curve_properties

    result = calculate_curve_properties(100.0, delta_deg=30.0)
    assert abs(result["arc_length_ft"] - 100.0 * math.radians(30.0)) < 0.01


def test_curve_properties_from_arc():
    from mp_bearing import calculate_curve_properties

    result = calculate_curve_properties(100.0, arc_length_ft=52.36)
    assert result["delta_deg"] is not None
    assert result["chord_length_ft"] is not None


def test_missing_curve_elements():
    from mp_bearing import calculate_missing_curve_elements

    result = calculate_missing_curve_elements(radius_ft=100.0, delta_deg=30.0)
    assert "arc_length_ft" in result
    assert "chord_length_ft" in result


def test_chord_bearing():
    from mp_bearing import calculate_chord_bearing

    chord_az = calculate_chord_bearing(90.0, 30.0, "right")
    assert abs(chord_az - 105.0) < 0.01
