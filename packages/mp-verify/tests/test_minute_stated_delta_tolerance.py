"""Whole-minute stated angles carry +/-30"; second-stated angles keep +/-0.5"."""

from __future__ import annotations

import math

import pytest
from mp_bearing import angle_half_unit_rad
from mp_models import DeedCall
from mp_verify import plot
from mp_verify.checks import check_curve_consistency

ORIGIN = {"call_id": "c", "occurrence_id": None, "page_id": None}


def _plots(call: DeedCall) -> bool:
    try:
        plot._arc(call, (0.0, 0.0), ORIGIN)
    except ValueError:
        return False
    return True


def _curve(radius: float, delta: float, arc: float) -> DeedCall:
    return DeedCall(
        course=1,
        direction_text="N 0°00'00\" E",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=arc,
        curve_dir="right",
        radius_ft=radius,
        delta_deg=delta,
        arc_length_ft=arc,
    )


def test_repro_radius_500_delta_12_34_arc_109_71_passes():
    call = _curve(500.0, 12 + 34 / 60, 109.71)
    assert check_curve_consistency([call]) == (True, [])
    assert _plots(call)


@pytest.mark.parametrize("radius", [25, 100, 500, 1200, 5000])
@pytest.mark.parametrize("minutes", [3 * 60, 7 * 60 + 41, 12 * 60 + 34, 45 * 60 + 17, 120 * 60])
def test_minute_stated_delta_sweep_passes_in_verify_and_plot(radius, minutes):
    delta = minutes / 60
    arc = round(radius * math.radians(delta), 2)
    call = _curve(float(radius), delta, arc)
    assert check_curve_consistency([call]) == (True, [])
    assert _plots(call)


def test_minute_rounding_worst_case_at_radius_5000_passes():
    # True delta 5°01'29.9" stated as 5°01'; arc from the true value.
    true_delta = 5 + 1 / 60 + 29.9 / 3600
    arc = round(5000 * math.radians(true_delta), 2)
    call = _curve(5000.0, 5 + 1 / 60, arc)
    assert check_curve_consistency([call]) == (True, [])
    assert _plots(call)


def test_second_stated_delta_keeps_tight_tolerance():
    # 12°34'10" at R=500: a 0.2 ft arc error exceeds +/-0.5" propagation (~0.01 ft).
    delta = 12 + 34 / 60 + 10 / 3600
    arc = round(500 * math.radians(delta), 2)
    assert check_curve_consistency([_curve(500.0, delta, arc)])[0]
    bad = _curve(500.0, delta, arc + 0.2)
    assert not check_curve_consistency([bad])[0]
    assert not _plots(bad)


def test_minute_stated_delta_still_rejects_gross_errors():
    delta = 12 + 34 / 60
    arc = round(500 * math.radians(delta), 2)
    assert not check_curve_consistency([_curve(500.0, delta, arc + 1.0)])[0]
    assert not _plots(_curve(500.0, delta, arc + 1.0))
    # 1 degree off in delta at R=500 is ~8.7 ft.
    assert not check_curve_consistency([_curve(500.0, delta + 1.0, arc)])[0]


def test_minute_stated_bearings_tangent_chord_pass_and_gross_fails():
    # R=500, delta 12°34': half 6°17'; tangent N0, chord N 6°17' E.
    delta = 12 + 34 / 60
    arc = round(500 * math.radians(delta), 2)
    chord = round(2 * 500 * math.sin(math.radians(delta) / 2), 2)

    def call(chord_bearing: str) -> DeedCall:
        return _curve(500.0, delta, arc).model_copy(
            update={"chord_bearing": chord_bearing, "chord_length_ft": chord}
        )

    assert check_curve_consistency([call("N 6°17'00\" E")]) == (True, [])
    assert _plots(call("N 6°17'00\" E"))
    assert not check_curve_consistency([call("N 7°17'00\" E")])[0]
    assert not _plots(call("N 7°17'00\" E"))


def test_angle_precision_inference():
    half_second = math.radians(0.5 / 3600)
    half_minute = math.radians(30 / 3600)
    assert angle_half_unit_rad(12 + 34 / 60) == half_minute
    # A whole degree is not widened to the minute rule.
    assert angle_half_unit_rad(12.0) == half_second
    assert angle_half_unit_rad(0.0) == half_second
    assert angle_half_unit_rad(12 + 34 / 60 + 10 / 3600) == half_second
    assert angle_half_unit_rad(12.5731) == half_second
