"""Behavioral tests for mp_bearing.curves geometry, solvers, and tolerances."""

from __future__ import annotations

import math

import pytest
from mp_bearing import (
    calculate_chord_bearing,
    calculate_curve_properties,
    calculate_missing_curve_elements,
    compute_curve_endpoint,
)
from mp_bearing.curves import (
    CURVE_ELEMENT_TOLERANCE_FT,
    STATED_ANGLE_HALF_UNIT_RAD,
    STATED_LENGTH_HALF_UNIT_FT,
    STATED_MINUTE_HALF_UNIT_RAD,
    TANGENT_CHORD_TOLERANCE_CAP_DEG,
    TANGENT_CHORD_TOLERANCE_DEG,
    angle_half_unit_rad,
    arc_length_tolerance_ft,
    bearing_difference_uncertainty_rad,
    chord_length_tolerance_ft,
    deflection_chord_tolerance_ft,
    delta_uncertainty_rad,
    tangent_chord_deflection,
    tangent_chord_tolerance_deg,
)
from mp_models import Point


def test_curve_properties_from_delta() -> None:
    result = calculate_curve_properties(100.0, delta_deg=30.0)
    delta_rad = math.radians(30.0)
    assert result["radius_ft"] == 100.0
    assert result["delta_deg"] == 30.0
    assert result["delta_rad"] == pytest.approx(delta_rad)
    assert result["arc_length_ft"] == pytest.approx(100.0 * delta_rad)
    assert result["chord_length_ft"] == pytest.approx(200.0 * math.sin(delta_rad / 2.0))
    assert result["tangent_length_ft"] == pytest.approx(100.0 * math.tan(delta_rad / 2.0))
    assert result["external_distance_ft"] == pytest.approx(
        100.0 * (1.0 / math.cos(delta_rad / 2.0) - 1.0)
    )
    assert result["middle_ordinate_ft"] == pytest.approx(100.0 * (1.0 - math.cos(delta_rad / 2.0)))


def test_curve_properties_from_arc() -> None:
    arc = 100.0 * math.radians(30.0)
    result = calculate_curve_properties(100.0, arc_length_ft=arc)
    assert result["delta_deg"] == pytest.approx(30.0)
    assert result["delta_rad"] == pytest.approx(math.radians(30.0))
    assert result["arc_length_ft"] == pytest.approx(arc)
    assert result["chord_length_ft"] == pytest.approx(200.0 * math.sin(math.radians(15.0)))
    assert result["tangent_length_ft"] == pytest.approx(100.0 * math.tan(math.radians(15.0)))


def test_curve_properties_180_degree_semicircle_and_validation_errors() -> None:
    semi = calculate_curve_properties(50.0, delta_deg=180.0)
    assert semi["arc_length_ft"] == pytest.approx(50.0 * math.pi)
    assert semi["chord_length_ft"] == pytest.approx(100.0)
    assert math.isinf(semi["tangent_length_ft"])
    assert math.isinf(semi["external_distance_ft"])
    assert semi["middle_ordinate_ft"] == pytest.approx(50.0)

    for bad_r in (0.0, -10.0, math.nan, math.inf, True):
        with pytest.raises(ValueError, match="Radius must be positive"):
            calculate_curve_properties(bad_r, delta_deg=30.0)

    for bad_d in (-1.0, 360.1, math.nan, math.inf, False):
        with pytest.raises(ValueError, match="Delta angle must be 0-360"):
            calculate_curve_properties(100.0, delta_deg=bad_d)

    for bad_arc in (-0.1, math.nan, math.inf, True):
        with pytest.raises(ValueError, match="Arc length must be non-negative"):
            calculate_curve_properties(100.0, arc_length_ft=bad_arc)

    with pytest.raises(ValueError, match="exceeds 360"):
        calculate_curve_properties(10.0, arc_length_ft=100.0)

    with pytest.raises(ValueError, match="Must provide either delta_deg or arc_length_ft"):
        calculate_curve_properties(100.0)


