"""CSV export for deed calls.

Exports structured calls to the standard 22-field CSV schema.
Reads CSV files back into DeedCall objects, including legacy 21-field files
(written before ``curve_type`` was appended; it then reads back as None, and a
curved legacy row records in its notes that it is treated as circular).
"""

from __future__ import annotations

import csv
import io
from collections import deque
from collections.abc import Callable
from pathlib import Path

import structlog
from mp_models import (
    DESCRIPTION_ROLES_NOTE,
    LEGACY_CURVE_NOTE,
    NON_BOUNDARY_NOTES,
    AuditContext,
    ClosureResult,
    DeedCall,
    LegalDescription,
    SkippedCourse,
    Tract,
    TractType,
    _Model,
    is_boundary_tract,
    mark_non_boundary,
    mark_roles_review,
    non_boundary_detail,
    non_boundary_marks,
    non_boundary_marks_detail,
    roles_need_review,
    roles_review_detail,
    split_notes,
    stated_areas_match,
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


def _write_metadata(
    metadata: dict[str, str | int | float | bool | None], output_path: Path
) -> None:
    """Write metadata to a text file."""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("DEED METADATA\n")
        f.write("=" * 60 + "\n\n")
        for key, value in metadata.items():
            if value is not None and value != "":
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
        set()
        if is_boundary_tract(tract.tract_type)
        else {non_boundary_detail(tract.label, tract.tract_type)}
    )
    # A result computed from the calls alone carries their non-boundary notes' verdict.
    kinds = non_boundary_marks(tract.calls)
    if kinds:
        expected.add(non_boundary_marks_detail(kinds))
    role_details = [c.detail for c in result.checks if c.name == _ROLE_CHECK]
    role_details += [w for w in result.warnings if w.startswith(f"{_ROLE_CHECK}:")]
    return any(detail not in expected for detail in role_details)


def _exportable(tract: Tract, result: ClosureResult) -> bool:
    """A verified parcel-boundary tract; easement/exception tracts never qualify,
    nor do calls bearing an easement/exception tract's note, whatever tract holds them."""
    return (
        is_boundary_tract(tract.tract_type)
        and not non_boundary_marks(tract.calls)
        and not _role_mismatch(tract, result)
        and result.is_fully_verified()
    )


def _not_exported_reason(tract: Tract, result: ClosureResult) -> str:
    """Why a tract got no verified CSV, derived from the tract itself."""
    if _role_mismatch(tract, result):
        return "supplied verification result does not belong to this tract"
    reasons = [w for w in result.warnings if not w.startswith(f"{_ROLE_CHECK}:")]
    kinds = non_boundary_marks(tract.calls)
    if not is_boundary_tract(tract.tract_type):
        reasons.insert(0, non_boundary_detail(tract.label, tract.tract_type))
    elif kinds:
        reasons.insert(0, non_boundary_marks_detail(kinds))
    return "; ".join(reasons) or "verification checks did not pass"


def _tracts_conflict(orig_tract: Tract, supplied_tract: Tract) -> bool:
    """Whether a supplied tract conflicts with a same-label tract in legal_desc."""
    return (
        orig_tract.tract_type != supplied_tract.tract_type
        or orig_tract.role_basis != supplied_tract.role_basis
        or orig_tract.calls != supplied_tract.calls
        or orig_tract.skipped_courses != supplied_tract.skipped_courses
        or orig_tract.stated_area_sq_ft != supplied_tract.stated_area_sq_ft
    )


