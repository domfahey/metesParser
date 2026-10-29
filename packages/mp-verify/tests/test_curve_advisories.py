"""Independent circular-arc fixtures for deterministic advisory engines."""

import copy
import math

import pytest
from mp_models.comparison import ComparisonRequest
from mp_models.deed_call import DeedCall
from mp_models.diagnostics import (
    ClosureDiagnosticRequest,
    DiagnosticCall,
    DiagnosticFrame,
    DiagnosticSourceRef,
    QuantizationAssumptions,
    diagnostic_input_hash,
)
from mp_verify.comparison import compare_descriptions
from mp_verify.diagnostics import diagnose_closure


def curve(radius=40, sweep=90, tangent=0, direction="right", **extra):
    sign = 1 if direction == "right" else -1
    chord = (tangent + sign * sweep / 2) % 360
    # Numeric azimuth is deliberately stored as a quadrant string in chord evidence.
    ns, ew = (
        ("N", "E")
        if chord <= 90
        else ("S", "E")
        if chord <= 180
        else ("S", "W")
        if chord <= 270
        else ("N", "W")
    )
    angle = (
        chord
        if chord <= 90
        else 180 - chord
        if chord <= 180
        else chord - 180
        if chord <= 270
        else 360 - chord
    )
    ticks = round(angle * 3600 * 100000000)
    degree, ticks = divmod(ticks, 3600 * 100000000)
    minute, ticks = divmod(ticks, 60 * 100000000)
    second = ticks / 100000000
    return {
        "course": 1,
        "direction_text": "verbatim circular boundary",
        "distance_ft": radius * math.radians(sweep),
        "curve_dir": direction,
        "radius_ft": radius,
        "delta_deg": sweep,
        "arc_length_ft": radius * math.radians(sweep),
        "chord_length_ft": 2 * radius * math.sin(math.radians(sweep) / 2),
        "chord_bearing": f"{ns} {degree}°{minute}' {second:.10f}\" {ew}",
        "bearing_azimuth_deg_from_north": tangent % 360,
        **extra,
    }


def diagnostic(fields, precision=None):
    calls = (
        DiagnosticCall(
            call_id="arc-source",
            call=DeedCall(**fields),
            source_refs=(DiagnosticSourceRef(source_id="deed", page=3, quote="  actual curve  "),),
        ),
        DiagnosticCall(
            call_id="west",
            call=DeedCall(
                course=2, direction_text="W", distance_ft=40, bearing_azimuth_deg_from_north=270
            ),
        ),
        DiagnosticCall(
            call_id="south",
            call=DeedCall(
                course=3, direction_text="S", distance_ft=39, bearing_azimuth_deg_from_north=180
            ),
        ),
    )
    return ClosureDiagnosticRequest(
        request_id="curve-review",
        input_id="deed",
        input_sha256=diagnostic_input_hash(calls),
        calls=calls,
        frame=DiagnosticFrame(name="recorded"),
        precision=precision,
    )


def comparison(left, right, reverse=False):
    def description(id, fields):
        return {
            "id": id,
            "plot": {
                "calculation_id": id,
                "title": id,
                "foot_definition": "international_ft",
                "calls": [{"id": id + "-curve", "quote": "  source " + id + "  ", "call": fields}],
            },
            "bearing_basis": {
                "label": "grid",
                "identity": "survey-grid",
                "source_references": ["recorded survey"],
            },
        }

    return {
        "left": description("old", left),
        "right": description("new", right),
        "pairs": [
            {
                "id": "curve",
                "left": {"call_ids": ["old-curve"], "direction": "forward"},
                "right": {
                    "call_ids": ["new-curve"],
                    "direction": "reverse" if reverse else "forward",
                },
            }
        ],
        "tolerances": {
            "length": 0.001,
            "displacement": 0.001,
            "position": 0.001,
            "linear_unit": "international_ft",
            "bearing_deg": 0.001,
            "radius": 0.001,
            "sweep_deg": 0.001,
            "source_references": ["review criteria"],
        },
    }


def compare(data):
    return compare_descriptions(ComparisonRequest.model_validate(data))


