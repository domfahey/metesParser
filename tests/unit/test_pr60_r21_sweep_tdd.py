"""PR #60 round 21: curved-first interior angles, one sweep rule in the traverse, one chord delta."""

from __future__ import annotations

import mp_models
import pytest
from mp_verify import tangents
from mp_verify.closure import traverse_positions as package_traverse
from mp_verify.closure import verify_closure as package_verify

from metesparser import models as monolith_models
from metesparser.closure_checker import ClosureChecker

IMPLS = {
    "package": (mp_models, package_verify, package_traverse),
    "monolith": (monolith_models, ClosureChecker.verify_closure, ClosureChecker.traverse_positions),
}


def _line(m, course, azimuth):
    return m.DeedCall(
        course=course,
        direction_text="recorded",
        bearing_azimuth_deg_from_north=azimuth,
        distance_ft=100.0,
    )


def _spiral(m):
    return m.DeedCall(
        course=2,
        direction_text="spiral",
        curve_type="spiral",
        curve_dir="right",
        radius_ft=100.0,
        distance_ft=100.0,
        chord_length_ft=100.0,
        chord_bearing="N 90°00'00\" E",
    )


def _chord_only(m):
    return m.DeedCall(
        course=2,
        direction_text="curve",
        curve_dir="right",
        radius_ft=100.0,
        distance_ft=100.0,
        chord_length_ft=100.0,
        chord_bearing="N 90°00'00\" E",
    )


def _parcel(m, curved):
    return [_line(m, 1, 0.0), curved, _line(m, 3, 180.0), _line(m, 4, 270.0)]


@pytest.mark.parametrize("impl", IMPLS)
@pytest.mark.parametrize("make", [_spiral, _chord_only])
def test_chord_positioned_curve_is_not_incomplete_bearing(impl, make):
    m, verify, _ = IMPLS[impl]
    result = verify(_parcel(m, make(m)))
    checks = {c.name: c for c in result.checks}
    assert checks["interior_angles"].status == "not_applicable"
    assert checks["interior_angles"].reason == "curved_boundary"
    assert not any("incomplete bearings" in w for w in result.warnings)


@pytest.mark.parametrize("impl", IMPLS)
def test_unpositioned_cardinal_course_still_warns(impl):
    m, verify, _ = IMPLS[impl]
    calls = _parcel(m, _spiral(m))
    calls[2] = m.DeedCall(course=3, direction_text="southerly", distance_ft=100.0)
    result = verify(calls)
    assert any("1 call(s) have incomplete bearings" in w for w in result.warnings)


@pytest.mark.parametrize("impl", IMPLS)
@pytest.mark.parametrize(
    "extra",
    [{"delta_deg": 400.0}, {"delta_deg": -30.0}, {"delta_deg": None, "arc_length_ft": 700.0}],
)
def test_tangent_curve_with_invalid_sweep_is_unpositioned(impl, extra):
    m, _, traverse_fn = IMPLS[impl]
    call = m.DeedCall(
        course=1,
        direction_text="curve",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=50.0,
        curve_dir="right",
        radius_ft=100.0,
        delta_deg=30.0,
    ).model_copy(update=extra)  # bypass field validation: sweep is rechecked downstream
    _, positioned = traverse_fn([call])
    assert positioned == [False]


def test_tangent_curve_with_valid_sweep_is_positioned():
    call = mp_models.DeedCall(
        course=1,
        direction_text="curve",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=50.0,
        curve_dir="right",
        radius_ft=100.0,
        delta_deg=30.0,
    )
    assert package_traverse([call])[1] == [True]


def test_chord_delta_helper_is_shared_and_reuses_parsed_azimuth():
    call = mp_models.DeedCall(
        course=1,
        direction_text="curve",
        curve_dir="right",
        radius_ft=100.0,
        distance_ft=50.0,
        delta_deg=30.0,
        chord_bearing="N 45°00'00\" E",
    )
    assert tangents.chord_positioned_delta(call) == 30.0
    assert tangents.chord_delta(call, 45.0) == 30.0
    assert tangents.chord_delta(call, None) is None
