"""PR #60 round 27: verification and plotting agree on non-tangent curves.

A non-tangent curve's course bearing never fixes its starting tangent; only a
stated radial bearing (start toward the centre) or a chord bearing with sweep
does. Parsed through both entry points, verified through the monolith facade and
plotted through the plot facade, positioning must agree.
"""

from __future__ import annotations

import mp_models
import pytest
from mp_parse.calls import extract_single_call as package_single_call

from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker
from metesparser.plot import PlotCall, PlotRequest, prepare_plot

REPRO = (
    "THENCE N 45 deg E along a non-tangent curve to the right having a radius of 300.00 "
    "feet, a central angle of 20 deg 00'00\", an arc length of 104.72 feet"
)
RADIAL = (
    "THENCE along a non-tangent curve to the right, the radius point of which bears "
    "S 45°00'00\" E 300.00 feet, having a central angle of 20°00'00\", an arc length of "
    "104.72 feet"
)
CHORD = (
    "THENCE N 10 deg E along a non-tangent curve to the right having a radius of 300.00 "
    "feet, a central angle of 20°00'00\", an arc length of 104.72 feet, a chord bearing "
    "of N 55°00'00\" E"
)
TANGENT = (
    "THENCE N 45 deg E along a curve to the right having a radius of 300.00 "
    "feet, a central angle of 20°00'00\", an arc length of 104.72 feet"
)
PARSERS = {
    "package": package_single_call,
    "monolith": CallExtractor.extract_single_call,
}


@pytest.fixture(params=sorted(PARSERS))
def parse(request):
    return PARSERS[request.param]


def _line() -> mp_models.DeedCall:
    return mp_models.DeedCall(
        course=1, direction_text="N", bearing_azimuth_deg_from_north=0.0, distance_ft=100.0
    )


def _calls(parse, text):
    curve = parse(text, 2)
    return [_line(), mp_models.DeedCall.model_validate(curve.model_dump())]


def _plot_end(calls):
    geometry = prepare_plot(
        PlotRequest(title="t", calls=tuple(PlotCall(id=f"c{c.course}", call=c) for c in calls))
    ).geometry
    ends = [p.end for p in geometry.primitives if p.call_id == "c2"]
    return ends[0] if ends else None


def _verify(calls):
    return ClosureChecker.verify_closure(calls)


def test_repro_unpositioned_in_verify_and_plot(parse):
    calls = _calls(parse, REPRO)
    assert calls[1].non_tangent and calls[1].bearing_azimuth_deg_from_north == 45.0
    assert _plot_end(calls) is None
    result = _verify(calls)
    assert result.misclosure_available is False
    assert len(result.points) == 2
    assert ClosureChecker.score_call_quality(calls[1]) == "low"


def test_repro_confidence_does_not_count_it_determined(parse):
    calls = _calls(parse, REPRO)
    tangent = _calls(parse, TANGENT)
    assert _verify(calls).confidence_score < _verify(tangent).confidence_score


@pytest.mark.parametrize("text", [RADIAL, CHORD, TANGENT], ids=["radial", "chord", "tangent"])
def test_positioned_identically_in_verify_and_plot(parse, text):
    calls = _calls(parse, text)
    plotted = _plot_end(calls)
    result = _verify(calls)
    assert plotted is not None
    assert len(result.points) == 3
    end = result.points[2]
    assert plotted == pytest.approx((end.x, end.y), abs=1e-9)


def test_radial_curve_matches_equivalent_tangent_curve(parse):
    radial = _verify(_calls(parse, RADIAL)).points[2]
    tangent = _verify(_calls(parse, TANGENT)).points[2]
    assert (radial.x, radial.y) == pytest.approx((tangent.x, tangent.y), abs=1e-9)