def test_quarter_circle_residual_is_analytic_and_sources_are_preserved():
    req = diagnostic(curve())
    before = req.model_dump_json()
    result = diagnose_closure(req)
    assert result.availability == "supported"
    assert (result.residual.east_ft, result.residual.north_ft) == pytest.approx((0, 1), abs=1e-10)
    row = result.sensitivities[0]
    assert row.distance_derivative is None and row.angle_derivative_per_radian is None
    assert [p.parameter for p in row.curve_parameters] == [
        "radius_ft",
        "sweep_radian",
        "start_tangent_radian",
    ]
    assert row.curve_parameters[0].derivative.east == pytest.approx(1)
    assert row.curve_parameters[0].derivative.north == pytest.approx(1)
    assert row.curve_parameters[1].derivative.east == pytest.approx(40)
    assert row.curve_parameters[1].derivative.north == pytest.approx(0, abs=1e-10)
    assert row.curve_parameters[2].derivative.east == pytest.approx(40)
    assert row.curve_parameters[2].derivative.north == pytest.approx(-40)
    assert row.source_refs == req.calls[0].source_refs
    assert row.source_refs[0].quote == "  actual curve  "
    assert req.model_dump_json() == before and result.verified_export_eligible is False


@pytest.mark.parametrize("direction", ["right", "left"])
@pytest.mark.parametrize("sweep", [30, 180, 270, 359.9])
def test_independent_curve_parameters_match_regenerated_evidence_finite_differences(
    direction, sweep
):
    basis = [40.0, math.radians(sweep), math.radians(23.7)]

    def endpoint(values):
        # Rebuild ALL redundant length and angle observations from the independent basis.
        request = diagnostic(
            curve(values[0], math.degrees(values[1]), math.degrees(values[2]), direction)
        )
        result = diagnose_closure(request)
        assert result.availability == "supported"
        return result.residual.east_ft, result.residual.north_ft

    row = diagnose_closure(diagnostic(curve(40, sweep, 23.7, direction))).sensitivities[0]
    assert len(row.curve_parameters) == 3
    for i, parameter in enumerate(row.curve_parameters):
        h = 1e-5
        plus, minus = basis.copy(), basis.copy()
        plus[i] += h
        minus[i] -= h
        ep, em = endpoint(plus), endpoint(minus)
        assert parameter.derivative.east == pytest.approx((ep[0] - em[0]) / (2 * h), abs=2e-7)
        assert parameter.derivative.north == pytest.approx((ep[1] - em[1]) / (2 * h), abs=2e-7)
        assert parameter.fixed_parameters and parameter.constraint


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"arc_length_ft": 12}, "inconsistent"),
        ({"chord_length_ft": 12}, "inconsistent"),
        ({"radius_ft": 41}, "inconsistent"),
        ({"bearing_azimuth_deg_from_north": 15}, "inconsistent"),
        ({"curve_type": "spiral"}, "spiral"),
        ({"delta_deg": 360, "arc_length_ft": 80 * math.pi, "chord_length_ft": 0}, "full"),
        ({"delta_deg": None, "arc_length_ft": 240 * math.pi}, "360"),
        ({"chord_bearing": None, "bearing_azimuth_deg_from_north": None}, "orientation"),
    ],
)
def test_invalid_curve_evidence_is_not_preferred_or_straightened(change, reason):
    fields = curve(**change)
    diagnosed = diagnose_closure(diagnostic(fields))
    assert diagnosed.availability in {"unsupported", "incomplete"}
    assert diagnosed.residual is None and diagnosed.sensitivities == ()
    assert reason in " ".join(diagnosed.limitations).lower()
    compared = compare(comparison(fields, curve())).pairs[0]
    assert compared.displacement.outcome == "not_comparable"
    assert reason in compared.displacement.reason.lower()


def test_partial_curve_evidence_and_missing_radius_are_not_lines():
    fields = {
        "course": 1,
        "direction_text": "curve?",
        "distance_ft": 40,
        "bearing_azimuth_deg_from_north": 90,
        "chord_bearing": "N 90 E",
    }
    result = diagnose_closure(diagnostic(fields))
    assert result.availability == "unsupported" and result.residual is None
    assert "curve" in " ".join(result.limitations)


def test_line_precision_does_not_claim_curve_rounding_bound():
    precision = QuantizationAssumptions(
        distance_increment_ft=0.01,
        bearing_increment_arcsec=1,
        evidence="line-only source increments",
    )
    result = diagnose_closure(diagnostic(curve(), precision))
    assert result.availability == "supported" and result.quantization is None
    assert "curve precision" in " ".join(result.limitations).lower()


