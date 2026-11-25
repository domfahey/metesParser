"""Text normalization for metes and bounds legal descriptions.

Handles cleaning up OCR errors, standardizing DMS notation, merging line breaks,
and expanding survey abbreviations.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from re import Match

# ----- Survey abbreviation table -----

SURVEY_ABBREVIATIONS: list[tuple[str, str]] = [
    (r"\bCon\s+Mon\s+F\b", "concrete monument found"),
    (r"\bIPF\b", "iron pin found"),
    (r"\bIPS\b", "iron pin set"),
    (r"\bIRF\b", "iron rod found"),
    (r"\bIRS\b", "iron rod set"),
    (r"\bCIP\b", "capped iron pin"),
    (r"\bCMP\b", "concrete monument placed"),
    (r"\bR/W\b", "right-of-way"),
    (r"\bROW\b", "right-of-way"),
    (r"\bN/F\b", "now or formerly"),
    (r"\bPK\b(?!\s+nail\b)", "pk nail"),
]

_COMPILED_SURVEY_ABBREVIATIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(pattern, 0 if pattern == r"\bROW\b" else re.IGNORECASE), expansion)
    for pattern, expansion in SURVEY_ABBREVIATIONS
]

# ----- DMS symbol normalization patterns -----

_DMS_DEGREE_RE = re.compile(r"[°º]")
_DMS_MINUTE_RE = re.compile(r"['\u2018\u2019\u2032`]")
_DMS_SECOND_RE = re.compile(r'["\u201c\u201d\u2033]')

# ----- Line-wrapping merge patterns -----

_HYPHEN_BREAK_RE = re.compile(r"-\s*\n\s*")
_CALL_START_LINE_RE = re.compile(
    r"^(?:(?:THENCE|BEGINNING|FROM|POB|POINT)\b|\(\d+\)|\d+[.)])(?:\s+|$)",
    re.IGNORECASE,
)

# ----- Cardinal direction standardization patterns -----

_CARDINAL_DIR_PATTERNS: list[tuple[re.Pattern[str], Callable[[Match[str]], str]]] = [
    (
        re.compile(
            r"\b(North|South|N|S)\s*(\d{1,3})\s+degrees?,?\s+(\d{1,2})\s+minutes?\s*,?\s*(\d{1,2}(?:\.\d+)?)\s+seconds?\s+(East|West|E|W)\b",
            re.IGNORECASE,
        ),
        lambda m: (
            f"{m.group(1)[0].upper()} {m.group(2)}°{m.group(3)}'{m.group(4)}\" {m.group(5)[0].upper()}"
        ),
    ),
    (
        re.compile(
            r"\b(North|South|N|S)\s*(\d{1,3})\s+degrees?,?\s+(\d{1,2})\s+minutes?\s*,?\s*(East|West|E|W)\b",
            re.IGNORECASE,
        ),
        lambda m: f"{m.group(1)[0].upper()} {m.group(2)}°{m.group(3)}' {m.group(4)[0].upper()}",
    ),
    (
        re.compile(
            r"\b(North|South|N|S)\s*(\d{1,3})\s+degrees?\s*,?\s*(East|West|E|W)\b",
            re.IGNORECASE,
        ),
        lambda m: f"{m.group(1)[0].upper()} {m.group(2)}° {m.group(3)[0].upper()}",
    ),
    (
        re.compile(
            r"([NS])\s*(\d{1,3})\s*°\s*(\d{1,2})\s*'\s*(\d{1,2}(?:\.\d+)?)\s*\"\s*([EW])",
            re.IGNORECASE,
        ),
        lambda m: (
            f"{m.group(1).upper()} {m.group(2)}°{m.group(3)}'{m.group(4)}\" {m.group(5).upper()}"
        ),
    ),
    (
        re.compile(r"([NS])\s*(\d{1,3})\s*°\s*(\d{1,2})\s*'\s*([EW])", re.IGNORECASE),
        lambda m: f"{m.group(1).upper()} {m.group(2)}°{m.group(3)}' {m.group(4).upper()}",
    ),
    (
        re.compile(r"([NS])\s*(\d{1,3})\s*°\s*([EW])", re.IGNORECASE),
        lambda m: f"{m.group(1).upper()} {m.group(2)}° {m.group(3).upper()}",
    ),
]

# ----- OCR cleanup patterns -----

_OCR_WORD_FIXES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b5outh\b", re.IGNORECASE), "South"),
    (re.compile(r"\bNOrth\b"), "North"),
    (re.compile(r"\bN0rth\b", re.IGNORECASE), "North"),
    (re.compile(r"\bEa5t\b", re.IGNORECASE), "East"),
    (re.compile(r"\bWe5t\b", re.IGNORECASE), "West"),
]
_OCR_ZERO_DEG_SYMBOL_RE = re.compile(
    r"([NS])\s+(\d{1,3})\s+0\s+(\d{1,2})\s*'\s*(?:(\d{1,2}(?:\.\d+)?)\s*\"\s*)?([EW])",
    re.IGNORECASE,
)
_OCR_ZERO_DEG_WORD_RE = re.compile(
    r"\b(North|South)\s+(\d{1,3})\s+0\s+(\d{1,2})\s*'\s*(?:(\d{1,2}(?:\.\d+)?)\s*\"\s*)?(East|West)\b",
    re.IGNORECASE,
)

# ----- Assessor abbreviation expansion patterns -----

_OCR_NO_DEG_RE = re.compile(r"\b([NS])O(\d*DEG|\d+D|D(?=\s+\d{1,2}\s*M\b))\b", re.IGNORECASE)
_OCR_NOO_DEG_RE = re.compile(r"\b([NS])OO(\d*DEG|\d+D|D(?=\s+\d{1,2}\s*M\b))\b", re.IGNORECASE)

_ASSESSOR_SUBS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"(?:(?<=[NS])|(?<!\w))(\d{1,3})\s*(?:DEG|D)\s+(\d{1,2})\s*(?:M)\s+(\d{1,2}(?:\.\d+)?)\s*(?:SEC|S)\b",
            re.IGNORECASE,
        ),
        r"\1 degrees \2 minutes \3 seconds",
    ),
    (
        re.compile(
            r"(?:(?<=[NS])|(?<!\w))(\d{1,3})\s*(?:DEG|D)\s+(\d{1,2})\s*(?:M)\b",
            re.IGNORECASE,
        ),
        r"\1 degrees \2 minutes",
    ),
    (re.compile(r"(?:(?<=[NS])|(?<!\w))(\d{1,3})\s*DEG\b", re.IGNORECASE), r"\1 degrees"),
    (re.compile(r"\b(N|S|North|South)\s*(\d{1,3})\s*D\b", re.IGNORECASE), r"\1 \2 degrees"),
    (re.compile(r"(?:(?<=[NS])|(?<!\w))(\d{1,3})\s+deg\.\s", re.IGNORECASE), r"\1 degrees "),
    (re.compile(r"(?<!\w)(\d{1,2}(?:\.\d+)?)SEC\b(?!\s*\d)", re.IGNORECASE), r"\1 seconds"),
    (
        re.compile(
            r"(?<!\w)(\d{1,2}(?:\.\d+)?)\s+SEC\b(?=\s*(?:East|West|E|W)\b)",
            re.IGNORECASE,
        ),
        r"\1 seconds",
    ),
    (
        re.compile(
            r"((?:minutes?|,|['′])\s*)(\d{1,2}(?:\.\d+)?)\s+SEC\b(?!\s*\d)",
            re.IGNORECASE,
        ),
        r"\1\2 seconds",
    ),
    (re.compile(r"\bTH\.?\s+", re.IGNORECASE), "thence "),
    (re.compile(r"(\d+(?:\.\d+)?)\s*FT\b", re.IGNORECASE), r"\1 feet"),
    (re.compile(r"\bSLY\b", re.IGNORECASE), "southerly"),
    (re.compile(r"\bNLY\b", re.IGNORECASE), "northerly"),
    (re.compile(r"\bELY\b", re.IGNORECASE), "easterly"),
    (re.compile(r"\bWLY\b", re.IGNORECASE), "westerly"),
    (re.compile(r"(?<![A-Za-z]\.)\bP\.O\.B\.", re.IGNORECASE), "point of beginning"),
    (re.compile(r"\bP\s+OB\b", re.IGNORECASE), "point of beginning"),
    (re.compile(r"\bPOB\b", re.IGNORECASE), "point of beginning"),
    (re.compile(r"\bALG\b", re.IGNORECASE), "along"),
    (re.compile(r"\bCOR\b", re.IGNORECASE), "corner"),
    (re.compile(r"\bBEG\b", re.IGNORECASE), "beginning"),
    (
        re.compile(
            r"(?<=\S)\s+(?:&|and)\s+(?=[NS]\s*\d{1,3}\s*(?:°|degrees?\b))",
            re.IGNORECASE,
        ),
        " thence ",
    ),
]

_CARDINAL_MAP: dict[str, str] = {
    "n": "North",
    "s": "South",
    "e": "East",
    "w": "West",
    "north": "North",
    "south": "South",
    "east": "East",
    "west": "West",
}

_BARE_CARDINAL_RE = re.compile(
    r"(\b(?:thence|proceeding)\s+)"
    r"(N|S|E|W|North|South|East|West)"
    r"(\s+)"
    r"(\d+\.?\d*)",
    re.IGNORECASE,
)

_DEGREE_AFTER_NUMBER = re.compile(
    r"\s*(?:°|degrees?\b|DEG\b|\d+(?:\.\d+)?\s*['′]|(?:E|W|East|West)\b)",
    re.IGNORECASE,
)


def _bare_cardinal_replace(m: Match[str]) -> str:
    """Replace bare cardinal + distance with 'due Cardinal distance' unless bearing follows."""
    after_pos = m.end()
    after_text = m.string[after_pos : after_pos + 50]
    if _DEGREE_AFTER_NUMBER.match(after_text):
        return m.group(0)

    prefix = m.group(1)
    cardinal = m.group(2)
    number = m.group(4)
    full_name = _CARDINAL_MAP[cardinal.lower()]
    return f"{prefix}due {full_name} {number}"


def normalize_dms_symbols(text: str) -> str:
    """Standardize degree/minute/second symbols.

    Converts various representations to standard DMS notation.

    Args:
        text: Input text with potentially non-standard DMS symbols

    Returns:
        Text with standardized DMS symbols
    """
    text = _DMS_DEGREE_RE.sub("°", text)
    text = _DMS_MINUTE_RE.sub("'", text)
    text = _DMS_SECOND_RE.sub('"', text)
    return text


def merge_line_wrapped_calls(text: str) -> str:
    """Merge lines that are part of the same call.

    THENCE lines should be single lines. This merges lines that were
    wrapped in the original document.

    Args:
        text: Input text with potential line wrapping

    Returns:
        Text with wrapped calls merged
    """
    text = _HYPHEN_BREAK_RE.sub("", text)

    lines = text.split("\n")
    merged = []
    current = ""

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if _CALL_START_LINE_RE.match(stripped):
            if current:
                merged.append(current)
            current = stripped
        else:
            if current:
                current += " " + stripped
            else:
                current = stripped

    if current:
        merged.append(current)

    return "\n".join(merged)


def standardize_cardinal_directions(text: str) -> str:
    """Standardize cardinal direction text.

    Converts various forms to standard: N, S, E, W with proper spacing.

    Args:
        text: Input text

    Returns:
        Text with standardized cardinal directions
    """
    for pattern, replacement in _CARDINAL_DIR_PATTERNS:
        text = pattern.sub(replacement, text)

    return text


def _ocr_zero_deg_symbol_replace(m: Match[str]) -> str:
    """Replace OCR '0' for degree symbol in compact DMS notation."""
    sec = f'{m.group(4)}"' if m.group(4) else ""
    return f"{m.group(1)} {m.group(2)}°{m.group(3)}'{sec} {m.group(5)}"


def clean_ocr_errors(text: str) -> str:
    """Attempt to fix common OCR errors in legal descriptions.

    This is a best-effort cleanup. Manual review is always recommended.

    Args:
        text: OCR text

    Returns:
        Cleaned text
    """
    for pattern, replacement in _OCR_WORD_FIXES:
        text = pattern.sub(replacement, text)

    text = _OCR_ZERO_DEG_SYMBOL_RE.sub(_ocr_zero_deg_symbol_replace, text)

    text = _OCR_ZERO_DEG_WORD_RE.sub(
        lambda m: (
            f"{m.group(1)} {m.group(2)} degrees {m.group(3)} minutes"
            f"{(' ' + m.group(4) + ' seconds') if m.group(4) else ''} {m.group(5)}"
        ),
        text,
    )

    return text


def expand_assessor_abbreviations(text: str) -> str:
    """Expand compressed assessor notation used in Wayne County MI and similar.

    Handles patterns like:
      S0DEG 32M 50S W 401.55FT → S 0 degrees 32 minutes 50 seconds W 401.55 feet
      N 88D 25M 31S E 330.00 FT → N 88 degrees 25 minutes 31 seconds E 330.00 feet
      TH SLY 90 FT ALG ELY LINE → thence southerly 90 feet along easterly LINE
      89D 05M 3SEC W → 89 degrees 05 minutes 3 seconds W

    This function must run BEFORE standardize_cardinal_directions() so that the
    word-form output ("degrees", "minutes", "seconds") can be converted to DMS
    symbols by the standard pipeline.

    CRITICAL: 'S' is ambiguous (South vs seconds).  We only treat 'S' as
    seconds when it appears as a numeric suffix inside a DMS pattern
    (e.g., "50S" after a minutes marker).

    Args:
        text: Raw legal description text with possible assessor notation

    Returns:
        Text with assessor abbreviations expanded to standard survey wording
    """
    if not text:
        return text

    # --- 1. Fix common OCR typos: NODEG → N0DEG, NOODEG → N00DEG -----------
    # O (letter) used instead of 0 (digit) adjacent to direction letters
    text = _OCR_NO_DEG_RE.sub(lambda m: f"{m.group(1)}0{m.group(2)}", text)
    text = _OCR_NOO_DEG_RE.sub(lambda m: f"{m.group(1)}00{m.group(2)}", text)

    # --- 2-9. Expand DMS, SEC, TH, FT, directionals, POB, misc, &/and ------
    for pattern, replacement in _ASSESSOR_SUBS:
        text = pattern.sub(replacement, text)

    # --- 10. Bare cardinal + distance → due Cardinal + distance ---------------
    text = _BARE_CARDINAL_RE.sub(_bare_cardinal_replace, text)

    return text


def expand_abbreviations(text: str) -> str:
    """Expand common survey abbreviations.

    Args:
        text: Text with potential abbreviations

    Returns:
        Text with abbreviations expanded
    """
    for pattern, expansion in _COMPILED_SURVEY_ABBREVIATIONS:
        text = pattern.sub(expansion, text)
    return text


def normalize_legal_description(text: str) -> str:
    """Apply all normalization steps to a legal description.

    Args:
        text: Raw legal description text

    Returns:
        Normalized text
    """
    text = clean_ocr_errors(text)
    text = normalize_dms_symbols(text)
    text = expand_assessor_abbreviations(text)
    text = merge_line_wrapped_calls(text)
    text = standardize_cardinal_directions(text)
    text = expand_abbreviations(text)

    return text
