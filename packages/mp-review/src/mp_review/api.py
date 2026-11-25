"""Deterministic review; no OCR or provider dependencies."""

from __future__ import annotations

import hashlib
import html
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mp_export.csv_writer import (
    calls_to_csv,
    csv_text_to_calls,
    export_verified_csv,
)
from mp_models import (
    AuditContext,
    DeedCall,
    LegalDescription,
    RunMetadata,
    Tract,
    TractType,
    is_boundary_tract,
    mark_non_boundary,
    mark_roles_review,
    roles_need_review,
    roles_review_detail,
    stated_areas_match,
)
from mp_verify import verify_closure

from .json_input import parse_json
from .text import MULTIPLE_PARCELS, prepare_text

ENGINE_VERSION = "2.0.0"
REPLAY_VERSION = "review-replay-1"
LIMITATIONS = [
    "Deterministic parsing requires source comparison; passing checks does not establish legal validity.",
    "Topology checks cover straight segments and circular arcs; unsupported or incomplete curve geometry requires review.",
    "No independent double entry is supplied; source completeness is not established by closure.",
]


def _base(source: bytes, name: str, kind: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "engine_version": ENGINE_VERSION,
        "status": "needs_review",
        "input": {"name": name, "sha256": hashlib.sha256(source).hexdigest(), "kind": kind},
        "calls": [],
        "verification": None,
        "limitations": list(LIMITATIONS),
        "errors": [],
        "artifacts": {},
    }


def _error(result: dict[str, Any], code: str, message: str) -> dict[str, Any]:
    result["status"] = "error"
    result["errors"].append({"code": code, "message": message})
    return result


