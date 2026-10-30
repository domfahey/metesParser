"""Split legal descriptions into tracts.

Detects multi-tract patterns in priority order:
1. Explicit markers: TRACT #N, TRACT A, PARCEL N
2. Multiple BEGINNING...POB blocks (text-pattern based)
3. EXCEPT/ALSO clauses (reuses split_exception_clauses)

An appurtenant easement or right of way described by its own courses ("Together
with an easement ... BEGINNING ...; thence ...") is split from whichever tract
holds it into an EASEMENT tract, so its legs never join a parcel boundary.
"""

from __future__ import annotations

import re

import structlog
from mp_models import TractType

from .metadata import _is_lot_qualifier_except, split_exception_clauses
from .units import LENGTH_NUMBER, LENGTH_UNIT

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
    rf"{LENGTH_NUMBER}\s*{LENGTH_UNIT}",
    re.IGNORECASE,
)


# An appurtenant easement or right of way introduced at a clause start ("Together
# with an easement 10 feet wide, BEGINNING ...", "ALSO an easement ...", "Subject to
# a right of way described as follows: ..."). The noun must follow in the same
# clause, before any THENCE or EXCEPT (an excepted right of way is an exception).
# ALSO opens one only at a sentence start: after a comma it continues a call
# ("..., also being the Southerly right of way of Mack Avenue").
_EASEMENT_NOUN = (
    r"(?:(?!\bthence\b|\bexcept)[^.;\n]){0,80}?\b(?:easements?|rights?[\s-]+of[\s-]+way)\b"
)
_EASEMENT_INTRO = r"(?:TOGETHER\s+WITH|SUBJECT\s+TO|ALSO|RESERVING)\b" + _EASEMENT_NOUN
_EASEMENT_OPENER = re.compile(
    r"(?:(?:^|(?<=[.;:,\n]))\s*(?P<open>(?:TOGETHER\s+WITH|SUBJECT\s+TO|RESERVING)\b"
    + _EASEMENT_NOUN
    + r")|(?:^|(?<=[.;:\n]))\s*(?P<also>ALSO\b"
    + _EASEMENT_NOUN
    + r"))",
    re.IGNORECASE,
)
# Wording right before a tract that makes it an easement description.
_EASEMENT_BEFORE = re.compile(_EASEMENT_INTRO + r"[^.;]*$", re.IGNORECASE)
_STRUCTURAL_EXCEPT = re.compile(r"\b(?:LESS\s+AND\s+)?EXCEPT(?:ING)?\b", re.IGNORECASE)
_ADDITION_START = re.compile(r"(?:^|[;\n.])\s*(?:ALSO|INCLUDING)\b", re.IGNORECASE)
_COMMENCING = re.compile(r"\bCOMMENCING\b", re.IGNORECASE)
EASEMENT_LABEL = "Easement"


def _boundary_closed_before(prefix: str) -> bool:
    """Return whether no boundary description is still open at the end of ``prefix``.

    An opener inside an open description ("BEGINNING at a pin, subject to a right of
    way, thence ...", "Commencing at a corner, also being ...") qualifies that
    description; it never starts an easement. A description is open from its last
    BEGINNING, COMMENCING or THENCE until a point-of-beginning closure.
    """
    openings = [
        *(m.end() for m in _beginning_starts(prefix)),
        *(m.end() for m in _COMMENCING.finditer(prefix)),
        *(m.end() for m in _THENCE_WORD.finditer(prefix)),
    ]
    return not openings or _POB_CLOSE_PATTERN.search(prefix, max(openings)) is not None


