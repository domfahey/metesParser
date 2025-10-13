"""Text parsing utilities for normalizing legal descriptions.

Handles cleaning up OCR errors, standardizing DMS notation, merging line breaks, etc.
"""

import re
from typing import List


class TextParser:
    """Parse and normalize legal description text."""

    # Common OCR substitution errors
    OCR_FIXES = {
        "°": ["0", "º", "°"],  # Degree symbol variations
        "'": ["'", "'", "`"],  # Minute symbol variations
        '"': ['"', '"', """],  # Second symbol variations
        "1": ["l", "I"],  # Number 1 vs letter l/I
        "4": ["A"],  # Number 4 vs letter A (rare)
        "7": ["T"],  # Number 7 vs letter T (rare)
        "S": ["5"],  # Letter S vs number 5
        "O": ["0"],  # Letter O vs number 0
    }

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
        text = re.sub(r"[""\u201C\u201D]", '"', text)

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
            # South 56 degrees 40 minutes West -> S 56°40' W
            (
                r"\b(North|South|East|West)\s+(\d{1,3})\s+degrees?\s+(\d{1,2})\s+minutes?\s+(North|South|East|West)\b",
                lambda m: f"{m.group(1)[0]} {m.group(2)}°{m.group(3)}' {m.group(4)[0]}",
            ),
            # North 45 degrees East -> N 45° E
            (
                r"\b(North|South|East|West)\s+(\d{1,3})\s+degrees?\s+(North|South|East|West)\b",
                lambda m: f"{m.group(1)[0]} {m.group(2)}° {m.group(3)[0]}",
            ),
            # Normalize spacing around DMS
            (r"([NS])\s*(\d{1,3})\s*°\s*(\d{1,2})\s*'\s*(\d{1,2}(?:\.\d+)?)\s*\"\s*([EW])", r"\1 \2°\3'\4\" \5"),
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
    def split_into_calls(cls, text: str) -> List[str]:
        """Split text into individual THENCE calls.

        Args:
            text: Legal description text

        Returns:
            List of call strings
        """
        # Split on THENCE keyword
        parts = re.split(r"\bTHENCE\b", text, flags=re.IGNORECASE)

        calls = []
        for part in parts:
            cleaned = part.strip()
            if not cleaned:
                continue

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
            text: OCR'd text

        Returns:
            Cleaned text
        """
        # Fix common degree symbol OCR errors
        # "S 56 0 40' W" -> "S 56°40' W" (0 mistaken for degree)
        text = re.sub(r"([NS])\s+(\d{1,3})\s+0\s+(\d{1,2})\s*'\s*([EW])", r"\1 \2°\3' \4", text)

        # Fix "5outh" -> "South", etc.
        text = re.sub(r"\b5outh\b", "South", text, flags=re.IGNORECASE)
        text = re.sub(r"\bNOrth\b", "North", text, flags=re.IGNORECASE)
        text = re.sub(r"\bEa5t\b", "East", text, flags=re.IGNORECASE)
        text = re.sub(r"\bWe5t\b", "West", text, flags=re.IGNORECASE)

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
    def extract_along_to_fields(cls, call_text: str) -> tuple[str, str]:
        """Extract 'along' and 'to' fields from a call description.

        Args:
            call_text: Single call text

        Returns:
            Tuple of (along, to) descriptions
        """
        along = ""
        to = ""

        # Look for "along X to Y" pattern
        along_pattern = r"along\s+(.*?)\s+to\s+(.*?)(?:\.|;|$)"
        match = re.search(along_pattern, call_text, re.IGNORECASE | re.DOTALL)
        if match:
            along = match.group(1).strip()
            to = match.group(2).strip()
        else:
            # Try just "along X"
            along_match = re.search(r"along\s+(.*?)(?:\.|;|$)", call_text, re.IGNORECASE | re.DOTALL)
            if along_match:
                along = along_match.group(1).strip()

            # Try just "to X"
            to_match = re.search(r"to\s+(.*?)(?:\.|;|$)", call_text, re.IGNORECASE | re.DOTALL)
            if to_match:
                to = to_match.group(1).strip()

        return (along, to)
