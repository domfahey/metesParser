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
from pydantic import ValidationError


def payload():
    calls = (
        DiagnosticCall(
            call_id="east",
            call=DeedCall(
                course=1, direction_text="E", bearing_azimuth_deg_from_north=90, distance_ft=100
            ),
        ),
    )
    return {
        "request_id": "request",
        "input_id": "parcel",
        "calls": calls,
        "frame": DiagnosticFrame(name="Recorded"),
        "input_sha256": diagnostic_input_hash(calls),
    }


def test_hash_and_identity_preserved_unknown_source_is_explicit():
    ref = DiagnosticSourceRef(source_id="deed", quote="  verbatim  ")
    assert ref.source_sha256 is None and ref.occurrence_id is None
    assert ref.quote == "  verbatim  "
    assert ClosureDiagnosticRequest(**payload()).input_sha256 == payload()["input_sha256"]


@pytest.mark.parametrize(
    ("update", "expected_match"),
    [
        ({"input_sha256": "0" * 64}, "input_sha256 differs"),
        ({"request_id": ""}, "at least 1 character"),
        ({"schema_version": "9"}, "Input should be '1.0'"),
        ({"calls": ()}, "at least 1 item"),
        ({"residual": {"east": 0}}, "Extra inputs are not permitted"),
    ],
)
def test_invalid_identity_and_supplied_geometry_rejected(update, expected_match):
    with pytest.raises(ValidationError, match=expected_match):
        ClosureDiagnosticRequest(**(payload() | update))


def test_duplicate_ids_and_mutation_rejected():
    data = payload()
    data["calls"] = data["calls"] * 2
    data["input_sha256"] = diagnostic_input_hash(data["calls"])
    with pytest.raises(ValidationError, match="unique"):
        ClosureDiagnosticRequest(**data)
    req = ClosureDiagnosticRequest(**payload())
    with pytest.raises(ValidationError, match="Instance is frozen"):
        req.input_id = "changed"
    with pytest.raises(ValidationError, match="input_sha256 differs"):
        ClosureDiagnosticRequest.model_validate(req.model_copy(update={"input_sha256": "0" * 64}))


@pytest.mark.parametrize(
    ("values", "expected_match"),
    [
        (
            {
                "distance_increment_ft": 0.01,
                "bearing_increment_arcsec": 1,
                "rounding": "truncate",
                "evidence": "x",
            },
            "Input should be 'nearest'",
        ),
        (
            {"distance_increment_ft": float("nan"), "bearing_increment_arcsec": 1, "evidence": "x"},
            "finite number",
        ),
        (
            {"distance_increment_ft": 0.01, "bearing_increment_arcsec": 1, "evidence": ""},
            "at least 1 character",
        ),
    ],
)
def test_precision_needs_finite_increments_supported_rounding_evidence(values, expected_match):
    with pytest.raises(ValidationError, match=expected_match):
        QuantizationAssumptions(**values)


def test_scenario_requires_all_evidence_fields():
    with pytest.raises(ValidationError, match="scenario"):
        ClosureDiagnosticRequest(**payload(), scenario_id="b")


def test_sensitivity_basis_cannot_mix_line_and_curve_derivatives():
    from mp_models.diagnostics import CallSensitivity, DiagnosticVector

    vector = DiagnosticVector(east=0, north=1)
    with pytest.raises(ValueError, match="line derivatives"):
        CallSensitivity(call_id="line")
    with pytest.raises(ValueError, match="independent circular-arc basis"):
        CallSensitivity(call_id="arc", geometry_kind="arc", distance_derivative=vector)


@pytest.mark.parametrize(
    ("change", "expected_match"),
    [
        ({"value": -40}, "outside the supported circular-arc basis"),
        ({"derivative_units": "ft/radian"}, "derivative units differ"),
        ({"fixed_parameters": ("radius_ft",)}, "other independent arc parameters constant"),
        ({"projection_abs": -1, "rank": 1}, "greater than or equal to 0"),
        ({"projection_abs": 1, "rank": None}, "projection and rank must be available together"),
    ],
)
def test_curve_parameter_requires_consistent_independent_basis(change, expected_match):
    from mp_models.diagnostics import CurveParameterSensitivity

    values = {
        "parameter": "radius_ft",
        "value": 40,
        "derivative": {"east": 1, "north": 1},
        "derivative_units": "ft/ft",
        "fixed_parameters": ("sweep_radian", "start_tangent_radian", "curve_dir"),
        "constraint": "derive redundant observations together",
        **change,
    }
    with pytest.raises(ValueError, match=expected_match):
        CurveParameterSensitivity.model_validate(values)


def test_closure_diagnostics_binding_and_consistency_guards():
    import hashlib
    import json

    from mp_models.diagnostics import (
        CallSensitivity,
        ClosureDiagnostics,
        CurveParameterSensitivity,
        DiagnosticResidual,
        DiagnosticVector,
    )

    req = ClosureDiagnosticRequest(**payload())
    req_sha = hashlib.sha256(
        json.dumps(req.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    vec = DiagnosticVector(east=1.0, north=0.0)
    res = DiagnosticResidual(east_ft=0.0, north_ft=0.0, magnitude_ft=0.0)
    line_sens = CallSensitivity(
        call_id="east",
        distance_derivative=vec,
        angle_derivative_per_radian=vec,
        angle_derivative_per_arcsecond=vec,
    )
    base = {"request": req, "request_sha256": req_sha, "input_sha256": req.input_sha256}

    # Wrong excluded_call_ids.
    with pytest.raises(ValidationError, match="excluded call identity"):
        ClosureDiagnostics(**base, availability="unsupported", excluded_call_ids=("east",))
    # Unsupported with residual or sensitivities rejected.
    with pytest.raises(ValidationError, match="cannot contain partial calculations"):
        ClosureDiagnostics(**base, availability="unsupported", residual=res)
    # Supported without residual or mismatched sensitivities count rejected.
    with pytest.raises(ValidationError, match="require all boundary sensitivities"):
        ClosureDiagnostics(**base, availability="supported", residual=res, sensitivities=())
    # Supported with mismatched call_id / source_refs rejected.
    with pytest.raises(ValidationError, match="sensitivity source identity"):
        ClosureDiagnostics(
            **base,
            availability="supported",
            residual=res,
            sensitivities=(line_sens.model_copy(update={"call_id": "wrong"}),),
        )
    # Supported with mismatched geometry_kind (arc sensitivity for a line call) rejected.
    arc_params = (
        CurveParameterSensitivity(
            parameter="radius_ft",
            value=100.0,
            derivative=vec,
            derivative_units="ft/ft",
            fixed_parameters=("sweep_radian", "start_tangent_radian", "curve_dir"),
            constraint="c",
        ),
        CurveParameterSensitivity(
            parameter="sweep_radian",
            value=1.0,
            derivative=vec,
            derivative_units="ft/radian",
            fixed_parameters=("radius_ft", "start_tangent_radian", "curve_dir"),
            constraint="c",
        ),
        CurveParameterSensitivity(
            parameter="start_tangent_radian",
            value=0.0,
            derivative=vec,
            derivative_units="ft/radian",
            fixed_parameters=("radius_ft", "sweep_radian", "curve_dir"),
            constraint="c",
        ),
    )
    arc_sens = CallSensitivity(call_id="east", geometry_kind="arc", curve_parameters=arc_params)
    with pytest.raises(ValidationError, match="sensitivity geometry kind"):
        ClosureDiagnostics(
            **base, availability="supported", residual=res, sensitivities=(arc_sens,)
        )
