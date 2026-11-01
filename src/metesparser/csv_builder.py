"""CSV export builder for deed calls (``mp_export.csv_writer`` facade).

Exports structured calls to the standard CSV schema defined in the playbook.
Monolith models are mirrored through ``package_bridge`` and the package writer
does the work, so export eligibility, written files and import results match it.
"""

from pathlib import Path

import mp_export.csv_writer as package_writer

from .models import (
    AuditContext,
    ClosureResult,
    DeedCall,
    LegalDescription,
    SkippedCourse,
    Tract,
)
from .package_bridge import (
    monolith_call,
    package_audit_context,
    package_call,
    package_calls,
    package_legal_description,
    package_result,
    package_skips,
    package_tract,
)


class CSVBuilder:
    """Build and export deed calls to CSV format."""

    FIELDNAMES: list[str] = list(package_writer.FIELDNAMES)

    @classmethod
    def calls_to_csv(
        cls,
        calls: list[DeedCall],
        output_path: str,
        metadata: dict[str, str | int | float | None] | None = None,
    ) -> None:
        """Export calls to CSV file.

        Args:
            calls: List of DeedCall objects
            output_path: Output file path
            metadata: Optional metadata dict (source_doc, exhibit, etc.)
        """
        package_writer.calls_to_csv(package_calls(calls), output_path, metadata)

    @classmethod
    def _call_to_row(cls, call: DeedCall) -> dict[str, str]:
        """Convert a DeedCall to a CSV row dict matching FIELDNAMES."""
        return package_writer._call_to_row(package_call(call))

    @classmethod
    def legal_description_to_csv(
        cls,
        legal_desc: LegalDescription,
        output_path: str,
    ) -> None:
        """Export a LegalDescription to CSV with its metadata sidecar.

        Args:
            legal_desc: LegalDescription object
            output_path: Output file path
        """
        package_writer.legal_description_to_csv(package_legal_description(legal_desc), output_path)

    @classmethod
    def csv_to_calls(
        cls,
        input_path: str,
        *,
        strict: bool = True,
        rejected_rows: list[tuple[int, str]] | None = None,
    ) -> list[DeedCall]:
        """Load calls from a CSV file.

        Args:
            input_path: Input CSV file path
            strict: Reject invalid rows; False permits partial recovery only when
                ``rejected_rows`` is supplied to record each rejected row
            rejected_rows: Receives ``(row_number, error)`` for each rejected row

        Returns:
            List of DeedCall objects
        """
        calls = package_writer.csv_to_calls(input_path, strict=strict, rejected_rows=rejected_rows)
        return [monolith_call(call) for call in calls]

    @classmethod
    def csv_text_to_calls(
        cls,
        text: str,
        *,
        strict: bool = True,
        rejected_rows: list[tuple[int, str]] | None = None,
    ) -> list[DeedCall]:
        """Decode retained CSV text without reopening its original file.

        A rejected row is never dropped silently: strict import raises, and non-strict
        import records it in ``rejected_rows`` (raising when no list is supplied), since
        omitting a course would join its neighbours into a different boundary. Legacy
        21-field CSVs without ``curve_type`` read it back as None; a curved legacy row
        notes that it is treated as circular.
        """
        calls = package_writer.csv_text_to_calls(text, strict=strict, rejected_rows=rejected_rows)
        return [monolith_call(call) for call in calls]

    @classmethod
    def export_verified_csv(
        cls,
        calls: list[DeedCall],
        closure_result: ClosureResult,
        output_path: str,
        legal_desc: LegalDescription | None = None,
        *,
        tract_results: list[tuple[Tract, ClosureResult]] | None = None,
        audit_context: AuditContext | None = None,
        skipped_courses: list[SkippedCourse] | None = None,
    ) -> list[Path]:
        """Export verified CSV(s) through the canonical package gate.

        For multi-tract deeds (tract_results provided), writes one CSV per verified
        main/addition tract; easement and exception tracts are never exported.

        Args:
            calls: List of DeedCall objects
            closure_result: ClosureResult from verification
            output_path: Base output file path
            legal_desc: Optional LegalDescription for metadata
            tract_results: Optional list of (Tract, ClosureResult) for multi-tract
            audit_context: Optional AuditContext for audit trail output. Its
                ``skipped_courses`` and each ``Tract.skipped_courses`` block export,
                as does the explicit ``skipped_courses`` list. The exporter cannot
                see skips it is not given: callers that extracted non-strictly must
                pass the audit context (or tracts) used for extraction.
            skipped_courses: Optional explicit skip records applied to the fresh
                re-check, in addition to those above.

        Returns:
            List of written file paths.

        Raises:
            ValueError: If verification checks did not pass, or (multi-tract) no
                main/addition tract was supplied or verified
        """
        return package_writer.export_verified_csv(
            package_calls(calls),
            package_result(closure_result),
            output_path,
            None if legal_desc is None else package_legal_description(legal_desc),
            tract_results=(
                None
                if tract_results is None
                else [(package_tract(t), package_result(r)) for t, r in tract_results]
            ),
            audit_context=(None if audit_context is None else package_audit_context(audit_context)),
            skipped_courses=None if skipped_courses is None else package_skips(skipped_courses),
        )
