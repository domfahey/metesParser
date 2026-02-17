"""Geometric verification for metes and bounds traverses."""

from .closure import get_closure_summary, verify_closure
from .confidence import calculate_confidence_score, score_call_quality

__version__ = "1.0.0"

__all__ = [
    "calculate_confidence_score",
    "get_closure_summary",
    "score_call_quality",
    "verify_closure",
]
