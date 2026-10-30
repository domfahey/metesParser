"""Text parsing utilities for normalizing legal descriptions.

Handles cleaning up OCR errors, standardizing DMS notation, merging line breaks, etc.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass
from re import Match
from typing import TYPE_CHECKING, Callable, Literal, TypedDict

from .models import ConversionFactors

if TYPE_CHECKING:
    from .models import DeedClause, SubdivisionReference

# Regex fragment for numbers with optional comma grouping (e.g., "1,200" or "3,500.00")
_COMMA_NUMBER = r"\d[\d,]*(?:\.\d+)?"

# Sentence-boundary markers where the legal description ends and post-description
# metadata begins.  The pattern requires ". " before the keyword so that phrases
# embedded *within* a call (e.g., "subject to easement rights") are not matched.
_METADATA_BOUNDARY = re.compile(
    r"\.\s+(?:"
    r"THE ABOVE DESCRIBED"
    r"|BEING (?:the same|all that|lot|part)"
    r"|CONTAINING"
    r"|SUBJECT TO"
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

_CLAUSE_ABBREVIATIONS = {"ave", "blvd", "dr", "ft", "in", "no", "rd", "st"}


def _before_clause_delimiter(text: str) -> str:
    """Trim a call at sentence punctuation without splitting decimals or abbreviations."""
    acronym_periods = [match.span() for match in re.finditer(r"\b[A-Za-z](?:\.[A-Za-z])+\.", text)]
    for match in re.finditer(r";|\.(?!\d)", text):
        if match.group() == ".":
            prefix = text[: match.start()]
            word = re.search(r"([A-Za-z]+)$", prefix)
            if word and word.group(1).lower() in _CLAUSE_ABBREVIATIONS:
                continue
            if any(start <= match.start() < end for start, end in acronym_periods):
                continue
        return text[: match.start()]
    return text


def parse_comma_number(s: str) -> float:
    """Convert a numeric string with optional comma grouping to float.

    Examples: "1,200" -> 1200.0, "3,500.00" -> 3500.0, "42" -> 42.0
    """
    return float(s.replace(",", ""))


# Without "and", only these (larger, smaller) unit pairs form a compound
# distance ("2 chains 20 links"). Equivalent units (pole/rod/perch) and
# unrelated adjacent measurements ("150 feet, 3 rods north of ...") never sum.
_IMPLICIT_COMPOUND_PAIRS = {
    ("chain", "link"),
    ("pole", "link"),
    ("rod", "link"),
    ("perch", "link"),
}


def _singular_unit(unit: str) -> str:
    unit = " ".join(unit.lower().split())
    return unit.removesuffix("es") if unit.endswith("ches") else unit.removesuffix("s")


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
# Enumerator styles: "(1)", "1)", "1." and "First,". Numbers are read from group 1.
_ORDINAL_ENUMERATOR = re.compile(rf"\b({'|'.join(_ORDINAL_WORDS)})\b,?", re.IGNORECASE)
_ENUMERATOR_STYLES = (
    re.compile(r"\((\d{1,3})\)"),
    re.compile(r"(?<![\w.(])(\d{1,3})\)"),
    re.compile(r"(?<![\w.(])(\d{1,3})\.(?=\s)"),
    _ORDINAL_ENUMERATOR,
)

# The one course-list header grammar, shared by header removal and enumeration
# detection:
#   THENCE [by|along|with|running|continuing <qualifier>] the following
#   [N | word | (N) | word (N)] courses|calls|lines [and distances]
#   [along|with|by ... <qualifier>] [, to wit | viz | namely] [: ; , .]
# Qualifiers are bounded and never cross ';' or ':'. A trailing qualifier holds
# digits only when an explicit ':' / 'to wit' / 'viz' ends it, so a course
# ("the following course North 10 degrees East 100 feet") is never a header.
_HEADER_QUALIFIER = r"(?:(?:by|along|with|running|continuing)\b[^;:]{0,200}?[\s,]+)?"
_HEADER_CORE = (
    r"the\s+following(?:\s+(?P<count>\d{1,3}|[a-z]+))?(?:\s+\((?P<count_paren>\d{1,3})\))?"
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
    item_starts: frozenset[int]
    list_starts: frozenset[int]
    has_numbered_markers: bool


def _enumerator_number(match: Match[str]) -> int:
    token = match.group(1)
    return int(token) if token.isdigit() else _ORDINAL_WORDS[token.lower()]


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
    more, so prose such as "THENCE first North ..." keeps its wording.
    """
    thence_starts = [m.start() for m in _THENCE.finditer(text)]
    headers = _course_list_headers(text, thence_starts)
    header_ends = [header.core_end for header in headers]
    styles = [list(style.finditer(text)) for style in _ENUMERATOR_STYLES]
    ordinal_style = len(styles) - 1
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
                if ordinal and len(sequence) < 2:
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


