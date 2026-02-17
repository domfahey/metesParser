"""CSV export for deed calls.

Exports structured calls to the standard 21-field CSV schema.
Reads CSV files back into DeedCall objects.
"""

from __future__ import annotations

import csv
from pathlib import Path

import structlog
from mp_models import (
    AuditContext,
    ClosureResult,
    DeedCall,
    LegalDescription,
    Tract,
    _Model,
)
from pydantic import ValidationError, field_validator

logger = structlog.get_logger(__name__)

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
    "monument_status",
    "is_exception",
    "is_meander",
    "is_tie_in",
    "non_tangent",
    "radial_bearing",
    "notes",
]


class _CSVDeedCallRow(_Model):
    """Validated CSV row shape before building a strict DeedCall."""

    course: int
    direction_text: str
    bearing_quadrant: str | None = None
    bearing_azimuth_deg_from_north: float | None = None
    distance_ft: float
    curve_dir: str | None = None
    radius_ft: float | None = None
    delta_deg: float | None = None
    arc_length_ft: float | None = None
    chord_bearing: str | None = None
    chord_length_ft: float | None = None
    along: str | None = None
    to: str | None = None
    monument_type: str | None = None
    monument_status: str | None = None
    is_exception: bool = False
    is_meander: bool = False
    is_tie_in: bool = False
    non_tangent: bool = False
    radial_bearing: str | None = None
    notes: str | None = None

    @field_validator("is_exception", "is_meander", "is_tie_in", "non_tangent", mode="before")
    @classmethod
    def _normalize_bool_fields(cls, value: object) -> bool:
        return cls._coerce_bool_field(value)


def _call_to_row(call: DeedCall) -> dict[str, str]:
    """Convert a DeedCall to a CSV row dict matching FIELDNAMES schema."""
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
        "monument_status": call.monument_status or "",
        "is_exception": "true" if call.is_exception else "false",
        "is_meander": "true" if call.is_meander else "false",
        "is_tie_in": "true" if call.is_tie_in else "false",
        "non_tangent": "true" if call.non_tangent else "false",
        "radial_bearing": call.radial_bearing or "",
        "notes": call.notes or "",
    }


def _write_metadata(metadata: dict[str, str | int | float | None], output_path: Path) -> None:
    """Write metadata to a text file."""
    with open(output_path, "w") as f:
        f.write("DEED METADATA\n")
        f.write("=" * 60 + "\n\n")
        for key, value in metadata.items():
            if value:
                f.write(f"{key}: {value}\n")


def calls_to_csv(
    calls: list[DeedCall],
    output_path: str,
    metadata: dict[str, str | int | float | None] | None = None,
) -> None:
    """Export calls to CSV file.

    Args:
        calls: List of DeedCall objects.
        output_path: Output file path.
        metadata: Optional metadata dict (source_doc, exhibit, etc.).
    """
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for call in calls:
            row = _call_to_row(call)
            writer.writerow(row)

    if metadata:
        metadata_path = output_file.with_suffix(".metadata.txt")
        _write_metadata(metadata, metadata_path)