def _run(
    source: bytes,
    name: str,
    kind: str,
    output_dir: Path | None,
    stated_area_sq_ft: float | None,
    *,
    include_audit: bool = False,
) -> dict[str, Any]:
    result = _base(source, name, kind)
    directory: Path | None = None
    if stated_area_sq_ft is not None and (
        isinstance(stated_area_sq_ft, bool)
        or not isinstance(stated_area_sq_ft, (int, float))
        or not math.isfinite(stated_area_sq_ft)
        or stated_area_sq_ft <= 0
    ):
        _error(result, "invalid_input", "Stated area must be finite and positive.")
    elif output_dir is not None:
        candidate = Path(output_dir)
        try:
            candidate.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            return _error(result, "output_exists", "Output directory must not already exist.")
        except OSError as exc:
            return _error(result, "output_error", str(exc))
        directory = candidate
    calls: list[DeedCall] = []
    verification = None
    legal = None
    text = ""
    normalized = None
    audit = AuditContext(
        run_metadata=RunMetadata(
            parser_version=ENGINE_VERSION,
            llm_provider="none",
            llm_model="none",
            prompt_hash="",
            timestamp_utc=datetime.now(UTC),
            source_pdf=name,
            cache_enabled=False,
            config={"input_kind": kind, "method": "deterministic"},
        )
    )
    if result["status"] == "error":
        try:
            text = source.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = ""
    else:
        try:
            text = source.decode("utf-8-sig")
            pre_role_review: list[str] = []
            if kind == "text":
                prepared = prepare_text(text, audit_context=audit)
                normalized = prepared.normalized_text
                legal = prepared.legal_description
                calls = legal.calls
                if prepared.inferred_distance_unit:
                    result["limitations"].append(
                        f"Advisory: historical or regional distance unit {prepared.inferred_distance_unit!r} "
                        "detected in source text; verify unit conversions against the source deed."
                    )
                if prepared.invalid_stated_area:
                    result["errors"].append(
                        {
                            "code": "invalid_stated_area",
                            "message": (
                                "Stated area is non-positive and requires review: "
                                f"{prepared.invalid_stated_area}"
                            ),
                        }
                    )
                if prepared.unresolved_commencement:
                    result["errors"].append(
                        {
                            "code": "unresolved_poc",
                            "message": "Point of commencement could not be separated from boundary calls.",
                        }
                    )
            elif kind == "json":
                data = parse_json(
                    text,
                    parse_constant=lambda x: (_ for _ in ()).throw(
                        ValueError(f"Invalid number {x}")
                    ),
                )
                if isinstance(data, list):
                    calls = [DeedCall.model_validate(c) for c in data]
                    legal = LegalDescription(calls=calls)
                elif isinstance(data, dict) and ("calls" in data or "tracts" in data):
                    legal = LegalDescription.model_validate(data)
                    boundary_tracts = [t for t in legal.tracts if is_boundary_tract(t.tract_type)]
                    if len(boundary_tracts) > 1:
                        raise ValueError(MULTIPLE_PARCELS)
                    if legal.tracts:

                        def _mark_tract(tract: Tract) -> Tract:
                            if is_boundary_tract(tract.tract_type):
                                return tract
                            tract_calls = (
                                [
                                    c
                                    if c.is_exception
                                    else c.model_copy(update={"is_exception": True})
                                    for c in tract.calls
                                ]
                                if tract.tract_type == TractType.EXCEPTION
                                else tract.calls
                            )
                            return tract.model_copy(
                                update={"calls": mark_non_boundary(tract_calls, tract.tract_type)}
                            )

                        marked_tracts = [_mark_tract(tract) for tract in legal.tracts]
                        marked_non_easement = [
                            c
                            for t in marked_tracts
                            if t.tract_type != TractType.EASEMENT
                            for c in t.calls
                        ]
                        non_empty_boundary = [
                            t for t in marked_tracts if is_boundary_tract(t.tract_type) and t.calls
                        ]

                        pre_role_review = roles_need_review(legal.tracts, legal.calls)
                        if legal.calls:
                            note_marked = [
                                tract.model_copy(
                                    update={
                                        "calls": mark_non_boundary(tract.calls, tract.tract_type)
                                    }
                                )
                                if not is_boundary_tract(tract.tract_type)
                                else tract
                                for tract in legal.tracts
                            ]
                            tract_sets = (legal.tracts, note_marked, marked_tracts)
                            base_candidates: list[list[DeedCall]] = [
                                [
                                    c
                                    for t in ts
                                    if t.tract_type != TractType.EASEMENT
                                    for c in t.calls
                                ]
                                for ts in tract_sets
                            ]
                            if not non_empty_boundary:
                                base_candidates.extend(
                                    [c for t in ts for c in t.calls] for ts in tract_sets
                                )
                            if roles_need_review(legal.tracts):
                                base_candidates.extend(
                                    t.calls for ts in tract_sets for t in ts if t.calls
                                )
                            valid_candidates = [
                                *base_candidates,
                                *(mark_roles_review(seq) for seq in base_candidates),
                            ]
                            if legal.calls not in valid_candidates:
                                raise ValueError(
                                    "JSON calls do not match tracts; supply consistent calls or tracts only."
                                )

                        if any(
                            t.tract_type == TractType.EXCEPTION and not t.calls
                            for t in marked_tracts
                        ):
                            result["errors"].append(
                                {
                                    "code": "incomplete_exception_tract",
                                    "message": (
                                        "Exception tract has no calls; cannot verify net parcel boundary."
                                    ),
                                }
                            )

                        calls = (
                            marked_non_easement
                            if non_empty_boundary
                            else [c for t in marked_tracts for c in t.calls]
                        )
                        if marked_tracts != legal.tracts:
                            legal = legal.model_copy(update={"tracts": marked_tracts})
                    else:
                        calls = list(legal.calls)
                    tract_skips = [skip for tract in legal.tracts for skip in tract.skipped_courses]
                    if tract_skips:
                        audit.skipped_courses.extend(tract_skips)
                    legal_updates: dict[str, Any] = {}
                    if calls != legal.calls:
                        legal_updates["calls"] = calls
                    if (
                        stated_area_sq_ft is None
                        and len(boundary_tracts) == 1
                        and boundary_tracts[0].stated_area_sq_ft is not None
                    ):
                        if legal.stated_area_sq_ft is None:
                            legal_updates["stated_area_sq_ft"] = boundary_tracts[
                                0
                            ].stated_area_sq_ft
                        elif not stated_areas_match(
                            legal.stated_area_sq_ft,
                            boundary_tracts[0].stated_area_sq_ft,
                        ):
                            result["errors"].append(
                                {
                                    "code": "conflicting_stated_area",
                                    "message": (
                                        f"Top-level stated_area_sq_ft ({legal.stated_area_sq_ft}) "
                                        "conflicts with boundary tract stated_area_sq_ft "
                                        f"({boundary_tracts[0].stated_area_sq_ft})."
                                    ),
                                }
                            )
                    if legal_updates:
                        legal = legal.model_copy(update=legal_updates)
                else:
                    raise ValueError("JSON must be a calls list or LegalDescription object.")
            elif kind == "csv":
                calls = csv_text_to_calls(text, strict=True)
                legal = LegalDescription(calls=calls)
            else:
                raise ValueError(
                    "Supported inputs are UTF-8 text, JSON, and CSV; PDF/OCR is not supported."
                )
            if stated_area_sq_ft is not None:
                override_updates: dict[str, Any] = {
                    "stated_area_sq_ft": stated_area_sq_ft,
                    "stated_area_approximate": False,
                }
                override_boundary = [t for t in legal.tracts if is_boundary_tract(t.tract_type)]
                if len(override_boundary) == 1:
                    override_updates["tracts"] = [
                        tract.model_copy(update={"stated_area_sq_ft": stated_area_sq_ft})
                        if is_boundary_tract(tract.tract_type)
                        else tract
                        for tract in legal.tracts
                    ]
                legal = legal.model_copy(update=override_updates)
            # Fail closed on guessed description roles (the one gate, for every input
            # kind): flat calls of a deed with several descriptions and an inferred role,
            # or calls a blocked review marked, never reach checks_passed or export.
            role_review = list(
                dict.fromkeys([*pre_role_review, *roles_need_review(legal.tracts, calls)])
            )
            if role_review:
                # Marked, every artifact written below stays blocked when re-reviewed.
                calls = mark_roles_review(calls)
                marked_tracts = [
                    tract.model_copy(update={"calls": mark_roles_review(tract.calls)})
                    for tract in legal.tracts
                ]
                legal = legal.model_copy(update={"calls": calls, "tracts": marked_tracts})
                result["errors"].append(
                    {
                        "code": "description_roles_inferred",
                        "message": roles_review_detail(role_review),
                    }
                )
            result["calls"] = [c.model_dump(mode="json") for c in calls]
            if not calls:
                result["errors"].append(
                    {"code": "no_calls", "message": "No calls could be parsed."}
                )
            else:
                verification = verify_closure(
                    calls,
                    audit_context=audit,
                    stated_area_sq_ft=(
                        stated_area_sq_ft
                        if stated_area_sq_ft is not None
                        else legal.stated_area_sq_ft or 0.0
                    ),
                )
                result["verification"] = verification.model_dump(mode="json")
                if verification.is_fully_verified() and not result["errors"]:
                    result["status"] = "checks_passed"
        except (ValueError, TypeError, OSError) as exc:
            _error(result, "invalid_input", str(exc))
    audit_payload = {
        "schema_version": "1.0",
        "provider": None,
        "model": None,
        "method": "deterministic",
        "input": result["input"],
        "original_source": text,
        "normalized_text": normalized,
        "source_encoding": "utf-8" if text else "unavailable or empty",
        "call_audits": [a.model_dump(mode="json") for a in audit.call_audits],
        # Courses extraction could not parse stay auditable (empty under strict text
        # extraction); verify_closure already blocks on them via audit_context.
        "skipped_courses": [s.model_dump(mode="json") for s in audit.skipped_courses],
        "verification_audit": audit.verification_audit.model_dump(mode="json")
        if audit.verification_audit
        else None,
        "extraction_record": None,
        "legal_description": legal.model_dump(mode="json") if legal else None,
        "verification": result["verification"],
        "errors": result["errors"],
    }
    if include_audit:
        result["audit"] = audit_payload
    if directory is not None:
        try:

            def write(name: str, value: str | bytes) -> None:
                target = directory / name
                target.write_bytes(value.encode("utf-8") if isinstance(value, str) else value)
                result["artifacts"][name] = str(target)

            write("source.txt", source)
            write("calls.json", json.dumps(result["calls"], indent=2, allow_nan=False))
            calls_to_csv(calls if result["status"] != "error" else [], str(directory / "calls.csv"))
            result["artifacts"]["calls.csv"] = str(directory / "calls.csv")
            write(
                "verification.json", json.dumps(result["verification"], indent=2, allow_nan=False)
            )
            write(
                "audit.json",
                json.dumps(
                    audit_payload,
                    indent=2,
                    allow_nan=False,
                ),
            )
            if result["status"] == "checks_passed" and verification is not None:
                # Exporter rechecks geometry before issuing the verified artifact.
                export_verified_csv(
                    calls,
                    verification,
                    str(directory / "calls.csv"),
                    legal,
                    # Re-blocks a fresh export check on any recorded skip.
                    skipped_courses=list(audit.skipped_courses),
                )
                result["artifacts"]["calls_verified.csv"] = str(directory / "calls_verified.csv")
                for sidecar in (
                    "calls_verified.verification.txt",
                    "calls_verified.metadata.txt",
                ):
                    sidecar_path = directory / sidecar
                    if sidecar_path.is_file():
                        result["artifacts"][sidecar] = str(sidecar_path)
            body = html.escape(json.dumps(result, indent=2, allow_nan=False))
            write(
                "review.html",
                '<!doctype html><html lang="en"><meta charset="utf-8"><title>Deed review</title><h1>Deed review</h1><h2>Source</h2><pre>'
                + html.escape(text)
                + "</pre><h2>Results and limitations</h2><pre>"
                + body
                + "</pre></html>",
            )
            manifest = {
                "schema_version": "1.0",
                "kind": "review",
                "engine_version": ENGINE_VERSION,
                "replay_version": REPLAY_VERSION,
                "input": {**result["input"], "path": "source.txt"},
                "parameters": {"stated_area_sq_ft": stated_area_sq_ft},
                "recorded_status": result["status"],
                "artifacts": {
                    artifact: hashlib.sha256(Path(location).read_bytes()).hexdigest()
                    for artifact, location in result["artifacts"].items()
                },
            }
            write("review-manifest.json", json.dumps(manifest, indent=2, allow_nan=False))
        except (ValueError, OSError) as exc:
            _error(result, "artifact_error", str(exc))
    return result


