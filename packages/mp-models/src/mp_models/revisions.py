"""Versioned, baseline-bound alternatives; raw drafts never imply valid geometry."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from .base import _Model
from .comparison import DescriptionComparison
from .corridor import CorridorRequest, CorridorResult
from .dashboard import DashboardBundle, DashboardEdit, Digest, Identifier
from .deed_call import DeedCall
from .plot_request import PreparedPlot


class _RevisionModel(_Model):
    model_config = ConfigDict(str_strip_whitespace=False, revalidate_instances="always")

    @field_validator("*")
    @classmethod
    def _unicode(cls, value: Any) -> Any:
        def check(item: Any) -> None:
            if isinstance(item, str):
                try:
                    item.encode("utf-8")
                except UnicodeEncodeError as exc:
                    raise ValueError("Revision strings require Unicode scalar values") from exc
            elif isinstance(item, dict):
                for key, member in item.items():
                    check(key)
                    check(member)
            elif isinstance(item, (tuple, list)):
                for member in item:
                    check(member)

        check(value)
        return value


class RevisionBaseline(_RevisionModel):
    id: Identifier
    bundle_sha256: Digest


class RevisionSourceRef(_RevisionModel):
    page_id: Identifier
    quote: str = Field(min_length=1)

    @model_validator(mode="after")
    def _quote(self) -> Self:
        if not self.quote.strip():
            raise ValueError("source quote must not be blank")
        return self


class RevisionCallDraft(_RevisionModel):
    call_id: Identifier
    occurrence_id: Identifier
    tract_id: Identifier
    document_id: Identifier
    action: Literal["update", "remove", "add"] = "update"
    page_id: Identifier | None = None
    structured_input: dict[str, str] | None = None
    raw_fields: dict[str, str] = Field(default_factory=dict)
    rationale: str = ""
    evidence_ids: tuple[Identifier, ...] = ()
    source_refs: tuple[RevisionSourceRef, ...] = ()

    @model_validator(mode="after")
    def _fields(self) -> Self:
        supported = {"distance_ft", "bearing_azimuth_deg_from_north", "interior_angle_deg", "notes"}
        if set(self.raw_fields) - supported:
            raise ValueError("unsupported revision raw field")
        if self.structured_input is not None and self.raw_fields:
            raise ValueError("use structured input or legacy patches, not both")
        if self.action == "add" and self.structured_input is None:
            raise ValueError("added calls require a complete structured input or recoverable draft")
        if self.action == "remove" and self.raw_fields:
            raise ValueError("explicit remove cannot also edit fields")
        return self


class RevisionTract(_RevisionModel):
    id: Identifier
    occurrence_id: Identifier
    document_ids: tuple[Identifier, ...] = Field(min_length=1)
    label: str
    call_order: tuple[Identifier, ...]
    action: Literal["retain", "remove"] = "retain"


class RevisionCorridor(_RevisionModel):
    """Exact corridor request text carried as part of a revision inventory."""

    id: Identifier
    action: Literal["retain", "remove"] = "retain"
    raw_request_json: str


class DashboardRevision(_RevisionModel):
    schema_version: Literal["1.0", "1.1", "1.2"] = "1.0"
    id: Identifier
    generation: int = Field(default=0, ge=0, strict=True)
    parent_revision_id: Identifier | None = None
    baseline: RevisionBaseline
    kind: Literal["scenario", "source_correction"] = "scenario"
    label: str
    rationale: str = ""
    tracts: tuple[RevisionTract, ...] = Field(min_length=1)
    edits: tuple[RevisionCallDraft, ...] = ()
    corridors: tuple[RevisionCorridor, ...] = ()

    @model_validator(mode="after")
    def _unique(self) -> Self:
        if len({t.occurrence_id for t in self.tracts}) != len(self.tracts):
            raise ValueError("duplicate tract occurrence identity")
        if len({e.call_id for e in self.edits}) != len(self.edits):
            raise ValueError("duplicate edited call identity")
        if any(len(set(t.call_order)) != len(t.call_order) for t in self.tracts):
            raise ValueError("duplicate call identity in tract")
        if self.corridors and self.schema_version != "1.2":
            raise ValueError("saved corridor definitions require revision schema 1.2")
        if len({corridor.id for corridor in self.corridors}) != len(self.corridors):
            raise ValueError("duplicate revision corridor identity")
        if self.parent_revision_id == self.id:
            raise ValueError("revision cannot be its own parent")
        return self


class RevisionError(_RevisionModel):
    call_id: Identifier | None = None
    corridor_id: Identifier | None = None
    field: str
    message: str


class PreparedRevisionCorridor(_RevisionModel):
    """Fresh corridor replay tied to the stable corridor identity in a revision."""

    id: Identifier
    state: Literal["computed", "draft"]
    request: CorridorRequest | None = None
    result: CorridorResult | None = None
    reasons: tuple[str, ...] = ()


class RevisionGeometry(_RevisionModel):
    revision_id: Identifier
    calculation_id: Identifier
    plot: PreparedPlot


class RevisionSourceChange(_RevisionModel):
    call_id: Identifier
    previous_quote: str
    revised_quote: str
    previous_call: DeedCall | None
    revised_call: DeedCall | None
    source_refs: tuple[RevisionSourceRef, ...]


class RevisionComparison(_RevisionModel):
    id: Identifier
    revision_id: Identifier
    comparison: DescriptionComparison | None = None
    unavailable_reason: str | None = None

    @model_validator(mode="after")
    def _outcome(self) -> Self:
        if (self.comparison is None) == (self.unavailable_reason is None):
            raise ValueError("Revision comparison requires a result or unavailable reason")
        return self


class RevisionPreparedCall(_RevisionModel):
    id: Identifier
    occurrence_id: Identifier
    tract_id: Identifier
    document_id: Identifier
    page_id: Identifier | None = None
    call: DeedCall | None = None
    role: Literal["boundary", "tie_in", "reference", "omitted"] = "boundary"
    removed: bool = False
    quote: str | None = None
    source_refs: tuple[RevisionSourceRef, ...] = ()
    source_status: Literal["recorded", "hypothetical", "source_correction"]
    original_source: dict[str, Any] | None = None
    raw_input: dict[str, str] | None = None


class PreparedRevision(_RevisionModel):
    schema_version: Literal["1.0"] = "1.0"
    revision: DashboardRevision
    state: Literal["parsed", "draft"]
    errors: tuple[RevisionError, ...] = ()
    parsed_edits: tuple[DashboardEdit, ...] = ()
    prepared_calls: tuple[RevisionPreparedCall, ...] = ()
    current_geometry: tuple[RevisionGeometry, ...] = ()
    last_valid_geometry: tuple[RevisionGeometry, ...] = ()
    source_changes: tuple[RevisionSourceChange, ...] = ()
    comparisons: tuple[RevisionComparison, ...] = ()
    corridor_results: tuple[PreparedRevisionCorridor, ...] = ()
    # A separate explicit verification/export request is always necessary.
    exportable: Literal[False] = False
    canonical_status_changed: Literal[False] = False
    invalidated_dependencies: tuple[str, ...] = (
        "placements",
        "comparisons",
        "exports",
        "canonical_verification",
    )


def bind_baseline(bundle: DashboardBundle, baseline_id: str = "baseline") -> RevisionBaseline:
    """Hash the complete validated baseline, never labels or heuristic call matches."""
    validated = DashboardBundle.model_validate(bundle.model_dump(mode="json"))
    payload = json.dumps(
        validated.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return RevisionBaseline(
        id=baseline_id, bundle_sha256=hashlib.sha256(payload.encode("utf-8")).hexdigest()
    )


def revision_template(
    bundle: DashboardBundle,
    *,
    revision_id: str = "revision-1",
    baseline_id: str = "baseline",
    generation: int = 0,
    label: str = "Working alternative",
) -> DashboardRevision:
    """Pure template helper usable by renderers without depending on review adapters."""
    pages = {p.id: p for p in bundle.pages}
    parcels = {p.id: p for p in bundle.parcels}
    return DashboardRevision(
        id=revision_id,
        generation=generation,
        baseline=bind_baseline(bundle, baseline_id),
        label=label,
        tracts=tuple(
            RevisionTract(
                id=o.parcel_id,
                occurrence_id=o.id,
                label=parcels[o.parcel_id].label,
                document_ids=tuple(dict.fromkeys(pages[p].document_id for p in o.page_ids)),
                call_order=tuple(c.id for c in bundle.calls if c.occurrence_id == o.id),
            )
            for o in bundle.occurrences
        ),
    )


class RevisionManifest(_RevisionModel):
    schema_version: Literal["1.0"] = "1.0"
    save_state: Literal["published"] = "published"
    revision_id: Identifier
    generation: int = Field(ge=0, strict=True)
    baseline: RevisionBaseline
    revision_hash: Digest
    artifacts: dict[str, Digest]