@pytest.mark.parametrize("sweep", [90, 180, 270])
def test_arc_comparison_uses_actual_arc_length_and_analytic_displacement(sweep):
    data = comparison(curve(sweep=sweep), curve(sweep=sweep))
    before = copy.deepcopy(data)
    pair = compare(data).pairs[0]
    assert pair.length.outcome == pair.bearing.outcome == pair.displacement.outcome == "agree"
    assert (
        pair.curve.radius.outcome == pair.curve.sweep.outcome == pair.curve.turn.outcome == "agree"
    )
    theta = math.radians(sweep)
    assert pair.left_displacement == pytest.approx(
        (40 * (1 - math.cos(theta)), 40 * math.sin(theta)), abs=1e-10
    )
    assert pair.left_sources[0].quote == "  source old  "
    assert data == before


@pytest.mark.parametrize("sweep", [90, 180, 270])
def test_reversed_arc_swaps_turn_and_endpoint_tangent(sweep):
    data = comparison(
        curve(sweep=sweep),
        curve(sweep=sweep, tangent=(sweep + 180) % 360, direction="left"),
        reverse=True,
    )
    pair = compare(data).pairs[0]
    assert pair.length.outcome == pair.bearing.outcome == pair.displacement.outcome == "agree"
    assert pair.curve.turn.outcome == "agree"


def test_equal_chords_do_not_hide_different_circular_boundaries():
    # Two opposite semicircles have the same endpoints but different shape and start tangent.
    pair = compare(
        comparison(curve(sweep=180), curve(sweep=180, tangent=180, direction="left"))
    ).pairs[0]
    assert pair.length.outcome == pair.displacement.outcome == "agree"
    assert pair.bearing.outcome == pair.curve.turn.outcome == "differ"
    assert pair.position.outcome == "unavailable"


def test_curve_radius_and_sweep_need_separate_explicit_tolerances():
    data = comparison(curve(), curve(radius=41, sweep=91))
    pair = compare(data).pairs[0]
    assert pair.curve.radius.difference == pytest.approx(1)
    assert pair.curve.sweep.difference == pytest.approx(1)
    assert pair.curve.radius.outcome == pair.curve.sweep.outcome == "differ"
    del data["tolerances"]["radius"]
    del data["tolerances"]["sweep_deg"]
    pair = compare(data).pairs[0]
    assert pair.curve.radius.outcome == pair.curve.sweep.outcome == "not_comparable"
    assert pair.length.outcome == "differ"


def placed(data, right_translation=(0, 0)):
    from mp_verify.plot import prepare_plot

    data["scene"] = {
        "id": "shared",
        "name": "survey control",
        "kind": "projected",
        "crs": "EPSG:2234",
        "units": "international_ft",
        "basis": "grid",
    }
    req = ComparisonRequest.model_validate(data)
    for side in ("left", "right"):
        geometry = prepare_plot(getattr(req, side).plot).geometry
        data[side]["placement"] = {
            "id": side + "-place",
            "calculation_id": geometry.calculation_id,
            "geometry_hash": geometry.geometry_hash,
            "scene_id": "shared",
            "status": "referenced",
            "rationale": "recorded control",
            "position_evidence": ["recorded control"],
            "orientation_evidence": ["survey grid"],
            "translation": (0, 0) if side == "left" else right_translation,
        }
    return data


def test_reverse_curve_position_uses_source_linked_fresh_start_and_end():
    data = placed(comparison(curve(), curve(tangent=270, direction="left"), reverse=True), (40, 40))
    pair = compare(data).pairs[0]
    assert pair.position.outcome == "agree"
    assert pair.position.difference == pytest.approx(0, abs=1e-10)
    data["right"]["placement"]["translation"] = (40.2, 40)
    assert compare(data).pairs[0].position.difference == pytest.approx(0.2)
    # A changed source observation invalidates a placement even with unchanged endpoints.
    data["right"]["plot"]["calls"][0]["quote"] = "changed source association"
    assert compare(data).pairs[0].position.outcome == "unavailable"
    assert "stale" in compare(data).pairs[0].position.reason


def test_unsupported_preceding_full_circle_cannot_position_later_selected_arc():
    data = comparison(curve(), curve())
    full = curve(sweep=360, chord_bearing=None)
    for side in ("left", "right"):
        data[side]["plot"]["calls"].insert(0, {"id": side + "-preceding-full", "call": full})
    pair = compare(placed(data)).pairs[0]
    assert pair.displacement.outcome == "agree"
    assert pair.position.outcome == "unavailable"
    assert "full" in pair.position.reason


