"""PR #60 round 13: curve-consistency tolerances follow the precision of stated values.

A fixed 0.01 ft / 1.5" tolerance rejected correctly rounded curves:

1. R=5000.00 with delta 10°00'00" (stated to the second) and arc 872.68: half a
   second of delta rounding moves R*delta by ~0.012 ft, so the arc must pass.
2. R=25.00, arc 17.45 (true 17.4533), tangent N 0° E, chord N 20°00'00" E: the
   arc's 0.005 ft rounding moves arc/R by ~41", so delta vs twice the deflection
   must pass.

Genuinely inconsistent curves (arc off by 1 ft at R=500; deflection off by 1°)
still fail, and the plot builder accepts exactly what verification accepts.
"""

from __future__ import annotations

import mp_models
import pytest
from mp_verify import checks as package_checks
from mp_verify import plot as package_plot
from mp_verify.closure import verify_closure as package_verify

from metesparser import models as monolith_models
from metesparser.closure_checker import ClosureChecker

IMPLS = {
    "package": (mp_models, package_verify),
    "monolith": (monolith_models, ClosureChecker.verify_closure),
}


def _large_radius(m, *, arc=872.68):
    return m.DeedCall(
        course=1,
        direction_text="N 0°00'00\" E",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=arc,
        curve_dir="right",
        radius_ft=5000.0,
        delta_deg=10.0,
        arc_length_ft=arc,
    )


def _small_radius(m, *, chord_bearing="N 20°00'00\" E", arc=17.45, chord=17.10):
    return m.DeedCall(
        course=1,
        direction_text="N 0°00'00\" E",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=arc,
        curve_dir="right",
        radius_ft=25.0,
        arc_length_ft=arc,
        chord_bearing=chord_bearing,
        chord_length_ft=chord,
    )


def _gross_arc(m):
    # R=500, delta 12°: R*delta = 104.72; the stated arc is 1 ft long.
    return m.DeedCall(
        course=1,
        direction_text="N 0°00'00\" E",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=105.72,
        curve_dir="right",
        radius_ft=500.0,
        delta_deg=12.0,
        arc_length_ft=105.72,
    )


ROUNDED = {
    "large radius delta to the second": _large_radius,
    "small radius arc to the hundredth": _small_radius,
}

GROSS = {
    "arc off by 1 ft at R=500": _gross_arc,
    "deflection off by 1 degree": lambda m: _small_radius(m, chord_bearing="N 21°00'00\" E"),
    "small radius arc off by 1 ft": lambda m: _small_radius(m, arc=18.45),
}


def _curve_check(result):
    return next(check for check in result.checks if check.name == "curve_consistency")


def _plots(call) -> bool:
    try:
        package_plot._arc(
            call, (0.0, 0.0), {"call_id": "c", "occurrence_id": None, "page_id": None}
        )
    except ValueError:
        return False
    return True


@pytest.mark.parametrize("impl", IMPLS)
@pytest.mark.parametrize("case", ROUNDED)
def test_rounded_curve_passes_verification(impl, case):
    m, verify = IMPLS[impl]
    result = verify([ROUNDED[case](m)])
    check = _curve_check(result)
    assert check.status == "passed", check.detail
    assert result.curve_consistency_passed is True


@pytest.mark.parametrize("case", ROUNDED)
def test_rounded_curve_passes_package_check_and_plots(case):
    call = ROUNDED[case](mp_models)
    assert package_checks.check_curve_consistency([call]) == (True, [])
    assert _plots(call)


@pytest.mark.parametrize("impl", IMPLS)
@pytest.mark.parametrize("case", GROSS)
def test_gross_curve_inconsistency_still_fails(impl, case):
    m, verify = IMPLS[impl]
    result = verify([GROSS[case](m)])
    assert _curve_check(result).status == "failed"
    assert result.curve_consistency_passed is False
    assert result.geometry_verified is False


@pytest.mark.parametrize("case", GROSS)
def test_gross_curve_inconsistency_does_not_plot(case):
    assert not _plots(GROSS[case](mp_models))
