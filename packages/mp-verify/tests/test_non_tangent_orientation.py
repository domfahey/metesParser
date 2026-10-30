"""A non-tangent curve's course bearing never fixes its starting tangent.

Its orientation comes only from a stated radial bearing (start toward the centre)
or a chord bearing with sweep, identically in verification, plotting, topology,
checks and confidence. Tangent curves are unchanged.
"""

from __future__ import annotations

import itertools

import pytest
from mp_models import DeedCall
from mp_models.plot_request import PlotCall, PlotRequest
from mp_verify.checks import check_curve_consistency, check_parallelism
from mp_verify.closure import verify_closure
from mp_verify.confidence import score_call_quality
from mp_verify.plot import prepare_plot
from mp_verify.tangents import curve_tangents, has_determined_direction
from mp_verify.traverse import traverse_positions


def _curve(**overrides: object) -> DeedCall:
    data: dict[str, object] = {
        "course": 2,
        "direction_text": "recorded",
        "curve_dir": "right",
        "radius_ft": 300.0,
        "distance_ft": 104.72,
        "arc_length_ft": 104.72,
        "non_tangent": True,
    }
    data.update(overrides)
    return DeedCall(**data)  # type: ignore[arg-type]


def _line(course: int, azimuth: float, distance: float = 100.0) -> DeedCall:
    return DeedCall(
        course=course,
        direction_text="recorded",
        bearing_azimuth_deg_from_north=azimuth,
        distance_ft=distance,
    )


def _plot_end(call: DeedCall) -> tuple[float, float] | None:
    geometry = prepare_plot(PlotRequest(title="t", calls=(PlotCall(id="c", call=call),))).geometry
    ends = [p.end for p in geometry.primitives if p.call_id == "c"]
    return ends[0] if ends else None


def _verify_end(call: DeedCall) -> tuple[float, float] | None:
    points, positioned = traverse_positions([call])
    return (points[-1].x, points[-1].y) if positioned[0] else None


REPRO = _curve(bearing_azimuth_deg_from_north=45.0)


def test_non_tangent_course_bearing_is_not_a_tangent():
    assert curve_tangents(REPRO) is None
    assert not has_determined_direction(REPRO)
    assert score_call_quality(REPRO) == "low"


def test_repro_is_unpositioned_in_verify_and_plot():
    assert _plot_end(REPRO) is None
    assert _verify_end(REPRO) is None
    result = verify_closure([_line(1, 0.0), REPRO, _line(3, 180.0), _line(4, 270.0)])
    assert result.misclosure_available is False
    assert result.closure_passed is False


def test_radial_bearing_positions_identically():
    # Radius point bears S 45 E from the start; a right curve's tangent is radial - 90.
    call = _curve(radial_bearing="S 45°00'00\" E", bearing_azimuth_deg_from_north=10.0)
    tangents = curve_tangents(call)
    assert tangents is not None
    assert tangents[0] == pytest.approx(45.0)
    assert has_determined_direction(call)
    plotted, verified = _plot_end(call), _verify_end(call)
    assert plotted is not None and verified is not None
    assert plotted == pytest.approx(verified, abs=1e-9)
    # Equivalent tangent curve along 45 degrees ends at the same point.
    tangent = _curve(non_tangent=False, bearing_azimuth_deg_from_north=45.0)
    assert _verify_end(tangent) == pytest.approx(verified, abs=1e-9)


def test_left_radial_bearing_positions_identically():
    call = _curve(curve_dir="left", radial_bearing="N 45°00'00\" W")
    tangents = curve_tangents(call)
    assert tangents is not None and tangents[0] == pytest.approx(45.0)
    plotted, verified = _plot_end(call), _verify_end(call)
    assert plotted is not None and plotted == pytest.approx(verified, abs=1e-9)


def test_chord_and_sweep_position_identically():
    call = _curve(bearing_azimuth_deg_from_north=10.0, chord_bearing="N 55°00'00\" E")
    tangents = curve_tangents(call)
    assert tangents is not None and tangents[0] == pytest.approx(55.0 - 10.0, abs=1e-3)
    plotted, verified = _plot_end(call), _verify_end(call)
    assert plotted is not None and plotted == pytest.approx(verified, abs=1e-9)


def test_tangent_curve_unchanged():
    call = _curve(non_tangent=False, bearing_azimuth_deg_from_north=45.0)
    tangents = curve_tangents(call)
    assert tangents is not None and tangents[0] == 45.0
    assert has_determined_direction(call)
    plotted, verified = _plot_end(call), _verify_end(call)
    assert plotted is not None and plotted == pytest.approx(verified, abs=1e-9)


def test_parallelism_ignores_non_tangent_course_bearing():
    calls = [_line(1, 90.0), REPRO.model_copy(update={"along": "continuing the same line"})]
    assert check_parallelism(calls) == []


@pytest.mark.parametrize(
    ("bearing", "radial", "chord", "sweep", "curve_dir"),
    list(
        itertools.product(
            (None, 45.0),
            (None, "S 45°00'00\" E", "garbage"),
            (None, "N 55°00'00\" E"),
            ({"arc_length_ft": 104.72}, {"delta_deg": 20.0}),
            ("right", "left"),
        )
    ),
)
def test_verify_and_plot_position_the_same_non_tangent_cases(
    bearing, radial, chord, sweep, curve_dir
):
    call = _curve(
        **{
            "bearing_azimuth_deg_from_north": bearing,
            "radial_bearing": radial,
            "chord_bearing": chord,
            "curve_dir": curve_dir,
            "arc_length_ft": None,
            **sweep,
        }
    )
    plotted, verified = _plot_end(call), _verify_end(call)
    if not check_curve_consistency([call])[0]:
        # Verification rejects contradictory radial/chord evidence; plot never draws it.
        assert plotted is None
        return
    assert (plotted is None) == (verified is None)
    assert (plotted is not None) == has_determined_direction(call)
    if plotted is not None:
        assert plotted == pytest.approx(verified, abs=1e-9)