def _validate_supplied_tracts(
    legal_desc: LegalDescription | None,
    tract_results: list[tuple[Tract, ClosureResult]],
) -> None:
    """Reject supplied tracts absent from or conflicting with legal_desc."""
    if legal_desc is None or not legal_desc.tracts or not tract_results:
        return
    remaining_by_label: dict[str, list[Tract]] = {}
    for orig in legal_desc.tracts:
        remaining_by_label.setdefault(orig.label, []).append(orig)
    supplied_labels: set[str] = set()
    for supplied, _ in tract_results:
        supplied_labels.add(supplied.label)
        candidates = remaining_by_label.get(supplied.label)
        if candidates is None:
            raise ValueError(
                f"Cannot export verified CSV: supplied tract {supplied.label!r} "
                "is not in legal_desc.tracts."
            )
        match_idx = next(
            (i for i, orig in enumerate(candidates) if not _tracts_conflict(orig, supplied)),
            None,
        )
        if match_idx is None:
            raise ValueError(
                f"Cannot export verified CSV: supplied tract {supplied.label!r} "
                "conflicts with legal_desc.tracts."
            )
        candidates.pop(match_idx)
    for label in supplied_labels:
        if remaining_by_label.get(label):
            raise ValueError(
                f"Cannot export verified CSV: supplied tract {label!r} "
                "conflicts with legal_desc.tracts."
            )


def _known_tracts(
    legal_desc: LegalDescription | None, tract_results: list[tuple[Tract, ClosureResult]]
) -> list[Tract]:
    """Every tract the caller knows, so a skip labelled with an omitted tract stays with it."""
    _validate_supplied_tracts(legal_desc, tract_results)
    known = [t for t, _ in tract_results]
    supplied_labels = {t.label for t in known}
    for tract in legal_desc.tracts if legal_desc is not None else []:
        if tract.label not in supplied_labels:
            known.append(tract)
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


_CHECK_RESULT_KEYS: frozenset[str] = frozenset(
    {"name", "status", "passed", "reason", "detail", "inputs"}
)


def _is_passed_double_entry_check(check: dict[str, object]) -> bool:
    """Return True when a dumped CheckResult structurally represents a passing double_entry."""
    detail = check.get("detail")
    return (
        set(check.keys()) == _CHECK_RESULT_KEYS
        and check.get("name") == "double_entry"
        and check.get("status") == "passed"
        and check.get("passed") is True
        and check.get("reason") == "check_passed"
        and check.get("inputs") == {}
        and isinstance(detail, str)
        and bool(detail.strip())
    )


def _results_match(
    closure_result: ClosureResult,
    fresh_result: ClosureResult,
    *,
    allow_external_double_entry: bool,
) -> bool:
    """Return True when the supplied result matches fresh geometry verification."""
    # Source review is an explicit human assessment, independent of fresh geometry.
    excluded = {"source_review_status"}
    if not {"checks", "source_review_status"} & closure_result.model_fields_set:
        # Historical results lack structured checks and used an older heuristic score.
        excluded.update({"checks", "confidence_score"})
    supplied_dump = closure_result.model_dump(exclude=excluded)
    fresh_dump = fresh_result.model_dump(exclude=excluded)
    if supplied_dump == fresh_dump:
        return True
    if not allow_external_double_entry or "checks" in excluded:
        return False
    if {k: v for k, v in supplied_dump.items() if k != "checks"} != {
        k: v for k, v in fresh_dump.items() if k != "checks"
    }:
        return False
    supplied_checks = supplied_dump["checks"]
    fresh_checks = fresh_dump["checks"]
    if len(supplied_checks) != len(fresh_checks):
        return False
    for supplied_check, fresh_check in zip(supplied_checks, fresh_checks, strict=True):
        if supplied_check == fresh_check:
            continue
        if not (
            _is_passed_double_entry_check(supplied_check)
            and fresh_check.get("name") == "double_entry"
            and fresh_check.get("status") == "not_applicable"
        ):
            return False
    return True


