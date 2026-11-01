"""Split legal descriptions into tracts.

Detects multi-tract patterns in priority order:
1. Explicit markers: TRACT #N, TRACT A, PARCEL N
2. Multiple BEGINNING...POB blocks (text-pattern based)
3. EXCEPT/ALSO clauses (reuses split_exception_clauses)

An appurtenant easement or right of way described by its own courses ("Together
with an easement ... BEGINNING ...; thence ...") is split from whichever tract
holds it into an EASEMENT tract, so its legs never join a parcel boundary.

Classification keeps three invariants, whatever the wording:

* INV-1: the first described parcel, and any description before a closed MAIN
  boundary, is never an EASEMENT or EXCEPTION because of its own preamble (SUBJECT
  TO / TOGETHER WITH / EXCEPTING recitals before it). Two explicit signals are kept:
  an EXCEPT lead taking its exception from lands described later
  (``_FROM_LANDS_DESCRIBED_LATER``) when a separate description does follow
  (``_described_after``; with none, the lead is the sole description's preamble, such
  as a mineral reservation), and an easement deed whose document opens with
  its own grant (``_is_easement_deed_grant``). A deed title alone ("GRANT OF
  EASEMENT") is not recognised. A recital is a preamble only when it does not
  introduce the description: a description introduced by an EXCEPT / LESS / SAVE /
  RESERVING lead (or "Excepted from the above is", "There is excepted",
  ``_EXCEPTED_LEAD``) or a grant of one easement (an opener, or ``_OBJECT_GRANT``: "An
  easement for ingress and egress described as follows:", "GRANTOR grants unto
  GRANTEE a perpetual easement over the following described land:") whose own
  clause runs on into it is that lead's EXCEPTION or EASEMENT, even as the only
  traverse (``_introduced_role``, ``_lead_introduces``); such a document is an
  easement deed. The parcel keeps the description only when its own intro follows
  the lead ("ALL THAT CERTAIN lot, EXCEPTING the mineral rights, bounded and described
  as follows:", "..., said lot being described as follows:") or the lead recites
  rights ("the mineral rights", "the rights of way of record", "SUBJECT TO the right
  of way of Main Street"); a lead taking land or granting one easement that runs on
  to the description after the parcel's intro ("ALL THAT CERTAIN lot known as Lot 5,
  EXCEPTING THEREFROM a strip 10 feet wide along Main Street: BEGINNING") claims it
  too, and two claims fail closed (r58).
* INV-2: only a description after a closed MAIN (or ADDITION) boundary is typed
  EASEMENT (by the grant rule, ``_grant_takes``) or EXCEPTION (by an EXCEPT lead
  introducing it), besides a description its lead introduces (INV-1). An EXCEPT
  inside a description still open keeps typing the description it introduces
  (``_except_may_type``): it is no preamble, and joining the exception's courses to
  the boundary would invent boundary courses. An easement clause whose courses are no
  traverse (one course not closing) is noted, never a description.
* INV-3: whether a boundary closed is decided from the parser's own course reading
  (``_course_count``: THENCE courses and enumerated course lists), never from THENCE
  words alone; a separate description after a closure is a traverse, never a tie line.

Each segment also records its role basis (``split_into_tracts_with_basis``). The certain
bases are allow-listed (r59), never decided by a deny-list of role wording:
"heading" for a TRACT/PARCEL heading typed MAIN or ADDITION whose plain label is
followed by nothing or the parcel's own intro, with only harmless sentences before it
(``_sentence_role``: no role wording, generic or rights recitals, or a recital about the
previous parcel when the parcel's own intro follows) and no role statement after the
last description (``_heading_basis``); "single" for a deed's only MAIN description when
nothing that introduces, titles or follows it names a role outside those recitals and
the parcel's own intro sentence (``sole_description_basis``, decided by
``extract_calls``); "inferred" for every other role, decided by the wording rules above
(or assumed from position). The rules are heuristics, so a deed with any inferred role,
a single description's included, is never eligible for verified export
(``mp_models.roles_need_review``, fail closed).
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, replace
from functools import cached_property, lru_cache

import structlog
from mp_models import RoleBasis, TractType, is_boundary_tract

from .metadata import (
    _ENUMERATOR_STYLES,
    CLOSING_ALONG_WITH,
    CONDITIONAL_EXCEPT_AFTER,
    STRUCTURE_BREAK,
    VERBATIM_BEARING,
    _is_lot_qualifier_except,
    analyze_course_lists,
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
    r"(?:-(?:\d+|[A-Z]))?)"
    # "TRACT 12th": an ordinal suffix belongs to the number, never a letter ID.
    r"(?:(?<=\d)(?:st|nd|rd|th))?\b",
    re.IGNORECASE,
)

# SCHEDULE A-1 (one property per schedule in a multi-property deed); a lone "Schedule A"
# names the attachment, not a tract.
_SCHEDULE_MARKER = re.compile(r"\b(?P<kind>SCHEDULE)\s+(?P<id>[A-Z]-?\d+)\b", re.IGNORECASE)

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
# (tract_text, label, tract_type, role_basis): ``split_into_tracts_with_basis``.
BasedSegment = tuple[str, str, TractType, RoleBasis]
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


# A grant of one easement or right of way named without an opener word (r58): the
# object at a clause start ("An easement for ingress and egress described as follows:",
# "A 20 foot wide right of way ...", "TRACT 2: A non-exclusive easement ..."), after a
# grant verb ("GRANTOR hereby grants and conveys unto GRANTEE a perpetual non-exclusive
# easement ...", "The Grantor grants a sanitary sewer easement ...") or after SUBJECT TO
# / TOGETHER WITH / RESERVING inside a sentence ("Said Parcel A is subject to the
# following easement:"). Like an opener's grant, it types a description only when its
# own clause introduces it (``_lead_introduces``); an easement deed is a document whose
# only description such a grant introduces.
_GRANT_VERB = (
    r"\b(?:grants?|conveys?|releases?|dedicates?)(?:\s*,?\s*(?:and\s+)?"
    r"(?:grants?|conveys?|releases?|bargains?|sells?|confirms?|warrants?|dedicates?)\b)*"
)
_GRANT_VERB_GRANTEE = (
    r"(?:\s*,?\s*(?:unto|to)\s+(?:the\s+)?(?:said\s+)?\w+(?:\s*,?\s*(?:and\s+)?(?:its|his|her"
    r"|their)\s+"
    + _EASEMENT_SUCCESSORS
    + r"(?:\s*,?\s*(?:and\s+)?"
    + _EASEMENT_SUCCESSORS
    + r")*)?\s*,?)?"
)
_OBJECT_GRANT = re.compile(
    r"(?:(?:^|(?<=[.;:\n]))[ \t*_#>]*|" + _GRANT_VERB + _GRANT_VERB_GRANTEE + r"\s*"
    r"|\b(?:subject\s+to|together\s+with|reserving)\s+)"
    r"(?P<grant>(?:an?|that\s+certain|the\s+following)\s+"
    + _EASEMENT_MODIFIER
    + r"(?:easement|right[\s-]+of[\s-]+way)\b"
    + _NOT_AREA
    + r")",
    re.IGNORECASE,
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
_PRECEDING_EXCEPT = re.compile(r"\b(?:LESS\s+AND\s+)?EXCEPT(?:ING)?\b", re.IGNORECASE)
# An EXCEPT lead taking its exception from lands described later ("EXCEPTING from the
# lands hereinafter described the following: BEGINNING ..."): the one preamble wording
# that types the first description (INV-1).
_FROM_LANDS_DESCRIBED_LATER = re.compile(
    r"\bfrom\s+(?:the\s+|said\s+)?(?:lands?|premises|property|tracts?|parcels?|lots?)\s+"
    r"(?:(?:herein\s*after|below)\s+(?:described|set\s+forth)"
    r"|(?:described|set\s+forth)\s+(?:herein\s*after|below))\b",
    re.IGNORECASE,
)
_COMMENCING = re.compile(r"\bCOMMENCING\b", re.IGNORECASE)
# A lead taking land out of the grant that is no stated EXCEPT lead: LESS, SAVE,
# RESERVING, or (r59) EXCLUDING / SAVING at a clause start ("LESS PARCEL B:",
# "RESERVING unto the Grantor the following described tract:", "EXCLUDING therefrom the
# following described parcel:", "SAVING AND EXCLUDING PARCEL B:"); "more or less" is
# never one.
# "LOT 48 EXCLUDING THAT PART DESCRIBED AS ...": that phrase takes a described part out
# of the grant even mid-sentence (MIWAYN-50428).
_TAKING_LEAD = re.compile(
    r"(?:^|(?<=[.;:,\n])|(?<=\s)(?=EXCLUDING\s+THAT\s+PART\b))[ \t]*"
    r"(?P<lead>(?:(?:ALSO|AND|BUT)\s+)?"
    r"(?:(?:LESS|SAVE|SAVING)(?:\s+AND\s+EXCLUDING)?|EXCLUDING|RESERVING)\b)",
    re.IGNORECASE,
)
# The r59 leads alone (EXCLUDING, SAVING): they type a description they introduce, but
# inside a parcel's own intro ("ALL THAT lot, excluding the street, described as
# follows:") they are no role lead for a heading (``_heading_basis``).
_EXCLUDING_LEAD = re.compile(r"(?:(?:ALSO|AND|BUT)\s+)?(?:EXCLUDING|SAVING)\b", re.IGNORECASE)
# Exception leads with no EXCEPT verb lead (r58): "Excepted from the above is ...",
# "There is (also) excepted therefrom ...", "The following is excepted: ...". They take
# land out of the grant like a stated EXCEPT lead ("Excepting out of", "Less and
# excepting" already are).
_EXCEPTED_LEAD = re.compile(
    r"(?:^|(?<=[.;:,\n]))[ \t]*(?P<lead>(?:(?:ALSO|AND|BUT)\s+)?(?:"
    r"THERE\s+(?:IS|ARE)\s+(?:ALSO\s+)?(?:HEREBY\s+)?EXCEPTED"
    r"|EXCEPTED\s+(?:THEREFROM|HEREFROM|FROM|OUT\s+OF)"
    r"|THE\s+FOLLOWING\s+(?:IS|ARE)\s+(?:ALSO\s+)?(?:HEREBY\s+)?EXCEPTED)\b)",
    re.IGNORECASE,
)
# The parcel's own lead naming conveyed land ("ALL THAT CERTAIN lot", "ALL THOSE TWO
# tracts", "ALL THAT PORTION of ..."), never land a grant runs over ("an easement over
# all that strip": ``_LOCATING_BEFORE``). From it on, wording introduces the parcel,
# not a lead's object, and no grant takes the description it introduces (r58).
_PARCEL_LAND_LEAD = re.compile(
    r"\bALL\s+(?:THAT|THOSE)\s+(?:[\w-]+,?\s+){0,3}?(?:lots?|tracts?|parcels?|pieces?|lands?"
    r"|premises|property|real\s+(?:estate|property)|units?|portions?|parts?)\b",
    re.IGNORECASE,
)


def _parcel_lead_between(text: str, start: int, end: int) -> int | None:
    """Return where the parcel's own lead (``_PARCEL_LAND_LEAD``) in ``text[start:end]`` starts."""
    return next(
        (
            match.start()
            for match in _PARCEL_LAND_LEAD.finditer(text, start, end)
            if not _LOCATING_BEFORE.search(text, max(start, match.start() - 20), match.start())
        ),
        None,
    )


