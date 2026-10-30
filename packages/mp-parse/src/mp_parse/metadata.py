"""Metadata extraction from metes and bounds legal descriptions.

Extracts structured metadata: PLSS data, POC/POB, area statements,
basis of bearing, surveyor certification, prior conveyance, deed clauses,
subdivision references, witness trees, coordinate systems, and more.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from re import Match
from typing import TYPE_CHECKING, Literal, NamedTuple, TypedDict

from mp_models import ConversionFactors

from .units import (
    LENGTH_NUMBER,
    LENGTH_UNIT,
    UNIT_TOKEN,
    is_foot_mark,
    normalize_unit_token,
    parse_number,
)

if TYPE_CHECKING:
    from mp_models import DeedClause, SubdivisionReference


# Sentence-boundary markers where the legal description ends and post-description
# metadata begins.  The pattern requires ". " before the keyword so that phrases
# embedded *within* a call (e.g., "subject to easement rights") are not matched.
_METADATA_BOUNDARY = re.compile(
    r"\.\s+(?:"
    r"THE ABOVE DESCRIBED"
    r"|BEING (?:the same|all that|lot|part)"
    r"|CONTAINING"
    r"|SUBJECT TO"
    r"|UNDER AND SUBJECT"
    r"|TOGETHER WITH"
    r"|RESERVING"
    r"|Said premises"
    r"|This conveyance"
    r"|I hereby certify"
    r"|Certified by"
    r"|Surveyed by"
    r"|AS SHOWN ON"
    r")",
    re.IGNORECASE,
)

# Words whose trailing period abbreviates them ("Main St.", "Acme Co.", "Deed Bk. 12").
_ABBREVIATIONS = frozenset(
    {
        "ave", "blvd", "dr", "ft", "in", "no", "rd", "st",
        "bk", "co", "corp", "inc", "jr", "ltd", "mr", "mrs", "ms", "pg", "sr", "vol", "wm",
    }
)  # fmt: skip
# A word opening a new deed clause or description; a period before it ends a sentence
# even after an initial or abbreviation ("Lot B. Subject to ...", "Acme Inc. ALSO ...").
_CLAUSE_OPENING_WORD = re.compile(
    r"\s+(?:ALSO|BEING|BEGINNING|COMMENCING|CONTAINING|EXCEPT\w*|INCLUDING|LESS|RESERVING"
    r"|SAVE|SAVING|SUBJECT|THENCE|TOGETHER|UNDER|PARCEL|TRACT)\b",
    re.IGNORECASE,
)


def is_abbreviation_period(text: str, index: int) -> bool:
    """Return whether the period at ``text[index]`` belongs to a word, not a sentence.

    A decimal point ("1.5"), a single-letter initial or acronym letter ("John A.
    Smith", "U.S."), or a known abbreviation ("Co.", "Bk.", "Jr.") keeps its period.
    """
    if text[index + 1 : index + 2].isdigit():
        return True
    word = re.search(r"(?<![A-Za-z])([A-Za-z]+)$", text[:index])
    return word is not None and (len(word.group(1)) == 1 or word.group(1).lower() in _ABBREVIATIONS)


def ends_sentence(text: str, index: int) -> bool:
    """Return whether the period at ``text[index]`` ends a sentence.

    It ends one before the end of ``text`` or before whitespace and a capital or "(",
    unless it is an initial, acronym, abbreviation or decimal point. Before a clause
    opening word ("Subject to", "ALSO", "Being") a period always ends the sentence.
    """
    rest = text[index + 1 :]
    if not rest.strip():
        return True
    if not re.match(r"\s+[A-Z(]", rest):
        return False
    return bool(_CLAUSE_OPENING_WORD.match(rest)) or not is_abbreviation_period(text, index)


def _before_clause_delimiter(text: str) -> str:
    """Trim a call at sentence punctuation without splitting decimals or abbreviations."""
    for match in re.finditer(r"[;.]", text):
        if match.group() == "." and is_abbreviation_period(text, match.start()):
            continue
        return text[: match.start()]
    return text


class _AreaStatement(TypedDict):
    value_sq_ft: float
    unit: str
    approximate: bool


_SQ_FT_UNIT = r"sq\.?\s*ft\.?|square\s+feet?"
_AREA_LEAD_UNIT = rf"(?:{_SQ_FT_UNIT}|acres?)"
# Later components of a compound area ("2 acres and 50 perches", "2 acres, 3 roods
# and 10 perches"): after an area, a perch, rod or pole is a square perch.
_SQ_PERCH_FEET = ConversionFactors.PERCH_TO_FEET**2
_AREA_COMPONENT = re.compile(
    rf"\s*,?\s*(?:and\s+)?(?P<value>{LENGTH_NUMBER})\s*"
    rf"(?P<unit>{_SQ_FT_UNIT}|acres?|roods?|(?:(?:square|sq\.?)\s*)?(?:perch(?:es)?|rods?|poles?))"
    r"(?![a-z])\.?",
    re.IGNORECASE,
)
# "2 acres and 50 feet": a further joined value that is not a read area unit. The
# area is then unavailable, never reported without it.
_UNREAD_AREA_COMPONENT = re.compile(rf"\s*,?\s*and\s+{LENGTH_NUMBER}\s*[a-z]", re.IGNORECASE)


def _area_sq_ft(value: str, unit: str) -> float:
    number = parse_number(value)
    unit = unit.lower()
    if unit.startswith("acre"):
        return number * ConversionFactors.ACRE_TO_SQ_FEET
    if unit.startswith("rood"):
        return number * ConversionFactors.ACRE_TO_SQ_FEET / 4
    if re.search(r"perch|rod|pole", unit):
        return number * _SQ_PERCH_FEET
    return number


def extract_area_statement(text: str) -> _AreaStatement | None:
    """Extract the first stated area statement from legal text.

    Returns a dict with:
        value_sq_ft: numeric area in square feet
        unit: original unit label ("sq_ft" or "acres"; "compound" for a sum such
            as "2 acres and 50 perches")
        approximate: whether wording indicates approximation

    Values use the shared length-number grammar (".5", "2 1/2", "1,234.5"). A
    compound area sums its components (acres, roods, square perches/rods/poles,
    square feet); a joined component that cannot be read makes the statement
    unavailable rather than partial. If no parseable area statement exists,
    returns None.
    """
    if not isinstance(text, str):
        return None

    normalized_text = text.lower()
    if not normalized_text:
        return None

    area_pattern = re.compile(
        rf"(?P<value>{LENGTH_NUMBER})\s*(?P<unit>{_AREA_LEAD_UNIT})(?![a-z])\.?",
        re.IGNORECASE,
    )

    matches = list(area_pattern.finditer(normalized_text))
    if not matches:
        return None

    def is_parent_area_context(match: re.Match[str]) -> bool:
        preceding_text = normalized_text[: match.start()]
        clause_start = max(
            preceding_text.rfind(";"), preceding_text.rfind("."), preceding_text.rfind("\n")
        )
        clause_prefix = preceding_text[clause_start + 1 :]
        return bool(
            re.search(r"\b(?:parent|larger|original)\s+(?:tract|parcel|lot)\b", clause_prefix)
        )

    # A bare area remains a supported API input, but an area embedded in a
    # legal description must be tied to the described parcel, not its parent.
    standalone = re.fullmatch(
        rf"\s*(?:(?:approximately|approx\.?|~)\s+)?"
        rf"{LENGTH_NUMBER}\s*{_AREA_LEAD_UNIT}"
        r"(?:\s+more\s+or\s+less)?\s*[.]?\s*",
        normalized_text,
        re.IGNORECASE,
    )
    parcel_matches = [
        match
        for match in matches
        if re.search(
            r"\b(?:containing|contains|comprising|consisting\s+of)\b|\barea\s*:\s*$",
            normalized_text[max(0, match.start() - 55) : match.start()],
        )
        and not re.search(
            r"\b(?:parent|larger|original)\s+tract\b",
            normalized_text[match.start() : match.end() + 45],
        )
        and not is_parent_area_context(match)
    ]
    if not parcel_matches and not standalone:
        return None

    for match in parcel_matches or matches[:1]:
        unit = match.group("unit")
        value_sq_ft = _area_sq_ft(match.group("value"), unit)
        unit_key = "acres" if "acre" in unit else "sq_ft"
        end = match.end()
        while component := _AREA_COMPONENT.match(normalized_text, end):
            value_sq_ft += _area_sq_ft(component.group("value"), component.group("unit"))
            unit_key = "compound"
            end = component.end()
        if _UNREAD_AREA_COMPONENT.match(normalized_text, end):
            return None

        prefix = normalized_text[max(0, match.start() - 45) : end + 45]
        approximate = bool(
            "~" in prefix
            or re.search(r"\bapprox(?:imately)?\.?\b", prefix)
            or "more or less" in prefix
        )

        return {
            "value_sq_ft": value_sq_ft,
            "unit": unit_key,
            "approximate": approximate,
        }

    return None


def extract_plss_metadata(text: str) -> dict[str, str | None]:
    """Extract PLSS (Public Land Survey System) metadata from text.

    Args:
        text: Legal description text

    Returns:
        Dict with section, township, range, principal_meridian, aliquot
    """
    plss_data: dict[str, str | None] = {
        "section": None,
        "township": None,
        "range": None,
        "principal_meridian": None,
        "aliquot": None,
    }

    text_upper = text.upper()

    section_match = re.search(r"\bSECTION\s+(\d+)\b", text_upper)
    if section_match:
        plss_data["section"] = section_match.group(1)

    township_match = re.search(
        r"\b(?:TOWNSHIP|TOWN|T\.?)\s*(\d+)\s*(NORTH|N\.?|SOUTH|S\.?)\b", text_upper
    )
    if township_match:
        township_num = township_match.group(1)
        direction_token = township_match.group(2)
        direction = "N" if direction_token.startswith("N") else "S"
        plss_data["township"] = f"{township_num} {direction}"

    range_match = re.search(r"\b(?:RANGE|R\.?)\s*(\d+)\s*(EAST|E\.?|WEST|W\.?)\b", text_upper)
    if range_match:
        range_num = range_match.group(1)
        direction_token = range_match.group(2)
        direction = "W" if direction_token.startswith("W") else "E"
        plss_data["range"] = f"{range_num} {direction}"

    pm_patterns = [
        r"\b(?:IN\s+|THE\s+)?([A-Z0-9]+(?:\s+[A-Z0-9]+){0,4})\s+PRINCIPAL\s+MERIDIAN\b",
        r"\b(?:IN\s+|THE\s+)?([A-Z0-9]+(?:\s+[A-Z0-9]+){0,4})\s+P\.?M\.?\b",
    ]
    for pattern in pm_patterns:
        pm_match = re.search(pattern, text_upper)
        if pm_match:
            meridian_name = pm_match.group(1).title()
            plss_data["principal_meridian"] = f"{meridian_name} Principal Meridian"
            break

    aliquot_pattern = r"\b((?:NE|NW|SE|SW|N|S|E|W)\s*(?:1/\d+|½|¼)\s+OF\s+(?:THE\s+)?)+(?:NE|NW|SE|SW|N|S|E|W)\s*(?:1/\d+|½|¼)\b"
    aliquot_match = re.search(aliquot_pattern, text_upper)
    if aliquot_match:
        aliquot_text = aliquot_match.group(0)
        aliquot_text = aliquot_text.replace("½", "1/2").replace("¼", "1/4")
        plss_data["aliquot"] = aliquot_text

    return plss_data


def extract_pob(text: str) -> str:
    """Extract Point of Beginning description.

    Args:
        text: Legal description text

    Returns:
        POB description string
    """
    pob_patterns = [
        r"BEGINNING\s+at\s+(.*?)(?:\.|;|THENCE)",
        r"POB\s+at\s+(.*?)(?:\.|;|THENCE)",
        r"POINT\s+OF\s+BEGINNING\s+at\s+(.*?)(?:\.|;|THENCE)",
        r"commencing\s+at\s+(.*?)(?:\.|;|THENCE)",
        r"TRUE\s+POINT\s+OF\s+BEGINNING\s+at\s+(.*?)(?:\.|;|THENCE)",
        r"TPOB\s+at\s+(.*?)(?:\.|;|THENCE)",
        r"T\.P\.O\.B\.\s+at\s+(.*?)(?:\.|;|THENCE)",
        r"REMOTE\s+POINT\s+OF\s+BEGINNING\s+at\s+(.*?)(?:\.|;|THENCE)",
        r"RPOB\s+at\s+(.*?)(?:\.|;|THENCE)",
    ]

    for pattern in pob_patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()

    return ""


def is_closure_to_pob(text: str) -> bool:
    """Detect if call text indicates closure back to Point of Beginning.

    Args:
        text: Call text to check

    Returns:
        True if text indicates returning to POB, False otherwise
    """
    closure_patterns = [
        r"\bto\s+(?:the\s+)?(?:point\s+of\s+)?beginning\b",
        r"\bto\s+(?:the\s+)?POB\b",
        r"\breturning\s+to\s+(?:the\s+)?(?:point\s+of\s+)?beginning\b",
        r"\bback\s+to\s+(?:the\s+)?(?:point\s+of\s+)?beginning\b",
        r"\bback\s+to\s+(?:the\s+)?POB\b",
        r"\bto\s+(?:the\s+)?(?:true\s+point\s+of\s+beginning\b|TPOB\b|T\.P\.O\.B\.)",
        r"\bto\s+(?:the\s+)?(?:remote\s+point\s+of\s+beginning\b|RPOB\b|R\.P\.O\.B\.)",
    ]

    text_lower = text.lower()

    for pattern in closure_patterns:
        last_part = text_lower[-60:] if len(text_lower) > 60 else text_lower
        if re.search(pattern, last_part, re.IGNORECASE):
            return True

    return False


def extract_poc(text: str) -> str:
    """Extract Point of Commencement (distinct from Point of Beginning).

    POC is the reference point where the survey starts, often distinct from
    where the parcel boundary begins (POB). Common pattern:
    "COMMENCING at [POC]; THENCE ... to the POINT OF BEGINNING; THENCE ..."

    Args:
        text: Legal description text

    Returns:
        POC description string (empty if no separate POC found)
    """
    pob_pattern = r"\b(?:point\s+of\s+beginning|beginning|POB)\b"

    has_later_pob = bool(re.search(pob_pattern, text, re.IGNORECASE))

    if not has_later_pob:
        return ""

    poc_patterns = [
        r"COMMENCING\s+at\s+(.*?)(?:;|THENCE)",
        r"STARTING\s+at\s+(.*?)(?:,|;|THENCE)",
    ]

    for pattern in poc_patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            poc_text = match.group(1).strip()
            poc_end_pos = match.end()

            pob_match = re.search(pob_pattern, text[poc_end_pos:], re.IGNORECASE)
            if pob_match:
                return poc_text

    return ""


def extract_poc_and_pob(text: str) -> tuple[str, str]:
    """Extract both Point of Commencement and Point of Beginning.

    Args:
        text: Legal description text

    Returns:
        Tuple of (poc_description, pob_description)
    """
    poc = extract_poc(text)
    pob = extract_pob(text)

    return (poc, pob)


_COUNT_WORDS = {
    word: number
    for number, word in enumerate(
        "one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
        "fifteen sixteen seventeen eighteen nineteen twenty".split(),
        start=1,
    )
}
_ORDINAL_WORDS = {
    word: number
    for number, word in enumerate(
        "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth "
        "thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth "
        "twentieth".split(),
        start=1,
    )
}
# Enumerator styles: "(1)", "1)", "1.", "(a)" and "First,". Numbers are read from
# group 1; a letter counts a=1, b=2, ...
_ORDINAL_ENUMERATOR = re.compile(rf"\b({'|'.join(_ORDINAL_WORDS)})\b,?", re.IGNORECASE)
_LETTER_ENUMERATOR = re.compile(r"(?<![\w(])\(([A-Za-z])\)(?=\s)")
_ENUMERATOR_STYLES = (
    re.compile(r"\((\d{1,3})\)"),
    re.compile(r"(?<![\w.(])(\d{1,3})\)"),
    re.compile(r"(?<![\w.(])(\d{1,3})\.(?=\s)"),
    _LETTER_ENUMERATOR,
    _ORDINAL_ENUMERATOR,
)

# The one course-list header grammar, shared by header removal and enumeration
# detection:
#   THENCE [by|along|with|running|continuing|in <qualifier>] the following|next
#   [N | word | (N) | word (N)] courses|calls|lines [and distances]
#   [along|with|by ... <qualifier>] [, to wit | viz | namely] [: ; , .]
# Qualifiers are bounded and never cross ';' or ':'. A trailing qualifier holds
# digits only when an explicit ':' / 'to wit' / 'viz' ends it, so a course
# ("the following course North 10 degrees East 100 feet") is never a header.
_HEADER_QUALIFIER = r"(?:(?:by|along|with|running|continuing|in)\b[^;:]{0,200}?[\s,]+)?"
_HEADER_CORE = (
    r"the\s+(?:following|next)(?:\s+(?P<count>\d{1,3}|[a-z]+))?(?:\s+\((?P<count_paren>\d{1,3})\))?"
    r"\s+(?:courses?|calls?|lines)(?:\s+and\s+distances?)?"
)
_HEADER_TAIL_WORD = r"[\s,]+(?:along|with|by|over|across|through|on|in|of|from|being)\b"
_HEADER_WIT = r"\s*,?\s*(?:to\s+wit|viz\.?|namely)"
_HEADER_REST = (
    rf"(?:{_HEADER_TAIL_WORD}[^;:]{{0,200}}?(?:{_HEADER_WIT}\s*[:;,.]?|\s*:)"
    rf"|(?:{_HEADER_TAIL_WORD}[^;:\d]{{0,200}}?)?(?:{_HEADER_WIT})?\s*[:;,.]?)\s*"
)
_THENCE = re.compile(r"\bTHENCE\b", re.IGNORECASE)
_HEADER_START = re.compile(r"THENCE\b[\s,]*" + _HEADER_QUALIFIER + _HEADER_CORE, re.IGNORECASE)
# From the end of a header's core to its first enumerator (a repeated THENCE allowed).
_HEADER_END = re.compile(_HEADER_REST + r"(?:THENCE\b[\s,]*[:;,.]?\s*)?", re.IGNORECASE)
_HEADER_REST_ONLY = re.compile(_HEADER_REST, re.IGNORECASE)
_BARE_THENCE = re.compile(r"THENCE\b[\s,]*[:;,.]?\s*", re.IGNORECASE)
# A split part that is only a THENCE or a course-list header introduces courses
# and is never a course itself.
COURSE_LIST_MARKER = re.compile(
    r"\s*(?:THENCE\b[\s,]*|(?:THENCE\b[\s,]*)?"
    + _HEADER_QUALIFIER
    + _HEADER_CORE
    + _HEADER_REST
    + r")?[:;,.]?\s*",
    re.IGNORECASE,
)
_HEADER_PREFIX = re.compile(_HEADER_QUALIFIER + _HEADER_CORE + _HEADER_REST, re.IGNORECASE)


def _split_header_led_parts(parts: list[str]) -> list[str]:
    """Split a part that opens with a course-list header on its ';'-separated courses.

    "THENCE the following two courses: N 10 E 100 feet; S 80 E 100 feet; THENCE ..."
    leaves both courses in one THENCE part. A segment with no digit continues the
    previous course (its wording is kept whole), so nothing is dropped.
    """
    result: list[str] = []
    for part in parts:
        stripped = part.lstrip()
        header = _HEADER_PREFIX.match(stripped)
        if header is None or ";" not in stripped[header.end() :]:
            result.append(part)
            continue
        courses: list[str] = []
        for segment in stripped[header.end() :].split(";"):
            if courses and not re.search(r"\d", segment):
                courses[-1] += ";" + segment
            else:
                courses.append(segment)
        courses = [course for course in courses if course.strip()]
        if len(courses) < 2:
            result.append(part)
            continue
        result.append(stripped[: header.end()])
        result.extend(courses)
    return result


_NUMBERED_LINE = re.compile(r"(?:^|\n)\s*(?:\(\d+\)|\d+[.)])\s+", re.MULTILINE)
_NUMBERED_SPLIT = re.compile(r"(?:^|\n)\s*(?=(?:\(\d+\)|\d+[.)])\s+)", re.MULTILINE)
_TRAILING_THENCE = re.compile(r"\bTHENCE\b[\s,]*$", re.IGNORECASE)
_GAP_END = re.compile(r"(?:[;:,.]|\band|\bthen(?:ce)?)$", re.IGNORECASE)


@dataclass(frozen=True)
class CourseListHeader:
    """A 'THENCE ... the following [N] courses' header; ``declared`` is its stated count."""

    start: int
    core_end: int
    declared: int | None


@dataclass(frozen=True)
class CourseList:
    """An enumerated course list: 1, 2, 3, ... after a header or a bare THENCE."""

    start: int
    header: CourseListHeader | None
    enumerators: tuple[Match[str], ...]


@dataclass(frozen=True)
class CourseListAnalysis:
    """Course-list structure of one text, computed once and passed through.

    ``text`` has every enumerator of a list run inline (one with any enumerator not
    starting its own line) rewritten onto its own '(n)' line; ``item_starts`` are
    the offsets of those lines in ``text`` and ``list_starts`` the offsets of the
    lines that open a list.
    """

    source: str
    text: str
    lists: tuple[CourseList, ...]
    mismatches: tuple[tuple[int, int], ...]
    mismatch_headers: tuple[str, ...]
    item_starts: frozenset[int]
    list_starts: frozenset[int]
    has_numbered_markers: bool


def _enumerator_number(match: Match[str]) -> int:
    token = match.group(1)
    if token.isdigit():
        return int(token)
    if len(token) == 1:
        return ord(token.lower()) - ord("a") + 1
    return _ORDINAL_WORDS[token.lower()]


def course_list_header_text(text: str, header: CourseListHeader) -> str:
    """The header's own wording: from THENCE through its closing punctuation."""
    rest = _HEADER_REST_ONLY.match(text, header.core_end)
    return text[header.start : rest.end() if rest else header.core_end].strip()


def _declared_course_count(header: Match[str]) -> int | None:
    for token in (header.group("count_paren"), header.group("count")):
        if token is None:
            continue
        if token.isdigit():
            return int(token)
        if token.lower() in _COUNT_WORDS:
            return _COUNT_WORDS[token.lower()]
    return None


def _course_list_headers(text: str, thence_starts: list[int]) -> list[CourseListHeader]:
    headers = []
    for start in thence_starts:
        match = _HEADER_START.match(text, start)
        if match is not None:
            headers.append(CourseListHeader(start, match.end(), _declared_course_count(match)))
    return headers


def _list_opening(
    text: str,
    position: int,
    headers: list[CourseListHeader],
    header_ends: list[int],
    thence_starts: list[int],
) -> tuple[int, CourseListHeader | None] | None:
    """Return (start, header) when a header or bare THENCE runs right up to ``position``."""
    index = bisect_right(header_ends, position) - 1
    if index >= 0:
        header = headers[index]
        if _HEADER_END.fullmatch(text, header.core_end, position):
            return header.start, header
    index = bisect_right(thence_starts, position) - 1
    if index >= 0 and _BARE_THENCE.fullmatch(text, thence_starts[index], position):
        return thence_starts[index], None
    return None


def _continues_list(text: str, previous_end: int, position: int) -> bool:
    """Whether an enumerator at ``position`` directly follows the previous course's
    punctuation, 'and', THENCE or a line break (bounded look-back, no full-gap scan)."""
    end = position
    while end > previous_end and text[end - 1].isspace():
        end -= 1
    if "\n" in text[end:position]:
        return True
    return bool(_GAP_END.search(text, max(previous_end, end - 8), end))


def _course_enumerations(text: str) -> tuple[list[CourseList], list[CourseListHeader]]:
    """Find each enumerated course list: a header or THENCE, then 1, 2, 3, ... in order.

    Each enumerator after the first must directly follow the previous course's
    punctuation (or a line break), so parenthetical numbers elsewhere ("Lot (2)",
    "(Tax ID 12-34)", "(100.00 feet)") are never taken for course numbers. Ordinal
    words ("First,") enumerate only after a real header and as a sequence of two or
    more, so prose such as "THENCE first North ..." keeps its wording. Letters
    ("(a)", "(b)") enumerate only as a sequence of two or more.
    """
    thence_starts = [m.start() for m in _THENCE.finditer(text)]
    headers = _course_list_headers(text, thence_starts)
    header_ends = [header.core_end for header in headers]
    styles = [list(style.finditer(text)) for style in _ENUMERATOR_STYLES]
    ordinal_style = len(styles) - 1
    letter_style = _ENUMERATOR_STYLES.index(_LETTER_ENUMERATOR)
    cursors = [0] * len(styles)

    def opening(match: Match[str], ordinal: bool) -> tuple[int, CourseListHeader | None] | None:
        if _enumerator_number(match) != 1:
            return None
        found = _list_opening(text, match.start(), headers, header_ends, thence_starts)
        if found is None or (ordinal and found[1] is None):
            return None
        return found

    found_lists: list[CourseList] = []
    position = 0
    while True:
        best: CourseList | None = None
        for style_index, matches in enumerate(styles):
            ordinal = style_index == ordinal_style
            needs_two = ordinal or style_index == letter_style
            while cursors[style_index] < len(matches) and (
                matches[cursors[style_index]].start() < position
            ):
                cursors[style_index] += 1
            for index in range(cursors[style_index], len(matches)):
                first = matches[index]
                if best is not None and first.start() > best.enumerators[0].start():
                    break
                start_header = opening(first, ordinal)
                if start_header is None:
                    continue
                sequence = [first]
                for candidate in matches[index + 1 :]:
                    if opening(candidate, ordinal) is not None:
                        break  # the next list begins
                    if _enumerator_number(candidate) == len(sequence) + 1 and _continues_list(
                        text, sequence[-1].end(), candidate.start()
                    ):
                        sequence.append(candidate)
                if needs_two and len(sequence) < 2:
                    continue
                course_list = CourseList(start_header[0], start_header[1], tuple(sequence))
                if (
                    best is None
                    or first.start() < best.enumerators[0].start()
                    or len(sequence) > len(best.enumerators)
                ):
                    best = course_list
                break
        if best is None:
            return found_lists, headers
        found_lists.append(best)
        position = best.enumerators[-1].end()


_COURSE_SEGMENT_SPLIT = re.compile(r";|\bTHENCE\b", re.IGNORECASE)


def _courses_after_header(text: str, header: CourseListHeader) -> int:
    """Courses (THENCE/semicolon segments) that follow a header within its tract."""
    opening = _HEADER_END.match(text, header.core_end)
    tail = text[opening.end() if opening is not None else header.core_end :]
    boundary = _METADATA_BOUNDARY.search(tail)
    if boundary:
        tail = tail[: boundary.start()]
    return sum(1 for part in _COURSE_SEGMENT_SPLIT.split(tail) if re.search(r"[A-Za-z]", part))


def _count_mismatches(
    text: str, lists: list[CourseList], headers: list[CourseListHeader]
) -> list[tuple[CourseListHeader, int, int]]:
    """(header, declared, found) for each counted header its enumerated courses do not satisfy.

    A header opening a list must match its length. A header inside a deed-numbered
    list ("...; thence along X, the following two courses; thence (4) ...") needs at
    least that many enumerated courses after it. A counted header with no
    enumeration needs at least that many courses after it in the tract (the list's
    end is not marked, so "at least" is the honest check); fewer is a mismatch.
    """
    mismatches = []
    for header in headers:
        if header.declared is None:
            continue
        found: int | None = None
        for course_list in lists:
            if course_list.header == header:
                found = len(course_list.enumerators)
                break
            enumerators = course_list.enumerators
            if enumerators[0].start() < header.start < enumerators[-1].start():
                after = sum(1 for m in enumerators if m.start() > header.start)
                found = header.declared if after >= header.declared else after
                break
        if found is None:
            after = _courses_after_header(text, header)
            found = header.declared if after >= header.declared else after
        if found != header.declared:
            mismatches.append((header, header.declared, found))
    return mismatches


def _is_inline(text: str, match: Match[str]) -> bool:
    position = match.start()
    while position > 0 and text[position - 1] in " \t":
        position -= 1
    return position > 0 and text[position - 1] != "\n"


def analyze_course_lists(text: str) -> CourseListAnalysis:
    """Detect course-list headers and enumerations once for a tract's text."""
    lists, headers = _course_enumerations(text)
    mismatched = _count_mismatches(text, lists, headers)

    pieces: list[str] = []
    length = 0
    cursor = 0
    item_starts: set[int] = set()
    list_starts: set[int] = set()
    for course_list in lists:
        if not course_list.enumerators[0].group(1).isdigit():
            pass  # ordinal words never split as numbered lines, so always rewrite them
        elif not any(_is_inline(text, match) for match in course_list.enumerators):
            continue  # a digit list already one course per line splits as numbered lines
        for match in course_list.enumerators:
            head_end = match.start()
            while head_end > cursor and text[head_end - 1] in " \t":
                head_end -= 1
            # The enumerator replaces a THENCE keyword it follows ("thence (2) ...").
            thence = _TRAILING_THENCE.search(text, max(cursor, head_end - 40), head_end)
            if thence is not None:
                head_end = thence.start()
                while head_end > cursor and text[head_end - 1] in " \t":
                    head_end -= 1
            line = text[cursor:head_end]
            if head_end > 0 and text[head_end - 1] != "\n":
                line += "\n"
            pieces.append(line)
            length += len(line)
            item_starts.add(length)
            if match is course_list.enumerators[0]:
                list_starts.add(length)
            marker = f"({_enumerator_number(match)}) "
            pieces.append(marker)
            length += len(marker)
            cursor = match.end()
            while cursor < len(text) and text[cursor] == " ":
                cursor += 1
    pieces.append(text[cursor:])
    broken = "".join(pieces)
    return CourseListAnalysis(
        source=text,
        text=broken,
        lists=tuple(lists),
        mismatches=tuple((declared, found) for _header, declared, found in mismatched),
        mismatch_headers=tuple(
            course_list_header_text(text, header) for header, _declared, _found in mismatched
        ),
        item_starts=frozenset(item_starts),
        list_starts=frozenset(list_starts),
        has_numbered_markers=_NUMBERED_LINE.search(broken) is not None,
    )


def break_inline_course_enumerators(text: str) -> str:
    """Put each enumerated course of a course list on its own '(n)' line.

    Only a sequence 1, 2, 3, ... that follows a course-list header or THENCE is
    rewritten; the enumerator is not deed language about the course itself.
    """
    return analyze_course_lists(text).text


def course_list_count_mismatches(text: str) -> list[tuple[int, int]]:
    """Return (declared, found) for each header whose stated count is not satisfied."""
    return list(analyze_course_lists(text).mismatches)


def _enumerated_parts(analysis: CourseListAnalysis) -> list[str]:
    """Split text holding course lists; re-split on THENCE only within lists.

    The leading text, the text holding a list's header, and the list's courses are
    THENCE-split; a course numbered on its own line outside any list keeps its
    wording whole ("to a point, thence running with said line").
    """
    text = analysis.text
    bounds = []
    previous = 0
    for match in _NUMBERED_SPLIT.finditer(text):
        bounds.append((previous, match.start()))
        previous = match.end()
    bounds.append((previous, len(text)))
    parts: list[str] = []
    for index, (start, end) in enumerate(bounds):
        part = text[start:end]
        following = bounds[index + 1][0] if index + 1 < len(bounds) else None
        within = index == 0 or start in analysis.item_starts or following in analysis.list_starts
        if within:
            parts.extend(_THENCE.split(part))
        else:
            parts.append(part)
    return parts


class CallFragment(NamedTuple):
    """One fragment of a split description.

    ``preamble`` marks a fragment opening with BEGINNING/COMMENCING/POB/POINT, which
    is not itself a call; its ``text`` is kept so a course inside it is never lost.
    """

    text: str
    preamble: bool = False


def unlisted_course_lists(text: str) -> CourseListAnalysis:
    """Return the analysis of ``text`` read without course-list detection."""
    return CourseListAnalysis(
        source=text,
        text=text,
        lists=(),
        mismatches=(),
        mismatch_headers=(),
        item_starts=frozenset(),
        list_starts=frozenset(),
        has_numbered_markers=_NUMBERED_LINE.search(text) is not None,
    )


_PREAMBLE_FRAGMENT = re.compile(r"^\s*(?:BEGINNING|COMMENCING|POB|POINT)", re.IGNORECASE)


def split_into_calls(text: str, *, course_lists: CourseListAnalysis | None = None) -> list[str]:
    """Split text into individual THENCE calls.

    Handles multiple formats:
    - Numbered (1., 2., 3.; 1), 2); (1), (2))
    - THENCE keyword separated
    - Semicolon separated

    Args:
        text: Legal description text
        course_lists: The text's precomputed ``analyze_course_lists`` result

    Returns:
        List of call strings; BEGINNING/COMMENCING fragments are dropped
        (``split_call_fragments`` reports them).
    """
    return [
        fragment.text
        for fragment in split_call_fragments(text, course_lists=course_lists)
        if not fragment.preamble
    ]


def split_call_fragments(
    text: str, *, course_lists: CourseListAnalysis | None = None
) -> list[CallFragment]:
    """Split text as ``split_into_calls`` does, keeping the preamble fragments it drops.

    Fragments are in source order; a preamble fragment's text is stripped only.
    """
    analysis = course_lists if course_lists is not None else analyze_course_lists(text)
    if analysis.item_starts:
        parts = _enumerated_parts(analysis)
    elif _NUMBERED_LINE.search(text):
        parts = _NUMBERED_SPLIT.split(text)
    elif _THENCE.search(text):
        parts = _split_header_led_parts(_THENCE.split(text))
    else:
        parts = text.split(";")

    calls = []
    for part in parts:
        cleaned = part.strip()
        if not cleaned:
            continue

        if _PREAMBLE_FRAGMENT.match(cleaned):
            calls.append(CallFragment(cleaned, preamble=True))
            continue

        cleaned = re.sub(r"^(?:\(\d+\)|\d+[.)])\s+", "", cleaned)

        # Truncate at metadata section boundaries (e.g., "THE ABOVE DESCRIBED",
        # "CONTAINING", "BEING the same").  The pattern is sentence-boundary
        # anchored (". KEYWORD") so mid-call phrases are not affected.
        boundary = _METADATA_BOUNDARY.search(cleaned)
        if boundary:
            cleaned = cleaned[: boundary.start()]

        cleaned = re.sub(r"[;,\.\s]+$", "", cleaned)

        if cleaned and calls and not calls[-1].preamble and _PASSING_PIECE.match(cleaned):
            # A ';'-separated passing call belongs to the course before it; with no
            # course before it, it stays a fragment of its own and fails closed.
            calls[-1] = CallFragment(f"{calls[-1].text}; {cleaned}")
        elif cleaned:
            calls.append(CallFragment(cleaned))

    return calls


# Without "and", only these (larger, smaller) unit pairs form a compound
# distance ("2 chains 20 links"). Equivalent units (pole/rod/perch) and
# unrelated adjacent measurements ("150 feet, 3 rods north of ...") never sum.
_IMPLICIT_COMPOUND_PAIRS = {
    ("chain", "link"),
    ("pole", "link"),
    ("rod", "link"),
    ("perch", "link"),
}


_EQUIVALENT_UNITS = {"pole", "rod", "perch"}


def _same_unit_family(first: str, second: str) -> bool:
    return first == second or (first in _EQUIVALENT_UNITS and second in _EQUIVALENT_UNITS)


def _singular_unit(unit: str) -> str:
    unit = " ".join(unit.lower().split())
    return unit.removesuffix("es") if unit.endswith("ches") else unit.removesuffix("s")


# --- Straight-course length roles ----------------------------------------------------
# Every length on a course is classified by its context. Only a COURSE length (or a
# stated TOTAL, which wins) measures the course. A TIE locates a point ("distant 10
# feet from", "said pin being 2 feet from", "3 rods north of the oak"), a WIDTH
# describes a road ("50 feet wide"), a parenthetical length restates or describes
# ("(100.5 feet per deed)"), and a STATION marks a point passed on the line ("passing
# a pin at 30 feet") and a DIMENSION sizes a feature ("a fence 4 feet high"); none of
# these is the course length. A DEPTH ("150 feet deep", "100 feet long") is the course
# length only when no other course length is stated. A PARTIAL length ("70 feet
# more", "a further distance of") is only part of the course. Several course lengths,
# or a partial length without a stated total, are ambiguous: none is chosen.
COURSE_LENGTH_AMBIGUOUS_NOTE = "course length ambiguous: {values}"
TIE_BEFORE_PATTERN = re.compile(
    r"(?<![A-Za-z])(?:distant|being(?:\s+also)?|which\s+(?:is|lies)|that\s+is|lying"
    r"|located|situated)\s*,?\s*$",
    re.IGNORECASE,
)
# Lengths (possibly compound) and an optional "more or less" before a suffix label.
LENGTH_RUN = rf"(?:\s*,?\s*(?:and\s+)?{LENGTH_NUMBER}\s*{UNIT_TOKEN}\b\.?)*\s*,?\s*"
# "... 2 feet from|of <object>": a tie, unless it is the first length stated.
TIE_AFTER_PATTERN = re.compile(
    LENGTH_RUN + r"(?:more\s+or\s+less\s*,?\s*)?(?:from|of)\s+\S", re.IGNORECASE
)
_DIRECTION_WORD = (
    r"(?:(?:north|south)(?:[\s-]*(?:east|west))?|east|west|[NS][EW])(?:erly|wardly|wards?)?"
)
# "... 68 feet Southeastwardly from <object>", "3 rods north of the oak".
_DIRECTED_TIE_AFTER = re.compile(
    r"\s*,?\s*(?:more\s+or\s+less\s*,?\s*)?(?:in\s+an?\s+)?"
    + _DIRECTION_WORD
    + r"(?:\s+direction)?\s*,?\s+(?:from|of)\b",
    re.IGNORECASE,
)
# "... 50 feet distant from|off <object>", "50 feet (measured) at right angles from",
# "10 feet from and parallel to|with <object>": a separation from an object, even
# when it is the first length stated.
_OFFSET_AFTER = re.compile(
    r"\s*,?\s*(?:more\s+or\s+less\s*,?\s*)?(?:"
    r"(?:distant|distance)\s+(?:from|of)\b"
    r"|off\b(?!\s+(?:to|at)\b)"
    r"|(?:\(?\s*measured\s*\)?\s*)?at\s+(?:a\s+)?right\s+angles?\s+(?:from|to)\b"
    r"|(?:distant\s+)?from\s+and\s+parallel\s+(?:to|with)\b)",
    re.IGNORECASE,
)
# "parallel to|with and 10 feet (distant) from <object>": the length is the offset.
_PARALLEL_AND_BEFORE = re.compile(r"\bparallel\s+(?:to|with)\s+and\s*$", re.IGNORECASE)
_OFFSET_FROM_AFTER = re.compile(r"\s*,?\s*(?:distant\s+)?(?:from|of)\b", re.IGNORECASE)
_LENGTH_JUST_BEFORE = re.compile(rf"{LENGTH_NUMBER}\s*{UNIT_TOKEN}\b\.?\s*,?\s*$", re.IGNORECASE)
# "said point (also) being ...": every later length locates that point.
_TIE_CLAUSE = re.compile(
    r"\b(?:said|which)\s+(?:[A-Za-z-]+\s+){0,3}?(?:also\s+)?"
    r"(?:being|lying|located|situated|distant)\b",
    re.IGNORECASE,
)
# "80 feet in width or breadth" is the lot-dimension idiom (paired with "in length
# or depth"): the stated breadth along the line is the course length, not a width.
_WIDTH_AFTER = re.compile(r"\s*(?:wide|in\s+width(?!\s+or\s+breadth))\b", re.IGNORECASE)
# "a 50 foot road", "a 16.5 foot right of way": a length used as an adjective
# before a way or strip noun is that way's width, not a course length.
_WAY_NOUN = (
    r"(?:road|street|avenue|alley|lane|right[\s-]+of[\s-]+way|easement|strip|drive|driveway"
    r"|way|path|highway|roadway|walkway|boulevard|trail)s?"
)
_ADJECTIVE_WIDTH_AFTER = re.compile(
    r"[\s.-]*(?:wide[\s,-]+)?(?:(?!(?:to|along|thence|from|of|and|then|in|on|at|by|with|the|a|an)\b)"
    r"[A-Za-z]+\s+){0,2}?" + _WAY_NOUN + r"\b",
    re.IGNORECASE,
)
_ARTICLE_JUST_BEFORE = re.compile(r"\b(?:an?|the)\s+$", re.IGNORECASE)
# "pipe found 0.5 feet below grade", "a stake set 2 feet back", "a stone 4 feet
# high": a monument's depth, height or position, never a course length. Only with
# monument context: a monument noun (at most three words before) or "found"/"set"
# just before the length (``_MONUMENT_BEFORE``), or a grade/surface/ground
# reference after "below" or "above" (``_GRADE_DEPTH_AFTER``). Otherwise "100 feet back to the place of
# beginning" and "150 feet deep" (a lot depth) are course lengths.
_MONUMENT_DEPTH_AFTER = re.compile(
    r"\s*,?\s*(?:(?:below|above|beneath)\b|(?:deep|high|back)\b|in\s+(?:depth|height)\b)",
    re.IGNORECASE,
)
_GRADE_DEPTH_AFTER = re.compile(
    r"\s*,?\s*(?:below|above|beneath)\s+(?:the\s+)?(?:(?:existing|finished|natural)\s+)?"
    r"(?:grade|surface|ground)\b",
    re.IGNORECASE,
)
_MONUMENT_BEFORE = re.compile(
    r"\b(?:pipe|pin|rod|rebar|bar|spike|nail|stake|hub|monument|post|marker|cap|tack"
    r"|stone|bolt)s?\b(?:\s*,?\s*(?!(?:to|along|thence|from|of)\b)[A-Za-z]+){0,3}\s*,?\s*$"
    r"|\b(?:found|set)\s*,?\s*$",
    re.IGNORECASE,
)
# A feature's dimension: a length directly followed by a dimension word ("a fence 4
# feet high", "a stone 2 feet long", "a 6 foot high fence", "a 20 foot radius")
# describes that feature, not the course. Only "long" and "deep" can describe the
# course itself ("150 feet deep" as a lot depth): such a length is the course length
# only when no other course length is stated (``_select_course_length``), and never
# as an adjective after an article ("a 150 foot deep lot"). Every other dimension
# word never states the course length. "In length" and "in depth" ("142 feet in
# length or depth") are the deed's own course-length idiom and stay course lengths,
# so two of them, or one beside another course length, remain ambiguous.
_DIMENSION_AFTER = re.compile(
    r"[\s,-]*(?:(?P<course>long|deep)"
    r"|high|tall|thick|square|radius|diameter|in\s+(?:height|thickness|diameter))\b",
    re.IGNORECASE,
)
# A curve element's own label ("the radius is 100 feet"); never the course length.
_ELEMENT_BEFORE = re.compile(
    r"\b(?:radius|(?:long\s+)?chord|tangent|arc)(?:\s+(?:length|distance))?"
    r"(?:\s+(?:of|is|equal\s+to))?\s*[:=]?\s*$",
    re.IGNORECASE,
)
_STATION_BEFORE = re.compile(r"(?<![A-Za-z])at\s+(?:a\s+distance\s+of\s+)?$", re.IGNORECASE)
# "N 45 E at a distance of 100 feet to a pin": as the first length, and not
# measured "from"/"of" an object, "at a distance of" states the course length.
_AT_DISTANCE_OF_BEFORE = re.compile(r"(?<![A-Za-z])at\s+a\s+distance\s+of\s+$", re.IGNORECASE)
_MEASURED_FROM_AFTER = re.compile(r"\s*,?\s*(?:from|of|beyond|past|short\s+of)\b", re.IGNORECASE)
_TOTAL_BEFORE = re.compile(
    r"(?<![A-Za-z])(?:in\s+all|in\s+total|altogether"
    r"|total(?:\s+(?:distance|length))?(?:\s+of)?)\s*[:,]?\s*$",
    re.IGNORECASE,
)
_TOTAL_AFTER = re.compile(
    r"\s*,?\s*(?:in\s+all|in\s+total|altogether)\b(?!\s*[:,]?\s*\d)", re.IGNORECASE
)
_PARTIAL_BEFORE = re.compile(
    r"(?<![A-Za-z])(?:further|additional)\s+(?:distance\s+(?:of\s+)?)?$", re.IGNORECASE
)
_PARTIAL_AFTER = re.compile(
    r"\s*(?:more(?!\s+or\s+less)|further|farther|additional)\b", re.IGNORECASE
)
_ROLE_CONTEXT = 120
# An abbreviation's period ("100 ft. 6 in.") may precede the joiner.
_COMPOUND_GAP = re.compile(r"\.?(?:\s+and\s+|\s*,\s*|\s+)")
# Inches are only a compound component ("100 feet 6 inches"); the doubled marks
# '' and the double prime stay a bearing's seconds and are never inches. ONE inch
# token, ONE measurement-end rule and ONE monument-size exclusion serve every
# inch form (compound unit, foot-inch pair, unread-inch check).
#
# Token: the words, the abbreviation "in"/"in." (its period may already be
# stripped by call splitting) or the inch marks (" and the double prime).
_INCH_WORD = r"(?:inch(?:es)?\b|in\b\.?)"
_INCH_MARK = r"(?:\"|\u2033)"
_INCH_TOKEN = rf"(?:{_INCH_WORD}|{_INCH_MARK})"
# Measurement end: the end of the text, punctuation, "to", "thence", "along" or
# "more or less". A preposition ("100 feet in a northerly direction", "in the
# line of") is never inches; the abbreviation "in" elsewhere is left unread and
# caught by ``_UNREAD_INCH_AFTER``.
_MEASUREMENT_END_ALT = r"$|[.,;:)]|(?:to|thence|along|more\s+or\s+less)\b"
_MEASUREMENT_END = rf"(?=\s*(?:{_MEASUREMENT_END_ALT}))"
# Monument size: an inch value directly before a monument noun ("1\" iron pipe",
# "3/4\" rebar") sizes the monument; it is not a length component.
_MONUMENT_NOUN = (
    r"(?:(?:iron|steel|capped|concrete|wooden|wood|aluminum|brass)\s+)*"
    r"(?:pipe|pin|rod|rebar|bar|spike|nail|stake|hub|monument|post|marker|cap|tack)s?\b"
)
_NOT_MONUMENT_SIZE = rf"(?!\.?\s*{_MONUMENT_NOUN})"
_MONUMENT_SIZE_AFTER_FOOT = rf",?\s*{LENGTH_NUMBER}\s*{_INCH_TOKEN}(?=\.?\s*{_MONUMENT_NOUN})"
_INCH_UNIT = rf"(?:inch(?:es)?\b|in\b\.?{_MEASUREMENT_END}){_NOT_MONUMENT_SIZE}"
_INCH = re.compile(r"(?:inch(?:es)?|in\.?|\"|\u2033)", re.IGNORECASE)
# An inch mark ending the measurement directly after a word-unit feet length
# ("100 feet 6\" to a point") is that length's inches (``_length_runs``). After a
# bearing's minutes a mark stays seconds: only a word-unit feet length qualifies.
_INCH_MARK_UNIT = rf"{_INCH_MARK}{_MEASUREMENT_END}{_NOT_MONUMENT_SIZE}"
_INCH_MARK_GAP = re.compile(r"\s*,?\s*")
# A number with an inch-like token directly after the chosen course length that
# was not summed into it: the length is not dropped silently, the course fails
# closed (a monument size is not a length).
_UNREAD_INCH_AFTER = re.compile(
    rf"\.?(?:\s*,\s*|\s+)(?:and\s+)?{LENGTH_NUMBER}\s*(?:{_INCH_TOKEN}|'')"
    rf"{_NOT_MONUMENT_SIZE}",
    re.IGNORECASE,
)
# Without "and", a later component must be a clearly smaller unit to extend a run.
_DESCENDING_RATIO = 1.5
_UNSUPPORTED_AND_PAIR = re.compile(
    rf"{LENGTH_NUMBER}\s+[A-Za-z]+(?:\s+[A-Za-z]+)?\s+and\s+{LENGTH_NUMBER}\s+[A-Za-z]+",
    re.IGNORECASE,
)
# A foot-mark length, optionally followed by an inch mark ("100' 6\"") that is
# one measurement with it only where the measurement ends; elsewhere the inch
# mark may be a bearing's seconds and the course fails closed (``_FOOT_INCH``).
_FOOT_MARK_LENGTH = re.compile(
    rf"({LENGTH_NUMBER})\s*(?:'(?!')|′(?!′))"
    rf"(?:\s*,?\s*({LENGTH_NUMBER})\s*{_INCH_TOKEN}"
    rf"(?=\s*(?:(?:feet|foot|ft)\b|{_MEASUREMENT_END_ALT})))?"
    rf"(?=\s*(?:(?:feet|foot|ft)\b|{_MEASUREMENT_END_ALT}|{_MONUMENT_SIZE_AFTER_FOOT}))",
    re.IGNORECASE,
)
_FOOT_INCH = re.compile(
    rf"{LENGTH_NUMBER}\s*(?:'(?!')|′(?!′))\s*,?\s*{LENGTH_NUMBER}\s*"
    rf"{_INCH_MARK}{_NOT_MONUMENT_SIZE}"
)
# Degrees written without a sign ("N 45 30' 15\""): the marks are minutes and seconds.
# Also after any degree marker: degree(s), deg., d, a degree sign or a hyphen.
_UNSIGNED_DEGREES_BEFORE = re.compile(
    r"\b(?:north|south|N|S)\.?\s*\d{1,3}(?:\s*(?:degrees?|deg\b\.?|d\b|[°º˚])\s*|\s+|-)$",
    re.IGNORECASE,
)


class _LengthRun(NamedTuple):
    """One stated length (a compound counts once) with the role its context gives it."""

    start: int
    end: int
    components: tuple[tuple[str, str], ...]  # (value, unit) as written
    # course, total, partial, depth, dimension, tie, width, element, size, station, record
    role: str
    unsupported: bool = False  # holds a component that cannot be summed


class CourseLengthReading(NamedTuple):
    """The course length read from text, or every course length when ambiguous."""

    value: float
    unit: str
    ambiguous: tuple[str, ...] = ()


# A course wholly in inches ("N 45 E 12 inches", "100 in.", "12\"") is a length
# only as the first thing after the bearing and where the measurement ends: an
# object size ("an 8 inch oak"), a monument size ("1\" iron pipe") and the
# preposition "in" never match, and the mark " is read only here, never as seconds
# (the bearing has already ended).
_STANDALONE_INCH = re.compile(
    rf"\s*,?\s*(?:(?:a\s+)?distance\s+of\s+|for\s+)?({LENGTH_NUMBER})\s*"
    rf"(?:inch(?:es)?\b|in\b\.?|{_INCH_MARK}){_MEASUREMENT_END}{_NOT_MONUMENT_SIZE}",
    re.IGNORECASE,
)


def read_standalone_inch_length(after_bearing: str) -> float | None:
    """Return feet for a course stated wholly in inches at the start of ``after_bearing``.

    ``after_bearing`` is the text directly after the course bearing; None when it
    does not begin with such a length (or the length is zero).
    """
    inches = _STANDALONE_INCH.match(after_bearing)
    value = parse_number(inches.group(1)) / 12.0 if inches else 0.0
    return value if value > 0.0 else None


def _is_inch(token: str) -> bool:
    return bool(_INCH.fullmatch(token.strip()))


def _unit_key(token: str) -> str:
    return "inch" if _is_inch(token) else _singular_unit(token)


def _component_feet(value: str, token: str) -> float:
    if _is_inch(token):
        return parse_number(value) / 12.0
    return ConversionFactors.convert_to_feet(parse_number(value), normalize_unit_token(token))


def _compound_size(text: str, tokens: list[Match[str]], index: int) -> int:
    """Return how many tokens from ``index`` form one compound length.

    Components join with "and" (different units only: "100 feet and 50 feet",
    or pole/rod/perch equivalents, is two measurements, never a sum). Without
    "and", a run of descending units separated only by spaces is one measurement
    ("100 feet 6 inches", "2 rods 3 feet", "1 mile 20 feet"), as is a sub-unit
    pair (``_IMPLICIT_COMPOUND_PAIRS``, also after a comma). In "1 chain and 25
    links and 10 links" further links extend a run that already holds a larger
    unit. Ascending or equivalent adjacent units never join.
    """
    keep = 1
    for prev, cur in zip(tokens[index:], tokens[index + 1 :], strict=False):
        gap = text[prev.end() : cur.start()]
        if not (
            _COMPOUND_GAP.fullmatch(gap)
            and all(
                re.fullmatch(UNIT_TOKEN, unit, re.IGNORECASE) or _is_inch(unit)
                for unit in (prev.group(2), cur.group(2))
            )
        ):
            break
        pair = (_unit_key(prev.group(2)), _unit_key(cur.group(2)))
        joined_by_and = re.search(r"\band\b", gap, re.IGNORECASE)
        descending = (
            not joined_by_and
            and ("," not in gap or _is_inch(cur.group(2)))
            and _component_feet("1", prev.group(2))
            > _DESCENDING_RATIO * _component_feet("1", cur.group(2))
        )
        if not (
            pair in _IMPLICIT_COMPOUND_PAIRS
            or descending
            or (joined_by_and and not _same_unit_family(*pair))
            or (joined_by_and and keep >= 2 and pair == ("link", "link"))
        ):
            break
        keep += 1
    return keep


def _unsupported_and_pair(text: str, start: int) -> bool:
    """Return True for "<n> <word> and <n> <word>" at ``start`` that cannot be summed.

    A same-unit pair is two measurements (each read as a length); any other pair
    that did not form a compound has a component that is not a supported unit.
    """
    pair = _UNSUPPORTED_AND_PAIR.match(text, start)
    if not pair:
        return False
    units = re.findall(rf"{LENGTH_NUMBER}\s*({UNIT_TOKEN})\b", pair.group(0), re.IGNORECASE)
    return not (len(units) == 2 and _same_unit_family(*(_singular_unit(u) for u in units)))


def _length_role(text: str, start: int, end: int, *, first: bool, tie_from: int) -> str:
    """Return the role of the length spanning ``start``-``end`` from its context."""
    before = text[max(0, start - _ROLE_CONTEXT) : start]
    after = text[end : end + _ROLE_CONTEXT]
    if text.rfind("(", 0, start) > text.rfind(")", 0, start):
        return "record"
    if _TOTAL_BEFORE.search(before) or _TOTAL_AFTER.match(after):
        return "total"
    if start >= tie_from or TIE_BEFORE_PATTERN.search(before) or _DIRECTED_TIE_AFTER.match(after):
        return "tie"
    if not first and TIE_AFTER_PATTERN.match(after):
        return "tie"
    if _PARALLEL_AND_BEFORE.search(before) and _OFFSET_FROM_AFTER.match(after):
        return "tie"
    if _OFFSET_AFTER.match(after) and not _LENGTH_JUST_BEFORE.search(before):
        # An offset directly after another unjoined length is not told apart: both stay.
        return "tie"
    if _WIDTH_AFTER.match(after):
        return "width"
    if _ARTICLE_JUST_BEFORE.search(before) and _ADJECTIVE_WIDTH_AFTER.match(after):
        return "width"
    if _GRADE_DEPTH_AFTER.match(after) or (
        _MONUMENT_DEPTH_AFTER.match(after) and _MONUMENT_BEFORE.search(before)
    ):
        return "tie"
    dimension = _DIMENSION_AFTER.match(after)
    if dimension:
        course_capable = dimension.group("course") and not _ARTICLE_JUST_BEFORE.search(before)
        return "depth" if course_capable else "dimension"
    if _ELEMENT_BEFORE.search(before):
        return "element"
    if _STATION_BEFORE.search(before) and not (
        first and _AT_DISTANCE_OF_BEFORE.search(before) and not _MEASURED_FROM_AFTER.match(after)
    ):
        return "station"
    if _PARTIAL_BEFORE.search(before) or _PARTIAL_AFTER.match(after):
        return "partial"
    return "course"


def _tie_clause_start(text: str) -> int:
    clause = _TIE_CLAUSE.search(text)
    return clause.end() if clause else len(text) + 1


def _inch_mark_after_word_feet(text: str, tokens: list[Match[str]], mark: Match[str]) -> bool:
    """Return True when an inch-mark length directly follows a word-unit feet length.

    Fewer than 12 inches only; the mark is otherwise left unread (and the course
    fails closed on it).
    """
    if not tokens or parse_number(mark.group(1)) >= 12:
        return False
    previous = tokens[-1]
    return (
        previous.end() <= mark.start()
        and re.fullmatch(r"(?:feet|foot|ft)", previous.group(2), re.IGNORECASE) is not None
        and _INCH_MARK_GAP.fullmatch(text, previous.end(), mark.start()) is not None
    )


def _length_runs(text: str) -> list[_LengthRun]:
    """Group the unit-word lengths in ``text`` into stated lengths, each with its role."""
    tokens: list[Match[str]] = []
    for m in re.finditer(
        rf"({LENGTH_NUMBER})\s*({LENGTH_UNIT}|{_INCH_UNIT}|{_INCH_MARK_UNIT})",
        text,
        re.IGNORECASE,
    ):
        if is_foot_mark(m.group(2)):
            continue
        if re.fullmatch(_INCH_MARK, m.group(2)) and not _inch_mark_after_word_feet(text, tokens, m):
            continue
        tokens.append(m)
    tie_from = _tie_clause_start(text)
    runs: list[_LengthRun] = []
    index = 0
    while index < len(tokens):
        size = _compound_size(text, tokens, index)
        group = tokens[index : index + size]
        start, end = group[0].start(), group[-1].end()
        unsupported = bool(
            re.match(rf"\s+and\s+{LENGTH_NUMBER}\s+[A-Za-z]+", text[end:], re.IGNORECASE)
            if size >= 2
            else _unsupported_and_pair(text, start)
        )
        # Inches alone size an object ("a 1.5 inch iron pipe"); never a course length.
        # Inches directly before a larger unit ("6 inches 10 feet") are an ascending
        # compound that is never summed: it stays a course length, so the course
        # is ambiguous rather than silently dropping the inches.
        following = tokens[index + size] if index + size < len(tokens) else None
        ascending = following is not None and bool(
            _COMPOUND_GAP.fullmatch(text, end, following.start())
        )
        role = (
            "size"
            if _is_inch(group[0].group(2)) and not ascending
            else _length_role(text, start, end, first=not runs, tie_from=tie_from)
        )
        components = tuple((m.group(1), m.group(2)) for m in group)
        runs.append(_LengthRun(start, end, components, role, unsupported))
        index += size
    return runs


def _run_value(run: _LengthRun) -> tuple[float, str]:
    if len(run.components) == 1 and not _is_inch(run.components[0][1]):
        value, unit = run.components[0]
        return parse_number(value), normalize_unit_token(unit)
    return sum(_component_feet(value, unit) for value, unit in run.components), "feet"


def _select_course_length(text: str, runs: list[_LengthRun]) -> CourseLengthReading | None:
    """Return the one course length among ``runs``, an ambiguous reading, or None."""
    totals = [run for run in runs if run.role == "total"]
    candidates = (
        totals
        or [run for run in runs if run.role in ("course", "partial")]
        or [run for run in runs if run.role == "depth"]
    )
    if not candidates:
        return None
    ambiguous = (
        len({_run_value(run) for run in totals}) > 1
        if totals
        else len(candidates) > 1 or candidates[0].role == "partial"
    )
    if ambiguous:
        return CourseLengthReading(0.0, "feet", tuple(text[r.start : r.end] for r in candidates))
    if candidates[0].unsupported:
        return CourseLengthReading(0.0, "feet")
    return CourseLengthReading(*_run_value(candidates[0]))


def read_course_length(text: str) -> CourseLengthReading:
    """Read the one course length stated in ``text`` from the role of each length.

    Tie, width, parenthetical and station lengths are not the course length; a
    stated total is. The one remaining course length (a compound counts once) is
    the reading. Several remaining course lengths, or a partial length without a
    stated total, are ambiguous: the reading is 0.0 and ``ambiguous`` lists each
    as written, so none is chosen. A compound with a component that cannot be
    summed reads 0.0. Foot marks (') are read only when no unit-word length is
    the course length.
    """
    runs = _length_runs(text)
    reading = _select_course_length(text, runs)
    if reading is not None:
        return _fail_closed_on_unread_inches(text, runs, reading)
    tie_from = _tie_clause_start(text)
    runs = []
    read_spans: list[tuple[int, int]] = []
    for mark in _FOOT_MARK_LENGTH.finditer(text):
        if _UNSIGNED_DEGREES_BEFORE.search(text, 0, mark.start()):
            continue
        components: tuple[tuple[str, str], ...] = ((mark.group(1), "feet"),)
        if mark.group(2) is not None:
            if parse_number(mark.group(2)) >= 12:
                continue
            components += ((mark.group(2), "inches"),)
        role = _length_role(text, mark.start(), mark.end(), first=not runs, tie_from=tie_from)
        runs.append(_LengthRun(mark.start(), mark.end(), components, role))
        read_spans.append((mark.start(), mark.end()))
    unread = [
        pair.group(0)
        for pair in _FOOT_INCH.finditer(text)
        if (pair.start(), pair.end()) not in read_spans
        and not _UNSIGNED_DEGREES_BEFORE.search(text, 0, pair.start())
    ]
    if unread:
        return CourseLengthReading(0.0, "feet", tuple(unread))
    reading = _select_course_length(text, runs) or CourseLengthReading(0.0, "feet")
    return _fail_closed_on_unread_inches(text, runs, reading)


def _fail_closed_on_unread_inches(
    text: str, runs: list[_LengthRun], reading: CourseLengthReading
) -> CourseLengthReading:
    """Fail closed when an inch-like length directly after the course length was not read."""
    if reading.ambiguous or reading.value == 0.0:
        return reading
    for run in runs:
        if run.role not in ("course", "total", "depth"):
            continue
        unread = _UNREAD_INCH_AFTER.match(text, run.end)
        if unread:
            stated = text[run.start : run.end]
            return CourseLengthReading(0.0, "feet", (stated, unread.group(0).strip(" .")))
    return reading


def extract_distance(text: str) -> tuple[float, str]:
    """Extract the course distance value and unit from text.

    Args:
        text: Text containing distance (e.g., "125.26 feet" or "258 poles")

    Returns:
        Tuple of (distance_value, unit). (0.0, "feet") when no course length is
        stated, or when several are and none is chosen (``read_course_length``).
    """
    reading = read_course_length(text)
    return (reading.value, reading.unit)


def _is_lot_qualifier_except(text: str, match: re.Match[str]) -> bool:
    """Check if an EXCEPT match is a lot-qualifier rather than a structural exception.

    Lot qualifiers describe a portion of a lot being excluded from the lot
    reference itself (e.g. "except the South 43.65 feet of said Lot").
    They are NOT structural exception clauses that introduce a separately
    described parcel.

    Returns True if the EXCEPT is a lot qualifier and should be ignored
    as a split point.
    """
    # "LESS AND EXCEPT" and "EXCEPTING" are always structural
    matched_text = match.group(0)
    if re.search(r"LESS\s+AND", matched_text, re.IGNORECASE):
        return False
    if re.search(r"ING$", matched_text, re.IGNORECASE):
        return False

    # Look at the text following the EXCEPT keyword
    after = text[match.end() :]

    # Lot qualifier pattern: "except the [direction] [number] [unit] (of|in|thereof)"
    # Examples:
    #   "except the South 43.65 feet of said Lot"
    #   "except the North 50 feet of the Lot"
    #   "except the Easterly 25 feet thereof"
    #   "except the Westerly 10.5 feet in even width"
    lot_qualifier_pattern = re.compile(
        r"^\s+the\s+"
        r"(?:North|South|East|West)"
        r"(?:erly|wardly)?"
        rf"\s+{LENGTH_NUMBER}"
        r"\s+(?:feet|foot|ft|poles?|rods?|chains?|links?|varas?|meters?)"
        r"\s+(?:of\b|in\b|thereof\b)",
        re.IGNORECASE,
    )
    return bool(lot_qualifier_pattern.match(after))


def split_exception_clauses(text: str) -> list[tuple[str, bool]]:
    """Split text into main tract and exception/inclusion tracts.

    Args:
        text: Legal description text

    Returns:
        List of tuples (tract_text, is_exception)
        where is_exception=True for EXCEPT clauses, False for main/ALSO
    """
    splits: list[tuple[int, int, bool]] = []

    for match in re.finditer(r"\b(?:LESS\s+AND\s+)?EXCEPT(?:ING)?\b", text, re.IGNORECASE):
        if _is_lot_qualifier_except(text, match):
            continue
        splits.append((match.start(), match.end(), True))

    for match in re.finditer(r"(?:^|[;\n.])\s*(ALSO|INCLUDING)\b", text, re.IGNORECASE):
        splits.append((match.start(1), match.end(1), False))

    splits.sort(key=lambda item: item[0])

    if not splits:
        return [(text, False)]

    tracts = []

    first_split_pos = splits[0][0]
    if first_split_pos > 0:
        main_tract = text[:first_split_pos].strip()
        if main_tract:
            tracts.append((main_tract, False))

    for i, (_, end, is_exception) in enumerate(splits):
        tract_end = splits[i + 1][0] if i + 1 < len(splits) else len(text)
        tract_text = text[end:tract_end].strip()
        if tract_text:
            tracts.append((tract_text, is_exception))

    return tracts if tracts else [(text, False)]


# Relationship phrases whose "to"/"with" relates the course to an adjoiner or another
# course. They qualify the course; they are not its destination.
_QUALIFIER_PHRASE = re.compile(
    r"\b(?:(?:parallel|perpendicular|tangent|radial|adjacent|next|contiguous)\s+(?:to|with)"
    r"|at\s+(?:a\s+)?right\s+angles?\s+to)\b",
    re.IGNORECASE,
)


# The separator before the next course ("to a pin and thence ...", "to a pin, and
# running thence ..."): a trailing conjunction, never wording inside the destination.
_TRAILING_SEPARATOR = re.compile(
    r"(?:[\s,]+(?:and|&)(?:\s+(?:running|proceeding|continuing|extend(?:s|ing)))?)+[\s,]*$",
    re.IGNORECASE,
)


# Adjoiner wording that introduces what the course runs along: "along Main Street",
# "by and with the line of Lot 6", "with the line of ...", "binding on Main Street",
# "bounding on ...", "adjoining lands of ...", "following the creek". "by"/"with" only
# before a line or lands ("by the line of Smith", "by land now or formerly of Smith");
# other senses ("by deed", "with a radius of") are not adjoiners.
_LINE_OR_LANDS = r"(?=\s+(?:(?:the|said)\s+)?(?:lines?|lands?)\s+(?:of|now\s+or\s+formerly|n/f)\b)"
_ADJOINER_LEAD = re.compile(
    r"\b(?:binding\s+(?:on|upon|along|with)|bounding\s+(?:on|upon|along)|along"
    rf"|by\s+and\s+with|by{_LINE_OR_LANDS}|with{_LINE_OR_LANDS}|adjoining"
    r"|(?<!the\s)following(?=\s+(?:the|said|an?|lands?|lines?)\s))\b",
    re.IGNORECASE,
)
# "to" related to the word before it ("conveyed to Smith", "belonging to", "opposite
# to", "subject to"): never the destination "to".
_RELATED_TO_BEFORE = re.compile(
    r"\b(?:conveyed|granted|deeded|sold|transferred|devised|leased|belonging|belongs"
    r"|belonged|opposite|adjacent|adjoining|close|near|nearest|common|corner|similar|equal"
    r"|according|prior|subject|due|thereto)\s+$",
    re.IGNORECASE,
)
# Wording after the destination that ends the course clause: a later course, the area,
# or a deed clause ("containing 0.23 acres", "subject to", "being the same ...").
_COURSE_CLAUSE_END = re.compile(
    r"\b(?:thence"
    r"|containing\b(?=[^;]*?\b(?:acres?|square|sq\b|perches|hectares?)\b)"
    r"|(?:under\s+and\s+)?subject\s+to|being\s+(?:the\s+same|a\s+part|part|a\s+portion|known)"
    r"|together\s+with|(?:saving\s+and\s+)?excepting|reserving)\b",
    re.IGNORECASE,
)
# The fragment's own leading "thence" ("THENCE N 45 E", "and running thence along ...").
_LEADING_THENCE = re.compile(
    r"\W*(?:(?:and|then|running|continuing|proceeding)\s+)*thence\b", re.IGNORECASE
)
# A passing call ("passing a pipe at 50 feet"): a point passed on the line, ending at a
# comma, a semicolon, adjoiner wording, the destination or the rest of the course
# ("in all", "and continuing", "a total distance of").
_PASSING = re.compile(r"\bpassing\b", re.IGNORECASE)
# A ';'-separated piece that is only a passing call ("; passing a pipe at 30 feet").
_PASSING_PIECE = re.compile(r"\s*(?:and\s+)?passing\b", re.IGNORECASE)
# A ';'-separated piece opening with course wording: an adjoiner ("along ...") or a
# qualifier ("parallel to ..."). A witness or tie ("; a hickory bears ...") is not.
_COURSE_WORDING_PIECE = re.compile(r"\s*(?:and\s+)?(?:running\s+)?(?=\w)", re.IGNORECASE)
_PASSING_END = re.compile(
    r"[,;]|\b(?:in\s+all|and\s+continuing|(?:a\s+)?total\s+distance)\b", re.IGNORECASE
)
# Wording of the course's own length when it follows the destination ("to a 5/8\"
# rebar a distance of 100 feet", "to a pipe 100 feet, more or less").
_LENGTH_LEAD_BEFORE = re.compile(
    r"[\s,]*(?:\b(?:for\s+)?(?:(?:a|the)\s+)?(?:total\s+)?distance\s+of|\bfor)?\s*$",
    re.IGNORECASE,
)
# "and continuing said course": the course continued, not what it runs along.
_CONTINUING_COURSE = re.compile(
    r"[\s,]*\band\s+continuing\s+(?:on\s+)?(?:said|the\s+same|same|this)\s+course\b",
    re.IGNORECASE,
)
_LENGTH_TAIL_AFTER = re.compile(r"\s*,?\s*more\s+or\s+less\b", re.IGNORECASE)


def course_length_phrase_span(text: str, start: int, end: int) -> tuple[int, int]:
    """Widen the course length ``text[start:end]`` to its wording.

    The wording is the length with a leading "a distance of" / "for" and a trailing
    "more or less"; nothing else (a monument size before it stays).
    """
    lead = _LENGTH_LEAD_BEFORE.search(text, 0, start)
    tail = _LENGTH_TAIL_AFTER.match(text, end)
    return (lead.start() if lead else start, tail.end() if tail else end)


# Punctuation left before the clause end ("to a pin, thence", "beginning -- BEING").
_CLAUSE_TRAILER = re.compile(r"[\s,;\u2013\u2014-]+$")


class CourseClause(NamedTuple):
    """Verbatim along/to wording of one course, read from its clause spans."""

    along: str
    to: str
    passing: tuple[str, ...] = ()  # passing calls, verbatim
    course_end: int = 0  # end of the course part (the destination "to", or the clause end)
    clause_end: int = 0  # end of this course's clause (before a later "thence")
    # ';'-separated course wording (adjoiner or qualifier) after the destination:
    # it belongs to no field, so the course fails closed on it.
    unattached: tuple[str, ...] = ()


def _course_length_span(text: str) -> tuple[int, int] | None:
    """Span of the length ``read_course_length`` reads as the course length, if one."""
    reading = read_course_length(text)
    if reading.ambiguous or reading.value <= 0:
        return None
    runs = _length_runs(text)
    if _select_course_length(text, runs) is None:
        # Foot-mark lengths are read only when no unit-word length is the course length.
        tie_from = _tie_clause_start(text)
        runs = []
        for mark in _FOOT_MARK_LENGTH.finditer(text):
            if _UNSIGNED_DEGREES_BEFORE.search(text, 0, mark.start()):
                continue
            if mark.group(2) is not None and parse_number(mark.group(2)) >= 12:
                continue
            role = _length_role(text, mark.start(), mark.end(), first=not runs, tie_from=tie_from)
            runs.append(_LengthRun(mark.start(), mark.end(), (), role))
    totals = [run for run in runs if run.role == "total"]
    candidates = totals or [run for run in runs if run.role in ("course", "partial")]
    return (candidates[0].start, candidates[0].end) if candidates else None


def _is_destination_to(text: str, match: Match[str], qualifiers: list[tuple[int, int]]) -> bool:
    after = text[match.end() :].lstrip()
    if re.match(r"the\s+(?:left|right)(?!\s+of)\b", after, re.IGNORECASE):
        return False  # "a curve to the left"
    if any(start <= match.start() < end for start, end in qualifiers):
        return False  # "parallel to", "at right angles to"
    return not _RELATED_TO_BEFORE.search(text, 0, match.start())


def _enclosing_bracket(text: str, position: int, floor: int) -> tuple[int, int] | None:
    """Span of the bracketed group around ``position`` (``floor`` on), or None.

    An unclosed group runs to the end of ``text``; the span includes both brackets.
    """
    openers: list[int] = []
    for index in range(floor, position):
        if text[index] in "([":
            openers.append(index)
        elif text[index] in ")]" and openers:
            openers.pop()
    if not openers:
        return None
    depth = 0
    for index in range(position, len(text)):
        if text[index] in "([":
            depth += 1
        elif text[index] in ")]":
            if not depth:
                return (openers[0], index + 1)
            depth -= 1
    return (openers[0], len(text))


def _unmatched_close(text: str, start: int) -> int | None:
    """Index of the first closing bracket after ``start`` that closes an earlier bracket."""
    depth = 0
    for index in range(start, len(text)):
        if text[index] in "([":
            depth += 1
        elif text[index] in ")]":
            if not depth:
                return index
            depth -= 1
    return None


def _remove_spans(text: str, spans: list[tuple[int, int]]) -> str:
    """Return ``text`` with ``spans`` replaced by one space each (later spans first)."""
    merged: list[tuple[int, int]] = []
    for s, e in sorted(spans):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(e, merged[-1][1]))
        else:
            merged.append((s, e))
    for s, e in reversed(merged):
        text = text[:s].rstrip() + " " + text[e:].lstrip()
    return text


