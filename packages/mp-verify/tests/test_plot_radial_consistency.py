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
    "radial_vs_chord": dict(
        non_tangent=True,
        radial_bearing="N 45°00'00\" W",
        chord_bearing="S 45°00'00\" E",
    ),
    "radial_vs_tangent": dict(
        bearing_azimuth_deg_from_north=0.0,
        radial_bearing="N 45°00'00\" W",
    ),
}
CONSISTENT = {
    "radial_chord_ok": dict(
        non_tangent=True,
        radial_bearing="N 90°00'00\" E",
        chord_bearing="N 45°00'00\" E",
    ),
    "radial_tangent_ok": dict(
        bearing_azimuth_deg_from_north=0.0,
        radial_bearing="N 90°00'00\" E",
    ),
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
