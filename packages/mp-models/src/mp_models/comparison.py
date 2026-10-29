"""Immutable advisory description-comparison contracts (no boundary establishment)."""

from typing import Literal, Self

from pydantic import Field, FiniteFloat, model_validator

from .base import _Model
from .plot import XY, Digest, Identifier, LinearUnit, PlotPlacement, PlotScene
from .plot_request import PlotCall, PlotRequest


class BearingBasis(_Model):
    label: str
    identity: str | None = None
    source_references: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _evidence(self) -> Self:
        if self.identity is not None and (not self.identity.strip() or not self.source_references):
            raise ValueError("known bearing basis requires identity and source references")
        if any(not r.strip() for r in self.source_references):
            raise ValueError("basis references must not be blank")
        return self


class ComparisonDescription(_Model):
    id: Identifier
    plot: PlotRequest
    bearing_basis: BearingBasis
    placement: PlotPlacement | None = None


class ComparisonTolerance(_Model):
    length: FiniteFloat = Field(ge=0)
    displacement: FiniteFloat = Field(ge=0)
    position: FiniteFloat = Field(ge=0)
    linear_unit: LinearUnit
    bearing_deg: FiniteFloat = Field(ge=0, lt=180)
    source_references: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _known(self) -> Self:
        if self.linear_unit == "unknown_ft" or any(not r.strip() for r in self.source_references):
            raise ValueError("tolerances require known units and provenance")
        return self


class ComparisonSelection(_Model):
    call_ids: tuple[Identifier, ...] = Field(min_length=1)
    direction: Literal["forward", "reverse"]

    @model_validator(mode="after")
    def _unique(self) -> Self:
        if len(set(self.call_ids)) != len(self.call_ids):
            raise ValueError("selection call IDs must be unique")
        return self


class ComparisonPair(_Model):
    id: Identifier
    left: ComparisonSelection
    right: ComparisonSelection


class ComparisonTransform(_Model):
    """Explicit clockwise rigid transform from right native frame to left frame."""

    rotation_deg: FiniteFloat
    translation: XY = (0.0, 0.0)
    source_references: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _sourced(self) -> Self:
        if any(not r.strip() for r in self.source_references):
            raise ValueError("rigid transform requires source evidence")
        return self


class ComparisonRequest(_Model):
    schema_version: Literal["1.0"] = "1.0"
    left: ComparisonDescription
    right: ComparisonDescription
    pairs: tuple[ComparisonPair, ...] = ()
    tolerances: ComparisonTolerance
    right_to_left_transform: ComparisonTransform | None = None
    scene: PlotScene | None = None

    @model_validator(mode="after")
    def _references(self) -> Self:
        if self.left.id == self.right.id:
            raise ValueError("description IDs must distinguish versions/occurrences")
        if len({p.id for p in self.pairs}) != len(self.pairs):
            raise ValueError("pair IDs must be unique")
        for pair in self.pairs:
            for description, selection in ((self.left, pair.left), (self.right, pair.right)):
                if not set(selection.call_ids) <= {r.id for r in description.plot.calls}:
                    raise ValueError("pair has dangling call IDs")
        return self


class ComparisonComponent(_Model):
    outcome: Literal["agree", "differ", "not_comparable", "unavailable"]
    reason: str
    difference: FiniteFloat | None = None
    units: str | None = None


class ComparedPair(_Model):
    id: Identifier
    left_call_ids: tuple[Identifier, ...]
    right_call_ids: tuple[Identifier, ...]
    left_sources: tuple[PlotCall, ...]
    right_sources: tuple[PlotCall, ...]
    length: ComparisonComponent
    bearing: ComparisonComponent
    displacement: ComparisonComponent
    position: ComparisonComponent
    left_displacement: XY | None = None
    right_displacement: XY | None = None


class StructuralDifference(_Model):
    kind: Literal[
        "anchor",
        "ambiguous",
        "changed",
        "unmatched_left",
        "unmatched_right",
        "reordered",
        "split_candidate",
        "merge_candidate",
    ]
    left_call_ids: tuple[Identifier, ...] = ()
    right_call_ids: tuple[Identifier, ...] = ()
    tentative: bool = True
    reason: str
    changed_fields: tuple[str, ...] = ()
    left_sources: tuple[PlotCall, ...] = ()
    right_sources: tuple[PlotCall, ...] = ()


class DescriptionComparison(_Model):
    schema_version: Literal["1.0"] = "1.0"
    algorithm_version: Literal["comparison-1.0.0"] = "comparison-1.0.0"
    input_hash: Digest
    left_id: Identifier
    right_id: Identifier
    pairs: tuple[ComparedPair, ...]
    structural: tuple[StructuralDifference, ...]
    tolerances: ComparisonTolerance
    limitations: tuple[str, ...] = (
        "Comparison criteria do not change canonical verification tolerances.",
        "Agreement does not establish the same physical or legal boundary.",
        "Structural correspondences and split/merge suggestions are tentative.",
    )
    verified_export_eligible: Literal[False] = False
    boundary_established: Literal[False] = False


class ComparisonManifest(_Model):
    schema_version: Literal["1.0"] = "1.0"
    artifact_kind: Literal["description_comparison"] = "description_comparison"
    algorithm_version: Literal["comparison-1.0.0"] = "comparison-1.0.0"
    request_file: Literal["comparison-request.json"] = "comparison-request.json"
    result_file: Literal["comparison.json"] = "comparison.json"
    request_sha256: Digest
    result_sha256: Digest
    input_hash: Digest
    left_id: Identifier
    right_id: Identifier