def _opens_with_course_wording(piece: str) -> bool:
    """Return True when ``piece`` opens with adjoiner or qualifier wording."""
    lead = _COURSE_WORDING_PIECE.match(piece)
    at = lead.end() if lead else 0
    return bool(_ADJOINER_LEAD.match(piece, at) or _QUALIFIER_PHRASE.match(piece, at))


def extract_course_clause(
    call_text: str, drop_spans: Sequence[tuple[int, int]] = ()
) -> CourseClause:
    """Read along/to of one course from the spans of its clause.

    The spans are computed once: the course clause runs from the fragment's leading
    "thence" to a later "thence"; the destination starts at the FIRST destination
    "to" ("to" in a qualifier, a curve direction or a relation such as "conveyed to"
    is not one) and runs verbatim to the end of the course clause ("containing ...
    acres", "subject to", "being the same ..."). ``along`` comes only from the
    course part before the destination: the wording after adjoiner wording ("along",
    "by and with", "binding on" ...) or, without one, a qualifier phrase ("parallel
    to"). Passing calls are returned verbatim, never dropped. The course's own
    length is removed from ``to`` (a monument size is kept).

    ``drop_spans`` are spans of ``call_text`` kept in notes, never in along/to (the
    record scan's record calls, measured course lengths and alternative-length
    parentheticals); they are left out of ``along`` and ``to`` wherever they sit, so
    the result does not depend on word order. A ';'-separated passing call after the
    destination is this course's passing call; ';'-separated adjoiner or qualifier
    wording there is ``unattached`` (the caller fails the course closed).
    A passing call in brackets is the whole bracketed group and ends at its closing
    bracket; unbracketed, it never runs past an unmatched closing bracket.
    """
    lead = _LEADING_THENCE.match(call_text)
    start = lead.end() if lead else 0
    later = re.search(r"\bthence\b", call_text[start:], re.IGNORECASE)
    clause_end = start + later.start() if later else len(call_text)
    clause = call_text[:clause_end]

    qualifiers = [m.span() for m in _QUALIFIER_PHRASE.finditer(clause)]
    destination = next(
        (
            m
            for m in re.finditer(r"\bto\b", clause, re.IGNORECASE)
            if m.start() >= start and _is_destination_to(clause, m, qualifiers)
        ),
        None,
    )
    course_end = destination.start() if destination else clause_end
    course = clause[:course_end]

    passing_spans: list[tuple[int, int]] = []
    passing_texts: list[str] = []
    for match in _PASSING.finditer(course, start):
        if any(s <= match.start() < e for s, e in passing_spans):
            continue
        group = _enclosing_bracket(course, match.start(), start)
        if group is not None:
            closed = course[group[1] - 1] in ")]"
            inner = course[group[0] + 1 : group[1] - 1 if closed else group[1]]
            passing_spans.append(group)
            passing_texts.append(inner.strip(" ,;."))
            continue
        ends = [m.start() for m in (_PASSING_END.search(course, match.end()),) if m]
        ends += [m.start() for m in (_ADJOINER_LEAD.search(course, match.end()),) if m]
        close = _unmatched_close(course, match.end())
        ends += [close] if close is not None else []
        stop = min(ends, default=len(course))
        passing_spans.append((match.start(), stop))
        passing_texts.append(course[match.start() : stop].strip(" ,;."))
    passing = tuple(passing_texts)
    dropped = [(s, min(e, course_end)) for s, e in drop_spans if start <= s < course_end]

    along = ""
    lead_word = _ADJOINER_LEAD.search(course, start)
    if lead_word:
        removed = [span for span in passing_spans + dropped if span[0] >= lead_word.end()]
        removed += [m.span() for m in _CONTINUING_COURSE.finditer(course, lead_word.end())]
        segment = _remove_spans(course, removed)
        segment = segment[lead_word.end() :].strip()
        if destination is None:
            segment = _before_clause_delimiter(segment)
        along = segment.strip(" ,;.")
    else:
        along = _qualifier_wording(_remove_spans(course, passing_spans + dropped))

    to = ""
    unattached: tuple[str, ...] = ()
    if destination is not None:
        tail_start = destination.end()
        end = _COURSE_CLAUSE_END.search(clause, tail_start)
        tail_end = end.start() if end else clause_end
        tail_end = tail_start + len(_before_clause_delimiter(clause[tail_start:tail_end]))
        # Record calls, measured groups and alternative lengths after the destination
        # are kept in notes (``drop_spans``): never part of ``to``.
        cuts = [
            (max(s, tail_start) - tail_start, min(e, tail_end) - tail_start)
            for s, e in drop_spans
            if s < tail_end and e > tail_start
        ]
        reading = clause
        for s, e in drop_spans:
            reading = reading[:s] + " " * (min(e, len(reading)) - s) + reading[e:]
        span = _course_length_span(reading)
        if span is not None and tail_start <= span[0] and span[1] <= tail_end:
            # Only the course's own length (with "a distance of" / "more or less").
            cut_start, cut_end = course_length_phrase_span(reading[:tail_end], *span)
            cuts.append((max(cut_start, tail_start) - tail_start, cut_end - tail_start))
        tail = _remove_spans(clause[tail_start:tail_end], cuts)
        to = _TRAILING_SEPARATOR.sub("", _CLAUSE_TRAILER.sub("", tail.strip()))
        # "to a pin; passing a monument at 30 feet": a ';'-separated passing call
        # after the destination belongs to this course; kept verbatim, never dropped.
        # Course wording there ("; along a line 10 feet from ...") cannot be
        # attached: it is returned so the course fails closed.
        # Wording in ``drop_spans`` there is blanked: it is already in notes.
        stop = end.start() if end else clause_end
        semicolons = [i + 1 for i in range(tail_end, stop) if reading[i] == ";"]
        piece_ends = [i - 1 for i in semicolons[1:]] + [stop] * bool(semicolons)
        for piece_start, piece_end in zip(semicolons, piece_ends, strict=True):
            piece = reading[piece_start:piece_end]
            kept = _before_clause_delimiter(piece)
            wording = clause[piece_start : piece_start + len(kept)].strip(" ,;.")
            if _PASSING_PIECE.match(piece):
                passing += (wording,)
            elif _opens_with_course_wording(piece):
                unattached += (wording,)

    return CourseClause(along, to, passing, course_end, clause_end, unattached)