def test_grouped_arc_selection_explicitly_unavailable_without_affecting_line_groups():
    data = comparison(curve(), curve())
    data["right"]["plot"]["calls"].append({"id": "another-arc", "call": curve(tangent=90)})
    data["pairs"][0]["right"]["call_ids"].append("another-arc")
    pair = compare(data).pairs[0]
    assert pair.displacement.outcome == "not_comparable"
    assert "grouped arcs" in pair.displacement.reason


def test_unknown_orientation_preserves_scalar_curve_shape_comparisons():
    data = comparison(curve(), curve(radius=41))
    for side in ("left", "right"):
        data[side]["bearing_basis"]["identity"] = None
    pair = compare(data).pairs[0]
    assert pair.length.outcome == pair.curve.radius.outcome == "differ"
    assert pair.curve.sweep.outcome == pair.curve.turn.outcome == "agree"
    assert pair.bearing.outcome == pair.displacement.outcome == "not_comparable"


@pytest.mark.parametrize("sweep", [30, 180, 270])
def test_chord_oriented_nontangent_arcs_and_arc_length_only_sweeps(sweep):
    fields = curve(
        sweep=sweep, delta_deg=None, non_tangent=True, bearing_azimuth_deg_from_north=None
    )
    diagnosed = diagnose_closure(diagnostic(fields))
    assert diagnosed.availability == "supported"
    assert diagnosed.sensitivities[0].curve_parameters[1].value == pytest.approx(
        math.radians(sweep)
    )
    pair = compare(comparison(fields, curve(sweep=sweep))).pairs[0]
    assert pair.bearing.outcome == pair.displacement.outcome == "agree"


def test_unvalidated_radial_observation_is_explicitly_refused():
    fields = curve(radial_bearing="N 90° E")
    diagnosed = diagnose_closure(diagnostic(fields))
    assert diagnosed.availability == "unsupported"
    assert "radial curve orientation convention unsupported" in " ".join(diagnosed.limitations)
    assert compare(comparison(fields, curve())).pairs[0].displacement.outcome == "not_comparable"


def test_unsupported_curve_tie_in_is_excluded_without_changing_boundary():
    baseline = diagnostic(curve())
    tie = DiagnosticCall(
        call_id="tie-full-circle",
        call=DeedCall(**curve(sweep=360, chord_bearing=None, is_tie_in=True)),
    )
    calls = (tie, *baseline.calls)
    data = baseline.model_dump()
    data.update(calls=calls, input_sha256=diagnostic_input_hash(calls))
    result = diagnose_closure(ClosureDiagnosticRequest.model_validate(data))
    assert result.residual == diagnose_closure(baseline).residual
    assert result.excluded_call_ids == ("tie-full-circle",)
    assert tuple(row.call_id for row in result.sensitivities) == ("arc-source", "west", "south")


def test_new_algorithm_identities_reject_prior_advisory_results():
    from mp_models.comparison import DescriptionComparison
    from mp_models.diagnostics import ClosureDiagnostics

    diagnosed = diagnose_closure(diagnostic(curve()))
    compared = compare(comparison(curve(), curve()))
    assert diagnosed.algorithm_version == "closure-diagnostics-2"
    assert compared.algorithm_version == "comparison-1.1.0"
    with pytest.raises(ValueError, match="algorithm_version"):
        ClosureDiagnostics.model_validate(
            diagnosed.model_dump() | {"algorithm_version": "closure-diagnostics-1"}
        )
    with pytest.raises(ValueError, match="algorithm_version"):
        DescriptionComparison.model_validate(
            compared.model_dump() | {"algorithm_version": "comparison-1.0.0"}
        )


def test_two_course_semicircular_boundary_supports_closure_and_zero_rank_handling():
    baseline = diagnostic(curve(sweep=180))
    calls = (
        baseline.calls[0],
        DiagnosticCall(
            call_id="diameter",
            call=DeedCall(
                course=2, direction_text="W", distance_ft=80, bearing_azimuth_deg_from_north=270
            ),
        ),
    )
    request = ClosureDiagnosticRequest.model_validate(
        baseline.model_dump() | {"calls": calls, "input_sha256": diagnostic_input_hash(calls)}
    )
    result = diagnose_closure(request)
    assert result.availability == "supported"
    assert result.residual.magnitude_ft == pytest.approx(0, abs=1e-10)
    assert result.ranking_available is False
    assert all(
        p.rank is None and p.projection_abs is None
        for p in result.sensitivities[0].curve_parameters
    )