def easement_description_spans(text: str) -> list[tuple[int, int]]:
    """Return the spans of appurtenant easement descriptions stated by their own courses.

    A span runs from its opener to the next easement opener, structural
    EXCEPT/ALSO clause or tract heading, or the end of ``text``. An opener without a
    THENCE course in its span is a clause (metadata), not a description.
    """
    openers = [
        m.start("open") if m["open"] else m.start("also") for m in _EASEMENT_OPENER.finditer(text)
    ]
    if not openers:
        return []
    stops = sorted(
        {
            *openers,
            *(
                m.start()
                for m in _STRUCTURAL_EXCEPT.finditer(text)
                if not _is_lot_qualifier_except(text, m)
            ),
            *(m.end() - len(m.group().lstrip(";\n. \t")) for m in _ADDITION_START.finditer(text)),
            *(position for position, _, _ in find_tract_markers(text)),
        }
    )
    spans: list[tuple[int, int]] = []
    for start in openers:
        if spans and start < spans[-1][1]:
            continue
        if not _boundary_closed_before(text[:start]):
            continue
        end = next((stop for stop in stops if stop > start), len(text))
        if _THENCE_COURSE.search(text, start, end):
            spans.append((start, end))
    return spans


# The whole lead of a stated exception ("SAVE AND EXCEPT", "ALSO EXCEPTING").
_STATED_EXCEPT_LEAD = re.compile(
    r"\b(?:(?:ALSO|AND|BUT)\s+)?(?:(?:LESS|SAVE)\s+AND\s+)?EXCEPT(?:ING)?\b", re.IGNORECASE
)
# A stated exception's clause ends at a period before a new sentence or the text's end
# (never at a decimal point or "Vol. 12").
_CLAUSE_SENTENCE_END = re.compile(r"\.(?=\s+[A-Z(]|\s*$)")
# A described traverse: any THENCE, or a quadrant bearing.
_TRAVERSE_WORDING = re.compile(
    r"\bTHENCE\b|\b[NS]\s*\.?\s*\d{1,3}\s*(?:°|deg\b|degrees?\b)", re.IGNORECASE
)
_CLAUSE_START_BEFORE = re.compile(r"(?:^|[.;:\n])\s*$")


def stated_exception_spans(text: str) -> list[tuple[int, int]]:
    """Return the spans of stated exceptions that describe no traverse.

    A stated exception opens a clause ("... to the point of beginning, EXCEPT the
    South 43.65 feet of said Lot in even width conveyed to Jones.") after a closed
    description. When no THENCE or bearing follows before the next structural
    clause, tract heading or easement description, it describes no course: reading
    its wording as a course invents one, and splitting on it makes an exception
    tract without calls. Its span runs from its lead to the end of its sentence.
    An EXCEPT inside an open description qualifies that description and is kept.
    """
    leads = list(_STATED_EXCEPT_LEAD.finditer(text))
    if not leads:
        return []
    stops = sorted(
        {
            *(m.start() for m in leads if not _is_lot_qualifier_except(text, m)),
            *(m.end() - len(m.group().lstrip(";\n. \t")) for m in _ADDITION_START.finditer(text)),
            *(position for position, _, _ in find_tract_markers(text)),
            *(
                m.start("open") if m["open"] else m.start("also")
                for m in _EASEMENT_OPENER.finditer(text)
            ),
        }
    )
    spans: list[tuple[int, int]] = []
    for lead in leads:
        start = lead.start()
        if spans and start < spans[-1][1]:
            continue
        prefix = text[:start]
        openings = [
            *(m.end() for m in _beginning_starts(prefix)),
            *(m.end() for m in _COMMENCING.finditer(prefix)),
            *(m.end() for m in _THENCE_WORD.finditer(prefix)),
        ]
        closure = list(_POB_CLOSE_PATTERN.finditer(prefix, max(openings))) if openings else []
        if not closure:
            continue
        # At a clause start, or directly after the closure ("... beginning, except ...").
        between = prefix[closure[-1].end() :]
        if not (_CLAUSE_START_BEFORE.search(prefix) or not between.strip(" \t\n,;:.")):
            continue
        extent_end = next((stop for stop in stops if stop > start), len(text))
        if _TRAVERSE_WORDING.search(text, lead.end(), extent_end):
            continue
        sentence_end = _CLAUSE_SENTENCE_END.search(text, lead.end(), extent_end)
        end = (
            sentence_end.start()
            if sentence_end
            else start + len(text[start:extent_end].rstrip(" \t\n.;,:"))
        )
        spans.append((start, end))
    return spans


