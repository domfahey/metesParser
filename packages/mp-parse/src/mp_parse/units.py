"""One length-unit vocabulary shared by course and curve-element length parsing."""

from __future__ import annotations

import re
import unicodedata

# A number directly after a degree sign (or digit/point/comma) is a bearing's
# minutes or part of a larger number, never a length; after a fraction slash it
# is a fraction's denominator.
LENGTH_NUMBER_GUARD = r"(?<![\d.,\u00b0/\u2044])(?<!\u00b0\s)"

# --- The one length-number grammar -------------------------------------------------
# Every length, curve-element, compound and inch value is read with LENGTH_NUMBER
# and converted with ``parse_number``: an integer or decimal with comma grouping
# ("1,200.50"), a mixed fraction ("100 1/2", "100-1/2", "6\u00bd", "6 \u00bd"), a
# plain fraction ("3/4") or a Unicode vulgar fraction ("\u00bd"). A match never
# starts inside a fraction (after its slash, or at its numerator when a whole
# number precedes it) and never stops before one, so a half-read number ("100.5
# 1/2", "1/2/3", "1/0") is no length at all rather than a fragment of one.
VULGAR_FRACTIONS = (
    "\u00bc\u00bd\u00be\u2150\u2151\u2152\u2153\u2154\u2155"
    "\u2156\u2157\u2158\u2159\u215a\u215b\u215c\u215d\u215e"
)
_VULGAR = f"[{VULGAR_FRACTIONS}]"
_FRACTION_SLASH = r"[/\u2044]"
_FRACTION = rf"\d+{_FRACTION_SLASH}0*[1-9]\d*"
# Comma grouping is valid thousands grouping only ("1,200"); "100,50" or "1,2,3" is
# no number, never a different value.
_WHOLE = r"(?:\d{1,3}(?:,\d{3})+|\d+)"
_MIXED_GAP = r"(?:\s*-\s*|\s+)"
# A fraction (or lone vulgar fraction) never starts after a whole number and a gap
# (it would be read without the whole number).
_NO_WHOLE_BEFORE = r"(?<!\d\s)(?<!\d\s\s)(?<!\d,\s)(?<!\d-)(?<!\d\s-)(?<!\d-\s)"
_NUMBER_END = rf"(?!\d|[.,]\d|{_FRACTION_SLASH}|{_VULGAR}|\s*-?\s*\d+{_FRACTION_SLASH}\d)"
LENGTH_NUMBER = (
    rf"{LENGTH_NUMBER_GUARD}(?:{_WHOLE}{_MIXED_GAP}{_FRACTION}|{_WHOLE}\s*{_VULGAR}"
    rf"|{_WHOLE}(?:\.\d+)?|{_NO_WHOLE_BEFORE}{_FRACTION}|{_NO_WHOLE_BEFORE}{_VULGAR})"
    rf"{_NUMBER_END}"
)
_NUMBER_FORM = re.compile(
    rf"(?P<decimal>{_WHOLE}(?:\.\d+)?)"
    rf"|(?:(?P<whole>{_WHOLE})(?:{_MIXED_GAP}(?=\d)|\s*(?={_VULGAR})))?"
    rf"(?:(?P<num>\d+){_FRACTION_SLASH}(?P<den>\d+)|(?P<vulgar>{_VULGAR}))"
)


def parse_number(text: str) -> float:
    """Convert one LENGTH_NUMBER match to a float ("100 1/2" -> 100.5, "\u00be" -> 0.75).

    Raises ValueError for anything that is not exactly one such number, so a
    fragment is never read.
    """
    form = _NUMBER_FORM.fullmatch(text.strip())
    if form is None:
        raise ValueError(f"not a length number: {text!r}")
    if form.group("decimal") is not None:
        return float(form.group("decimal").replace(",", ""))
    value = float(form.group("whole").replace(",", "")) if form.group("whole") else 0.0
    if form.group("vulgar") is not None:
        return value + unicodedata.numeric(form.group("vulgar"))
    denominator = int(form.group("den"))
    if denominator == 0:
        raise ValueError(f"zero denominator: {text!r}")
    return value + int(form.group("num")) / denominator


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
# A foot mark directly before a compass letter/word is a bearing's minutes written
# without a degree sign ("N 45 30' E"), not a length; a compass that opens a new
# bearing in degrees ("100' N 45\u00b0 E") leaves the mark a length.
# Seconds ("30' 15\" E") may sit between the mark and the compass.
_BEARING_MINUTES_TAIL = (
    r"(?!\s*(?:\d+(?:\.\d+)?\s*(?:\"|''|\u2033)\s*)?"
    r"(?:North|South|East|West|[NSEW])\b(?!\s*\d+\s*(?:[\u00b0\u00ba]|deg(?:rees?)?\.?)))"
)
LENGTH_UNIT = (
    rf"(?:{UNIT_TOKEN}\b|metres?\b|m\b(?!\s*\d)"
    rf"|'(?!'){_BEARING_MINUTES_TAIL}|\u2032(?!\u2032){_BEARING_MINUTES_TAIL})"
)


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