# The parcel's description intro after a recital set off by commas inside the parcel's
# sentence ("ALL THAT lot, SUBJECT to ..., bounded and described as follows:", "...,
# being more particularly described as follows:").
_PARCEL_INTRO = re.compile(
    r",\s*(?:and\s+)?(?:(?:being|which\s+is|that\s+is)\s+)?(?:more\s+)?(?:particularly\s+)?"
    r"(?:bounded\s+and\s+described|described|bounded)\b",
    re.IGNORECASE,
)
# The conveyed land named as the one described after a lead ("..., the premises being
# described as follows:", "..., said lot being described as follows:"); never a lead's
# own object ("the parcel described as follows"). The same noun in the lead's own
# clause ("EXCEPTING a tract of land, said tract being described ...") refers back to
# the lead's object, so it is no parcel intro there.
_NAMED_PARCEL_DESCRIBED = re.compile(
    r"\b(?:the|said)\s+(?P<noun>premises|lot|land|tract|parcel|property)s?\s+"
    r"(?:(?:referred\s+to\s+herein|herein\s+referred\s+to|herein|aforesaid)\s+)?"
    r"(?:is|are|being|which\s+(?:is|are))\s+(?:more\s+)?(?:particularly\s+)?"
    r"(?:bounded\s+and\s+)?described\b",
    re.IGNORECASE,
)
# A lead's own clause naming its object as the one described ("the following described
# parcel", "that part described as follows", "an easement ... described as follows",
# "the following:"): the description is the lead's even against a parcel intro in the
# same sentence (two claims on one description fail closed). So is a lead running
# straight into it ("EXCEPTING THEREFROM:", "LESS PARCEL B:").
_OBJECT_DESCRIBED = re.compile(
    r"\b(?:described\s+as\s+follows|as\s+follows|following\s+described|the\s+following)\b",
    re.IGNORECASE,
)
_LEAD_ALONE = re.compile(
    r"\s*(?:(?:there|here)(?:from|out|of)\b\s*)?(?::\s*)?(?:(?:TRACT|PARCEL)\b[^:\n]{0,20}:\s*)?",
    re.IGNORECASE,
)
# A rights recital (r58): a lead's object that is rights, never land that is described:
# mineral, oil and gas rights, plural easements or rights of way, rights of the public,
# or any portion lying within a right of way, street or bed ("RESERVING unto the Grantor
# the mineral rights", "LESS the rights of way of record", "SAVE AND EXCEPT any portion
# lying within the right of way of Main Street"). It never introduces a description,
# unless its clause goes on to name land (``_LAND_NOUN``: "... and the parcel conveyed
# to Smith:"). "That portion lying within ..." may be the excepted strip described next,
# so only "any" or "all" portions are rights.
_RIGHTS_RECITAL = re.compile(
    r"[\s,]*(?:(?:unto|to|for)\s+[^,:;]{0,80}?(?:,\s*|\s+(?=(?:all|any|the|its|their)\b)))?"
    r"(?:(?:there|here)(?:from|out|of)\s+)?(?:"
    r"(?:(?:all|any)\s+(?:(?:and|or)\s+(?:all|any)\s+)?(?:of\s+)?)?(?:(?:the|its|their|such|said)\s+)?"
    r"(?:(?:[\w-]+,?\s+(?:(?:and|or|&)\s+)?){0,4}?(?:minerals?|oil|gas|coal|timber|petroleum"
    r"|hydrocarbons?)\b"
    r"|(?:[\w-]+\s+){0,2}?(?:easements|rights[\s-]+of[\s-]+way)\b"
    r"|rights?\s+of\s+the\s+public\b)"
    r"|(?:all|any)\s+(?:(?:and|or)\s+(?:all|any)\s+)?(?:portions?|parts?)\s+(?:thereof\s+)?"
    r"(?:(?:lying|being|located|situated?|falling)\s+)?(?:with)?in\s+(?:(?:the|a|any)\s+)?"
    r"(?:[\w-]+\s+){0,3}?(?:rights?[\s-]+of[\s-]+way|streets?|roads?|highways?|avenues?|lanes?"
    r"|alleys?|beds?)\b)",
    re.IGNORECASE,
)
_LAND_NOUN = re.compile(
    r"\b(?:parcels?|tracts?|lots?|strips?|pieces?|lands?|premises|portions?|parts?|areas?)\b",
    re.IGNORECASE,
)
# A public road's right of way recited as an encumbrance ("SUBJECT TO the right of way
# of Main Street:"): a rights recital. Taken out of the grant ("EXCEPTING the right of
# way of Route 30:") it may be the strip described next, so only SUBJECT TO recites it.
_STREET_RIGHT_OF_WAY = re.compile(
    r"SUBJECT\s+TO\s+(?:the\s+)?(?:(?:existing|public|legal)\s+)?rights?[\s-]+of[\s-]+way\s+"
    r"(?:of|in)\s+(?:the\s+)?(?:[\w'.-]+\s+){0,4}?(?:streets?|roads?|avenues?|highways?|lanes?"
    r"|drives?|boulevards?|pikes?|turnpikes?|routes?)\b(?:\s+(?:no\.?\s*)?\d+[A-Z]?)?[\s,:]*",
    re.IGNORECASE,
)


# A second lead word joined to a lead ("EXCEPTING AND RESERVING", "SAVE AND EXCEPT"): part
# of the lead, never of its object.
_JOINED_LEAD = re.compile(
    r"(?:\s*,?\s*(?:and|&)\s+(?:reserv(?:e|es|ed|ing)|except(?:s|ed|ing)?|exclud(?:e|es|ed|ing)"
    r"|sav(?:e|ing)))+\b",
    re.IGNORECASE,
)


def _after_joined_lead(text: str, position: int, end: int) -> int:
    """Return where a lead's object starts after ``position`` (past any ``_JOINED_LEAD``)."""
    joined = _JOINED_LEAD.match(text, position, end)
    return position if joined is None else joined.end()


def _rights_recital(text: str, lead_start: int, lead_end: int, own_end: int) -> bool:
    """Return whether the lead ``text[lead_start:lead_end]`` with its clause recites rights.

    ``_RIGHTS_RECITAL`` for the clause after any joined lead word ("EXCEPTING AND
    RESERVING unto the Grantor all oil, gas and minerals": ``_JOINED_LEAD``), naming no
    land after it, or a public road's right of way under SUBJECT TO
    (``_STREET_RIGHT_OF_WAY``).
    """
    # TODO(r59): adopt rights.is_rights_clause from fix/pr60-r59-rights once merged.
    clause = text[_after_joined_lead(text, lead_end, own_end) : own_end]
    rights = _RIGHTS_RECITAL.match(clause)
    if rights is not None and not _LAND_NOUN.search(clause, rights.end()):
        return True
    return _STREET_RIGHT_OF_WAY.fullmatch(text, lead_start, own_end) is not None


# A BEING recital ("BEING known as Block 91 Lot 32", "being the same premises ...").
_BEING_RECITAL = re.compile(r"\s*BEING\b", re.IGNORECASE)
_OPENING_WORD = re.compile(r"\b(?:BEGINNING|COMMENCING)\b", re.IGNORECASE)
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
    # Where each closed BEGINNING description that is no tie ends (``_described_ends``).
    described_ends: tuple[int, ...]
    # Where each THENCE course (``_THENCE_COURSE``) starts: a description has started.
    description_starts: tuple[int, ...]
    except_leads: tuple[re.Match[str], ...]
    # Where each tract heading starts.
    headings: tuple[int, ...]
    # Where each easement opener starts and ends, and the easement descriptions they open.
    openers: tuple[int, ...]
    opener_ends: tuple[int, ...]
    # Where an easement deed's own grant starts (``_is_easement_deed_grant``), if any.
    deed_grant: int | None
    # Leads that can introduce a description as an exception (stated EXCEPT leads,
    # ``_TAKING_LEAD`` and ``_EXCEPTED_LEAD``) or an easement (openers granting one
    # easement, never plural "easements", and ``_OBJECT_GRANT`` grants): (start, end).
    taking: tuple[tuple[int, int], ...]
    grants: tuple[tuple[int, int], ...]
    # Per closure: whether a separate description (a traverse) opens after it.
    follows: tuple[bool, ...]
    easements: tuple[tuple[int, int], ...]
    # Easement clauses after a closed description whose courses are no traverse.
    easement_clauses: tuple[tuple[int, int], ...] = ()
    # Grants of one easement named without an opener word (``_OBJECT_GRANT``).
    object_grants: tuple[tuple[int, int], ...] = ()

    @cached_property
    def text_role(self) -> TractType | None:
        """Role of the text's first description when a lead introduces it, computed once.

        ``_introduced_role`` of the first description (``_opening_after``): EXCEPTION or
        EASEMENT, or None when no lead introduces it (the parcel's own).
        """
        opening = _opening_after(self.text, 0)
        found = None if opening is None else self.introduced(opening)
        return None if found is None else found[1]

    def next_stop(self, position: int) -> int:
        """Return the first clause stop after ``position``, or the end of the text."""
        i = bisect_right(self.stops, position)
        return self.stops[i] if i < len(self.stops) else len(self.text)

    def after_boundary(self, position: int) -> bool:
        """Return whether a closed MAIN or ADDITION boundary ends before ``position``."""
        return _after_boundary(self.boundary_ends, position)

    def may_grant(self, opener: int) -> bool:
        """Return whether the opener at ``opener`` may type a description an easement.

        After a closed boundary (INV-2), or as an easement deed's own grant; before the
        first boundary any other opener is the parcel's preamble (INV-1).
        """
        return self.after_boundary(opener) or opener == self.deed_grant

    def introduced(self, description: int, floor: int = 0) -> tuple[int, TractType] | None:
        """Return the lead introducing the description at ``description`` and its role.

        ``_introduced_role`` with this text's leads after ``floor``.
        """
        return _introduced_role(self.text, description, floor, self.taking, self.grants)


def _starts_clause(text: str, position: int) -> bool:
    """Return whether ``position`` starts a sentence or clause of its own.

    Only whitespace or markdown separates it from the start of the text, a colon, a
    semicolon, a line break or a sentence-ending period. A lead after other wording
    ("ALL THAT lot, SUBJECT to ...") is a recital inside that wording's sentence.
    """
    i = position
    while i > 0 and text[i - 1] in " \t*_#":
        i -= 1
    if i == 0 or text[i - 1] in ":;\n":
        return True
    return text[i - 1] == "." and ends_sentence(text, i - 1)


_OBJECT_PHRASE_END = re.compile(r"[,;:]")
# Where a lead's object phrase names land a later "said <noun>" refers back to: its
# direct object ("EXCEPTING THEREFROM Lot 5A", "a tract of land") or land after a
# preposition of the object ("a strip of land", "an easement over a tract"); never land
# the lead takes something from ("from the premises hereinafter described").
_REFERS_BACK = (
    r"(?:^[\s,]*(?:(?:there|here)(?:from|out|of)\b[\s,]*)?"
    r"(?:(?:an?|that|those|the(?:\s+following)?|one|certain)\s+)?"
    r"(?:(?!(?:of|from|in|on|to|for|by|at|with|over|across|upon|through|along|within|under)\b)"
    r"[\w-]+\s+){0,3}?"
    r"|\b(?:of|over|across|upon|through|along|in|within)\s+(?:(?:an?|the|that|said)\s+)?"
    r"(?:[\w-]+\s+){0,2}?)"
)