def _row_to_call(row: dict[str, str | None], row_number: int | None = None) -> DeedCall | None:
    """Convert a CSV row to a DeedCall object.

    Returns None if the row fails validation.
    """
    try:
        normalized_row = {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
        normalized_row = {k: (None if v == "" else v) for k, v in normalized_row.items()}

        csv_row = _CSVDeedCallRow.model_validate(normalized_row)
        normalized_payload = csv_row.model_dump()
        normalized_payload["is_exception"] = bool(csv_row.is_exception)
        normalized_payload["is_meander"] = bool(csv_row.is_meander)
        normalized_payload["is_tie_in"] = bool(csv_row.is_tie_in)
        normalized_payload["non_tangent"] = bool(csv_row.non_tangent)
        return DeedCall.model_validate(normalized_payload, strict=True)

    except (KeyError, TypeError, ValueError, ValidationError) as e:
        row_label = row_number if row_number is not None else "unknown"
        logger.warning("Skipping invalid CSV row", row=row_label, error=str(e))
        return None


def csv_to_calls(input_path: str) -> list[DeedCall]:
    """Load calls from a CSV file.

    Args:
        input_path: Input CSV file path.

    Returns:
        List of DeedCall objects.
    """
    calls: list[DeedCall] = []

    with open(input_path) as f:
        reader = csv.DictReader(f)
        for row_number, row in enumerate(reader, start=2):
            call = _row_to_call(row, row_number=row_number)
            if call:
                calls.append(call)

    return calls


def legal_description_to_csv(
    legal_desc: LegalDescription,
    output_path: str,
) -> None:
    """Export a LegalDescription to CSV with metadata sidecar.

    Args:
        legal_desc: LegalDescription object.
        output_path: Output file path.
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
        "coordinate_system": legal_desc.coordinate_system,
        "fips_code": legal_desc.fips_code,
        "clauses": (
            "; ".join(f"[{c.clause_type}] {c.text}" for c in legal_desc.clauses)
            if legal_desc.clauses
            else None
        ),
        "subdivision_ref": (
            f"Lot {legal_desc.subdivision_ref.lot or '?'}, "
            f"Block {legal_desc.subdivision_ref.block or '?'}, "
            f"{legal_desc.subdivision_ref.subdivision_name or '?'}"
            if legal_desc.subdivision_ref
            else None
        ),
        "witness_trees": (
            "; ".join(legal_desc.witness_trees) if legal_desc.witness_trees else None
        ),
    }
    calls_to_csv(legal_desc.calls, output_path, metadata)


def export_verified_csv(
    calls: list[DeedCall],
    closure_result: ClosureResult,
    output_path: str,
    legal_desc: LegalDescription | None = None,
    *,
    tract_results: list[tuple[Tract, ClosureResult]] | None = None,
    audit_context: AuditContext | None = None,
) -> list[Path]:
    """Export verified CSV(s).

    For multi-tract deeds (tract_results provided), writes one CSV per tract:
    deed_verified_tract1.csv, deed_verified_tract2.csv, etc.

    Args:
        calls: List of DeedCall objects.
        closure_result: ClosureResult from verification.
        output_path: Base output file path.
        legal_desc: Optional LegalDescription for metadata.
        tract_results: Optional list of (Tract, ClosureResult) for multi-tract.
        audit_context: Optional AuditContext for audit trail output.

    Returns:
        List of written file paths.

    Raises:
        ValueError: If verification checks did not pass.
    """
    if not closure_result.is_fully_verified():
        raise ValueError(
            "Cannot export verified CSV: verification checks failed. "
            f"Misclosure: {closure_result.misclosure_ft:.4f} ft, "
            f"Warnings: {len(closure_result.warnings)}"
        )

    output_file = Path(output_path)
    written_paths: list[Path] = []

    if tract_results:
        for i, (tract, _tract_result) in enumerate(tract_results, start=1):
            tract_path = output_file.with_stem(f"{output_file.stem}_verified_tract{i}")
            calls_to_csv(tract.calls, str(tract_path))
            written_paths.append(tract_path)
            logger.info("Verified tract CSV exported", path=str(tract_path), tract=tract.label)
    else:
        verified_path = output_file.with_stem(output_file.stem + "_verified")
        if legal_desc:
            legal_description_to_csv(legal_desc, str(verified_path))
        else:
            calls_to_csv(calls, str(verified_path))
        written_paths.append(verified_path)
        logger.info("Verified CSV exported", path=str(verified_path))

    summary_path = output_file.with_stem(output_file.stem + "_verified").with_suffix(
        ".verification.txt"
    )
    from mp_verify import get_closure_summary

    summary = get_closure_summary(closure_result)
    with open(summary_path, "w") as f:
        f.write(summary)
    logger.info("Verification summary written", path=str(summary_path))

    if audit_context is not None:
        audit_base = output_file.with_stem(output_file.stem + "_verified")
        audit_json_path = audit_base.with_suffix(".audit.json")
        audit_json_path.write_text(audit_context.model_dump_json(indent=2))
        logger.info("Audit trail written", path=str(audit_json_path))

        from .audit_html import write_report

        audit_html_path = audit_base.with_suffix(".audit.html")
        write_report(audit_context, audit_html_path)
        logger.info("Audit HTML report written", path=str(audit_html_path))

    return written_paths
