"""PR #60 round 22: parallelism around curves uses tangent-in/out, not stored bearings.

Each behavior runs through the package and the compatibility monolith.
"""

from __future__ import annotations

import math

import mp_models
import pytest
from mp_verify.closure import verify_closure as package_verify

from metesparser import models as monolith_models
from metesparser.closure_checker import ClosureChecker

IMPLS = {
    "package": (mp_models, package_verify),
    "monolith": (monolith_models, ClosureChecker.verify_closure),
}
ARC = 100.0 * math.pi / 2.0
CHORD = 2.0 * 100.0 * math.sin(math.radians(45.0))


def _line(m, course, azimuth, distance, **extra):
    return m.DeedCall(
        course=course,
        direction_text="recorded",
        bearing_azimuth_deg_from_north=azimuth,
        distance_ft=distance,
        **extra,
    )


def _curve(m, course, **extra):
    return m.DeedCall(
        course=course,
        direction_text="recorded",
        distance_ft=ARC,
        curve_dir="right",
        radius_ft=100.0,
        delta_deg=90.0,
        arc_length_ft=ARC,
        chord_length_ft=CHORD,
        **extra,
    )


def _parcel(m, curve, follow_az=90.0):
    return [
        _line(m, 1, 0.0, 100.0),
        curve,
        _line(m, 3, follow_az, 50.0, along="THENCE continuing along the same line"),
        _line(m, 4, 180.0, 200.0),
        _line(m, 5, 270.0, 150.0),
    ]


def _parallelism(result):
    return next(c for c in result.checks if c.name == "parallelism")


@pytest.mark.parametrize("impl", IMPLS)
def test_chord_positioned_curve_then_continuing_is_not_blocked(impl):
    m, verify = IMPLS[impl]
    curve = _curve(m, 2, chord_bearing="N 45° E")
    result = verify(_parcel(m, curve))
    assert result.misclosure_ft < 1e-6
    assert _parallelism(result).status == "passed"
    assert result.geometry_verified


@pytest.mark.parametrize("impl", IMPLS)
def test_tangent_curve_then_continuing_uses_tangent_out(impl):
    m, verify = IMPLS[impl]
    curve = _curve(m, 2, bearing_azimuth_deg_from_north=0.0)
    result = verify(_parcel(m, curve))
    assert _parallelism(result).status == "passed"
    assert result.geometry_verified


@pytest.mark.parametrize("impl", IMPLS)
def test_genuine_mismatch_after_curve_still_fails(impl):
    m, verify = IMPLS[impl]
    curve = _curve(m, 2, bearing_azimuth_deg_from_north=0.0)
    result = verify(_parcel(m, curve, follow_az=80.0))
    assert result.warnings
    assert _parallelism(result).status == "failed"


@pytest.mark.parametrize("impl", IMPLS)
def test_chord_only_curve_before_continuing_is_blocked(impl):
    m, verify = IMPLS[impl]
    curve = m.DeedCall(
        course=2,
        direction_text="recorded",
        distance_ft=CHORD,
        curve_dir="right",
        radius_ft=100.0,
        chord_bearing="N 45° E",
        chord_length_ft=CHORD,
        is_indefinite=True,
    )
    result = verify(_parcel(m, curve))
    assert _parallelism(result).status == "blocked"