def _parcel_intro_after(text: str, lead_end: int, end: int, own_sentence: bool) -> int | None:
    """Return where the parcel's own intro after a lead starts, before ``end``, or None.

    The parcel lead (``_PARCEL_LAND_LEAD``: "ALL THAT CERTAIN lot"), the conveyed land
    named as the one described ("the premises being described", "said lot being
    described", "The land referred to herein is described": ``_NAMED_PARCEL_DESCRIBED``,
    unless the lead's own object phrase, up to its first comma or colon, names the same
    land, which it then refers back to (``_REFERS_BACK``: "EXCEPTING THEREFROM a strip
    of land, said land being described"), or, for a recital inside the parcel's sentence
    (not ``own_sentence``), the comma intro (``_PARCEL_INTRO``: "..., bounded and
    described as follows:"). Wording from it on is the parcel's.
    """
    lead = _parcel_lead_between(text, lead_end, end)
    found = [] if lead is None else [lead]
    for named in _NAMED_PARCEL_DESCRIBED.finditer(text, lead_end, end):
        phrase_end = _OBJECT_PHRASE_END.search(text, lead_end, named.start())
        phrase = text[lead_end : named.start() if phrase_end is None else phrase_end.start()]
        if not re.search(_REFERS_BACK + rf"{named['noun']}s?\b", phrase, re.IGNORECASE):
            found.append(named.start())
            break
    if not own_sentence:
        intro = _PARCEL_INTRO.search(text, lead_end, end)
        if intro is not None:
            found.append(intro.start())
    return min(found, default=None)


def _lead_introduces(text: str, lead_start: int, lead_end: int, description: int) -> bool:
    """Return whether the lead ``text[lead_start:lead_end]`` introduces ``description``.

    Its clause must run on into the description: no sentence break
    (``_sentence_break``), semicolon, THENCE or course between. Then, in order:

    1. The lead's own clause (up to the parcel's intro after it,
       ``_parcel_intro_after``) names its object as the one described ("EXCEPTING
       THEREFROM the following described parcel:", "LESS AND EXCEPT that part described
       as follows:", "over the following described strip:", "an easement for drainage
       described as follows:", "EXCEPTING THEREFROM:", "LESS PARCEL B:"): the
       description is the lead's, even against the parcel's own intro in the sentence
       (two claims on one description fail closed: never the parcel).
    2. The parcel's own intro after the lead ("ALL THAT CERTAIN lot", "the premises
       being described", "..., bounded and described as follows:"): the lead is a
       recital inside the parcel's sentence and the description is the parcel's
       ("Being Lot 5, RESERVING unto the Grantor the mineral rights, the premises being
       described as follows: BEGINNING ...").
    3. A rights recital (``_rights_recital``: mineral, oil and gas rights, rights of way
       of record, any portion within a right of way, a public road's right of way under
       SUBJECT TO) introduces no description ("ALL THAT CERTAIN lot more particularly
       described as follows, SUBJECT TO the right of way of Main Street: BEGINNING ...").
    4. Otherwise a colon in the lead's clause, or the lead starting its own sentence and
       running on into the description, introduces it, whatever parcel intro precedes
       the lead: "ALL THAT CERTAIN lot known as Lot 5, EXCEPTING THEREFROM a strip 10
       feet wide along Main Street: BEGINNING ..." most likely describes the strip, so
       the two claims fail closed (r58) and the description is never the parcel. A lead
       inside the parcel's sentence that neither has a colon nor starts its own sentence
       ("ALL THAT CERTAIN lot, TOGETHER WITH an easement for access, BEGINNING ...")
       introduces nothing (INV-1).
    """
    # The break test reads the description's own opening word (a line break before a
    # BEGINNING breaks the sentence only when that BEGINNING is in view).
    brk = _sentence_break(text, lead_end, min(len(text), description + _OPENING_LOOKAHEAD))
    if (
        (brk is not None and brk < description)
        or _OPENER_CLAUSE_BREAK.search(text, lead_end, description)
        or _TRAVERSE_WORDING.search(text, lead_end, description)
    ):
        return False
    own_sentence = _starts_clause(text, lead_start)
    intro = _parcel_intro_after(text, lead_end, description, own_sentence)
    own_end = description if intro is None else intro
    clause = text[lead_end:own_end]
    if _OBJECT_DESCRIBED.search(clause) or (
        _LEAD_ALONE.fullmatch(clause) and (":" in clause or _MARKER.match(text, own_end))
    ):
        return True
    if intro is not None or _rights_recital(text, lead_start, lead_end, own_end):
        return False
    return ":" in clause or own_sentence


def _introduced_role(
    text: str,
    description: int,
    floor: int,
    taking: Sequence[tuple[int, int]],
    grants: Sequence[tuple[int, int]],
) -> tuple[int, TractType] | None:
    """Return where the lead introducing the description at ``description`` starts, and its role.

    The nearest lead after ``floor`` whose own clause introduces the description
    (``_lead_introduces``): an EXCEPT / LESS / SAVE / RESERVING lead (``taking``) makes
    it an EXCEPTION, a grant of one easement (``grants``) an EASEMENT. Such a
    description is never the parcel (INV-1 covers only preamble recitals the parcel's
    own lead introduces), even when it is the deed's only traverse. None when no lead
    introduces it.
    """
    candidates = [(start, end, TractType.EXCEPTION) for start, end in taking]
    candidates += [(start, end, TractType.EASEMENT) for start, end in grants]
    for start, end, role in sorted(
        (c for c in candidates if floor <= c[0] < description),
        key=lambda c: (c[0], c[2] == TractType.EASEMENT),
        reverse=True,
    ):
        if _lead_introduces(text, start, end, description):
            return start, role
    return None


def _opening_after(text: str, start: int, end: int | None = None) -> int | None:
    """Return where the first description after ``start`` (before ``end``) opens.

    Its BEGINNING at/in or COMMENCING (never a point of beginning reached: "to the point
    of beginning at ..."), or else its first THENCE course; None without one.
    """
    end = len(text) if end is None else end
    found = [
        match.start()
        for match in (
            next(
                (
                    m
                    for m in _BEGINNING_PATTERN.finditer(text, start, end)
                    if not _REACHED_BEFORE.search(text, max(0, m.start() - 40), m.start())
                ),
                None,
            ),
            _COMMENCING.search(text, start, end),
            _THENCE_COURSE.search(text, start, end),
        )
        if match is not None
    ]
    return min(found, default=None)


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
    described_ends = _described_ends(text, closures)
    # Read only for an EXCEPT lead taking land "from the lands hereinafter described"
    # (course lists are then read once more per later description).
    follows = (
        _traverses_after(text, closures, [*beginnings, *commencings])
        if _FROM_LANDS_DESCRIBED_LATER.search(text)
        else (False,) * len(closures)
    )
    # A BEGINNING opening alone starts none: recording references read as one
    # ("recorded in Deed Book 5264, beginning at Page 849").
    description_starts = tuple(m.start() for m in _THENCE_COURSE.finditer(text))
    opener_matches = list(_EASEMENT_OPENER.finditer(text))
    # A RESERVING that opens an easement grant ("RESERVING to the grantor the right of
    # way ...") is that grant, never an exception lead.
    grant_words = {_opener_start(m) for m in opener_matches}
    # One lead per start, its whole wording ("SAVE AND EXCEPT", never "SAVE" alone).
    leads: dict[int, int] = {}
    for start, end in (
        *(m.span() for m in structural_leads),
        *(
            m.span("lead")
            for m in _TAKING_LEAD.finditer(text)
            if m.start("lead") not in grant_words
        ),
        *(m.span("lead") for m in _EXCEPTED_LEAD.finditer(text)),
    ):
        leads[start] = max(end, leads.get(start, end))
    taking = tuple(sorted(leads.items()))
    # A grant named without an opener word, unless an opener already grants it.
    opener_spans = [(_opener_start(m), m.end()) for m in opener_matches]
    object_grants = tuple(
        m.span("grant")
        for m in _OBJECT_GRANT.finditer(text)
        if not any(start <= m.start("grant") < end for start, end in opener_spans)
    )
    # One pass in text order: whether an opener is a generic recital depends on the
    # boundaries closed before it, and whether a closure closes a boundary on the
    # openers before it.
    openers: list[re.Match[str]] = []
    grants: list[tuple[int, int]] = list(object_grants)
    boundary_ends: list[int] = []
    pending = list(enumerate(closures))
    floor = 0

    def settle(position: int) -> None:
        nonlocal floor
        while pending and pending[0][1].start < position:
            number, closure = pending.pop(0)
            if _closes_boundary(
                text,
                closure,
                floor,
                structural_leads,
                openers,
                boundary_ends,
                (described_ends, description_starts),
                (taking, grants),
                follows[number],
            ):
                boundary_ends.append(closure.end)
            floor = closure.end

    for match in opener_matches:
        start = _opener_start(match)
        settle(start)
        if not _is_generic_encumbrance(
            text, match, after_boundary=_after_boundary(boundary_ends, start)
        ):
            openers.append(match)
            # One easement can introduce a description; plural ones ("all easements
            # appurtenant thereto") describe none.
            if not _PLURAL_EASEMENT_END.search(match.group("open") or match.group("also")):
                grants.append((start, match.end()))
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
        described_ends=described_ends,
        description_starts=description_starts,
        except_leads=except_leads,
        headings=headings,
        openers=opener_starts,
        opener_ends=tuple(m.end() for m in openers),
        deed_grant=(
            opener_starts[0] if openers and _is_easement_deed_grant(text, openers[0]) else None
        ),
        taking=taking,
        grants=tuple(sorted(grants)),
        follows=follows,
        easements=(),
        object_grants=object_grants,
    )
    easements, clauses = _easement_spans(index)
    return replace(index, easements=tuple(easements), easement_clauses=tuple(clauses))


def _traverses_after(
    text: str, closures: Sequence[_Closure], openings: Sequence[tuple[int, int]]
) -> tuple[bool, ...]:
    """Return, per closure, whether a separate description opens after it.

    A separate description is a traverse (``_describes_traverse``: two or more courses,
    or one reaching a point of beginning) after a BEGINNING or COMMENCING opening. A tie
    line or one-course clause after the closure ("The said point of beginning being
    located from the monument as follows: thence N 10° E 50 feet.") is none.
    """
    ends = [closure.end for closure in closures]
    traverses = sorted(
        start
        for start, end in openings
        if _describes_traverse(
            text,
            end,
            next((e for e in ends if e > end), len(text)),
        )
    )
    return tuple(bisect_left(traverses, end) < len(traverses) for end in ends)


# Fewest courses of a closed boundary: two (a curve and its chord line); a description
# that COMMENCES, or reaches "the true point of beginning", with fewer than three is a
# tie to the point of beginning.
_BOUNDARY_COURSES = 2
_TIE_BOUNDARY_COURSES = 3


