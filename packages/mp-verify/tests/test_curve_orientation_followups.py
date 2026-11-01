"""Unreadable chords block both verify and plot; radial and chord cross-check; diagnostics orientation."""

from __future__ import annotations

import math

import pytest
from mp_models import DeedCall
from mp_models.diagnostics import (
    ClosureDiagnosticRequest,
    DiagnosticCall,
    DiagnosticFrame,
    DiagnosticSourceRef,
    diagnostic_input_hash,
)
from mp_models.plot_request import PlotCall, PlotRequest
from mp_verify.checks import check_curve_consistency
from mp_verify.closure import verify_closure
from mp_verify.diagnostics import diagnose_closure
from mp_verify.plot import prepare_plot
from mp_verify.traverse import traverse_positions


def _curve(**overrides: object) -> DeedCall:
    data: dict[str, object] = {
        "course": 2,
        "direction_text": "recorded",
        "curve_dir": "right",
        "radius_ft": 300.0,
        "delta_deg": 20.0,
        "arc_length_ft": 104.72,
        "distance_ft": 104.72,
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


def _plot_positioned(call: DeedCall) -> bool:
    geometry = prepare_plot(PlotRequest(title="t", calls=(PlotCall(id="c", call=call),))).geometry
    return any(p.call_id == "c" for p in geometry.primitives)


# Radial S 45 E => tangent-in 45; chord = 45 + 10 = 55 for a 20 degree right sweep.
RADIAL = "S 45°00'00\" E"
CHORD = "N 55°00'00\" E"


@pytest.mark.parametrize(
    "extra",
    [
        {"non_tangent": False, "bearing_azimuth_deg_from_north": 45.0},
        {"radial_bearing": RADIAL},
    ],
)
def test_unreadable_chord_is_unpositioned_in_verify_and_plot(extra):
    call = _curve(chord_bearing="garbage", **extra)
    _, positioned = traverse_positions([call])
    assert positioned == [False]
    assert not _plot_positioned(call)
    result = verify_closure([_line(1, 0.0), call, _line(3, 180.0), _line(4, 270.0)])
    assert result.misclosure_available is False
    assert any("chord bearing" in w for w in result.warnings)


def test_consistent_radial_and_chord_pass():
    call = _curve(radial_bearing=RADIAL, chord_bearing=CHORD)
    passed, warnings = check_curve_consistency([call])
    assert passed, warnings


def test_inconsistent_radial_and_chord_fail():
    call = _curve(radial_bearing=RADIAL, chord_bearing="N 80°00'00\" E")
    passed, warnings = check_curve_consistency([call])
    assert not passed
    assert "radial and chord" in warnings[-1]
    result = verify_closure([_line(1, 0.0), call, _line(3, 180.0), _line(4, 270.0)])
    assert result.curve_consistency_passed is False


def _diag(calls: list[DeedCall]):
    wrapped = tuple(
        DiagnosticCall(
            call_id=f"c{i}",
            call=c,
            source_refs=(DiagnosticSourceRef(source_id="d", occurrence_id="o", quote="q"),),
        )
        for i, c in enumerate(calls, 1)
    )
    return diagnose_closure(
        ClosureDiagnosticRequest(
            request_id="r",
            input_id="p",
            calls=wrapped,
            input_sha256=diagnostic_input_hash(wrapped),
            frame=DiagnosticFrame(name="Recorded"),
        )
    )


def test_diagnostics_accepts_radial_oriented_curve_and_matches_verify():
    calls = [_line(1, 0.0), _curve(radial_bearing=RADIAL), _line(3, 180.0), _line(4, 270.0)]
    result = _diag(calls)
    assert result.availability == "supported", result.limitations
    points, positioned = traverse_positions(calls)
    assert all(positioned)
    expected = math.hypot(points[-1].x - points[0].x, points[-1].y - points[0].y)
    assert result.residual is not None
    assert result.residual.magnitude_ft == pytest.approx(expected, abs=1e-6)