def extract_along_to_fields(call_text: str) -> tuple[str, str]:
    """Extract along and to fields from a call description.

    Qualifier phrases ("parallel to", "at right angles to", "tangent to" ...) are
    kept verbatim in ``along`` and never supply ``to``; ``to`` comes only from the
    destination "to" ("to a pin", "to the point of beginning"). See
    ``extract_course_clause``.

    Args:
        call_text: Single call text

    Returns:
        Tuple of (along, to) descriptions
    """
    clause = extract_course_clause(call_text)
    return (clause.along, clause.to)


def _qualifier_wording(text: str) -> str:
    """Return the verbatim text from the first qualifier phrase on, trimmed at a clause end."""
    match = _QUALIFIER_PHRASE.search(text)
    if match is None:
        return ""
    wording = _before_clause_delimiter(text[match.start() :])
    # "a distance of N feet" is the course's own length, not part of the qualifier.
    wording = re.split(r"\s+(?:a\s+)?distance\s+of\b", wording, maxsplit=1, flags=re.I)[0]
    return wording.strip(" ,;.")


def extract_basis_of_bearing(text: str) -> str | None:
    """Extract basis of bearing from legal description text.

    Args:
        text: Legal description text

    Returns:
        Basis of bearing string or None if not found
    """
    patterns = [
        (r"basis\s+of\s+bearings?\s*:\s*(.+?)(?:\.|$)", re.IGNORECASE),
        (r"bearings?\s+(?:are\s+)?based\s+on\s+(.+?)(?:\.|$)", re.IGNORECASE),
        (r"bearings?\s+referenced\s+to\s+(.+?)(?:\.|$)", re.IGNORECASE),
        (
            r"bearings?\s+(?:herein\s+)?are\s+(magnetic|assumed|true\s+north|grid\s+north)(?:\b.*?)(?:\.|$)",
            re.IGNORECASE,
        ),
    ]

    for pattern, flags in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return match.group(1).strip()

    return None