def _validate_export_geometry(
    calls: list[DeedCall],
    closure_result: ClosureResult,
    legal_desc: LegalDescription | None,
    *,
    independent_tract: bool = False,
    tract: Tract | None = None,
    stated_area_sq_ft: float | None = None,
    skipped_courses: list[SkippedCourse] | None = None,
    double_entry_calls: list[DeedCall] | None = None,
) -> tuple[list[DeedCall], ClosureResult]:
    """Require the supplied verification to describe the calls actually exported."""
    selected_calls = legal_desc.calls if legal_desc is not None else calls
    if legal_desc is not None and [c.model_dump() for c in calls] != [
        c.model_dump() for c in selected_calls
    ]:
        raise ValueError("Cannot export verified CSV: calls do not match LegalDescription.calls")

    if stated_area_sq_ft is not None:
        stated_area = stated_area_sq_ft
    elif legal_desc is not None and legal_desc.stated_area_sq_ft is not None:
        stated_area = legal_desc.stated_area_sq_ft
    else:
        stated_area = 0.0
    from mp_verify import verify_closure, verify_tract

    if independent_tract:
        fresh_result = verify_tract(
            selected_calls,
            stated_area_sq_ft=stated_area,
            skipped_courses=skipped_courses,
            double_entry_calls=double_entry_calls,
            tract=tract,
        )
    else:
        fresh_result = verify_closure(
            selected_calls,
            stated_area_sq_ft=stated_area,
            skipped_courses=skipped_courses,
            double_entry_calls=double_entry_calls,
        )
    if not fresh_result.is_fully_verified():
        raise ValueError(
            "Cannot export verified CSV: selected calls failed fresh verification. "
            f"Misclosure: {_misclosure_text(fresh_result)}, "
            f"Warnings: {len(fresh_result.warnings)}"
        )
    if not _results_match(
        closure_result,
        fresh_result,
        allow_external_double_entry=double_entry_calls is None,
    ):
        raise ValueError("Cannot export verified CSV: closure result does not match selected calls")
    return selected_calls, fresh_result


def calls_to_csv(
    calls: list[DeedCall],
    output_path: str,
    metadata: dict[str, str | int | float | bool | None] | None = None,
) -> None:
    """Export calls to CSV file.

    Args:
        calls: List of DeedCall objects.
        output_path: Output file path.
        metadata: Optional metadata dict (source_doc, exhibit, etc.).
    """
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, "w", encoding="utf-8", newline="") as f:
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


_MARK_NOTES: frozenset[str] = frozenset({DESCRIPTION_ROLES_NOTE, *NON_BOUNDARY_NOTES})


def _call_exact_key(call: DeedCall) -> tuple[tuple[str, object], ...]:
    """Hashable exact identity for matching calls across flat calls and tracts."""
    return tuple(sorted(call.model_dump().items()))


def _call_normalized_key(
    call: DeedCall, *, include_course: bool = True
) -> tuple[tuple[str, object], ...]:
    """Hashable call identity ignoring non-boundary/role notes and is_exception flag."""
    dump = call.model_dump()
    stripped_notes = [note for note in split_notes(call.notes) if note not in _MARK_NOTES]
    dump["notes"] = "; ".join(stripped_notes) if stripped_notes else None
    dump["is_exception"] = False
    if not include_course:
        dump.pop("course", None)
    return tuple(sorted(dump.items()))


