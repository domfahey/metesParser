"""Monument classification for metes and bounds legal descriptions.

Classifies survey monument types and status from text descriptions.
Regex-based, specificity-ordered pattern matching against 20+ monument types.
"""

from __future__ import annotations

import re

from mp_models import MonumentStatus, MonumentType

MONUMENT_PATTERNS: list[tuple[str, MonumentType]] = [
    (r"\btxdot\b.*\bmonument\b", "txdot_monument"),
    (r"\bcapped\s+(?:iron\s+)?rod\b", "capped_rod"),
    (r"\bcapped\s+(?:iron\s+)?pin\b", "capped_pin"),
    (r"\bcapped\s+rebar\b", "capped_rod"),
    (r"\biron\s+rod\b", "iron_rod"),
    (r"\biron\s+pin\b", "iron_pin"),
    (r"\biron\s+pipe\b", "iron_pipe"),
    (r"\biron\s+stake\b", "iron_rod"),
    (r"\biron\s+monument\b", "iron_rod"),
    (r"\brebar\b", "rebar"),
    (r"\bpk\s+nail\b", "pk_nail"),
    (r"\b(?:mag|magnetic)\s+nail\b", "nail"),
    (r"\bnail\b", "nail"),
    (r"\bhub\s+(?:and|&)\s+tack\b", "hub_and_tack"),
    (r"\bmonitoring\s+well\b", "monitoring_well"),
    (r"\brailroad\s+(?:spike|tie)\b", "railroad_spike"),
    (r"\bgin\s+(?:spike|pole)\b", "railroad_spike"),
    (r"\bstone\s+monument\b", "stone"),
    (r"\bstone\b", "stone"),
    (r"\bconcrete\s+monument\b", "concrete"),
    (r"\bconcrete\b", "concrete"),
    (r"\bbrass\s+(?:cap|marker|monument)\b", "brass_cap"),
    (r"\bwooden\s+(?:post|stake)\b", "wooden_post"),
    (r"\bhedge\s+post\b", "wooden_post"),
    (r"\bwood\s+stake\b", "wooden_post"),
    (r"\blandscap(?:e|ing)\s+(?:rod|pin)\b", "iron_rod"),
    # Natural monuments -- trees
    (
        r"\b(?:oak|hickory|elm|pine|walnut|sycamore|maple|beech|poplar|cedar|ash|birch|chestnut|cottonwood|willow|cypress)\b",
        "tree",
    ),
    (r"\btree\b", "tree"),
    # Natural monuments -- rocks
    (r"\bboulder\b", "rock"),
    (r"\brock\s+outcrop\b", "rock"),
    (r"\bstanding\s+rock\b", "rock"),
    (r"\blarge\s+rock\b", "rock"),
    # Natural features -- water/terrain
    (r"\b(?:stream|creek|river|brook|branch|run)\b", "natural_feature"),
    (r"\b(?:ridge|bluff|cliff|shoreline|lakeshore|shore)\b", "natural_feature"),
]

MONUMENT_STATUS_PATTERNS: list[tuple[str, MonumentStatus]] = [
    (r"\bfd\b", "found"),
    (r"\bfnd\b", "found"),
    (r"\bfound\b", "found"),
    (r"\bset\b", "set"),
    (r"\bplaced\b", "set"),
]


def classify_monument(text: str) -> MonumentType | None:
    """Classify monument type from text description.

    Patterns are specificity-ordered: more specific patterns (e.g.,
    "capped iron rod") are tested before general ones ("iron rod").

    Args:
        text: Text description (typically from 'to' field)

    Returns:
        Monument type literal or None if not found
    """
    if not text:
        return None

    text_lower = text.lower()

    for pattern, monument_type in MONUMENT_PATTERNS:
        if re.search(pattern, text_lower):
            return monument_type

    if re.search(r"\bmonument\b", text_lower):
        return "other"

    return None


def classify_monument_status(text: str | None) -> MonumentStatus | None:
    """Classify whether monument status indicates found or set.

    Args:
        text: Text to check for found/set keywords

    Returns:
        "found", "set", or None if no status detected
    """
    if not text:
        return None

    text_lower = text.lower()
    for pattern, status in MONUMENT_STATUS_PATTERNS:
        if re.search(pattern, text_lower):
            return status

    return None
