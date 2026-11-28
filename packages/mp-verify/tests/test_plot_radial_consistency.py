"""Plot and closure diagnosis apply the same radial/chord/tangent checks as verification."""

from __future__ import annotations

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
from mp_verify.diagnostics import diagnose_closure
from mp_verify.plot import prepare_plot

INCONSISTENT = {
    # Non-tangent right curve R=100, delta=90: chord S45E implies tangent 0, so the
    # radial must be N90W; N45W contradicts it.
    "radial_vs_chord": {
        "non_tangent": True,
        "radial_bearing": "N 45°00'00\" W",
        "chord_bearing": "S 45°00'00\" E",
    },
    "radial_vs_tangent": {
        "bearing_azimuth_deg_from_north": 0.0,
        "radial_bearing": "N 45°00'00\" W",
    },
}
CONSISTENT = {
    "radial_chord_ok": {
        "non_tangent": True,
        "radial_bearing": "N 90°00'00\" E",
        "chord_bearing": "N 45°00'00\" E",
    },
    "radial_tangent_ok": {
        "bearing_azimuth_deg_from_north": 0.0,
        "radial_bearing": "N 90°00'00\" E",
    },
}


def _curve(**extra: object) -> DeedCall:
    return DeedCall(
        course=1,
        direction_text="recorded",
        curve_dir="right",
        radius_ft=100.0,
        delta_deg=90.0,
        distance_ft=157.08,
        **extra,  # type: ignore[arg-type]
    )


def _plot(call: DeedCall):
    return prepare_plot(PlotRequest(title="t", calls=(PlotCall(id="c", call=call),))).geometry


def _diagnose(call: DeedCall):
    ref = (DiagnosticSourceRef(source_id="d", occurrence_id="o", quote="q"),)
    calls = (
        DiagnosticCall(call_id="c1", call=call, source_refs=ref),
        DiagnosticCall(
            call_id="c2",
            call=DeedCall(
                course=2,
                direction_text="r",
                bearing_azimuth_deg_from_north=90.0,
                distance_ft=10.0,
            ),
            source_refs=ref,
        ),
    )
    return diagnose_closure(
        ClosureDiagnosticRequest(
            request_id="r",
            input_id="i",
            calls=calls,
            input_sha256=diagnostic_input_hash(calls),
            frame=DiagnosticFrame(name="f"),
        )
    )


def _passed(call: DeedCall) -> bool:
    return check_curve_consistency([call])[0]


@pytest.mark.parametrize("name", INCONSISTENT)
def test_inconsistent_radial_is_rejected_by_verify_plot_and_diagnosis(name):
    call = _curve(**INCONSISTENT[name])
    assert _passed(call) is False
    geometry = _plot(call)
    assert not geometry.primitives
    assert {u.call_id for u in geometry.unresolved} == {"c"}
    assert _diagnose(call).availability == "unsupported"


@pytest.mark.parametrize("name", CONSISTENT)
def test_consistent_radial_is_accepted_everywhere(name):
    call = _curve(**CONSISTENT[name])
    assert _passed(call) is True
    assert [p.call_id for p in _plot(call).primitives] == ["c"]
    assert _diagnose(call).availability != "unsupported"


def _two_call_plot(call: DeedCall):
    line = DeedCall(
        course=2,
        direction_text="N 0° E",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=50.0,
    )
    return prepare_plot(
        PlotRequest(
            title="t",
            calls=(PlotCall(id="c1", call=call), PlotCall(id="c2", call=line)),
        )
    ).geometry


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(
            DeedCall(
                course=1,
                direction_text="recorded",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
                curve_dir="right",
                radius_ft=100.0,
                chord_bearing="S 45° E",
                chord_length_ft=100.0,
                is_indefinite=False,
            ),
            id="tangent_chord_issue",
        ),
        pytest.param(
            DeedCall(
                course=1,
                direction_text="recorded",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
                curve_dir="right",
                radius_ft=100.0,
                radial_bearing="N 45°00'00\" W",
                chord_bearing="N 30°00'00\" E",
                chord_length_ft=100.0,
                is_indefinite=False,
            ),
            id="radial_tangent_issue",
        ),
    ],
)
def test_chord_only_curve_with_inconsistent_tangent_or_radial_is_unpositioned(call: DeedCall):
    assert check_curve_consistency([call])[0] is False
    geometry = _two_call_plot(call)
    assert geometry.primitives == ()
    assert geometry.unresolved[0].positioned is False
    assert "inconsistent" in geometry.unresolved[0].reason
    assert geometry.unresolved[1].reason == "unpositioned after unresolved displacement"


def test_consistent_chord_only_curve_remains_chord_positioned():
    call = DeedCall(
        course=1,
        direction_text="recorded",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=100.0,
        curve_dir="right",
        radius_ft=100.0,
        radial_bearing="N 90°00'00\" E",
        chord_bearing="N 30°00'00\" E",
        chord_length_ft=100.0,
        is_indefinite=False,
    )
    assert check_curve_consistency([call])[0] is True
    geometry = _two_call_plot(call)
    assert geometry.unresolved[0].positioned is True
    assert "positioned by chord only" in geometry.unresolved[0].reason
    assert len(geometry.primitives) == 1


def test_spiral_chord_skips_circular_orientation_checks():
    call = DeedCall(
        course=1,
        direction_text="recorded",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=100.0,
        curve_type="spiral",
        curve_dir="right",
        radius_ft=100.0,
        radial_bearing="N 45°00'00\" W",
        chord_bearing="S 45°00'00\" E",
        chord_length_ft=100.0,
        is_indefinite=False,
    )
    geometry = _two_call_plot(call)
    assert geometry.unresolved[0].positioned is True
    assert "spiral" in geometry.unresolved[0].reason
    assert len(geometry.primitives) == 1
