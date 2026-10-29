"""Deterministic text-first deed review."""

from .api import ENGINE_VERSION, replay_review, review_file, review_text, verify_file
from .artifact_inspect import inspect_artifacts
from .comparison import compare_descriptions_file
from .dashboard import dashboard_file, prepare_dashboard
from .diagnostics import diagnose_closure_file
from .mapbox_mcp import mapbox_mcp_file
from .online_map import render_map_file
from .plot import plot_file
from .relative import review_relative_file
from .revision_view import render_revision_file
from .revisions import import_revision, load_revision, publish_revision
from .source_handoff import validate_source_bundle
from .webmap import PreparedWebMap, prepare_web_map

__version__ = ENGINE_VERSION
__all__ = [
    "compare_descriptions_file",
    "render_revision_file",
    "import_revision",
    "load_revision",
    "publish_revision",
    "inspect_artifacts",
    "diagnose_closure_file",
    "validate_source_bundle",
    "replay_review",
    "dashboard_file",
    "render_map_file",
    "mapbox_mcp_file",
    "prepare_dashboard",
    "prepare_web_map",
    "PreparedWebMap",
    "plot_file",
    "review_text",
    "review_file",
    "verify_file",
    "review_relative_file",
]
