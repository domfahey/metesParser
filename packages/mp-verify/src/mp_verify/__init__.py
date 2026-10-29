"""Geometric verification for metes and bounds traverses."""

from .closure import get_closure_summary, verify_closure, verify_tract
from .comparison import compare_descriptions
from .confidence import calculate_confidence_score, score_call_quality
from .diagnostics import diagnose_closure
from .plot import (
    arc_point,
    build_dashboard_plots,
    compare_points,
    derive_scenario_placement,
    prepare_plot,
    transform_point,
    validate_prepared_plot,
)
from .relative import analyze_relative

__version__ = "1.0.0"

__all__ = [
    "compare_descriptions",
    "diagnose_closure",
    "analyze_relative",
    "arc_point",
    "build_dashboard_plots",
    "compare_points",
    "derive_scenario_placement",
    "transform_point",
    "prepare_plot",
    "validate_prepared_plot",
    "calculate_confidence_score",
    "get_closure_summary",
    "score_call_quality",
    "verify_closure",
    "verify_tract",
]
