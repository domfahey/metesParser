"""Shared deterministic preparation of already-isolated legal-description prose."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from mp_models import AuditContext, LegalDescription, RunMetadata, is_boundary_tract
from mp_parse import (
    enrich_calls_with_azimuths,
    extract_calls,
    mark_tie_in_calls,
)
from mp_parse.metadata import (
    extract_area_statement,
    extract_poc_and_pob,
    split_into_calls,
)
from mp_parse.normalizer import normalize_legal_description
from mp_parse.parcels import detect_parcel_markers

MULTIPLE_PARCELS = "Multiple parcel descriptions require separate reviews."


@dataclass(frozen=True)
class PreparedText:
    normalized_text: str
    legal_description: LegalDescription
    quotes: tuple[str, ...]
    multiple_tracts: bool
    unresolved_commencement: bool


def prepare_text(text: str, *, audit_context: AuditContext | None = None) -> PreparedText:
    """Parse one selected description, retaining tie-ins and honest source quotations.

    This stage neither verifies geometry nor establishes source completeness. A quote
    falls back to the complete supplied description if a verbatim call span cannot
    be matched confidently after normalization.

    Several parcels are refused for separate reviews, so no artifact presents them as
    one boundary: labelled parcels or a combined restatement (``detect_parcel_markers``
    on the source), or more than one parcel boundary (main/addition tract) in the
    parser's own tract split, headed ("PARCEL ONE:", "TRACT 1:") or not. A parcel and
    its excepted or easement land stay one review.
    """
    if len(detect_parcel_markers(text)) > 1:
        raise ValueError(MULTIPLE_PARCELS)
    normalized = normalize_legal_description(text)
    poc, pob = extract_poc_and_pob(normalized)
    audit = audit_context or AuditContext(
        run_metadata=RunMetadata(
            parser_version="1.0.0",
            llm_provider="none",
            llm_model="none",
            prompt_hash="",
            timestamp_utc=datetime.now(UTC),
            source_pdf="isolated text",
            cache_enabled=False,
            config={"method": "deterministic"},
        )
    )
    audit_start = len(audit.call_audits)
    extracted, tracts = extract_calls(normalized, audit_context=audit)
    if sum(is_boundary_tract(tract.tract_type) for tract in tracts) > 1:
        raise ValueError(MULTIPLE_PARCELS)
    calls = mark_tie_in_calls(enrich_calls_with_azimuths(extracted), poc)
    area = extract_area_statement(normalized)
    # The tracts (with role bases) travel with the description, so the role gate
    # (``mp_models.roles_need_review``) reads the same extraction its calls came from.
    legal = LegalDescription(
        calls=calls,
        tracts=tracts,
        poc_description=poc or None,
        pob_description=pob or None,
        stated_area_sq_ft=area["value_sq_ft"] if area else None,
    )
    # Normalization changes bearing notation and abbreviations. Never present the
    # normalized parser excerpt as a verbatim quotation of the user's source.
    candidates = split_into_calls(text)
    quotes = []
    cursor = 0
    for entry in audit.call_audits[audit_start:]:
        quote = text
        for index in range(cursor, len(candidates)):
            candidate = candidates[index]
            normalized_parts = split_into_calls(normalize_legal_description(candidate))
            if normalized_parts == [entry.source_excerpt] and candidate in text:
                quote = candidate
                cursor = index + 1
                break
        quotes.append(quote)
    has_commencement = bool(
        re.search(r"\b(?:COMMENCING|STARTING|POINT\s+OF\s+COMMENCEMENT|POC)\b", normalized, re.I)
    )
    return PreparedText(
        normalized_text=normalized,
        legal_description=legal,
        quotes=tuple(quotes),
        multiple_tracts=bool(tracts),
        unresolved_commencement=has_commencement
        and (not poc or not any(c.is_tie_in for c in calls) or all(c.is_tie_in for c in calls)),
    )
