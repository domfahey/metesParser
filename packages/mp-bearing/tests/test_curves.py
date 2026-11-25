"""Verify curve calculation functions."""

import math


def test_curve_properties_from_delta():
    from mp_bearing import calculate_curve_properties

    result = calculate_curve_properties(100.0, delta_deg=30.0)
    assert abs(result["arc_length_ft"] - 100.0 * math.radians(30.0)) < 0.01


def test_curve_properties_from_arc():
    from mp_bearing import calculate_curve_properties

    result = calculate_curve_properties(100.0, arc_length_ft=52.36)
    expected_delta_deg = math.degrees(52.36 / 100.0)
    expected_chord = 2 * 100.0 * math.sin(math.radians(expected_delta_deg) / 2)
    assert math.isclose(result["delta_deg"], expected_delta_deg, rel_tol=1e-9)
    assert math.isclose(result["chord_length_ft"], expected_chord, rel_tol=1e-9)


def test_missing_curve_elements():
    from mp_bearing import calculate_missing_curve_elements

    result = calculate_missing_curve_elements(radius_ft=100.0, delta_deg=30.0)
    assert math.isclose(result["arc_length_ft"], 100.0 * math.radians(30.0), rel_tol=1e-9)
    assert math.isclose(
        result["chord_length_ft"], 200.0 * math.sin(math.radians(15.0)), rel_tol=1e-9
    )


def test_chord_bearing():
    from mp_bearing import calculate_chord_bearing

    chord_az = calculate_chord_bearing(90.0, 30.0, "right")
    assert abs(chord_az - 105.0) < 0.01
