"""Read-only validation of source evidence; never OCR, normalize, or certify it."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from mp_models.source_handoff import (
    DescriptionCandidate,
    DescriptionSelectionRecord,
    SourceAcquisitionRecord,
)
from pydantic import ValidationError

SCHEMA_VERSION = "1.1"
LIMITATIONS = [
    "Structural validity and matching hashes establish identity, not source-reading accuracy.",
    "Unknown page counts, unavailable originals and declared uncertainties remain unresolved.",
    "Validation does not confer canonical verification or verified-export eligibility.",
]


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


class _Validator:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.result: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "operation": "validate-source",
            "status": "needs_review",
            "bundle_root": str(root),
            "acquisition": {"status": "missing"},
            "selection": {"status": "missing"},
            "structure": {"status": "valid", "findings": []},
            "identity": {"status": "matched", "checks": [], "findings": []},
            "source_uncertainties": {
                "status": "none_declared",
                "items": [],
                "unreadable_pages": [],
                "missing_pages": [],
                "unread_pages": [],
                "unknown_page_count_source_ids": [],
                "findings": [],
            },
            "findings": [],
            "errors": [],
            "limitations": list(LIMITATIONS),
        }

    def finding(
        self,
        code: str,
        message: str,
        *,
        category: str = "structure",
        record_id: str | None = None,
        path: str | None = None,
        error: bool = False,
        **context: Any,
    ) -> None:
        item = {
            "code": code,
            "message": message,
            "category": category,
            "id": record_id,
            "path": path,
            **context,
        }
        self.result["findings"].append(item)
        self.result[category]["findings"].append(item)
        if error:
            self.result["status"] = "error"
            self.result["errors"].append(item)
            if self.result["identity"]["status"] == "matched":
                self.result["identity"]["status"] = "unverifiable"
        if category == "structure":
            self.result["structure"]["status"] = "invalid"
        elif category == "identity":
            status = "mismatched" if code.endswith("mismatch") else "unverifiable"
            if self.result["identity"]["status"] != "mismatched":
                self.result["identity"]["status"] = status
        else:
            self.result["source_uncertainties"]["status"] = "declared"

    def read(
        self, reference: str | Path, record_id: str | None, *, record: bool = False
    ) -> bytes | None:
        value = Path(reference)
        display = str(reference)
        if value.is_absolute():
            try:
                # Resolve the directory (not the final name) so symlinked roots such as
                # macOS /tmp compare equal to the resolved root without hiding a final symlink.
                value = (value.parent.resolve() / value.name).relative_to(self.root)
                display = value.as_posix()
            except ValueError:
                self.finding(
                    "unsafe_path",
                    "Reference is outside the explicit bundle root.",
                    record_id=record_id,
                    path=display,
                    error=record,
                )
                return None
        if any(p in {"..", "."} for p in value.parts) or not value.parts:
            self.finding(
                "unsafe_path",
                "Reference must remain under the explicit bundle root.",
                record_id=record_id,
                path=display,
                error=record,
            )
            return None
        current = self.root
        for part in value.parts:
            current = current / part
            if current.is_symlink():
                self.finding(
                    "unsafe_path",
                    "Symlink components below the bundle root are unsupported.",
                    record_id=record_id,
                    path=display,
                    error=record,
                )
                if not record:
                    self.finding(
                        "identity_unavailable",
                        "Unsafe reference was not read.",
                        category="identity",
                        record_id=record_id,
                        path=display,
                    )
                return None
        try:
            return current.read_bytes()
        except FileNotFoundError:
            self.finding(
                "missing_record" if record else "missing_file",
                "Declared local file is unavailable.",
                category="structure" if record else "identity",
                record_id=record_id,
                path=display,
                error=record,
            )
        except (OSError, ValueError) as exc:
            self.finding(
                "record_unavailable" if record else "file_unavailable",
                str(exc),
                category="structure" if record else "identity",
                record_id=record_id,
                path=display,
                error=record,
            )
        return None

    def check_hash(
        self,
        data: bytes | None,
        declared: str | None,
        record_id: str,
        path: str,
        *,
        code: str = "hash_mismatch",
    ) -> None:
        actual = _digest(data) if data is not None else None
        status = (
            "unverifiable"
            if declared is None or actual is None
            else "matched"
            if declared == actual
            else "mismatched"
        )
        self.result["identity"]["checks"].append(
            {
                "id": record_id,
                "path": path,
                "declared_sha256": declared,
                "actual_sha256": actual,
                "status": status,
            }
        )
        if declared is None:
            self.finding(
                "hash_unavailable",
                "No hash was recorded; identity remains unverifiable.",
                category="identity",
                record_id=record_id,
                path=path,
            )
        elif actual is None:
            self.finding(
                "identity_unavailable",
                "Declared hash could not be compared with local bytes.",
                category="identity",
                record_id=record_id,
                path=path,
            )
        elif actual != declared:
            self.finding(
                code,
                "Raw byte hash differs from the recorded identity.",
                category="identity",
                record_id=record_id,
                path=path,
                declared_sha256=declared,
                actual_sha256=actual,
            )

    def utf8(self, raw: bytes | None, record_id: str, path: str) -> str | None:
        if raw is None:
            return None
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            self.finding(
                "invalid_utf8",
                "Text must be valid UTF-8 without replacement or normalization.",
                record_id=record_id,
                path=path,
            )
            return None

    def record(self, reference: Path, kind: str) -> tuple[Any, bytes | None]:
        raw = self.read(reference, None, record=True)
        if raw is None:
            self.result[kind] = {"status": "invalid", "path": str(reference)}
            return None, None
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            self.result[kind] = {
                "status": "invalid",
                "path": str(reference),
                "sha256": _digest(raw),
            }
            self.finding(
                "invalid_utf8",
                "Record must contain valid UTF-8 JSON.",
                path=str(reference),
                error=True,
            )
            return None, raw
        try:
            data = json.loads(
                text,
                object_pairs_hook=_json_object,
                parse_constant=lambda x: (_ for _ in ()).throw(
                    ValueError(f"Invalid JSON number: {x}")
                ),
            )
            if not isinstance(data, dict):
                raise ValueError("Record must be a JSON object.")
        except ValueError as exc:
            self.result[kind] = {
                "status": "invalid",
                "path": str(reference),
                "sha256": _digest(raw),
            }
            self.finding("invalid_json", str(exc), path=str(reference), error=True)
            return None, raw
        version = data.get("schema_version")
        metadata = {
            "path": str(reference),
            "schema_version": version,
            "sha256": _digest(raw),
            "id": data.get("id"),
        }
        if version == "1.0":
            self.result[kind] = {**metadata, "status": "legacy"}
            self.finding(
                "legacy_schema",
                "Legacy 1.0 evidence is retained but cannot establish a validated 1.1 chain; explicit migration must preserve unknown facts as null.",
                category="identity",
                record_id=data.get("id"),
                path=str(reference),
            )
            if self.result["structure"]["status"] != "invalid":
                self.result["structure"]["status"] = "legacy"
            return None, raw
        if version != SCHEMA_VERSION:
            self.result[kind] = {**metadata, "status": "invalid"}
            self.finding(
                "unknown_schema_version",
                "Only source-handoff versions 1.1 and legacy 1.0 are recognized.",
                record_id=data.get("id"),
                path=str(reference),
                error=True,
            )
            return None, raw
        model = SourceAcquisitionRecord if kind == "acquisition" else DescriptionSelectionRecord
        try:
            parsed = model.model_validate(data)
        except ValidationError as exc:
            self.result[kind] = {**metadata, "status": "invalid"}
            for issue in exc.errors(include_url=False, include_context=False, include_input=False):
                self.finding(
                    "schema_invalid",
                    issue["msg"],
                    record_id=data.get("id"),
                    path=str(reference),
                    error=True,
                    location=list(issue["loc"]),
                )
            return None, raw
        self.result[kind] = {**metadata, "status": "valid"}
        if isinstance(parsed, DescriptionSelectionRecord):
            self.result[kind]["candidate_ids"] = [c.id for c in parsed.candidates]
        return parsed, raw

    def acquisition(self, record: SourceAcquisitionRecord) -> bytes | None:
        evidence = self.result["source_uncertainties"]
        evidence["items"] = [u.model_dump(mode="json") for u in record.uncertainties]
        evidence["missing_pages"] = [p.model_dump(mode="json") for p in record.missing_pages]
        evidence["unreadable_pages"] = list(record.unreadable_pages)
        evidence["unread_pages"] = [
            p
            for p in record.supplied_pages
            if p not in (*record.read_pages, *record.unreadable_pages)
        ]
        evidence["unknown_page_count_source_ids"] = [
            s.id for s in record.sources if s.page_count is None
        ]
        if any(
            evidence[k]
            for k in (
                "items",
                "missing_pages",
                "unreadable_pages",
                "unread_pages",
                "unknown_page_count_source_ids",
            )
        ):
            evidence["status"] = "declared"
        for source in record.sources:
            if source.page_count is not None:
                declared_pages = sorted(
                    p.page
                    for p in (*record.page_map, *record.missing_pages)
                    if p.source_id == source.id
                )
                gaps = []
                next_page = 1
                for page_number in (*declared_pages, source.page_count + 1):
                    if next_page < page_number:
                        gaps.append((next_page, page_number - 1))
                    next_page = page_number + 1
                if gaps:
                    gap_count = sum(end - start + 1 for start, end in gaps)
                    self.finding(
                        "undeclared_pages",
                        "Known page count includes pages without supplied or missing-page declarations.",
                        category="source_uncertainties",
                        record_id=source.id,
                        path=source.path,
                        page_numbers=[p for start, end in gaps for p in range(start, end + 1)]
                        if gap_count <= 1000
                        else None,
                        page_ranges=gaps,
                    )
            if source.path is not None:
                raw = self.read(source.path, source.id)
                self.check_hash(raw, source.sha256, source.id, source.path)
            else:
                self.finding(
                    "attachment_unavailable",
                    "Opaque attachment identity cannot be checked from local bytes.",
                    category="identity",
                    record_id=source.id,
                    attachment_id=source.attachment_id,
                )
        raw = self.read(record.transcript.path, record.id)
        self.check_hash(raw, record.transcript.sha256, record.id, record.transcript.path)
        if self.utf8(raw, record.id, record.transcript.path) is not None:
            assert raw is not None
            # A trailing LF terminates the preceding line; it creates no phantom line.
            line_count = raw.count(b"\n") + int(bool(raw) and not raw.endswith(b"\n"))
            for page in record.page_map:
                if page.end_line > line_count:
                    self.finding(
                        "page_lines_out_of_bounds",
                        "Declared page extends beyond available transcript lines.",
                        record_id=page.id,
                        path=record.transcript.path,
                        line_count=line_count,
                    )
            return raw
        return None

    def candidate(
        self,
        candidate: DescriptionCandidate,
        transcript: bytes | None,
        acquisition: SourceAcquisitionRecord | None,
    ) -> None:
        path = candidate.selected_text.path
        selected = self.read(path, candidate.id)
        self.check_hash(selected, candidate.selected_text.sha256, candidate.id, path)
        text = self.utf8(selected, candidate.id, path)
        if text is not None:
            if not text.startswith(candidate.opening_words):
                self.finding(
                    "opening_words_mismatch",
                    "Opening words must be an exact selected-text prefix.",
                    record_id=candidate.id,
                    path=path,
                )
            if not text.endswith(candidate.closing_words):
                self.finding(
                    "closing_words_mismatch",
                    "Closing words must be an exact selected-text suffix.",
                    record_id=candidate.id,
                    path=path,
                )
        if acquisition is None:
            return
        pages = {page.id: page for page in acquisition.page_map}
        uncertainties = {u.id: u for u in acquisition.uncertainties}
        for carried in candidate.carried_uncertainty_ids:
            if carried not in uncertainties:
                self.finding(
                    "dangling_uncertainty_id",
                    "Carried uncertainty is not present in the acquisition record.",
                    record_id=candidate.id,
                    path=path,
                    uncertainty_id=carried,
                )
        selected_pages = {span.page_id for span in candidate.spans}
        selected_sources = {pages[p].source_id for p in selected_pages if p in pages}
        missing_pages = {p.id for p in acquisition.missing_pages if p.source_id in selected_sources}
        for uncertainty in acquisition.uncertainties:
            relevant = (
                bool(set(uncertainty.page_ids) & (selected_pages | missing_pages))
                if uncertainty.page_ids
                else uncertainty.source_id is None or uncertainty.source_id in selected_sources
            )
            if relevant and uncertainty.id not in candidate.carried_uncertainty_ids:
                self.finding(
                    "uncertainty_dropped",
                    "Selection must carry relevant source/page uncertainty IDs.",
                    category="source_uncertainties",
                    record_id=candidate.id,
                    path=path,
                    uncertainty_id=uncertainty.id,
                )
        chunks = []
        valid_spans = transcript is not None
        for span in candidate.spans:
            page = pages.get(span.page_id)
            if page is None:
                self.finding(
                    "dangling_page_id",
                    "Span page is not present in the acquisition transcript map.",
                    record_id=candidate.id,
                    path=path,
                    page_id=span.page_id,
                )
                valid_spans = False
            if transcript is None:
                continue
            if span.end_byte > len(transcript):
                self.finding(
                    "span_out_of_bounds",
                    "Byte range exceeds transcript length.",
                    record_id=candidate.id,
                    path=path,
                    page_id=span.page_id,
                )
                valid_spans = False
                continue
            try:
                transcript[: span.start_byte].decode("utf-8")
                transcript[: span.end_byte].decode("utf-8")
            except UnicodeDecodeError:
                self.finding(
                    "span_character_boundary",
                    "Offsets must lie on UTF-8 character boundaries.",
                    record_id=candidate.id,
                    path=path,
                    page_id=span.page_id,
                )
                valid_spans = False
                continue
            start_line = transcript.count(b"\n", 0, span.start_byte) + 1
            end_line = transcript.count(b"\n", 0, span.end_byte - 1) + 1
            if (span.start_line, span.end_line) != (start_line, end_line):
                self.finding(
                    "span_line_mismatch",
                    "Display lines do not identify the selected raw byte range.",
                    record_id=candidate.id,
                    path=path,
                    page_id=span.page_id,
                    actual_start_line=start_line,
                    actual_end_line=end_line,
                )
                valid_spans = False
            if page is not None and not page.start_line <= start_line <= end_line <= page.end_line:
                self.finding(
                    "span_page_mismatch",
                    "Selected byte range lies outside its declared page lines.",
                    record_id=candidate.id,
                    path=path,
                    page_id=span.page_id,
                )
                valid_spans = False
            chunks.append(transcript[span.start_byte : span.end_byte])
        if valid_spans and selected is not None:
            reconstructed = chunks[0]
            for separator, chunk in zip(candidate.separators, chunks[1:], strict=True):
                reconstructed += separator.encode("utf-8") + chunk
            if reconstructed != selected:
                self.finding(
                    "selected_bytes_mismatch",
                    "Selected text must equal ordered transcript spans and explicit separators byte for byte.",
                    record_id=candidate.id,
                    path=path,
                )


def validate_source_bundle(
    root: Path, *, acquisition: Path | None = None, selection: Path | None = None
) -> dict[str, Any]:
    """Validate local 1.1 source records under an explicit root without writing.

    Default record names are ``source-acquisition.json`` and
    ``description-selection.json``. Relative override paths resolve under root;
    absolute override paths must remain inside root. A completed result always
    has ``needs_review`` (CLI exit 1), including fully matching evidence. Invalid
    invocation/JSON/schema produces ``error`` (CLI exit 2). Runtime identity and
    span findings are completed advisory results, never an accuracy attestation.
    """
    root = Path(root)
    validator = _Validator(root)
    try:
        resolved = root.resolve(strict=True)
        if not resolved.is_dir():
            raise ValueError("Bundle root must be an existing directory.")
    except (OSError, ValueError, RuntimeError) as exc:
        validator.finding("invalid_bundle_root", str(exc), path=str(root), error=True)
        return validator.result
    validator.root = resolved
    validator.result["bundle_root"] = str(resolved)
    references: dict[str, Path] = {}
    for kind, override, default in (
        ("acquisition", acquisition, "source-acquisition.json"),
        ("selection", selection, "description-selection.json"),
    ):
        default_path = resolved / default
        if override is not None or default_path.exists() or default_path.is_symlink():
            references[kind] = Path(override) if override is not None else Path(default)
    if not references:
        validator.finding(
            "no_source_records",
            "No acquisition or selection record was supplied or found.",
            path=str(resolved),
            error=True,
        )
        return validator.result
    records: dict[str, Any] = {}
    raw_records: dict[str, bytes | None] = {}
    for kind, reference in references.items():
        records[kind], raw_records[kind] = validator.record(reference, kind)
    acquisition_record = records.get("acquisition")
    selection_record = records.get("selection")
    transcript = (
        validator.acquisition(acquisition_record) if acquisition_record is not None else None
    )
    if selection_record is not None:
        if acquisition_record is None:
            validator.finding(
                "missing_acquisition",
                "Selection spans and uncertainty carry-forward require a valid 1.1 acquisition record.",
                category="identity",
                record_id=selection_record.id,
                path=str(references["selection"]),
            )
            validator.result["source_uncertainties"]["status"] = "unverifiable"
        else:
            if selection_record.acquisition_id != acquisition_record.id:
                validator.finding(
                    "acquisition_id_mismatch",
                    "Selection names a different acquisition ID.",
                    category="identity",
                    record_id=selection_record.id,
                    path=str(references["selection"]),
                )
            validator.check_hash(
                raw_records["acquisition"],
                selection_record.acquisition_sha256,
                selection_record.id,
                str(references["acquisition"]),
                code="acquisition_hash_mismatch",
            )
            declared = acquisition_record.transcript.sha256
            if (
                selection_record.transcript_sha256 is not None
                and declared is not None
                and selection_record.transcript_sha256 != declared
            ):
                validator.finding(
                    "transcript_identity_mismatch",
                    "Selection transcript identity differs from the acquisition declaration.",
                    category="identity",
                    record_id=selection_record.id,
                    path=acquisition_record.transcript.path,
                )
            validator.check_hash(
                transcript,
                selection_record.transcript_sha256,
                selection_record.id,
                acquisition_record.transcript.path,
                code="transcript_identity_mismatch",
            )
        for candidate in selection_record.candidates:
            validator.candidate(candidate, transcript, acquisition_record)
    return validator.result
