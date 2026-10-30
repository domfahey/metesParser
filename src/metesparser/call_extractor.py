"""Extract individual deed calls from legal descriptions.

Compatibility facade over ``mp_parse.calls``: course splitting, skip recording,
bearing and DMS normalisation, curve and chord/radial grammar, distance roles and
the per-call audit are implemented once by the package. This module converts the
package models back to the monolith's, preserving the legacy ``CallExtractor`` and
``MonumentClassifier`` APIs, exceptions, log events and audit behaviour.
"""

from __future__ import annotations

import mp_models
import mp_parse.calls as package_calls
import mp_parse.monuments as package_monuments

from .models import AuditContext, DeedCall, MonumentStatus, MonumentType, SkippedCourse
from .package_bridge import monolith_call, monolith_call_audit, monolith_calls_from, monolith_skip
from .package_bridge import package_calls as to_package_calls

# Canonical cardinal-only pattern (shared with the package; see AGENTS.md).
_CARDINAL_ONLY_PATTERN = package_calls._CARDINAL_ONLY_PATTERN
CURVE_LENGTH_AMBIGUOUS_NOTE = package_calls.CURVE_LENGTH_AMBIGUOUS_NOTE
RADIUS_CONFLICT_NOTE = package_calls.RADIUS_CONFLICT_NOTE


class MonumentClassifier:
    """Classify survey monument types from text descriptions (``mp_parse`` facade)."""

    MONUMENT_PATTERNS: list[tuple[str, MonumentType]] = package_monuments.MONUMENT_PATTERNS
    MONUMENT_STATUS_PATTERNS: list[tuple[str, MonumentStatus]] = (
        package_monuments.MONUMENT_STATUS_PATTERNS
    )

    @classmethod
    def classify_monument(cls, text: str) -> MonumentType | None:
        """Classify monument type from text description (typically the 'to' field)."""
        return package_monuments.classify_monument(text)

    @classmethod
    def classify_monument_status(cls, text: str | None) -> MonumentStatus | None:
        """Classify whether monument status indicates found or set."""
        return package_monuments.classify_monument_status(text)


class CallExtractor:
    """Extract and structure deed calls from legal description text (``mp_parse`` facade)."""

    CURVE_PATTERN = package_calls.CURVE_PATTERN
    PACKED_DMS_PATTERN = package_calls.PACKED_DMS_PATTERN

    @classmethod
    def extract_calls(
        cls,
        text: str,
        distance_unit: str = "feet",
        *,
        audit_context: AuditContext | None = None,
        strict: bool = True,
        skipped_courses: list[SkippedCourse] | None = None,
    ) -> list[DeedCall]:
        """Extract all calls from normalized legal description text.

        Handles exception clauses (EXCEPT, LESS AND EXCEPT, ALSO, INCLUDING)
        and marks calls accordingly. Unlike ``mp_parse.extract_calls`` the text is
        treated as one description: tract markers are not split into ``Tract``s.

        Args:
            text: Normalized legal description text (should already be normalized)
            distance_unit: Primary distance unit (feet, poles, etc.)
            audit_context: Optional audit context for recording parsing decisions
            strict: Raise with course context when a geometric course is malformed.
                Otherwise the course is recorded as a ``SkippedCourse`` (in
                ``audit_context`` and/or ``skipped_courses``) with its course
                number reserved, and blocks verification given that record. With
                neither supplied it raises as in strict mode.
            skipped_courses: Optional list receiving non-strict skipped courses.

        Returns:
            List of DeedCall objects
        """
        # The package records on scratch containers; records are copied back even
        # when it raises, so the caller sees exactly what was recorded before then.
        scratch = (
            mp_models.AuditContext.model_construct(call_audits=[], skipped_courses=[])
            if audit_context is not None
            else None
        )
        scratch_skips: list[mp_models.SkippedCourse] | None = (
            [] if skipped_courses is not None else None
        )
        try:
            calls = package_calls._extract_calls_from_text(
                text,
                distance_unit,
                audit_context=scratch,
                strict=strict,
                course_start=1,
                skipped_courses=scratch_skips,
            )
        finally:
            # One monolith record per package record, shared by both destinations.
            converted: dict[int, SkippedCourse] = {}

            def skip(record: mp_models.SkippedCourse) -> SkippedCourse:
                return converted.setdefault(id(record), monolith_skip(record))

            if audit_context is not None and scratch is not None:
                audit_context.call_audits.extend(
                    monolith_call_audit(audit) for audit in scratch.call_audits
                )
                audit_context.skipped_courses.extend(skip(r) for r in scratch.skipped_courses)
            if skipped_courses is not None and scratch_skips is not None:
                skipped_courses.extend(skip(r) for r in scratch_skips)
        return [monolith_call(call) for call in calls]

    @classmethod
    def extract_single_call(
        cls,
        call_text: str,
        course: int,
        distance_unit: str = "feet",
    ) -> DeedCall | None:
        """Extract a single call from text.

        Args:
            call_text: Text for one call
            course: Course number
            distance_unit: Primary distance unit

        Returns:
            DeedCall object or None if parsing fails
        """
        call = package_calls.extract_single_call(call_text, course, distance_unit)
        return monolith_call(call) if call is not None else None

    @classmethod
    def extract_direction(cls, text: str) -> str:
        """Extract direction/bearing from call text (e.g. "S 56°40' W" or "southwesterly")."""
        return package_calls.extract_direction(text)

    @classmethod
    def extract_distance_alternate(cls, text: str) -> float:
        """Extract distance using alternate patterns such as "125.26' along..." (0.0 if none)."""
        return package_calls.extract_distance_alternate(text)

    @classmethod
    def extract_curve_info(cls, text: str) -> dict[str, float | str | None]:
        """Extract curve information from call text (empty if no curve)."""
        return package_calls.extract_curve_info(text)

    @classmethod
    def mark_tie_in_calls(
        cls, calls: list[DeedCall], poc_description: str | None
    ) -> list[DeedCall]:
        """Mark calls between POC and POB as tie-in calls.

        When a POC exists, calls before (and including) the first call whose
        'to' field references the Point of Beginning are marked as tie-in.

        Args:
            calls: List of DeedCall objects
            poc_description: POC description (None or empty means no POC)

        Returns:
            List of DeedCall objects with is_tie_in set appropriately
        """
        mirrored = to_package_calls(calls)
        marked = package_calls.mark_tie_in_calls(mirrored, poc_description)
        if marked is mirrored:
            return calls
        return monolith_calls_from(calls, mirrored, marked)

    @classmethod
    def enrich_calls_with_azimuths(cls, calls: list[DeedCall]) -> list[DeedCall]:
        """Add azimuths to calls that have quadrant bearings but missing azimuths.

        Args:
            calls: List of DeedCall objects

        Returns:
            List of enriched DeedCall objects
        """
        mirrored = to_package_calls(calls)
        return monolith_calls_from(
            calls, mirrored, package_calls.enrich_calls_with_azimuths(mirrored)
        )
