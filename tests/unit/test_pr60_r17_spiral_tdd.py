"""PR #60 round 17: spirals are never positioned by circular geometry; one feasibility rule."""

from __future__ import annotations

import mp_models
import pytest
from mp_models.plot_request import PlotCall, PlotRequest
from mp_verify.closure import traverse_positions as package_traverse
from mp_verify.closure import verify_closure as package_verify
from mp_verify.plot import prepare_plot

from metesparser import models as monolith_models
from metesparser.closure_checker import ClosureChecker

IMPLS = {
    "package": (mp_models, package_verify, package_traverse),
    "monolith": (monolith_models, ClosureChecker.verify_closure, ClosureChecker.traverse_positions),
}


def _spiral(m, **kw):
    base = {
        "course": 1,
        "direction_text": "spiral",
        "distance_ft": 50.0,
        "curve_type": "spiral",
        "curve_dir": "right",
        "radius_ft": 100.0,
        "arc_length_ft": 50.0,
        "chord_bearing": "N 45°00'00\" E",
    }
    base.update(kw)
    return m.DeedCall(**base)


@pytest.mark.parametrize("impl", IMPLS)
def test_spiral_chord_bearing_only_is_unpositioned(impl):
    m, verify, traverse = IMPLS[impl]
    call = _spiral(m)
    _, positioned = traverse([call])
    assert positioned == [False]
    result = verify([call])
    assert not result.area_available
    assert not result.perimeter_available


@pytest.mark.parametrize("impl", IMPLS)
def test_spiral_with_stated_chord_is_positioned_but_area_perimeter_undetermined(impl):
    m, verify, traverse = IMPLS[impl]
    call = _spiral(m, chord_length_ft=49.5)
    points, positioned = traverse([call])
    assert positioned == [True]
    assert (points[-1].x, points[-1].y) == pytest.approx((49.5 * 0.70710678,) * 2, abs=1e-3)
    result = verify([call])
    assert not result.area_available
    assert not result.perimeter_available


@pytest.mark.parametrize("impl", IMPLS)
def test_spiral_never_adds_circular_segment_to_area(impl):
    m, verify, _ = IMPLS[impl]
    sides = [("N", 0.0), ("E", 90.0), ("S", 180.0), ("W", 270.0)]
    square = [
        m.DeedCall(
            course=i + 1, direction_text=t, bearing_azimuth_deg_from_north=az, distance_ft=100.0
        )
        for i, (t, az) in enumerate(sides)
    ]
    assert verify(square).area_sq_ft == pytest.approx(10000.0)
    square[1] = _spiral(
        m,
        chord_bearing="N 90°00'00\" E",
        chord_length_ft=100.0,
        arc_length_ft=110.0,
        bearing_azimuth_deg_from_north=90.0,
    )
    assert not verify(square).area_available


def test_plot_refuses_spiral_and_predicate_is_shared():
    from mp_verify.tangents import is_circular_curve

    call = _spiral(mp_models, chord_length_ft=49.5)
    geometry = prepare_plot(PlotRequest(title="t", calls=(PlotCall(id="c1", call=call),))).geometry
    assert geometry.unresolved
    assert not is_circular_curve(call)
    assert is_circular_curve(_spiral(mp_models, curve_type="simple"))


def test_chord_feasibility_uses_absolute_radius():
    # DeedCall normalises radius to be positive (a negative one needs curve_dir "left"
    # and is flipped), so bypass validation to pin the shared helper's abs() contract.
    from mp_verify.tangents import chord_is_feasible

    call = mp_models.DeedCall.model_construct(radius_ft=-100.0, chord_length_ft=150.0)
    assert chord_is_feasible(call)
    call = mp_models.DeedCall.model_construct(radius_ft=-100.0, chord_length_ft=250.0)
    assert not chord_is_feasible(call)