def _attribute_calls_to_tracts(
    calls: list[DeedCall], tracts: list[Tract]
) -> list[TractType | None]:
    """Attribute each flat call to at most one tract call slot.

    Preserves original tract order when all matching slots are covered, and fails
    closed to non-boundary slots on ambiguous partial subsets across boundary and
    non-boundary tracts.
    """
    slots: list[tuple[DeedCall, TractType]] = [
        (call, tract.tract_type) for tract in tracts for call in tract.calls
    ]
    used = [False] * len(slots)
    attributed: list[TractType | None] = [None] * len(calls)

    def broad_key_fn(call: DeedCall) -> object:
        return _call_normalized_key(call, include_course=False)

    key_fns: tuple[Callable[[DeedCall], object], ...] = (
        id,
        _call_exact_key,
        _call_normalized_key,
        broad_key_fn,
    )
    for key_fn in key_fns:
        index: dict[object, list[int]] = {}
        broad_slot_counts: dict[object, int] = {}
        for slot_idx, (slot_call, _) in enumerate(slots):
            if not used[slot_idx]:
                index.setdefault(key_fn(slot_call), []).append(slot_idx)
                bk = broad_key_fn(slot_call)
                broad_slot_counts[bk] = broad_slot_counts.get(bk, 0) + 1
        call_counts: dict[object, int] = {}
        broad_call_counts: dict[object, int] = {}
        for call_idx, call in enumerate(calls):
            if attributed[call_idx] is None:
                key = key_fn(call)
                if key in index:
                    call_counts[key] = call_counts.get(key, 0) + 1
                bk = broad_key_fn(call)
                if bk in broad_slot_counts:
                    broad_call_counts[bk] = broad_call_counts.get(bk, 0) + 1
        queues: dict[object, deque[int]] = {}
        for key, slot_indices in index.items():
            bk = broad_key_fn(slots[slot_indices[0]][0])
            if (
                call_counts.get(key, 0) < len(slot_indices)
                and broad_call_counts.get(bk, 0) < broad_slot_counts[bk]
            ):
                has_boundary = any(is_boundary_tract(slots[i][1]) for i in slot_indices)
                has_non_boundary = any(not is_boundary_tract(slots[i][1]) for i in slot_indices)
                if has_boundary and has_non_boundary:
                    slot_indices = [
                        *(i for i in slot_indices if not is_boundary_tract(slots[i][1])),
                        *(i for i in slot_indices if is_boundary_tract(slots[i][1])),
                    ]
            queues[key] = deque(slot_indices)
        for call_idx, call in enumerate(calls):
            if attributed[call_idx] is not None:
                continue
            queue = queues.get(key_fn(call))
            while queue and used[queue[0]]:
                queue.popleft()
            if queue:
                slot_idx = queue.popleft()
                used[slot_idx] = True
                attributed[call_idx] = slots[slot_idx][1]
    return attributed


