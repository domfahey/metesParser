"""Split legal descriptions into tracts.

Detects multi-tract patterns in priority order:
1. Explicit markers: TRACT #N, TRACT A, PARCEL N
2. Multiple BEGINNING...POB blocks (text-pattern based)
3. EXCEPT/ALSO clauses (reuses split_exception_clauses)
"""

from __future__ import annotations

import re

import structlog
from mp_models import TractType

from .metadata import split_exception_clauses

logger = structlog.get_logger(__name__)

# Negative lookahead for common words that follow TRACT/PARCEL in deed preambles
# (e.g., "TRACT OF LAND", "PARCEL SITUATE IN") to prevent false positives.
_COMMON_WORDS = (
    r"(?!OF\b|OR\b|AND\b|IN\b|ON\b|AT\b|TO\b|THE\b|BEING\b|LAND\b"
    r"|SITUATE\b|IS\b|DESCRIBED\b|CONVEYED\b|KNOWN\b|LYING\b"
    r"|HEREIN\b|SAID\b|WHICH\b|THAT\b|CONTAINING\b|BOUNDED\b)"
)

# TRACT #1, TRACT 1, TRACT III, TRACT A (numbers, Roman numerals, single letters)
# [IVX]+ must precede [A-Z] so "TRACT III" matches "III" not "I".
_TRACT_MARKER = re.compile(
    r"\bTRACT\s+(?:#\s*)?" + _COMMON_WORDS + r"(\d+|[IVX]+|[A-Z])"
    r"\s*[:.\-\u2014]?\s*",
    re.IGNORECASE,
)

# PARCEL 1, PARCEL A (same constraints as TRACT)
_PARCEL_MARKER = re.compile(
    r"\bPARCEL\s+(?:#\s*)?" + _COMMON_WORDS + r"(\d+|[IVX]+|[A-Z])"
    r"\s*[:.\-\u2014]?\s*",
    re.IGNORECASE,
)

# Include the full POB opening so extracted tracts retain their original wording.
_BEGINNING_PATTERN = re.compile(
    r"\b(?:(?:POINT(?:\s+AND\s+PLACE)?|PLACE)\s+OF\s+)?BEGINNING\s+(?:at|in)\b",
    re.IGNORECASE,
)

# Closure to POB
_POB_CLOSE_PATTERN = re.compile(
    r"(?:POINT\s+(?:AND\s+PLACE\s+)?OF\s+BEGINNING|place\s+of\s+BEGINNING|POB)\b",
    re.IGNORECASE,
)


# Words that make a following TRACT/PARCEL a reference to another parcel
# ("corner of Parcel 2", "adjoining Tract 4"), even across an OCR line break.
_REFERENCE_WORD_BEFORE = re.compile(
    r"\b(?:of|to|said|adjoining|adjacent|along|from|with|in|within|being)\s*$", re.IGNORECASE
)
# Text after a marker that indicates it opens a description.
_HEADING_CONTINUATION = re.compile(r"\s*(?:BEGINNING|COMMENCING|ALL\s+THAT)\b", re.IGNORECASE)


def _is_standalone_line(text: str, match: re.Match[str]) -> bool:
    """Return whether the marker starts a line and ends it or is followed by BEGINNING."""
    prefix = text[: match.start()]
    if "\n" not in prefix[len(prefix.rstrip()) :]:
        return False
    return "\n" in match.group(0) or bool(_HEADING_CONTINUATION.match(text, match.end()))


def _inside_open_description(prefix: str) -> bool:
    """Return whether a BEGINNING in prefix has no later point-of-beginning closure."""
    starts = list(_BEGINNING_PATTERN.finditer(prefix))
    if not starts:
        return False
    return _POB_CLOSE_PATTERN.search(prefix, starts[-1].start()) is None