def extract_surveyor_certification(text: str) -> str | None:
    """Extract surveyor certification from legal description text.

    Args:
        text: Legal description text

    Returns:
        Surveyor certification string or None if not found
    """
    patterns = [
        (
            r"(?:That\s+I,\s+)(.+?)(?:,\s+(?:a\s+)?(?:Licensed|Registered|Professional))",
            re.IGNORECASE | re.DOTALL,
        ),
        (r"(?:Certified\s+by:\s*)(.+?)(?:\.|$)", re.IGNORECASE),
        (r"(?:Surveyed\s+by\s+)(.+?)(?:\.|$)", re.IGNORECASE),
        (r"(I\s+hereby\s+certify\s+.+?)(?:\.|$)", re.IGNORECASE),
    ]

    for pattern, flags in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return match.group(1).strip()

    return None


def extract_prior_conveyance(text: str) -> str | None:
    """Extract prior conveyance reference from legal description text.

    Args:
        text: Legal description text

    Returns:
        Prior conveyance string or None if not found
    """
    patterns = [
        (r"(BEING\s+the\s+same\s+premises\s+.+?)(?:\.|$)", re.IGNORECASE),
        (
            r"((?:Deed|Official\s+Records)\s+Book\s+\d+.*?(?:Page\s+\d+)?)(?:\b.*?)(?:\.|$)",
            re.IGNORECASE,
        ),
        (r"(Instrument\s+Number\s+\d+.+?)(?:\.|$)", re.IGNORECASE),
    ]

    for pattern, flags in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return match.group(1).strip()

    return None


