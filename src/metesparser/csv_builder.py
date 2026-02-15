"""CSV export builder for deed calls.

Exports structured calls to the standard CSV schema defined in the playbook.
"""

import csv
from pathlib import Path

import structlog
from pydantic import ValidationError

from .models import ClosureResult, DeedCall, LegalDescription

logger = structlog.get_logger(__name__)


class CSVBuilder:
    """Build and export deed calls to CSV format."""

    # Standard CSV schema (18 fields)
    FIELDNAMES: list[str] = [
        "course",
        "direction_text",
        "bearing_quadrant",
        "bearing_azimuth_deg_from_north",
        "distance_ft",
        "curve_dir",
        "radius_ft",
        "delta_deg",
        "arc_length_ft",
        "chord_bearing",
        "chord_length_ft",
        "along",
        "to",
        "monument_type",
        "is_exception",
        "non_tangent",
        "radial_bearing",
        "notes",
    ]

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
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=cls.FIELDNAMES)

            # Write header
            writer.writeheader()
            # Write calls
            for call in calls:
                row = cls._call_to_row(call)
                writer.writerow(row)

        if metadata:
            metadata_path = output_file.with_suffix(".metadata.txt")
            cls._write_metadata(metadata, metadata_path)

    @classmethod
    def _call_to_row(cls, call: DeedCall) -> dict[str, str]:
        """Convert a DeedCall to a CSV row dict.

        Args:
            call: DeedCall object

        Returns:
            Dict matching FIELDNAMES schema
        """
        return {
            "course": str(call.course),
            "direction_text": call.direction_text,
            "bearing_quadrant": call.bearing_quadrant or "",
            "bearing_azimuth_deg_from_north": (
                f"{call.bearing_azimuth_deg_from_north:.6f}"
                if call.bearing_azimuth_deg_from_north is not None
                else ""
            ),
            "distance_ft": f"{call.distance_ft:.2f}",
            "curve_dir": call.curve_dir or "",
            "radius_ft": f"{call.radius_ft:.2f}" if call.radius_ft is not None else "",
            "delta_deg": f"{call.delta_deg:.6f}" if call.delta_deg is not None else "",
            "arc_length_ft": f"{call.arc_length_ft:.2f}" if call.arc_length_ft is not None else "",
            "chord_bearing": call.chord_bearing or "",
            "chord_length_ft": (
                f"{call.chord_length_ft:.2f}" if call.chord_length_ft is not None else ""
            ),
            "along": call.along or "",
            "to": call.to or "",
            "monument_type": call.monument_type or "",
            "is_exception": "true" if call.is_exception else "false",
            "non_tangent": "true" if call.non_tangent else "false",
            "radial_bearing": call.radial_bearing or "",
            "notes": call.notes or "",
        }

    @classmethod
    def legal_description_to_csv(
        cls,
        legal_desc: LegalDescription,
        output_path: str,
    ) -> None:
        """Export a LegalDescription to CSV.

        Args:
            legal_desc: LegalDescription object
            output_path: Output file path
        """
        metadata: dict[str, str | int | float | None] = {
            "poc_description": legal_desc.poc_description,
            "pob_description": legal_desc.pob_description,
            "source_doc": legal_desc.source_doc,
            "exhibit": legal_desc.exhibit,
            "page": legal_desc.page,
            "survey_date": legal_desc.survey_date,
            "basis_of_bearing": legal_desc.basis_of_bearing,
            "datum": legal_desc.datum,
            "distance_unit": legal_desc.distance_unit,
            "section": legal_desc.section,
            "township": legal_desc.township,
            "range": legal_desc.range,
            "principal_meridian": legal_desc.principal_meridian,
            "aliquot": legal_desc.aliquot,
            "surveyor_certification": legal_desc.surveyor_certification,
            "prior_conveyance": legal_desc.prior_conveyance,
        }
        cls.calls_to_csv(legal_desc.calls, output_path, metadata)

    @classmethod
    def _write_metadata(
        cls, metadata: dict[str, str | int | float | None], output_path: Path
    ) -> None:
        """Write metadata to a text file.

        Args:
            metadata: Metadata dict
            output_path: Output file path
        """
        with open(output_path, "w") as f:
            f.write("DEED METADATA\n")
            f.write("=" * 60 + "\n\n")
            for key, value in metadata.items():
                if value:
                    f.write(f"{key}: {value}\n")

    @classmethod
    def csv_to_calls(cls, input_path: str) -> list[DeedCall]:
        """Load calls from a CSV file.

        Args:
            input_path: Input CSV file path

        Returns:
            List of DeedCall objects
        """
        calls = []

        with open(input_path) as f:
            reader = csv.DictReader(f)

            for row_number, row in enumerate(reader, start=2):
                call = cls._row_to_call(row, row_number=row_number)
                if call:
                    calls.append(call)

        return calls

    @classmethod
    def _row_to_call(
        cls, row: dict[str, str | None], row_number: int | None = None
    ) -> DeedCall | None:
        """Convert a CSV row to a DeedCall object.

        Args:
            row: CSV row dict

        Returns:
            DeedCall object or None if parsing fails
        """
        try:
            # Trim all text values first
            normalized_row = {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
            normalized_row = {k: (None if v == "" else v) for k, v in normalized_row.items()}

            return DeedCall.model_validate(normalized_row, strict=False)

        except (KeyError, TypeError, ValueError, ValidationError) as e:
            row_label = row_number if row_number is not None else "unknown"
            logger.warning("Skipping invalid CSV row", row=row_label, error=str(e))
            return None

    @classmethod
    def export_verified_csv(
        cls,
        calls: list[DeedCall],
        closure_result: ClosureResult,
        output_path: str,
        legal_desc: LegalDescription | None = None,
    ) -> None:
        """Export verified CSV only if all checks pass.

        Adds '_verified' suffix to filename.

        Args:
            calls: List of DeedCall objects
            closure_result: ClosureResult from verification
            output_path: Base output file path
            legal_desc: Optional LegalDescription for metadata

        Raises:
            ValueError: If verification checks did not pass
        """
        if not closure_result.is_fully_verified():
            raise ValueError(
                "Cannot export verified CSV: verification checks failed. "
                f"Misclosure: {closure_result.misclosure_ft:.4f} ft, "
                f"Warnings: {len(closure_result.warnings)}"
            )

        # Add '_verified' suffix
        output_file = Path(output_path)
        verified_path = output_file.with_stem(output_file.stem + "_verified")

        # Export
        if legal_desc:
            cls.legal_description_to_csv(legal_desc, str(verified_path))
        else:
            cls.calls_to_csv(calls, str(verified_path))

        # Also write closure summary
        summary_path = verified_path.with_suffix(".verification.txt")
        from .closure_checker import ClosureChecker

        summary = ClosureChecker.get_closure_summary(closure_result)
        with open(summary_path, "w") as f:
            f.write(summary)

        logger.info("Verified CSV exported", path=str(verified_path))
        logger.info("Verification summary written", path=str(summary_path))
