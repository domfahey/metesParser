"""One length-unit vocabulary shared by course and curve-element length parsing."""

from __future__ import annotations

# A number directly after a degree sign (or digit/point/comma) is a bearing's
# minutes or part of a larger number, never a length.
LENGTH_NUMBER_GUARD = r"(?<![\d.,\u00b0])(?<!\u00b0\s)"
FOOT_MARKS = ("'", "\u2032")

UNIT_TOKEN = (
    r"(?:US\s+survey\s+(?:feet|foot)|engineer\s+chains?|engineer\s+links?"
    r"|feet|foot|ft|poles?|rods?|perch(?:es)?|chains?|links?"
    r"|varas?|arpents?|toises?|furlongs?|meters?|miles?)"
)
# The one unit grammar of every curve-element length (radius, chord, arc, radial):
# each unit the distance converter supports, metric spellings and the foot marks
# ' and \u2032 (a doubled mark is seconds). "m" is metres unless a number follows
# it (a bearing's minutes). Converted with ``normalize_unit_token``.
LENGTH_UNIT = rf"(?:{UNIT_TOKEN}\b|metres?\b|m\b(?!\s*\d)|'(?!')|\u2032(?!\u2032))"


def normalize_unit_token(token: str | None, default: str = "feet") -> str:
    """Normalize a captured unit token to a ConversionFactors-compatible key.

    A missing unit is ``default`` (the deed's distance unit).
    """
    if token is None or not token.strip():
        return default
    t = " ".join(token.strip().lower().split())
    if t in ("ft", "feet", "foot", "'", "\u2032"):
        return "feet"
    if t in ("pole", "poles"):
        return "poles"
    if t in ("rod", "rods"):
        return "rods"
    if t in ("perch", "perches"):
        return "perches"
    if t in ("chain", "chains"):
        return "chains"
    if t in ("link", "links"):
        return "links"
    if t in ("engineer chain", "engineer chains"):
        return "engineer_chains"
    if t in ("engineer link", "engineer links"):
        return "engineer_links"
    if t in ("us survey foot", "us survey feet"):
        return "us_survey_feet"
    if t in ("vara", "varas"):
        return "varas"
    if t in ("arpent", "arpents"):
        return "arpents"
    if t in ("toise", "toises"):
        return "toises"
    if t in ("furlong", "furlongs"):
        return "furlongs"
    if t in ("meter", "meters", "metre", "metres", "m"):
        return "meters"
    if t in ("mile", "miles"):
        return "miles"
    return "feet"


def is_foot_mark(token: str) -> bool:
    """True for the bare foot marks that need extra context to count as a unit."""
    return token.strip() in FOOT_MARKS