def extract_deed_clauses(text: str) -> list[DeedClause]:
    """Extract deed clauses (reservations, subject-to, together-with).

    These are metadata clauses that don't change the boundary geometry.

    Args:
        text: Legal description text

    Returns:
        List of DeedClause objects
    """
    from mp_models import DeedClause

    clauses: list[DeedClause] = []
    ClauseType = Literal["reservation", "subject_to", "together_with"]

    patterns: list[tuple[str, ClauseType]] = [
        (r"(RESERVING\b.*?)(?=\.\s+[A-Z]|\.\s*$|$)", "reservation"),
        (r"(SUBJECT\s+TO\b.*?)(?=\.\s+[A-Z]|\.\s*$|$)", "subject_to"),
        (r"(TOGETHER\s+WITH\b.*?)(?=\.\s+[A-Z]|\.\s*$|$)", "together_with"),
    ]

    for pattern, clause_type in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE | re.DOTALL):
            clause_text = match.group(1).strip().rstrip(".")
            if clause_text:
                clauses.append(DeedClause(clause_type=clause_type, text=clause_text))

    return clauses


def extract_subdivision_reference(text: str) -> SubdivisionReference | None:
    """Extract subdivision lot/block reference from deed text.

    Args:
        text: Legal description text

    Returns:
        SubdivisionReference or None if no subdivision reference found
    """
    from mp_models import SubdivisionReference

    lot = None
    block = None
    subdivision_name = None
    plat_book = None
    plat_page = None

    lot_match = re.search(r"\bLot\s+(\w+)", text, re.IGNORECASE)
    if lot_match:
        lot = lot_match.group(1)

    block_match = re.search(r"\bBlock\s+(\w+)", text, re.IGNORECASE)
    if block_match:
        block = block_match.group(1)

    # Subdivision name: typically in ALL CAPS after Lot/Block
    name_match = re.search(
        r"(?:Block\s+\w+|Lot\s+\w+),?\s+([A-Z][A-Z\s]+(?:ESTATES?|SUBDIVISION|ADDITION|HEIGHTS?|HILLS?|PARK|PLACE|MANOR|ACRES|VILLAGE|LANDING|TERRACE|GARDENS?)?)\b",
        text,
    )
    if name_match:
        subdivision_name = name_match.group(1).strip()

    plat_match = re.search(r"Plat\s+Book\s+(\d+),?\s*Page\s+(\d+)", text, re.IGNORECASE)
    if plat_match:
        plat_book = plat_match.group(1)
        plat_page = plat_match.group(2)

    if any([lot, block, subdivision_name, plat_book]):
        return SubdivisionReference(
            lot=lot,
            block=block,
            subdivision_name=subdivision_name,
            plat_book=plat_book,
            plat_page=plat_page,
        )

    return None


