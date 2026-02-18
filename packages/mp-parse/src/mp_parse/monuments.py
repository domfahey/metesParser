"""Monument classification for metes and bounds legal descriptions.

Classifies survey monument types and status from text descriptions.
Regex-based, specificity-ordered pattern matching against 20+ monument types.
"""

from __future__ import annotations

import re

from mp_models import MonumentStatus, MonumentType

# Keep original list for backward compatibility and external consumers
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

# Performance optimization: Compile monument patterns into single regex
# Each pattern becomes a named group; we check which group matched
_MONUMENT_TYPE_MAP: dict[str, MonumentType] = {
    "txdot": "txdot_monument",
    "capped_rod": "capped_rod",
    "capped_pin": "capped_pin",
    "capped_rebar": "capped_rod",
    "iron_rod": "iron_rod",
    "iron_pin": "iron_pin",
    "iron_pipe": "iron_pipe",
    "iron_stake": "iron_rod",
    "iron_monument": "iron_rod",
    "rebar": "rebar",
    "pk_nail": "pk_nail",
    "mag_nail": "nail",
    "nail": "nail",
    "hub_tack": "hub_and_tack",
    "monitoring_well": "monitoring_well",
    "railroad_spike": "railroad_spike",
    "gin_spike": "railroad_spike",
    "stone_monument": "stone",
    "stone": "stone",
    "concrete_monument": "concrete",
    "concrete": "concrete",
    "brass_cap": "brass_cap",
    "wooden_post": "wooden_post",
    "hedge_post": "wooden_post",
    "wood_stake": "wooden_post",
    "landscaping": "iron_rod",
    "tree_species": "tree",
    "tree": "tree",
    "boulder": "rock",
    "rock_outcrop": "rock",
    "standing_rock": "rock",
    "large_rock": "rock",
    "water_feature": "natural_feature",
    "terrain_feature": "natural_feature",
}

# Build combined regex with named groups (order matters for specificity)
_COMBINED_MONUMENT_PATTERN = re.compile(
    r"(?:"
    r"(?P<txdot>\btxdot\b.*\bmonument\b)|"
    r"(?P<capped_rod>\bcapped\s+(?:iron\s+)?rod\b)|"
    r"(?P<capped_pin>\bcapped\s+(?:iron\s+)?pin\b)|"
    r"(?P<capped_rebar>\bcapped\s+rebar\b)|"
    r"(?P<iron_rod>\biron\s+rod\b)|"
    r"(?P<iron_pin>\biron\s+pin\b)|"
    r"(?P<iron_pipe>\biron\s+pipe\b)|"
    r"(?P<iron_stake>\biron\s+stake\b)|"
    r"(?P<iron_monument>\biron\s+monument\b)|"
    r"(?P<rebar>\brebar\b)|"
    r"(?P<pk_nail>\bpk\s+nail\b)|"
    r"(?P<mag_nail>\b(?:mag|magnetic)\s+nail\b)|"
    r"(?P<nail>\bnail\b)|"
    r"(?P<hub_tack>\bhub\s+(?:and|&)\s+tack\b)|"
    r"(?P<monitoring_well>\bmonitoring\s+well\b)|"
    r"(?P<railroad_spike>\brailroad\s+(?:spike|tie)\b)|"
    r"(?P<gin_spike>\bgin\s+(?:spike|pole)\b)|"
    r"(?P<stone_monument>\bstone\s+monument\b)|"
    r"(?P<stone>\bstone\b)|"
    r"(?P<concrete_monument>\bconcrete\s+monument\b)|"
    r"(?P<concrete>\bconcrete\b)|"
    r"(?P<brass_cap>\bbrass\s+(?:cap|marker|monument)\b)|"
    r"(?P<wooden_post>\bwooden\s+(?:post|stake)\b)|"
    r"(?P<hedge_post>\bhedge\s+post\b)|"
    r"(?P<wood_stake>\bwood\s+stake\b)|"
    r"(?P<landscaping>\blandscap(?:e|ing)\s+(?:rod|pin)\b)|"
    r"(?P<tree_species>\b(?:oak|hickory|elm|pine|walnut|sycamore|maple|beech|poplar|cedar|ash|birch|chestnut|cottonwood|willow|cypress)\b)|"
    r"(?P<tree>\btree\b)|"
    r"(?P<boulder>\bboulder\b)|"
    r"(?P<rock_outcrop>\brock\s+outcrop\b)|"
    r"(?P<standing_rock>\bstanding\s+rock\b)|"
    r"(?P<large_rock>\blarge\s+rock\b)|"
    r"(?P<water_feature>\b(?:stream|creek|river|brook|branch|run)\b)|"
    r"(?P<terrain_feature>\b(?:ridge|bluff|cliff|shoreline|lakeshore|shore)\b)"
    r")",
    re.IGNORECASE,
)

_FALLBACK_MONUMENT_PATTERN = re.compile(r"\bmonument\b", re.IGNORECASE)

_COMBINED_STATUS_PATTERN = re.compile(
    r"(?:\b(?:fd|fnd|found)\b)|(?:\b(?:set|placed)\b)", re.IGNORECASE
)


def classify_monument(text: str) -> MonumentType | None:
    """Classify monument type from text description.

    Optimized with single compiled regex for all patterns.
    Patterns are specificity-ordered via named groups.

    Args:
        text: Text description (typically from 'to' field)

    Returns:
        Monument type literal or None if not found
    """
    if not text:
        return None

    text_lower = text.lower()

    # Single regex match for all monument patterns
    match = _COMBINED_MONUMENT_PATTERN.search(text_lower)
    if match:
        # Find which named group matched (first one wins due to alternation order)
        for group_name, group_value in match.groupdict().items():
            if group_value is not None:
                return _MONUMENT_TYPE_MAP[group_name]

    # Fallback for generic "monument"
    if _FALLBACK_MONUMENT_PATTERN.search(text_lower):
        return "other"

    return None


def classify_monument_status(text: str | None) -> MonumentStatus | None:
    """Classify whether monument status indicates found or set.

    Optimized with single compiled regex pattern.

    Args:
        text: Text to check for found/set keywords

    Returns:
        "found", "set", or None if no status detected
    """
    if not text:
        return None

    text_lower = text.lower()
    match = _COMBINED_STATUS_PATTERN.search(text_lower)
    if not match:
        return None

    matched_text = match.group(0).lower()
    # Check for "found" keywords first
    if matched_text in ("fd", "fnd", "found"):
        return "found"
    # Check for "set" keywords
    if matched_text in ("set", "placed"):
        return "set"

    return None
