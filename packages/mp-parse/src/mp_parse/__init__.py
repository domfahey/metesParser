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
from .metadata import detect_strip_exceptions, remove_strip_exceptions
from .monuments import (
    MONUMENT_PATTERNS,
    MONUMENT_STATUS_PATTERNS,
    classify_monument,
    classify_monument_status,
)
from .normalizer import expand_assessor_abbreviations
from .numbers import COMMA_NUMBER, parse_comma_number
from .parcels import ParcelInfo, ParcelMarker, detect_parcel_markers, split_into_parcels
from .tracts import split_into_tracts

__version__ = "2.0.0"

__all__ = [
    "COMMA_NUMBER",
    "MONUMENT_PATTERNS",
    "MONUMENT_STATUS_PATTERNS",
    "ParcelInfo",
    "ParcelMarker",
    "classify_monument",
    "classify_monument_status",
    "detect_parcel_markers",
    "detect_strip_exceptions",
    "enrich_calls_with_azimuths",
    "expand_assessor_abbreviations",
    "extract_calls",
    "extract_curve_info",
    "extract_direction",
    "extract_distance_alternate",
    "extract_single_call",
    "mark_tie_in_calls",
    "parse_comma_number",
    "remove_strip_exceptions",
    "split_into_parcels",
    "split_into_tracts",
]
