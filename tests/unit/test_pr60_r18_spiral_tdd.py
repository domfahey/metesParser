"""PR #60 round 18: a spiral is never a circular arc nor a straight line (package and monolith)."""

from __future__ import annotations

import math

import mp_models
import pytest
from mp_verify.closure import traverse_positions as package_traverse
from mp_verify.closure import verify_closure as package_verify

from metesparser import models as monolith_models
from metesparser.closure_checker import ClosureChecker

IMPLS = {
    "package": (mp_models, package_verify, package_traverse),
    "monolith": (monolith_models, ClosureChecker.verify_closure, ClosureChecker.traverse_positions),
}


def _square(m):
    sides = [("N", 0.0), ("E", 90.0), ("S", 180.0), ("W", 270.0)]
    return [
        m.DeedCall(
            course=i + 1, direction_text=t, bearing_azimuth_deg_from_north=az, distance_ft=100.0
        )
        for i, (t, az) in enumerate(sides)
    ]


@pytest.mark.parametrize("impl", IMPLS)
def test_radiusless_spiral_in_square_is_unpositioned_not_a_line(impl):
    m, verify, traverse = IMPLS[impl]
    square = _square(m)
    square[1] = m.DeedCall(
        course=2,
        direction_text="along a spiral curve North 90°00'00\" East",
        bearing_azimuth_deg_from_north=90.0,
        distance_ft=100.0,
        curve_type="spiral",
    )
    assert traverse(square)[1] == [True, False, True, True]
    result = verify(square)
    assert not result.area_available
    assert result.area_sq_ft == 0.0
    assert not result.perimeter_available
    closure = next(c for c in result.checks if c.name == "traverse_closure")
    assert closure.status == "blocked"
    angles = next(c for c in result.checks if c.name == "interior_angles")
    assert angles.status != "passed"


@pytest.mark.parametrize("impl", IMPLS)
def test_valid_spiral_curve_consistency_is_blocked_not_failed(impl):
    m, verify, _ = IMPLS[impl]
    spiral = m.DeedCall(
        course=1,
        direction_text="spiral",
        distance_ft=200.0,
        curve_type="spiral",
        curve_dir="right",
        radius_ft=1000.0,
        arc_length_ft=200.0,
        delta_deg=math.degrees(200.0 / 2000.0),
    )
    result = verify([spiral])
    curve = next(c for c in result.checks if c.name == "curve_consistency")
    assert curve.status == "blocked"
    assert "spiral_geometry_unverified" in curve.reason
    assert not any("arc length inconsistency" in w for w in result.warnings)
    assert not result.curve_consistency_passed


@pytest.mark.parametrize("impl", IMPLS)
def test_chord_stated_spiral_is_positioned_exactly_without_circular_feasibility(impl):
    m, verify, traverse = IMPLS[impl]
    spiral = m.DeedCall(
        course=1,
        direction_text="spiral",
        distance_ft=100.0,
        curve_type="spiral",
        curve_dir="right",
        radius_ft=40.0,
        chord_bearing="N 90°00'00\" E",
        chord_length_ft=100.0,
        bearing_azimuth_deg_from_north=80.0,
    )
    points, positioned = traverse([spiral])
    assert positioned == [True]
    assert (points[-1].x, points[-1].y) == pytest.approx((100.0, 0.0))
    result = verify([spiral])
    assert not result.area_available and not result.perimeter_available
    # Neither the chord-only nor the tangent/chord circular checks apply to a spiral.
    assert not any("delta/arc not stated" in w for w in result.warnings)
    assert not any("inconsistent" in w for w in result.warnings)
