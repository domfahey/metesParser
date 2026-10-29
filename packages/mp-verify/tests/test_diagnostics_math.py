"""Independent numeric and non-promotion contracts for advisory diagnostics."""

import math

import pytest
from mp_models.deed_call import DeedCall
from mp_models.diagnostics import (
    ClosureDiagnosticRequest,
    DiagnosticCall,
    DiagnosticFrame,
    DiagnosticSourceRef,
    QuantizationAssumptions,
    diagnostic_input_hash,
)
from mp_verify.diagnostics import diagnose_closure


def rectangle(rotation=0, excess=0.5):
    return tuple(
        DiagnosticCall(
            call_id=f"c{i}",
            call=DeedCall(
                course=i,
                direction_text=f"source {i}",
                distance_ft=distance,
                bearing_azimuth_deg_from_north=(angle + rotation) % 360,
            ),
            source_refs=(
                DiagnosticSourceRef(
                    source_id="deed", occurrence_id="exhibit-a", quote=f"  verbatim course {i}  "
                ),
            ),
        )
        for i, (angle, distance) in enumerate(
            ((90, 100 + excess), (180, 100), (270, 100), (0, 100)), 1
        )
    )


def request(calls=None, **kwargs):
    calls = rectangle() if calls is None else calls
    return ClosureDiagnosticRequest(
        request_id="r1",
        input_id="parcel-1",
        calls=calls,
        input_sha256=diagnostic_input_hash(calls),
        frame=DiagnosticFrame(name="Recorded local"),
        **kwargs,
    )


@pytest.mark.parametrize("rotation", [0, 90, 31.7])
def test_opposing_distance_candidates_tie_without_culprit(rotation):
    req = request(rectangle(rotation))
    before = req.model_dump_json()
    result = diagnose_closure(req)
    assert result.availability == "supported"
    assert result.residual.magnitude_ft == pytest.approx(0.5)
    by_id = {row.call_id: row for row in result.sensitivities}
    assert by_id["c1"].distance_rank == by_id["c3"].distance_rank == 1
    assert by_id["c2"].distance_rank == by_id["c4"].distance_rank == 2
    assert by_id["c1"].distance_projection_abs == pytest.approx(1)
    assert result.verified_export_eligible is False
    assert result.request == req
    assert result.request.calls[0].source_refs[0].quote == "  verbatim course 1  "
    assert req.model_dump_json() == before
    assert "culprit" not in result.model_dump_json()


def test_derivatives_agree_with_independent_finite_differences():
    req = request(rectangle(27.4))
    row = diagnose_closure(req).sensitivities[0]
    d = req.calls[0].call.distance_ft
    a = math.radians(117.4)
    h = 1e-5
    expected_distance = ((d + h) * math.sin(a) - (d - h) * math.sin(a)) / (2 * h)
    expected_angle_east = (d * math.sin(a + h) - d * math.sin(a - h)) / (2 * h)
    expected_angle_north = (d * math.cos(a + h) - d * math.cos(a - h)) / (2 * h)
    assert row.distance_derivative.east == pytest.approx(expected_distance, abs=1e-8)
    assert row.angle_derivative_per_radian.east == pytest.approx(expected_angle_east, abs=1e-7)
    assert row.angle_derivative_per_radian.north == pytest.approx(expected_angle_north, abs=1e-7)
    assert row.angle_derivative_per_arcsecond.east == pytest.approx(
        row.angle_derivative_per_radian.east * math.pi / 648000
    )


def test_hand_computed_east_derivatives():
    row = diagnose_closure(request()).sensitivities[0]
    assert row.distance_derivative.east == pytest.approx(1)
    assert row.distance_derivative.north == pytest.approx(0, abs=1e-12)
    assert row.angle_derivative_per_radian.east == pytest.approx(0, abs=1e-12)
    assert row.angle_derivative_per_radian.north == pytest.approx(-100.5)


def test_zero_residual_retains_derivatives_without_direction_ranking():
    result = diagnose_closure(request(rectangle(excess=0)))
    assert result.residual.magnitude_ft < 1e-10
    assert result.ranking_available is False
    assert all(row.distance_rank is None and row.angle_rank is None for row in result.sensitivities)
    assert all(row.distance_projection_abs is None for row in result.sensitivities)


@pytest.mark.parametrize(
    "update,availability,reason",
    [
        ({"bearing_azimuth_deg_from_north": None}, "incomplete", "unresolved_bearing"),
        (
            {"curve_dir": "left", "radius_ft": 100, "delta_deg": 30, "curve_type": "spiral"},
            "unsupported",
            "curve",
        ),
        ({"is_meander": True}, "unsupported", "meander"),
        ({"is_exception": True}, "unsupported", "exception_boundary"),
        ({"is_indefinite": True}, "incomplete", "indefinite_call"),
    ],
)
def test_unknown_course_never_manufactures_partial_residual(update, availability, reason):
    calls = list(rectangle())
    calls[0] = calls[0].model_copy(update={"call": calls[0].call.model_copy(update=update)})
    result = diagnose_closure(request(tuple(calls)))
    assert result.availability == availability
    assert result.residual is None
    assert result.sensitivities == ()
    assert any(reason in item for item in result.limitations)


