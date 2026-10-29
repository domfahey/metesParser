"""Lossless source-bound centerline and width construction contracts."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, FiniteFloat, model_validator

from .base import _Model
from .diagnostics import DiagnosticSourceRef
from .plot import XY, Digest, Identifier, LinearUnit
from .plot_request import PlotRequest, PreparedPlot

Nonnegative = Annotated[FiniteFloat, Field(ge=0)]


class _CorridorModel(_Model):
    model_config = ConfigDict(str_strip_whitespace=False, revalidate_instances="always")


class CorridorStation(_CorridorModel):
    call_id: Identifier
    fraction: FiniteFloat = Field(ge=0, le=1)


class CorridorWidthInterval(_CorridorModel):
    """Widths are relative to forward centerline traversal, never averaged per call.

    A step row is constant on its interval; a different next row explicitly creates
    a width jump. A taper interpolates each side linearly in centerline arc length.
    """

    id: Identifier
    start: CorridorStation
    end: CorridorStation
    left_start: Nonnegative
    left_end: Nonnegative
    right_start: Nonnegative
    right_end: Nonnegative
    rule: Literal["step", "linear_taper"]
    source_refs: tuple[DiagnosticSourceRef, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _widths(self) -> Self:
        if self.left_start + self.right_start <= 0 or self.left_end + self.right_end <= 0:
            raise ValueError("corridor must retain positive total width at both interval endpoints")
        if self.rule == "step" and (
            self.left_start != self.left_end or self.right_start != self.right_end
        ):
            raise ValueError("step widths must be constant within their interval")
        return self


class CorridorErrorBudget(_CorridorModel):
    max_error: FiniteFloat = Field(gt=0)
    unit: LinearUnit
    max_segments: int = Field(default=2048, ge=4, le=16384, strict=True)

    @model_validator(mode="after")
    def _known_unit(self) -> Self:
        if self.unit == "unknown_ft":
            raise ValueError("corridor error budget requires known linear units")
        return self


class CorridorRequest(_CorridorModel):
    """An explicit construction, including user-selected join/cap conventions.

    Square caps extend by half the total endpoint width. Round caps have the
    left/right endpoint diameter, whose center may lie off an asymmetric centerline.
    These choices record instructions, not inferred surveyed intent.
    """

    schema_version: Literal["1.0"] = "1.0"
    id: Identifier
    centerline: PlotRequest
    widths: tuple[CorridorWidthInterval, ...]
    width_unit: LinearUnit
    side_reference: Literal["forward_centerline"] = "forward_centerline"
    join: Literal["bevel", "miter", "round"]
    miter_limit: FiniteFloat = Field(default=4, ge=1)
    cap: Literal["butt", "square", "round"]
    construction_source_refs: tuple[DiagnosticSourceRef, ...] = Field(min_length=1)
    error_budget: CorridorErrorBudget

    @model_validator(mode="after")
    def _references(self) -> Self:
        if self.width_unit == "unknown_ft":
            raise ValueError("width unit must identify a known linear unit")
        if len({width.id for width in self.widths}) != len(self.widths):
            raise ValueError("width interval IDs must be unique")
        call_ids = {record.id for record in self.centerline.calls}
        if any(
            row.start.call_id not in call_ids or row.end.call_id not in call_ids
            for row in self.widths
        ):
            raise ValueError("width interval references an unknown centerline call")
        return self


class CorridorErrorReport(_CorridorModel):
    unit: LinearUnit
    linearization_bound: Nonnegative
    floating_point_bound: Nonnegative
    total_bound: Nonnegative
    requested_max_error: Annotated[FiniteFloat, Field(gt=0)]
    boundary_segments: int = Field(ge=3)
    method: Literal["second_derivative_chord_bound"] = "second_derivative_chord_bound"

    @model_validator(mode="after")
    def _bound(self) -> Self:
        if self.total_bound < self.linearization_bound + self.floating_point_bound:
            raise ValueError("total error must include linearization and floating point bounds")
        if self.total_bound > self.requested_max_error:
            raise ValueError("computed corridor exceeds its declared error budget")
        return self


class CorridorBoundaryEdge(_CorridorModel):
    call_id: Identifier
    centerline_call_ids: tuple[Identifier, ...]
    width_interval_ids: tuple[Identifier, ...]
    role: Literal["left_offset", "right_offset", "join", "start_cap", "end_cap"]
    source_refs: tuple[DiagnosticSourceRef, ...]


class CorridorResult(_CorridorModel):
    schema_version: Literal["1.0"] = "1.0"
    algorithm_version: Literal["corridor-1"] = "corridor-1"
    request: CorridorRequest
    input_sha256: Digest
    availability: Literal[
        "supported", "unsupported", "incomplete", "topology_failed", "topology_unavailable"
    ]
    centerline: PreparedPlot | None = None
    boundary: PreparedPlot | None = None
    boundary_origin_in_centerline_frame: XY | None = None
    polygon: tuple[XY, ...] | None = None
    boundary_edges: tuple[CorridorBoundaryEdge, ...] = ()
    error: CorridorErrorReport | None = None
    limitations: tuple[str, ...] = ()
    verified_export_eligible: Literal[False] = False
    engine_verified: Literal[False] = False
    source_review_complete: Literal[False] = False

    @model_validator(mode="after")
    def _availability(self) -> Self:
        if self.availability == "supported":
            if (
                self.boundary is None
                or self.polygon is None
                or self.error is None
                or self.centerline is None
                or self.boundary_origin_in_centerline_frame is None
            ):
                raise ValueError(
                    "supported corridor requires centerline, boundary, polygon and error evidence"
                )
            if len(self.boundary_edges) != len(self.boundary.geometry.primitives):
                raise ValueError(
                    "boundary edges must retain every prepared boundary segment identity"
                )
        elif (
            self.boundary is not None
            or self.polygon is not None
            or self.error is not None
            or self.boundary_edges
            or self.boundary_origin_in_centerline_frame is not None
        ):
            raise ValueError("unsupported corridor must not expose an apparently complete polygon")
        return self


class CorridorManifest(_CorridorModel):
    schema_version: Literal["1.0"] = "1.0"
    artifact_kind: Literal["centerline_corridor"] = "centerline_corridor"
    algorithm_version: Literal["corridor-1"] = "corridor-1"
    source_file: Literal["request.json"] = "request.json"
    canonical_request_file: Literal["corridor-request.json"] = "corridor-request.json"
    result_file: Literal["corridor.json"] = "corridor.json"
    source_sha256: Digest
    canonical_request_sha256: Digest
    result_sha256: Digest
    input_sha256: Digest
    centerline_plot_sha256: Digest | None = None
    boundary_plot_sha256: Digest | None = None
    boundary_html_sha256: Digest | None = None
    engine_verified: Literal[False] = False
    verified_export_eligible: Literal[False] = False
