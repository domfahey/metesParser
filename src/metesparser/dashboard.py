"""Compatibility facade for validated, non-verifying dashboard rendering."""

from mp_export.dashboard_html import render_dashboard
from mp_export.mapbox_mcp import build_mapbox_mcp_handoff
from mp_export.online_map_html import render_online_map
from mp_models.dashboard import (
    DashboardBundle,
    DashboardManifest,
    DashboardResult,
    PreparedDashboard,
)
from mp_models.webmap import (
    MapboxViewOptions,
    StandaloneWebMapInput,
    WebMapArtifact,
    WebMapOptions,
    WebMapRequest,
)
from mp_review.dashboard import dashboard_file, prepare_dashboard  # type: ignore[import-untyped]
from mp_review.mapbox_mcp import mapbox_mcp_file  # type: ignore[import-untyped]
from mp_review.online_map import render_map_file  # type: ignore[import-untyped]
from mp_review.webmap import PreparedWebMap, prepare_web_map  # type: ignore[import-untyped]

__all__ = [
    "DashboardBundle",
    "DashboardManifest",
    "DashboardResult",
    "PreparedDashboard",
    "dashboard_file",
    "build_mapbox_mcp_handoff",
    "mapbox_mcp_file",
    "prepare_dashboard",
    "render_dashboard",
    "MapboxViewOptions",
    "WebMapArtifact",
    "WebMapOptions",
    "WebMapRequest",
    "StandaloneWebMapInput",
    "render_map_file",
    "PreparedWebMap",
    "prepare_web_map",
    "render_online_map",
]
