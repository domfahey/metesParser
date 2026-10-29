"""Compatibility facade for source-linked, non-verifying plotting geometry."""

from mp_models.plot import DashboardPlots, PlotGeometry, PlotPlacement, PlotScene
from mp_models.plot_request import PlotCall, PlotRequest, PreparedPlot
from mp_review.plot import plot_file  # type: ignore[import-untyped]
from mp_verify.plot import (
    arc_point,
    build_dashboard_plots,
    compare_points,
    derive_scenario_placement,
    prepare_plot,
    transform_point,
    unit_factor,
    validate_prepared_plot,
)

__all__ = [
    "DashboardPlots",
    "PlotGeometry",
    "PlotCall",
    "PlotPlacement",
    "PlotScene",
    "PlotRequest",
    "PreparedPlot",
    "arc_point",
    "build_dashboard_plots",
    "compare_points",
    "derive_scenario_placement",
    "plot_file",
    "prepare_plot",
    "transform_point",
    "unit_factor",
    "validate_prepared_plot",
]
