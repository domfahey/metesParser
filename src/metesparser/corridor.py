"""Compatibility facade for advisory, source-bound corridor geometry."""

from mp_models.corridor import (
    CorridorBoundaryEdge,
    CorridorErrorBudget,
    CorridorErrorReport,
    CorridorManifest,
    CorridorRequest,
    CorridorResult,
    CorridorStation,
    CorridorWidthInterval,
)
from mp_review.corridor import (
    analyze_corridor_file,
    replay_corridor,
)
from mp_verify.corridor import analyze_corridor, validate_corridor_result

__all__ = [
    "CorridorBoundaryEdge",
    "CorridorErrorBudget",
    "CorridorErrorReport",
    "CorridorManifest",
    "CorridorRequest",
    "CorridorResult",
    "CorridorStation",
    "CorridorWidthInterval",
    "analyze_corridor",
    "analyze_corridor_file",
    "replay_corridor",
    "validate_corridor_result",
]
