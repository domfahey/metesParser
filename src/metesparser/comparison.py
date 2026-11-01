"""Compatibility facade for source-linked advisory description comparison."""

from mp_models.comparison import (
    BearingBasis,
    CircularArcComparison,
    ComparedPair,
    ComparisonComponent,
    ComparisonDescription,
    ComparisonManifest,
    ComparisonPair,
    ComparisonRequest,
    ComparisonSelection,
    ComparisonTolerance,
    ComparisonTransform,
    DescriptionComparison,
    StructuralDifference,
)
from mp_review.comparison import compare_descriptions_file
from mp_verify.comparison import compare_descriptions

__all__ = [
    "BearingBasis",
    "CircularArcComparison",
    "ComparedPair",
    "ComparisonComponent",
    "ComparisonDescription",
    "ComparisonManifest",
    "ComparisonPair",
    "ComparisonRequest",
    "ComparisonSelection",
    "ComparisonTolerance",
    "ComparisonTransform",
    "DescriptionComparison",
    "StructuralDifference",
    "compare_descriptions",
    "compare_descriptions_file",
]
