"""Text parsing utilities for normalizing legal descriptions.

Handles cleaning up OCR errors, standardizing DMS notation, merging line breaks, etc.
"""

import re
from typing import List


class TextParser:
    """Parse and normalize legal description text."""

    @classmethod
    def extract_plss_metadata(cls, text: str) -> dict[str, str | None]:
        """Extract PLSS (Public Land Survey System) metadata from text.

        Args:
            text: Legal description text

        Returns:
            Dict with section, township, range, principal_meridian, aliquot
        """
        plss_data = {
            "section": None,
            "township": None,
            "range": None,
            "principal_meridian": None,
            "aliquot": None,
        }

        text_upper = text.upper()

        # Extract Section
        section_match = re.search(r"\bSECTION\s+(\d+)\b", text_upper)
        if section_match:
            plss_data["section"] = section_match.group(1)

        # Extract Township (various formats)
        # "Township 15 North" or "T15N" or "T. 15 N."
        township_match = re.search(
            r"\b(?:TOWNSHIP|T\.?)\s*(\d+)\s*(?:NORTH|N\.?|SOUTH|S\.?)\b", text_upper
        )
        if township_match:
            township_num = township_match.group(1)
            direction = (
                "N" if "NORTH" in township_match.group(0) or "N" in township_match.group(0) else "S"
            )
            plss_data["township"] = f"{township_num} {direction}"

        # Extract Range (various formats)
        # "Range 3 East" or "R3E" or "R. 3 E."
        range_match = re.search(r"\b(?:RANGE|R\.?)\s*(\d+)\s*(?:EAST|E\.?|WEST|W\.?)\b", text_upper)
        if range_match:
            range_num = range_match.group(1)
            direction = (
                "E" if "EAST" in range_match.group(0) or "E" in range_match.group(0) else "W"
            )
            plss_data["range"] = f"{range_num} {direction}"

        # Extract Principal Meridian
        # Common meridians: Willamette, San Bernardino, Mount Diablo, etc.
        pm_patterns = [
            r"\b(\w+)\s+PRINCIPAL\s+MERIDIAN\b",
            r"\b(\w+)\s+P\.?M\.?\b",
        ]
        for pattern in pm_patterns:
            pm_match = re.search(pattern, text_upper)
            if pm_match:
                meridian_name = pm_match.group(1).title()
                plss_data["principal_meridian"] = f"{meridian_name} Principal Meridian"
                break

        # Extract Aliquot (e.g., "SW 1/4 of NE 1/4")
        # Pattern: cardinal direction + fraction "of" cardinal direction + fraction...
        aliquot_pattern = r"\b((?:NE|NW|SE|SW|N|S|E|W)\s*(?:1/\d+|½|¼)\s+OF\s+(?:THE\s+)?)+(?:NE|NW|SE|SW|N|S|E|W)\s*(?:1/\d+|½|¼)\b"
        aliquot_match = re.search(aliquot_pattern, text_upper)
        if aliquot_match:
            # Normalize fractions
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
        # Replace common degree symbol variants
        text = re.sub(r"[°º\u00B0\u00BA]", "°", text)

        # Replace minute symbols
        text = re.sub(r"[''\u2018\u2019`]", "'", text)

        # Replace second symbols
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
        # Replace hyphenated line breaks
        text = re.sub(r"-\s*\n\s*", "", text)

        # Merge lines that don't start with THENCE/BEGINNING/FROM
        lines = text.split("\n")
        merged = []
        current = ""

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # If line starts with keyword, it's a new call
            if re.match(r"^(THENCE|BEGINNING|FROM|POB|POINT)", stripped, re.IGNORECASE):
                if current:
                    merged.append(current)
                current = stripped
            else:
                # Continue previous line
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
        # Standardize common patterns
        patterns = [
            # South 87 degrees 7 minutes 30 seconds West -> S 87°7'30" W (with seconds)
            (
                r"\b(North|South|East|West)\s+(\d{1,3})\s+degrees?\s+(\d{1,2})\s+minutes?\s+(\d{1,2}(?:\.\d+)?)\s+seconds?\s+(North|South|East|West)\b",
                lambda m: f'{m.group(1)[0]} {m.group(2)}°{m.group(3)}\'{m.group(4)}" {m.group(5)[0]}',
            ),
            # South 56 degrees 40 minutes West -> S 56°40' W (without seconds)
            (
                r"\b(North|South|East|West)\s+(\d{1,3})\s+degrees?\s+(\d{1,2})\s+minutes?\s+(North|South|East|West)\b",
                lambda m: f"{m.group(1)[0]} {m.group(2)}°{m.group(3)}' {m.group(4)[0]}",
            ),
            # North 45 degrees East -> N 45° E
            (
                r"\b(North|South|East|West)\s+(\d{1,3})\s+degrees?\s+(North|South|East|West)\b",
                lambda m: f"{m.group(1)[0]} {m.group(2)}° {m.group(3)[0]}",
            ),
            # Normalize spacing around DMS with seconds
            # NOTE: This pattern is redundant - the lambda above already handles this format
            # (
            #     r"([NS])\s*(\d{1,3})\s*°\s*(\d{1,2})\s*'\s*(\d{1,2}(?:\.\d+)?)\s*\"\s*([EW])",
            #     r'\1 \2°\3\'\4" \5',
            # ),
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
        # Look for BEGINNING/POB/POINT OF BEGINNING
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
        # Patterns for closure to POB (must be at/near end of text)
        # Use \b for word boundaries and require "to" keyword
        closure_patterns = [
            r"\bto\s+(?:the\s+)?(?:point\s+of\s+)?beginning\b",  # to [the] [point of] beginning
            r"\bto\s+(?:the\s+)?POB\b",  # to [the] POB
            r"\breturning\s+to\s+(?:the\s+)?(?:point\s+of\s+)?beginning\b",  # returning to...
            r"\bback\s+to\s+(?:the\s+)?(?:point\s+of\s+)?beginning\b",  # back to...
            r"\bback\s+to\s+(?:the\s+)?POB\b",  # back to POB
        ]

        text_lower = text.lower()

        for pattern in closure_patterns:
            # Must be in last 60 characters (near end of call)
            # to avoid matching "from the point of beginning" at start
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
        # Look for COMMENCING or STARTING patterns that occur BEFORE "POINT OF BEGINNING"
        # This indicates a separate POC from POB
        pob_pattern = r"\b(?:point\s+of\s+)?beginning\b"

        # Check if there's a "POINT OF BEGINNING" later in the text
        has_later_pob = bool(re.search(pob_pattern, text, re.IGNORECASE))

        if not has_later_pob:
            # No separate POB found, so no distinct POC
            return ""

        # Extract POC patterns that come before POB
        poc_patterns = [
            r"COMMENCING\s+at\s+(.*?)(?:;|THENCE)",
            r"STARTING\s+at\s+(.*?)(?:,|;|THENCE)",
        ]

        for pattern in poc_patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                # Verify this comes before "POINT OF BEGINNING"
                poc_text = match.group(1).strip()
                poc_end_pos = match.end()

                # Find position of POB
                pob_match = re.search(pob_pattern, text[poc_end_pos:], re.IGNORECASE)
                if pob_match:
                    # POC comes before POB - this is a valid POC
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
    def split_into_calls(cls, text: str) -> List[str]:
        """Split text into individual THENCE calls.

        Handles multiple formats:
        - Numbered (1., 2., 3.) - checked FIRST (most specific)
        - THENCE keyword separated
        - Semicolon separated

        Args:
            text: Legal description text

        Returns:
            List of call strings
        """
        # Try numbered patterns FIRST (1., 2., etc.) - more specific than THENCE
        if re.search(r"(?:^|\n)\s*\d+\.\s+", text, re.MULTILINE):
            parts = re.split(r"(?:^|\n)\s*(?=\d+\.\s+)", text, flags=re.MULTILINE)
        # Then try splitting on THENCE keyword
        elif re.search(r"\bTHENCE\b", text, re.IGNORECASE):
            parts = re.split(r"\bTHENCE\b", text, flags=re.IGNORECASE)
        # Try semicolon-separated calls (most common in normalized text)
        else:
            parts = text.split(";")

        calls = []
        for part in parts:
            cleaned = part.strip()
            if not cleaned:
                continue

            # Skip POB/BEGINNING lines
            if re.match(r"^\s*(?:BEGINNING|COMMENCING|POB|POINT)", cleaned, re.IGNORECASE):
                continue

            # Remove leading number patterns like "1. " or "2. "
            cleaned = re.sub(r"^\d+\.\s+", "", cleaned)

            # Remove trailing punctuation and whitespace
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
        # Pattern for distance
        pattern = r"(\d+(?:\.\d+)?)\s*(feet|ft|poles?|rods?|perches?|chains?|links?)"

        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = float(match.group(1))
            unit = match.group(2).lower()

            # Normalize unit names
            if unit in ["ft", "feet", "foot"]:
                unit = "feet"
            elif unit in ["pole", "poles"]:
                unit = "poles"
            elif unit in ["rod", "rods"]:
                unit = "rods"
            elif unit in ["perch", "perches"]:
                unit = "perches"
            elif unit in ["chain", "chains"]:
                unit = "chains"
            elif unit in ["link", "links"]:
                unit = "links"

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
        # Fix "5outh" -> "South", "NOrth" -> "North", etc. FIRST
        # This must run before degree symbol fixes so we can handle both formats
        text = re.sub(r"\b5outh\b", "South", text, flags=re.IGNORECASE)
        text = re.sub(r"\bNOrth\b", "North", text, flags=re.IGNORECASE)
        text = re.sub(r"\bEa5t\b", "East", text, flags=re.IGNORECASE)
        text = re.sub(r"\bWe5t\b", "West", text, flags=re.IGNORECASE)

        # Fix common degree symbol OCR errors
        # "S 56 0 40' W" -> "S 56°40' W" (0 mistaken for degree symbol)
        text = re.sub(r"([NS])\s+(\d{1,3})\s+0\s+(\d{1,2})\s*'\s*([EW])", r"\1 \2°\3' \4", text)

        # Also handle full cardinal names: "South 56 0 40' West" -> "South 56 degrees 40 minutes West"
        # This allows standardize_cardinal_directions to convert it properly
        text = re.sub(
            r"\b(North|South)\s+(\d{1,3})\s+0\s+(\d{1,2})\s*'\s*(East|West)\b",
            r"\1 \2 degrees \3 minutes \4",
            text,
            flags=re.IGNORECASE,
        )

        return text

    @classmethod
    def normalize_legal_description(cls, text: str) -> str:
        """Apply all normalization steps to a legal description.

        Args:
            text: Raw legal description text

        Returns:
            Normalized text
        """
        # Step 1: Clean OCR errors
        text = cls.clean_ocr_errors(text)

        # Step 2: Normalize DMS symbols
        text = cls.normalize_dms_symbols(text)

        # Step 3: Merge line-wrapped calls
        text = cls.merge_line_wrapped_calls(text)

        # Step 4: Standardize cardinal directions
        text = cls.standardize_cardinal_directions(text)

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
        # Patterns for exception/inclusion keywords
        # Order matters - check longer phrases first
        split_patterns = [
            (r"\b(?:LESS\s+AND\s+)?EXCEPT(?:ING)?\b", True),  # EXCEPT or LESS AND EXCEPT
            (r"\b(?:ALSO|INCLUDING)\b", False),  # ALSO or INCLUDING
        ]

        tracts = []
        remaining_text = text
        last_end = 0

        # Find all split points
        splits = []
        for pattern, is_exception in split_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                splits.append((match.start(), match.end(), is_exception))

        # Sort by position
        splits.sort(key=lambda x: x[0])

        if not splits:
            # No exceptions - return entire text as main tract
            return [(text, False)]

        # Add main tract (everything before first split)
        first_split_pos = splits[0][0]
        if first_split_pos > 0:
            main_tract = text[:first_split_pos].strip()
            if main_tract:
                tracts.append((main_tract, False))

        # Add subsequent tracts
        for i, (start, end, is_exception) in enumerate(splits):
            # Find where this tract ends (at next split or end of text)
            if i + 1 < len(splits):
                tract_end = splits[i + 1][0]
            else:
                tract_end = len(text)

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

        # Normalized text for searching
        lower_text = call_text.lower()

        # Determine along segment
        along_idx = lower_text.find("along")
        if along_idx != -1:
            segment = call_text[along_idx + len("along") :].lstrip()
            to_tokens = list(re.finditer(r"\bto\b", segment, re.IGNORECASE))
            if to_tokens:
                last_to = to_tokens[-1]
                along = segment[: last_to.start()].strip(" ,;.")
                to_section = segment[last_to.end() :].strip()
                to = re.split(r"[.;]", to_section, maxsplit=1)[0].strip(" ,")
            else:
                along = re.split(r"[.;]", segment, maxsplit=1)[0].strip(" ,")

        # If no 'along' or we still need an endpoint, grab the final 'to'
        if not to:
            to_matches = list(re.finditer(r"\bto\b", call_text, re.IGNORECASE))
            if to_matches:
                last = to_matches[-1]
                to_candidate = call_text[last.end() :].strip()
                to = re.split(r"[.;]", to_candidate, maxsplit=1)[0].strip(" ,")

        return (along, to)