def _described_ends(text: str, closures: Sequence[_Closure]) -> tuple[int, ...]:
    """Return where each closed BEGINNING description that is no tie ends.

    A closure whose description opened with BEGINNING and does not reach "the true
    point of beginning", whatever its course count: never a COMMENCING tie or a
    recital mentioning the point of beginning. EXCEPT wording after one follows a
    described parcel, so it is no preamble (``_except_may_type``).
    """
    return tuple(
        closure.end
        for closure in closures
        if closure.opening is not None
        and not closure.commencing
        and _TRUE_BEFORE.search(text, max(0, closure.start - 20), closure.start) is None
    )


def _closes_boundary(
    text: str,
    closure: _Closure,
    floor: int,
    except_leads: Sequence[re.Match[str]],
    openers: Sequence[re.Match[str]],
    boundary_ends: Sequence[int],
    descriptions: tuple[Sequence[int], Sequence[int]] = ((), ()),
    leads: tuple[Sequence[tuple[int, int]], Sequence[tuple[int, int]]] = ((), ()),
    follows: bool = False,
) -> bool:
    """Return whether ``closure`` closes a MAIN or ADDITION boundary description.

    ``floor`` is where the previous closure ended. None of these is a boundary:

    * a recital mentioning the point of beginning ("Being the premises whose corner is
      at the point of beginning hereinafter described"): no courses reach it;
    * a tie: a COMMENCING description (or one reaching "the true point of beginning")
      with fewer than three courses (``_TIE_BOUNDARY_COURSES``);
    * a description its lead introduces (``_introduced_role`` over ``leads``: the taking
      leads and specific grants): the lead's exception or easement, before or after
      any boundary;
    * an exception description: an EXCEPT lead runs on into its opening with no
      sentence end or course between ("EXCEPTING from the lands hereinafter described
      the following: BEGINNING ...");
    * an easement description: the grant of the last opener before its opening takes
      it (``_grant_takes``).

    Before any boundary has closed (INV-1) neither a preamble EXCEPT lead nor a grant
    makes a description no boundary: only a lead introducing it, an EXCEPT lead that is
    no preamble (after a closed BEGINNING description or inside one still open,
    ``descriptions``: the ``_described_ends`` and the description starts, as
    ``_except_may_type`` reads them) or that takes its exception from lands described
    later (``_FROM_LANDS_DESCRIBED_LATER``, when a separate description ``follows``
    this one), or an easement deed's own grant (``_is_easement_deed_grant``).
    """
    described_ends, starts = descriptions
    opening = closure.opening
    courses = _course_count(text, floor if opening is None else opening[1], closure.start)
    tie = closure.commencing or _TRUE_BEFORE.search(text, max(0, closure.start - 20), closure.start)
    if courses < (_TIE_BOUNDARY_COURSES if tie else _BOUNDARY_COURSES):
        return False
    if opening is None:
        return True
    description = opening[0]
    if _introduced_role(text, description, floor, *leads) is not None:
        return False
    for lead in except_leads:
        if (
            floor <= lead.start() < description
            and _sentence_break(text, lead.end(), description) is None
            and _TRAVERSE_WORDING.search(text, lead.end(), description) is None
            and (
                bool(boundary_ends)
                or _after_boundary(described_ends, lead.start())
                # A description opened since the last closure is still open.
                or bisect_left(starts, floor) < bisect_left(starts, lead.start())
                or (
                    _FROM_LANDS_DESCRIBED_LATER.search(text, lead.start(), description) is not None
                    and follows
                )
            )
        ):
            return False
    grant = next(
        (m for m in reversed(openers) if floor <= _opener_start(m) < description),
        None,
    )
    if grant is None or not (boundary_ends or _is_easement_deed_grant(text, grant)):
        return True
    start = _opener_start(grant)
    return not _grant_takes(text, start, description, _after_boundary(boundary_ends, start))


# Whitespace and markdown before a document's first words.
_BEFORE_FIRST_WORDS = " \t\r\n#*_>"
_TOGETHER_WITH = re.compile(r"TOGETHER\s+WITH\b", re.IGNORECASE)


