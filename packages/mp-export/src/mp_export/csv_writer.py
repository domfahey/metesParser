"""CSV export for deed calls.

Exports structured calls to the standard 22-field CSV schema.
Reads CSV files back into DeedCall objects, including legacy 21-field files
(written before ``curve_type`` was appended; it then reads back as None, and a
curved legacy row records in its notes that it is treated as circular).
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import structlog
from mp_models import (
    LEGACY_CURVE_NOTE,
    AuditContext,
    ClosureResult,
    DeedCall,
    LegalDescription,
    SkippedCourse,
    Tract,
    _Model,
    is_boundary_tract,
    non_boundary_detail,
    roles_need_review,
    roles_review_detail,
    tract_kind,
)
from mp_verify.closure import skips_for_tract
from pydantic import ValidationError, field_validator

logger = structlog.get_logger(__name__)


def _misclosure_text(result: ClosureResult) -> str:
    """Misclosure for messages; an undetermined misclosure is never shown as 0.0."""
    return f"{result.misclosure_ft:.4f} ft" if result.misclosure_available else "not determined"


def _format_float(value: float, decimal_places: int) -> str:
    """Keep familiar formatting when exact, otherwise retain roundtrip precision."""
    formatted = f"{value:.{decimal_places}f}"
    return formatted if float(formatted) == value else repr(value)


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

# Header of CSVs written before ``curve_type`` was exported; still accepted on import.
LEGACY_FIELDNAMES: list[str] = FIELDNAMES[:-1]


# A legacy row cannot say whether a curve was a spiral; make the assumption visible.


def is_supported_csv_header(header: list[str] | None) -> bool:
    """Return True for the current exact header or the legacy 21-field header."""
    return header in (FIELDNAMES, LEGACY_FIELDNAMES)


def _require_supported_header(header: list[str] | None) -> None:
    """Raise ValueError naming missing/unexpected columns unless the header is supported."""
    if is_supported_csv_header(header):
        return
    got = header or []
    missing = [c for c in FIELDNAMES if c not in got]
    unexpected = [c for c in got if c not in FIELDNAMES]
    detail = []
    if missing:
        detail.append(f"missing columns: {', '.join(missing)}")
    if unexpected:
        detail.append(f"unexpected columns: {', '.join(unexpected)}")
    if not detail:
        detail.append("columns are duplicated or out of order")
    raise ValueError(
        "Unsupported CSV header: expected the exact ordered 22-field call schema "
        f"(or the legacy 21-field schema without curve_type); {'; '.join(detail)}"
    )


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


def _call_to_row(call: DeedCall) -> dict[str, str]:
    """Convert a DeedCall to a CSV row dict matching FIELDNAMES schema."""
    return {
        "course": str(call.course),
        "direction_text": call.direction_text,
        "bearing_quadrant": call.bearing_quadrant or "",
        "bearing_azimuth_deg_from_north": (
            _format_float(call.bearing_azimuth_deg_from_north, 6)
            if call.bearing_azimuth_deg_from_north is not None
            else ""
        ),
        "distance_ft": (_format_float(call.distance_ft, 2) if call.distance_ft is not None else ""),
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


def _write_metadata(metadata: dict[str, str | int | float | None], output_path: Path) -> None:
    """Write metadata to a text file."""
    with open(output_path, "w") as f:
        f.write("DEED METADATA\n")
        f.write("=" * 60 + "\n\n")
        for key, value in metadata.items():
            if value:
                f.write(f"{key}: {value}\n")


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


def _labelled_skips(
    audit_context: AuditContext | None, explicit: list[SkippedCourse] | None
) -> list[SkippedCourse]:
    """Explicit and audit-context skip records, before tract routing."""
    return [
        *(explicit or []),
        *(audit_context.skipped_courses if audit_context is not None else []),
    ]


_ROLE_CHECK = "non_boundary_tract"


def _role_mismatch(tract: Tract, result: ClosureResult) -> bool:
    """Whether the result carries a tract-role verdict that is not this tract's own."""
    expected = (
        None
        if is_boundary_tract(tract.tract_type)
        else non_boundary_detail(tract.label, tract.tract_type)
    )
    role_details = [c.detail for c in result.checks if c.name == _ROLE_CHECK]
    role_details += [w for w in result.warnings if w.startswith(f"{_ROLE_CHECK}:")]
    return any(detail != expected for detail in role_details)


def _exportable(tract: Tract, result: ClosureResult) -> bool:
    """A verified parcel-boundary tract; easement/exception tracts never qualify."""
    return (
        is_boundary_tract(tract.tract_type)
        and not _role_mismatch(tract, result)
        and result.is_fully_verified()
    )


