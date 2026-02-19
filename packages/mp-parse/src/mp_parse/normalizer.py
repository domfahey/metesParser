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


def expand_assessor_abbreviations(text: str) -> str:
    """Expand compressed county assessor notation.

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
    text = re.sub(
        r"\b([NS])O(\d*(?:DEG|D))",
        lambda m: f"{m.group(1)}0{m.group(2)}",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\b([NS])OO(\d*(?:DEG|D))",
        lambda m: f"{m.group(1)}00{m.group(2)}",
        text,
        flags=re.IGNORECASE,
    )
    # Catch NOODEG specifically where the OO represents 00
    text = re.sub(
        r"\b([NS])OO(DEG|D)\b",
        lambda m: f"{m.group(1)}00{m.group(2)}",
        text,
        flags=re.IGNORECASE,
    )
    # Catch NODEG where O is 0
    text = re.sub(
        r"\b([NS])O(DEG|D)\b",
        lambda m: f"{m.group(1)}0{m.group(2)}",
        text,
        flags=re.IGNORECASE,
    )

    # --- 2. Expand DMS bearing notation (DEG/D, M, S/SEC) ------------------
    # Match complete DMS bearing: [cardinal]<deg>(DEG|D) <min>M [<sec>(S|SEC)] [cardinal]
    # Full DMS with seconds (S or SEC)
    text = re.sub(
        r"(\d{1,3})\s*(?:DEG|D)\s+(\d{1,2})\s*(?:M)\s+(\d{1,2}(?:\.\d+)?)\s*(?:SEC|S)\b",
        r"\1 degrees \2 minutes \3 seconds",
        text,
        flags=re.IGNORECASE,
    )
    # DM only (no seconds)
    text = re.sub(
        r"(\d{1,3})\s*(?:DEG|D)\s+(\d{1,2})\s*(?:M)\b",
        r"\1 degrees \2 minutes",
        text,
        flags=re.IGNORECASE,
    )
    # Degrees only (DEG/D without M following)
    text = re.sub(
        r"(\d{1,3})\s*(?:DEG|D)\b",
        r"\1 degrees",
        text,
        flags=re.IGNORECASE,
    )
    # "deg." → "degrees" (e.g., "26 deg. 00 41")
    text = re.sub(
        r"(\d{1,3})\s+deg\.\s",
        r"\1 degrees ",
        text,
        flags=re.IGNORECASE,
    )

    # --- 3. Expand number+SEC that wasn't already caught (standalone) -------
    text = re.sub(
        r"(\d{1,2}(?:\.\d+)?)\s*SEC\b",
        r"\1 seconds",
        text,
        flags=re.IGNORECASE,
    )

    # --- 4. TH / TH. → thence (word boundary, not inside words) ------------
    # Must not match THE, THAT, THIS, THEREOF, THENCE, etc.
    text = re.sub(
        r"\bTH\.?\s(?!E\b|A\b|I\b|ERE|EN|ROU|AT\b|US\b)",
        "thence ",
        text,
        flags=re.IGNORECASE,
    )

    # --- 5. FT suffix → feet -----------------------------------------------
    # Handles both "175FT" (no space) and "175 FT" (with space)
    text = re.sub(
        r"(\d+(?:\.\d+)?)\s*FT\b",
        r"\1 feet",
        text,
        flags=re.IGNORECASE,
    )

    # --- 6. Directional abbreviations ---------------------------------------
    text = re.sub(r"\bSLY\b", "southerly", text, flags=re.IGNORECASE)
    text = re.sub(r"\bNLY\b", "northerly", text, flags=re.IGNORECASE)
    text = re.sub(r"\bELY\b", "easterly", text, flags=re.IGNORECASE)
    text = re.sub(r"\bWLY\b", "westerly", text, flags=re.IGNORECASE)

    # --- 7. POB variants → point of beginning ------------------------------
    text = re.sub(r"\bP\.O\.B\.", "point of beginning", text, flags=re.IGNORECASE)
    text = re.sub(r"\bP\s+OB\b", "point of beginning", text, flags=re.IGNORECASE)
    text = re.sub(r"\bPOB\b", "point of beginning", text, flags=re.IGNORECASE)

    # --- 8. Misc abbreviations ---------------------------------------------
    text = re.sub(r"\bALG\b", "along", text, flags=re.IGNORECASE)
    text = re.sub(r"\bCOR\b", "corner", text, flags=re.IGNORECASE)
    text = re.sub(r"\bBEG\b", "beginning", text, flags=re.IGNORECASE)

    # --- 9. `&` / `and` as call separators → thence --------------------------
    # Between bearings: "113.41 feet & N 69° 53' 23\" E" or
    # "49.18 feet and N 48° 03' 44\" E".  Replace `&` or `and` with `thence`
    # when followed by a quadrant bearing pattern ([NS] <digits>°).
    # Note: Only [NS] because standard quadrant bearings always start with
    # North or South.  E/W-initial bearings need different handling.
    text = re.sub(
        r"(?<=\S)\s+(?:&|and)\s+(?=[NS]\s*\d{1,3}\s*°)",
        " thence ",
        text,
        flags=re.IGNORECASE,
    )

    # --- 10. Bare cardinal + distance → due Cardinal + distance ---------------
    # "thence S 289.81 feet" → "thence due South 289.81 feet"
    # Only match single cardinal letters (N/S/E/W) or full words
    # (North/South/East/West) followed by a number, NOT followed by degree
    # notation (°, degrees, DEG).  Must not match compound cardinals
    # (northerly, southwesterly, NE, NW, etc.).
    _CARDINAL_MAP = {
        "n": "North",
        "s": "South",
        "e": "East",
        "w": "West",
        "north": "North",
        "south": "South",
        "east": "East",
        "west": "West",
    }

    # Pattern: capture the full match so the callback can inspect context
    _BARE_CARDINAL_RE = re.compile(
        r"(\b(?:thence|proceeding)\s+)"  # group 1: anchor
        r"(N|S|E|W|North|South|East|West)"  # group 2: bare cardinal
        r"(\s+)"  # group 3: whitespace
        r"(\d+\.?\d*)",  # group 4: distance number
        re.IGNORECASE,
    )

    # Degree notation that immediately follows the captured number.
    _DEGREE_AFTER_NUMBER = re.compile(
        r"\s*(?:°|degrees?|DEG\b)",
        re.IGNORECASE,
    )

    def _bare_cardinal_replace(m: Match[str]) -> str:
        # Check what follows the captured number in the original string.
        # If degree notation follows, this is a quadrant bearing — leave it alone.
        after_pos = m.end()
        after_text = m.string[after_pos : after_pos + 50]
        if _DEGREE_AFTER_NUMBER.match(after_text):
            return m.group(0)  # no change

        prefix = m.group(1)  # "thence " (or "proceeding ")
        cardinal = m.group(2)
        number = m.group(4)  # "289.81" etc.
        full_name = _CARDINAL_MAP[cardinal.lower()]
        return f"{prefix}due {full_name} {number}"

    text = _BARE_CARDINAL_RE.sub(_bare_cardinal_replace, text)

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
    text = expand_assessor_abbreviations(text)
    text = merge_line_wrapped_calls(text)
    text = standardize_cardinal_directions(text)
    text = expand_abbreviations(text)

    return text