def test_chord_bearing_directions_wraparound_and_errors() -> None:
    assert calculate_chord_bearing(90.0, 30.0, "right") == pytest.approx(105.0)
    assert calculate_chord_bearing(90.0, 30.0, "left") == pytest.approx(75.0)
    assert calculate_chord_bearing(350.0, 20.0, "right") == pytest.approx(0.0)
    assert calculate_chord_bearing(5.0, 20.0, "left") == pytest.approx(355.0)

    with pytest.raises(ValueError, match="curve_dir"):
        calculate_chord_bearing(90.0, 30.0, "straight")
    for bad in (math.nan, math.inf, True):
        with pytest.raises(ValueError, match="tangent_azimuth"):
            calculate_chord_bearing(bad, 30.0, "right")
        with pytest.raises(ValueError, match="delta_deg"):
            calculate_chord_bearing(90.0, bad, "right")


def test_compute_curve_endpoint_geometry_and_validation() -> None:
    start = Point(x=0.0, y=0.0)
    # Heading North (0 deg), 90 deg curve to the right with R=100 ends at (100, 100).
    end_right = compute_curve_endpoint(start, 0.0, 100.0, 90.0, "right")
    assert end_right.x == pytest.approx(100.0, abs=1e-9)
    assert end_right.y == pytest.approx(100.0, abs=1e-9)

    # Heading North (0 deg), 90 deg curve to the left with R=100 ends at (-100, 100).
    end_left = compute_curve_endpoint(start, 0.0, 100.0, 90.0, "left")
    assert end_left.x == pytest.approx(-100.0, abs=1e-9)
    assert end_left.y == pytest.approx(100.0, abs=1e-9)

    # Heading North (0 deg), 180 deg curve to the right with R=50 ends at (100, 0).
    end_semi = compute_curve_endpoint(start, 0.0, 50.0, 180.0, "right")
    assert end_semi.x == pytest.approx(100.0, abs=1e-9)
    assert end_semi.y == pytest.approx(0.0, abs=1e-9)

    for bad_r in (0.0, -5.0, math.nan, True):
        with pytest.raises(ValueError, match="Radius must be positive"):
            compute_curve_endpoint(start, 0.0, bad_r, 90.0, "right")


def test_missing_curve_elements_all_six_input_pairs_and_degree_of_curvature() -> None:
    radius = 200.0
    delta_deg = 60.0
    delta_rad = math.radians(delta_deg)
    arc = radius * delta_rad
    chord = 2.0 * radius * math.sin(delta_rad / 2.0)
    tangent = radius * math.tan(delta_rad / 2.0)
    external = radius * (1.0 / math.cos(delta_rad / 2.0) - 1.0)
    mid_ord = radius * (1.0 - math.cos(delta_rad / 2.0))

    cases = [
        {"radius_ft": radius, "delta_deg": delta_deg},
        {"radius_ft": radius, "arc_length_ft": arc},
        {"radius_ft": radius, "chord_length_ft": chord},
        {"arc_length_ft": arc, "delta_deg": delta_deg},
        {"chord_length_ft": chord, "delta_deg": delta_deg},
        {"arc_length_ft": arc, "chord_length_ft": chord},
        {"degree_of_curvature": 5729.578 / radius, "delta_deg": delta_deg},
        # Explicit radius_ft takes precedence when degree_of_curvature is also passed.
        {"degree_of_curvature": 10.0, "radius_ft": radius, "delta_deg": delta_deg},
    ]

    for kwargs in cases:
        result = calculate_missing_curve_elements(**kwargs)
        assert result["radius_ft"] == pytest.approx(radius, rel=1e-6)
        assert result["delta_deg"] == pytest.approx(delta_deg, rel=1e-6)
        assert result["arc_length_ft"] == pytest.approx(arc, rel=1e-6)
        assert result["chord_length_ft"] == pytest.approx(chord, rel=1e-6)
        assert result["tangent_length_ft"] == pytest.approx(tangent, rel=1e-6)
        assert result["external_distance_ft"] == pytest.approx(external, rel=1e-6)
        assert result["middle_ordinate_ft"] == pytest.approx(mid_ord, rel=1e-6)