def infer_distance_unit(text: str, state: str | None = None, year: int | None = None) -> str | None:
    """Infer the primary distance unit from context.

    Advisory only -- returns a suggestion, caller decides whether to apply it.

    Args:
        text: Legal description text
        state: US state abbreviation (e.g., "TX", "LA")
        year: Year of the deed

    Returns:
        Suggested unit string or None if no inference
    """
    text_lower = text.lower()

    if "varas" in text_lower or "vara" in text_lower:
        return "varas"
    if "chains and links" in text_lower:
        return "chains"
    if "arpents" in text_lower or "arpent" in text_lower:
        return "arpents"

    if state == "TX" and year is not None and year < 1900:
        return "varas"
    if state == "LA":
        return "arpents"

    new_england = {"MA", "CT", "ME", "NH", "VT", "RI"}
    if state in new_england and year is not None and year < 1850:
        return "rods"

    return None


def extract_witness_trees(text: str) -> list[str]:
    """Extract witness tree / reference mark descriptions.

    Historical surveyors recorded trees near corners with species,
    diameter, bearing and distance. Stored verbatim per architecture
    principle #3 (preserve deed language).

    Args:
        text: Legal description text

    Returns:
        List of verbatim witness tree descriptions
    """
    trees: list[str] = []

    tree_pattern = re.compile(
        r"((?:a\s+)?(?:\w+\s+)?(?:oak|hickory|elm|pine|walnut|sycamore|maple|beech|"
        r"poplar|cedar|ash|birch|chestnut|cottonwood|willow|cypress)"
        r"[^;.]*?\bbears?\b[^;.]*?(?:dist(?:ant)?|links?|feet|ft)[^;.]*)",
        re.IGNORECASE,
    )

    for match in tree_pattern.finditer(text):
        trees.append(match.group(1).strip())

    return trees


