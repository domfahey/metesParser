"""PR #60 round 40: one curve predicate; a radiusless spiral is a curved course."""

from __future__ import annotations

import mp_export.csv_writer as package_writer
import pytest
from mp_models import DeedCall
from mp_models.plot_request import PlotCall, PlotRequest
from mp_verify.closure import calculate_perimeter
from mp_verify.plot import prepare_plot
from mp_verify.tangents import is_curved_course

from metesparser.models import DeedCall as MonolithDeedCall

DEEDCALLS = [DeedCall, MonolithDeedCall]


def _spiral(cls=DeedCall, **kw):
    base = {
        "course": 1,
        "direction_text": "spiral curve",
        "distance_ft": 200.0,
        "curve_type": "spiral",
        "chord_bearing": "N 45°00'00\" E",
        "chord_length_ft": 199.5,
    }
    base.update(kw)
    return cls(**base)


@pytest.mark.parametrize("cls", DEEDCALLS)
def test_radiusless_spiral_is_curve_and_line_is_not(cls):
    assert _spiral(cls).is_curve() is True
    line = cls(course=1, direction_text="N", bearing_azimuth_deg_from_north=0.0, distance_ft=1.0)
    assert line.is_curve() is False


def test_is_curved_course_agrees_with_is_curve():
    for call in (
        _spiral(),
        DeedCall(course=1, direction_text="N", distance_ft=1.0),
        DeedCall(
            course=1,
            direction_text="c",
            distance_ft=1.0,
            radius_ft=10.0,
            curve_dir="left",
            delta_deg=5.0,
        ),
    ):
        assert is_curved_course(call) == call.is_curve()


def test_csv_row_spiral_with_curve_type_column_gets_no_legacy_note():
    row = package_writer._call_to_row(_spiral())
    call = package_writer._validate_row(row)
    assert call.curve_type == "spiral"
    assert package_writer.LEGACY_CURVE_NOTE not in (call.notes or "")


def test_legacy_row_without_curve_type_column_still_noted():
    call = DeedCall(
        course=1,
        direction_text="c",
        distance_ft=10.0,
        radius_ft=10.0,
        curve_dir="left",
        delta_deg=5.0,
    )
    row = package_writer._call_to_row(call)
    row.pop("curve_type")
    assert package_writer.LEGACY_CURVE_NOTE in (package_writer._validate_row(row).notes or "")


def test_plot_spiral_without_radius_is_positioned_by_chord_not_drawn():
    geometry = prepare_plot(
        PlotRequest(title="t", calls=(PlotCall(id="c1", call=_spiral()),))
    ).geometry
    assert geometry.primitives == ()
    assert "spiral" in geometry.unresolved[0].reason


def test_perimeter_uses_spiral_stated_length_not_circular_rules():
    assert calculate_perimeter([_spiral(arc_length_ft=205.0)]) == pytest.approx(205.0)
