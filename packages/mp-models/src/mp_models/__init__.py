"""Pydantic schemas for metes and bounds deed parsing."""

from .audit import (
    AuditContext,
    CallAudit,
    Decision,
    ExtractionRecord,
    LLMStageRecord,
    RunMetadata,
    Transformation,
    VerificationAudit,
)
from .base import _Model
from .closure import CheckResult, ClosureResult, Point
from .constants import PERMANENT_MONUMENTS, PRIOR_CONVEYANCE_SIGNALS
from .dashboard import DashboardBundle, DashboardManifest, DashboardResult, PreparedDashboard
from .deed_call import (
    CurveDirection,
    CurveType,
    DeedCall,
    DeedClause,
    MonumentStatus,
    MonumentType,
    SubdivisionReference,
)
from .envelope import (
    ClosureResultMessage,
    LegalDescriptionMessage,
    MessageType,
    RawTextMessage,
    parse_message,
    read_jsonl,
    write_jsonl,
)
from .legal_description import LegalDescription
from .logging import configure_logging, get_log_format
from .plot import (
    DashboardPlots,
    MapSource,
    PlotComparison,
    PlotComparisonSpec,
    PlotGeometry,
    PlotPlacement,
    PlotPrimitive,
    PlotScene,
    PlotView,
    PointCorrespondence,
    VectorLayer,
)
from .plot_request import PlotCall, PlotRequest, PreparedPlot
from .raster import RasterControl, RasterLayer, RasterRegistration, RasterResidual
from .relative import (
    LocalFrame,
    RelativeAnalysisResult,
    RelativeConstraint,
    RelativeCourse,
    RelativeCourseGeometry,
    RelativeDescription,
    RelativeIssue,
    RelativeSource,
)
from .tract import Tract, TractType
from .units import ConversionFactors, DistanceUnit
from .webmap import (
    MapboxViewOptions,
    StandaloneWebMapInput,
    WebMapArtifact,
    WebMapOptions,
    WebMapRequest,
)

__version__ = "1.0.0"

__all__ = [
    "MapboxViewOptions",
    "StandaloneWebMapInput",
    "WebMapArtifact",
    "WebMapOptions",
    "WebMapRequest",
    "RasterControl",
    "RasterLayer",
    "RasterRegistration",
    "RasterResidual",
    "AuditContext",
    "CallAudit",
    "CheckResult",
    "ClosureResultMessage",
    "ClosureResult",
    "ConversionFactors",
    "CurveDirection",
    "CurveType",
    "DashboardBundle",
    "DashboardPlots",
    "MapSource",
    "PlotComparison",
    "PlotComparisonSpec",
    "PlotGeometry",
    "PlotCall",
    "PlotRequest",
    "PreparedPlot",
    "PlotPlacement",
    "PlotPrimitive",
    "PlotScene",
    "PlotView",
    "PointCorrespondence",
    "VectorLayer",
    "DashboardManifest",
    "DashboardResult",
    "Decision",
    "DeedCall",
    "DeedClause",
    "DistanceUnit",
    "ExtractionRecord",
    "LLMStageRecord",
    "LegalDescription",
    "LegalDescriptionMessage",
    "LocalFrame",
    "MessageType",
    "MonumentStatus",
    "MonumentType",
    "PERMANENT_MONUMENTS",
    "PRIOR_CONVEYANCE_SIGNALS",
    "Point",
    "PreparedDashboard",
    "RawTextMessage",
    "RelativeAnalysisResult",
    "RelativeConstraint",
    "RelativeCourse",
    "RelativeCourseGeometry",
    "RelativeDescription",
    "RelativeIssue",
    "RelativeSource",
    "RunMetadata",
    "SubdivisionReference",
    "Tract",
    "TractType",
    "Transformation",
    "VerificationAudit",
    "_Model",
    "configure_logging",
    "get_log_format",
    "parse_message",
    "read_jsonl",
    "write_jsonl",
]
