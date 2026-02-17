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
    (r"\bPK\b", "pk nail"),
]


def normalize_dms_symbols(text: str) -> str:
    """Standardize degree/minute/second symbols.

    Converts various representations to standard DMS notation.

    Args:
        text: Input text with potentially non-standard DMS symbols

    Returns:
        Text with standardized DMS symbols
    """
    text = re.sub(r"[°º\u00B0\u00BA]", "°", text)

    text = re.sub(r"[''\u2018\u2019`]", "'", text)

    text = re.sub(r"[" "\u201c\u201d]", '"', text)

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
    text = re.sub(r"-\s*\n\s*", "", text)

    lines = text.split("\n")
    merged = []
    current = ""

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if re.match(r"^(THENCE|BEGINNING|FROM|POB|POINT)", stripped, re.IGNORECASE):
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
    patterns: list[tuple[str, str | Callable[[Match[str]], str]]] = [
        (
            r"\b(North|South|East|West)\s+(\d{1,3})\s+degrees?\s+(\d{1,2})\s+minutes?\s+(\d{1,2}(?:\.\d+)?)\s+seconds?\s+(North|South|East|West)\b",
            lambda m: f"{m.group(1)[0]} {m.group(2)}°{m.group(3)}'{m.group(4)}\" {m.group(5)[0]}",
        ),
        (
            r"\b(North|South|East|West)\s+(\d{1,3})\s+degrees?\s+(\d{1,2})\s+minutes?\s+(North|South|East|West)\b",
            lambda m: f"{m.group(1)[0]} {m.group(2)}°{m.group(3)}' {m.group(4)[0]}",
        ),
        (
            r"\b(North|South|East|West)\s+(\d{1,3})\s+degrees?\s+(North|South|East|West)\b",
            lambda m: f"{m.group(1)[0]} {m.group(2)}° {m.group(3)[0]}",
        ),
        (
            r"([NS])\s*(\d{1,3})\s*°\s*(\d{1,2})\s*'\s*(\d{1,2}(?:\.\d+)?)\s*\"\s*([EW])",
            "\\1 \\2°\\3'\\4\" \\5",
        ),
        (r"([NS])\s*(\d{1,3})\s*°\s*(\d{1,2})\s*'\s*([EW])", r"\1 \2°\3' \4"),
        (r"([NS])\s*(\d{1,3})\s*°\s*([EW])", r"\1 \2° \3"),
    ]

    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    return text


def clean_ocr_errors(text: str) -> str:
    """Attempt to fix common OCR errors in legal descriptions.

    This is a best-effort cleanup. Manual review is always recommended.

    Args:
        text: OCR text

    Returns:
        Cleaned text
    """
    text = re.sub(r"\b5outh\b", "South", text, flags=re.IGNORECASE)
    text = re.sub(r"\bNOrth\b", "North", text, flags=re.IGNORECASE)
    text = re.sub(r"\bEa5t\b", "East", text, flags=re.IGNORECASE)
    text = re.sub(r"\bWe5t\b", "West", text, flags=re.IGNORECASE)

    text = re.sub(r"([NS])\s+(\d{1,3})\s+0\s+(\d{1,2})\s*'\s*([EW])", r"\1 \2°\3' \4", text)

    text = re.sub(
        r"\b(North|South)\s+(\d{1,3})\s+0\s+(\d{1,2})\s*'\s*(East|West)\b",
        r"\1 \2 degrees \3 minutes \4",
        text,
        flags=re.IGNORECASE,
    )

    return text


def expand_abbreviations(text: str) -> str:
    """Expand common survey abbreviations.

    Args:
        text: Text with potential abbreviations

    Returns:
        Text with abbreviations expanded
    """
    for pattern, expansion in SURVEY_ABBREVIATIONS:
        text = re.sub(pattern, expansion, text, flags=re.IGNORECASE)
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
    text = merge_line_wrapped_calls(text)
    text = standardize_cardinal_directions(text)
    text = expand_abbreviations(text)

    return text
