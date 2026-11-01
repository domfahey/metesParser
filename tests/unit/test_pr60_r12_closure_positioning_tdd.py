"""PR #60 round 12: closure reasons follow traverse positioning, not mutated bearings.

Each behavior runs through the package and the compatibility monolith.
"""

from __future__ import annotations

import mp_models
import pytest
from mp_verify.closure import verify_closure as package_verify

from metesparser import models as monolith_models
from metesparser.closure_checker import ClosureChecker

IMPLS = {
    "package": (mp_models, package_verify),
    "monolith": (monolith_models, ClosureChecker.verify_closure),
}

INFEASIBLE_CHORD = "S 89°00'00\" E"
EAST_CHORD = "S 90°00'00\" E"


def _line(m, course, azimuth, distance=100.0):
    return m.DeedCall(
        course=course,
        direction_text="recorded",
        bearing_azimuth_deg_from_north=azimuth,
        distance_ft=distance,
    )


def _curve(m, *, tangent, radius, chord_bearing, chord_length):
    return m.DeedCall(
        course=2,
        direction_text="recorded",
        bearing_azimuth_deg_from_north=tangent,
        distance_ft=chord_length,
        curve_dir="right",
        radius_ft=radius,
        chord_bearing=chord_bearing,
        chord_length_ft=chord_length,
    )


def _deed(m, curve):
    return [_line(m, 1, 0.0), curve, _line(m, 3, 180.0), _line(m, 4, 270.0)]


def _checks(result):
    return {c.name: c for c in result.checks}


@pytest.mark.parametrize("impl", IMPLS)
def test_stated_bearing_unpositioned_course_reports_unpositioned_courses(impl):
    m, verify = IMPLS[impl]
    curve = _curve(m, tangent=90.0, radius=10.0, chord_bearing=INFEASIBLE_CHORD, chord_length=100.0)
    result = verify(_deed(m, curve))
    closure = _checks(result)["traverse_closure"]
    assert closure.status == "blocked"
    assert closure.reason == "unpositioned_courses"
    # The stated tangent is never erased to express that the course is unpositioned.
    assert not any("incomplete bearings" in w for w in result.warnings)
    assert result.misclosure_available is False
    assert result.geometry_verified is False


@pytest.mark.parametrize("impl", IMPLS)
def test_actually_missing_bearing_still_reports_missing_bearings(impl):
    m, verify = IMPLS[impl]
    calls = _deed(m, _line(m, 2, None))
    closure = _checks(verify(calls))["traverse_closure"]
    assert closure.status == "blocked"
    assert closure.reason == "missing_bearings"


@pytest.mark.parametrize("impl", IMPLS)
def test_chord_positioned_curve_without_tangent_is_not_missing_for_closure(impl):
    m, verify = IMPLS[impl]
    curve = _curve(m, tangent=None, radius=60.0, chord_bearing=EAST_CHORD, chord_length=100.0)
    result = verify(_deed(m, curve))
    checks = _checks(result)
    assert result.misclosure_available is True
    assert result.closure_passed is True
    assert checks["traverse_closure"].status == "passed"
    assert checks["traverse_closure"].reason == "within_tolerance"
    # The unstated delta still blocks the curve check, so the parcel is not eligible.
    assert checks["curve_consistency"].status == "blocked"
    assert "curve_delta_not_stated" in checks["curve_consistency"].reason
    assert result.geometry_verified is False


@pytest.mark.parametrize("impl", IMPLS)
def test_unpositioned_course_skips_area_calculation(impl):
    m, verify = IMPLS[impl]
    curve = _curve(m, tangent=90.0, radius=10.0, chord_bearing=INFEASIBLE_CHORD, chord_length=100.0)
    result = verify(_deed(m, curve))
    assert result.area_available is False
    assert result.area_sq_ft == 0.0
    assert not any("Cannot calculate area" in w for w in result.warnings)


@pytest.mark.parametrize("impl", IMPLS)
def test_missing_bearing_skips_area_calculation(impl):
    m, verify = IMPLS[impl]
    result = verify(_deed(m, _line(m, 2, None)))
    assert result.area_available is False
    assert not any("Cannot calculate area" in w for w in result.warnings)


@pytest.mark.parametrize("impl", IMPLS)
def test_chord_only_with_stated_tangent_is_not_called_ambiguous(impl):
    m, verify = IMPLS[impl]
    # Tangent east, right curve, chord S 60 E: deflection 30 deg, so chord = 2R sin 30 = R.
    curve = _curve(
        m, tangent=90.0, radius=100.0, chord_bearing="S 60°00'00\" E", chord_length=100.0
    )
    result = verify(_deed(m, curve))
    curve_check = _checks(result)["curve_consistency"]
    assert curve_check.status == "blocked"
    assert curve_check.reason == "curve_delta_not_stated"
    assert "ambiguous" not in curve_check.detail
    assert "not derived" in curve_check.detail


@pytest.mark.parametrize("impl", IMPLS)
def test_chord_only_without_tangent_is_still_called_ambiguous(impl):
    m, verify = IMPLS[impl]
    curve = _curve(m, tangent=None, radius=60.0, chord_bearing=EAST_CHORD, chord_length=100.0)
    detail = _checks(verify(_deed(m, curve)))["curve_consistency"].detail
    assert "minor or major arc ambiguous" in detail
