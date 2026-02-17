"""Tests for mp_verify verification checks and confidence scoring."""

from __future__ import annotations


def test_confidence_scoring():
    """Confidence score for a well-formed closure result should be in [0, 1]."""
    from mp_models import ClosureResult, DeedCall
    from mp_verify.confidence import calculate_confidence_score

    result = ClosureResult(
        misclosure_x_ft=0.001,
        misclosure_y_ft=0.001,
        misclosure_ft=0.002,
        area_sq_ft=10000.0,
        area_acres=0.23,
        perimeter_ft=400.0,
        closure_passed=True,
        angle_check_passed=True,
        curve_consistency_passed=True,
    )
    calls = [
        DeedCall(
            course=i,
            direction_text="North",
            bearing_quadrant="N 00\u00b000' E",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=100.0,
        )
        for i in range(1, 5)
    ]
    score = calculate_confidence_score(result, calls)
    assert 0.0 <= score <= 1.0


def test_confidence_scoring_empty_calls():
    """Empty call list should return 0.0 confidence."""
    from mp_models import ClosureResult
    from mp_verify.confidence import calculate_confidence_score

    result = ClosureResult(
        misclosure_x_ft=0.0,
        misclosure_y_ft=0.0,
        misclosure_ft=0.0,
        area_sq_ft=0.0,
        area_acres=0.0,
        perimeter_ft=0.0,
        closure_passed=False,
        angle_check_passed=True,
        curve_consistency_passed=True,
    )
    score = calculate_confidence_score(result, [])
    assert score == 0.0


def test_score_call_quality_high():
    """A call with complete bearing and no flags should score high."""
    from mp_models import DeedCall
    from mp_verify.confidence import score_call_quality

    call = DeedCall(
        course=1,
        direction_text="N 45\u00b000' E",
        bearing_quadrant="N 45\u00b000' E",
        bearing_azimuth_deg_from_north=45.0,
        distance_ft=100.0,
    )
    assert score_call_quality(call) == "high"


def test_score_call_quality_low_incomplete():
    """A call without azimuth should score low."""
    from mp_models import DeedCall
    from mp_verify.confidence import score_call_quality

    call = DeedCall(
        course=1,
        direction_text="southwesterly",
        distance_ft=100.0,
    )
    assert score_call_quality(call) == "low"


def test_score_call_quality_medium_meander():
    """A meander call with complete bearing should score medium."""
    from mp_models import DeedCall
    from mp_verify.confidence import score_call_quality

    call = DeedCall(
        course=1,
        direction_text="N 45\u00b000' E",
        bearing_azimuth_deg_from_north=45.0,
        distance_ft=100.0,
        is_meander=True,
    )
    assert score_call_quality(call) == "medium"


def test_check_bearing_reversals_detects():
    """Adjacent courses ~180 degrees apart should be flagged."""
    from mp_models import DeedCall
    from mp_verify.checks import check_bearing_reversals

    calls = [
        DeedCall(
            course=1,
            direction_text="North",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=100.0,
        ),
        DeedCall(
            course=2,
            direction_text="South",
            bearing_azimuth_deg_from_north=178.0,
            distance_ft=100.0,
        ),
    ]
    warnings = check_bearing_reversals(calls)
    assert len(warnings) == 1
    assert "bearing reversal" in warnings[0].lower()


def test_check_bearing_reversals_no_false_positive():
    """Normal courses should not trigger reversal warnings."""
    from mp_models import DeedCall
    from mp_verify.checks import check_bearing_reversals

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
    warnings = check_bearing_reversals(calls)
    assert len(warnings) == 0


def test_check_distance_reasonableness_short():
    """Suspiciously short distances should be flagged."""
    from mp_models import DeedCall
    from mp_verify.checks import check_distance_reasonableness

    calls = [
        DeedCall(
            course=1,
            direction_text="North",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=0.1,
        ),
        DeedCall(
            course=2,
            direction_text="East",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=100.0,
        ),
    ]
    warnings = check_distance_reasonableness(calls)
    assert any("short" in w.lower() for w in warnings)


def test_check_curve_consistency_passes():
    """Consistent curve data should pass."""
    import math

    from mp_models import DeedCall
    from mp_verify.checks import check_curve_consistency

    radius = 100.0
    delta = 45.0
    arc = radius * math.radians(delta)
    calls = [
        DeedCall(
            course=1,
            direction_text="Curve",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=arc,
            curve_dir="right",
            radius_ft=radius,
            delta_deg=delta,
            arc_length_ft=arc,
        ),
    ]
    passed, warnings = check_curve_consistency(calls)
    assert passed
    assert len(warnings) == 0


def test_check_interior_angles_square():
    """A perfect square should pass interior angle check."""
    from mp_models import DeedCall
    from mp_verify.checks import check_interior_angles

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
    passed = check_interior_angles(calls, [])
    assert passed


def test_check_parallelism_no_warnings():
    """Normal calls without 'continuing' should not trigger warnings."""
    from mp_models import DeedCall
    from mp_verify.checks import check_parallelism

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
    warnings = check_parallelism(calls)
    assert len(warnings) == 0