def stated_clause_end(text: str, end: int) -> int:
    """Return where the clause of wording ending at ``end`` ends.

    Wording continued after a comma or semicolon ("EXCEPT the North 10 feet thereof,
    conveyed to X by deed recorded in Book 12, page 4.") belongs to the clause up to
    its sentence end, unless a traverse, a structural clause or a tract heading
    starts before it. Otherwise the clause ends at ``end``.
    """
    if text[end : end + 1] not in (",", ";"):
        return end
    sentence_end = _CLAUSE_SENTENCE_END.search(text, end)
    stop = sentence_end.start() if sentence_end else len(text.rstrip(" \t\n.;,:"))
    rest = text[end:stop]
    if (
        _TRAVERSE_WORDING.search(rest)
        or _STATED_EXCEPT_LEAD.search(rest)
        or _ADDITION_START.search(rest)
        or _EASEMENT_OPENER.search(rest)
        or find_tract_markers(rest)
    ):
        return end
    return end + len(rest.rstrip(" \t\n;,:"))


def _separate_easements(
    segments: list[tuple[str, str, TractType]],
) -> list[tuple[str, str, TractType]]:
    """Split easement descriptions out of each segment into EASEMENT tracts.

    Generated easement labels are numbered in order of appearance.
    """
    result: list[tuple[str, str, TractType]] = []
    for segment, label, tract_type in segments:
        spans = [] if tract_type == TractType.EASEMENT else easement_description_spans(segment)
        if not spans:
            result.append((segment, label, tract_type))
            continue
        kept: list[str] = []
        cursor = 0
        for start, end in spans:
            kept.append(segment[cursor:start])
            cursor = end
        kept.append(segment[cursor:])
        remainder = " ".join(part.strip() for part in kept if part.strip())
        if remainder:
            result.append((remainder, label, tract_type))
        result.extend(
            (segment[start:end].strip(), EASEMENT_LABEL, TractType.EASEMENT) for start, end in spans
        )
    count = 0
    numbered: list[tuple[str, str, TractType]] = []
    for segment, label, tract_type in result:
        if tract_type == TractType.EASEMENT and re.fullmatch(
            re.escape(EASEMENT_LABEL) + r"(?: \d+)?", label
        ):
            count += 1
            label = f"{EASEMENT_LABEL} {count}"
        numbered.append((segment, label, tract_type))
    return numbered


def _tract_type_before(preceding: str) -> TractType:
    """Type of the tract that follows ``preceding`` (its last 80 characters)."""
    if _EASEMENT_BEFORE.search(preceding):
        return TractType.EASEMENT
    if re.search(r"\b(?:LESS\s+AND\s+)?EXCEPT(?:ING)?\b", preceding, re.IGNORECASE):
        return TractType.EXCEPTION
    if re.search(r"\b(?:ALSO|INCLUDING)\b", preceding, re.IGNORECASE):
        return TractType.ADDITION
    return TractType.MAIN


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


# A description opener; with no course before it, the marker's own text begins a
# description ("Parcel 2 being all that lot BEGINNING at a pin").
_DESCRIPTION_OPENER = re.compile(
    r"\b(?:(?:POINT(?:\s+AND\s+PLACE)?|PLACE)\s+OF\s+)?BEGINNING\b|\bCOMMENCING\b|\bALL\s+THAT\b",
    re.IGNORECASE,
)
# Wording right after an ID that makes the marker a reference whatever follows.
_REFERENCE_AFTER_ID = re.compile(
    r"[ \t]*(?:(?:of|as|on|per|thence)\b|in\s+said\b"
    r"|being\s+(?:the\s+same|part\s+of|a\s+part\s+of)\b)",
    re.IGNORECASE,
)