def test_missing_curve_elements_major_arc_bisection_and_180_degree_boundary() -> None:
    # Major arc (delta = 240 deg > 180 deg) exercises bisection beyond small-angle approximations.
    radius = 150.0
    delta_deg = 240.0
    delta_rad = math.radians(delta_deg)
    arc = radius * delta_rad
    chord = 2.0 * radius * math.sin(delta_rad / 2.0)

    major = calculate_missing_curve_elements(arc_length_ft=arc, chord_length_ft=chord)
    assert major["delta_deg"] == pytest.approx(delta_deg, abs=1e-7)
    assert major["radius_ft"] == pytest.approx(radius, abs=1e-7)

    # Semicircle (delta = 180 deg) yields infinite tangent and external distance.
    semi = calculate_missing_curve_elements(radius_ft=100.0, delta_deg=180.0)
    assert math.isinf(semi["tangent_length_ft"])
    assert math.isinf(semi["external_distance_ft"])
    assert semi["chord_length_ft"] == pytest.approx(200.0)


def test_missing_curve_elements_validation_errors() -> None:
    with pytest.raises(ValueError, match="Need at least two curve elements"):
        calculate_missing_curve_elements(radius_ft=100.0)

    for bad_d in (math.nan, math.inf, True):
        with pytest.raises(ValueError, match="Delta angle must be finite"):
            calculate_missing_curve_elements(radius_ft=100.0, delta_deg=bad_d)
    with pytest.raises(ValueError, match="non-zero"):
        calculate_missing_curve_elements(radius_ft=100.0, delta_deg=0.0)
    for out_of_range_d in (-5.0, 361.0):
        with pytest.raises(ValueError, match="0-360 degrees"):
            calculate_missing_curve_elements(radius_ft=100.0, delta_deg=out_of_range_d)

    for bad_r in (0.0, -10.0, math.nan, True):
        with pytest.raises(ValueError, match="Radius must be positive"):
            calculate_missing_curve_elements(radius_ft=bad_r, delta_deg=30.0)
    for bad_arc in (0.0, -5.0, math.nan, False):
        with pytest.raises(ValueError, match="Arc length must be positive"):
            calculate_missing_curve_elements(radius_ft=100.0, arc_length_ft=bad_arc)
    for bad_chord in (-1.0, math.nan, math.inf, True):
        with pytest.raises(ValueError, match="Chord length must be non-negative"):
            calculate_missing_curve_elements(radius_ft=100.0, chord_length_ft=bad_chord)

    with pytest.raises(ValueError, match="exceeds 360"):
        calculate_missing_curve_elements(radius_ft=10.0, arc_length_ft=100.0)
    with pytest.raises(ValueError, match="Chord length must be positive"):
        calculate_missing_curve_elements(radius_ft=100.0, chord_length_ft=0.0)
    with pytest.raises(ValueError, match="exceeds diameter"):
        calculate_missing_curve_elements(radius_ft=100.0, chord_length_ft=205.0)
    with pytest.raises(ValueError, match="zero chord length or 360-degree"):
        calculate_missing_curve_elements(chord_length_ft=0.0, delta_deg=30.0)
    with pytest.raises(ValueError, match="zero chord length or 360-degree"):
        calculate_missing_curve_elements(chord_length_ft=10.0, delta_deg=360.0)
    with pytest.raises(ValueError, match="must be less than arc"):
        calculate_missing_curve_elements(arc_length_ft=50.0, chord_length_ft=50.0)


