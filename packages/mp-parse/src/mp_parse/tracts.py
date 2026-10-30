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

# TRACT/PARCEL [#|NO.] ID, where ID is a whole token: a number with an optional
# letter (2B), a Roman numeral, a single letter, or a spelled number, optionally
# hyphenated (A-1). NO is a whole token ("NO.", "NO 2", "NO #2"), never the
# start of a word ("TRACT NOW"). [IVX]+ precedes [A-Z] so "TRACT III" captures "III"; the
# closing \b rejects ordinary words ("TRACT OF LAND", "Parcel Info").
_MARKER = re.compile(
    r"\b(?P<kind>TRACT|PARCEL)\s+(?:#\s*|NO(?:\.|\s*#|\s)\s*)?"
    r"(?P<id>(?:\d+[A-Z]?|[IVX]+|[A-Z]"
    r"|ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN|ELEVEN|TWELVE)"
    r"(?:-(?:\d+|[A-Z]))?)\b",
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


# What follows the marker ID decides whether the marker is a heading.
# Strong: the marker's own colon, or a description opener directly after it
# (optionally across a line break or heading punctuation).
_STRONG_TERMINATOR = re.compile(
    r"[ \t]*:|\s*(?:[.\-\u2013\u2014]\s*)?"
    r"(?:(?:(?:POINT(?:\s+AND\s+PLACE)?|PLACE)\s+OF\s+)?BEGINNING|COMMENCING|ALL\s+THAT)\b",
    re.IGNORECASE,
)
# Weak: end of line/text, a period, or a heading dash not glued to the next word.
# Valid only when the marker is in heading position.
_WEAK_TERMINATOR = re.compile(r"[ \t]*(?:\n|$|\.|[\-\u2013\u2014](?![A-Za-z0-9]))", re.IGNORECASE)
# An uppercase TRACT/PARCEL in heading position is a heading whatever prose
# follows its ID ("TRACT 2 Situate in ...", "PARCEL TWO being all that lot"),
# unless that prose is reference wording ("TRACT 2 of the Smith subdivision",
# "PARCEL 2 as shown on", "TRACT 4567 on said map") or a recital opener.
_UPPERCASE_REFERENCE_AFTER_ID = re.compile(
    r"[ \t]*(?:(?:of|as|on|per|and|or|thence)\b|&|in\s+said\b"
    r"|being\s+(?:the\s+same|part\s+of|a\s+part\s+of)\b"
    # Predicate/recital words that cannot start a description heading
    # ("TRACT 1 CONTAINING 0.23 ACRES", "PARCEL 2 IS EXCEPTED THEREFROM").
    r"|(?:containing|contains|is|are|was|herein|hereinabove|hereinbefore|above|described"
    r"|aforesaid|excepted|excepting|subject|shall|conveyed|recorded)\b)",
    re.IGNORECASE,
)
# Sentence breaks that put the following marker in heading position.
_HEADING_POSITION_BREAKS = (".", ":", ";")
# A markdown heading prefix before the marker: any '#' run at a line start, or
# '##'+ after whitespace (normalization flattens newlines; a lone mid-line '#'
# is a number sign, not a heading).
_MARKDOWN_HEADING_PREFIX = re.compile(r"(?:(?:^|\n)[ \t]*#{1,6}|\s#{2,6})[ \t]*$")
# Label for text with boundary calls before the first marker; no heading is invented.
UNLABELLED_TRACT_LABEL = "Unlabelled tract"
# A bearing or curve phrase: a direction word, an N/S-prefixed bearing, or a curve/arc.
_COURSE_WORD = (
    r"(?:(?:north|south|east|west)(?:erly|wardly)?(?![A-Za-z])"
    r"|[NS]\s*\.?\s*\d|(?:curve|arc)s?(?![A-Za-z])|curv(?:ed|ing)\b)"
)
# A THENCE that opens a real course: directly followed by a direction word or
# letter, or by along/with/by ... then a bearing or curve phrase in the same
# clause. OCR/table noise ("thence colspan=3", "thence in Southeasterly
# direction") is not mistaken for a boundary description.
_THENCE_COURSE = re.compile(
    r"\bTHENCE[\s,]+(?:"
    r"(?:(?:due|running)\s+)?(?:north|south|east|west|[NSEW]{1,2})(?:erly|wardly)?(?![A-Za-z])"
    r"|(?:along|with|by)\b[^;\n]{0,100}?" + _COURSE_WORD + r")",
    re.IGNORECASE,
)
# Parenthetical and comma after a marker ID are transparent to the heading test.
_TRANSPARENT_AFTER_ID = re.compile(r"(?:[ \t]*\([^()\n]*\))?(?:[ \t]*,)?")
# Words that make a following marker a reference to another parcel
# ("corner of Parcel 2", "lying in Tract 4567"), even across an OCR line break.
_REFERENCE_WORD_BEFORE = re.compile(
    r"\b(?:of|to|said|adjoining|adjacent|along|from|with|in|within|being)\s*$", re.IGNORECASE
)


# A marker segment that is a title recital ("TRACT #1: BEING the same lands and
# premises which became vested in ... by deed ..."), not a boundary description.
_RECITAL_OPENER = re.compile(
    r"^[^\n]{0,40}?\bBEING\s+(?:all\s+of\s+)?the\s+same\s+"
    r"(?:lands?|premises|property|tract|parcel|lot)\b",
    re.IGNORECASE,
)
_RECITAL_CONVEYANCE = re.compile(r"\b(?:conveyed|vested|deed|recorded)\b", re.IGNORECASE)
# A measured distance; a recital may name directions ("lying Northerly of ...",
# even "thence Westerly of ...") but states no course distance.
_COURSE_DISTANCE = re.compile(
    r"\d[\d,]*(?:\.\d+)?\s*(?:feet|foot|ft\b|chains?|rods?|perches|poles?|links?|met(?:er|re)s?)",
    re.IGNORECASE,
)


def _is_title_recital(segment: str) -> bool:
    """Return whether a marker segment is a BEING-the-same recital with no boundary call.

    A boundary call needs a BEGINNING clause or a recognised THENCE course with a
    measured distance; direction words alone in a recital are not courses.
    """
    if not (_RECITAL_OPENER.match(segment) and _RECITAL_CONVEYANCE.search(segment)):
        return False
    if _BEGINNING_PATTERN.search(segment):
        return False
    return not any(
        _COURSE_DISTANCE.search(segment, course.end(), course.end() + 200)
        for course in _THENCE_COURSE.finditer(segment)
    )


def _inside_open_description(prefix: str) -> bool:
    """Return whether a BEGINNING in prefix has no later point-of-beginning closure."""
    starts = list(_BEGINNING_PATTERN.finditer(prefix))
    if not starts:
        return False
    return _POB_CLOSE_PATTERN.search(prefix, starts[-1].end()) is None


def _is_heading_marker(text: str, match: re.Match[str]) -> bool:
    """Return whether a TRACT/PARCEL match is a heading rather than a reference.

    A heading is a whole heading unit: nothing but a terminator follows its ID.
    A marker followed by ordinary prose ("Parcel 2 on a plan", "Tract 4567,
    thence", "Parcel 3; THENCE") is a reference.

    * Strong terminator (own colon, or BEGINNING/COMMENCING/ALL THAT next):
      a heading anywhere, including headings the normalizer merged into the
      preceding sentence, except a reference-word mention inside a boundary
      description that is still open ("BEGINNING at a point lying in
      Tract 4567 BEGINNING ...").
    * Heading position (start of text, after a sentence break . : ; or behind a
      markdown '#' prefix) is required otherwise. There a weak terminator (end of
      line, '.', spaced dash) makes any marker a heading, and an uppercase
      TRACT/PARCEL is a heading whatever follows its ID unless reference or
      recital wording does ("TRACT 2 of ...", "PARCEL 2 as shown", "TRACT 2
      BEING THE SAME ..."). Titlecase or lowercase markers followed by prose
      stay references. Leading text with calls is kept as its own tract by
      split_on_markers, so an OCR-dropped heading no longer loses data.
    """
    prefix = text[: match.start()]
    skipped = _TRANSPARENT_AFTER_ID.match(text, match.end())
    end = skipped.end() if skipped else match.end()
    if _STRONG_TERMINATOR.match(text, end):
        return not (_REFERENCE_WORD_BEFORE.search(prefix) and _inside_open_description(prefix))
    stripped = prefix.rstrip()
    heading_position = (
        not stripped
        or stripped.endswith(_HEADING_POSITION_BREAKS)
        or _MARKDOWN_HEADING_PREFIX.search(prefix) is not None
    )
    if not heading_position:
        return False
    if _WEAK_TERMINATOR.match(text, end):
        return True
    # Heading position already excludes a marker right after a reference word.
    return match["kind"].isupper() and not _UPPERCASE_REFERENCE_AFTER_ID.match(text, end)


def find_tract_markers(
    text: str,
) -> list[tuple[int, str, str]]:
    """Find explicit TRACT or PARCEL markers.

    Returns: list of (position, label, marker_kind)
    """
    return [
        (m.start(), f"{m['kind'].capitalize()} {m['id']}", m["kind"].lower())
        for m in _MARKER.finditer(text)
        if _is_heading_marker(text, m)
    ]


def _label_key(label: str) -> str:
    """Identity of a tract label for folding: the ID's case is not significant.

    The displayed label stays the first occurrence's wording ("Tract ONE").
    Number spellings are not folded: the codebase keeps no word-to-digit mapping
    for tract IDs, so "Tract ONE" and "Tract 1" remain distinct tracts.
    """
    return label.casefold()


def split_on_markers(
    text: str,
    markers: list[tuple[int, str, str]],
) -> list[tuple[str, str, TractType]]:
    """Split text on explicit markers.

    Inspects text preceding each marker to detect EXCEPT/ALSO keywords
    and assign the correct TractType.
    """
    result: list[tuple[str, str, TractType]] = []
    recitals: list[tuple[str, str, TractType]] = []

    # Boundary calls before the first marker belong to a tract whose heading was
    # not found (e.g. lost by OCR). Keep them under a neutral label; recitals
    # and headers without calls are still dropped.
    if markers and markers[0][0] > 0:
        pre_text = text[: markers[0][0]].strip()
        if not _THENCE_COURSE.search(pre_text):
            if re.search(r"\bTHENCE\b", pre_text, re.IGNORECASE):
                logger.warning(
                    "Dropping text before first tract marker: THENCE without a recognised course",
                    preview=pre_text[:120],
                    characters=len(pre_text),
                )
        else:
            logger.warning(
                "Tract heading not found before first marker; keeping leading text as unlabelled tract",
                preview=pre_text[:120],
                characters=len(pre_text),
            )
            result.append((pre_text, UNLABELLED_TRACT_LABEL, TractType.MAIN))

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

        # A title recital is never a tract of its own; it is resolved after all
        # descriptions are known (a same-label description may follow it).
        if _is_title_recital(segment):
            recitals.append((segment, label, tract_type))
            continue

        # A repeated label whose segment has no calls is prose about an earlier
        # tract (area, exception recital), not a new tract: fold it back.
        if not (_BEGINNING_PATTERN.search(segment) or _THENCE_COURSE.search(segment)):
            earlier = next(
                (j for j, r in enumerate(result) if _label_key(r[1]) == _label_key(label)), None
            )
            if earlier is not None:
                prev_text, prev_label, prev_type = result[earlier]
                result[earlier] = (f"{prev_text} {segment}".strip(), prev_label, prev_type)
                continue

        result.append((segment, label, tract_type))

    described = bool(result)
    for segment, label, tract_type in recitals:
        same = next(
            (j for j, r in enumerate(result) if _label_key(r[1]) == _label_key(label)), None
        )
        if same is not None:
            prev_text, prev_label, prev_type = result[same]
            result[same] = (f"{prev_text} {segment}".strip(), prev_label, prev_type)
        elif described:
            # No described tract carries this label (e.g. its heading was OCR-garbled):
            # the recital has no calls, so it is dropped rather than made a tract.
            logger.warning(
                "Dropping title recital whose label matches no described tract",
                label=label,
                preview=segment[:120],
            )
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
