"""Deterministic review; no OCR or provider dependencies."""

from __future__ import annotations

import hashlib
import html
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mp_export.csv_writer import (  # type: ignore[import-untyped]
    calls_to_csv,
    csv_text_to_calls,
    export_verified_csv,
)
from mp_models import AuditContext, DeedCall, LegalDescription, RunMetadata
from mp_verify import verify_closure

from .text import prepare_text

ENGINE_VERSION = "1.0.0"
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
    directory = Path(output_dir) if output_dir is not None else None
    if directory is not None:
        try:
            directory.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            return _error(result, "output_exists", "Output directory must not already exist.")
        except OSError as exc:
            return _error(result, "output_error", str(exc))
    calls = []
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
    try:
        text = source.decode("utf-8")
        if stated_area_sq_ft is not None and (
            not math.isfinite(stated_area_sq_ft) or stated_area_sq_ft <= 0
        ):
            raise ValueError("Stated area must be finite and positive.")
        if kind == "text":
            prepared = prepare_text(text, audit_context=audit)
            normalized = prepared.normalized_text
            legal = prepared.legal_description
            calls = legal.calls
            if legal.poc_description and not any(c.is_tie_in for c in calls):
                result["errors"].append(
                    {
                        "code": "unresolved_poc",
                        "message": "Point of commencement could not be separated from boundary calls.",
                    }
                )
        elif kind == "json":
            data = json.loads(
                text,
                parse_constant=lambda x: (_ for _ in ()).throw(ValueError(f"Invalid number {x}")),
            )
            if isinstance(data, list):
                calls = [DeedCall.model_validate(c) for c in data]
                legal = LegalDescription(calls=calls)
            elif isinstance(data, dict) and "calls" in data:
                legal = LegalDescription.model_validate(data)
                calls = legal.calls
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
            legal = legal.model_copy(update={"stated_area_sq_ft": stated_area_sq_ft})
        result["calls"] = [c.model_dump(mode="json") for c in calls]
        if not calls:
            result["errors"].append({"code": "no_calls", "message": "No calls could be parsed."})
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
