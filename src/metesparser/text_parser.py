"""Text parsing utilities for normalizing legal descriptions.

Compatibility facade over ``mp_parse.normalizer`` and ``mp_parse.metadata``: OCR
clean-up, DMS and cardinal normalisation, course-list analysis, call splitting,
distances, exception clauses and metadata extraction are implemented once by the
package. ``TextParser`` keeps the legacy classmethod API and converts the package's
deed-clause and subdivision models back to the monolith's.
"""

from __future__ import annotations

import mp_parse.metadata as package_metadata
import mp_parse.normalizer as package_normalizer
from mp_parse.metadata import (
    COURSE_LIST_MARKER,
    CourseList,
    CourseListAnalysis,
    CourseListHeader,
    _AreaStatement,
    analyze_course_lists,
    break_inline_course_enumerators,
    course_list_count_mismatches,
)
from mp_parse.numbers import COMMA_NUMBER, parse_comma_number

from .models import DeedClause, SubdivisionReference

# Regex fragment for numbers with optional comma grouping (e.g., "1,200" or "3,500.00")
_COMMA_NUMBER = COMMA_NUMBER

__all__ = [
    "COURSE_LIST_MARKER",
    "CourseList",
    "CourseListAnalysis",
    "CourseListHeader",
    "TextParser",
    "analyze_course_lists",
    "break_inline_course_enumerators",
    "course_list_count_mismatches",
    "parse_comma_number",
]