def _opens_description_before_course(text: str, end: int) -> bool:
    """Return whether a description opener precedes any THENCE course after a marker ID.

    Looks only at the marker's own segment, up to the next TRACT/PARCEL marker.
    """
    following = _MARKER.search(text, end)
    segment = text[end : following.start() if following else len(text)]
    opener = _DESCRIPTION_OPENER.search(segment)
    if opener is None:
        return False
    course = _THENCE_COURSE.search(segment)
    return course is None or opener.start() < course.start()


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
      stay references unless the segment opens a description (BEGINNING,
      COMMENCING, ALL THAT) before any THENCE course and the previous description
      is closed. Leading text with calls is kept as its own tract by
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
    # Structural signal, in any case: the prior description is closed and this
    # segment opens its own description before any course.
    if (
        not _REFERENCE_AFTER_ID.match(text, end)
        and not _inside_open_description(prefix)
        and _opens_description_before_course(text, end)
    ):
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

        # Check preceding text for easement/EXCEPT/ALSO wording to assign the TractType
        tract_type = _tract_type_before(text[max(0, pos - 80) : pos])

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


_THENCE_WORD = re.compile(r"\bTHENCE\b", re.IGNORECASE)
# A point of beginning reached by a tie and followed by more courses ("... to a point
# and place of beginning, thence; (1) ...") is not the description's closure.
_POB_CONTINUES = re.compile(r"\s*[,;]?\s*thence\b", re.IGNORECASE)


def find_beginning_blocks(text: str) -> list[tuple[int, int]]:
    """Find BEGINNING...POB blocks.

    A block closes at the first point-of-beginning mention after its first
    THENCE that no further THENCE follows: preamble wording ("said point of
    beginning being distant ...", "from said point of beginning running thence")
    and a tie to the point of beginning ("to a point and place of beginning,
    thence; (1) ...") are not closures.

    Returns: list of (start, end) positions
    """
    blocks: list[tuple[int, int]] = []
    for m in _beginning_starts(text):
        # The block's courses start at its first THENCE; a closure precedes none.
        first_thence = _THENCE_WORD.search(text, m.end())
        if not first_thence:
            logger.warning(
                "BEGINNING block without THENCE calls",
                position=m.start(),
                preview=text[m.start() : m.start() + 80],
            )
            continue
        close = next(
            (
                mention
                for mention in _POB_CLOSE_PATTERN.finditer(text, first_thence.end())
                if not _POB_CONTINUES.match(text, mention.end())
            ),
            None,
        )
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
                "BEGINNING block has an intervening BEGINNING before its POB; "
                "its text is kept by split_into_tracts if it holds courses",
                position=m.start(),
                preview=text[m.start() : m.start() + 120],
            )
            continue

        blocks.append((m.start(), close.end()))
    return blocks


# Wording between an easement and the description after it ("ALSO all that lot")
# is that description's lead-in; punctuation alone is no lead-in.
_LEAD_IN_PUNCTUATION = " \t\n.;,:"


def _with_unassigned_course_text(
    blocks: list[tuple[int, int]], text: str
) -> list[tuple[int, int, TractType | None, int]]:
    """Return blocks plus any text between or around them that holds courses.

    Each entry is (start, end, kind, typed_at): kind None for a BEGINNING block,
    EASEMENT for an easement description, MAIN for other course text; typed_at is
    where the wording that types a block ends (its BEGINNING). Course text outside
    every block (an unclosed description, a block dropped for an intervening
    BEGINNING) is kept as its own span so it is never silently lost; text without a
    course (schedule headings, recitals) is still dropped. When a gap's only courses
    are easement descriptions, each is its own span and the wording left after the
    last ("ALSO all that lot") is the following block's lead-in, never a tract.
    """
    spans: list[tuple[int, int, TractType | None, int]] = []
    easements = easement_description_spans(text)

    def keep_gap(start: int, end: int, before_block: bool) -> int | None:
        """Keep the gap's course text; return the following block's lead-in start."""
        gap = text[start:end]
        if not _THENCE_COURSE.search(gap):
            return None
        inside = [(s, e) for s, e in easements if start <= s and e <= end]
        remainder = gap
        for s, e in inside:
            remainder = remainder[: s - start] + " " * (e - s) + remainder[e - start :]
        if inside and not _THENCE_COURSE.search(remainder):
            spans.extend((s, e, TractType.EASEMENT, s) for s, e in inside)
            tail = inside[-1][1]
            while tail < end and text[tail] in _LEAD_IN_PUNCTUATION:
                tail += 1
            return tail if before_block and tail < end else None
        logger.warning(
            "Course text outside every BEGINNING block; keeping it as an unlabelled tract",
            position=start,
            preview=gap.strip()[:120],
            characters=len(gap.strip()),
        )
        spans.append((start, end, TractType.MAIN, start))
        return None

    cursor = 0
    for start, end in blocks:
        lead_in = keep_gap(cursor, start, before_block=True)
        spans.append((start if lead_in is None else lead_in, end, None, start))
        cursor = end
    keep_gap(cursor, len(text), before_block=False)
    return spans


