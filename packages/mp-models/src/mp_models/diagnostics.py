"""Immutable identities and explicitly advisory line/circular-arc diagnostics."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, FiniteFloat, model_validator

from .base import _Model
from .deed_call import DeedCall

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Identity = Annotated[str, Field(min_length=1, pattern=r"^\S(?:.*\S)?$")]
Positive = Annotated[FiniteFloat, Field(gt=0)]


class _DiagnosticModel(_Model):
    model_config = ConfigDict(str_strip_whitespace=False, revalidate_instances="always")


class DiagnosticSourceRef(_DiagnosticModel):
    """Source evidence when known; absent identity details remain unknown."""

    source_id: Identity
    source_sha256: Digest | None = None
    occurrence_id: Identity | None = None
    page: int | None = Field(default=None, gt=0, strict=True)
    page_id: Identity | None = None
    crop_id: Identity | None = None
    span_id: Identity | None = None
    quote: str | None = None
    uncertainty: str | None = None


class DiagnosticCall(_DiagnosticModel):
    call_id: Identity
    call: DeedCall
    source_refs: tuple[DiagnosticSourceRef, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def _revalidate_call(cls, value: object) -> object:
        # DeedCall predates revalidation; never allow model_copy to bypass geometry validation.
        if isinstance(value, dict) and isinstance(value.get("call"), DeedCall):
            value = dict(value)
            value["call"] = value["call"].model_dump(mode="json")
        return value


class DiagnosticFrame(_DiagnosticModel):
    name: Identity
    basis: Literal["recorded_bearings"] = "recorded_bearings"
    units: Literal["ft"] = "ft"
    foot_definition: Literal["international_ft", "us_survey_ft", "unknown_ft"] = "unknown_ft"


class QuantizationAssumptions(_DiagnosticModel):
    """Explicit source increments, with deterministic nearest-rounding limits."""

    distance_increment_ft: Positive
    bearing_increment_arcsec: Annotated[Positive, Field(le=1296000)]
    rounding: Literal["nearest"] = "nearest"
    evidence: Identity


def diagnostic_input_hash(calls: Sequence[DiagnosticCall]) -> str:
    """SHA-256 of canonical complete call/source payload; includes order and stable IDs.

    Author requests with this helper after constructing all calls. It detects changes;
    it does not authenticate source documents or certify transcription accuracy.
    """
    payload = [DiagnosticCall.model_validate(c).model_dump(mode="json") for c in calls]
    return _diagnostic_hash(payload)


def _diagnostic_hash(value: object) -> str:
    data = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


class ClosureDiagnosticRequest(_DiagnosticModel):
    schema_version: Literal["1.0"] = "1.0"
    request_id: Identity
    input_id: Identity
    input_sha256: Digest
    calls: tuple[DiagnosticCall, ...] = Field(min_length=1)
    frame: DiagnosticFrame
    precision: QuantizationAssumptions | None = None
    scenario_id: Identity | None = None
    baseline_request_sha256: Digest | None = None
    scenario_evidence: Identity | None = None

    @model_validator(mode="after")
    def _identities(self) -> Self:
        if len({c.call_id for c in self.calls}) != len(self.calls):
            raise ValueError("call_id must be unique")
        if diagnostic_input_hash(self.calls) != self.input_sha256:
            raise ValueError("input_sha256 differs from canonical calls and source references")
        fields = (self.scenario_id, self.baseline_request_sha256, self.scenario_evidence)
        if any(v is not None for v in fields) and not all(v is not None for v in fields):
            raise ValueError("scenario requires ID, baseline request hash, and source evidence")
        return self


class DiagnosticVector(_DiagnosticModel):
    east: FiniteFloat
    north: FiniteFloat


class DiagnosticResidual(_DiagnosticModel):
    east_ft: FiniteFloat
    north_ft: FiniteFloat
    magnitude_ft: Annotated[FiniteFloat, Field(ge=0)]


class CurveParameterSensitivity(_DiagnosticModel):
    """Endpoint derivative in an independent circular-arc basis, never a correction."""

    parameter: Literal["radius_ft", "sweep_radian", "start_tangent_radian"]
    value: FiniteFloat
    derivative: DiagnosticVector
    derivative_units: Literal["ft/ft", "ft/radian"]
    fixed_parameters: tuple[Identity, ...] = Field(min_length=1)
    constraint: Identity
    projection_abs: Annotated[FiniteFloat, Field(ge=0)] | None = None
    rank: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _basis(self) -> Self:
        parameters = ("radius_ft", "sweep_radian", "start_tangent_radian", "curve_dir")
        if self.fixed_parameters != tuple(p for p in parameters if p != self.parameter):
            raise ValueError(
                "fixed parameters must hold the other independent arc parameters constant"
            )
        expected_units = "ft/ft" if self.parameter == "radius_ft" else "ft/radian"
        if self.derivative_units != expected_units:
            raise ValueError("derivative units differ from the independent parameter")
        if (
            (self.parameter == "radius_ft" and self.value <= 0)
            or (self.parameter == "sweep_radian" and not 0 < self.value < 2 * math.pi)
            or (self.parameter == "start_tangent_radian" and not 0 <= self.value < 2 * math.pi)
        ):
            raise ValueError("curve parameter value outside the supported circular-arc basis")
        if (self.projection_abs is None) != (self.rank is None):
            raise ValueError("projection and rank must be available together")
        return self


class CallSensitivity(_DiagnosticModel):
    call_id: Identity
    source_refs: tuple[DiagnosticSourceRef, ...] = ()
    geometry_kind: Literal["line", "arc"] = "line"
    distance_derivative: DiagnosticVector | None = None
    angle_derivative_per_radian: DiagnosticVector | None = None
    angle_derivative_per_arcsecond: DiagnosticVector | None = None
    distance_projection_abs: FiniteFloat | None = None
    angle_projection_abs_per_arcsecond: FiniteFloat | None = None
    distance_rank: int | None = Field(default=None, ge=1)
    angle_rank: int | None = Field(default=None, ge=1)
    curve_parameters: tuple[CurveParameterSensitivity, ...] = ()

    @model_validator(mode="after")
    def _parameter_basis(self) -> Self:
        line_vectors = (
            self.distance_derivative,
            self.angle_derivative_per_radian,
            self.angle_derivative_per_arcsecond,
        )
        if self.geometry_kind == "line":
            if any(v is None for v in line_vectors) or self.curve_parameters:
                raise ValueError("line sensitivities require line derivatives and no curve basis")
        elif (
            any(v is not None for v in line_vectors)
            or any(
                v is not None
                for v in (
                    self.distance_projection_abs,
                    self.angle_projection_abs_per_arcsecond,
                    self.distance_rank,
                    self.angle_rank,
                )
            )
            or tuple(p.parameter for p in self.curve_parameters)
            != ("radius_ft", "sweep_radian", "start_tangent_radian")
        ):
            raise ValueError("arc sensitivities require only the independent circular-arc basis")
        return self


class QuantizationBound(_DiagnosticModel):
    assumptions: QuantizationAssumptions
    endpoint_bound_ft: Annotated[FiniteFloat, Field(ge=0)]
    limitation: str = "Conservative rounding bound, not an error probability or confidence score."


class ClosureDiagnostics(_DiagnosticModel):
    schema_version: Literal["1.0"] = "1.0"
    algorithm_version: Literal["closure-diagnostics-2"] = "closure-diagnostics-2"
    request: ClosureDiagnosticRequest
    request_sha256: Digest
    input_sha256: Digest
    availability: Literal["supported", "unsupported", "incomplete"]
    residual: DiagnosticResidual | None = None
    sensitivities: tuple[CallSensitivity, ...] = ()
    excluded_call_ids: tuple[Identity, ...] = ()
    limitations: tuple[str, ...] = ()
    ranking_available: bool = False
    numerical_zero_threshold_ft: Annotated[FiniteFloat, Field(ge=0)] | None = None
    quantization: QuantizationBound | None = None
    verified_export_eligible: Literal[False] = False

    @model_validator(mode="after")
    def _bindings(self) -> Self:
        if (
            self.input_sha256 != self.request.input_sha256
            or self.request_sha256 != _diagnostic_hash(self.request.model_dump(mode="json"))
        ):
            raise ValueError("diagnostic result identity differs from its request")
        excluded = tuple(c.call_id for c in self.request.calls if c.call.is_tie_in)
        if self.excluded_call_ids != excluded:
            raise ValueError("excluded call identity differs from the marked tie-ins")
        if self.availability != "supported":
            if (
                self.residual is not None
                or self.sensitivities
                or self.quantization is not None
                or self.ranking_available
            ):
                raise ValueError(
                    "unsupported or incomplete results cannot contain partial calculations"
                )
        else:
            included = [c for c in self.request.calls if not c.call.is_tie_in]
            if self.residual is None or len(included) != len(self.sensitivities):
                raise ValueError(
                    "supported results require all boundary sensitivities and a residual"
                )
            if any(
                row.call_id != call.call_id or row.source_refs != call.source_refs
                for row, call in zip(self.sensitivities, included, strict=True)
            ):
                raise ValueError("sensitivity source identity differs from its request")
            if any(
                row.geometry_kind != ("arc" if call.call.is_curve() else "line")
                for row, call in zip(self.sensitivities, included, strict=True)
            ):
                raise ValueError("sensitivity geometry kind differs from its request")
        return self
