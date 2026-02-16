"""Text parsing utilities for normalizing legal descriptions.

Handles cleaning up OCR errors, standardizing DMS notation, merging line breaks, etc.
"""

import re
from re import Match
from typing import Callable, TypedDict

from .models import ConversionFactors


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

        for match in area_pattern.finditer(normalized_text):
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
            r"\b(?:TOWNSHIP|T\.?)\s*(\d+)\s*(NORTH|N\.?|SOUTH|S\.?)\b", text_upper
        )
        if township_match:
            township_num = township_match.group(1)
            direction_token = township_match.group(2)
            direction = "N" if direction_token.startswith("N") else "S"
            plss_data["township"] = f"{township_num} {direction}"

        range_match = re.search(
            r"\b(?:RANGE|R\.?)\s*(\d+)\s*(EAST|E\.?|WEST|W\.?)\b", text_upper
        )
        if range_match:
            range_num = range_match.group(1)
            direction_token = range_match.group(2)
            direction = "W" if direction_token.startswith("W") else "E"
            plss_data["range"] = f"{range_num} {direction}"

        pm_patterns = [
            r"\b(?:IN\s+|THE\s+)?([A-Z]+(?:\s+[A-Z]+){0,4})\s+PRINCIPAL\s+MERIDIAN\b",
            r"\b(?:IN\s+|THE\s+)?([A-Z]+(?:\s+[A-Z]+){0,4})\s+P\.?M\.?\b",
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

            if re.match(r"^(THENCE|BEGINNING|FROM|POB|POINT)", stripped, re.IGNORECASE):
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
    def split_into_calls(cls, text: str) -> list[str]:
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
            r"(\d+(?:\.\d+)?)\s*"
            r"(foot|feet|ft|poles?|rods?|perches?|chains?|links?"
            r"|varas?|arpents?|toises?|furlongs?|meters?|miles?)"
        )

        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = float(match.group(1))
            unit = match.group(2).lower()

            if unit in ("ft", "feet", "foot"):
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
        text = cls.merge_line_wrapped_calls(text)
        text = cls.standardize_cardinal_directions(text)
        text = cls.expand_abbreviations(text)

        return text

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
            return bool(re.match(r"the\s+(?:left|right)\b", after, re.IGNORECASE))

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
                to = re.split(r"[.;]", to_section, maxsplit=1)[0].strip(" ,")
            else:
                along = re.split(r"[.;]", segment, maxsplit=1)[0].strip(" ,")

        if not to:
            to_tokens = [
                match
                for match in re.finditer(r"\bto\b", call_text, re.IGNORECASE)
                if not is_curve_direction_to(call_text, match.end())
            ]
            if to_tokens:
                last = to_tokens[-1]
                to_candidate = call_text[last.end() :].strip()
                to = re.split(r"[.;]", to_candidate, maxsplit=1)[0].strip(" ,")

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
            (r"bearings?\s+(?:herein\s+)?are\s+(magnetic|assumed|true\s+north|grid\s+north)(?:\b.*?)(?:\.|$)", re.IGNORECASE),
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
            (r"(?:That\s+I,\s+)(.+?)(?:,\s+(?:a\s+)?(?:Licensed|Registered|Professional))", re.IGNORECASE | re.DOTALL),
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
            (r"((?:Deed|Official\s+Records)\s+Book\s+\d+.*?(?:Page\s+\d+)?)(?:\b.*?)(?:\.|$)", re.IGNORECASE),
            (r"(Instrument\s+Number\s+\d+.+?)(?:\.|$)", re.IGNORECASE),
        ]

        for pattern, flags in patterns:
            match = re.search(pattern, text, flags)
            if match:
                return match.group(1).strip()

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
