"""Multi-parcel deed separation.

Splits a legal description containing multiple parcels (e.g., "Parcel A",
"Parcel B", "Combined Legal Description") into individual parcel texts
so each can be parsed and verified independently.
"""

from __future__ import annotations

import re
from typing import TypedDict

import structlog

logger = structlog.get_logger(__name__)


class ParcelInfo(TypedDict):
    """Structured result from parcel splitting."""

    label: str
    text: str
    parcel_type: str


class ParcelMarker(TypedDict):
    """Detected parcel delimiter in text."""

    label: str
    position: int
    marker_type: str


# ---------------------------------------------------------------------------
# Marker patterns — standalone compiled regexes
# ---------------------------------------------------------------------------

# Lettered parcels: "Parcel A:", "Parcel A (Northern Tract):", "Parcel A -"
_LETTERED_PARCEL = re.compile(
    r"\bParcel\s+([A-Z])\s*(?:\([^)]*\)\s*)?(?:[:;\-\u2013\u2014])",
    re.IGNORECASE,
)

# Numbered parcels: "Parcel 1:", "Parcel 2:", "Parcel 10 -"
_NUMBERED_PARCEL = re.compile(
    r"\bParcel\s+(\d+)\s*(?:\([^)]*\)\s*)?(?:[:;\-\u2013\u2014])",
    re.IGNORECASE,
)

# Combined / aggregate description: "Combined Legal Description:" or
# "Combine Legal Description:" (the ground truth uses the typo "Combine")
_COMBINED_DESCRIPTION = re.compile(
    r"\bCombine[d]?\s+Legal\s+Description\s*[:;\-\u2013\u2014]",
    re.IGNORECASE,
)

# "ALSO:" or "ALSO DESCRIBED AS:"
_ALSO_MARKER = re.compile(
    r"\bALSO(?:\s+DESCRIBED\s+AS)?\s*:",
    re.IGNORECASE,
)

# "TOGETHER WITH:"
_TOGETHER_WITH_MARKER = re.compile(
    r"\bTOGETHER\s+WITH\s*:",
    re.IGNORECASE,
)


def detect_parcel_markers(text: str) -> list[ParcelMarker]:
    """Detect parcel delimiter positions in text.

    Returns a list of dicts sorted by position:
    [
        {"label": "Parcel A", "position": 123, "marker_type": "lettered"},
        {"label": "Parcel B", "position": 456, "marker_type": "lettered"},
    ]

    If no parcel markers are found, returns an empty list.
    """
    markers: list[ParcelMarker] = []

    # Lettered parcels
    for match in _LETTERED_PARCEL.finditer(text):
        letter = match.group(1).upper()
        markers.append(
            {
                "label": f"Parcel {letter}",
                "position": match.start(),
                "marker_type": "lettered",
            }
        )

    # Numbered parcels
    for match in _NUMBERED_PARCEL.finditer(text):
        number = match.group(1)
        markers.append(
            {
                "label": f"Parcel {number}",
                "position": match.start(),
                "marker_type": "numbered",
            }
        )

    # Combined / aggregate description
    for match in _COMBINED_DESCRIPTION.finditer(text):
        # Preserve the exact label from the text (Combine vs Combined)
        raw = match.group(0).rstrip(":;-\u2013\u2014 ")
        markers.append(
            {
                "label": raw.strip(),
                "position": match.start(),
                "marker_type": "combined",
            }
        )

    # "ALSO:" / "ALSO DESCRIBED AS:"
    for match in _ALSO_MARKER.finditer(text):
        raw = match.group(0).rstrip(": ")
        markers.append(
            {
                "label": raw.strip(),
                "position": match.start(),
                "marker_type": "additional",
            }
        )

    # "TOGETHER WITH:"
    for match in _TOGETHER_WITH_MARKER.finditer(text):
        raw = match.group(0).rstrip(": ")
        markers.append(
            {
                "label": raw.strip(),
                "position": match.start(),
                "marker_type": "appurtenant",
            }
        )

    # Sort by position so they appear in document order
    markers.sort(key=lambda m: m["position"])

    return markers


def _marker_type_to_parcel_type(marker_type: str) -> str:
    """Map a marker_type to a parcel_type for the output dict."""
    mapping = {
        "lettered": "primary",
        "numbered": "primary",
        "combined": "combined",
        "additional": "additional",
        "appurtenant": "appurtenant",
    }
    return mapping.get(marker_type, "primary")


def split_into_parcels(text: str) -> list[ParcelInfo]:
    """Split a legal description into separate parcels.

    Returns a list of ParcelInfo dicts:
    [
        {"label": "Parcel A", "text": "...", "parcel_type": "primary"},
        {"label": "Parcel B", "text": "...", "parcel_type": "primary"},
        {"label": "Combined Legal Description", "text": "...", "parcel_type": "combined"},
    ]

    If no parcel markers are found, returns the entire text as a single parcel
    with label "Parcel 1" and parcel_type "primary".
    """
    markers = detect_parcel_markers(text)

    if not markers:
        return [ParcelInfo(label="Parcel 1", text=text, parcel_type="primary")]

    logger.debug(
        "parcel_markers_detected", count=len(markers), labels=[m["label"] for m in markers]
    )

    parcels: list[ParcelInfo] = []

    # If the first marker is not at the very beginning and the text before it
    # contains substantive content (not just a header), create a preamble parcel.
    # This handles cases like "Main parcel description.\nALSO: Second parcel."
    first_marker = markers[0]
    if first_marker["position"] > 0:
        preamble = text[: first_marker["position"]].strip()
        if preamble and first_marker["marker_type"] in ("additional", "appurtenant"):
            # Text before ALSO/TOGETHER WITH is the main parcel
            parcels.append(
                {
                    "label": "Parcel 1",
                    "text": preamble,
                    "parcel_type": "primary",
                }
            )

    for i, marker in enumerate(markers):
        # Start of this parcel's text is after the marker delimiter
        # Find the end of the marker pattern to get the text start
        marker_pos = marker["position"]

        # Re-match at the exact position to find the end of the marker
        # We search from marker_pos onward and take the first match
        text_start = _find_marker_end(text, marker_pos)

        # End of this parcel's text is the start of the next marker
        if i + 1 < len(markers):
            text_end = markers[i + 1]["position"]
        else:
            text_end = len(text)

        parcel_text = text[text_start:text_end].strip()

        parcels.append(
            {
                "label": marker["label"],
                "text": parcel_text,
                "parcel_type": _marker_type_to_parcel_type(marker["marker_type"]),
            }
        )

    return parcels


def _find_marker_end(text: str, start_pos: int) -> int:
    """Find where the marker pattern ends so we can extract the text after it.

    Searches all marker patterns starting from start_pos and returns the
    end position of the first match that begins at start_pos.
    """
    patterns = [
        _LETTERED_PARCEL,
        _NUMBERED_PARCEL,
        _COMBINED_DESCRIPTION,
        _ALSO_MARKER,
        _TOGETHER_WITH_MARKER,
    ]

    for pattern in patterns:
        match = pattern.search(text, pos=start_pos)
        if match and match.start() == start_pos:
            return match.end()

    # This indicates a bug: detect_parcel_markers found a marker but
    # _find_marker_end cannot re-match it at this position.
    logger.warning(
        "parcel_marker_rematch_failed",
        start_pos=start_pos,
        text_preview=text[start_pos : start_pos + 50],
    )

    return start_pos