def label_beginning_blocks(
    blocks: list[tuple[int, int]],
    text: str,
) -> list[tuple[str, str, TractType]]:
    """Label multiple BEGINNING blocks as tracts.

    Inspects the text preceding each block to detect ALSO/EXCEPT keywords
    and assign the correct TractType. Course text outside every block is kept
    under the unlabelled-tract label (numbered when there is more than one); an
    easement description between blocks is an easement tract.
    """
    result: list[tuple[str, str, TractType]] = []
    main_count = 0
    exception_count = 0
    addition_count = 0
    unlabelled_count = 0

    for start, end, kind, typed_at in _with_unassigned_course_text(blocks, text):
        segment = text[start:end].strip()
        if kind == TractType.EASEMENT:
            # Numbered with every other easement by _separate_easements.
            result.append((segment, EASEMENT_LABEL, TractType.EASEMENT))
            continue
        if kind is not None:
            unlabelled_count += 1
            label = UNLABELLED_TRACT_LABEL
            if unlabelled_count > 1:
                label = f"{UNLABELLED_TRACT_LABEL} {unlabelled_count}"
            result.append((segment, label, TractType.MAIN))
            continue

        # Check text before this block (and its lead-in) for easement/EXCEPT/ALSO wording
        tract_type = _tract_type_before(text[max(0, typed_at - 80) : typed_at])
        if tract_type == TractType.EASEMENT:
            # Numbered with every other easement by _separate_easements.
            label = EASEMENT_LABEL
        elif tract_type == TractType.EXCEPTION:
            exception_count += 1
            label = f"Exception {exception_count}"
        elif tract_type == TractType.ADDITION:
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

    An easement described by its own courses is then split from the tract holding
    it into an EASEMENT tract ("Easement N").

    Returns: list of (tract_text, label, tract_type)
    """
    return _separate_easements(_split_tract_segments(text))


def _split_tract_segments(text: str) -> list[tuple[str, str, TractType]]:
    """Split ``text`` by markers, BEGINNING blocks or EXCEPT/ALSO clauses."""
    # 1. Try explicit TRACT/PARCEL markers
    markers = find_tract_markers(text)
    if markers:
        return split_on_markers(text, markers)

    # 2. Try multiple BEGINNING blocks
    blocks = find_beginning_blocks(text)
    if len(blocks) > 1:
        return label_beginning_blocks(blocks, text)

    # Easements are separated before clause splitting, which would cut an "ALSO an
    # easement ..." opener off its description.
    separated = _separate_easements([(text, "Tract 1", TractType.MAIN)])
    if len(separated) > 1:
        easements = [segment for segment in separated if segment[2] == TractType.EASEMENT]
        parcel = [segment[0] for segment in separated if segment[2] != TractType.EASEMENT]
        return (_split_clauses(parcel[0]) if parcel else []) + easements
    return _split_clauses(text)


def _split_clauses(text: str) -> list[tuple[str, str, TractType]]:
    """Split ``text`` by EXCEPT/ALSO clauses, or keep it as one tract."""
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
