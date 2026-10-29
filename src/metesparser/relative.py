"""Compatibility facade for deterministic, non-verifying local-angle analysis."""

from mp_models.relative import (
    LocalFrame,
    RelativeAnalysisResult,
    RelativeConstraint,
    RelativeCourse,
    RelativeCourseGeometry,
    RelativeDescription,
    RelativeIssue,
    RelativeSource,
)
from mp_verify.relative import analyze_relative

__all__ = [
    "LocalFrame",
    "RelativeAnalysisResult",
    "RelativeConstraint",
    "RelativeCourse",
    "RelativeCourseGeometry",
    "RelativeDescription",
    "RelativeIssue",
    "RelativeSource",
    "analyze_relative",
]