def _legal_desc_metadata(
    legal_desc: LegalDescription,
) -> dict[str, str | int | float | bool | None]:
    """Build the sidecar metadata mapping from a LegalDescription."""
    return {
        "poc_description": legal_desc.poc_description,
        "pob_description": legal_desc.pob_description,
        "source_doc": legal_desc.source_doc,
        "exhibit": legal_desc.exhibit,
        "page": legal_desc.page,
        "survey_date": legal_desc.survey_date,
        "basis_of_bearing": legal_desc.basis_of_bearing,
        "datum": legal_desc.datum,
        "distance_unit": legal_desc.distance_unit,
        "stated_area_sq_ft": legal_desc.stated_area_sq_ft,
        "stated_area_approximate": legal_desc.stated_area_approximate,
        "section": legal_desc.section,
        "township": legal_desc.township,
        "range": legal_desc.range,
        "principal_meridian": legal_desc.principal_meridian,
        "aliquot": legal_desc.aliquot,
        "surveyor_certification": legal_desc.surveyor_certification,
        "prior_conveyance": legal_desc.prior_conveyance,
        "coordinate_system": legal_desc.coordinate_system,
        "fips_code": legal_desc.fips_code,
        "plat_book": legal_desc.subdivision_ref.plat_book if legal_desc.subdivision_ref else None,
        "plat_page": legal_desc.subdivision_ref.plat_page if legal_desc.subdivision_ref else None,
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


def _matches_sole_boundary_tract(calls: list[DeedCall], tracts: list[Tract]) -> bool:
    """Return True when calls match a sole boundary tract verbatim and no non-boundary tract."""
    if not calls or not tracts or roles_need_review(tracts, calls):
        return False
    boundary_tracts = [t for t in tracts if is_boundary_tract(t.tract_type)]
    if len(boundary_tracts) != 1:
        return False
    call_dumps = [c.model_dump() for c in calls]
    if call_dumps != [c.model_dump() for c in boundary_tracts[0].calls]:
        return False
    normalized_calls = [_call_normalized_key(c) for c in calls]
    return all(
        [_call_normalized_key(c) for c in t.calls] != normalized_calls
        for t in tracts
        if not is_boundary_tract(t.tract_type)
    )


def legal_description_to_csv(
    legal_desc: LegalDescription,
    output_path: str,
) -> None:
    """Export a LegalDescription to CSV with metadata sidecar.

    Args:
        legal_desc: LegalDescription object.
        output_path: Output file path.
    """
    metadata = _legal_desc_metadata(legal_desc)
    if legal_desc.calls:
        calls_to_write = list(legal_desc.calls)
        if legal_desc.tracts and not _matches_sole_boundary_tract(
            calls_to_write, legal_desc.tracts
        ):
            attributed = _attribute_calls_to_tracts(calls_to_write, legal_desc.tracts)
            has_boundary = any(is_boundary_tract(tract.tract_type) for tract in legal_desc.tracts)
            fallback_types = (
                []
                if has_boundary
                else list(dict.fromkeys(tract.tract_type for tract in legal_desc.tracts))
            )
            all_exception_fallback = not has_boundary and all(
                tract.tract_type == TractType.EXCEPTION for tract in legal_desc.tracts
            )
            marked_calls: list[DeedCall] = []
            for call, tract_type in zip(calls_to_write, attributed, strict=True):
                if tract_type is not None:
                    if tract_type == TractType.EXCEPTION and not call.is_exception:
                        call = call.model_copy(update={"is_exception": True})
                    if not is_boundary_tract(tract_type):
                        call = mark_non_boundary([call], tract_type)[0]
                elif fallback_types:
                    if all_exception_fallback and not call.is_exception:
                        call = call.model_copy(update={"is_exception": True})
                    for fallback_type in fallback_types:
                        call = mark_non_boundary([call], fallback_type)[0]
                marked_calls.append(call)
            calls_to_write = marked_calls
    elif legal_desc.tracts:
        calls_to_write = []
        for tract in legal_desc.tracts:
            tract_calls = tract.calls
            if tract.tract_type == TractType.EXCEPTION:
                tract_calls = [
                    c if c.is_exception else c.model_copy(update={"is_exception": True})
                    for c in tract_calls
                ]
            if not is_boundary_tract(tract.tract_type):
                tract_calls = mark_non_boundary(tract_calls, tract.tract_type)
            calls_to_write.extend(tract_calls)
    else:
        calls_to_write = []
    if legal_desc.tracts and roles_need_review(legal_desc.tracts, calls_to_write):
        calls_to_write = mark_roles_review(calls_to_write)
    calls_to_csv(calls_to_write, output_path, metadata)


def export_verified_csv(
    calls: list[DeedCall],
    closure_result: ClosureResult,
    output_path: str,
    legal_desc: LegalDescription | None = None,
    *,
    tract_results: list[tuple[Tract, ClosureResult]] | None = None,
    audit_context: AuditContext | None = None,
    skipped_courses: list[SkippedCourse] | None = None,
    double_entry_calls: list[DeedCall] | None = None,
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
        double_entry_calls: Optional independently-entered call set to replay
            during fresh verification (matches ``verify_closure`` ordering in
            multi-tract mode).

    Returns:
        List of written file paths.

    Only MAIN/ADDITION tracts are export candidates: easement and exception
    tracts describe land that is not the conveyed parcel, so they never get a
    verified CSV, whatever their supplied result claims. They are listed in the
    verification summary instead.

    Nothing is exported when any known tract's role needs review
    (``mp_models.roles_need_review``: several descriptions, and a role inferred from
    wording rather than an explicit tract heading) or any supplied call bears the
    role-review mark, whatever the supplied results claim: land whose role was
    guessed is never exported. Calls bearing an easement/exception tract's note
    (``mp_models.mark_non_boundary``) are never exported either, whichever tract or
    selection supplies them.

    Raises:
        ValueError: If verification checks did not pass (single-tract only).
            For multi-tract, if no parcel-boundary tract is supplied or none
            verifies; individual unverified or non-boundary tracts are skipped.
            In both modes, if description roles need review.
    """
    # Deed level, before anything else: the supplied tracts and the description's own,
    # and the role-review mark on any supplied call.
    known_tracts = _known_tracts(legal_desc, tract_results or [])
    role_reasons = roles_need_review(
        known_tracts, [*calls, *(legal_desc.calls if legal_desc is not None else [])]
    )
    if role_reasons:
        raise ValueError("Cannot export verified CSV: " + roles_review_detail(role_reasons))
    boundary_tract: Tract | None = None
    if tract_results is None:
        if known_tracts:
            all_boundary = [tract for tract in known_tracts if is_boundary_tract(tract.tract_type)]
            non_empty_boundary = [tract for tract in all_boundary if tract.calls]
            if not non_empty_boundary:
                raise ValueError(
                    "Cannot export verified CSV: no parcel boundary tract (main or addition) "
                    "with calls was supplied; easement and exception tracts are never eligible for "
                    f"verified export. Tracts checked: {len(known_tracts)}"
                )
            if len(all_boundary) > 1:
                raise ValueError(
                    "Cannot export verified CSV: multiple boundary tracts require "
                    "multi-tract verification (tract_results=)."
                )
            if any(
                tract_kind(tract.tract_type) == TractType.EXCEPTION.value for tract in known_tracts
            ):
                raise ValueError(
                    "Cannot export verified CSV: deeds with exception tracts require "
                    "multi-tract verification (tract_results=)."
                )
            boundary_tract = non_empty_boundary[0]
            if [c.model_dump() for c in calls] != [c.model_dump() for c in boundary_tract.calls]:
                raise ValueError(
                    "Cannot export verified CSV: calls do not match the boundary tract."
                )
            if (
                legal_desc is not None
                and legal_desc.stated_area_sq_ft is not None
                and boundary_tract.stated_area_sq_ft is not None
                and not stated_areas_match(
                    legal_desc.stated_area_sq_ft,
                    boundary_tract.stated_area_sq_ft,
                )
            ):
                raise ValueError(
                    "Cannot export verified CSV: legal_desc.stated_area_sq_ft conflicts with "
                    "boundary tract stated_area_sq_ft."
                )
        kinds = non_boundary_marks([*calls, *(legal_desc.calls if legal_desc is not None else [])])
        if kinds:
            raise ValueError("Cannot export verified CSV: " + non_boundary_marks_detail(kinds))
    single_boundary_stated_area: float | None = None
    # Multi-tract mode gates per tract, but at least one boundary tract must verify.
    if tract_results is not None:
        if not any(is_boundary_tract(tract.tract_type) for tract, _ in tract_results):
            raise ValueError(
                "Cannot export verified CSV: no parcel boundary tract (main or addition) "
                "was supplied; easement and exception tracts are never eligible for "
                f"verified export. Tracts checked: {len(tract_results)}"
            )
        if legal_desc is not None and legal_desc.stated_area_sq_ft is not None:
            boundary_tracts = [t for t in known_tracts if is_boundary_tract(t.tract_type)]
            has_exception = any(
                tract_kind(t.tract_type) == TractType.EXCEPTION.value for t in known_tracts
            )
            # Align with verify_closure: deed-level stated area applies to a sole boundary
            # tract only when no EXCEPTION tract exists (net deed area != gross MAIN area).
            if len(boundary_tracts) == 1 and not has_exception:
                sole_boundary = boundary_tracts[0]
                if sole_boundary.stated_area_sq_ft is not None:
                    if not stated_areas_match(
                        legal_desc.stated_area_sq_ft,
                        sole_boundary.stated_area_sq_ft,
                    ):
                        raise ValueError(
                            "Cannot export verified CSV: legal_desc.stated_area_sq_ft conflicts "
                            "with boundary tract stated_area_sq_ft."
                        )
                else:
                    single_boundary_stated_area = legal_desc.stated_area_sq_ft
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
    verified_stem = (
        output_file.stem
        if output_file.stem.endswith("_verified")
        else f"{output_file.stem}_verified"
    )
    written_paths: list[Path] = []

    validated_tract_summaries: dict[int, ClosureResult] = {}
    validated_single_summary: ClosureResult | None = None
    selected_single_calls: list[DeedCall] = calls
    # Validate every selected successful result before writing any output.
    if tract_results is not None:
        labelled_skips = _labelled_skips(audit_context, skipped_courses)
        if double_entry_calls is not None:
            total_tract_calls = sum(len(tract.calls) for tract, _ in tract_results)
            if len(double_entry_calls) != total_tract_calls:
                raise ValueError(
                    "Cannot export verified CSV: selected calls failed fresh verification. "
                    f"Double-entry call count mismatch: {total_tract_calls} vs "
                    f"{len(double_entry_calls)} (multi-tract total)"
                )
        offset = 0
        for idx, (tract, result) in enumerate(tract_results):
            tract_double_entry = (
                double_entry_calls[offset : offset + len(tract.calls)]
                if double_entry_calls is not None
                else None
            )
            offset += len(tract.calls)
            if _exportable(tract, result):
                effective_stated_area = (
                    tract.stated_area_sq_ft
                    if tract.stated_area_sq_ft is not None
                    else (
                        single_boundary_stated_area if is_boundary_tract(tract.tract_type) else None
                    )
                )
                selected = LegalDescription(
                    calls=tract.calls, stated_area_sq_ft=effective_stated_area
                )
                _, fresh = _validate_export_geometry(
                    tract.calls,
                    result,
                    selected,
                    independent_tract=True,
                    tract=tract,
                    stated_area_sq_ft=effective_stated_area,
                    skipped_courses=skips_for_tract(tract, known_tracts, labelled_skips),
                    double_entry_calls=tract_double_entry,
                )
                validated_tract_summaries[idx] = fresh.model_copy(
                    update={"source_review_status": result.source_review_status}
                )
    else:
        single_stated_area = (
            legal_desc.stated_area_sq_ft
            if (legal_desc is not None and legal_desc.stated_area_sq_ft is not None)
            else (
                boundary_tract.stated_area_sq_ft
                if (boundary_tract is not None and boundary_tract.stated_area_sq_ft is not None)
                else 0.0
            )
        )
        selected_single_calls, fresh = _validate_export_geometry(
            calls,
            closure_result,
            legal_desc,
            stated_area_sq_ft=single_stated_area,
            skipped_courses=_single_description_skips(legal_desc, audit_context, skipped_courses),
            double_entry_calls=double_entry_calls,
        )
        validated_single_summary = fresh.model_copy(
            update={"source_review_status": closure_result.source_review_status}
        )

    if tract_results is not None:
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
            tract_path = output_file.with_stem(f"{verified_stem}_tract{i}")
            calls_to_csv(tract.calls, str(tract_path))
            written_paths.append(tract_path)
            logger.info("Verified tract CSV exported", path=str(tract_path), tract=tract.label)

    else:
        verified_path = output_file.with_stem(verified_stem)
        metadata = _legal_desc_metadata(legal_desc) if legal_desc is not None else None
        calls_to_csv(selected_single_calls, str(verified_path), metadata)
        written_paths.append(verified_path)
        logger.info("Verified CSV exported", path=str(verified_path))

    summary_path = output_file.with_stem(verified_stem).with_suffix(".verification.txt")
    from mp_verify import get_closure_summary

    if tract_results is not None:
        summaries: list[str] = []
        for idx, (tract, tract_result) in enumerate(tract_results):
            if not _exportable(tract, tract_result):
                continue
            summaries.append(f"--- {tract.label} ---")
            summaries.append(get_closure_summary(validated_tract_summaries.get(idx, tract_result)))
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
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write("\n".join(summaries))
    else:
        summary = get_closure_summary(
            validated_single_summary if validated_single_summary is not None else closure_result
        )
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(summary)
    logger.info("Verification summary written", path=str(summary_path))

    if audit_context is not None:
        audit_base = output_file.with_stem(verified_stem)
        audit_json_path = audit_base.with_suffix(".audit.json")

        audit_json_path.write_text(audit_context.model_dump_json(indent=2), encoding="utf-8")
        logger.info("Audit trail written", path=str(audit_json_path))

        from .audit_html import write_report

        audit_html_path = audit_base.with_suffix(".audit.html")

        write_report(audit_context, audit_html_path)
        logger.info("Audit HTML report written", path=str(audit_html_path))

    return written_paths