def _is_easement_deed_grant(text: str, opener: re.Match[str]) -> bool:
    """Return whether ``opener`` is the operative grant of an easement deed.

    An opener-word easement-deed signal (INV-1's exception): the document itself opens
    with a TOGETHER WITH grant naming a specific easement ("TOGETHER WITH an easement
    for access as follows: BEGINNING ..."), with no parcel wording before it. Its grant
    then takes the first description when its clause runs on into it (``_grant_takes``)
    and no parcel intro lies between. A grant of one easement introducing the first
    description in any other form (``_OBJECT_GRANT``, ``_lead_introduces``) makes an
    easement deed too (r58). A deed title alone ("GRANT OF EASEMENT") is not recognised.
    """
    start = _opener_start(opener)
    return (
        start == len(text) - len(text.lstrip(_BEFORE_FIRST_WORDS))
        and _TOGETHER_WITH.match(text, start) is not None
        and _names_specific_easement(text, start, opener.end())
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


def _easement_spans(index: _TextIndex) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Return the spans of appurtenant easement descriptions stated by their own courses.

    An opener inside an open description ("BEGINNING at a pin, subject to a right of
    way, thence ...", "Commencing at a corner, also being ...") qualifies that
    description; it never starts an easement. An opener without a THENCE course
    (``_THENCE_COURSE``, numbered or not) before the next clause stop is a clause
    (metadata), not a description. The description after the opener (its opening, or
    its first course) is the easement's only when the grant takes it (``_grant_takes``,
    the rule every path shares), and only after a closed boundary (INV-1, INV-2): an
    opener before the first boundary is that parcel's preamble, unless its own clause
    introduces the description (``_introduced_role``: "TOGETHER WITH a perpetual
    easement over the following described strip: BEGINNING ..."), whose span then ends
    with that description's closing sentence. A grant named without an opener word
    (``_OBJECT_GRANT``: "An easement for ingress and egress described as follows:")
    takes a description only that way, wherever it stands. A span ends with the
    sentence of its last course when only wording without a course follows it before
    the stop (wording already set aside, a recital); otherwise at the stop, so no course
    is ever left behind on a boundary.

    Returns the spans and, separately, the easement clauses whose courses describe no
    traverse (``_describes_traverse``: "SUBJECT TO a sewer easement which begins at the
    northeast corner and runs thence South 10 feet."): such a clause is no description,
    so it is noted (``easement_clause_spans``), never an easement tract or a course.
    """
    text = index.text
    spans: list[tuple[int, int]] = []
    clauses: list[tuple[int, int]] = []
    # Openers, and grants named without an opener word (r58: ``_OBJECT_GRANT``), which
    # take a description only when their own clause introduces it.
    leads = sorted(
        [*((s, e, True) for s, e in zip(index.openers, index.opener_ends, strict=True))]
        + [(s, e, False) for s, e in index.object_grants]
    )
    for start, opener_end, is_opener in leads:
        if spans and start < spans[-1][1]:
            continue
        # An earlier easement description closes where it ends.
        if _last_closure_end(index, start, spans) is None:
            continue
        stop = index.next_stop(start)
        introduced = not (is_opener and index.may_grant(start))
        if introduced:
            opening = _opening_after(text, opener_end)
            if opening is None:
                continue
            found = index.introduced(opening, start)
            if found is None or found[0] != start:
                continue
            stop = _closing_sentence_end(index, opening)
            # A tract heading directly before the grant labels the easement ("TRACT 2: A
            # non-exclusive easement ... described as follows:"), as on its own segment.
            start = _heading_before(index, start)
        courses = list(_THENCE_COURSE.finditer(text, start, stop))
        if not courses:
            continue
        first = courses[0].start()
        description = _DESCRIPTION_OPENER.search(text, opener_end, first)
        if not introduced and not _grant_takes(
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
        if not _describes_traverse(text, opener_end, end):
            clauses.append((start, start + len(text[start:end].rstrip(" \t\n,;:."))))
            continue
        spans.append((start, start + len(text[start:end].rstrip())))
    return spans, clauses


# What may separate a tract heading's ID (and parenthetical) from the wording it labels.
_HEADING_GAP = re.compile(r"[\s:.\-–—]*")


def _heading_before(index: _TextIndex, position: int) -> int:
    """Return where a tract heading directly before ``position`` starts, else ``position``.

    Directly before: only its terminator (a colon, period, dash) and whitespace lie
    between the heading's ID (and parenthetical) and ``position`` ("TRACT 2: A ...").
    """
    i = bisect_left(index.headings, position)
    if not i:
        return position
    heading = index.headings[i - 1]
    marker = _MARKER.match(index.text, heading)
    if marker is None:
        return position
    skipped = _TRANSPARENT_AFTER_ID.match(index.text, marker.end())
    end = marker.end() if skipped is None else skipped.end()
    gap = _HEADING_GAP.match(index.text, end, position)
    return heading if gap is not None and gap.end() == position else position


def _closing_sentence_end(index: _TextIndex, opening: int) -> int:
    """Return where the sentence closing the description opened at ``opening`` ends.

    After its period when the closing course's sentence ends with one; the next clause
    stop when the description never closes.
    """
    text = index.text
    j = bisect_right(index.closure_ends, opening)
    if j == len(index.closure_ends):
        return index.next_stop(opening)
    closed = index.closure_ends[j]
    end = _sentence_limit(text, closed, len(text))
    return end + 1 if text[end : end + 1] == "." else end


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
    * The parcel's own intro between the grant and the description, or opening it
      ("TOGETHER WITH an easement 10 feet wide ALL THAT CERTAIN lot, ... described as
      follows: BEGINNING ...", "... The land referred to herein is described as
      follows:", ``_parcel_intro_after``), gives the description to the parcel (r58),
      wherever the grant stands.
    """
    intro = _parcel_intro_after(
        text, opener, min(len(text), description + _LABEL_LOOKAHEAD), own_sentence=True
    )
    if intro is not None and intro <= description:
        return False
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

    An easement clause after a closed description whose THENCE courses describe no
    traverse ("SUBJECT TO a sewer easement which begins at the northeast corner of
    said lot and runs thence South 10 feet.": one course, not closing) is returned too
    (``_easement_spans``): it is never an easement tract, nor a course of the boundary.
    """
    index = _index(text)
    spans: list[tuple[int, int]] = list(index.easement_clauses)
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
    return sorted(spans)


def _course_count(text: str, start: int, end: int) -> int:
    """Return how many courses ``text[start:end]`` states.

    In each ';'-separated clause every THENCE opens a course, and a complete course
    (bearing and distance) before its first THENCE is one more ("BEGINNING ... S 61° W
    50 feet; thence ...", "Beginning ...; S 80-00-00 E 10 feet; S 10-00-00 W 10 feet;
    ..."). An enumerated course list is read as the course parser reads it
    (``analyze_course_lists``): its enumerators are its courses, in place of the THENCE
    words within it ("thence the following four courses: (1) ..., (2) ..., (3) ... and
    (4) ..." states four, as does "thence (1) ...; thence (2) ...; ...").

    Callers compare the count with at most ``_TIE_BOUNDARY_COURSES``; once THENCE
    courses reach it the lists are not read again (the course parser reads each
    tract's lists once).
    """
    courses = 0
    clause_starts = [start, *(i + 1 for i in range(start, end) if text[i] == ";")]
    for clause_start, clause_end in zip(clause_starts, [*clause_starts[1:], end], strict=True):
        first = _THENCE_WORD.search(text, clause_start, clause_end)
        courses += len(_THENCE_WORD.findall(text, clause_start, clause_end)) + bool(
            _COMPLETE_COURSE.search(text, clause_start, first.start() if first else clause_end)
        )
    if courses >= _TIE_BOUNDARY_COURSES:
        return courses
    segment = text[start:end]
    for course_list in analyze_course_lists(segment).lists:
        last = course_list.enumerators[-1].end()
        courses += len(course_list.enumerators) - len(
            _THENCE_WORD.findall(segment, course_list.start, last)
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
        if CONDITIONAL_EXCEPT_AFTER.match(text, lead.end()):
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
    segments: list[BasedSegment], indexes: dict[str, _TextIndex] | None = None
) -> list[BasedSegment]:
    """Split easement descriptions out of each segment into EASEMENT tracts.

    Generated easement labels are numbered in order of appearance. A split-out
    easement's role is inferred (from its grant wording); the remainder keeps the
    segment's own role basis. ``indexes`` are clause structures already built for some
    segment texts; the others are built here.
    """
    known = indexes or {}
    result: list[BasedSegment] = []
    for segment, label, tract_type, basis in segments:
        index = known.get(segment)
        spans = (
            []
            if tract_type == TractType.EASEMENT
            else list((_index(segment) if index is None else index).easements)
        )
        if not spans:
            result.append((segment, label, tract_type, basis))
            continue
        kept: list[str] = []
        cursor = 0
        for start, end in spans:
            kept.append(segment[cursor:start])
            cursor = end
        kept.append(segment[cursor:])
        remainder = " ".join(part.strip() for part in kept if part.strip())
        if remainder:
            result.append((remainder, label, tract_type, basis))
        result.extend(
            (segment[start:end].strip(), EASEMENT_LABEL, TractType.EASEMENT, "inferred")
            for start, end in spans
        )
    count = 0
    numbered: list[BasedSegment] = []
    for segment, label, tract_type, basis in result:
        if tract_type == TractType.EASEMENT and re.fullmatch(
            re.escape(EASEMENT_LABEL) + r"(?: \d+)?", label
        ):
            count += 1
            label = f"{EASEMENT_LABEL} {count}"
        numbered.append((segment, label, tract_type, basis))
    return numbered


def _easement_lead(text: str, position: int, floor: int = 0) -> int | None:
    """Return where the easement opener of the tract starting at ``position`` starts.

    The opener is the last one after ``floor`` (the end of the previous tract) and its
    grant takes the description at ``position`` (``_grant_takes``, the rule the easement
    spans share): its clause runs on to it, however long its grantee wording
    ("RESERVING unto the grantor, its successors and assigns, a perpetual non-exclusive
    easement ... as follows: BEGINNING ..."), or it follows a closed boundary with
    nothing but punctuation or structure after the grant's sentence end. An opener
    before the first closed boundary types nothing (INV-1) unless its own clause
    introduces the description (``_introduced_role``).
    """
    index = _index(text)
    # A description the easement spans claim (one introduced as the easement's
    # across its grant sentence's end) is the easement's.
    for span_start, span_end in index.easements:
        if floor <= span_start < position < span_end:
            return span_start
    i = bisect_left(index.openers, position)
    if i and index.openers[i - 1] >= floor:
        opener = index.openers[i - 1]
        if index.may_grant(opener) and _grant_takes(
            text, opener, position, index.after_boundary(opener), index.headings
        ):
            return opener
    found = index.introduced(position, floor)
    return found[0] if found is not None and found[1] == TractType.EASEMENT else None


def _except_may_type(index: _TextIndex, position: int) -> bool:
    """Return whether EXCEPT wording at ``position`` may type the description after it.

    After a closed boundary (INV-2), after a closed BEGINNING description that is no tie
    (``_described_ends``: one whose courses an OCR error or a single course keeps from
    counting as a boundary), or inside a description still open (a THENCE course
    (``_THENCE_COURSE``) precedes it with no point of beginning reached since:
    "THENCE ...; THENCE ... EXCEPT THENCE ..."; neither an OCR table tag read as THENCE
    nor a recording reference "beginning at Page 849" opens one). There the wording is
    no preamble, and
    reading the description it introduces as the boundary's would join the exception's
    courses to the boundary. Before the first description, or after only a tie or a
    recital, it is a preamble recital (INV-1).
    """
    if index.after_boundary(position) or _after_boundary(index.described_ends, position):
        return True
    i = bisect_right(index.description_starts, position)
    if not i:
        return False
    j = bisect_right(index.closure_ends, position)
    return not (j and index.closure_ends[j - 1] > index.description_starts[i - 1])


def _described_after(index: _TextIndex, position: int) -> bool:
    """Return whether a separate description follows the one at ``position``.

    The description at ``position`` ends at the first point-of-beginning closure after
    it; another description is a traverse opened by BEGINNING or COMMENCING after that
    closure (``_traverses_after``), never a tie line or one-course clause.
    """
    j = bisect_right(index.closure_ends, position)
    return j < len(index.closure_ends) and index.follows[j]


def _excepts_from_later_description(index: _TextIndex, lead: int, end: int, position: int) -> bool:
    """Return whether the EXCEPT lead at ``lead`` excepts land from a later description.

    Its wording (up to ``end``) takes the exception "from the lands hereinafter
    described" and a separate description does follow the one at ``position``. With
    none after it, the lands described later are that description itself: the lead is
    its preamble ("ALL THAT tract, EXCEPTING AND RESERVING from the premises
    hereinafter described all oil, gas and minerals, BEGINNING ...") and types nothing
    (INV-1).
    """
    return _FROM_LANDS_DESCRIBED_LATER.search(
        index.text, lead, end
    ) is not None and _described_after(index, position)


def _except_lead(text: str, position: int, floor: int = 0) -> int | None:
    """Return where the EXCEPT lead introducing the tract starting at ``position`` starts.

    The lead follows ``floor`` (the end of the previous tract), may type a description
    there (``_except_may_type``: INV-1, INV-2), and its wording runs on to ``position``
    with no sentence end and no course ("EXCEPTING THEREFROM the following described
    parcel: PARCEL A: ...", "LESS AND EXCEPT that part described as follows: Tract 2:
    ..."). Elsewhere only a lead taking its exception from lands described later
    (``_FROM_LANDS_DESCRIBED_LATER``) introduces an exception, and only when a
    separate description follows (``_described_after``), or a lead whose own clause
    introduces the description (``_introduced_role``: "EXCEPTING THEREFROM the
    following described parcel:", "LESS PARCEL B:"), before or after any boundary.
    """
    index = _index(text)
    found = index.introduced(position, floor)
    if found is not None and found[1] == TractType.EXCEPTION:
        return found[0]
    leads = [
        lead
        for lead in index.except_leads
        if floor <= lead.start() < position and not _is_lot_qualifier_except(text, lead)
    ]
    if not leads:
        return None
    lead = leads[-1]
    if (
        _sentence_break(text, lead.end(), position) is None
        and _TRAVERSE_WORDING.search(text, lead.end(), position) is None
        and (
            _except_may_type(index, lead.start())
            or _excepts_from_later_description(index, lead.start(), position, position)
        )
    ):
        return lead.start()
    return None


def _tract_type_at(text: str, position: int, floor: int = 0) -> TractType:
    """Type of the tract whose wording starts at ``position`` in ``text``.

    An easement opener (``_easement_lead``) makes it an easement and an EXCEPT lead
    introducing it (``_except_lead``) an exception; otherwise EXCEPT wording that may
    type it (``_except_may_type``) and ALSO wording in the 80 characters before
    ``position`` type it.
    """
    if _easement_lead(text, position, floor) is not None:
        return TractType.EASEMENT
    if _except_lead(text, position, floor) is not None:
        return TractType.EXCEPTION
    window = max(0, position - 80)
    preceding = text[window:position]
    index = _index(text)
    if any(
        _except_may_type(index, window + match.start())
        for match in _PRECEDING_EXCEPT.finditer(preceding)
    ):
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
    """Find explicit TRACT, PARCEL or SCHEDULE markers.

    Returns: list of (position, label, marker_kind)
    """
    matches = sorted(
        [*_MARKER.finditer(text), *_SCHEDULE_MARKER.finditer(text)], key=lambda m: m.start()
    )
    return [
        (
            m.start(),
            f"{m['kind'].capitalize()} "
            + (m["id"].upper() if m["kind"].lower() == "schedule" else m["id"]),
            m["kind"].lower(),
        )
        for m in matches
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
    return [segment[:3] for segment in _split_on_markers(text, markers)]


def _split_on_markers(
    text: str, markers: list[tuple[int, str, str]]
) -> list[tuple[str, str, TractType, int]]:
    """``split_on_markers`` with the position of each segment's marker (0 for text before
    the first marker)."""
    result: list[tuple[str, str, TractType, int]] = []
    recitals: list[tuple[str, str, TractType, int]] = []
    # A tract introduced by an EXCEPT lead ("EXCEPTING THEREFROM the following
    # described parcel: PARCEL A: ...") or by the grant of one easement whose own clause
    # introduces it ("subject to the following easement: PARCEL B: ...", r58) starts at
    # its lead: the lead types it and is never left on the tract before it.
    index = _index(text)
    starts: list[int] = []
    for i, (pos, _, _) in enumerate(markers):
        floor = markers[i - 1][0] if i else 0
        lead = _except_lead(text, pos, floor)
        if lead is None:
            found = index.introduced(pos, floor)
            lead = found[0] if found is not None and found[1] == TractType.EASEMENT else None
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
            result.append((pre_text, UNLABELLED_TRACT_LABEL, TractType.MAIN, 0))

    for i, (pos, label, _kind) in enumerate(markers):
        end = starts[i + 1] if i + 1 < len(markers) else len(text)
        segment = text[starts[i] : end].strip()

        # Check preceding text for easement/EXCEPT/ALSO wording to assign the TractType
        tract_type = _tract_type_at(text, pos, markers[i - 1][0] if i else 0)
        if is_boundary_tract(tract_type):
            # A lead in the heading's own text introducing its description ("TRACT 2: A
            # non-exclusive easement ... described as follows:") types it (r58).
            opening = _opening_after(text, pos, end)
            found = None if opening is None else index.introduced(opening, pos)
            if found is not None:
                tract_type = found[1]

        # A title recital is never a tract of its own; it is resolved after all
        # descriptions are known (a same-label description may follow it).
        if _is_title_recital(segment):
            recitals.append((segment, label, tract_type, pos))
            continue

        # A repeated label whose segment has no calls is prose about an earlier
        # tract (area, exception recital), not a new tract: fold it back.
        if not (_BEGINNING_PATTERN.search(segment) or _THENCE_COURSE.search(segment)):
            earlier = next(
                (j for j, r in enumerate(result) if _label_key(r[1]) == _label_key(label)), None
            )
            if earlier is not None:
                prev_text, prev_label, prev_type, prev_pos = result[earlier]
                result[earlier] = (
                    f"{prev_text} {segment}".strip(),
                    prev_label,
                    prev_type,
                    prev_pos,
                )
                continue

        result.append((segment, label, tract_type, pos))

    described = bool(result)
    for segment, label, tract_type, pos in recitals:
        same = next(
            (j for j, r in enumerate(result) if _label_key(r[1]) == _label_key(label)), None
        )
        if same is not None:
            prev_text, prev_label, prev_type, prev_pos = result[same]
            result[same] = (f"{prev_text} {segment}".strip(), prev_label, prev_type, prev_pos)
        elif described:
            # No described tract carries this label (e.g. its heading was OCR-garbled):
            # the recital has no calls, so it is dropped rather than made a tract.
            logger.warning(
                "Dropping title recital whose label matches no described tract",
                label=label,
                preview=segment[:120],
            )
        else:
            result.append((segment, label, tract_type, pos))
    return result


# A point of beginning reached ("to the point of beginning at ..."), not an opening.
_REACHED_BEFORE = re.compile(
    r"\b(?:to|being)\s+(?:(?:a|the|said|aforesaid|original|true|initial)\s+)*$", re.IGNORECASE
)


def _beginning_starts(text: str) -> list[re.Match[str]]:
    """Keep POB openings; exclude references reached 'to' or 'being' the POB."""
    return [
        match
        for match in _BEGINNING_PATTERN.finditer(text)
        if not _REACHED_BEFORE.search(text[: match.start()])
    ]


_THENCE_WORD = re.compile(r"\bTHENCE\b", re.IGNORECASE)
# A point of beginning reached by a tie and followed by more courses ("... to a point
# and place of beginning, thence; (1) ...") is not the description's closure.
_POB_CONTINUES = re.compile(r"\s*[,;]?\s*thence\b", re.IGNORECASE)


# A description opens at its commencement or point of beginning.
_DESCRIPTION_OPENING = re.compile(r"\b(?:COMMENCING|BEGINNING)\s+at\b", re.IGNORECASE)
_CLAUSE_KEYWORD = re.compile(
    r"\b(?:(?:LESS\s+AND\s+)?EXCEPT(?:ING)?|EXCLUDING|ALSO|INCLUDING|EASEMENT)\b", re.IGNORECASE
)


def split_complete_descriptions(text: str) -> list[str]:
    """Split text holding complete descriptions in sequence.

    "...to the point of beginning. Combined Legal Description: ... Commencing at ..." opens
    another description once the previous one has closed at its point of beginning (a point
    of beginning followed by THENCE is a tie, not a closure). An excepted, added or easement
    parcel ("..., EXCEPT ... beginning at ...") stays with its description.
    """
    parts: list[str] = []
    start = 0
    # The first description runs from the text's start (it may open with assessor wording,
    # "BEG N89DEG ..."); every later one opens with BEGINNING/COMMENCING at.
    anchor = 0
    while first_thence := _THENCE_WORD.search(text, anchor):
        close = next(
            (
                mention
                for mention in _POB_CLOSE_PATTERN.finditer(text, first_thence.end())
                if not _POB_CONTINUES.match(text, mention.end())
            ),
            None,
        )
        if close is None:
            break
        following = _DESCRIPTION_OPENING.search(text, close.end())
        # A later opening with no courses after it ("... Beginning at a point in the line
        # of Lot 10, said point being ...") is a recital, not another description.
        if following is None or not _THENCE_WORD.search(text, following.end()):
            break
        between = text[close.end() : following.start()]
        if _THENCE_WORD.search(between):
            break
        # Wording taking, granting or reciting land between them ("SUBJECT to the right of
        # way over the following:") ties the next description to this one.
        if not (_CLAUSE_KEYWORD.search(between) or _ROLE_WORD.search(between)):
            parts.append(text[start : close.end()])
            start = close.end()
        anchor = following.end()
    parts.append(text[start:])
    return [part.strip() for part in parts if part.strip()]


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
    return [segment[:3] for segment in split_into_tracts_with_basis(text)]


def split_into_tracts_with_basis(text: str, unblanked: str | None = None) -> list[BasedSegment]:
    """``split_into_tracts`` with each segment's role basis.

    "heading" when an explicit TRACT/PARCEL heading (``find_tract_markers``) starts a
    MAIN or ADDITION segment and the wording around it is allow-listed
    (``_heading_basis``); every other role is "inferred" from wording or position. (A
    deed's sole MAIN description is "single" when ``sole_description_basis`` allows it,
    decided by ``extract_calls`` once segments without calls are dropped.)
    ``unblanked`` is ``text`` before wording was set aside (blanked to spaces, offsets
    kept): the wording around a heading is read there.

    Returns: list of (tract_text, label, tract_type, role_basis)
    """
    # The text's clause structure is built once and passed to every step (r58).
    index = _index(text)
    source = text if unblanked is None or len(unblanked) != len(text) else unblanked
    return _separate_easements(_split_tract_segments(index, source), {text: index})


# --- r59: the certain role bases are allow-listed ---------------------------------------
#
# Role wording: a noun naming land as an easement or a right in it ("easement", "right of
# way", "right of ingress", "the right to construct", "ingress and egress"), or a verb
# reciting, taking or reserving ("subject to", "together with", "except", "exclude",
# "reserve", "save", "less", "deduct"). Plural "easements" and "rights of way" name no
# specific easement (a generic recital); "more or less", "or less" and "less than" take
# nothing. "License" and "the right to convey" are left out: surveyors' license numbers
# and the grantor's covenants fill deed forms.
_ROLE_NOUN = (
    r"easement(?!s)|right[\s-]+of[\s-]+way|(?:rights?|privileges?)\s+(?:of\s+(?:ingress|egress"
    r"|access|passage|use)|to\s+(?:use|construct|reconstruct|install|lay|maintain|operate"
    r"|repair|replace|inspect|enter|pass|cross|travel|access|drain|park|erect|place|excavate"
    r"|remove)\b)"
    r"|ingress|egress"
)
_RECITAL_VERB = (
    r"(?:under\s+and\s+)?subject\s+to|together\s+with|reserv(?:e|es|ed|ing|ations?)"
    r"|except(?:s|ed|ing|ions?)?|exclud(?:e|es|ed|ing)|exclusions?|sav(?:e|ing)"
    r"|(?<!or\s)less(?!\s+than)|deduct(?:s|ed|ing|ions?)?"
)
_ROLE_WORD = re.compile(rf"\b(?:(?P<verb>{_RECITAL_VERB})|(?P<noun>{_ROLE_NOUN}))\b", re.IGNORECASE)
# With no role noun these recite encumbrances or appurtenances ("SUBJECT to easements of
# record", "TOGETHER WITH all improvements"), never land; nor with one recorded elsewhere
# ("SUBJECT to an easement of record").
_GENERIC_VERB = re.compile(r"(?:under\s+and\s+)?subject\s+to|together\s+with", re.IGNORECASE)
# A role noun locating land rather than naming its role ("a portion of the former right
# of way", "lying within the right of way of Main Street", "along the easement line").
_LOCATED_NOUN = re.compile(
    r"\b(?:(?:portions?|parts?|lines?|sides?|corners?|beds?|limits?|edges?|center(?:line)?)\s+of"
    r"|in|into|within|on|upon|along|over|across|through|under|adjoining|adjacent|abutting"
    r"|from|by|at|between|near|beside)\s+(?:(?:the|a|an|said|such|that|this|its|their)\s+)?"
    r"(?:[\w'-]+\s+){0,3}$",
    re.IGNORECASE,
)
# Wording pointing on to a description ("the following", "hereinafter described", "as
# follows", "described below", "the land described as Parcel 2").
_FORWARD_REFERENCE = re.compile(
    r"\b(?:following|herein\s*after|below|as\s+follows|described\s+as)\b", re.IGNORECASE
)
# The parcel's own intro, besides ``_PARCEL_LAND_LEAD`` and ``_NAMED_PARCEL_DESCRIBED``:
# "Being Lot 5", "Being known as", "BEING the same premises", a lot reference ("Lot 5,
# Block 3"), "The land referred to herein", "The premises hereby conveyed", "The property
# consists of".
_OWN_PARCEL_LEAD = re.compile(
    r"\bBEING\s+(?:all\s+(?:of\s+)?|(?:a\s+)?part\s+of\s+)?(?:(?:tax\s+)?lots?\b|known\s+as\b"
    r"|the\s+same\s+(?:lands?|premises|property|tracts?|parcels?|lots?)\b"
    r"|(?:that|those)\s+certain\b|all\s+(?:that|those)\b)"
    r"|(?<![\w-])(?:tax\s+)?lots?\s+(?:no\.?\s*)?\d"
    r"|\bthe\s+(?:lands?|premises|property|real\s+(?:property|estate))\s+(?:referred\s+to"
    r"|herein|hereby|hereinafter|conveyed|situated?|located|lying|consists?)\b",
    re.IGNORECASE,
)
# Wording that introduces a parcel's description without naming land ("Situate in ...,
# bounded and described as follows:").
_INTRO_PHRASE = re.compile(
    r"\b(?:described|as\s+follows|bounded|situated?|lying|located)\b", re.IGNORECASE
)
# A plain heading label after the marker's ID: at most ':', '.' or a dash (markdown
# emphasis allowed), never a parenthetical or words of its own.
_PLAIN_LABEL_END = re.compile(r"[ \t*_]*(?:[:.\-–—](?![\w-])[ \t*_]*)?")
_STRIP_LABEL = " \t\n*_#>.:;,-–—|"


def _sentence_spans(text: str, start: int, end: int) -> list[tuple[int, int, bool]]:
    """Return the sentences of ``text[start:end]`` as (start, end, ended), in one pass.

    The breaks ``_sentence_break`` reads: a sentence-ending period, document structure, a
    line break before a description opening its own line (one at ``end`` included) when
    the line before does not run on. ``ended`` is False for a last sentence that runs on
    into ``end``. Blank sentences are left out.
    """
    breaks: dict[int, int] = {}
    for structure in STRUCTURE_BREAK.finditer(text, start, end):
        breaks.setdefault(structure.start(), structure.end())
    for line in _LINE_DESCRIPTION.finditer(text, start, min(len(text), end + _OPENING_LOOKAHEAD)):
        if line.start() < end and not _LINE_CONTINUES.search(
            text, max(start, line.start() - 200), line.start()
        ):
            breaks.setdefault(line.start(), line.start() + 1)
    period = text.find(".", start, end)
    while period >= 0:
        if ends_sentence(text, period) and not _ENUMERATOR_BEFORE_PERIOD.search(
            text, max(0, period - 16), period
        ):
            breaks.setdefault(period + 1, period + 1)
        period = text.find(".", period + 1, end)
    spans: list[tuple[int, int, bool]] = []
    cursor = start
    for stop in sorted(breaks):
        if stop >= cursor:
            spans.append((cursor, stop, True))
            cursor = max(stop, breaks[stop])
    spans.append((cursor, end, False))
    return [span for span in spans if text[span[0] : span[1]].strip(_STRIP_LABEL)]


def _rights_recital_spans(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Return the rights recitals in ``text[start:end]``: a recital verb and its rights.

    The verb's object is rights (``_RIGHTS_RECITAL``: mineral, oil and gas rights, plural
    easements or rights of way, rights of the public, any portion within a street) naming
    no land after it ("EXCEPTING AND RESERVING all oil, gas and mineral rights", "EXCEPT
    the rights of the public in Main Street", "RESERVING unto the Grantor the coal and
    mining rights"). A second lead after the first ("EXCEPTING AND RESERVING") is part
    of it.
    """
    spans: list[tuple[int, int]] = []
    for word in _ROLE_WORD.finditer(text, start, end):
        if word["verb"] is None or (spans and word.start() < spans[-1][1]):
            continue
        rights = _RIGHTS_RECITAL.match(text, _after_joined_lead(text, word.end(), end), end)
        if rights is not None and not _LAND_NOUN.search(text, rights.end(), end):
            spans.append((word.start(), rights.end()))
    return spans


def _role_words(text: str, start: int, end: int) -> list[re.Match[str]]:
    """Return the role words of ``text[start:end]`` (``_ROLE_WORD``) that name a role.

    Never one inside a rights recital (``_rights_recital_spans``), nor a role noun locating
    land ("a portion of the former right of way", ``_LOCATED_NOUN``). SUBJECT TO and
    TOGETHER WITH are kept (``_only_generic`` reads them).
    """
    covered = _rights_recital_spans(text, start, end)
    return [
        word
        for word in _ROLE_WORD.finditer(text, start, end)
        if not any(s <= word.start() < e for s, e in covered)
        and not (
            word["noun"] is not None
            and _LOCATED_NOUN.search(text, max(start, word.start() - 60), word.start())
        )
    ]


def _only_generic(words: Sequence[re.Match[str]]) -> bool:
    """Return whether ``words`` are only SUBJECT TO / TOGETHER WITH (or none)."""
    return all(word["verb"] is not None and _GENERIC_VERB.fullmatch(word["verb"]) for word in words)


def _sentence_role(text: str, start: int, end: int, *, runs_on: bool = False) -> str:
    """Return how the sentence ``text[start:end]`` bears on a description's role.

    * "plain": no role wording (``_role_words``: rights recitals and land located by a
      right of way are none), only SUBJECT TO / TOGETHER WITH with no role noun (generic
      recitals: "SUBJECT to easements of record", "TOGETHER WITH all improvements
      thereon") or with one of record ("SUBJECT to an easement of record"), or a taking
      verb with no role noun that points nowhere ("EXCEPT the South 10 feet thereof",
      "No. of Pages (excluding Summary Sheet)");
    * "recital": a recital naming an easement or right whose first role word is its verb
      ("TOGETHER with a non-exclusive easement over the common driveway", "SUBJECT to a
      right of way along the Westerly 10 feet thereof"): it encumbers or benefits the
      parcel it follows and names no land described;
    * "role": anything else with role wording: a statement whose first role word is a
      noun ("Parcel B is a non-exclusive easement", "The foregoing describes an access
      easement", "SANITARY SEWER EASEMENT"), wording pointing on to a description ("the
      following described land", "described as Parcel 2") or naming a tract, or a
      sentence running on into what follows it (``runs_on``).
    """
    words = _role_words(text, start, end)
    if _only_generic(words):
        return "plain"
    nouns = [word for word in words if word["noun"] is not None]
    points = runs_on or bool(
        _FORWARD_REFERENCE.search(text, start, end) or _MARKER.search(text, start, end)
    )
    if not nouns:
        return "role" if points else "plain"
    if (
        not points
        and words[0]["verb"] is not None
        and _GENERIC_VERB.fullmatch(words[0]["verb"])
        and _OF_RECORD.search(text, start, end)
    ):
        return "plain"
    if points:
        return "role"
    return "recital" if words[0]["verb"] is not None else "role"


def _own_parcel_lead(text: str, start: int, end: int) -> int | None:
    """Return where the parcel's own intro starts in ``text[start:end]``, or None.

    "ALL THAT CERTAIN lot" (``_PARCEL_LAND_LEAD``, no role word among its modifiers,
    never land a grant runs over), "said lot being described" (``_NAMED_PARCEL_DESCRIBED``)
    or ``_OWN_PARCEL_LEAD`` ("Being Lot 5", "Lot 5, Block 3", "The land referred to
    herein"), never after a locating word ("over Lot 5").
    """
    found = [
        match.start()
        for pattern in (_PARCEL_LAND_LEAD, _NAMED_PARCEL_DESCRIBED, _OWN_PARCEL_LEAD)
        for match in pattern.finditer(text, start, end)
        if not _LOCATING_BEFORE.search(text, max(start, match.start() - 20), match.start())
        and not (pattern is _PARCEL_LAND_LEAD and _ROLE_WORD.search(match.group()))
    ]
    return min(found, default=None)


def _introduces_parcel(text: str, start: int, end: int) -> tuple[bool, bool]:
    """Return whether ``text[start:end]`` introduces the parcel, and with its full intro.

    Each sentence is read up to the parcel's own intro in it (``_own_parcel_lead``:
    recitals inside the parcel's own sentence are the parcel's); the last one, running
    on into the description, may not name a role on its own (it would introduce the
    described land as that role). No sentence may state a role (``_sentence_role``);
    a recital about other land is harmless only with the parcel's own intro (the full
    intro: "TOGETHER with a right of way over the driveway as shown on the plan. ALL
    THAT CERTAIN lot ..."). Plain sentences are always harmless.
    """
    sentences = _sentence_spans(text, start, end)
    roles: list[str] = []
    full = False
    for sentence_start, sentence_end, ended in sentences:
        lead = _own_parcel_lead(text, sentence_start, sentence_end)
        full = full or lead is not None
        roles.append(
            _sentence_role(
                text,
                sentence_start,
                sentence_end if lead is None else lead,
                runs_on=lead is None and not ended,
            )
        )
    ok = not any(role == "role" or (role == "recital" and not full) for role in roles)
    return ok, full


# Wording referring back to the land just described ("The foregoing", "the above
# described premises", "said strip", "Being ...").
_BACK_REFERENCE = re.compile(
    r"\b(?:foregoing|aforesaid|above(?:[\s-]+(?:described|mentioned))?"
    r"|herein(?:above|before)?[\s-]+described"
    r"|(?:said|this|the\s+(?:described|same))\s+(?:premises|lands?|lots?|parcels?|tracts?|strips?"
    r"|property|area|description))\b"
    r"|^[\s*_#>]*(?:it\s+)?being\b",
    re.IGNORECASE,
)


def _states_role_after(text: str, start: int) -> bool:
    """Return whether wording after a closed description states a described land's role.

    A sentence naming a tract with role wording ("Parcel B is a non-exclusive easement
    appurtenant to Parcel A", "EXCEPTING from Parcel 1 the land described as Parcel 2"),
    or a statement whose first role word is a noun about the land just described ("The
    foregoing describes a 20 foot wide access easement", "Being an easement for ingress
    and egress"). Recitals ("SUBJECT to a right of way ...", "TOGETHER with ...") and the
    deed's form text after the description (covenants, transfer-fee forms) state none.
    """
    for s, e, _ in _sentence_spans(text, start, len(text)):
        words = _role_words(text, s, e)
        if _only_generic(words):
            continue
        if _MARKER.search(text, s, e) is not None:
            return True
        first_noun = next((word for word in words if word["noun"] is not None), None)
        if (
            first_noun is not None
            and words[0] is first_noun
            and _BACK_REFERENCE.search(text[s : first_noun.start()])
        ):
            return True
    return False


def _closure_after(index: _TextIndex, position: int) -> int | None:
    """Return where the first description closing after ``position`` closes, or None."""
    j = bisect_right(index.closure_ends, position)
    return index.closure_ends[j] if j < len(index.closure_ends) else None


def sole_description_basis(text: str, basis: RoleBasis, unblanked: str | None = None) -> RoleBasis:
    """Return the role basis of a deed's only (MAIN) description: "single" or "inferred".

    ``basis`` is the description's basis from the tract split. Under a heading it is
    "single" only when the heading established it ("heading"); otherwise (the split
    infers every role) the deed's wording decides. It is "single" only when nothing that
    introduces, titles or follows the description names a role (``_introduces_parcel``,
    ``_states_role_after``): an easement deed ("SANITARY SEWER EASEMENT", "Grantor grants
    the perpetual right to construct a pipeline over the following described land:"),
    or a statement after it ("The foregoing describes an access easement"), leaves it
    "inferred", so it is never verified or exported (fail closed). Rights recitals,
    generic recitals, recitals inside the parcel's own intro sentence and recitals
    followed by the parcel's own intro keep it "single". ``unblanked`` is ``text``
    before wording was set aside (same offsets).
    """
    if basis == "inferred" and find_tract_markers(text):
        return "inferred"
    source = text if unblanked is None or len(unblanked) != len(text) else unblanked
    opening = _opening_after(text, 0)
    if opening is None:
        return "single"
    if not _introduces_parcel(source, 0, opening)[0]:
        return "inferred"
    closed = _closure_after(_index(text), opening)
    if closed is not None and _states_role_after(source, closed):
        return "inferred"
    return "single"


def _heading_basis(
    index: _TextIndex,
    label: str,
    tract_type: TractType,
    position: int,
    markers: Sequence[int],
    source: str,
) -> RoleBasis:
    """Role basis of a segment split on tract markers, its heading at ``position``.

    A heading proves a description exists, not its role. It is "heading" (r59: an
    allow-list) only for a MAIN or ADDITION tract when all of these hold; otherwise the
    role is "inferred" (fail closed), whatever typing made of the wording:

    1. No role lead in the heading's own text before its opening: an EXCEPT / LESS / SAVE
       / RESERVING lead (``index.except_leads``, ``index.taking``: "PARCEL TWO: ALL THAT
       tract, EXCEPTING AND RESERVING the oil and gas rights, ..."), or a grant of one
       specific easement or right of way (``index.grants``: "TRACT 2: A non-exclusive
       easement ..."). EXCLUDING / SAVING inside the parcel's own intro ("ALL THAT lot,
       excluding the street, described as follows:") is none.
    2. A plain label: the marker's identifier, then at most ':', '.' or a dash
       (``_PLAIN_LABEL_END``), followed by nothing or the parcel's own intro ("ALL THAT
       CERTAIN lot ...", "Being Lot 5", "Being known as ...", "The land referred to
       herein ...", or wording with no role word introducing it: "Situate in ..., bounded
       and described as follows:"). A parenthetical ("PARCEL B (Ingress and Egress):"),
       or a role named after the colon ("PARCEL B: ACCESS EASEMENT", "PARCEL B: The
       non-exclusive easement area described as follows:") is not plain.
    3. Between the previous description's closure and the heading, only plain sentences
       (``_sentence_role``: no role wording, rights or generic recitals), or recitals
       about the previous parcel naming no described land when the parcel's own intro
       follows the label ("TOGETHER with an easement over the common driveway as shown
       on the plan. PARCEL TWO: ALL THAT CERTAIN lot ..."). A lead running on into the
       heading ("EXCLUDING therefrom the following:", "ACCESS EASEMENT PARCEL B:") or a
       role statement is never harmless.
    4. After the last description, no role statement (``_states_role_after``: "Parcel
       B is a non-exclusive easement appurtenant to Parcel A").

    The previous description ends at its first closure after the previous heading
    (``markers``), or, unclosed, at the sentence holding this heading. Before the first
    heading there is no previous description: its window starts with the sentence
    running on into it (``_sentence_start``), never in a recording cover sheet or a
    warranty clause before it. The wording around the heading is read in ``source``
    (the text before wording was set aside: stated exceptions after a description
    count).
    """
    if label == UNLABELLED_TRACT_LABEL or not is_boundary_tract(tract_type):
        return "inferred"
    text = index.text
    k = bisect_left(markers, position)
    following = markers[k + 1] if k + 1 < len(markers) else len(text)
    opening = _opening_after(text, position, following)
    end = following if opening is None else opening
    leads = (
        *(lead.start() for lead in index.except_leads),
        *(
            start
            for start, lead_end in index.taking
            if not _EXCLUDING_LEAD.fullmatch(text, start, lead_end)
        ),
        *(start for start, _ in index.grants),
    )
    if any(position <= start < end for start in leads):
        return "inferred"
    marker = _MARKER.match(text, position)
    if marker is None:
        return "inferred"
    skipped = _PLAIN_LABEL_END.match(source, marker.end(), end)
    label_end = marker.end() if skipped is None else skipped.end()
    rest = source[label_end:end].strip(_STRIP_LABEL)
    full = _own_parcel_lead(source, label_end, end)
    if rest.startswith("("):
        return "inferred"
    # Whatever names a role before the parcel's own intro (or with none) is a label.
    if rest and not (
        _only_generic(_role_words(source, label_end, end if full is None else full))
        and (full is not None or _INTRO_PHRASE.search(source, label_end, end))
    ):
        return "inferred"
    floor = _sentence_start(text, position)
    if k:
        closed = _closure_after(index, markers[k - 1])
        floor = closed if closed is not None and closed <= position else max(floor, markers[k - 1])
    for start, stop, ended in _sentence_spans(source, floor, position):
        role = _sentence_role(source, start, stop, runs_on=not ended)
        if role == "role" or (role == "recital" and full is None):
            return "inferred"
    if k == len(markers) - 1:
        closed = _closure_after(index, position)
        if closed is not None and _states_role_after(source, closed):
            return "inferred"
    return "heading"


# How far past a description's opening a parcel intro is read (``_grant_takes``).
_LABEL_LOOKAHEAD = 40


def _inferred(segments: list[tuple[str, str, TractType]]) -> list[BasedSegment]:
    return [(text, label, tract_type, "inferred") for text, label, tract_type in segments]


def _split_tract_segments(index: _TextIndex, source: str | None = None) -> list[BasedSegment]:
    """Split ``index.text`` by markers, BEGINNING blocks or EXCEPT/ALSO clauses.

    ``source`` is the text before wording was set aside (``_heading_basis``).
    """
    text = index.text
    # 1. Try explicit TRACT/PARCEL markers
    markers = find_tract_markers(text)
    if markers:
        positions = [position for position, _, _ in markers]
        segments: list[BasedSegment] = []
        for segment, label, tract_type, position in _split_on_markers(text, markers):
            basis = _heading_basis(
                index, label, tract_type, position, positions, text if source is None else source
            )
            # A further description under the same heading has no heading of its own.
            for number, description in enumerate(split_complete_descriptions(segment), start=1):
                if number == 1:
                    segments.append((description, label, tract_type, basis))
                else:
                    segments.append(
                        (description, f"{label}, description {number}", tract_type, "inferred")
                    )
        return segments

    # 2. Try multiple BEGINNING blocks
    blocks = find_beginning_blocks(text)
    if len(blocks) > 1:
        return _inferred(label_beginning_blocks(blocks, text))

    # 3. Complete descriptions in sequence that are not both BEGINNING blocks ("BEG
    # N89DEG ... to the point of beginning ... And 10M6B1A1 THAT PART ... DESCRIBED AS
    # BEGINNING AT ...").
    descriptions = split_complete_descriptions(text)
    if len(descriptions) > 1:
        return [
            (segment, f"Tract {number}" if label == "Tract 1" else label, tract_type, "inferred")
            for number, description in enumerate(descriptions, start=1)
            for segment, label, tract_type, _basis in _split_tract_segments(
                _index(description), None
            )
        ]

    # Easements are separated before clause splitting, which would cut an "ALSO an
    # easement ..." opener off its description.
    separated = _separate_easements([(text, "Tract 1", TractType.MAIN, "inferred")], {text: index})
    if len(separated) > 1:
        easements = [segment for segment in separated if segment[2] == TractType.EASEMENT]
        parcel = [segment[0] for segment in separated if segment[2] != TractType.EASEMENT]
        # An easement deed's grant words or title left with no course and naming no land
        # ("GRANTOR hereby grants and conveys unto GRANTEE") describe no tract. A parcel
        # named by reference only stays a tract (strict extraction refuses it).
        if not parcel or not (_COURSE_TEXT.search(parcel[0]) or _LAND_NOUN.search(parcel[0])):
            return easements
        return _inferred(_split_clauses(parcel[0])) + easements
    return _inferred(_split_clauses(text, index))


# Any course wording: a THENCE course, a complete course or a description opening.
_COURSE_TEXT = re.compile(
    _THENCE_COURSE.pattern + "|" + _COMPLETE_COURSE.pattern + r"|\b(?:BEGINNING|COMMENCING)\b",
    re.IGNORECASE,
)


def split_boundary_clauses(text: str) -> list[tuple[str, bool]]:
    """Return ``split_exception_clauses(text)`` with preamble exceptions kept on the parcel.

    An EXCEPT clause whose lead may not type a description (``_except_may_type``:
    before the first description, or after a tie or recital with no closed boundary)
    is the first description's preamble ("ALL THAT tract, EXCEPTING AND RESERVING the
    oil and gas rights, BEGINNING ..."): it never makes that description an exception
    (INV-1). Its wording, lead included, is joined to the clause before it, unless its
    lead takes the exception from lands described later and a separate description
    does follow (``_excepts_from_later_description``), or its own clause introduces the
    clause's description (``_introduced_role``: "EXCEPTING THEREFROM the following
    described parcel: BEGINNING ..."). A text whose one description a LESS / SAVE /
    RESERVING lead introduces (no EXCEPT to split on) is one exception clause.
    """
    return _boundary_clauses(_index(text))


def _lone_rights_preamble(index: _TextIndex) -> bool:
    """Return whether a text opening with an EXCEPT lead opens with a rights recital.

    "EXCEPTING AND RESERVING all oil, gas and mineral rights. BEGINNING ..." (r59): the
    lead recites rights (``_rights_recital``), may not type the description after it
    (``_except_may_type``: nothing is described before it) and does not introduce it, so
    it is the description's preamble (INV-1) and the description is the parcel. Every
    course was read as an exception before, so no traverse was computable. A lead taking
    land ("LESS AND EXCEPT any portion thereof conveyed to the State.") stays an exception
    clause (fail closed).
    """
    text = index.text
    opening = _opening_after(text, 0)
    lead = None if opening is None else _STATED_EXCEPT_LEAD.search(text, 0, opening)
    if opening is None or lead is None:
        return False
    own_end = _sentence_limit(text, lead.end(), opening)
    return (
        _rights_recital(text, lead.start(), lead.end(), own_end)
        and not _except_may_type(index, lead.start())
        and index.introduced(opening) is None
    )


def _boundary_clauses(index: _TextIndex) -> list[tuple[str, bool]]:
    """``split_boundary_clauses`` of ``index.text``, with its clause structure built."""
    text = index.text
    clauses = split_exception_clauses(text)
    if len(clauses) < 2:
        if clauses and clauses[0][1]:
            # A lone exception clause: the text opens with its EXCEPT lead.
            return [(clauses[0][0], not _lone_rights_preamble(index))]
        if clauses and index.text_role == TractType.EXCEPTION:
            return [(clauses[0][0], True)]
        return clauses
    # (start, end, is_exception) of each clause in ``text``, in order.
    spans: list[tuple[int, int, bool]] = []
    # Where a recital before the first kept clause starts (it joins that clause).
    pending: int | None = None
    cursor = 0
    for clause, is_exception in clauses:
        start = text.find(clause, cursor)
        if start < 0:
            return clauses
        previous_end, cursor = cursor, start + len(clause)
        leads = list(_PRECEDING_EXCEPT.finditer(text, previous_end, start))
        lead = leads[-1].start() if leads else start
        opening = _opening_after(text, start, cursor)
        # The clause split cuts a lead in two ("SAVE AND | EXCEPT"): its whole wording
        # may introduce the clause's description.
        floor = min(
            (s for s, e in index.taking if s < previous_end and lead < e), default=previous_end
        )
        preamble = (
            is_exception
            and not _except_may_type(index, lead)
            and not _excepts_from_later_description(index, lead, cursor, start)
            and (opening is None or index.introduced(opening, floor) is None)
        )
        if preamble:
            if spans:
                first, _, kind = spans.pop()
                spans.append((first, cursor, kind))
            else:
                spans.append((0, cursor, False))
                pending = None
            continue
        # A course-free BEING recital split off by ALSO / INCLUDING ("ALSO BEING known
        # as Block 91 Lot 32 ...", "Also being the same premises ...") describes no land:
        # it stays with the clause before it (or the first clause after it). Any THENCE,
        # course or BEGINNING / COMMENCING word keeps the clause (an OCR-scrambled
        # description is never folded away).
        if (
            not is_exception
            and _BEING_RECITAL.match(text, start)
            and not _TRAVERSE_WORDING.search(text, start, cursor)
            and not _OPENING_WORD.search(text, start, cursor)
        ):
            if spans:
                first, _, kind = spans.pop()
                spans.append((first, cursor, kind))
            elif pending is None:
                pending = start
            continue
        spans.append((start if pending is None else pending, cursor, is_exception))
        pending = None
    if pending is not None:
        spans.append((pending, cursor, False))
    return [(text[start:end].strip(), kind) for start, end, kind in spans]


def _sentence_start(text: str, position: int) -> int:
    """Return where the sentence holding ``position`` starts.

    After the last document structure (``STRUCTURE_BREAK``: a paragraph break, a
    markdown heading, a table border, an HTML tag) or sentence-ending period before it.
    """
    start = 0
    for brk in STRUCTURE_BREAK.finditer(text, 0, position):
        start = brk.end()
    period = text.rfind(".", start, position)
    while period >= 0 and not ends_sentence(text, period):
        period = text.rfind(".", start, period)
    return max(start, period + 1)


def _split_clauses(text: str, index: _TextIndex | None = None) -> list[tuple[str, str, TractType]]:
    """Split ``text`` by EXCEPT/ALSO clauses, or keep it as one tract.

    ``index`` is the text's clause structure when already built.
    """
    index = _index(text) if index is None else index
    # 3. Fall back to EXCEPT/ALSO splitting
    clauses = _boundary_clauses(index)
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

    # The one description introduced by its own lead is that lead's, never the parcel.
    role = index.text_role
    if role is not None:
        label = "Exception 1" if role == TractType.EXCEPTION else EASEMENT_LABEL
        return [(text, label, role)]

    # Single tract — pass through (log if multiple BEGINNINGs detected but unmatched)
    beginning_count = len(_beginning_starts(text))
    if beginning_count > 1:
        logger.warning(
            "Single-tract fallback with multiple BEGINNING keywords",
            beginning_count=beginning_count,
            text_length=len(text),
        )
    return [(text, "Tract 1", TractType.MAIN)]
