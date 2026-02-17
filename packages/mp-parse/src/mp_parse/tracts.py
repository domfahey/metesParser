"""Split legal descriptions into tracts.

Detects multi-tract patterns in priority order:
1. Explicit markers: TRACT #N, TRACT A, PARCEL N
2. Multiple BEGINNING blocks with independent closures
3. EXCEPT/ALSO clauses (reuses split_exception_clauses)
"""

from __future__ import annotations

import re

from mp_models import TractType

from .metadata import split_exception_clauses

# TRACT #1, TRACT 1, TRACT A, TRACT ONE (with optional colon/dash)
_TRACT_MARKER = re.compile(
    r"\bTRACT\s+(?:#\s*)?([A-Z0-9]+)\s*[:.\-\u2014]?\s*",
    re.IGNORECASE,
)

# PARCEL 1, PARCEL A (with optional colon/dash)
_PARCEL_MARKER = re.compile(
    r"\bPARCEL\s+(?:#\s*)?([A-Z0-9]+)\s*[:.\-\u2014]?\s*",
    re.IGNORECASE,
)

# BEGINNING at/in (start of a metes block)
_BEGINNING_PATTERN = re.compile(
    r"\bBEGINNING\s+(?:at|in)\b",
    re.IGNORECASE,
)

# Closure to POB
_POB_CLOSE_PATTERN = re.compile(
    r"(?:POINT\s+(?:AND\s+PLACE\s+)?OF\s+BEGINNING|place\s+of\s+BEGINNING|POB)\b",
    re.IGNORECASE,
)


def find_tract_markers(
    text: str,
) -> list[tuple[int, str, str]]:
    """Find explicit TRACT or PARCEL markers.

    Returns: list of (position, label, marker_kind)
    """
    markers: list[tuple[int, str, str]] = []
    for m in _TRACT_MARKER.finditer(text):
        markers.append((m.start(), f"Tract {m.group(1)}", "tract"))
    for m in _PARCEL_MARKER.finditer(text):
        markers.append((m.start(), f"Parcel {m.group(1)}", "parcel"))
    markers.sort(key=lambda x: x[0])
    return markers


def split_on_markers(
    text: str,
    markers: list[tuple[int, str, str]],
) -> list[tuple[str, str, TractType]]:
    """Split text on explicit markers."""
    result: list[tuple[str, str, TractType]] = []
    for i, (pos, label, _kind) in enumerate(markers):
        end = markers[i + 1][0] if i + 1 < len(markers) else len(text)
        segment = text[pos:end].strip()
        result.append((segment, label, TractType.MAIN))
    return result


def find_beginning_blocks(text: str) -> list[tuple[int, int]]:
    """Find BEGINNING...POB blocks.

    Returns: list of (start, end) positions
    """
    blocks: list[tuple[int, int]] = []
    for m in _BEGINNING_PATTERN.finditer(text):
        # Look for matching POB closure after this BEGINNING
        close = _POB_CLOSE_PATTERN.search(text, m.end())
        if close:
            # Verify this block has at least one THENCE
            block_text = text[m.start() : close.end()]
            if re.search(r"\bTHENCE\b", block_text, re.IGNORECASE):
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

    # Single tract — pass through
    return [(text, "Tract 1", TractType.MAIN)]
