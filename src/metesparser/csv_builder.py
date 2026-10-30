"""CSV export builder for deed calls.

Exports structured calls to the standard CSV schema defined in the playbook.
"""

import csv
import io
from pathlib import Path

import mp_models
import structlog
from mp_verify.closure import skips_for_tract as package_skips_for_tract
from pydantic import ValidationError, field_validator

from .models import (
    AuditContext,
    ClosureResult,
    DeedCall,
    LegalDescription,
    SkippedCourse,
    Tract,
    _Model,
)
from .package_bridge import monolith_skips, package_skips

logger = structlog.get_logger(__name__)


def _misclosure_text(result: ClosureResult) -> str:
    """Misclosure for messages; an undetermined misclosure is never shown as 0.0."""
    return f"{result.misclosure_ft:.4f} ft" if result.misclosure_available else "not determined"


def skips_for_tract(
    tract: Tract, all_tracts: list[Tract], extra_skips: list[SkippedCourse]
) -> list[SkippedCourse]:
    """Monolith-typed adapter over the shared ``mp_verify`` per-tract skip routing."""

    def mirror(t: Tract) -> mp_models.Tract:
        return mp_models.Tract.model_construct(
            label=t.label,
            tract_type=t.tract_type,
            calls=[],
            skipped_courses=package_skips(t.skipped_courses),
        )

    routed = package_skips_for_tract(
        mirror(tract), [mirror(t) for t in all_tracts], package_skips(extra_skips)
    )
    return monolith_skips(routed)


def _cleanup_stale_sidecars(output_file: Path, *, metadata_written: bool) -> None:
    """Remove exact sidecars a successful raw CSV rewrite can no longer support."""
    sidecars = []
    if not metadata_written:
        sidecars.append(output_file.with_suffix(".metadata.txt"))
    if output_file.stem.endswith("_verified"):
        sidecars.extend(
            output_file.with_suffix(suffix)
            for suffix in (".verification.txt", ".audit.json", ".audit.html")
        )
    for sidecar in sidecars:
        if sidecar.exists():
            sidecar.unlink()


def _format_float(value: float, decimal_places: int) -> str:
    """Keep familiar formatting when exact, otherwise retain roundtrip precision."""
    formatted = f"{value:.{decimal_places}f}"
    return formatted if float(formatted) == value else repr(value)


_ROW_ERRORS = (KeyError, TypeError, ValueError, ValidationError)


class _CSVDeedCallRow(_Model):
    """Validated CSV row shape before building a strict DeedCall."""

    course: int
    direction_text: str
    bearing_quadrant: str | None = None
    bearing_azimuth_deg_from_north: float | None = None
    # Blank only where DeedCall allows it (a spiral with no stated length).
    distance_ft: float | None = None
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
    curve_type: str | None = None

    @field_validator("is_exception", "is_meander", "is_tie_in", "non_tangent", mode="before")
    @classmethod
    def _normalize_bool_fields(cls, value: object) -> bool:
        return cls._coerce_bool_field(value)


