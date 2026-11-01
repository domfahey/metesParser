"""Split legal descriptions into tracts.

Detects multi-tract patterns in priority order:
1. Explicit markers: TRACT #N, TRACT A, PARCEL N, SCHEDULE A-1
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

# TRACT #1, TRACT NO. 1, TRACT #2B, TRACT III, TRACT A (numbers with an optional letter suffix,
# Roman numerals, single letters). [IVX]+ must precede [A-Z] so "TRACT III" matches
# "III" not "I"; the suffix must end the label so "TRACT 12th" stays "12". Letter labels
# must be whole words so "tract number 1" is not "Tract n".
_MARKER_LABEL = r"(\d+(?:[A-Z](?![A-Z]))?|(?:[IVX]+|[A-Z])\b)"

_TRACT_MARKER = re.compile(
    r"\bTRACT\s+(?:(?:#|NO\.?)\s*)?" + _COMMON_WORDS + _MARKER_LABEL + r"\s*[:.\-\u2014]?\s*",
    re.IGNORECASE,
)

# PARCEL 1, PARCEL A (same constraints as TRACT)
_PARCEL_MARKER = re.compile(
    r"\bPARCEL\s+(?:(?:#|NO\.?)\s*)?" + _COMMON_WORDS + _MARKER_LABEL + r"\s*[:.\-\u2014]?\s*",
    re.IGNORECASE,
)

# SCHEDULE A-1 (one property per schedule in a multi-property deed); a lone
# "Schedule A" names the attachment, not a tract.
_SCHEDULE_MARKER = re.compile(r"\bSCHEDULE\s+([A-Z]-?\d+)\b\s*[:.\-\u2014]?\s*", re.IGNORECASE)

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


# "the Southeasterly corner of Parcel #69", "D.R.P.A., Parcel #69": references, not markers
_REFERENCE_BEFORE = re.compile(r"(?:\b(?:of|to|said|with|from|by)|,)\s*$", re.IGNORECASE)


def find_tract_markers(
    text: str,
) -> list[tuple[int, str, str]]:
    """Find explicit TRACT, PARCEL or SCHEDULE markers.

    Returns: list of (position, label, marker_kind)
    """
    markers: list[tuple[int, str, str]] = []
    for m in _TRACT_MARKER.finditer(text):
        markers.append((m.start(), f"Tract {m.group(1)}", "tract"))
    for m in _PARCEL_MARKER.finditer(text):
        markers.append((m.start(), f"Parcel {m.group(1)}", "parcel"))
    for m in _SCHEDULE_MARKER.finditer(text):
        markers.append((m.start(), f"Schedule {m.group(1).upper()}", "schedule"))
    markers = [marker for marker in markers if not _REFERENCE_BEFORE.search(text, 0, marker[0])]
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

    exception_count = 0
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

        # EXCEPT clauses with courses inside a main tract describe separate exception
        # parcels; a narrative exception ("so much as was conveyed to the State") stays.
        clauses = split_exception_clauses(segment) if tract_type == TractType.MAIN else []
        clauses = [
            (part, is_exception and bool(re.search(r"\bTHENCE\b", part, re.IGNORECASE)))
            for part, is_exception in clauses
        ]
        if any(is_exception for _, is_exception in clauses):
            main_text = " ".join(part for part, is_exception in clauses if not is_exception)
            result.append((main_text, label, tract_type))
            for part, is_exception in clauses:
                if is_exception:
                    exception_count += 1
                    result.append((part, f"Exception {exception_count}", TractType.EXCEPTION))
        else:
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


def _find_pob_close(text: str, start: int) -> re.Match[str] | None:
    """Find the closure after start, skipping "said point of beginning" references.

    "to said point of beginning" still closes the block; a point of beginning reached by a
    tie course ("to a point and place of beginning, thence;") does not.
    """
    for match in _POB_CLOSE_PATTERN.finditer(text, start):
        if re.search(r"(?<!\bto\s)\bsaid\s+$", text[: match.start()], re.IGNORECASE):
            continue
        if re.match(r"\s*[,;]?\s*thence\b", text[match.end() :], re.IGNORECASE):
            continue
        return match
    return None


def find_beginning_blocks(text: str) -> list[tuple[int, int]]:
    """Find BEGINNING...POB blocks.

    Returns: list of (start, end) positions
    """
    blocks: list[tuple[int, int]] = []
    for m in _beginning_starts(text):
        # Look for matching POB closure after this BEGINNING
        close = _find_pob_close(text, m.end())
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

    Inspects the text preceding each block to detect EXCEPT/EASEMENT/ALSO keywords
    and assign the correct TractType.
    """
    result: list[tuple[str, str, TractType]] = []
    main_count = 0
    exception_count = 0
    easement_count = 0
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
        elif re.search(r"\bEASEMENT\b", preceding, re.IGNORECASE):
            tract_type = TractType.EASEMENT
            easement_count += 1
            label = f"Easement {easement_count}"
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
    1. Explicit TRACT/PARCEL/SCHEDULE markers
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

    # 3. Fall back to EXCEPT/ALSO splitting. A clause without courses ("ALSO BEING known
    # as...", "Excepting so much as was conveyed to the State") stays with the one before it.
    clauses: list[tuple[str, bool]] = []
    for clause_text, is_exc in split_exception_clauses(text):
        if clauses and not re.search(r"\bTHENCE\b", clause_text, re.IGNORECASE):
            previous_text, previous_exc = clauses[-1]
            clauses[-1] = (f"{previous_text} {clause_text}", previous_exc)
        else:
            clauses.append((clause_text, is_exc))
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