def _not_exported_reason(tract: Tract, result: ClosureResult) -> str:
    """Why a tract got no verified CSV, derived from the tract itself."""
    if _role_mismatch(tract, result):
        return "supplied verification result does not belong to this tract"
    reasons = [w for w in result.warnings if not w.startswith(f"{_ROLE_CHECK}:")]
    if not is_boundary_tract(tract.tract_type):
        reasons.insert(0, non_boundary_detail(tract.label, tract.tract_type))
    return "; ".join(reasons) or "verification checks did not pass"


def _known_tracts(
    legal_desc: LegalDescription | None, tract_results: list[tuple[Tract, ClosureResult]]
) -> list[Tract]:
    """Every tract the caller knows, so a skip labelled with an omitted tract stays with it."""
    known = [t for t, _ in tract_results]
    labels = {t.label for t in known}
    for tract in legal_desc.tracts if legal_desc is not None else []:
        if tract.label not in labels:
            known.append(tract)
            labels.add(tract.label)
    return known


def _single_description_skips(
    legal_desc: LegalDescription | None,
    audit_context: AuditContext | None,
    explicit: list[SkippedCourse] | None,
) -> list[SkippedCourse]:
    """Every skip blocking a single-description export, including each tract's own."""
    labelled = _labelled_skips(audit_context, explicit)
    skips = list(labelled)
    tracts = legal_desc.tracts if legal_desc is not None else []
    for tract in tracts:
        skips.extend(skip for skip in skips_for_tract(tract, tracts, labelled) if skip not in skips)
    return skips


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
        raise ValueError("Cannot export verified CSV: calls do not match LegalDescription.calls")

    stated_area = 0.0
    if legal_desc is not None and legal_desc.stated_area_sq_ft is not None:
        stated_area = legal_desc.stated_area_sq_ft
    from mp_verify import verify_closure, verify_tract

    verifier = verify_tract if independent_tract else verify_closure
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
        raise ValueError("Cannot export verified CSV: closure result does not match selected calls")
    return selected_calls


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
    _cleanup_stale_sidecars(output_file, metadata_written=bool(metadata))


class _RowWidthError(ValueError):
    """A data row whose cell count differs from the header."""


_ROW_ERRORS = (KeyError, TypeError, ValueError, ValidationError)


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
    call = DeedCall.model_validate(normalized_payload, strict=True)
    if "curve_type" in row or not call.is_curve() or LEGACY_CURVE_NOTE in (call.notes or ""):
        return call
    normalized_payload["notes"] = "; ".join(filter(None, (call.notes, LEGACY_CURVE_NOTE)))
    return DeedCall.model_validate(normalized_payload, strict=True)


def csv_to_calls(
    input_path: str,
    *,
    strict: bool = True,
    rejected_rows: list[tuple[int, str]] | None = None,
) -> list[DeedCall]:
    """Load calls from a CSV file.

    Args:
        input_path: Input CSV file path.
        strict: Reject invalid rows; False permits partial recovery only when
            ``rejected_rows`` is supplied to record each rejected row.
        rejected_rows: Receives ``(row_number, error)`` for each rejected row.

    Returns:
        List of DeedCall objects.
    """
    with open(input_path, encoding="utf-8-sig", newline="") as f:
        return csv_text_to_calls(f.read(), strict=strict, rejected_rows=rejected_rows)


