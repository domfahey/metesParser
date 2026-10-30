"""Curve checks tolerate rounding of stated values; verify and plot accept the same set."""

from __future__ import annotations

import math

import pytest
from mp_models import DeedCall
from mp_verify import plot
from mp_verify.checks import check_curve_consistency, tangent_chord_issue


def _plots(call: DeedCall) -> bool:
    try:
        plot._arc(call, (0.0, 0.0), {"call_id": "c", "occurrence_id": None, "page_id": None})
    except ValueError:
        return False
    return True


def test_delta_rounded_to_second_at_large_radius_passes():
    # True delta 10°00'00.45" -> arc 872.68; stated delta rounds to 10°00'00".
    call = DeedCall(
        course=1,
        direction_text="N 0°00'00\" E",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=872.68,
        curve_dir="right",
        radius_ft=5000.0,
        delta_deg=10.0,
        arc_length_ft=872.68,
    )
    assert check_curve_consistency([call]) == (True, [])
    assert _plots(call)


def test_arc_rounded_to_hundredth_at_small_radius_passes_tangent_chord():
    call = DeedCall(
        course=1,
        direction_text="N 0°00'00\" E",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=17.45,
        curve_dir="right",
        radius_ft=25.0,
        arc_length_ft=17.45,
        chord_bearing="N 20°00'00\" E",
        chord_length_ft=17.10,
    )
    assert tangent_chord_issue(call) is None
    assert check_curve_consistency([call]) == (True, [])
    assert _plots(call)


def test_arc_off_by_one_foot_at_radius_500_fails():
    call = DeedCall(
        course=1,
        direction_text="N 0°00'00\" E",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=105.72,
        curve_dir="right",
        radius_ft=500.0,
        delta_deg=12.0,
        arc_length_ft=105.72,
    )
    passed, warnings = check_curve_consistency([call])
    assert not passed
    assert "arc length inconsistency" in warnings[0]
    assert not _plots(call)


def test_deflection_off_by_one_degree_fails():
    call = DeedCall(
        course=1,
        direction_text="N 0°00'00\" E",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=17.45,
        curve_dir="right",
        radius_ft=25.0,
        arc_length_ft=17.45,
        chord_bearing="N 21°00'00\" E",
        chord_length_ft=17.10,
    )
    assert tangent_chord_issue(call) is not None
    assert not check_curve_consistency([call])[0]
    assert not _plots(call)


# --- Agreement sweep: verification and plotting accept exactly the same curves ----

RADII = [25.0, 150.0, 500.0, 5000.0, 50000.0]
DELTAS = [3.0, 40.0, 120.0]
LENGTH_ERRORS = [0.0, 0.004, 0.009, 0.015, 0.03, 0.1, 0.3, 1.0]
ANGLE_ERRORS_SEC = [0.0, 1.0, 10.0, 30.0, 60.0, 600.0, 3600.0]


def _dms(az: float) -> str:
    total = round(az * 3600)
    d, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"N {d}°{m:02d}'{s:02d}\" E"


def _call(radius, delta, *, arc_error=0.0, chord_error=0.0, angle_error_sec=0.0, stated_delta):
    arc = round(radius * math.radians(delta), 2) + arc_error
    chord = round(2 * radius * math.sin(math.radians(delta / 2)), 2) + chord_error
    chord_az = delta / 2 + angle_error_sec / 3600
    return DeedCall(
        course=1,
        direction_text="N 0°00'00\" E",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=arc,
        curve_dir="right",
        radius_ft=radius,
        delta_deg=delta if stated_delta else None,
        arc_length_ft=arc,
        chord_bearing=_dms(chord_az),
        chord_length_ft=chord,
    )


@pytest.mark.parametrize("stated_delta", [True, False])
@pytest.mark.parametrize("radius", RADII)
@pytest.mark.parametrize("delta", DELTAS)
def test_verification_and_plot_agree_across_sweep(radius, delta, stated_delta):
    for error in LENGTH_ERRORS:
        for kwargs in ({"arc_error": error}, {"chord_error": error}):
            call = _call(radius, delta, stated_delta=stated_delta, **kwargs)
            assert check_curve_consistency([call])[0] is _plots(call), (kwargs, call)
    for seconds in ANGLE_ERRORS_SEC:
        call = _call(radius, delta, angle_error_sec=seconds, stated_delta=stated_delta)
        assert check_curve_consistency([call])[0] is _plots(call), (seconds, call)


@pytest.mark.parametrize("stated_delta", [True, False])
@pytest.mark.parametrize("radius", RADII)
@pytest.mark.parametrize("delta", DELTAS)
def test_correctly_rounded_curves_pass_and_gross_errors_fail(radius, delta, stated_delta):
    assert check_curve_consistency([_call(radius, delta, stated_delta=stated_delta)])[0]
    assert not check_curve_consistency(
        [_call(radius, delta, arc_error=1.0, stated_delta=stated_delta)]
    )[0]
    assert not check_curve_consistency(
        [_call(radius, delta, chord_error=1.0, stated_delta=stated_delta)]
    )[0]
    assert not check_curve_consistency(
        [_call(radius, delta, angle_error_sec=3600.0, stated_delta=stated_delta)]
    )[0]
