"""A cardinal/chord conflict is indefinite everywhere, with or without the stored flag.

is_indefinite is not a CSV column, so a conflicting chord-only course that reaches
verification through CSV or a directly built DeedCall must be treated exactly like the
parsed one (is_indefinite=True) by confidence, plot, diagnostics, comparison and corridor.
"""

from __future__ import annotations

import pytest
from mp_models import DeedCall
from mp_models.comparison import (
    BearingBasis,
    ComparisonDescription,
    ComparisonPair,
    ComparisonRequest,
    ComparisonSelection,
    ComparisonTolerance,
)
from mp_models.corridor import CorridorRequest
from mp_models.diagnostics import (
    ClosureDiagnosticRequest,
    DiagnosticCall,
    DiagnosticFrame,
    diagnostic_input_hash,
)
from mp_models.plot_request import PlotCall, PlotRequest
from mp_verify.comparison import compare_descriptions
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


def _compare_pair(call: DeedCall):
    basis = BearingBasis(label="Grid", identity="NAD83", source_references=("deed p.1",))
    tol = ComparisonTolerance(
        length=0.5,
        displacement=0.5,
        position=0.5,
        linear_unit="international_ft",
        bearing_deg=0.5,
        source_references=("review",),
    )
    req = ComparisonRequest(
        left=ComparisonDescription(
            id="left",
            plot=PlotRequest(
                title="L",
                calculation_id="l",
                foot_definition="international_ft",
                calls=(PlotCall(id="c1", call=call),),
            ),
            bearing_basis=basis,
        ),
        right=ComparisonDescription(
            id="right",
            plot=PlotRequest(
                title="R",
                calculation_id="r",
                foot_definition="international_ft",
                calls=(
                    PlotCall(
                        id="c2",
                        call=DeedCall(
                            course=1,
                            direction_text="S 45° E",
                            bearing_azimuth_deg_from_north=135.0,
                            distance_ft=100.0,
                        ),
                    ),
                ),
            ),
            bearing_basis=basis,
        ),
        pairs=(
            ComparisonPair(
                id="p1",
                left=ComparisonSelection(call_ids=("c1",), direction="forward"),
                right=ComparisonSelection(call_ids=("c2",), direction="forward"),
            ),
        ),
        tolerances=tol,
    )
    return compare_descriptions(req).pairs[0]


def test_comparison_excludes_unflagged_conflict():
    flagged = _compare_pair(conflict(is_indefinite=True))
    plain = _compare_pair(conflict())
    agreeing = _compare_pair(conflict(direction_text="southeasterly"))
    assert flagged.displacement.outcome == plain.displacement.outcome == "not_comparable"
    assert "indefinite boundary unsupported" in flagged.displacement.reason
    assert plain.displacement.reason == flagged.displacement.reason
    # Agreeing cardinal is not excluded as indefinite (fails on missing sweep instead).
    assert "indefinite boundary unsupported" not in agreeing.displacement.reason


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


def _north_line(course: int = 2) -> DeedCall:
    return DeedCall(
        course=course,
        direction_text="N 0° E",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=50.0,
    )


def test_plot_identical_for_flagged_and_unflagged_conflict():
    def plot(call: DeedCall):
        request = PlotRequest(
            title="t",
            calls=(PlotCall(id="c1", call=call), PlotCall(id="c2", call=_north_line())),
        )
        return prepare_plot(request).geometry

    dumped = []
    for call in (conflict(), conflict(is_indefinite=True)):
        geometry = plot(call)
        assert geometry.completeness == "unresolved"
        assert geometry.primitives == ()
        assert len(geometry.unresolved) == 2
        assert geometry.unresolved[0].call_id == "c1"
        assert geometry.unresolved[0].positioned is False
        assert "incomplete bearing" in geometry.unresolved[0].reason
        assert geometry.unresolved[1].call_id == "c2"
        assert geometry.unresolved[1].positioned is False
        assert geometry.unresolved[1].reason == "unpositioned after unresolved displacement"
        data = geometry.model_dump(mode="json")
        data.pop("geometry_hash", None)
        dumped.append(data)

    assert dumped[0] == dumped[1]


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(
            DeedCall(
                course=1,
                direction_text="recorded",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=157.08,
                curve_dir="right",
                radius_ft=100.0,
                delta_deg=90.0,
                is_indefinite=True,
            ),
            id="arc-flagged-indefinite",
        ),
        pytest.param(
            DeedCall(
                course=1,
                direction_text="northerly",
                bearing_azimuth_deg_from_north=None,
                distance_ft=104.72,
                curve_dir="right",
                radius_ft=200.0,
                delta_deg=30.0,
                chord_bearing="S 45° E",
                chord_length_ft=100.0,
                is_indefinite=False,
            ),
            id="arc-cardinal-chord-conflict",
        ),
        pytest.param(
            DeedCall(
                course=1,
                direction_text="northerly",
                distance_ft=100.0,
                curve_type="spiral",
                chord_bearing="S 45° E",
                chord_length_ft=100.0,
                is_indefinite=False,
            ),
            id="spiral-conflict-unflagged",
        ),
        pytest.param(
            DeedCall(
                course=1,
                direction_text="northerly",
                distance_ft=100.0,
                curve_type="spiral",
                chord_bearing="S 45° E",
                chord_length_ft=100.0,
                is_indefinite=True,
            ),
            id="spiral-conflict-flagged",
        ),
        pytest.param(
            DeedCall(
                course=1,
                direction_text="recorded",
                bearing_azimuth_deg_from_north=90.0,
                distance_ft=100.0,
                is_indefinite=True,
            ),
            id="line-flagged-indefinite",
        ),
    ],
)
def test_plot_rejects_effectively_indefinite_arc_spiral_and_line(call: DeedCall):
    geometry = prepare_plot(PlotRequest(title="t", calls=(PlotCall(id="c1", call=call),))).geometry
    assert geometry.completeness == "unresolved"
    assert geometry.primitives == ()
    assert geometry.unresolved[0].positioned is False
    assert "incomplete bearing" in geometry.unresolved[0].reason


def test_plot_keeps_non_conflicting_legacy_chord_only_positioned():
    call = DeedCall(
        course=1,
        direction_text="curve",
        distance_ft=50.0,
        curve_dir="right",
        radius_ft=100.0,
        chord_bearing="N 90°00' E",
        chord_length_ft=50.0,
        is_indefinite=True,
    )
    geometry = prepare_plot(
        PlotRequest(
            title="t",
            calls=(PlotCall(id="c1", call=call), PlotCall(id="c2", call=_north_line())),
        )
    ).geometry
    assert geometry.unresolved[0].positioned is True
    assert "positioned by chord only" in geometry.unresolved[0].reason
    assert len(geometry.primitives) == 1


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