def extract_coordinate_system(text: str) -> tuple[str | None, str | None]:
    """Extract State Plane or other coordinate system reference.

    Advisory only -- no grid correction computation.

    Args:
        text: Legal description text

    Returns:
        Tuple of (coordinate_system, fips_code) -- both may be None
    """
    coordinate_system = None
    fips_code = None

    spcs_match = re.search(
        r"(State\s+Plane\s+Coordinate\s+System[^.;]*?)(?:\.|;|$)",
        text,
        re.IGNORECASE,
    )
    if spcs_match:
        coordinate_system = spcs_match.group(1).strip()

    fips_match = re.search(r"\bFIPS\s+(?:Zone\s+)?(\d{4})\b", text, re.IGNORECASE)
    if fips_match:
        fips_code = fips_match.group(1)

    return (coordinate_system, fips_code)


# ----- Compiled patterns for meander and indefinite call detection -----

WATER_BODY_KEYWORDS = re.compile(
    r"\b(?:creek|stream|river|brook|run|branch|kill|pond|lake|"
    r"shore|bank|thalweg|thread)\b",
    re.IGNORECASE,
)

MEANDER_PATTERNS = re.compile(
    r"\b(?:meander(?:ing)?|meander\s+line)\b",
    re.IGNORECASE,
)

