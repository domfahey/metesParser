"""Spirals are never circular arcs nor straight lines, in verification and plotting alike.

A spiral is positioned only by a stated chord bearing and chord length (exact
endpoint, nothing drawn, area/perimeter not determined); otherwise unpositioned.
"""

from __future__ import annotations

import math

import pytest
from mp_models import DeedCall
from mp_models.plot import plot_point_of_beginning
from mp_models.plot_request import PlotCall, PlotRequest
from mp_verify.closure import verify_closure
from mp_verify.plot import prepare_plot
from mp_verify.tangents import is_spiral
from mp_verify.traverse import traverse_positions

SIDES = [("N", 0.0), ("E", 90.0), ("S", 180.0), ("W", 270.0)]


def _square() -> list[DeedCall]:
    return [
        DeedCall(
            course=i + 1, direction_text=t, bearing_azimuth_deg_from_north=az, distance_ft=100.0
        )
        for i, (t, az) in enumerate(SIDES)
    ]


def _radiusless_spiral(course: int = 1, azimuth: float = 10.0) -> DeedCall:
    # 'thence along a spiral curve North 10°00'00" East 100.00 feet': no radius, no
    # direction, so no stated chord - the bearing/distance are not the spiral's chord.
    return DeedCall(
        course=course,
        direction_text="along a spiral curve North 10°00'00\" East",
        bearing_azimuth_deg_from_north=azimuth,
        distance_ft=100.0,
        curve_type="spiral",
    )


def _chord_spiral(course: int = 1, **kw: object) -> DeedCall:
    base: dict[str, object] = {
        "course": course,
        "direction_text": "spiral",
        "distance_ft": 200.0,
        "curve_type": "spiral",
        "curve_dir": "right",
        "radius_ft": 1000.0,
        "arc_length_ft": 200.0,
        "chord_bearing": "N 90°00'00\" E",
        "chord_length_ft": 100.0,
    }
    base.update(kw)
    return DeedCall(**base)


def _plot(calls: list[DeedCall]):
    return prepare_plot(
        PlotRequest(
            title="t",
            calls=tuple(PlotCall(id=f"c{i}", call=c) for i, c in enumerate(calls, 1)),
        )
    ).geometry


def test_radiusless_spiral_is_spiral_and_never_a_straight_line():
    square = _square()
    square[1] = _radiusless_spiral(course=2, azimuth=90.0)
    assert is_spiral(square[1]) and not square[1].is_curve()
    assert traverse_positions(square)[1] == [True, False, True, True]
    result = verify_closure(square)
    assert not result.area_available and result.area_sq_ft == 0.0
    assert not result.perimeter_available
    assert not result.misclosure_available
    assert any("spiral" in w and "cannot be positioned" in w for w in result.warnings)


def test_valid_spiral_is_not_failed_by_circular_formulas():
    # L = 200, R = 1000: a spiral's delta is L/(2R), not the circular L/R.
    spiral = _chord_spiral(
        delta_deg=math.degrees(200.0 / 2000.0), chord_bearing=None, chord_length_ft=None
    )
    result = verify_closure([spiral])
    curve = next(c for c in result.checks if c.name == "curve_consistency")
    assert curve.status == "blocked"
    assert "spiral_geometry_unverified" in curve.reason
    assert not any("inconsistency" in w for w in result.warnings)
    assert not result.curve_consistency_passed


def test_spiral_block_does_not_hide_a_failed_circular_curve():
    bad_arc = DeedCall(
        course=2,
        direction_text="arc",
        distance_ft=50.0,
        bearing_azimuth_deg_from_north=0.0,
        curve_dir="right",
        radius_ft=100.0,
        delta_deg=30.0,
        arc_length_ft=99.0,
    )
    result = verify_closure([_chord_spiral(), bad_arc])
    curve = next(c for c in result.checks if c.name == "curve_consistency")
    assert curve.status == "failed"


def test_plot_positions_chord_stated_spiral_without_drawing_it():
    square = _square()
    square[1] = _chord_spiral(course=2)
    geometry = _plot(square)
    assert [p.call_id for p in geometry.primitives] == ["c1", "c3", "c4"]
    assert [u.call_id for u in geometry.unresolved] == ["c2"]
    assert "spiral" in geometry.unresolved[0].reason
    assert geometry.primitives[1].start == pytest.approx((100.0, 100.0))
    assert geometry.chains == (("c1",), ("c3", "c4"))
    assert geometry.area_sq_ft is None and geometry.perimeter_ft is None


def test_plot_leading_chord_stated_spiral_keeps_point_of_beginning():
    square = _square()
    square[0] = _chord_spiral(course=1, chord_bearing="N 00°00'00\" E")
    geometry = _plot(square)
    assert geometry.primitives[0].start == pytest.approx((0.0, 100.0))
    assert plot_point_of_beginning(geometry) == pytest.approx((0.0, 0.0))


@pytest.mark.parametrize(
    "spiral",
    [
        _radiusless_spiral(course=2, azimuth=90.0),
        _chord_spiral(course=2, chord_length_ft=None, delta_deg=5.0),
        _chord_spiral(course=2, chord_bearing="garbage"),
    ],
    ids=["radiusless", "no-chord-length", "bad-chord-bearing"],
)
def test_plot_unpositioned_spiral_stops_chain(spiral):
    square = _square()
    square[1] = spiral
    geometry = _plot(square)
    assert [p.call_id for p in geometry.primitives] == ["c1"]
    assert [u.call_id for u in geometry.unresolved] == ["c2", "c3", "c4"]


SPIRAL_CASES = {
    "radiusless": _radiusless_spiral(),
    "radiusless-chord-bearing": _radiusless_spiral().model_copy(
        update={"chord_bearing": "N 10°00'00\" E"}
    ),
    "no-chord": _chord_spiral(chord_bearing=None, chord_length_ft=None),
    "chord-bearing-only": _chord_spiral(chord_length_ft=None),
    "bad-chord-bearing": _chord_spiral(chord_bearing="garbage"),
    "chord-stated": _chord_spiral(),
    "chord-only-no-arc": _chord_spiral(arc_length_ft=None),
    "chord-beyond-circular-diameter": _chord_spiral(radius_ft=40.0),
    "with-tangent": _chord_spiral(bearing_azimuth_deg_from_north=80.0),
}


@pytest.mark.parametrize("name", SPIRAL_CASES)
def test_verify_and_plot_position_exactly_the_same_spirals(name):
    spiral = SPIRAL_CASES[name]
    points, positioned = traverse_positions([spiral])
    geometry = _plot([spiral])
    assert not geometry.primitives  # a spiral is never drawn
    plotted = geometry.unresolved[0].reason.endswith("positioned by stated chord only")
    assert positioned == [plotted]
    if plotted:
        # Same exact chord endpoint: the following course starts there.
        follower = DeedCall(
            course=2, direction_text="N", bearing_azimuth_deg_from_north=0.0, distance_ft=1.0
        )
        start = _plot([spiral, follower]).primitives[0].start
        assert start == pytest.approx((points[-1].x, points[-1].y))
        result = verify_closure([spiral])
        assert not result.area_available and not result.perimeter_available
    assert positioned == [
        name
        in {"chord-stated", "chord-only-no-arc", "chord-beyond-circular-diameter", "with-tangent"}
    ]