class TextParser:
    """Parse and normalize legal description text (``mp_parse`` facade)."""

    WATER_BODY_KEYWORDS = package_metadata.WATER_BODY_KEYWORDS
    MEANDER_PATTERNS = package_metadata.MEANDER_PATTERNS
    WATER_PREPOSITION_PATTERN = package_metadata.WATER_PREPOSITION_PATTERN
    INDEFINITE_PATTERNS = package_metadata.INDEFINITE_PATTERNS
    # Canonical cardinal-only pattern (shared with the package; see AGENTS.md).
    CARDINAL_ONLY_PATTERN = package_metadata.CARDINAL_ONLY_PATTERN

    # --- Normalisation (mp_parse.normalizer) ---------------------------------

    @classmethod
    def normalize_dms_symbols(cls, text: str) -> str:
        """Standardize degree/minute/second symbols."""
        return package_normalizer.normalize_dms_symbols(text)

    @classmethod
    def merge_line_wrapped_calls(cls, text: str) -> str:
        """Merge calls that were split across line breaks."""
        return package_normalizer.merge_line_wrapped_calls(text)

    @classmethod
    def standardize_cardinal_directions(cls, text: str) -> str:
        """Standardize cardinal direction abbreviations."""
        return package_normalizer.standardize_cardinal_directions(text)

    @classmethod
    def clean_ocr_errors(cls, text: str) -> str:
        """Fix common OCR errors in legal descriptions."""
        return package_normalizer.clean_ocr_errors(text)

    @classmethod
    def expand_assessor_abbreviations(cls, text: str) -> str:
        """Expand assessor-style abbreviations (e.g. ``N0DEG``, ``FT``, ``DEG``)."""
        return package_normalizer.expand_assessor_abbreviations(text)

    @classmethod
    def expand_abbreviations(cls, text: str) -> str:
        """Expand common legal-description abbreviations."""
        return package_normalizer.expand_abbreviations(text)

    @classmethod
    def normalize_legal_description(cls, text: str) -> str:
        """Apply the full normalisation pipeline to a legal description."""
        return package_normalizer.normalize_legal_description(text)

    # --- Calls and courses (mp_parse.metadata) -------------------------------

    @classmethod
    def split_into_calls(
        cls, text: str, *, course_lists: CourseListAnalysis | None = None
    ) -> list[str]:
        """Split text into individual THENCE calls (numbered, THENCE or semicolon forms)."""
        return package_metadata.split_into_calls(text, course_lists=course_lists)

    @classmethod
    def extract_distance(cls, text: str) -> tuple[float, str]:
        """Extract a call's distance and unit."""
        return package_metadata.extract_distance(text)

    @classmethod
    def detect_meander(cls, text: str) -> bool:
        """Detect whether a call follows a water body (meander line)."""
        return package_metadata.detect_meander(text)

    @classmethod
    def is_indefinite_call(cls, direction_text: str, has_bearing: bool) -> bool:
        """Return whether a call's direction is indefinite."""
        return package_metadata.is_indefinite_call(direction_text, has_bearing)

    @classmethod
    def split_exception_clauses(cls, text: str) -> list[tuple[str, bool]]:
        """Split text into ``(tract_text, is_exception)`` segments."""
        return package_metadata.split_exception_clauses(text)

    @classmethod
    def extract_along_to_fields(cls, call_text: str) -> tuple[str, str]:
        """Extract the verbatim 'along' and 'to' fields of a call."""
        return package_metadata.extract_along_to_fields(call_text)

    # --- Points of beginning / commencement ----------------------------------

    @classmethod
    def extract_pob(cls, text: str) -> str:
        """Extract the Point of Beginning description."""
        return package_metadata.extract_pob(text)

    @classmethod
    def is_closure_to_pob(cls, text: str) -> bool:
        """Return whether text closes back to the Point of Beginning."""
        return package_metadata.is_closure_to_pob(text)

    @classmethod
    def extract_poc(cls, text: str) -> str:
        """Extract the Point of Commencement description."""
        return package_metadata.extract_poc(text)

    @classmethod
    def extract_poc_and_pob(cls, text: str) -> tuple[str, str]:
        """Extract both the Point of Commencement and Point of Beginning."""
        return package_metadata.extract_poc_and_pob(text)

    # --- Metadata ------------------------------------------------------------

    @classmethod
    def extract_area_statement(cls, text: str) -> _AreaStatement | None:
        """Extract the first stated area statement from legal text."""
        return package_metadata.extract_area_statement(text)

    @classmethod
    def extract_plss_metadata(cls, text: str) -> dict[str, str | None]:
        """Extract PLSS section/township/range metadata."""
        return package_metadata.extract_plss_metadata(text)

    @classmethod
    def extract_basis_of_bearing(cls, text: str) -> str | None:
        """Extract the basis-of-bearing statement."""
        return package_metadata.extract_basis_of_bearing(text)

    @classmethod
    def extract_surveyor_certification(cls, text: str) -> str | None:
        """Extract the surveyor certification statement."""
        return package_metadata.extract_surveyor_certification(text)

    @classmethod
    def extract_prior_conveyance(cls, text: str) -> str | None:
        """Extract the prior conveyance reference."""
        return package_metadata.extract_prior_conveyance(text)

    @classmethod
    def extract_deed_clauses(cls, text: str) -> list[DeedClause]:
        """Extract reservation, subject-to and together-with clauses."""
        return [
            DeedClause.model_validate(clause.model_dump())
            for clause in package_metadata.extract_deed_clauses(text)
        ]

    @classmethod
    def extract_subdivision_reference(cls, text: str) -> SubdivisionReference | None:
        """Extract a lot/block/subdivision/plat reference."""
        reference = package_metadata.extract_subdivision_reference(text)
        if reference is None:
            return None
        return SubdivisionReference.model_validate(reference.model_dump())

    @classmethod
    def infer_distance_unit(
        cls, text: str, state: str | None = None, year: int | None = None
    ) -> str | None:
        """Infer the primary distance unit from context (advisory only)."""
        return package_metadata.infer_distance_unit(text, state=state, year=year)

    @classmethod
    def extract_witness_trees(cls, text: str) -> list[str]:
        """Extract witness-tree references."""
        return package_metadata.extract_witness_trees(text)

    @classmethod
    def extract_coordinate_system(cls, text: str) -> tuple[str | None, str | None]:
        """Extract the coordinate system and datum."""
        return package_metadata.extract_coordinate_system(text)
