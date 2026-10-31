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
from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, replace
from functools import lru_cache

import structlog
from mp_models import TractType

from .metadata import (
    _ENUMERATOR_STYLES,
    CLOSING_ALONG_WITH,
    STRUCTURE_BREAK,
    VERBATIM_BEARING,
    _is_lot_qualifier_except,
    ends_sentence,
    split_exception_clauses,
)
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
# A course's enumerator in the course parser's own grammar (``_ENUMERATOR_STYLES``:
# "(1)", "1)", "1.", "(a)", "First,").
_COURSE_ENUMERATOR = r"(?:(?:" + "|".join(style.pattern for style in _ENUMERATOR_STYLES) + r")\s*)?"
# A THENCE that opens a real course: directly followed (after a comma or the course's
# enumerator: "thence, N ...", "thence (1) North ...", "thence 1) N ...") by a
# direction word or letter, or by along/with/by ... then a bearing or curve phrase in
# the same clause. OCR/table noise ("thence colspan=3", "thence in Southeasterly
# direction") is not mistaken for a boundary description. Numbering never changes
# which courses are recognised.
_THENCE_COURSE = re.compile(
    r"\bTHENCE[\s,]+" + _COURSE_ENUMERATOR + r"(?:"
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


# An appurtenant easement or right of way granted, reserved or excepted to at a
# clause start ("Together with an easement 10 feet wide, BEGINNING ...", "ALSO an
# easement ...", "Subject to a right of way described as follows: ...", "RESERVING
# unto the grantor, its successors and assigns, a perpetual easement ..."). The
# easement is the clause's object, after an optional grantee ("unto the grantor, its
# successors and assigns,", "to the grantor"): a determiner and modifiers ("a
# perpetual, non-exclusive", "a 20 foot wide") then the noun, or a grant of its use
# ("the use of an easement", "the use of a 10 foot wide right of way", "the right to
# use ...", "the free and uninterrupted use of ...", "a right of ingress and egress").
# A fee parcel that merely mentions one ("ALSO all that tract of land adjoining the
# railroad right of way", "ALSO the land within the former easement area", "ALSO a
# strip of land for a right of way") is not an easement: a parcel word, preposition
# or participle before the noun, or an area/line noun after it, keeps the clause a
# parcel, so its courses stay on a boundary (an addition) rather than being set
# aside. ALSO opens one only at a sentence start: after a comma it continues a call
# ("..., also being the Southerly right of way of Mack Avenue").
_EASEMENT_PARTY = r"(?:grantors?|grantees?|sellers?|purchasers?|buyers?|owners?|part(?:y|ies))\b"
_EASEMENT_SUCCESSORS = r"(?:heirs|successors|assigns|(?:legal|personal)\s+representatives)"
_EASEMENT_GRANTEE = (
    r"(?:\s*,?\s*(?:unto|to|for)\s+(?:the\s+)?(?:said\s+)?"
    + _EASEMENT_PARTY
    # "..., its successors and assigns," / "and their heirs and assigns", commas optional
    + r"(?:(?:\s*,?\s*(?:and\s+)?(?:its|his|her|their)\s+"
    + _EASEMENT_SUCCESSORS
    + r"(?:\s*,?\s*(?:and\s+)?"
    + _EASEMENT_SUCCESSORS
    + r")*)?\s*,?"
    # any other grantee wording, closed by a comma
    + r"|[^.;:]{0,60}?,))?"
)
_EASEMENT_DETERMINER = (
    r"\s*,?\s*(?:(?:an?|the|said|all|any|such|its|their|his|her|(?:that|those)\s+certain)\s+)?"
)
# Modifier words; never a word that makes the noun part of another object.
_EASEMENT_MODIFIER = (
    r"(?:(?!(?:of|in|on|to|into|within|adjoining|adjacent|abutting|along|over|across|upon"
    r"|lying|being|situate|situated|bounded|near|from|by|at|with|under|through|between"
    r"|subject|except\w*|thence|tracts?|lots?|parcels?|lands?|pieces?|premises|portions?"
    r"|parts?|strips?|areas?)\b)[\w'%°-]+,?\s+){0,6}"
)
# An area or line noun after the easement noun makes it part of another object
# ("the easement area", "the right of way line").
_NOT_AREA = r"(?![\s-]+(?:areas?|lines?|lands?|tracts?|parcels?|lots?|premises|portions?|parts?)\b)"
_EASEMENT_WORD = r"(?:easements?|rights?[\s-]+of[\s-]+way)\b" + _NOT_AREA
# A grant of the easement's benefit or of an interest in it ("the benefit of an
# easement", "all (of the grantor's) right, title and interest in and to the ...
# easement"). The object that follows is still the easement noun, so "all right,
# title and interest in and to the land lying within the easement area" stays a parcel.
_EASEMENT_INTEREST = (
    r"(?:(?:the\s+)?benefits?\s+of\b"
    r"|all\s+(?:of\s+)?(?:(?:the|its|his|her|their)\s+|(?:the\s+)?[\w]+'s?\s+)?"
    r"(?:right|title|interest)[\w\s,]{0,40}?interests?\s+(?:in\s+and\s+to|in|to)\b)"
)
_EASEMENT_NOUN = (
    _EASEMENT_GRANTEE
    + r"(?:\s*,?\s*"
    + _EASEMENT_INTEREST
    + r")?"
    + _EASEMENT_DETERMINER
    + r"(?:free\s+and\s+uninterrupted\s+(?:use|rights?|passage)\b|"
    + _EASEMENT_MODIFIER
    + r"(?:"
    + _EASEMENT_WORD
    + r"|(?:rights?|privileges?)\s+(?:to\s+(?:the\s+)?use|of\s+(?:ingress|egress|access|passage))\b"
    + r"|use\s+of"
    + _EASEMENT_DETERMINER
    + _EASEMENT_MODIFIER
    + _EASEMENT_WORD
    + r"))"
)
_EASEMENT_OPENER = re.compile(
    r"(?:(?:^|(?<=[.;:,\n]))\s*(?P<open>(?:TOGETHER\s+WITH|SUBJECT\s+TO|RESERVING)\b"
    + _EASEMENT_NOUN
    + r")|(?:^|(?<=[.;:\n]))\s*(?P<also>ALSO\b"
    + _EASEMENT_NOUN
    + r"))",
    re.IGNORECASE,
)
# A generic encumbrance recital ("SUBJECT to easements of record", "subject to
# easements and restrictions of record, if any", "SUBJECT to zoning ordinances,
# easements, conditions and restrictions of record"): plural easements of record
# describe no easement, so the recital opens none (it is a deed clause).
_PLURAL_EASEMENT_END = re.compile(r"(?:easements|rights[\s-]+of[\s-]+way)$", re.IGNORECASE)
_OF_RECORD = re.compile(r"\b(?:of\s+record|if\s+any)\b", re.IGNORECASE)
_RECITAL_CLAUSE_END = re.compile(r"[;:]|\b(?:THENCE|BEGINNING|COMMENCING)\b", re.IGNORECASE)
# How far a recital's clause is read for "of record".
_RECITAL_WINDOW = 300
# A specific easement named in a recital: a singular easement or right of way as the
# grant's object ("and to an easement for drainage", "including a drainage easement",
# "a right of way 20 feet wide"), with the grant grammar's modifiers
# (``_EASEMENT_MODIFIER``). Land located by one is no grant object ("that portion
# lying within a right of way", "a portion of the former right of way"): a locating
# word before it (``_LOCATING_BEFORE``) or a parcel word among its modifiers.
_SPECIFIC_EASEMENT = re.compile(
    r"\b(?:an?|that\s+certain|said)\s+"
    + _EASEMENT_MODIFIER
    + r"(?:easement|right[\s-]+of[\s-]+way)\b"
    + _NOT_AREA,
    re.IGNORECASE,
)
_LOCATING_BEFORE = re.compile(
    r"\b(?:of|in|into|within|on|upon|along|over|across|through|under|adjoining|adjacent|abutting"
    r"|lying|being|situate|situated|near|from|by|at|between)\s+$",
    re.IGNORECASE,
)


def _names_specific_easement(text: str, start: int, end: int) -> bool:
    """Return whether ``text[start:end]`` names a specific easement as a grant object."""
    return any(
        not _LOCATING_BEFORE.search(text, start, match.start())
        for match in _SPECIFIC_EASEMENT.finditer(text, start, end)
    )


# Wording that introduces a description ("described as follows", "the following
# described land").
_DESCRIPTION_INTRO = re.compile(
    r"\b(?:described\s+as\s+follows|as\s+follows|following\s+described)\b", re.IGNORECASE
)
# A colon directly before a description ("of record: BEGINNING").
_COLON_DESCRIPTION = re.compile(
    r":\s*(?:(?:POINT(?:\s+AND\s+PLACE)?|PLACE)\s+OF\s+)?(?:BEGINNING|COMMENCING)\b",
    re.IGNORECASE,
)


# A line that runs on into a description on the next line: it ends with continuing
# punctuation, a forward-pointing phrase or a connective word ("described as follows:",
# "10 feet wide,", "over the following", "described as").
_LINE_CONTINUES = re.compile(
    r"(?:[,:;\-\u2013\u2014]|\b(?:as|of|to|over|across|through|upon|along|and|in|on|by"
    r"|the|an?|being|follows|following|described|viz))\s*$",
    re.IGNORECASE,
)
# A description opening its own line (normalization keeps a line break before a
# BEGINNING but flattens the paragraph break before it).
_LINE_DESCRIPTION = re.compile(
    r"\n[ \t]*(?:(?:POINT(?:\s+AND\s+PLACE)?|PLACE)\s+OF\s+)?(?:BEGINNING|COMMENCING)\b",
    re.IGNORECASE,
)


# How far past a description's start ``_grant_takes`` reads for the line it opens.
_OPENING_LOOKAHEAD = 20
# A period closing a course's enumerator after THENCE ("thence 2. N 80° E") ends no
# sentence.
_ENUMERATOR_BEFORE_PERIOD = re.compile(r"\bTHENCE[\s,]+\d{1,3}$", re.IGNORECASE)


def _sentence_break(text: str, start: int, end: int) -> int | None:
    """Return where the sentence from ``start`` breaks before ``end``, or None.

    The one sentence-end rule of this module. A sentence breaks at a sentence-ending
    period (``ends_sentence``: never at an initial, abbreviation or decimal, nor at a
    course's enumerator: "thence 2. N 80° E"), at document structure
    (``STRUCTURE_BREAK``: a paragraph break, a markdown heading, bullet or table
    border, an HTML tag), or at a line break before a description opening its own line
    when the line before does not run on into it (``_LINE_CONTINUES``): normalization
    reduces a paragraph break before a BEGINNING to one line break ("SUBJECT to a
    right of way over the driveway\nBEGINNING ..."). Returns the period's position, or
    where the structure or line break starts.
    """
    structure = STRUCTURE_BREAK.search(text, start, end)
    limit = end if structure is None else structure.start()
    for line in _LINE_DESCRIPTION.finditer(text, start, limit):
        if not _LINE_CONTINUES.search(text, start, line.start()):
            limit = line.start()
            break
    period = next(
        (
            i
            for i in range(start, limit)
            if text[i] == "."
            and ends_sentence(text, i)
            and not _ENUMERATOR_BEFORE_PERIOD.search(text, max(0, i - 16), i)
        ),
        None,
    )
    if period is not None:
        return period
    return None if limit == end else limit


def _sentence_limit(text: str, start: int, end: int) -> int:
    """Return where the sentence from ``start`` ends (``_sentence_break``), at most ``end``."""
    found = _sentence_break(text, start, end)
    return end if found is None else found


def _is_generic_encumbrance(text: str, match: re.Match[str], after_boundary: bool) -> bool:
    """Return whether an easement opener match is a generic encumbrance recital.

    The opener names plural easements (or rights of way) and its clause, up to its
    sentence end, a semicolon, colon, THENCE or description opening, says "of record"
    or "if any". A specific easement ("a right of way for ingress and egress",
    "an easement of record for utilities") is never generic, nor is a recital whose
    sentence (up to its end, document structure or a semicolon) also names a specific
    easement as a grant object (``_names_specific_easement``: "the easements of record
    and an easement for drainage", never "the portion lying within a right of way").
    After a closed boundary (``after_boundary``) a recital whose sentence introduces a
    description ("described as follows", "following described", or a colon running on
    into a BEGINNING) introduces an easement's description. Before any boundary that
    description is the parcel: the deed's own intro ("subject to easements of record,
    bounded and described as follows:") makes no recital specific.
    """
    if not _PLURAL_EASEMENT_END.search(match.group("open") or match.group("also")):
        return False
    end = _sentence_limit(text, match.end(), min(len(text), match.end() + _RECITAL_WINDOW))
    semicolon = text.find(";", match.end(), end)
    sentence_end = end if semicolon < 0 else semicolon
    if _names_specific_easement(text, match.end(), sentence_end) or (
        after_boundary
        and (
            _DESCRIPTION_INTRO.search(text, match.end(), sentence_end)
            or _COLON_DESCRIPTION.search(text, match.end(), end + 1)
        )
    ):
        return False
    clause_end = _RECITAL_CLAUSE_END.search(text, match.end(), end)
    return (
        _OF_RECORD.search(text, match.end(), end if clause_end is None else clause_end.start())
        is not None
    )


_ADDITION_START = re.compile(r"(?:^|[;\n.])\s*(?:ALSO|INCLUDING)\b", re.IGNORECASE)
_COMMENCING = re.compile(r"\bCOMMENCING\b", re.IGNORECASE)
EASEMENT_LABEL = "Easement"
# The whole lead of a stated exception ("SAVE AND EXCEPT", "ALSO EXCEPTING").
_STATED_EXCEPT_LEAD = re.compile(
    r"\b(?:(?:ALSO|AND|BUT)\s+)?(?:(?:LESS|SAVE)\s+AND\s+)?EXCEPT(?:ING)?\b", re.IGNORECASE
)
# A complete course: a quadrant bearing and a measured distance in the same clause.
# The bearing is any form the course parser reads verbatim (``VERBATIM_BEARING``:
# symbols, words, dashed DMS, symbol-less "N 80 E"); one it then cannot parse fails
# its course closed rather than being set aside.
_COMPLETE_COURSE = re.compile(
    VERBATIM_BEARING.pattern + r"[^;]{0,80}?" + _COURSE_DISTANCE.pattern,
    re.IGNORECASE,
)
# Course wording: any THENCE, or a complete course. A bearing alone ("lying north of
# a line running N 80 degrees E from the pin") locates a dividing line; it is no course.
_TRAVERSE_WORDING = re.compile(r"\bTHENCE\b|" + _COMPLETE_COURSE.pattern, re.IGNORECASE)
# ``_last_closure_end`` when no description has opened.
_NO_DESCRIPTION = -1


# A point of beginning reached by a course ("to the point of beginning", "to the POB").
_POB_REACHED = re.compile(
    r"\bto\s+(?:(?:the|said|a|aforesaid|original|true|initial)\s+)*" + _POB_CLOSE_PATTERN.pattern,
    re.IGNORECASE,
)
# Wording between an easement opener and the tract it types that ends the opener's
# clause: a THENCE (the opener's own courses) or a semicolon.
_OPENER_CLAUSE_BREAK = re.compile(r";|\bTHENCE\b", re.IGNORECASE)


@dataclass(frozen=True)
class _Closure:
    """A point-of-beginning closure and the description opening it closes.

    ``opening`` is the (start, end) of the BEGINNING or COMMENCING the description
    opened with, None when no opening precedes it; ``commencing`` marks COMMENCING.
    """

    start: int
    end: int
    opening: tuple[int, int] | None
    commencing: bool


@dataclass(frozen=True)
class _TextIndex:
    """The clause structure of one text, computed once per text (``_index``).

    Positions are sorted; lookups bisect them instead of re-scanning the text.
    """

    text: str
    # Where a clause after a closed description can end (``_index``).
    stops: tuple[int, ...]
    # Where each description opening (BEGINNING, COMMENCING, THENCE) ends.
    openings: tuple[int, ...]
    # Point-of-beginning closures (start, end) (``_course_closures``), and their ends.
    closures: tuple[tuple[int, int], ...]
    closure_ends: tuple[int, ...]
    # Where each closed MAIN or ADDITION boundary description ends (``_closes_boundary``).
    boundary_ends: tuple[int, ...]
    except_leads: tuple[re.Match[str], ...]
    # Where each tract heading starts.
    headings: tuple[int, ...]
    # Where each easement opener starts and ends, and the easement descriptions they open.
    openers: tuple[int, ...]
    opener_ends: tuple[int, ...]
    easements: tuple[tuple[int, int], ...]

    def next_stop(self, position: int) -> int:
        """Return the first clause stop after ``position``, or the end of the text."""
        i = bisect_right(self.stops, position)
        return self.stops[i] if i < len(self.stops) else len(self.text)

    def after_boundary(self, position: int) -> bool:
        """Return whether a closed MAIN or ADDITION boundary ends before ``position``."""
        return _after_boundary(self.boundary_ends, position)


def _after_boundary(boundary_ends: Sequence[int], position: int) -> bool:
    """Return whether any of the (sorted) ``boundary_ends`` is at or before ``position``."""
    return bool(boundary_ends) and boundary_ends[0] <= position


def _opener_start(match: re.Match[str]) -> int:
    """Return where an ``_EASEMENT_OPENER`` match's opener word starts."""
    return match.start("open") if match["open"] else match.start("also")


@lru_cache(maxsize=32)
def _index(text: str) -> _TextIndex:
    """Return the clause structure of ``text`` (cached: one computation per text)."""
    except_leads = tuple(_STATED_EXCEPT_LEAD.finditer(text))
    headings = tuple(position for position, _, _ in find_tract_markers(text))
    # A structural stated-exception lead, an ALSO/INCLUDING addition, a tract heading
    # or an easement opener starts a new clause.
    structural_leads = [m for m in except_leads if not _is_lot_qualifier_except(text, m)]
    structural = sorted(
        {
            *(m.start() for m in structural_leads),
            *(m.end() - len(m.group().lstrip(";\n. \t")) for m in _ADDITION_START.finditer(text)),
            *headings,
        }
    )
    beginnings = [m.span() for m in _beginning_starts(text)]
    commencings = [m.span() for m in _COMMENCING.finditer(text)]
    openings = sorted(
        {
            *(end for _, end in [*beginnings, *commencings]),
            *(m.end() for m in _THENCE_WORD.finditer(text)),
        }
    )
    closures = _course_closures(text, beginnings, commencings, structural)
    # One pass in text order: whether an opener is a generic recital depends on the
    # boundaries closed before it, and whether a closure closes a boundary on the
    # openers before it.
    openers: list[re.Match[str]] = []
    boundary_ends: list[int] = []
    pending = list(closures)
    floor = 0

    def settle(position: int) -> None:
        nonlocal floor
        while pending and pending[0].start < position:
            closure = pending.pop(0)
            if _closes_boundary(text, closure, floor, structural_leads, openers, boundary_ends):
                boundary_ends.append(closure.end)
            floor = closure.end

    for match in _EASEMENT_OPENER.finditer(text):
        start = _opener_start(match)
        settle(start)
        if not _is_generic_encumbrance(
            text, match, after_boundary=_after_boundary(boundary_ends, start)
        ):
            openers.append(match)
    settle(len(text) + 1)
    opener_starts = tuple(_opener_start(m) for m in openers)
    stops = sorted({*structural, *opener_starts})
    index = _TextIndex(
        text=text,
        stops=tuple(stops),
        openings=tuple(openings),
        closures=tuple((c.start, c.end) for c in closures),
        closure_ends=tuple(c.end for c in closures),
        boundary_ends=tuple(boundary_ends),
        except_leads=except_leads,
        headings=headings,
        openers=opener_starts,
        opener_ends=tuple(m.end() for m in openers),
        easements=(),
    )
    return replace(index, easements=tuple(_easement_spans(index)))


# Fewest courses of a closed boundary: two (a curve and its chord line); a description
# that COMMENCES, or reaches "the true point of beginning", with fewer than three is a
# tie to the point of beginning.
_BOUNDARY_COURSES = 2
_TIE_BOUNDARY_COURSES = 3


def _closes_boundary(
    text: str,
    closure: _Closure,
    floor: int,
    except_leads: Sequence[re.Match[str]],
    openers: Sequence[re.Match[str]],
    boundary_ends: Sequence[int],
) -> bool:
    """Return whether ``closure`` closes a MAIN or ADDITION boundary description.

    ``floor`` is where the previous closure ended. None of these is a boundary:

    * a recital mentioning the point of beginning ("Being the premises whose corner is
      at the point of beginning hereinafter described"): no courses reach it;
    * a tie: a COMMENCING description (or one reaching "the true point of beginning")
      with fewer than three courses (``_TIE_BOUNDARY_COURSES``);
    * an exception description: an EXCEPT lead runs on into its opening with no
      sentence end or course between ("EXCEPTING from the lands hereinafter described
      the following: BEGINNING ...");
    * an easement description: the grant of the last opener before its opening takes
      it (``_grant_takes``).
    """
    opening = closure.opening
    courses = _course_count(text, floor if opening is None else opening[1], closure.start)
    tie = closure.commencing or _TRUE_BEFORE.search(text, max(0, closure.start - 20), closure.start)
    if courses < (_TIE_BOUNDARY_COURSES if tie else _BOUNDARY_COURSES):
        return False
    if opening is None:
        return True
    description = opening[0]
    for lead in except_leads:
        if (
            floor <= lead.start() < description
            and _sentence_break(text, lead.end(), description) is None
            and _TRAVERSE_WORDING.search(text, lead.end(), description) is None
        ):
            return False
    grant = next(
        (_opener_start(m) for m in reversed(openers) if floor <= _opener_start(m) < description),
        None,
    )
    return grant is None or not _grant_takes(
        text, grant, description, _after_boundary(boundary_ends, grant)
    )


# A point of beginning a course leaves from ("and from said point of beginning running").
_FROM_BEFORE = re.compile(
    r"\bfrom\s+(?:(?:the|said|a|aforesaid|original|true|initial)\s+)*$", re.IGNORECASE
)
# "the true point of beginning": the point a tie reaches, whatever opened its description.
_TRUE_BEFORE = re.compile(r"\btrue\s+$", re.IGNORECASE)


def _course_closures(
    text: str,
    beginnings: Sequence[tuple[int, int]],
    commencings: Sequence[tuple[int, int]],
    structural: Sequence[int],
) -> tuple[_Closure, ...]:
    """Return the point-of-beginning mentions that close a description, in text order.

    A closure is a course's destination: a point of beginning reached after the
    description's opening clause, by a THENCE course or by the last course of a
    BEGINNING description stated without THENCE ("...; N 10 E 10 feet to the point of
    beginning"). These mentions close nothing:

    * one inside an opening: in the BEGINNING/COMMENCING clause itself, before any
      THENCE or semicolon ("BEGINNING at an iron pin marking the point of beginning,
      together with ...; thence ..."), or one that opens a description ("POINT OF
      BEGINNING at a pin");
    * a point a course leaves from ("and from said point of beginning running thence");
    * a point of beginning followed directly by THENCE (a tie, as in
      ``find_beginning_blocks``: "to a point and place of beginning, thence; (1) ...");
    * a tie: the first point of beginning reached after COMMENCING, or any "true point
      of beginning", when a THENCE follows in its sentence before any structural clause
      (EXCEPT, ALSO, a tract heading) or another opening ("COMMENCING ...; thence ... to
      the true point of beginning, subject to a right of way ...; thence ..."). The tie
      opens the boundary; it never closes it. Reached with no course after it, the same
      point closes the description.

    Each closure records the opening of the description it closes (``_Closure``).
    """
    starts = sorted(
        [(start, end, False) for start, end in beginnings]
        + [(start, end, True) for start, end in commencings],
        key=lambda opening: opening[1],
    )
    ends = [end for _, end, _ in starts]
    closures: list[_Closure] = []
    for mention in _POB_CLOSE_PATTERN.finditer(text):
        start, end = mention.span()
        i = bisect_right(ends, start)
        if i < len(starts) and starts[i][0] <= start:
            continue  # "POINT OF BEGINNING at ...": an opening
        if i and _OPENER_CLAUSE_BREAK.search(text, ends[i - 1], start) is None:
            continue
        if _FROM_BEFORE.search(text, max(0, start - 60), start) or _POB_CONTINUES.match(text, end):
            continue
        commencing_tie = bool(
            i and starts[i - 1][2] and not (closures and closures[-1].start >= ends[i - 1])
        )
        if commencing_tie or _TRUE_BEFORE.search(text, max(0, start - 20), start):
            course = _THENCE_WORD.search(text, end)
            if (
                course is not None
                and _sentence_break(text, end, course.start()) is None
                and not (i < len(ends) and ends[i] <= course.start())
                and not any(end <= stop < course.start() for stop in structural)
            ):
                continue
        opening = starts[i - 1] if i else None
        closures.append(
            _Closure(
                start,
                end,
                None if opening is None else (opening[0], opening[1]),
                bool(opening and opening[2]),
            )
        )
    return tuple(closures)


def _last_closure_end(
    index: _TextIndex, position: int, closed: Sequence[tuple[int, int]] = ()
) -> int | None:
    """Return where the last description before ``position`` closed.

    A description is open from its last BEGINNING, COMMENCING or THENCE until a
    point-of-beginning closure (``_course_closures``). Returns None while one is still
    open and ``_NO_DESCRIPTION`` when none has opened. ``closed`` spans (easement descriptions
    and exceptions set aside on their own) close where they end, whether or not their
    courses return to a point of beginning; openings inside them are theirs.
    """
    last_end = max((end for _, end in closed if end <= position), default=_NO_DESCRIPTION)
    i = bisect_right(index.openings, position)
    opening = None
    while i > 0:
        i -= 1
        if not any(start <= index.openings[i] <= end for start, end in closed):
            opening = index.openings[i]
            break
    if opening is None or last_end > opening:
        return last_end
    j = bisect_right(index.closure_ends, position)
    if j and index.closures[j - 1][0] >= opening:
        return index.closure_ends[j - 1]
    return None


def _easement_spans(index: _TextIndex) -> list[tuple[int, int]]:
    """Return the spans of appurtenant easement descriptions stated by their own courses.

    An opener inside an open description ("BEGINNING at a pin, subject to a right of
    way, thence ...", "Commencing at a corner, also being ...") qualifies that
    description; it never starts an easement. An opener without a THENCE course
    (``_THENCE_COURSE``, numbered or not) before the next clause stop is a clause
    (metadata), not a description. The description after the opener (its opening, or
    its first course) is the easement's only when the grant takes it (``_grant_takes``,
    the rule every path shares). A span ends with the sentence of its last course when
    only wording without a course follows it before the stop (wording already set
    aside, a recital); otherwise at the stop, so no course is ever left behind on a
    boundary.
    """
    text = index.text
    spans: list[tuple[int, int]] = []
    for start, opener_end in zip(index.openers, index.opener_ends, strict=True):
        if spans and start < spans[-1][1]:
            continue
        # An earlier easement description closes where it ends.
        if _last_closure_end(index, start, spans) is None:
            continue
        stop = index.next_stop(start)
        courses = list(_THENCE_COURSE.finditer(text, start, stop))
        if not courses:
            continue
        first = courses[0].start()
        description = _DESCRIPTION_OPENER.search(text, opener_end, first)
        if not _grant_takes(
            text,
            start,
            first if description is None else description.start(),
            index.after_boundary(start),
            index.headings,
        ):
            continue
        end = stop
        sentence_end = _sentence_break(text, courses[-1].end(), stop)
        if sentence_end is not None and not (
            _TRAVERSE_WORDING.search(text, sentence_end, stop)
            or _COURSE_DISTANCE.search(text, sentence_end, stop)
        ):
            end = sentence_end + (text[sentence_end] == ".")
        spans.append((start, start + len(text[start:end].rstrip())))
    return spans


# A sentence introducing the easement's description after its grant sentence ("The
# said easement is bounded and described as follows:", "Said right of way is
# described as follows:", "which easement being more particularly described as").
_EASEMENT_DESCRIPTION_SENTENCE = re.compile(
    r"\s*(?:the\s+)?(?:said|such|this|which)\s+(?:easements?|rights?[\s-]+of[\s-]+way)\b"
    r"[^.;]{0,120}?\bdescribed\b[^.;]{0,60}?[:,.]?\s*",
    re.IGNORECASE,
)


def _grant_takes(
    text: str,
    opener: int,
    description: int,
    after_boundary: bool,
    headings: Sequence[int] = (),
) -> bool:
    """Return whether the grant opened at ``opener`` takes the description at ``description``.

    The one rule deciding whether an easement opener's grant takes the description
    after it, used by every path: easement spans, BEGINNING blocks and tract markers
    (``_easement_lead``), and boundary closures (``_closes_boundary``). Course
    numbering plays no part in it.

    * A grant clause running on into the description (no sentence break, semicolon or
      THENCE between: ``_sentence_break``, ``_OPENER_CLAUSE_BREAK``) takes it ("TOGETHER
      WITH an easement 10 feet wide, BEGINNING ...", "... as follows: PARCEL B: ...").
    * Across that break, wording introducing the description as the easement's takes it
      ("The said easement is bounded and described as follows:").
    * After a closed MAIN or ADDITION boundary (``after_boundary``), a description
      with nothing but punctuation or document structure between it and the grant's
      sentence end is the easement's ("<boundary> TOGETHER WITH an easement for
      ingress and egress.\nBEGINNING ..."): easement land never becomes a fee tract.
      A tract heading at ``description`` (one of ``headings``) is the heading's tract.
    * Before any boundary the grant sentence never takes the description after it
      ("TOGETHER WITH an easement for utilities. BEGINNING ..."): that description
      is the parcel.
    """
    limit = min(len(text), description + _OPENING_LOOKAHEAD)
    sentence = _sentence_break(text, opener, limit)
    clause = _OPENER_CLAUSE_BREAK.search(text, opener, description)
    ends = [
        *([sentence] if sentence is not None and sentence < description else []),
        *([clause.start()] if clause is not None else []),
    ]
    if not ends:
        return True
    between = text[min(ends) : description]
    if _EASEMENT_DESCRIPTION_SENTENCE.fullmatch(between.lstrip(_LEAD_IN_PUNCTUATION)):
        return True
    if description in headings or STRUCTURE_BREAK.sub(" ", between).strip(
        _LEAD_IN_PUNCTUATION + "#"
    ):
        return False
    return after_boundary


def easement_description_spans(text: str) -> list[tuple[int, int]]:
    """Return the spans of appurtenant easement descriptions stated by their own courses.

    A span runs from its opener to the next clause stop (a structural EXCEPT, an
    ALSO/INCLUDING addition, a tract heading or another opener), or to the end of
    the sentence of its last course (``_easement_spans``).
    """
    return list(_index(text).easements)


# Wording that resumes the course after a comma (its destination or its length): an
# easement clause followed by it is part of the course and is not set aside.
_COURSE_RESUMES = re.compile(r",\s*(?:to\b|a\s+distance\b|\d)", re.IGNORECASE)
# Where an easement clause inside a description ends: a semicolon, a THENCE, or the
# description's "running" ("..., together with an easement ..., running thence").
_EASEMENT_CLAUSE_BREAK = re.compile(
    r";|\bTHENCE\b|(?:,|\band)\s+(?:running|proceeding|continuing)\b", re.IGNORECASE
)


def easement_clause_spans(text: str) -> list[tuple[int, int]]:
    """Return easement clauses stated inside an open description without courses of their own.

    An easement opener inside an open description ("COMMENCING ...; thence ... to the
    true point of beginning, subject to a right of way for ingress and egress; thence
    ...", "BEGINNING at a pin, together with an easement for utilities over the same;
    thence ...") qualifies the description; it is never a tract and never takes a
    course. Its clause runs to the next semicolon, THENCE, "running", sentence end or
    clause stop.
    A clause stating a course or an opening of its own, or followed after a comma by
    its course's destination or length ("..., subject to a right of way, to a pin"), is
    left to its course.
    """
    index = _index(text)
    spans: list[tuple[int, int]] = []
    for start in index.openers:
        if _last_closure_end(index, start, index.easements) is not None:
            continue
        brk = _EASEMENT_CLAUSE_BREAK.search(text, start)
        limit = min(brk.start() if brk else len(text), index.next_stop(start))
        clause = text[start : _sentence_limit(text, start, limit)]
        if (
            _DESCRIPTION_OPENER.search(clause)
            or _COMPLETE_COURSE.search(clause)
            or _COURSE_RESUMES.search(clause)
        ):
            continue
        spans.append((start, start + len(clause.rstrip(" \t\n,;:."))))
    return spans


def _course_count(text: str, start: int, end: int) -> int:
    """Return how many courses ``text[start:end]`` states.

    In each ';'-separated clause every THENCE opens a course, and a complete course
    (bearing and distance) before its first THENCE is one more ("BEGINNING ... S 61° W
    50 feet; thence ...", "Beginning ...; S 80-00-00 E 10 feet; S 10-00-00 W 10 feet;
    ...").
    """
    courses = 0
    clause_starts = [start, *(i + 1 for i in range(start, end) if text[i] == ";")]
    for clause_start, clause_end in zip(clause_starts, [*clause_starts[1:], end], strict=True):
        first = _THENCE_WORD.search(text, clause_start, clause_end)
        courses += len(_THENCE_WORD.findall(text, clause_start, clause_end)) + bool(
            _COMPLETE_COURSE.search(text, clause_start, first.start() if first else clause_end)
        )
    return courses


def _describes_traverse(text: str, start: int, end: int) -> bool:
    """Return whether ``text[start:end]`` describes an exception traverse.

    A traverse has courses (``_course_count``): two or more, or one reaching a point of
    beginning. A single bearing and distance ("lying North of a line running N 80° E
    100 feet from the pin", "a line running thence N 80° E 100 feet to the river")
    locates a dividing line; it is no traverse.
    """
    courses = _course_count(text, start, end)
    return courses >= 2 or (courses == 1 and _POB_REACHED.search(text, start, end) is not None)


def stated_exception_spans(text: str) -> list[tuple[int, int]]:
    """Return the spans of stated exceptions that describe no traverse.

    A stated exception follows a closed description (an easement description set
    aside on its own counts as closed), at a clause start ("... to the point of
    beginning. EXCEPT the South 43.65 feet of said Lot in even width conveyed to
    Jones.") or after wording that states no course ("... to the point of beginning,
    containing 0.23 acres, more or less, EXCEPT that portion conveyed to the State").
    When it describes no traverse before the next clause stop (``_describes_traverse``),
    reading its wording as a course invents one (or fails the deed on a bearing
    without a distance), and splitting on it makes an exception tract without calls
    or a one-course "traverse". Its span runs from its lead to the end of its sentence
    (``ends_sentence``: never at an initial, abbreviation or decimal). An EXCEPT
    inside an open description qualifies that description and is kept.
    """
    index = _index(text)
    spans: list[tuple[int, int]] = []
    for lead in index.except_leads:
        start = lead.start()
        if spans and start < spans[-1][1]:
            continue
        closed_at = _last_closure_end(index, start, [*index.easements, *spans])
        if closed_at is None or closed_at == _NO_DESCRIPTION:
            continue
        if _TRAVERSE_WORDING.search(text, closed_at, start):
            continue
        extent_end = index.next_stop(start)
        # A lead introducing a described parcel ("the following described parcel:
        # PARCEL A: BEGINNING ...") runs on over the parcel's heading.
        while (
            extent_end in index.headings and _sentence_break(text, lead.end(), extent_end) is None
        ):
            extent_end = index.next_stop(extent_end)
        if _describes_traverse(text, lead.end(), extent_end):
            continue
        sentence_end = _sentence_break(text, lead.end(), extent_end)
        end = (
            sentence_end
            if sentence_end is not None
            else start + len(text[start:extent_end].rstrip(" \t\n.;,:"))
        )
        spans.append((start, start + len(text[start:end].rstrip())))
    return spans


def _inside_open_course(text: str, position: int) -> bool:
    """Return whether ``position`` is inside a course that has not ended.

    Its description is open (no point-of-beginning closure since its last opening,
    no easement description closing it) and no sentence has ended since then.
    """
    index = _index(text)
    if _last_closure_end(index, position, index.easements) is not None:
        return False
    i = bisect_right(index.openings, position)
    return i > 0 and _sentence_break(text, index.openings[i - 1], position) is None


def stated_clause_end(text: str, end: int, start: int | None = None) -> int:
    """Return where the clause of wording ending at ``end`` ends.

    Wording continued after a comma or semicolon ("EXCEPT the North 10 feet thereof,
    conveyed to X by deed recorded in Book 12, page 4.") belongs to the clause up to
    its sentence end, unless a traverse, a structural clause, a tract heading or a
    point of beginning starts before it. So is wording after a period that ends no
    sentence ("conveyed to John A. Smith", "the U.S. Government"). Wording starting
    at ``start`` inside a course ("thence N 90° W 100 feet, except the North 10 feet
    thereof, to the point of beginning") never extends: what follows is the course's
    own destination. Otherwise the clause ends at ``end``.
    """
    if text[end : end + 1] not in (",", ";") and not (
        text[end : end + 1] == "." and not ends_sentence(text, end)
    ):
        return end
    if start is not None and _inside_open_course(text, start):
        return end
    sentence_end = _sentence_break(text, end, len(text))
    stop = sentence_end if sentence_end is not None else len(text.rstrip(" \t\n.;,:"))
    rest = text[end:stop]
    if (
        _TRAVERSE_WORDING.search(rest)
        or _STATED_EXCEPT_LEAD.search(rest)
        or _ADDITION_START.search(rest)
        or _EASEMENT_OPENER.search(rest)
        or _POB_CLOSE_PATTERN.search(rest)
        or _BEGINNING_PATTERN.search(rest)
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


def _easement_lead(text: str, position: int, floor: int = 0) -> int | None:
    """Return where the easement opener of the tract starting at ``position`` starts.

    The opener is the last one after ``floor`` (the end of the previous tract) and its
    grant takes the description at ``position`` (``_grant_takes``, the rule the easement
    spans share): its clause runs on to it, however long its grantee wording
    ("RESERVING unto the grantor, its successors and assigns, a perpetual non-exclusive
    easement ... as follows: BEGINNING ..."), or it follows a closed boundary with
    nothing but punctuation or structure after the grant's sentence end.
    """
    index = _index(text)
    # A description the easement spans claim (one introduced as the easement's
    # across its grant sentence's end) is the easement's.
    for span_start, span_end in index.easements:
        if floor <= span_start < position < span_end:
            return span_start
    i = bisect_left(index.openers, position)
    if not i or index.openers[i - 1] < floor:
        return None
    opener = index.openers[i - 1]
    if _grant_takes(text, opener, position, index.after_boundary(opener), index.headings):
        return opener
    return None


def _except_lead(text: str, position: int, floor: int = 0) -> int | None:
    """Return where the EXCEPT lead introducing the tract starting at ``position`` starts.

    The lead follows ``floor`` (the end of the previous tract) and its wording runs on
    to ``position`` with no sentence end and no course ("EXCEPTING THEREFROM the
    following described parcel: PARCEL A: ...", "LESS AND EXCEPT that part described
    as follows: Tract 2: ...").
    """
    leads = [
        lead
        for lead in _index(text).except_leads
        if floor <= lead.start() < position and not _is_lot_qualifier_except(text, lead)
    ]
    if not leads:
        return None
    lead = leads[-1]
    if (
        _sentence_break(text, lead.end(), position) is None
        and _TRAVERSE_WORDING.search(text, lead.end(), position) is None
    ):
        return lead.start()
    return None


def _tract_type_at(text: str, position: int, floor: int = 0) -> TractType:
    """Type of the tract whose wording starts at ``position`` in ``text``.

    An easement opener (``_easement_lead``) makes it an easement and an EXCEPT lead
    introducing it (``_except_lead``) an exception; otherwise EXCEPT and ALSO wording
    in the 80 characters before ``position`` types it.
    """
    if _easement_lead(text, position, floor) is not None:
        return TractType.EASEMENT
    if _except_lead(text, position, floor) is not None:
        return TractType.EXCEPTION
    preceding = text[max(0, position - 80) : position]
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
    # A tract introduced by an EXCEPT lead ("EXCEPTING THEREFROM the following
    # described parcel: PARCEL A: ...") starts at its lead: the lead types it and is
    # never left on the tract before it.
    starts: list[int] = []
    for i, (pos, _, _) in enumerate(markers):
        lead = _except_lead(text, pos, markers[i - 1][0] if i else 0)
        starts.append(pos if lead is None else lead)

    # Boundary calls before the first marker belong to a tract whose heading was
    # not found (e.g. lost by OCR). Keep them under a neutral label; recitals
    # and headers without calls are still dropped.
    if markers and starts[0] > 0:
        pre_text = text[: starts[0]].strip()
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
        end = starts[i + 1] if i + 1 < len(markers) else len(text)
        segment = text[starts[i] : end].strip()

        # Check preceding text for easement/EXCEPT/ALSO wording to assign the TractType
        tract_type = _tract_type_at(text, pos, markers[i - 1][0] if i else 0)

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
    thence; (1) ...") are not closures. ';'-separated wording after the closure that
    is the closing course's own ("; passing a monument at 30 feet") stays in the block
    (``closing_tail_end``).

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

        # ';'-separated wording after the closure is the closing course's own.
        brk = _CLAUSE_BREAK_CHARACTER.search(text, close.end())
        end = close.end()
        if brk is not None and text[brk.start()] == ";":
            tail = closing_tail_end(text, brk.start())
            if tail > brk.start():
                end = tail
        blocks.append((m.start(), end))
    return blocks


# The first clause break after a closure.
_CLAUSE_BREAK_CHARACTER = re.compile(r"[;.]")
# A ';'-separated clause after a closing course that is no wording of that course: a
# later clause, a deed clause, a heading or another description.
_CLAUSE_AFTER_CLOSING = re.compile(
    r"\s*(?:(?:AND|BUT)\s+)?(?:ALSO|INCLUDING|(?:LESS|SAVE)\s+AND|EXCEPT\w*|TRACTS?|PARCELS?|LOTS?"
    r"|TOGETHER|SUBJECT|UNDER|RESERVING|BEING|CONTAINING|BEGINNING|COMMENCING|POINT|PLACE|POB"
    r"|THE\s+ABOVE|SAID\s+PREMISES)\b"
    # "along with" opening the wording is conveyancing, not adjoiner wording, unless
    # it names a line or lands.
    rf"|\s*{CLOSING_ALONG_WITH}",
    re.IGNORECASE,
)


def closing_tail_end(text: str, end: int) -> int:
    """Return where the closing course's ';'-separated wording starting at ``end`` ends.

    ``end`` is where the closing course's clause ends (its first semicolon or
    sentence end after the point of beginning). Wording after a semicolon there
    ("... to the point of beginning; passing a monument at 30 feet.", "...; along the
    line of Smith.") belongs to the closing course, as it would to any course: it is
    read by the course's clause (``extract_course_clause``: a passing call is noted,
    adjoiner wording fails the course closed), never dropped. It runs to the sentence
    end; a clause stating a course, a THENCE, a heading, an easement or another clause
    (``_CLAUSE_AFTER_CLOSING``) ends it. Returns the position of the semicolon or
    sentence end closing the attached wording (``end`` when none is attached).
    """
    while end < len(text) and text[end] == ";":
        semicolon = text.find(";", end + 1)
        sentence_end = _sentence_break(text, end + 1, len(text) if semicolon < 0 else semicolon)
        piece_end = (
            sentence_end if sentence_end is not None else len(text) if semicolon < 0 else semicolon
        )
        piece = text[end + 1 : piece_end]
        if (
            not piece.strip()
            or _CLAUSE_AFTER_CLOSING.match(piece)
            or _TRAVERSE_WORDING.search(piece)
            or _EASEMENT_OPENER.search(piece)
            or find_tract_markers(piece)
        ):
            break
        end = piece_end
    return end


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

    floor = 0
    for start, end, kind, typed_at in _with_unassigned_course_text(blocks, text):
        segment = text[start:end].strip()
        previous_end, floor = floor, end
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
        tract_type = _tract_type_at(text, typed_at, previous_end)
        if tract_type == TractType.EASEMENT:
            # The easement's tract keeps its grant wording and its sentence's period
            # (as when it is set aside from one description); numbered with every
            # other easement by _separate_easements.
            lead = _easement_lead(text, typed_at, previous_end)
            stop = end + 1 if text[end : end + 1] == "." else end
            segment = text[start if lead is None else min(lead, start) : stop].strip()
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