def csv_text_to_calls(
    text: str,
    *,
    strict: bool = True,
    rejected_rows: list[tuple[int, str]] | None = None,
) -> list[DeedCall]:
    """Decode retained CSV text without requiring or reopening its original file.

    A rejected row is never dropped silently: strict import raises, and non-strict
    import records it in ``rejected_rows`` (raising when no list is supplied), since
    omitting a course would join its neighbours into a different boundary. The header
    must be the exact current or legacy schema; anything else raises ValueError.

    Row numbers in errors and ``rejected_rows`` are the physical line (1-based, header
    is line 1) on which the rejected record starts, not a record count.
    """
    calls: list[DeedCall] = []
    text = text.removeprefix("\ufeff")
    reader = csv.reader(io.StringIO(text), strict=True)
    try:
        header = next(reader, None)
        _require_supported_header(header)
        assert header is not None
        while True:
            # Physical line where the record starts (a quoted cell may span lines).
            row_number = reader.line_num + 1
            values = next(reader, None)
            if values is None:
                break
            if not values:
                continue  # blank lines are skipped; a row of empty cells is still malformed
            try:
                if len(values) != len(header):
                    raise _RowWidthError(f"expected {len(header)} cells, got {len(values)}")
                calls.append(_validate_row(dict(zip(header, values, strict=True))))
            except _ROW_ERRORS as e:
                logger.warning("Invalid CSV row", row=row_number, error=str(e))
                if strict:
                    raise ValueError(
                        f"Cannot import complete parcel: invalid CSV row {row_number}: {e}"
                        if isinstance(e, _RowWidthError)
                        else f"Cannot import complete parcel: invalid CSV row {row_number}"
                    ) from e
                if rejected_rows is None:
                    raise ValueError(
                        f"Cannot import parcel: invalid CSV row {row_number}; non-strict import "
                        "requires rejected_rows to record each rejected course"
                    ) from e
                rejected_rows.append((row_number, str(e)))
    except csv.Error as e:
        raise ValueError(
            f"Cannot import parcel: malformed CSV near row {reader.line_num}: {e}"
        ) from e

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
    skipped_courses: list[SkippedCourse] | None = None,
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
        audit_context: Optional AuditContext for audit trail output. Its
            ``skipped_courses`` and each ``Tract.skipped_courses`` block export,
            as does the explicit ``skipped_courses`` list. The exporter cannot
            see skips it is not given: callers that extracted non-strictly must
            pass the audit context (or tracts) used for extraction.
        skipped_courses: Optional explicit skip records applied to the fresh
            re-check, in addition to those above.

    Returns:
        List of written file paths.

    Only MAIN/ADDITION tracts are export candidates: easement and exception
    tracts describe land that is not the conveyed parcel, so they never get a
    verified CSV, whatever their supplied result claims. They are listed in the
    verification summary instead.

    Nothing is exported when any known tract's role needs review
    (``mp_models.roles_need_review``: several descriptions, and a role inferred from
    wording rather than an explicit tract heading), whatever the supplied results
    claim: land whose role was guessed is never exported.

    Raises:
        ValueError: If verification checks did not pass (single-tract only).
            For multi-tract, if no parcel-boundary tract is supplied or none
            verifies; individual unverified or non-boundary tracts are skipped.
            In both modes, if description roles need review.
    """
    # Deed level, before anything else: the supplied tracts and the description's own.
    known_tracts = _known_tracts(legal_desc, tract_results or [])
    role_reasons = roles_need_review(known_tracts)
    if role_reasons:
        raise ValueError("Cannot export verified CSV: " + roles_review_detail(role_reasons))
    # Multi-tract mode gates per tract, but at least one boundary tract must verify.
    if tract_results:
        if not any(is_boundary_tract(tract.tract_type) for tract, _ in tract_results):
            raise ValueError(
                "Cannot export verified CSV: no parcel boundary tract (main or addition) "
                "was supplied; easement and exception tracts are never eligible for "
                f"verified export. Tracts checked: {len(tract_results)}"
            )
        if not any(_exportable(tract, result) for tract, result in tract_results):
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
        labelled_skips = _labelled_skips(audit_context, skipped_courses)
        for tract, result in tract_results:
            if _exportable(tract, result):
                selected = LegalDescription(
                    calls=tract.calls, stated_area_sq_ft=tract.stated_area_sq_ft
                )
                _validate_export_geometry(
                    tract.calls,
                    result,
                    selected,
                    independent_tract=True,
                    skipped_courses=skips_for_tract(tract, known_tracts, labelled_skips),
                )
    else:
        _validate_export_geometry(
            calls,
            closure_result,
            legal_desc,
            skipped_courses=_single_description_skips(legal_desc, audit_context, skipped_courses),
        )

    if tract_results:
        for i, (tract, tract_result) in enumerate(tract_results, start=1):
            if not _exportable(tract, tract_result):
                logger.warning(
                    "Skipping tract that is not an exportable verified boundary",
                    tract=tract.label,
                    tract_type=tract_kind(tract.tract_type),
                    boundary=is_boundary_tract(tract.tract_type),
                    misclosure_ft=(
                        tract_result.misclosure_ft if tract_result.misclosure_available else None
                    ),
                    warnings_count=len(tract_result.warnings),
                )
                continue
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

    if tract_results:
        summaries: list[str] = []
        for tract, tract_result in tract_results:
            if not _exportable(tract, tract_result):
                continue
            summaries.append(f"--- {tract.label} ---")
            summaries.append(get_closure_summary(tract_result))
            summaries.append("")
        unverified = [(t, r) for t, r in tract_results if not _exportable(t, r)]
        if unverified:
            summaries.append("Not verified (no CSV written):")
            for tract, tract_result in unverified:
                reasons = _not_exported_reason(tract, tract_result)
                summaries.append(
                    f"{tract.label}: misclosure {_misclosure_text(tract_result)}; {reasons}"
                )
            summaries.append("")
        with open(summary_path, "w") as f:
            f.write("\n".join(summaries))
    else:
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