class CSVBuilder:
    """Build and export deed calls to CSV format."""

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
        # Appended last so the historical 21-column order is unchanged.
        "curve_type",
    ]

    @staticmethod
    def _labelled_skips(
        audit_context: AuditContext | None, explicit: list[SkippedCourse] | None
    ) -> list[SkippedCourse]:
        """Explicit and audit-context skip records, before tract routing."""
        return [
            *(explicit or []),
            *(audit_context.skipped_courses if audit_context is not None else []),
        ]

    @classmethod
    def _single_description_skips(
        cls,
        legal_desc: LegalDescription | None,
        audit_context: AuditContext | None,
        explicit: list[SkippedCourse] | None,
    ) -> list[SkippedCourse]:
        """Every skip blocking a single-description export, including each tract's own."""
        labelled = cls._labelled_skips(audit_context, explicit)
        skips = list(labelled)
        tracts = legal_desc.tracts if legal_desc is not None else []
        for tract in tracts:
            skips.extend(
                skip for skip in skips_for_tract(tract, tracts, labelled) if skip not in skips
            )
        return skips

    @staticmethod
    def _validate_export_geometry(
        calls: list[DeedCall],
        closure_result: ClosureResult,
        legal_desc: LegalDescription | None,
        *,
        independent_tract: bool = False,
        skipped_courses: list[SkippedCourse] | None = None,
    ) -> list[DeedCall]:
        """Require the supplied verification to describe the calls actually exported."""
        selected_calls = legal_desc.calls if legal_desc is not None else calls
        if legal_desc is not None and [c.model_dump() for c in calls] != [
            c.model_dump() for c in selected_calls
        ]:
            raise ValueError(
                "Cannot export verified CSV: calls do not match LegalDescription.calls"
            )

        stated_area = 0.0
        if legal_desc is not None and legal_desc.stated_area_sq_ft is not None:
            stated_area = legal_desc.stated_area_sq_ft
        from .closure_checker import ClosureChecker

        verifier = (
            ClosureChecker.verify_tract if independent_tract else ClosureChecker.verify_closure
        )
        fresh_result = verifier(
            selected_calls, stated_area_sq_ft=stated_area, skipped_courses=skipped_courses
        )
        if not fresh_result.is_fully_verified():
            raise ValueError(
                "Cannot export verified CSV: selected calls failed fresh verification. "
                f"Misclosure: {_misclosure_text(fresh_result)}, "
                f"Warnings: {len(fresh_result.warnings)}"
            )
        # Source review is an explicit human assessment, independent of fresh geometry.
        excluded = {"source_review_status"}
        if not {"checks", "source_review_status"} & closure_result.model_fields_set:
            # Historical results lack structured checks and used an older heuristic score.
            excluded.update({"checks", "confidence_score"})
        if closure_result.model_dump(exclude=excluded) != fresh_result.model_dump(exclude=excluded):
            raise ValueError(
                "Cannot export verified CSV: closure result does not match selected calls"
            )
        return selected_calls

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

            writer.writeheader()
            for call in calls:
                row = cls._call_to_row(call)
                writer.writerow(row)

        if metadata:
            metadata_path = output_file.with_suffix(".metadata.txt")
            cls._write_metadata(metadata, metadata_path)
        _cleanup_stale_sidecars(output_file, metadata_written=bool(metadata))

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
                _format_float(call.bearing_azimuth_deg_from_north, 6)
                if call.bearing_azimuth_deg_from_north is not None
                else ""
            ),
            "distance_ft": (
                _format_float(call.distance_ft, 2) if call.distance_ft is not None else ""
            ),
            "curve_dir": call.curve_dir or "",
            "radius_ft": _format_float(call.radius_ft, 2) if call.radius_ft is not None else "",
            "delta_deg": _format_float(call.delta_deg, 6) if call.delta_deg is not None else "",
            "arc_length_ft": _format_float(call.arc_length_ft, 2)
            if call.arc_length_ft is not None
            else "",
            "chord_bearing": call.chord_bearing or "",
            "chord_length_ft": (
                _format_float(call.chord_length_ft, 2) if call.chord_length_ft is not None else ""
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
            "curve_type": call.curve_type or "",
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
            "coordinate_system": legal_desc.coordinate_system,
            "fips_code": legal_desc.fips_code,
            "clauses": (
                "; ".join(f"[{c.clause_type}] {c.text}" for c in legal_desc.clauses)
                if legal_desc.clauses
                else None
            ),
            "subdivision_ref": (
                f"Lot {legal_desc.subdivision_ref.lot or '?'}, Block {legal_desc.subdivision_ref.block or '?'}, {legal_desc.subdivision_ref.subdivision_name or '?'}"
                if legal_desc.subdivision_ref
                else None
            ),
            "witness_trees": (
                "; ".join(legal_desc.witness_trees) if legal_desc.witness_trees else None
            ),
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
        with open(input_path) as f:
            return cls.csv_text_to_calls(f.read(), strict=strict, rejected_rows=rejected_rows)

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
        21-field CSVs without ``curve_type`` read it back as None.
        """
        calls = []
        for row_number, row in enumerate(csv.DictReader(io.StringIO(text)), start=2):
            try:
                calls.append(cls._validate_row(row))
            except _ROW_ERRORS as e:
                logger.warning("Invalid CSV row", row=row_number, error=str(e))
                if strict:
                    raise ValueError(
                        f"Cannot import complete parcel: invalid CSV row {row_number}"
                    ) from e
                if rejected_rows is None:
                    raise ValueError(
                        f"Cannot import parcel: invalid CSV row {row_number}; non-strict "
                        "import requires rejected_rows to record each rejected course"
                    ) from e
                rejected_rows.append((row_number, str(e)))

        return calls

    @staticmethod
    def _validate_row(row: dict[str, str | None]) -> DeedCall:
        """Convert a CSV row to a strict DeedCall, raising when the row is invalid."""
        normalized_row = {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
        normalized_row = {k: (None if v == "" else v) for k, v in normalized_row.items()}

        csv_row = _CSVDeedCallRow.model_validate(normalized_row)
        normalized_payload = csv_row.model_dump()
        normalized_payload["is_exception"] = bool(csv_row.is_exception)
        normalized_payload["is_meander"] = bool(csv_row.is_meander)
        normalized_payload["is_tie_in"] = bool(csv_row.is_tie_in)
        normalized_payload["non_tangent"] = bool(csv_row.non_tangent)
        return DeedCall.model_validate(normalized_payload, strict=True)

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
            return cls._validate_row(row)
        except _ROW_ERRORS as e:
            row_label = row_number if row_number is not None else "unknown"
            logger.warning("Invalid CSV row", row=row_label, error=str(e))
            return None

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
        """Export verified CSV(s).

        For multi-tract deeds (tract_results provided), writes one CSV per tract.

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
            ValueError: If verification checks did not pass
        """
        # Multi-tract mode gates per tract, but at least one tract must verify.
        if tract_results:
            if not any(result.is_fully_verified() for _, result in tract_results):
                raise ValueError(
                    "Cannot export verified CSV: no tract passed verification. "
                    f"Tracts checked: {len(tract_results)}"
                )
        elif not closure_result.is_fully_verified():
            raise ValueError(
                "Cannot export verified CSV: verification checks failed. "
                f"Misclosure: {_misclosure_text(closure_result)}, "
                f"Warnings: {len(closure_result.warnings)}"
            )

        output_file = Path(output_path)
        written_paths: list[Path] = []

        # Validate every selected successful result before writing any output.
        if tract_results:
            for tract, result in tract_results:
                if result.is_fully_verified():
                    selected = LegalDescription(
                        calls=tract.calls, stated_area_sq_ft=tract.stated_area_sq_ft
                    )
                    cls._validate_export_geometry(
                        tract.calls,
                        result,
                        selected,
                        independent_tract=True,
                        skipped_courses=skips_for_tract(
                            tract,
                            [t for t, _ in tract_results],
                            cls._labelled_skips(audit_context, skipped_courses),
                        ),
                    )
        else:
            cls._validate_export_geometry(
                calls,
                closure_result,
                legal_desc,
                skipped_courses=cls._single_description_skips(
                    legal_desc, audit_context, skipped_courses
                ),
            )

        if tract_results:
            for i, (tract, tract_result) in enumerate(tract_results, start=1):
                if not tract_result.is_fully_verified():
                    logger.warning(
                        "Skipping unverified tract",
                        tract=tract.label,
                        misclosure_ft=(
                            tract_result.misclosure_ft
                            if tract_result.misclosure_available
                            else None
                        ),
                        warnings_count=len(tract_result.warnings),
                    )
                    continue
                tract_path = output_file.with_stem(f"{output_file.stem}_verified_tract{i}")
                cls.calls_to_csv(tract.calls, str(tract_path))
                written_paths.append(tract_path)
                logger.info("Verified tract CSV exported", path=str(tract_path), tract=tract.label)

        else:
            verified_path = output_file.with_stem(output_file.stem + "_verified")
            if legal_desc:
                cls.legal_description_to_csv(legal_desc, str(verified_path))
            else:
                cls.calls_to_csv(calls, str(verified_path))
            written_paths.append(verified_path)
            logger.info("Verified CSV exported", path=str(verified_path))

        summary_path = output_file.with_stem(output_file.stem + "_verified").with_suffix(
            ".verification.txt"
        )
        from .closure_checker import ClosureChecker

        if tract_results:
            summaries: list[str] = []
            for tract, tract_result in tract_results:
                if not tract_result.is_fully_verified():
                    continue
                summaries.append(f"--- {tract.label} ---")
                summaries.append(ClosureChecker.get_closure_summary(tract_result))
                summaries.append("")
            unverified = [(t, r) for t, r in tract_results if not r.is_fully_verified()]
            if unverified:
                summaries.append("Not verified (no CSV written):")
                for tract, tract_result in unverified:
                    reasons = "; ".join(tract_result.warnings) or "verification checks did not pass"
                    summaries.append(
                        f"{tract.label}: misclosure {_misclosure_text(tract_result)}; {reasons}"
                    )
                summaries.append("")
            with open(summary_path, "w") as f:
                f.write("\n".join(summaries))
        else:
            summary = ClosureChecker.get_closure_summary(closure_result)
            with open(summary_path, "w") as f:
                f.write(summary)
        logger.info("Verification summary written", path=str(summary_path))

        if audit_context is not None:
            audit_base = output_file.with_stem(output_file.stem + "_verified")
            audit_json_path = audit_base.with_suffix(".audit.json")

            audit_json_path.write_text(audit_context.model_dump_json(indent=2))
            logger.info("Audit trail written", path=str(audit_json_path))

            from .audit_reporter import AuditReporter

            audit_html_path = audit_base.with_suffix(".audit.html")

            AuditReporter.write_report(audit_context, audit_html_path)
            logger.info("Audit HTML report written", path=str(audit_html_path))

        return written_paths