def test_curve_rounding_uncertainties_tolerances_and_deflection() -> None:
    # Whole-minute (non-degree) angle gets +-30", whole degree or seconds gets +-0.5".
    assert angle_half_unit_rad(12.0 + 34.0 / 60.0) == pytest.approx(STATED_MINUTE_HALF_UNIT_RAD)
    assert angle_half_unit_rad(12.0) == pytest.approx(STATED_ANGLE_HALF_UNIT_RAD)
    assert angle_half_unit_rad(12.0 + 34.0 / 60.0 + 15.0 / 3600.0) == pytest.approx(
        STATED_ANGLE_HALF_UNIT_RAD
    )

    assert delta_uncertainty_rad() == pytest.approx(STATED_ANGLE_HALF_UNIT_RAD)
    assert delta_uncertainty_rad(delta_deg=12.5) == pytest.approx(STATED_MINUTE_HALF_UNIT_RAD)
    assert delta_uncertainty_rad(arc_length_ft=100.0, radius_ft=200.0) == pytest.approx(
        STATED_LENGTH_HALF_UNIT_FT / 200.0 + 100.0 * STATED_LENGTH_HALF_UNIT_FT / (200.0**2)
    )

    assert bearing_difference_uncertainty_rad(45.0, 12.5) == pytest.approx(
        STATED_ANGLE_HALF_UNIT_RAD + STATED_MINUTE_HALF_UNIT_RAD
    )

    # Small curve hits the 0.01 ft floor; large minute-stated curve scales with R*d(delta).
    assert arc_length_tolerance_ft(10.0, 10.0) == CURVE_ELEMENT_TOLERANCE_FT
    expected_large_arc_tol = (
        5000.0 * STATED_MINUTE_HALF_UNIT_RAD
        + STATED_LENGTH_HALF_UNIT_FT * math.radians(12.5)
        + STATED_LENGTH_HALF_UNIT_FT
    )
    assert arc_length_tolerance_ft(5000.0, 12.5) == pytest.approx(expected_large_arc_tol)

    assert chord_length_tolerance_ft(10.0, 10.0, STATED_ANGLE_HALF_UNIT_RAD) == (
        CURVE_ELEMENT_TOLERANCE_FT
    )
    expected_large_chord_tol = (
        5000.0 * math.cos(math.radians(12.5) / 2.0) * STATED_MINUTE_HALF_UNIT_RAD
        + 2.0 * math.sin(math.radians(12.5) / 2.0) * STATED_LENGTH_HALF_UNIT_FT
        + STATED_LENGTH_HALF_UNIT_FT
    )
    assert chord_length_tolerance_ft(5000.0, 12.5, STATED_MINUTE_HALF_UNIT_RAD) == pytest.approx(
        expected_large_chord_tol
    )
    assert deflection_chord_tolerance_ft(5000.0, 10.0) == pytest.approx(
        chord_length_tolerance_ft(5000.0, 20.0, 4.0 * STATED_ANGLE_HALF_UNIT_RAD)
    )

    # Tangent-to-chord tolerance: default deflection error, mid-range propagation, and 0.1 deg cap.
    assert tangent_chord_tolerance_deg(STATED_ANGLE_HALF_UNIT_RAD) == pytest.approx(
        TANGENT_CHORD_TOLERANCE_DEG
    )
    assert tangent_chord_tolerance_deg(
        STATED_MINUTE_HALF_UNIT_RAD, deflection_error_rad=2.0 * STATED_MINUTE_HALF_UNIT_RAD
    ) == pytest.approx(math.degrees(2.5 * STATED_MINUTE_HALF_UNIT_RAD))
    assert tangent_chord_tolerance_deg(1.0) == TANGENT_CHORD_TOLERANCE_CAP_DEG

    # Deflection sign: positive toward curve_dir, negative when chord is on wrong side.
    assert tangent_chord_deflection(350.0, 10.0, "right") == pytest.approx(20.0)
    assert tangent_chord_deflection(350.0, 10.0, "left") == pytest.approx(-20.0)
    assert tangent_chord_deflection(10.0, 350.0, "left") == pytest.approx(20.0)
