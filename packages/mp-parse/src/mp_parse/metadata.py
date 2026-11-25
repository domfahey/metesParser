"""Metadata extraction from metes and bounds legal descriptions.

Extracts structured metadata: PLSS data, POC/POB, area statements,
basis of bearing, surveyor certification, prior conveyance, deed clauses,
subdivision references, witness trees, coordinate systems, and more.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal, TypedDict

from mp_models import ConversionFactors

from .numbers import COMMA_NUMBER, parse_comma_number

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

_COMMA_NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"

_DISTANCE_UNIT_TOKEN = (
    r"US\s+survey\s+(?:feet|foot)|engineer\s+chains?|engineer\s+links?"
    r"|foot|feet|ft|poles?|rods?|perches?|chains?|links?"
    r"|varas?|arpents?|toises?|furlongs?|meters?|miles?"
)

_UNSUPPORTED_DISTANCE_UNIT_TOKEN = (
    r"inch(?:es)?|yards?|yds?|cubits?|paces?|fathoms?|leagues?|ells?|spans?|hands?"
    r"|(?:kilo|centi|milli|deci)met(?:er|re)s?|metres?|km|cm|mm"
    r"|gunter(?:'s)?\s+(?:chains?|links?)"
)

_DISTANCE_UNIT_ALIASES: dict[str, str] = {
    "ft": "feet",
    "foot": "feet",
    "feet": "feet",
    "poles": "poles",
    "pole": "poles",
    "rods": "rods",
    "rod": "rods",
    "perch": "perches",
    "perches": "perches",
    "chain": "chains",
    "chains": "chains",
    "link": "links",
    "links": "links",
    "engineer chain": "engineer_chains",
    "engineer chains": "engineer_chains",
    "engineer link": "engineer_links",
    "engineer links": "engineer_links",
    "us survey foot": "us_survey_feet",
    "us survey feet": "us_survey_feet",
    "vara": "varas",
    "varas": "varas",
    "arpent": "arpents",
    "arpents": "arpents",
    "toise": "toises",
    "toises": "toises",
    "furlong": "furlongs",
    "furlongs": "furlongs",
    "meter": "meters",
    "meters": "meters",
    "mile": "miles",
    "miles": "miles",
}


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


class _AreaStatement(TypedDict):
    value_sq_ft: float
    unit: str
    approximate: bool


_AREA_PATTERN = re.compile(
    r"(?:(?:(?:approximately|approx\.?|~)\s+)?)"
    r"(?P<value>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"\s*(?P<unit>sq\.?\s*ft\.?|square\s+(?:feet|foot)|acres?)",
    re.IGNORECASE,
)
_AREA_STANDALONE_PATTERN = re.compile(
    r"\s*(?:(?:approximately|approx\.?|~)\s+)?"
    r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*(?:sq\.?\s*ft\.?|square\s+(?:feet|foot)|acres?)"
    r"(?:\s+more\s+or\s+less)?\s*[.]?\s*",
    re.IGNORECASE,
)
_AREA_PARCEL_CONTEXT_RE = re.compile(
    r"\b(?:containing|contains|comprising|consisting\s+of)\b|\barea\s*:\s*$"
)
_PARENT_AREA_CONTEXT_RE = re.compile(r"\b(?:parent|larger|original)\s+(?:tract|parcel|lot)\b")
_AREA_APPROX_RE = re.compile(r"\bapprox(?:imately)?\.?\b")


def extract_area_statement(text: str) -> _AreaStatement | None:
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

    matches = list(_AREA_PATTERN.finditer(normalized_text))
    if not matches:
        return None

    def is_parent_area_context(match: re.Match[str]) -> bool:
        preceding_text = normalized_text[: match.start()]
        clause_start = max(
            preceding_text.rfind(";"), preceding_text.rfind("."), preceding_text.rfind("\n")
        )
        clause_prefix = preceding_text[clause_start + 1 :]
        return bool(_PARENT_AREA_CONTEXT_RE.search(clause_prefix))

    # A bare area remains a supported API input, but an area embedded in a
    # legal description must be tied to the described parcel, not its parent.
    standalone = _AREA_STANDALONE_PATTERN.fullmatch(normalized_text)
    parcel_matches = [
        match
        for match in matches
        if _AREA_PARCEL_CONTEXT_RE.search(
            normalized_text[max(0, match.start() - 55) : match.start()]
        )
        and not _PARENT_AREA_CONTEXT_RE.search(normalized_text[match.start() : match.end() + 45])
        and not is_parent_area_context(match)
    ]
    if not parcel_matches and not standalone:
        return None

    match = parcel_matches[0] if parcel_matches else matches[0]
    unit = match.group("unit").replace(" ", "")
    value = float(match.group("value").replace(",", ""))

    if "acre" in unit:
        value_sq_ft = value * ConversionFactors.ACRE_TO_SQ_FEET
        unit_key = "acres"
    else:
        value_sq_ft = value
        unit_key = "sq_ft"

    prefix = normalized_text[max(0, match.start() - 45) : match.end() + 45]
    approximate = bool("~" in prefix or _AREA_APPROX_RE.search(prefix) or "more or less" in prefix)

    return {
        "value_sq_ft": value_sq_ft,
        "unit": unit_key,
        "approximate": approximate,
    }


_PLSS_SECTION_RE = re.compile(r"\b(?:SECTION|SEC\.?)\s+(\d+)\b")
_PLSS_TOWNSHIP_RE = re.compile(r"\b(?:TOWNSHIP|TOWN|T\.?)\s*(\d+)\s*(NORTH|N\.?|SOUTH|S\.?)\b")
_PLSS_RANGE_RE = re.compile(r"\b(?:RANGE|R\.?)\s*(\d+)\s*(EAST|E\.?|WEST|W\.?)\b")
_PLSS_PM_PRINCIPAL_RE = re.compile(
    r"\b(?:IN\s+|THE\s+)?([A-Z0-9]+(?:\s+[A-Z0-9]+){0,4})\s+PRINCIPAL\s+MERIDIAN\b"
)
_PLSS_PM_ABBREV_RE = re.compile(r"\b(?:IN\s+|THE\s+)?([A-Z0-9]+(?:\s+[A-Z0-9]+){0,4})\s+P\.?M\.?\b")
_PLSS_PM_PREFIX_STRIP_RE = re.compile(
    r"^(?:.*?\b(?:OF\s+THE|OF|IN|THE)\s+|(?:\d+\s+)?(?:NORTH|SOUTH|EAST|WEST)\s+)"
)
_PLSS_TIME_PM_RE = re.compile(r"\bAT\s+\d+(?::\d+)?\s+P\.?M\.?\b")
_PLSS_ORDINAL_OR_WORD_RE = re.compile(r"^(?:[A-Z][A-Z0-9]*|\d+(?:ST|ND|RD|TH))$")
_PLSS_ALIQUOT_RE = re.compile(
    r"\b((?:NE|NW|SE|SW|N|S|E|W)\s*(?:1/\d+|½|¼)\s+OF\s+(?:THE\s+)?)*(?:NE|NW|SE|SW|N|S|E|W)\s*(?:1/\d+|½|¼)\b"
)


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

    section_match = _PLSS_SECTION_RE.search(text_upper)
    if section_match:
        plss_data["section"] = section_match.group(1)

    township_match = _PLSS_TOWNSHIP_RE.search(text_upper)
    if township_match:
        township_num = township_match.group(1)
        direction_token = township_match.group(2)
        direction = "N" if direction_token.startswith("N") else "S"
        plss_data["township"] = f"{township_num} {direction}"

    range_match = _PLSS_RANGE_RE.search(text_upper)
    if range_match:
        range_num = range_match.group(1)
        direction_token = range_match.group(2)
        direction = "W" if direction_token.startswith("W") else "E"
        plss_data["range"] = f"{range_num} {direction}"

    pm_match = _PLSS_PM_PRINCIPAL_RE.search(text_upper)
    if pm_match:
        cleaned = _PLSS_PM_PREFIX_STRIP_RE.sub("", pm_match.group(1)).strip()
        if cleaned:
            plss_data["principal_meridian"] = f"{cleaned.title()} Principal Meridian"
    else:
        for abbrev_match in _PLSS_PM_ABBREV_RE.finditer(text_upper):
            ctx_start = max(0, abbrev_match.start() - 15)
            if _PLSS_TIME_PM_RE.search(text_upper[ctx_start : abbrev_match.end()]):
                continue
            cleaned = _PLSS_PM_PREFIX_STRIP_RE.sub("", abbrev_match.group(1)).strip()
            if not cleaned:
                continue
            last_token = cleaned.split()[-1]
            if not _PLSS_ORDINAL_OR_WORD_RE.match(last_token):
                continue
            plss_data["principal_meridian"] = f"{cleaned.title()} Principal Meridian"
            break

    aliquot_match = _PLSS_ALIQUOT_RE.search(text_upper)
    if aliquot_match:
        aliquot_text = aliquot_match.group(0)
        aliquot_text = aliquot_text.replace("½", "1/2").replace("¼", "1/4")
        plss_data["aliquot"] = aliquot_text

    return plss_data


_POB_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE | re.DOTALL)
    for pattern in (
        r"BEGINNING\s+at\s+(.*?)(?:\.(?!\d)|;|THENCE)",
        r"POB\s+at\s+(.*?)(?:\.(?!\d)|;|THENCE)",
        r"POINT\s+OF\s+BEGINNING\s+at\s+(.*?)(?:\.(?!\d)|;|THENCE)",
        r"TRUE\s+POINT\s+OF\s+BEGINNING\s+at\s+(.*?)(?:\.(?!\d)|;|THENCE)",
        r"TPOB\s+at\s+(.*?)(?:\.(?!\d)|;|THENCE)",
        r"T\.P\.O\.B\.\s+at\s+(.*?)(?:\.(?!\d)|;|THENCE)",
        r"REMOTE\s+POINT\s+OF\s+BEGINNING\s+at\s+(.*?)(?:\.(?!\d)|;|THENCE)",
        r"RPOB\s+at\s+(.*?)(?:\.(?!\d)|;|THENCE)",
        r"R\.P\.O\.B\.\s+at\s+(.*?)(?:\.(?!\d)|;|THENCE)",
        r"commencing\s+at\s+(.*?)(?:\.(?!\d)|;|THENCE)",
    )
)


def extract_pob(text: str) -> str:
    """Extract Point of Beginning description.

    Args:
        text: Legal description text

    Returns:
        POB description string
    """
    for pattern in _POB_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1).strip()

    return ""


_CLOSURE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\bto\s+(?:the\s+)?(?:(?:true|remote)\s+)?(?:point\s+(?:and\s+place\s+)?of\s+|place\s+of\s+)?beginning\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bto\s+(?:the\s+)?(?:(?:[TR]\.?P\.?O\.?B\.?)|P\.?O\.?B\.?)(?=\W|$)",
        re.IGNORECASE,
    ),
)


def is_closure_to_pob(text: str) -> bool:
    """Detect if call text indicates closure back to Point of Beginning.

    Args:
        text: Call text to check

    Returns:
        True if text indicates returning to POB, False otherwise
    """
    last_part = text[-60:] if len(text) > 60 else text

    return any(pattern.search(last_part) for pattern in _CLOSURE_PATTERNS)


_POC_POB_PATTERN = re.compile(r"\b(?:point\s+of\s+beginning|beginning|POB)\b", re.IGNORECASE)
_POC_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"COMMENCING\s+at\s+(.*?)(?:;|THENCE)", re.IGNORECASE | re.DOTALL),
    re.compile(r"STARTING\s+at\s+(.*?)(?:,|;|THENCE)", re.IGNORECASE | re.DOTALL),
)
_SUBSEQUENT_COURSE_RE = re.compile(
    r"\bTHENCE\b|(?:^|\n)\s*(?:\(\d+\)|\d+[.)])\s+",
    re.IGNORECASE | re.MULTILINE,
)
_BETWEEN_THENCE_RE = re.compile(r"\bTHENCE\b", re.IGNORECASE)
_BETWEEN_NUM_RE = re.compile(r"(?:^|\n)\s*(?:\(\d+\)|\d+[.)])\s+", re.MULTILINE)


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
    if not _POC_POB_PATTERN.search(text):
        return ""

    for pattern in _POC_PATTERNS:
        match = pattern.search(text)
        if match:
            poc_text = match.group(1).strip()
            poc_end_pos = match.end()

            pob_match = _POC_POB_PATTERN.search(text[poc_end_pos:])
            if pob_match:
                after_pob = text[poc_end_pos + pob_match.end() :]
                if _SUBSEQUENT_COURSE_RE.search(after_pob):
                    return poc_text
                between = text[poc_end_pos : poc_end_pos + pob_match.start()]
                if (
                    len(_BETWEEN_THENCE_RE.findall(between)) < 2
                    and ";" not in between
                    and len(_BETWEEN_NUM_RE.findall(between)) < 2
                ):
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


def split_into_calls(text: str) -> list[str]:
    """Split text into individual THENCE calls.

    Handles multiple formats:
    - Numbered (1., 2., 3.; 1), 2); (1), (2))
    - THENCE keyword separated
    - Semicolon separated

    Args:
        text: Legal description text

    Returns:
        List of call strings
    """
    numbered_pattern = r"(?:^|\n)\s*(?:\(\d+\)|\d+[.)])\s+"

    if re.search(numbered_pattern, text, re.MULTILINE):
        parts = re.split(
            r"(?:^|\n)\s*(?=(?:\(\d+\)|\d+[.)])\s+)",
            text,
            flags=re.MULTILINE,
        )
    elif re.search(r"\bTHENCE\b", text, re.IGNORECASE):
        parts = re.split(r"\bTHENCE\b", text, flags=re.IGNORECASE)
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


def extract_distance(text: str) -> tuple[float, str]:
    """Extract distance value and unit from text.

    Args:
        text: Text containing distance (e.g., "125.26 feet" or "258 poles")

    Returns:
        Tuple of (distance_value, unit)
    """
    component_pattern = rf"({_COMMA_NUMBER})\s*({_DISTANCE_UNIT_TOKEN})\b"

    def _normalize_unit(raw_unit: str) -> str:
        return _DISTANCE_UNIT_ALIASES[" ".join(raw_unit.lower().split())]

    def _consume_compound_from(
        base_value_raw: str, base_unit_raw: str, start_pos: int
    ) -> tuple[float, str] | None:
        base_unit = _normalize_unit(base_unit_raw)
        total_ft = ConversionFactors.convert_to_feet(parse_comma_number(base_value_raw), base_unit)
        pos = start_pos
        count = 1
        while True:
            cont = re.match(rf"\s+and\s+{component_pattern}", text[pos:], re.IGNORECASE)
            if not cont:
                break
            cont_unit = _normalize_unit(cont.group(2))
            total_ft += ConversionFactors.convert_to_feet(
                parse_comma_number(cont.group(1)), cont_unit
            )
            pos += cont.end()
            count += 1
        if re.match(
            rf"\s+and\s+{_COMMA_NUMBER}\s+(?:{_UNSUPPORTED_DISTANCE_UNIT_TOKEN})\b",
            text[pos:],
            re.IGNORECASE,
        ):
            return (0.0, "feet")
        if count >= 2:
            return (total_ft, "feet")
        return None

    total_match = re.search(
        rf"\b(?:for\s+)?a\s+total\s+distance\s+(?:of\s+)?{component_pattern}",
        text,
        re.IGNORECASE,
    )
    if total_match:
        compound_total = _consume_compound_from(
            total_match.group(1), total_match.group(2), total_match.end()
        )
        if compound_total is not None:
            return compound_total
        return (
            parse_comma_number(total_match.group(1)),
            _normalize_unit(total_match.group(2)),
        )

    first_match = re.search(component_pattern, text, re.IGNORECASE)
    if first_match:
        if re.search(
            rf"{_COMMA_NUMBER}\s+(?:{_UNSUPPORTED_DISTANCE_UNIT_TOKEN})\b\s+and\s+$",
            text[: first_match.start()],
            re.IGNORECASE,
        ):
            return (0.0, "feet")
        compound_result = _consume_compound_from(
            first_match.group(1), first_match.group(2), first_match.end()
        )
        if compound_result is not None:
            return compound_result
        return (
            parse_comma_number(first_match.group(1)),
            _normalize_unit(first_match.group(2)),
        )

    for m in re.finditer(
        rf"(?<![\d\u00b0])({_COMMA_NUMBER})\s*'(?=\s*(?:(?:feet|foot|ft)\b|along\b|to\b|[.,;)]|$))",
        text,
        re.IGNORECASE,
    ):
        prefix = text[: m.end()]
        if re.search(
            r"\b(?:NORTH|SOUTH|N|S)\s+\d{1,3}\s+\d+(?:\.\d+)?\s*'\s*$",
            prefix,
            re.IGNORECASE,
        ) or re.search(r"\d+\u00b0\s*\d+(?:\.\d+)?\s*'\s*$", prefix):
            continue
        return (parse_comma_number(m.group(1)), "feet")

    return (0.0, "feet")


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
        rf"\s+{COMMA_NUMBER}"
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


def extract_along_to_fields(call_text: str) -> tuple[str, str]:
    """Extract along and to fields from a call description.

    Args:
        call_text: Single call text

    Returns:
        Tuple of (along, to) descriptions
    """
    along = ""
    to = ""

    def is_non_endpoint_to(segment: str, token_start: int, token_end: int) -> bool:
        after = segment[token_end:].lstrip()
        if re.match(r"the\s+(?:left|right)(?!\s+of)\b", after, re.IGNORECASE):
            return True
        before = segment[:token_start].rstrip()
        return bool(re.search(r"\b(?:common|parallel)$", before, re.IGNORECASE))

    along_match = re.search(r"\balong\b", call_text, re.IGNORECASE)
    if along_match:
        segment = call_text[along_match.end() :].lstrip()
        to_tokens = [
            match
            for match in re.finditer(r"\bto\b", segment, re.IGNORECASE)
            if not is_non_endpoint_to(segment, match.start(), match.end())
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
            if not is_non_endpoint_to(call_text, match.start(), match.end())
        ]
        if to_tokens:
            last = to_tokens[-1]
            to_candidate = call_text[last.end() :].strip()
            to = _before_clause_delimiter(to_candidate).strip(" ,")

    return (along, to)


_SENTENCE_END = r"(?:(?<!\b[A-Za-z])(?<!\bNo)(?<!\.[A-Za-z])\.(?!\d)|$)"
_CLAUSE_END = r"(?:;|(?<!\b[A-Za-z])(?<!\bNo)(?<!\.[A-Za-z])\.(?!\d)|$)"

_BASIS_OF_BEARING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(rf"basis\s+of\s+bearings?\s*:\s*(.+?){_SENTENCE_END}", re.IGNORECASE),
    re.compile(rf"bearings?\s+(?:are\s+)?based\s+on\s+(.+?){_SENTENCE_END}", re.IGNORECASE),
    re.compile(rf"bearings?\s+referenced\s+to\s+(.+?){_SENTENCE_END}", re.IGNORECASE),
    re.compile(
        rf"bearings?\s+(?:herein\s+)?are\s+(magnetic|assumed|true\s+north|grid\s+north)(?:\b.*?){_SENTENCE_END}",
        re.IGNORECASE,
    ),
)

_SURVEYOR_CERT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:That\s+I,\s+)(.+?)(?:,\s+(?:a\s+)?(?:Licensed|Registered|Professional))",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(rf"(?:Certified\s+by:\s*)(.+?){_SENTENCE_END}", re.IGNORECASE),
    re.compile(rf"(?:Surveyed\s+by\s+)(.+?){_SENTENCE_END}", re.IGNORECASE),
    re.compile(rf"(I\s+hereby\s+certify\s+.+?){_SENTENCE_END}", re.IGNORECASE),
)

_PRIOR_CONVEYANCE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(rf"(BEING\s+the\s+same\s+premises\s+.+?){_SENTENCE_END}", re.IGNORECASE),
    re.compile(
        r"((?:Deed|Official\s+Records)\s+Book\s+\d+(?:,?\s*Page\s+\d+)?)",
        re.IGNORECASE,
    ),
    re.compile(rf"(Instrument\s+Number\s+\d+.+?){_SENTENCE_END}", re.IGNORECASE),
)

_DEED_CLAUSE_PATTERNS: tuple[
    tuple[re.Pattern[str], Literal["reservation", "subject_to", "together_with"]], ...
] = (
    (
        re.compile(r"(RESERVING\b.*?)(?=\.\s+[A-Z]|\.\s*$|$)", re.IGNORECASE | re.DOTALL),
        "reservation",
    ),
    (
        re.compile(r"(SUBJECT\s+TO\b.*?)(?=\.\s+[A-Z]|\.\s*$|$)", re.IGNORECASE | re.DOTALL),
        "subject_to",
    ),
    (
        re.compile(r"(TOGETHER\s+WITH\b.*?)(?=\.\s+[A-Z]|\.\s*$|$)", re.IGNORECASE | re.DOTALL),
        "together_with",
    ),
)

_SUBDIV_STOPWORDS = frozenset(
    {
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "and",
        "or",
        "the",
        "a",
        "an",
        "is",
        "was",
        "as",
        "by",
        "from",
        "with",
        "that",
        "this",
        "wall",
        "walls",
        "building",
        "house",
        "line",
        "corner",
        "thereof",
        "said",
        "such",
        "land",
        "ground",
        "area",
        "size",
        "more",
        "less",
    }
)
_SUBDIV_LOT_RE = re.compile(r"\bLot\s+(?:(?:No\.?|#)\s*)?(\w+)\b", re.IGNORECASE)
_SUBDIV_BLOCK_RE = re.compile(r"\bBlock\s+(?:(?:No\.?|#)\s*)?(\w+)\b", re.IGNORECASE)
_SUBDIV_NAME_RE = re.compile(
    r"(?i:(?:Block|Lot)\s+(?:(?:No\.?|#)\s*)?(?:\d+[A-Za-z]?|[A-Za-z](?![a-z]))),?\s+"
    r"(?!(?:BLOCK|LOT)\b)"
    r"([A-Z][A-Z\s]+(?:ESTATES?|SUBDIVISION|ADDITION|HEIGHTS?|HILLS?|PARK|PLACE|MANOR|ACRES|VILLAGE|LANDING|TERRACE|GARDENS?)?)\b"
)
_SUBDIV_PLAT_RE = re.compile(r"Plat\s+Book\s+(\d+),?\s*Page\s+(\d+)", re.IGNORECASE)

_VARAS_RE = re.compile(r"\bvaras?\b", re.IGNORECASE)
_ARPENTS_RE = re.compile(r"\barpents?\b", re.IGNORECASE)
_NEW_ENGLAND_STATES = frozenset({"MA", "CT", "ME", "NH", "VT", "RI"})

_WITNESS_TREE_PATTERN = re.compile(
    r"((?:a\s+)?(?:\w+\s+)?\b(?:oak|hickory|elm|pine|walnut|sycamore|maple|beech|"
    r"poplar|cedar|ash|birch|chestnut|cottonwood|willow|cypress)\b"
    r"(?:[^;.]|\.(?=\d))*?\bbears?\b(?:[^;.]|\.(?=\d))*?(?:dist(?:ant)?|links?|feet|ft)(?:[^;.]|\.(?=\d))*)",
    re.IGNORECASE,
)
_CHORD_OR_RADIAL_BEARS_RE = re.compile(
    r"\b(?:chord(?:\s+of\s+which)?|radial(?:\s+line)?)\s+bears?\b",
    re.IGNORECASE,
)

_SPCS_RE = re.compile(
    rf"(State\s+Plane\s+Coordinate\s+System.+?){_CLAUSE_END}",
    re.IGNORECASE,
)
_FIPS_RE = re.compile(r"\bFIPS\s+(?:Zone\s+)?(\d{4})\b", re.IGNORECASE)


def extract_basis_of_bearing(text: str) -> str | None:
    """Extract basis of bearing from legal description text.

    Args:
        text: Legal description text

    Returns:
        Basis of bearing string or None if not found
    """
    for pattern in _BASIS_OF_BEARING_PATTERNS:
        match = pattern.search(text)
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
    for pattern in _SURVEYOR_CERT_PATTERNS:
        match = pattern.search(text)
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
    for pattern in _PRIOR_CONVEYANCE_PATTERNS:
        match = pattern.search(text)
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

    for pattern, clause_type in _DEED_CLAUSE_PATTERNS:
        for match in pattern.finditer(text):
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

    for lot_match in _SUBDIV_LOT_RE.finditer(text):
        candidate = lot_match.group(1)
        if candidate.lower() not in _SUBDIV_STOPWORDS:
            lot = candidate
            break

    for block_match in _SUBDIV_BLOCK_RE.finditer(text):
        candidate = block_match.group(1)
        if candidate.lower() not in _SUBDIV_STOPWORDS:
            block = candidate
            break

    # Subdivision name: typically in ALL CAPS after Lot/Block
    name_match = _SUBDIV_NAME_RE.search(text)
    if name_match:
        subdivision_name = name_match.group(1).strip()

    plat_match = _SUBDIV_PLAT_RE.search(text)
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
    if _VARAS_RE.search(text):
        return "varas"
    if "chains and links" in text.lower():
        return "chains"
    if _ARPENTS_RE.search(text):
        return "arpents"

    state_upper = state.upper() if state else None
    if state_upper == "TX" and year is not None and year < 1900:
        return "varas"
    if state_upper == "LA":
        return "arpents"

    if state_upper in _NEW_ENGLAND_STATES and year is not None and year < 1850:
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

    for match in _WITNESS_TREE_PATTERN.finditer(text):
        candidate = match.group(1).strip()
        if _CHORD_OR_RADIAL_BEARS_RE.search(candidate):
            continue
        trees.append(candidate)

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

    spcs_match = _SPCS_RE.search(text)
    if spcs_match:
        coordinate_system = spcs_match.group(1).strip()

    fips_match = _FIPS_RE.search(text)
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


_STREET_WATER_NAME_RE = re.compile(
    r"\b(?:creek|stream|river|brook|run|branch|kill|pond|lake|shore|bank|bay|spring)\s+"
    r"(?:ave(?:nue)?|st(?:reet)?|rd|road|dr(?:ive)?|ln|lane|ct|court|blvd|boulevard|"
    r"pkwy|parkway|way|pl(?:ace)?|cir(?:cle)?|ter(?:race)?|tr(?:ail)?|hwy|highway|"
    r"pike|turnpike|alley)\b\.?",
    re.IGNORECASE,
)

_FINANCIAL_BANK_RE = re.compile(
    r"\b(?:(?:first|second|third|national|federal|state|savings|trust|commercial|"
    r"community|citizens|merchants|farmers|chase|wells\s+fargo|citibank|pnc|td|us|"
    r"union|peoples|american|city|central|capital|valley|heritage|liberty|pacific|"
    r"atlantic|republic|united|home|security|fidelity)\s+)+bank\b"
    r"|\bbank\s+of\s+(?!the\s+(?:creek|stream|river|brook|run|branch|kill|pond|lake)\b)[A-Za-z]+",
    re.IGNORECASE,
)

_UNAMBIGUOUS_WATER_BODY_RE = re.compile(
    r"\b(?:creek|stream|river|brook|run|branch|kill|pond|lake|shore|thalweg|thread)\b",
    re.IGNORECASE,
)

_WATER_BANK_RE = re.compile(
    r"\b(?:the|north(?:erly)?|south(?:erly)?|east(?:erly)?|west(?:erly)?|left|right|"
    r"high|low|opposite|creek|river|stream|brook|pond|lake)\s+bank\b"
    r"|\bbank\s+of\s+(?:the\s+)?(?:creek|stream|river|brook|run|branch|kill|pond|lake)\b",
    re.IGNORECASE,
)

_WATER_MARK_RE = re.compile(
    r"\b(?:(?:high|low)\s+water\s+mark|water(?:'s)?\s+edge|"
    r"thread\s+of\s+(?:the\s+)?(?:creek|stream|river|brook|run|branch))\b",
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

    cleaned = _STREET_WATER_NAME_RE.sub(" ", text)
    cleaned = _FINANCIAL_BANK_RE.sub(" ", cleaned)

    if _WATER_MARK_RE.search(cleaned):
        return True

    if WATER_PREPOSITION_PATTERN.search(cleaned) and (
        _UNAMBIGUOUS_WATER_BODY_RE.search(cleaned) or _WATER_BANK_RE.search(cleaned)
    ):
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

# Full direction names (case-insensitive group).
_DIRECTION_GROUP = r"(?P<dir>North|South|East|West|N|S|E|W)"

# Width: integer or decimal number.
_WIDTH_GROUP = r"(?P<width>\d+(?:\.\d+)?)"

# Unit: feet or ft.
_UNIT_GROUP = r"(?:feet|ft)"


class _StripException(TypedDict):
    direction: str
    width_ft: float
    purpose: str | None
    original_text: str


# Each pattern is a compiled regex that captures: direction, width, and an
# optional trailing purpose clause.  The patterns are tried in order; each
# match produces one _StripException dict.
_STRIP_PATTERNS: list[re.Pattern[str]] = [
    # "LESS AND EXCEPT the North 15 feet thereof" (must come before generic except)
    re.compile(
        r"less\s+and\s+except(?:ing)?\s+(?:the\s+)"
        + _DIRECTION_GROUP
        + r"\s+"
        + _WIDTH_GROUP
        + r"\s+"
        + _UNIT_GROUP
        + r"(?:\s+(?P<purpose>deeded\s+for\s+(?:(?!\s+(?:and\s+)?(?:less\s+and\s+)?except(?:ing)?\b)[^.;,\n])+|thereof))?"
        + r"[.\s]*",
        re.IGNORECASE,
    ),
    # "except the East 20 feet [deeded for roadway]"
    # "except the South 30 feet thereof"
    # Also covers "and except the ..."
    re.compile(
        r"(?:and\s+)?except(?:ing)?\s+(?:the\s+)"
        + _DIRECTION_GROUP
        + r"\s+"
        + _WIDTH_GROUP
        + r"\s+"
        + _UNIT_GROUP
        + r"(?:\s+(?P<purpose>deeded\s+for\s+(?:(?!\s+(?:and\s+)?(?:less\s+and\s+)?except(?:ing)?\b)[^.;,\n])+|thereof))?"
        + r"[.\s]*",
        re.IGNORECASE,
    ),
    # "excepting therefrom the West 25 feet"
    re.compile(
        r"excepting\s+therefrom\s+(?:the\s+)"
        + _DIRECTION_GROUP
        + r"\s+"
        + _WIDTH_GROUP
        + r"\s+"
        + _UNIT_GROUP
        + r"[.\s]*",
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
        + r"[.\s]*",
        re.IGNORECASE,
    ),
]

# Pattern to detect a metes-and-bounds traverse inside an exception clause.
# If an EXCEPT clause contains "THENCE" or a quadrant bearing like "S 45 degrees",
# it is a geometric exception (not a simple strip), and should NOT be removed.
_METES_INDICATOR = re.compile(
    r"\bthence\b|"
    r"\b[NS]\s*\d{1,3}\s*°|"
    r"\b(?:North|South|N|S)\s+\d{1,3}\s+degree",
    re.IGNORECASE,
)
_STRIP_CLAUSE_BOUNDARY_RE = re.compile(
    r"\.(?!\d)|\b(?:ALSO|INCLUDING|TRACT|PARCEL)\b",
    re.IGNORECASE,
)


def _normalize_direction(raw: str) -> str:
    """Normalize a direction token to its full canonical name (title case).

    >>> _normalize_direction("E")
    'East'
    >>> _normalize_direction("south")
    'South'
    """
    upper = raw.upper().strip()
    if upper in _DIRECTION_ABBREV:
        return _DIRECTION_ABBREV[upper]
    return raw.strip().capitalize()


def _clean_purpose(raw: str | None) -> str | None:
    """Clean and normalize the purpose string, or return None."""
    if raw is None:
        return None
    cleaned = raw.strip().rstrip(".")
    if not cleaned or cleaned.lower() == "thereof":
        return None
    # Collapse "deeded for roadway" → "roadway"
    deeded_match = re.match(r"deeded\s+for\s+(.+)", cleaned, re.IGNORECASE)
    if deeded_match:
        return deeded_match.group(1).strip().lower()
    return cleaned


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
    if not text:
        return []

    results: list[_StripException] = []
    seen_spans: set[tuple[int, int]] = set()

    for pattern in _STRIP_PATTERNS:
        for match in pattern.finditer(text):
            span = (match.start(), match.end())
            # Avoid duplicate matches from overlapping patterns
            if any(s[0] < span[1] and span[0] < s[1] for s in seen_spans):
                continue

            original = match.group(0).strip().rstrip(".")

            # Guard: if the exception clause (bounded at sentence/tract boundary)
            # contains metes indicators, this is a geometric exception, not a strip.
            post_limit = min(len(text), match.end() + 200)
            boundary_match = _STRIP_CLAUSE_BOUNDARY_RE.search(text, match.start())
            if boundary_match:
                post_limit = min(post_limit, boundary_match.start())
            post_match_text = text[match.start() : post_limit]
            if _METES_INDICATOR.search(post_match_text):
                continue

            direction_raw = match.group("dir")
            width = float(match.group("width"))

            # Extract purpose -- not all patterns define this named group
            purpose_raw = None
            if "purpose" in pattern.groupindex:
                purpose_raw = match.group("purpose")

            results.append(
                _StripException(
                    direction=_normalize_direction(direction_raw),
                    width_ft=width,
                    purpose=_clean_purpose(purpose_raw),
                    original_text=original,
                )
            )
            seen_spans.add(span)

    return results


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