def _is_heading_marker(text: str, match: re.Match[str]) -> bool:
    """Return whether a TRACT/PARCEL match heads a description.

    Neighbour references ("corner of Parcel 2", "Lot 5 of Tract 4567") follow a
    reference word, even when OCR wrapped the line. A heading that is not such a
    reference starts the text, a line, or a sentence/clause (period, colon,
    semicolon), or is followed by a description opener such as BEGINNING (which
    also covers headings merged into the preceding sentence). A marker with its
    own colon/dash ("Description of PARCEL 1: ...") is always a heading.
    """
    own_punct = match.group(0).strip()[-1:]
    # A dash glued to the next alphanumeric is part of a hyphenated ID ("A-1").
    hyphenated_id = own_punct == "-" and text[match.end() : match.end() + 1].isalnum()
    if own_punct in (":", "-", "\u2014") and not hyphenated_id:
        return True
    prefix = text[: match.start()]
    if not prefix.strip():
        return True
    if _REFERENCE_WORD_BEFORE.search(prefix):
        # A marker alone on its line is a heading even after a dangling word
        # ("description of\nPARCEL 1\nBEGINNING"), unless an earlier BEGINNING
        # is still unclosed, where a wrapped "in\nTract 4567" is a reference.
        return _is_standalone_line(text, match) and not _inside_open_description(prefix)
    stripped = prefix.rstrip()
    if "\n" in prefix[len(stripped) :] or stripped.endswith((".", ":", ";")):
        return True
    return bool(_HEADING_CONTINUATION.match(text, match.end()))


def find_tract_markers(
    text: str,
) -> list[tuple[int, str, str]]:
    """Find explicit TRACT or PARCEL markers.

    Returns: list of (position, label, marker_kind)
    """
    markers: list[tuple[int, str, str]] = []
    for m in _TRACT_MARKER.finditer(text):
        if _is_heading_marker(text, m):
            markers.append((m.start(), f"Tract {m.group(1)}", "tract"))
    for m in _PARCEL_MARKER.finditer(text):
        if _is_heading_marker(text, m):
            markers.append((m.start(), f"Parcel {m.group(1)}", "parcel"))
    markers.sort(key=lambda x: x[0])
    return markers


def split_on_markers(
    text: str,
    markers: list[tuple[int, str, str]],
) -> list[tuple[str, str, TractType]]:
    """Split text on explicit markers.

    Inspects text preceding each marker to detect EXCEPT/ALSO keywords
    and assign the correct TractType.
    """
    result: list[tuple[str, str, TractType]] = []

    # Warn if text before first marker contains THENCE calls (would be lost)
    if markers and markers[0][0] > 0:
        pre_text = text[: markers[0][0]].strip()
        if re.search(r"\bTHENCE\b", pre_text, re.IGNORECASE):
            logger.warning(
                "Text with THENCE calls found before first tract marker",
                preview=pre_text[:120],
                characters=len(pre_text),
            )

    for i, (pos, label, _kind) in enumerate(markers):
        end = markers[i + 1][0] if i + 1 < len(markers) else len(text)
        segment = text[pos:end].strip()

        # Check preceding text for EXCEPT/ALSO to assign correct TractType
        preceding = text[max(0, pos - 80) : pos]
        if re.search(r"\b(?:LESS\s+AND\s+)?EXCEPT(?:ING)?\b", preceding, re.IGNORECASE):
            tract_type = TractType.EXCEPTION
        elif re.search(r"\b(?:ALSO|INCLUDING)\b", preceding, re.IGNORECASE):
            tract_type = TractType.ADDITION
        else:
            tract_type = TractType.MAIN

        result.append((segment, label, tract_type))
    return result


def _beginning_starts(text: str) -> list[re.Match[str]]:
    """Keep POB openings; exclude references reached 'to' or 'being' the POB."""
    return [
        match
        for match in _BEGINNING_PATTERN.finditer(text)
        if not re.search(
            r"\b(?:to|being)\s+(?:(?:a|the|said|aforesaid|original|true|initial)\s+)*$",
            text[: match.start()],
            re.IGNORECASE,
        )
    ]


