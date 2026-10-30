"""PR #60 round 16: exception loops and check fallbacks share traverse positioning.

A tangent-less curve fixed by chord bearing and delta is positioned on a main
traverse; an exception loop must accept the same curve rather than reporting an
incomplete bearing. ``build_verification_checks`` without a supplied traverse
outcome derives positioning from ``traverse_positions`` itself.
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


def _line(m, course, azimuth, distance, **extra):
    return m.DeedCall(
        course=course,
        direction_text="recorded",
        bearing_azimuth_deg_from_north=azimuth,
        distance_ft=distance,
        **extra,
    )


def _square(m):
    return [_line(m, i + 1, a, 100.0) for i, a in enumerate((0.0, 90.0, 180.0, 270.0))]


def _tangentless_curve(m, course, **extra):
    return m.DeedCall(
        course=course,
        direction_text="curve",
        distance_ft=14.14,
        curve_dir="right",
        radius_ft=10.0,
        delta_deg=90.0,
        chord_bearing="S 45°00' E",
        **extra,
    )


def _loop(m, start=1, **extra):
    """N 20; right curve R 10, delta 90, chord S 45 E (no tangent); S 10; W 10."""
    return [
        _line(m, start, 0.0, 20.0, **extra),
        _tangentless_curve(m, start + 1, **extra),
        _line(m, start + 2, 180.0, 10.0, **extra),
        _line(m, start + 3, 270.0, 10.0, **extra),
    ]


@pytest.mark.parametrize("impl", IMPLS)
def test_tangentless_curve_loop_has_area_as_main_tract(impl):
    m, verify = IMPLS[impl]
    result = verify(_loop(m))
    assert result.area_available
    assert result.area_sq_ft == pytest.approx(178.54, abs=0.01)


@pytest.mark.parametrize("impl", IMPLS)
def test_exception_loop_with_tangentless_curve_subtracts_area(impl):
    m, verify = IMPLS[impl]
    calls = _square(m) + _loop(m, start=5, is_exception=True)
    result = verify(calls)

    assert result.area_available
    assert result.area_sq_ft == pytest.approx(10000.0 - 178.54, abs=0.01)
    assert not any("incomplete bearing" in warning for warning in result.warnings)
    assert not any("Cannot calculate exception area" in w for w in result.warnings)
    # Positioning is internal: the exception call is not rewritten.
    assert calls[5].bearing_azimuth_deg_from_north is None


@pytest.mark.parametrize("impl", IMPLS)
def test_exception_loop_with_unpositioned_curve_stays_unavailable(impl):
    m, verify = IMPLS[impl]
    loop = _loop(m, start=5, is_exception=True)
    # No delta or arc: a tangent-less curve without a sweep cannot be positioned.
    loop[1] = loop[1].model_copy(update={"delta_deg": None})
    result = verify(_square(m) + loop)

    assert not result.area_available
    assert any("Exception course 6" in warning for warning in result.warnings)
    assert "Exception tract has 1 incomplete bearing(s)" in result.warnings
