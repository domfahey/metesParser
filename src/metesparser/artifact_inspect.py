"""Compatibility facade for bounded read-only artifact inspection."""

from mp_models.artifact_inspection import (
    ArtifactInspection,
    InspectedArtifact,
    InspectedStage,
    InspectionReason,
)
from mp_review.artifact_inspect import inspect_artifacts  # type: ignore[import-untyped]

__all__ = [
    "ArtifactInspection",
    "InspectedArtifact",
    "InspectedStage",
    "InspectionReason",
    "inspect_artifacts",
]
