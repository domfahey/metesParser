"""Reservations and exceptions of rights, which are never land exceptions (PR #60 round 59).

A reserved or excepted *right* (mineral, oil, gas and coal rights, an easement or right
of way not described by courses, rights of the public, riparian, water and air rights)
removes no land from the parcel. Its wording is kept, but it is not an unapplied land
exception and must not block verification, whether it comes before the description
(``tracts._rights_recital``) or after the boundary (``calls._set_aside_non_boundary_text``).

``is_rights_clause`` takes the wording after an exception/reservation lead;
``is_rights_reservation`` takes the whole clause, lead included. Both reuse
``tracts._RIGHTS_RECITAL`` and fail closed: any land noun, dimension or portion in the
clause keeps it a land exception.
"""

from __future__ import annotations

import re

from .tracts import _LAND_NOUN, _RIGHTS_RECITAL

# The verb(s) of a reservation or exception: "EXCEPTING", "SAVE AND EXCEPT", "EXCEPTING AND
# RESERVING", "RESERVING", "EXCEPT AND RESERVE", optionally "therefrom"/"thereout and
# therefrom" and "as to".
_VERB = r"(?:EXCEPT(?:ING|ED)?|RESERV(?:E|ING|ED)|SAV(?:E|ING))"
_RESERVATION_LEAD = re.compile(
    r"\s*(?:(?:ALSO|AND|BUT)\s+)?(?:(?:LESS|SAVE)\s+AND\s+)?" + _VERB + r"\b"
    r"(?:\s+(?:AND|OR)\s+" + _VERB + r"\b)?"
    r"(?:\s+(?:there|here)(?:from|out|of)\b(?:\s+and\s+(?:there|here)(?:from|out|of)\b)?)?"
    r"(?:\s+as\s+to\b)?",
    re.IGNORECASE,
)
# Rights ``_RIGHTS_RECITAL`` does not name: a single easement or right of way, water, air
# and similar rights ("unto the Grantor an easement for ingress and egress").
_RESERVEE = r"(?:(?:unto|to|for)\s+[^,:;]{0,80}?(?:,\s*|\s+(?=(?:an?|the|all|any|its|their)\b)))?"
_OTHER_RIGHTS = re.compile(
    r"[\s,]*" + _RESERVEE + r"(?:(?:all|any|an?|the|its|their|such|said)\s+)*"
    r"(?:[\w-]+,?\s+(?:(?:and|or|&)\s+)?){0,3}?"
    r"(?:(?:riparian|water|air|surface|subsurface|mineral|mining|development|access|ingress"
    r"|egress|passage|view)\s+rights?\b"
    r"|easements?\b|rights?[\s-]+of[\s-]+(?:way|ingress|egress|access|passage)\b"
    r"|rights?\s+of\s+the\s+public\b)",
    re.IGNORECASE,
)
# Land nouns that only locate the rights ("minerals in and under the premises") name no land.
_LOCATOR = re.compile(
    r"\b(?:in|on|under|beneath|underlying|upon)\s+(?:and\s+(?:under|beneath|upon)\s+)?"
    r"(?:so\s+much\s+of\s+)?(?:the|said|such|this)\s+(?:above\s+described\s+|aforesaid\s+)?"
    r"(?:premises|lands?|property)\b",
    re.IGNORECASE,
)
# A measured extent: a width, area or any stated feet names land taken out.
_DIMENSION = re.compile(
    r"\d[\d,.]*\s*(?:feet|foot|ft\b|acres?|sq\b|square|['’′])|\b(?:wide|width)\b",
    re.IGNORECASE,
)
_PORTION = re.compile(r"\b(?:portions?|parts?)\b", re.IGNORECASE)


def is_rights_clause(clause: str) -> bool:
    """Return whether ``clause`` (the wording after an exception/reservation lead) is rights only.

    ``tracts._RIGHTS_RECITAL`` or a single easement, right of way, or water/air right
    leads it, and the clause names no land: no land noun (``tracts._LAND_NOUN``), no
    stated dimension and no portion ("any portion lying within the bed of Main Street"
    removes land and stays an exception).
    """
    clause = clause.strip(" \t\r\n.;,:")
    if not clause or _DIMENSION.search(clause):
        return False
    for pattern in (_RIGHTS_RECITAL, _OTHER_RIGHTS):
        match = pattern.match(clause)
        if match is None or _PORTION.search(clause):
            continue
        if _LAND_NOUN.search(_LOCATOR.sub(" ", clause)) is None:
            return True
    return False


def is_rights_reservation(wording: str) -> bool:
    """Return whether the stated exception/reservation ``wording`` reserves only rights."""
    lead = _RESERVATION_LEAD.match(wording)
    return lead is not None and is_rights_clause(wording[lead.end() :])
