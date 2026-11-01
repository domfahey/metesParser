"""PR #60 round 14: a tangent-less curve with a chord bearing is positioned like plot draws it."""

from __future__ import annotations

import math

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


def _curve(m, **kw):
    base = {
        "course": 1,
        "direction_text": "recorded",
        "distance_ft": 157.08,
        "curve_dir": "right",
        "radius_ft": 100.0,
        "chord_bearing": "S 45°00' E",
    }
    base.update(kw)
    return m.DeedCall(**base)


def _plot(call):
    plot_call = mp_models.DeedCall(**call.model_dump())
    return prepare_plot(PlotRequest(title="t", calls=(PlotCall(id="c1", call=plot_call),))).geometry


@pytest.mark.parametrize("impl", IMPLS)
@pytest.mark.parametrize(
    "extra",
    [
        {"delta_deg": 90.0, "chord_length_ft": 141.42},
        {"delta_deg": 90.0},
        {"arc_length_ft": 50.0 * math.pi},
    ],
)
def test_tangentless_curve_is_positioned_and_matches_plot(impl, extra):
    m, verify, traverse = IMPLS[impl]
    call = _curve(m, **extra)
    points, positioned = traverse([call])
    assert positioned == [True]
    geometry = _plot(call)
    assert not geometry.unresolved
    end = geometry.primitives[0].end
    assert (points[-1].x, points[-1].y) == pytest.approx(end, abs=1e-6)

    result = verify([call])
    assert result.misclosure_available is True
    assert result.misclosure_ft == pytest.approx(math.hypot(*end), abs=1e-6)
    assert result.perimeter_available is True


@pytest.mark.parametrize("impl", IMPLS)
def test_tangentless_curve_perimeter_uses_radius_times_delta(impl):
    m, verify, _ = IMPLS[impl]
    result = verify([_curve(m, delta_deg=90.0, distance_ft=141.42)])
    assert result.perimeter_ft == pytest.approx(50.0 * math.pi, abs=1e-6)


@pytest.mark.parametrize("impl", IMPLS)
def test_chord_bearing_only_stays_unpositioned(impl):
    m, verify, traverse = IMPLS[impl]
    # The model rejects this shape on validation; revision tooling can still hand it over.
    call = m.DeedCall.model_construct(
        **_curve(m, delta_deg=90.0).model_dump() | {"delta_deg": None}
    )
    assert traverse([call])[1] == [False]
    assert verify([call]).misclosure_available is False


@pytest.mark.parametrize("impl", IMPLS)
@pytest.mark.parametrize("extra", [{"delta_deg": 0.0}])
def test_unresolvable_sweep_stays_unpositioned_and_unplotted(impl, extra):
    m, _, traverse = IMPLS[impl]
    call = _curve(m, **extra)
    assert traverse([call])[1] == [False]
    assert not _plot(call).primitives
