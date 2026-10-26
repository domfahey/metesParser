"""Compatibility facade for validated, non-verifying dashboard rendering."""

from mp_export.dashboard_html import render_dashboard  # type: ignore[import-untyped]
from mp_models.dashboard import (
    DashboardBundle,
    DashboardManifest,
    DashboardResult,
    PreparedDashboard,
)
from mp_review.dashboard import dashboard_file, prepare_dashboard  # type: ignore[import-untyped]

__all__ = [
    "DashboardBundle",
    "DashboardManifest",
    "DashboardResult",
    "PreparedDashboard",
    "dashboard_file",
    "prepare_dashboard",
    "render_dashboard",
]
