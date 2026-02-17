"""Rule-based parsing for metes and bounds legal descriptions."""

from .calls import (
    enrich_calls_with_azimuths,
    extract_calls,
    extract_curve_info,
    extract_direction,
    extract_distance_alternate,
    extract_single_call,
    mark_tie_in_calls,
)
from .monuments import (
    MONUMENT_PATTERNS,
    MONUMENT_STATUS_PATTERNS,
    classify_monument,
    classify_monument_status,
)
from .numbers import COMMA_NUMBER, parse_comma_number

__version__ = "1.0.0"

__all__ = [
    "COMMA_NUMBER",
    "MONUMENT_PATTERNS",
    "MONUMENT_STATUS_PATTERNS",
    "classify_monument",
    "classify_monument_status",
    "enrich_calls_with_azimuths",
    "extract_calls",
    "extract_curve_info",
    "extract_direction",
    "extract_distance_alternate",
    "extract_single_call",
    "mark_tie_in_calls",
    "parse_comma_number",
]