def replay_review(
    source: bytes,
    *,
    input_kind: str,
    source_name: str = "source.txt",
    stated_area_sq_ft: float | None = None,
) -> dict[str, Any]:
    """Recompute retained input bytes in memory without artifact or verified export writes."""
    return _run(source, source_name, input_kind, None, stated_area_sq_ft, include_audit=True)


def review_text(
    text: str,
    *,
    source_name: str = "description.txt",
    output_dir: Path | None = None,
    stated_area_sq_ft: float | None = None,
) -> dict[str, Any]:
    """Review user-provided text and optionally write a new review folder."""
    return _run(text.encode("utf-8"), source_name, "text", output_dir, stated_area_sq_ft)


def review_file(
    path: Path | str, *, output_dir: Path | None = None, stated_area_sq_ft: float | None = None
) -> dict[str, Any]:
    """Review text, strict CSV, or JSON from a file."""
    path = Path(path)
    kind = {".txt": "text", ".md": "text", ".csv": "csv", ".json": "json"}.get(
        path.suffix.lower(), "unsupported"
    )
    try:
        source = path.read_bytes()
    except OSError as exc:
        return _error(_base(b"", path.name, kind), "input_error", str(exc))
    return _run(source, path.name, kind, output_dir, stated_area_sq_ft)


def verify_file(
    path: Path | str, *, output_dir: Path | None = None, stated_area_sq_ft: float | None = None
) -> dict[str, Any]:
    """Verify strict CSV or JSON call input without parsing prose."""
    if Path(path).suffix.lower() not in {".csv", ".json"}:
        return _error(
            _base(b"", Path(path).name, "unsupported"),
            "invalid_input",
            "Verification requires CSV or JSON input.",
        )
    return review_file(path, output_dir=output_dir, stated_area_sq_ft=stated_area_sq_ft)
