"""A cardinal/chord conflict is indefinite everywhere, with or without the stored flag.

is_indefinite is not a CSV column, so a conflicting chord-only course that reaches
verification through CSV or a directly built DeedCall must be treated exactly like the
parsed one (is_indefinite=True) by confidence, plot, diagnostics, comparison and corridor.
"""

from __future__ import annotations

from mp_models import DeedCall
from mp_models.corridor import CorridorRequest
from mp_models.diagnostics import (
    ClosureDiagnosticRequest,
    DiagnosticCall,
    DiagnosticFrame,
    diagnostic_input_hash,
)
from mp_models.plot_request import PlotCall, PlotRequest
from mp_verify.comparison import _excluded_boundary
from mp_verify.confidence import score_call_quality
from mp_verify.corridor import analyze_corridor
from mp_verify.diagnostics import diagnose_closure
from mp_verify.plot import prepare_plot
from mp_verify.traverse import effective_indefinite


def conflict(**kw) -> DeedCall:
    base = {
        "course": 1,
        "direction_text": "northerly",
        "curve_dir": "right",
        "radius_ft": 200.0,
        "chord_bearing": "S 45° E",
        "chord_length_ft": 100.0,
        "distance_ft": 100.0,
    }
    base.update(kw)
    return DeedCall(**base)


def test_helper_flags_conflict_and_oversize_chord_but_not_agreeing_chord():
    assert effective_indefinite(conflict()) is True
    assert effective_indefinite(conflict(direction_text="southeasterly", chord_length_ft=500.0))
    assert effective_indefinite(conflict(direction_text="southeasterly")) is False
    assert effective_indefinite(conflict(direction_text="x", is_indefinite=True)) is True
    assert conflict().is_indefinite is False  # stored field is untouched


def test_confidence_low_for_unflagged_conflict():
    assert score_call_quality(conflict(is_indefinite=True)) == "low"
    assert score_call_quality(conflict()) == "low"
    assert score_call_quality(conflict(direction_text="southeasterly")) == "medium"


def test_comparison_excludes_unflagged_conflict():
    assert _excluded_boundary(conflict(is_indefinite=True)) is True
    assert _excluded_boundary(conflict()) is True
    assert _excluded_boundary(conflict(direction_text="southeasterly")) is False


def _diag(call: DeedCall):
    calls = tuple(DiagnosticCall(call_id=f"c{i}", call=call) for i in range(3))
    return diagnose_closure(
        ClosureDiagnosticRequest(
            request_id="r",
            input_id="i",
            input_sha256=diagnostic_input_hash(calls),
            calls=calls,
            frame=DiagnosticFrame(name="f"),
        )
    )


def _without_request(result) -> dict:
    data = result.model_dump(mode="json")
    for key in ("request", "request_sha256", "input_sha256"):
        data.pop(key, None)
    return data


def test_diagnostics_same_for_flagged_and_unflagged_conflict():
    flagged = _diag(conflict(is_indefinite=True))
    plain = _diag(conflict())
    assert "indefinite_call" in plain.model_dump_json()
    assert _without_request(plain) == _without_request(flagged)


def test_plot_identical_for_flagged_and_unflagged_conflict():
    def plot(call):
        request = PlotRequest(title="t", calls=(PlotCall(id="c", call=call),))
        geometry = prepare_plot(request).geometry.model_dump(mode="json")
        geometry.pop("geometry_hash", None)
        return geometry

    assert plot(conflict()) == plot(conflict(is_indefinite=True))


def _corridor(call: DeedCall):
    return analyze_corridor(
        CorridorRequest.model_validate(
            {
                "id": "easement",
                "centerline": {
                    "calculation_id": "centerline",
                    "title": "centerline",
                    "foot_definition": "international_ft",
                    "calls": [
                        {
                            "id": "road",
                            "source_reference": "deed page 3",
                            "call": call.model_dump(mode="json"),
                        }
                    ],
                },
                "widths": [
                    {
                        "id": "width",
                        "start": {"call_id": "road", "fraction": 0},
                        "end": {"call_id": "road", "fraction": 1},
                        "left_start": 10,
                        "left_end": 10,
                        "right_start": 10,
                        "right_end": 10,
                        "rule": "step",
                        "source_refs": [{"source_id": "deed", "page": 3, "quote": "w"}],
                    }
                ],
                "width_unit": "international_ft",
                "join": "bevel",
                "cap": "butt",
                "construction_source_refs": [{"source_id": "survey", "quote": "join and cap"}],
                "error_budget": {
                    "max_error": 0.01,
                    "unit": "international_ft",
                    "max_segments": 2048,
                },
            }
        )
    )


def test_corridor_rejects_unflagged_conflict_as_incomplete_like_flagged():
    flagged = _corridor(conflict(is_indefinite=True))
    plain = _corridor(conflict())
    assert flagged.availability == plain.availability == "incomplete"
    assert any("incomplete centerline geometry" in x for x in plain.limitations)
    assert plain.limitations == flagged.limitations
