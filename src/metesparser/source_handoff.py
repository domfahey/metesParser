"""Compatibility facade for deterministic advisory source handoff operations."""

from mp_models.source_handoff import (
    DescriptionCandidate,
    DescriptionSelectionRecord,
    MissingSourcePage,
    SelectionSpan,
    SourceAcquisitionRecord,
    SourcePage,
    SourceReference,
    SourceUncertainty,
    TranscriptReference,
)
from mp_review.source_handoff import validate_source_bundle  # type: ignore[import-untyped]

__all__ = [
    "DescriptionCandidate",
    "DescriptionSelectionRecord",
    "MissingSourcePage",
    "SelectionSpan",
    "SourceAcquisitionRecord",
    "SourcePage",
    "SourceReference",
    "SourceUncertainty",
    "TranscriptReference",
    "validate_source_bundle",
]
