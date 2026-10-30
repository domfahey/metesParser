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
            re.search(r"\b(?:parent|larger|original)\s+(?:tract|parcel|lot)\b", clause_prefix)
        )

    # A bare area remains a supported API input, but an area embedded in a
    # legal description must be tied to the described parcel, not its parent.
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


def extract_distance(text: str) -> tuple[float, str]:
    """Extract distance value and unit from text.

    Args:
        text: Text containing distance (e.g., "125.26 feet" or "258 poles")

    Returns:
        Tuple of (distance_value, unit)
    """
    pattern = (
        rf"({COMMA_NUMBER})\s*"
        r"(US\s+survey\s+(?:feet|foot)|engineer\s+chains?|engineer\s+links?"
        r"|foot|feet|ft|poles?|rods?|perches?|chains?|links?"
        r"|varas?|arpents?|toises?|furlongs?|meters?|miles?)"
    )

    total_match = re.search(
        rf"\b(?:for\s+)?a\s+total\s+distance\s+(?:of\s+)?({COMMA_NUMBER})\s*"
        r"(US\s+survey\s+(?:feet|foot)|engineer\s+chains?|engineer\s+links?|foot|feet|ft|poles?|rods?|perches?|chains?|links?|varas?|arpents?|toises?|furlongs?|meters?|miles?)",
        text,
        re.IGNORECASE,
    )
    total_has_additional_component = bool(
        total_match
        and re.match(
            rf"\s+and\s+{COMMA_NUMBER}\s+[A-Za-z]+",
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
        component_pattern = rf"({COMMA_NUMBER})\s*({compound_unit})"
        # Components join with "and"; without it only genuine descending
        # sub-unit pairs (_IMPLICIT_COMPOUND_PAIRS) are summed.
        joiner = r"(?:\s+and\s+|\s*,\s*|\s+)"
        compound = re.search(
            rf"{component_pattern}(?:{joiner}{component_pattern})+",
            text,
            re.IGNORECASE,
        )
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
                # Keep a valid "and" compound; drop unrelated trailing measurements.
                compound = re.search(
                    rf"{component_pattern}(?:\s+and\s+{component_pattern})+",
                    text,
                    re.IGNORECASE,
                )
        if compound:
            trailing_component = re.match(
                rf"\s+and\s+{COMMA_NUMBER}\s+[A-Za-z]+", text[compound.end() :], re.IGNORECASE
            )
            if trailing_component:
                return 0.0, "feet"
            values = [
                (component.group(1), component.group(2))
                for component in re.finditer(component_pattern, compound.group(0), re.IGNORECASE)
            ]
            unit_keys = {
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
            total_ft = sum(
                ConversionFactors.convert_to_feet(
                    parse_comma_number(value), unit_keys[" ".join(unit.lower().split())]
                )
                for value, unit in values
            )
            return total_ft, "feet"
        if re.search(
            rf"{COMMA_NUMBER}\s+[A-Za-z]+(?:\s+[A-Za-z]+)?\s+and\s+{COMMA_NUMBER}\s+[A-Za-z]+",
            text,
            re.IGNORECASE,
        ):
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
        rf"(?<!\u00b0)({COMMA_NUMBER})\s*'(?=\s*(?:(?:feet|foot|ft)\b|along\b|to\b|[.,;)]|$))",
        text,
        re.IGNORECASE,
    )
    if apostrophe_feet:
        return (parse_comma_number(apostrophe_feet.group(1)), "feet")

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
        + r"(?:\s+(?P<purpose>deeded\s+for\s+\S+|thereof))?"
        + r"[.\s]*",
        re.IGNORECASE,
    ),
    # "LESS AND EXCEPT the North 15 feet thereof"
    re.compile(
        r"less\s+and\s+except(?:ing)?\s+(?:the\s+)"
        + _DIRECTION_GROUP
        + r"\s+"
        + _WIDTH_GROUP
        + r"\s+"
        + _UNIT_GROUP
        + r"(?:\s+(?P<purpose>thereof))?"
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
    r"\b[NS]\s+\d+\s+degree",
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
    deeded_match = re.match(r"deeded\s+for\s+(\S+)", cleaned, re.IGNORECASE)
    if deeded_match:
        return deeded_match.group(1).lower()
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
            if any(s[0] <= span[0] < s[1] or s[0] < span[1] <= s[1] for s in seen_spans):
                continue

            original = match.group(0).strip().rstrip(".")

            # Guard: if the matched text (or nearby context) contains metes
            # indicators, this is a geometric exception, not a simple strip.
            # Look at the broader exception clause context.
            context_start = max(0, match.start() - 10)
            context_end = min(len(text), match.end() + 200)
            context = text[context_start:context_end]
            if _METES_INDICATOR.search(context):
                # Check that the THENCE/bearing is actually AFTER the
                # exception keyword, not before it in the main description.
                post_match_text = text[match.start() : context_end]
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