def find_beginning_blocks(text: str) -> list[tuple[int, int]]:
    """Find BEGINNING...POB blocks.

    Returns: list of (start, end) positions
    """
    blocks: list[tuple[int, int]] = []
    for m in _beginning_starts(text):
        # Look for matching POB closure after this BEGINNING
        close = _POB_CLOSE_PATTERN.search(text, m.end())
        if not close:
            logger.warning(
                "BEGINNING block without matching POB closure",
                position=m.start(),
                preview=text[m.start() : m.start() + 80],
            )
            continue

        # Ensure no intervening BEGINNING between this one and its POB
        intervening = _beginning_starts(text[m.end() : close.start()])
        if intervening:
            logger.warning(
                "Dropping BEGINNING block due to intervening BEGINNING before POB",
                position=m.start(),
                preview=text[m.start() : m.start() + 120],
            )
            continue

        # Verify this block has at least one THENCE
        block_text = text[m.start() : close.end()]
        if not re.search(r"\bTHENCE\b", block_text, re.IGNORECASE):
            logger.warning(
                "BEGINNING block without THENCE calls",
                position=m.start(),
                preview=block_text[:80],
            )
            continue

        blocks.append((m.start(), close.end()))
    return blocks


def label_beginning_blocks(
    blocks: list[tuple[int, int]],
    text: str,
) -> list[tuple[str, str, TractType]]:
    """Label multiple BEGINNING blocks as tracts.

    Inspects the text preceding each block to detect ALSO/EXCEPT keywords
    and assign the correct TractType.
    """
    result: list[tuple[str, str, TractType]] = []
    main_count = 0
    exception_count = 0
    addition_count = 0

    for start, end in blocks:
        segment = text[start:end].strip()

        # Check text before this block for EXCEPT or ALSO keywords
        preceding = text[max(0, start - 80) : start]
        tract_type = TractType.MAIN

        if re.search(r"\b(?:LESS\s+AND\s+)?EXCEPT(?:ING)?\b", preceding, re.IGNORECASE):
            tract_type = TractType.EXCEPTION
            exception_count += 1
            label = f"Exception {exception_count}"
        elif re.search(r"\b(?:ALSO|INCLUDING)\b", preceding, re.IGNORECASE):
            tract_type = TractType.ADDITION
            addition_count += 1
            label = f"Addition {addition_count}"
        else:
            main_count += 1
            label = f"Tract {main_count}"

        result.append((segment, label, tract_type))

    return result


def split_into_tracts(text: str) -> list[tuple[str, str, TractType]]:
    """Split legal description text into tract segments.

    Detection priority:
    1. Explicit TRACT/PARCEL markers
    2. Multiple BEGINNING blocks
    3. EXCEPT/ALSO clauses (fallback)

    Returns: list of (tract_text, label, tract_type)
    """
    # 1. Try explicit TRACT/PARCEL markers
    markers = find_tract_markers(text)
    if markers:
        return split_on_markers(text, markers)

    # 2. Try multiple BEGINNING blocks
    blocks = find_beginning_blocks(text)
    if len(blocks) > 1:
        return label_beginning_blocks(blocks, text)

    # 3. Fall back to EXCEPT/ALSO splitting
    clauses = split_exception_clauses(text)
    if len(clauses) > 1:
        result: list[tuple[str, str, TractType]] = []
        main_idx = 0
        exc_idx = 0
        for clause_text, is_exc in clauses:
            if is_exc:
                exc_idx += 1
                result.append((clause_text, f"Exception {exc_idx}", TractType.EXCEPTION))
            else:
                main_idx += 1
                result.append((clause_text, f"Tract {main_idx}", TractType.MAIN))
        return result

    # Single tract — pass through (log if multiple BEGINNINGs detected but unmatched)
    beginning_count = len(_beginning_starts(text))
    if beginning_count > 1:
        logger.warning(
            "Single-tract fallback with multiple BEGINNING keywords",
            beginning_count=beginning_count,
            text_length=len(text),
        )
    return [(text, "Tract 1", TractType.MAIN)]
