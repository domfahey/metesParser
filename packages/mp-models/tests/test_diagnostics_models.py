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
    "update",
    [
        {"input_sha256": "0" * 64},
        {"request_id": ""},
        {"schema_version": "9"},
        {"calls": ()},
        {"residual": {"east": 0}},
    ],
)
def test_invalid_identity_and_supplied_geometry_rejected(update):
    with pytest.raises(ValidationError):
        ClosureDiagnosticRequest(**(payload() | update))


def test_duplicate_ids_and_mutation_rejected():
    data = payload()
    data["calls"] = data["calls"] * 2
    data["input_sha256"] = diagnostic_input_hash(data["calls"])
    with pytest.raises(ValidationError, match="unique"):
        ClosureDiagnosticRequest(**data)
    req = ClosureDiagnosticRequest(**payload())
    with pytest.raises(ValidationError):
        req.input_id = "changed"
    with pytest.raises(ValidationError):
        ClosureDiagnosticRequest.model_validate(req.model_copy(update={"input_sha256": "0" * 64}))


@pytest.mark.parametrize(
    "values",
    [
        {
            "distance_increment_ft": 0.01,
            "bearing_increment_arcsec": 1,
            "rounding": "truncate",
            "evidence": "x",
        },
        {"distance_increment_ft": float("nan"), "bearing_increment_arcsec": 1, "evidence": "x"},
        {"distance_increment_ft": 0.01, "bearing_increment_arcsec": 1, "evidence": ""},
    ],
)
def test_precision_needs_finite_increments_supported_rounding_evidence(values):
    with pytest.raises(ValidationError):
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
    "change",
    [
        {"value": -40},
        {"derivative_units": "ft/radian"},
        {"fixed_parameters": ("radius_ft",)},
        {"projection_abs": -1, "rank": 1},
        {"projection_abs": 1, "rank": None},
    ],
)
def test_curve_parameter_requires_consistent_independent_basis(change):
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
    with pytest.raises(ValueError):
        CurveParameterSensitivity.model_validate(values)
