"""Read-only artifact inventory; usability never substitutes for source accuracy."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

InspectionStage = Literal[
    "convert",
    "extract",
    "verify",
    "review",
    "plot",
    "dashboard",
    "render-map",
    "compare-descriptions",
]
ArtifactStatus = Literal[
    "present_valid", "missing", "stale", "invalid", "unverifiable", "blocked", "not_requested"
]


class InspectionReason(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: str
    message: str
    path: str | None = None
    dependency_id: str | None = None
    artifact_id: str | None = None


class InspectedArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    kind: str
    stage: InspectionStage
    path: str
    status: ArtifactStatus
    local_status: ArtifactStatus
    dependency_ids: tuple[str, ...] = ()
    reasons: tuple[InspectionReason, ...] = ()
    identities: dict[str, Any] = Field(default_factory=dict)
    recorded_canonical_status: str | None = None
    limitations: tuple[str, ...] = ()


class InspectedStage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    stage: InspectionStage
    status: ArtifactStatus
    artifact_ids: tuple[str, ...] = ()
    dependency_ids: tuple[str, ...] = ()
    reasons: tuple[InspectionReason, ...] = ()


class ArtifactInspection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0"] = "1.0"
    operation: Literal["inspect-artifacts"] = "inspect-artifacts"
    status: Literal["needs_review", "error"] = "needs_review"
    bundle_root: str
    requested_stage: InspectionStage
    artifacts: tuple[InspectedArtifact, ...] = ()
    stages: tuple[InspectedStage, ...] = ()
    earliest_invalid_stage: InspectionStage | None = None
    required_inputs: tuple[str, ...] = ()
    recommendations: tuple[dict[str, Any], ...] = ()
    limitations: tuple[str, ...] = ()
    errors: tuple[InspectionReason, ...] = ()