def _count_mismatches(
    lists: list[CourseList], headers: list[CourseListHeader]
) -> list[tuple[int, int]]:
    """(declared, found) for each counted header its enumerated courses do not satisfy.

    A header opening a list must match its length. A header inside a deed-numbered
    list ("...; thence along X, the following two courses; thence (4) ...") needs at
    least that many enumerated courses after it. A counted header with no
    enumeration at all is reported with 0 found, never silently accepted.
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
            found = 0
        if found != header.declared:
            mismatches.append((header.declared, found))
    return mismatches


def _is_inline(text: str, match: Match[str]) -> bool:
    position = match.start()
    while position > 0 and text[position - 1] in " \t":
        position -= 1
    return position > 0 and text[position - 1] != "\n"


def analyze_course_lists(text: str) -> CourseListAnalysis:
    """Detect course-list headers and enumerations once for a tract's text."""
    lists, headers = _course_enumerations(text)
    mismatches = _count_mismatches(lists, headers)

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
        mismatches=tuple(mismatches),
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


class TextParser:
    """Parse and normalize legal description text."""

    class _AreaStatement(TypedDict):
        value_sq_ft: float
        unit: str
        approximate: bool

    @classmethod
    def extract_area_statement(cls, text: str) -> _AreaStatement | None:
        """Extract the first stated area statement from legal text.

        Returns a dict with:
            value_sq_ft: numeric area in square feet
            unit: original unit label ("sq_ft" or "acres")
            approximate: whether wording indicates approximation

        If no parseable area statement exists, returns None.
        """
        if not isinstance(text, str):
            return None

        normalized_text = text.lower()
        if not normalized_text:
            return None

        area_pattern = re.compile(
            r"(?:(?:(?:approximately|approx\.?|~)\s+)?)"
            r"(?P<value>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)"
            r"\s*(?P<unit>sq\.?\s*ft\.?|square\s+feet?|acres?)",
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
                re.search(
                    r"\b(?:parent|larger|original)\s+(?:tract|parcel|lot)\b", clause_prefix
                )
            )

        standalone = re.fullmatch(
            r"\s*(?:(?:approximately|approx\.?|~)\s+)?"
            r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*(?:sq\.?\s*ft\.?|square\s+feet?|acres?)"
            r"(?:\s+more\s+or\s+less)?\s*[.]?\s*",
            normalized_text,
            re.IGNORECASE,
        )
        parcel_matches = [
            match
            for match in matches
            if re.search(r"\b(?:containing|contains|comprising|consisting\s+of)\b|\barea\s*:\s*$", normalized_text[max(0, match.start() - 55) : match.start()])
            and not re.search(r"\b(?:parent|larger|original)\s+tract\b", normalized_text[match.start() : match.end() + 45])
            and not is_parent_area_context(match)
        ]
        if not parcel_matches and not standalone:
            return None

        for match in (parcel_matches or matches[:1]):
            unit = match.group("unit").replace(" ", "")
            value = float(match.group("value").replace(",", ""))

            if "acre" in unit:
                value_sq_ft = value * ConversionFactors.ACRE_TO_SQ_FEET
                unit_key = "acres"
            else:
                value_sq_ft = value
                unit_key = "sq_ft"

            prefix = normalized_text[max(0, match.start() - 45) : match.end() + 45]
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

    @classmethod
    def extract_plss_metadata(cls, text: str) -> dict[str, str | None]:
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

    @classmethod
    def normalize_dms_symbols(cls, text: str) -> str:
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

    @classmethod
    def merge_line_wrapped_calls(cls, text: str) -> str:
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

            if re.match(
                r"^(?:(?:THENCE|BEGINNING|FROM|POB|POINT)\b|\(\d+\)|\d+[.)])(?:\s+|$)",
                stripped,
                re.IGNORECASE,
            ):
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

    @classmethod
    def standardize_cardinal_directions(cls, text: str) -> str:
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

    @classmethod
    def extract_pob(cls, text: str) -> str:
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

    @classmethod
    def is_closure_to_pob(cls, text: str) -> bool:
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

    @classmethod
    def extract_poc(cls, text: str) -> str:
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

    @classmethod
    def extract_poc_and_pob(cls, text: str) -> tuple[str, str]:
        """Extract both Point of Commencement and Point of Beginning.

        Args:
            text: Legal description text

        Returns:
            Tuple of (poc_description, pob_description)
        """
        poc = cls.extract_poc(text)
        pob = cls.extract_pob(text)

        return (poc, pob)

    @classmethod
    def split_into_calls(
        cls, text: str, *, course_lists: CourseListAnalysis | None = None
    ) -> list[str]:
        """Split text into individual THENCE calls.

        Handles multiple formats:
        - Numbered (1., 2., 3.; 1), 2); (1), (2))
        - THENCE keyword separated
        - Semicolon separated

        Args:
            text: Legal description text
            course_lists: The text's precomputed ``analyze_course_lists`` result

        Returns:
            List of call strings
        """
        analysis = course_lists if course_lists is not None else analyze_course_lists(text)
        if analysis.item_starts:
            parts = _enumerated_parts(analysis)
        elif _NUMBERED_LINE.search(text):
            parts = _NUMBERED_SPLIT.split(text)
        elif _THENCE.search(text):
            parts = _THENCE.split(text)
        else:
            parts = text.split(";")

        calls = []
        for part in parts:
            cleaned = part.strip()
            if not cleaned:
                continue

            if re.match(r"^\s*(?:BEGINNING|COMMENCING|POB|POINT)", cleaned, re.IGNORECASE):
                continue

            cleaned = re.sub(r"^(?:\(\d+\)|\d+[.)])\s+", "", cleaned)

            # Truncate at metadata section boundaries (e.g., "THE ABOVE DESCRIBED",
            # "CONTAINING", "BEING the same").  The pattern is sentence-boundary
            # anchored (". KEYWORD") so mid-call phrases are not affected.
            boundary = _METADATA_BOUNDARY.search(cleaned)
            if boundary:
                cleaned = cleaned[: boundary.start()]

            cleaned = re.sub(r"[;,\.\s]+$", "", cleaned)

            if cleaned:
                calls.append(cleaned)

        return calls

    @classmethod
    def extract_distance(cls, text: str) -> tuple[float, str]:
        """Extract distance value and unit from text.

        Args:
            text: Text containing distance (e.g., "125.26 feet" or "258 poles")

        Returns:
            Tuple of (distance_value, unit)
        """
        pattern = (
            rf"({_COMMA_NUMBER})\s*"
            r"(US\s+survey\s+(?:feet|foot)|engineer\s+chains?|engineer\s+links?"
            r"|foot|feet|ft|poles?|rods?|perches?|chains?|links?"
            r"|varas?|arpents?|toises?|furlongs?|meters?|miles?)"
        )

        total_match = re.search(
            rf"\b(?:for\s+)?a\s+total\s+distance\s+(?:of\s+)?({_COMMA_NUMBER})\s*"
            r"(US\s+survey\s+(?:feet|foot)|engineer\s+chains?|engineer\s+links?|foot|feet|ft|poles?|rods?|perches?|chains?|links?|varas?|arpents?|toises?|furlongs?|meters?|miles?)",
            text,
            re.IGNORECASE,
        )
        total_has_additional_component = bool(
            total_match
            and re.match(
                rf"\s+and\s+{_COMMA_NUMBER}\s+[A-Za-z]+",
                text[total_match.end() :],
                re.IGNORECASE,
            )
        )
        match: re.Match[str] | None = None
        if total_match and not total_has_additional_component:
            match = total_match
        else:
            compound_unit = (
                r"US\s+survey\s+(?:feet|foot)|engineer\s+chains?|engineer\s+links?|"
                r"foot|feet|ft|poles?|rods?|perches?|chains?|links?|varas?|arpents?|"
                r"toises?|furlongs?|meters?|miles?"
            )
            component_pattern = rf"({_COMMA_NUMBER})\s*({compound_unit})"
            # Components join with "and"; without it only genuine descending
            # sub-unit pairs (_IMPLICIT_COMPOUND_PAIRS) are summed.
            joiner = r"(?:\s+and\s+|\s*,\s*|\s+)"
            compound = re.search(
                rf"{component_pattern}(?:{joiner}{component_pattern})+",
                text,
                re.IGNORECASE,
            )
            # A compound counts only if it starts at the first measurement; a later
            # pair (e.g. a witness distance after "to a stake") never replaces it.
            first_measurement = re.search(pattern, text, re.IGNORECASE)
            if compound and (
                first_measurement is None or compound.start() != first_measurement.start()
            ):
                compound = None
            if compound and not re.fullmatch(
                rf"{component_pattern}(?:\s+and\s+{component_pattern})+",
                compound.group(0),
                re.IGNORECASE,
            ):
                comps = list(re.finditer(component_pattern, compound.group(0), re.IGNORECASE))
                keep = 1
                for prev, cur in zip(comps, comps[1:], strict=False):
                    gap = compound.group(0)[prev.end() : cur.start()]
                    pair = (_singular_unit(prev.group(2)), _singular_unit(cur.group(2)))
                    joined_by_and = re.search(r"\band\b", gap, re.IGNORECASE)
                    if not (joined_by_and or pair in _IMPLICIT_COMPOUND_PAIRS):
                        break
                    keep += 1
                if keep >= 2:
                    # Sum the full valid run so no leading component is dropped.
                    compound = re.compile(
                        rf"{component_pattern}(?:{joiner}{component_pattern}){{{keep - 1}}}",
                        re.IGNORECASE,
                    ).match(text, compound.start())
                else:
                    # Keep a valid "and" compound only if it begins at the first
                    # measurement (never skip a leading component); otherwise the
                    # first measurement alone is used.
                    compound = re.compile(
                        rf"{component_pattern}(?:\s+and\s+{component_pattern})+",
                        re.IGNORECASE,
                    ).match(text, compound.start())
            if compound:
                trailing_component = re.match(
                    rf"\s+and\s+{_COMMA_NUMBER}\s+[A-Za-z]+",
                    text[compound.end() :],
                    re.IGNORECASE,
                )
                if trailing_component:
                    return 0.0, "feet"
                values = [
                    (component.group(1), component.group(2))
                    for component in re.finditer(component_pattern, compound.group(0), re.IGNORECASE)
                ]
                unit_keys = {
                    "ft": "feet", "foot": "feet", "feet": "feet",
                    "poles": "poles", "pole": "poles", "rods": "rods", "rod": "rods",
                    "perch": "perches", "perches": "perches", "chain": "chains", "chains": "chains",
                    "link": "links", "links": "links", "engineer chain": "engineer_chains",
                    "engineer chains": "engineer_chains", "engineer link": "engineer_links",
                    "engineer links": "engineer_links", "us survey foot": "us_survey_feet",
                    "us survey feet": "us_survey_feet", "vara": "varas", "varas": "varas",
                    "arpent": "arpents", "arpents": "arpents", "toise": "toises", "toises": "toises",
                    "furlong": "furlongs", "furlongs": "furlongs", "meter": "meters", "meters": "meters",
                    "mile": "miles", "miles": "miles",
                }
                total_ft = sum(
                    ConversionFactors.convert_to_feet(
                        parse_comma_number(value), unit_keys[" ".join(unit.lower().split())]
                    )
                    for value, unit in values
                )
                return total_ft, "feet"
            if re.search(rf"{_COMMA_NUMBER}\s+[A-Za-z]+(?:\s+[A-Za-z]+)?\s+and\s+{_COMMA_NUMBER}\s+[A-Za-z]+", text, re.IGNORECASE):
                return 0.0, "feet"
            match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = parse_comma_number(match.group(1))
            unit = " ".join(match.group(2).lower().split())

            if unit in ("us survey feet", "us survey foot"):
                unit = "us_survey_feet"
            elif unit in ("engineer chain", "engineer chains"):
                unit = "engineer_chains"
            elif unit in ("engineer link", "engineer links"):
                unit = "engineer_links"
            elif unit in ("ft", "feet", "foot"):
                unit = "feet"
            elif unit in ("pole", "poles"):
                unit = "poles"
            elif unit in ("rod", "rods"):
                unit = "rods"
            elif unit in ("perch", "perches"):
                unit = "perches"
            elif unit in ("chain", "chains"):
                unit = "chains"
            elif unit in ("link", "links"):
                unit = "links"
            elif unit in ("vara", "varas"):
                unit = "varas"
            elif unit in ("arpent", "arpents"):
                unit = "arpents"
            elif unit in ("toise", "toises"):
                unit = "toises"
            elif unit in ("furlong", "furlongs"):
                unit = "furlongs"
            elif unit in ("meter", "meters"):
                unit = "meters"
            elif unit in ("mile", "miles"):
                unit = "miles"

            return (value, unit)

        apostrophe_feet = re.search(
            rf"(?<!°)({_COMMA_NUMBER})\s*'(?=\s*(?:(?:feet|foot|ft)\b|along\b|to\b|[.,;)]|$))",
            text,
            re.IGNORECASE,
        )
        if apostrophe_feet:
            return (parse_comma_number(apostrophe_feet.group(1)), "feet")

        return (0.0, "feet")

    @classmethod
    def clean_ocr_errors(cls, text: str) -> str:
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

    @classmethod
    def detect_meander(cls, text: str) -> bool:
        """Detect if call text references a water boundary (meander).

        Args:
            text: Call text to check

        Returns:
            True if text references a water boundary
        """
        if not text:
            return False

        if cls.MEANDER_PATTERNS.search(text):
            return True

        if cls.WATER_PREPOSITION_PATTERN.search(text) and cls.WATER_BODY_KEYWORDS.search(text):
            return True

        return False

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

    @classmethod
    def is_indefinite_call(cls, direction_text: str, has_bearing: bool) -> bool:
        """Detect if a call has vague/indefinite direction.

        Args:
            direction_text: The direction text of the call
            has_bearing: Whether a precise quadrant bearing was parsed

        Returns:
            True if the call is indefinite (no precise bearing)
        """
        if not direction_text or has_bearing:
            return False

        if cls.CARDINAL_ONLY_PATTERN.match(direction_text.strip()):
            return True

        if cls.INDEFINITE_PATTERNS.search(direction_text):
            return True

        return False

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

    @classmethod
    def expand_assessor_abbreviations(cls, text: str) -> str:
        """Expand compressed assessor notation (Wayne County MI and similar).

        Handles patterns like:
          S0DEG 32M 50S W 401.55FT
          N 88D 25M 31S E 330.00 FT
          TH SLY 90 FT ALG ELY LINE
          89D 05M 3SEC W

        Must run BEFORE standardize_cardinal_directions() so the word-form
        output ("degrees", "minutes", "seconds") can be converted to DMS
        symbols by the standard pipeline.

        CRITICAL: 'S' is ambiguous (South vs seconds).  We only treat 'S' as
        seconds when it appears as a numeric suffix inside a DMS pattern.

        Args:
            text: Raw legal description text with possible assessor notation

        Returns:
            Text with assessor abbreviations expanded
        """
        if not text:
            return text

        # --- 1. Fix common OCR typos: NODEG -> N0DEG, NOODEG -> N00DEG -----
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
        text = re.sub(
            r"\b([NS])OO(DEG|D)\b",
            lambda m: f"{m.group(1)}00{m.group(2)}",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\b([NS])O(DEG|D)\b",
            lambda m: f"{m.group(1)}0{m.group(2)}",
            text,
            flags=re.IGNORECASE,
        )

        # --- 2. Expand DMS bearing notation (DEG/D, M, S/SEC) --------------
        # Full DMS with seconds (S or SEC)
        text = re.sub(
            r"(\d{1,3})\s*(?:DEG|D)\s+(\d{1,2})\s*(?:M)\s+(\d{1,2}(?:\.\d+)?)\s*(?:SEC\b\.?|S\b)",
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
            r"(\d{1,3})\s*(?:DEG\b\.?|D\b)",
            r"\1 degrees",
            text,
            flags=re.IGNORECASE,
        )
        # "deg." -> "degrees"
        text = re.sub(
            r"(\d{1,3})\s+deg\.\s",
            r"\1 degrees ",
            text,
            flags=re.IGNORECASE,
        )

        # --- 3. Expand number+SEC that wasn't already caught ----------------
        text = re.sub(
            r"(\d{1,2}(?:\.\d+)?)\s*SEC\b\.?",
            r"\1 seconds",
            text,
            flags=re.IGNORECASE,
        )

        # --- 4. TH / TH. -> thence -----------------------------------------
        text = re.sub(
            r"\bTH\.?\s(?!E\b|A\b|I\b|ERE|EN|ROU|AT\b|US\b)",
            "thence ",
            text,
            flags=re.IGNORECASE,
        )

        # --- 5. FT suffix -> feet -------------------------------------------
        text = re.sub(
            r"(\d+(?:\.\d+)?)\s*FT\b",
            r"\1 feet",
            text,
            flags=re.IGNORECASE,
        )

        # --- 6. Directional abbreviations -----------------------------------
        text = re.sub(r"\bSLY\b", "southerly", text, flags=re.IGNORECASE)
        text = re.sub(r"\bNLY\b", "northerly", text, flags=re.IGNORECASE)
        text = re.sub(r"\bELY\b", "easterly", text, flags=re.IGNORECASE)
        text = re.sub(r"\bWLY\b", "westerly", text, flags=re.IGNORECASE)

        # --- 7. POB variants -> point of beginning --------------------------
        text = re.sub(r"\bP\.O\.B\.", "point of beginning", text, flags=re.IGNORECASE)
        text = re.sub(r"\bP\s+OB\b", "point of beginning", text, flags=re.IGNORECASE)
        text = re.sub(r"\bPOB\b", "point of beginning", text, flags=re.IGNORECASE)

        # --- 8. Misc abbreviations ------------------------------------------
        text = re.sub(r"\bALG\b", "along", text, flags=re.IGNORECASE)
        text = re.sub(r"\bCOR\b", "corner", text, flags=re.IGNORECASE)
        text = re.sub(r"\bBEG\b", "beginning", text, flags=re.IGNORECASE)

        # --- 9. `&` / `and` as call separators -> thence --------------------
        # Between bearings: "113.41 feet & N 69° 53' 23\" E" or
        # "49.18 feet and N 48° 03' 44\" E".  Replace `&` or `and` with
        # `thence` when followed by a quadrant bearing pattern ([NS] <digits>°).
        # Note: Only [NS] because standard quadrant bearings always start with
        # North or South.  E/W-initial bearings need different handling.
        text = re.sub(
            r"(?<=\S)\s+(?:&|and)\s+(?=[NS]\s*\d{1,3}\s*°)",
            " thence ",
            text,
            flags=re.IGNORECASE,
        )

        # --- 10. Bare cardinal + distance -> due Cardinal + distance --------
        # "thence S 289.81 feet" -> "thence due South 289.81 feet"
        # Only match single cardinal letters (N/S/E/W) or full words
        # (North/South/East/West) followed by a number, NOT followed by
        # degree notation (°, degrees, DEG).
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

        _BARE_CARDINAL_RE = re.compile(
            r"(\b(?:thence|proceeding)\s+)"  # group 1: anchor
            r"(N|S|E|W|North|South|East|West)"  # group 2: bare cardinal
            r"(\s+)"  # group 3: whitespace
            r"(\d+\.?\d*)",  # group 4: distance number

            re.IGNORECASE,
        )

        _DEGREE_AFTER_NUMBER = re.compile(
            r"\s*(?:°|degrees?|DEG\b)",
            re.IGNORECASE,
        )

        # A dashed, spaced or d/m bearing ("N 45-30-00 E", "N 45d30m E") is a
        # quadrant bearing too: only DMS tokens separate the number from E/W.
        _BEARING_TAIL = re.compile(
            r"(?:\s*(?:[-\d.°'\"′″]+|(?:d(?:eg(?:rees?)?)?|m(?:in(?:utes?)?)?"
            r"|s(?:ec(?:onds?)?)?)\.?(?![a-z])))*?\s*(?:E|W|East|West)\b",
            re.IGNORECASE,
        )

        def _bare_cardinal_replace(m: Match[str]) -> str:
            after_pos = m.end()
            after_text = m.string[after_pos : after_pos + 50]
            if _DEGREE_AFTER_NUMBER.match(after_text) or _BEARING_TAIL.match(after_text):
                return m.group(0)  # no change -- quadrant bearing
            prefix = m.group(1)
            cardinal = m.group(2)
            number = m.group(4)
            full_name = _CARDINAL_MAP[cardinal.lower()]
            return f"{prefix}due {full_name} {number}"

        text = _BARE_CARDINAL_RE.sub(_bare_cardinal_replace, text)

        return text

    @classmethod
    def expand_abbreviations(cls, text: str) -> str:
        """Expand common survey abbreviations.

        Args:
            text: Text with potential abbreviations

        Returns:
            Text with abbreviations expanded
        """
        for pattern, expansion in cls.SURVEY_ABBREVIATIONS:
            text = re.sub(pattern, expansion, text, flags=re.IGNORECASE)
        return text

    @classmethod
    def normalize_legal_description(cls, text: str) -> str:
        """Apply all normalization steps to a legal description.

        Args:
            text: Raw legal description text

        Returns:
            Normalized text
        """
        text = cls.clean_ocr_errors(text)
        text = cls.normalize_dms_symbols(text)
        text = cls.expand_assessor_abbreviations(text)
        text = cls.merge_line_wrapped_calls(text)
        text = cls.standardize_cardinal_directions(text)
        text = cls.expand_abbreviations(text)

        return text

    @staticmethod
    def _is_lot_qualifier_except(text: str, match: re.Match[str]) -> bool:
        """Check if an EXCEPT match is a lot-qualifier rather than structural.

        Lot qualifiers describe a portion of a lot being excluded from the lot
        reference itself (e.g. "except the South 43.65 feet of said Lot").
        They are NOT structural exception clauses that introduce a separately
        described parcel.
        """
        matched_text = match.group(0)
        if re.search(r"LESS\s+AND", matched_text, re.IGNORECASE):
            return False
        if re.search(r"ING$", matched_text, re.IGNORECASE):
            return False

        after = text[match.end() :]

        lot_qualifier_pattern = re.compile(
            r"^\s+the\s+"
            r"(?:North|South|East|West)"
            r"(?:erly|wardly)?"
            rf"\s+{_COMMA_NUMBER}"

            r"\s+(?:feet|foot|ft|poles?|rods?|chains?|links?|varas?|meters?)"
            r"\s+(?:of\b|in\b|thereof\b)",
            re.IGNORECASE,
        )
        return bool(lot_qualifier_pattern.match(after))

    @classmethod
    def split_exception_clauses(cls, text: str) -> list[tuple[str, bool]]:
        """Split text into main tract and exception/inclusion tracts.

        Args:
            text: Legal description text

        Returns:
            List of tuples (tract_text, is_exception)
            where is_exception=True for EXCEPT clauses, False for main/ALSO
        """
        splits: list[tuple[int, int, bool]] = []

        for match in re.finditer(r"\b(?:LESS\s+AND\s+)?EXCEPT(?:ING)?\b", text, re.IGNORECASE):
            if cls._is_lot_qualifier_except(text, match):
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

    @classmethod
    def extract_along_to_fields(cls, call_text: str) -> tuple[str, str]:
        """Extract along and to fields from a call description.

        Args:
            call_text: Single call text

        Returns:
            Tuple of (along, to) descriptions
        """
        along = ""
        to = ""

        def is_curve_direction_to(segment: str, token_end: int) -> bool:
            after = segment[token_end:].lstrip()
            return bool(re.match(r"the\s+(?:left|right)(?!\s+of)\b", after, re.IGNORECASE))

        along_match = re.search(r"\balong\b", call_text, re.IGNORECASE)
        if along_match:
            segment = call_text[along_match.end() :].lstrip()
            to_tokens = [
                match
                for match in re.finditer(r"\bto\b", segment, re.IGNORECASE)
                if not is_curve_direction_to(segment, match.end())
            ]

            if to_tokens:
                last_to = to_tokens[-1]
                along = segment[: last_to.start()].strip(" ,;.")
                to_section = segment[last_to.end() :].strip()
                to = _before_clause_delimiter(to_section).strip(" ,")
            else:
                along = _before_clause_delimiter(segment).strip(" ,")

        if not to:
            to_tokens = [
                match
                for match in re.finditer(r"\bto\b", call_text, re.IGNORECASE)
                if not is_curve_direction_to(call_text, match.end())
            ]
            if to_tokens:
                last = to_tokens[-1]
                to_candidate = call_text[last.end() :].strip()
                to = _before_clause_delimiter(to_candidate).strip(" ,")

        return (along, to)

    @classmethod
    def extract_basis_of_bearing(cls, text: str) -> str | None:
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

    @classmethod
    def extract_surveyor_certification(cls, text: str) -> str | None:
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

    @classmethod
    def extract_prior_conveyance(cls, text: str) -> str | None:
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

    @classmethod
    def extract_deed_clauses(cls, text: str) -> list[DeedClause]:
        """Extract deed clauses (reservations, subject-to, together-with).

        These are metadata clauses that don't change the boundary geometry.

        Args:
            text: Legal description text

        Returns:
            List of DeedClause objects
        """
        from .models import DeedClause

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

    @classmethod
    def extract_subdivision_reference(cls, text: str) -> SubdivisionReference | None:
        """Extract subdivision lot/block reference from deed text.

        Args:
            text: Legal description text

        Returns:
            SubdivisionReference or None if no subdivision reference found
        """
        from .models import SubdivisionReference

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

    @classmethod
    def infer_distance_unit(
        cls, text: str, state: str | None = None, year: int | None = None
    ) -> str | None:
        """Infer the primary distance unit from context.

        Advisory only — returns a suggestion, caller decides whether to apply it.

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

    @classmethod
    def extract_witness_trees(cls, text: str) -> list[str]:
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

    @classmethod
    def extract_coordinate_system(cls, text: str) -> tuple[str | None, str | None]:
        """Extract State Plane or other coordinate system reference.

        Advisory only — no grid correction computation.

        Args:
            text: Legal description text

        Returns:
            Tuple of (coordinate_system, fips_code) — both may be None
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
