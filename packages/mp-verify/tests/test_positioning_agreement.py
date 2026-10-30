"""Closure and plot agree on which courses cannot be positioned."""

from mp_models import DeedCall
from mp_models.plot_request import PlotCall, PlotRequest
from mp_verify.closure import verify_closure
from mp_verify.plot import prepare_plot


def _line(course, azimuth):
    return DeedCall(
        course=course,
        direction_text="recorded",
        bearing_azimuth_deg_from_north=azimuth,
        distance_ft=100.0,
    )


def _deed():
    curve = DeedCall(
        course=2,
        direction_text="recorded",
        distance_ft=450.0,
        curve_dir="right",
        radius_ft=200.0,
        chord_length_ft=450.0,
        chord_bearing="N 90° E",
    )
    return [_line(1, 0.0), curve, _line(3, 180.0), _line(4, 270.0), _line(5, 0.0), _line(6, 180.0)]


def test_plot_and_closure_both_stop_at_the_infeasible_chord():
    calls = _deed()
    geometry = prepare_plot(
        PlotRequest(title="t", calls=tuple(PlotCall(id=f"c{c.course}", call=c) for c in calls))
    ).geometry
    plotted = {p.call_id for p in geometry.primitives}
    unresolved = {u.call_id for u in geometry.unresolved}
    assert plotted == {"c1"}
    assert unresolved == {"c2", "c3", "c4", "c5", "c6"}

    result = verify_closure(calls)
    assert result.misclosure_available is False
    assert result.closure_passed is False
    text = " ".join(result.warnings)
    assert "Course 2" in text and "3, 4, 5, 6" in text
