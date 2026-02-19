"""Pydantic schemas for metes and bounds deed parsing."""

from .audit import (
    AuditContext,
    CallAudit,
    Decision,
    ExtractionRecord,
    RunMetadata,
    Transformation,
    VerificationAudit,
)
from .base import _Model
from .closure import CheckResult, ClosureResult, Point
from .constants import PERMANENT_MONUMENTS, PRIOR_CONVEYANCE_SIGNALS
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
from .tract import Tract, TractType
from .units import ConversionFactors, DistanceUnit

__version__ = "1.0.0"

__all__ = [
    "AuditContext",
    "CallAudit",
    "CheckResult",
    "ClosureResultMessage",
    "ClosureResult",
    "ConversionFactors",
    "CurveDirection",
    "CurveType",
    "Decision",
    "DeedCall",
    "DeedClause",
    "DistanceUnit",
    "ExtractionRecord",
    "LegalDescription",
    "LegalDescriptionMessage",
    "MessageType",
    "MonumentStatus",
    "MonumentType",
    "PERMANENT_MONUMENTS",
    "PRIOR_CONVEYANCE_SIGNALS",
    "Point",
    "RawTextMessage",
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