WATER_PREPOSITION_PATTERN = re.compile(
    r"\b(?:along|with|up|down)\s+(?:the\s+)?",
    re.IGNORECASE,
)

INDEFINITE_PATTERNS = re.compile(
    r"\b(?:as\s+it\s+now\s+runs|top\s+of\s+the|"
    r"old\s+ford|down\s+the|up\s+the|"
    r"by\s+the\s+road|along\s+the\s+road)\b",
    re.IGNORECASE,
)

CARDINAL_ONLY_PATTERN = re.compile(
    r"^(?:north|south|east|west|northeast|northwest|southeast|southwest|NE|NW|SE|SW)(?:erly|wardly)?$",
    re.IGNORECASE,
)


def detect_meander(text: str) -> bool:
    """Detect if call text references a water boundary (meander).

    Args:
        text: Call text to check

    Returns:
        True if text references a water boundary
    """
    if not text:
        return False

    if MEANDER_PATTERNS.search(text):
        return True

    if WATER_PREPOSITION_PATTERN.search(text) and WATER_BODY_KEYWORDS.search(text):
        return True

    return False


def is_indefinite_call(direction_text: str, has_bearing: bool) -> bool:
    """Detect if a call has vague/indefinite direction.

    Args:
        direction_text: The direction text of the call
        has_bearing: Whether a precise quadrant bearing was parsed

    Returns:
        True if the call is indefinite (no precise bearing)
    """
    if not direction_text or has_bearing:
        return False

    if CARDINAL_ONLY_PATTERN.match(direction_text.strip()):
        return True

    if INDEFINITE_PATTERNS.search(direction_text):
        return True

    return False


# ----- Strip exception detection and removal -----

# Canonical direction abbreviation → full name mapping.
_DIRECTION_ABBREV: dict[str, str] = {
    "N": "North",
    "S": "South",
    "E": "East",
    "W": "West",
}

# Full direction names, with an -erly/-wardly suffix ("the westerly 10 feet"), or
# their abbreviations (case-insensitive group).
_DIRECTION_GROUP = r"(?P<dir>(?:North|South|East|West)(?:erly|wardly)?|N|S|E|W)"

# Width: any shared length number (decimal, comma-grouped, fraction or mixed).
_WIDTH_GROUP = rf"(?P<width>{LENGTH_NUMBER})"

# Unit: feet or ft.
_UNIT_GROUP = r"(?:feet|ft)"

# The whole lead of a strip, kept verbatim with it: "EXCEPT", "and except",
# "LESS AND EXCEPT", "SAVE AND EXCEPT", "EXCEPTING AND RESERVING", "EXCEPTING
# THEREFROM", "excepting thereout and therefrom".
_STRIP_LEAD = (
    r"(?:(?:less|save)\s+and\s+|and\s+)?except(?:ing)?"
    r"(?:\s+and\s+reserving)?(?:\s+(?:thereout\s+and\s+)?therefrom)?"
)
# What the strip is taken from: "thereof", "of said lot", "of the above described
# premises", "of the herein described tract".
_STRIP_OBJECT = (
    r"(?:\s+(?:thereof|of\s+(?:(?:said|the|this)\s+)?"
    r"(?:(?:above|herein(?:above|before)?)[\s-]+described\s+)?"
    r"(?:lot|premises|tract|parcel|land|lands|property)))?"
)
# The strip's own trailing purpose: "deeded for roadway", "for road purposes",
# "conveyed for ...", "taken for ...", "; conveyed to the County".
_PURPOSE_TAIL = (
    r"(?:(?:\s*[,;]\s*|\s+)(?P<purpose>"
    r"(?:heretofore\s+)?(?:taken|deeded|conveyed|used|reserved|dedicated|granted)"
    r"\s+(?:for|to)\s+[^.;,]+?"
    r"|for\s+[^.;,]+?\s+purposes))?"
)
# A strip ends its clause: more wording ("of said Lot in even width ...") makes it
# part of a longer exception, which is not read as a strip.
_STRIP_END = r"(?=\s*(?:[.;,]|and\b|$))[.\s]*"


class _StripException(TypedDict):
    direction: str
    width_ft: float
    purpose: str | None
    original_text: str


# Each pattern is a compiled regex that captures: direction, width, and an
# optional trailing purpose clause.  The patterns are tried in order; each
# match produces one _StripException dict.
_STRIP_PATTERNS: list[re.Pattern[str]] = [
    # "except the East 20 feet [deeded for roadway]"
    # "except the South 30 feet thereof", "SAVE AND EXCEPT the westerly 10 feet thereof"
    # "LESS AND EXCEPT the North 10 feet of said lot conveyed for road purposes"
    # "EXCEPTING THEREFROM the Northerly 10 feet of the above described premises ..."
    re.compile(
        _STRIP_LEAD
        + r"\s+(?:the\s+)"
        + _DIRECTION_GROUP
        + r"\s+"
        + _WIDTH_GROUP
        + r"\s+"
        + _UNIT_GROUP
        + _STRIP_OBJECT
        + _PURPOSE_TAIL
        + _STRIP_END,
        re.IGNORECASE,
    ),
    # "Subject to an Easement for Private Road Purposes over the West 30 Feet thereof"
    re.compile(
        r"subject\s+to\s+(?:an?\s+)?(?P<purpose>[^.]*?)"
        + r"\s+over\s+(?:the\s+)"
        + _DIRECTION_GROUP
        + r"\s+"
        + _WIDTH_GROUP
        + r"\s+"
        + _UNIT_GROUP
        + r"(?:\s+thereof)?"
        + _STRIP_END,
        re.IGNORECASE,
    ),
]

# Pattern to detect a metes-and-bounds traverse inside an exception clause.
# If an EXCEPT clause contains "THENCE" or a quadrant bearing like "S 45 degrees",
# it is a geometric exception (not a simple strip), and should NOT be removed.
_METES_INDICATOR = re.compile(
    r"\bthence\b|"
    r"\b[NS]\s+\d+\s+degree",
    re.IGNORECASE,
)
# The end of a sentence: a strip's clause never continues past it.
_SENTENCE_BREAK = re.compile(r"\.\s")


def _normalize_direction(raw: str) -> str:
    """Normalize a direction token to its full canonical name (title case).

    >>> _normalize_direction("E")
    'East'
    >>> _normalize_direction("south")
    'South'
    >>> _normalize_direction("westerly")
    'West'
    """
    upper = raw.upper().strip()
    if upper in _DIRECTION_ABBREV:
        return _DIRECTION_ABBREV[upper]
    return re.sub(r"(?:erly|wardly)$", "", raw.strip(), flags=re.IGNORECASE).capitalize()


def _clean_purpose(raw: str | None) -> str | None:
    """Clean and normalize the purpose string, or return None."""
    if raw is None:
        return None
    cleaned = re.sub(r"^thereof\s+", "", raw.strip().rstrip("."), flags=re.IGNORECASE)
    if not cleaned or cleaned.lower() == "thereof":
        return None
    # Collapse "deeded for roadway" → "roadway"
    deeded_match = re.match(r"deeded\s+for\s+(\S+)", cleaned, re.IGNORECASE)
    if deeded_match:
        return deeded_match.group(1).lower()
    return cleaned


def strip_exception_spans(text: str) -> list[tuple[int, int, _StripException]]:
    """Return each uniform-width strip with its span, in text order.

    The span covers the strip's wording ("except the East 20 feet deeded for
    roadway"), not the clause punctuation after it. See ``detect_strip_exceptions``.
    """
    if not text:
        return []

    results: list[tuple[int, int, _StripException]] = []

    for pattern in _STRIP_PATTERNS:
        for match in pattern.finditer(text):
            span = (match.start(), match.end())
            # Avoid duplicate matches from overlapping patterns
            if any(start <= span[0] < end or start < span[1] <= end for start, end, _ in results):
                continue

            original = match.group(0).strip().rstrip(".")

            # Guard: a THENCE or quadrant bearing inside the strip's own clause makes
            # it a geometric exception, not a simple strip. A later sentence (the
            # next tract, a following description) is not part of the clause.
            clause = match.group(0)
            if not clause.rstrip().endswith("."):
                following = text[match.end() : match.end() + 200]
                sentence_end = _SENTENCE_BREAK.search(following)
                clause += following[: sentence_end.start()] if sentence_end else following
            if _METES_INDICATOR.search(clause):
                continue

            direction_raw = match.group("dir")
            width = parse_number(match.group("width"))

            # Extract purpose -- not all patterns define this named group
            purpose_raw = None
            if "purpose" in pattern.groupindex:
                purpose_raw = match.group("purpose")

            results.append(
                (
                    match.start(),
                    match.start() + len(match.group(0).rstrip(". \t\n\r")),
                    _StripException(
                        direction=_normalize_direction(direction_raw),
                        width_ft=width,
                        purpose=_clean_purpose(purpose_raw),
                        original_text=original,
                    ),
                )
            )

    return sorted(results, key=lambda item: item[0])


def detect_strip_exceptions(text: str) -> list[_StripException]:
    """Detect uniform-width strip exceptions in legal description text.

    Strip exceptions are area deductions like "except the East 20 feet
    deeded for roadway" that describe a uniform strip removed from one side
    of a parcel.  They are NOT traverse calls and should not produce DeedCall
    objects.

    Args:
        text: Legal description text (may be full or partial)

    Returns:
        List of dicts, each with:
            direction:     Canonical direction name (e.g., "East")
            width_ft:      Width in feet
            purpose:       Purpose string or None
            original_text: Verbatim matched text from the input
    """
    return [strip for _, _, strip in strip_exception_spans(text)]


def remove_strip_exceptions(text: str) -> str:
    """Remove strip exception text from a legal description.

    Strips detected by ``detect_strip_exceptions()`` are removed from the
    input text.  Exception clauses that contain metes-and-bounds calls
    (geometric exceptions) are preserved.

    Args:
        text: Legal description text

    Returns:
        Cleaned text with strip exception phrases removed
    """
    if not text:
        return ""

    strips = detect_strip_exceptions(text)
    if not strips:
        return text

    result = text
    for strip in strips:
        original = strip["original_text"]
        # Remove the matched text.  Also remove leading punctuation/whitespace
        # (comma, semicolon, period) that attached to the strip.
        # Build a pattern that matches optional leading punct + the literal text.
        escaped = re.escape(original)
        # Allow for trailing period or whitespace that wasn't captured
        removal_pattern = re.compile(
            r"[,;\s]*" + escaped + r"[.\s]*",
            re.IGNORECASE,
        )
        result = removal_pattern.sub(" ", result, count=1)

    # Clean up any trailing/leading whitespace artifacts
    result = re.sub(r"\s{2,}", " ", result).strip()
    return result