def test_tie_in_explicitly_excluded_even_with_unknown_bearing():
    calls = (
        DiagnosticCall(
            call_id="tie",
            call=DeedCall(course=5, direction_text="commencing", distance_ft=50, is_tie_in=True),
        ),
        *rectangle(),
    )
    result = diagnose_closure(request(calls))
    assert result.availability == "supported"
    assert result.excluded_call_ids == ("tie",)
    assert result.residual.magnitude_ft == pytest.approx(0.5)
    assert len(result.request.calls) == 5


def test_quantization_bounds_require_explicit_assumptions_and_stay_separate():
    assert diagnose_closure(request()).quantization is None
    precision = QuantizationAssumptions(
        distance_increment_ft=0.01,
        bearing_increment_arcsec=1,
        rounding="nearest",
        evidence="Survey legend precision",
    )
    result = diagnose_closure(request(precision=precision))
    expected = 4 * 0.005 + (400.5 + 4 * 0.005) * 2 * math.sin(math.pi / 1296000 / 2)
    assert result.quantization.endpoint_bound_ft == pytest.approx(expected)
    assert result.quantization.assumptions == precision
    assert "probability" in result.quantization.limitation


def test_scenario_retains_source_evidence_and_does_not_mutate_baseline():
    baseline = diagnose_closure(request())
    scenario = diagnose_closure(
        request(
            rectangle(excess=0),
            scenario_id="reading-b",
            baseline_request_sha256=baseline.request_sha256,
            scenario_evidence="Digit may be 0 or 5",
        )
    )
    assert baseline.residual.magnitude_ft == pytest.approx(0.5)
    assert scenario.request.baseline_request_sha256 == baseline.request_sha256
    assert scenario.request.scenario_evidence == "Digit may be 0 or 5"
    assert scenario.request_sha256 != baseline.request_sha256


def test_too_few_boundary_calls_incomplete():
    result = diagnose_closure(request(rectangle()[:2]))
    assert result.availability == "incomplete"
    assert result.residual is None


def test_finite_inputs_that_overflow_analysis_are_honestly_unsupported():
    calls = tuple(
        item.model_copy(update={"call": item.call.model_copy(update={"distance_ft": 1e308})})
        for item in rectangle()
    )
    result = diagnose_closure(request(calls))
    assert result.availability == "unsupported"
    assert result.residual is None
    assert any("finite" in limitation for limitation in result.limitations)


def test_result_identity_cannot_be_rebound_to_other_input():
    from mp_models.diagnostics import ClosureDiagnostics
    from mp_verify.diagnostics import diagnose_closure
    from pydantic import ValidationError

    result = diagnose_closure(request())
    with pytest.raises(ValidationError, match="identity"):
        ClosureDiagnostics.model_validate(
            result.model_dump(mode="json") | {"input_sha256": "0" * 64}
        )
    with pytest.raises(ValidationError, match="identity"):
        ClosureDiagnostics.model_validate(
            result.model_dump(mode="json") | {"request_sha256": "0" * 64}
        )


@pytest.mark.parametrize("rotation", [0, 53.1, 179.999])
def test_all_vector_components_independently_match_endpoint_finite_differences(rotation):
    req = request(rectangle(rotation))
    result = diagnose_closure(req)

    def endpoint(distances, angles):
        return (
            math.fsum(d * math.sin(a) for d, a in zip(distances, angles, strict=True)),
            math.fsum(d * math.cos(a) for d, a in zip(distances, angles, strict=True)),
        )

    distances = [c.call.distance_ft for c in req.calls]
    angles = [math.radians(c.call.bearing_azimuth_deg_from_north) for c in req.calls]
    for i, row in enumerate(result.sensitivities):
        for parameter, vector in (
            (distances, row.distance_derivative),
            (angles, row.angle_derivative_per_radian),
        ):
            step = 1e-5
            plus, minus = parameter.copy(), parameter.copy()
            plus[i] += step
            minus[i] -= step
            if parameter is distances:
                ep, em = endpoint(plus, angles), endpoint(minus, angles)
            else:
                ep, em = endpoint(distances, plus), endpoint(distances, minus)
            assert vector.east == pytest.approx((ep[0] - em[0]) / (2 * step), abs=1e-7)
            assert vector.north == pytest.approx((ep[1] - em[1]) / (2 * step), abs=1e-7)


def test_declared_rounding_bound_contains_independent_corner_perturbations():
    from itertools import product

    precision = QuantizationAssumptions(
        distance_increment_ft=0.02,
        bearing_increment_arcsec=2,
        evidence="Explicit synthetic source precision",
    )
    req = request(rectangle(13), precision=precision)
    result = diagnose_closure(req)
    # Enumerate all 2^8 end points of the explicitly declared rounding box.
    # This samples the bound independently rather than restating its derivation.
    for signs in product((-1, 1), repeat=8):
        e = n = 0.0
        for i, item in enumerate(req.calls):
            d = item.call.distance_ft + signs[2 * i] * 0.01
            a = math.radians(item.call.bearing_azimuth_deg_from_north + signs[2 * i + 1] / 3600)
            e += d * math.sin(a)
            n += d * math.cos(a)
        error = math.hypot(e - result.residual.east_ft, n - result.residual.north_ft)
        assert error <= result.quantization.endpoint_bound_ft
