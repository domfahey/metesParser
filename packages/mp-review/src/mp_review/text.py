"""Shared deterministic preparation of already-isolated legal-description prose."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from mp_models import (
    AuditContext,
    LegalDescription,
    RunMetadata,
    TractType,
    invalid_stated_area_notes,
    is_boundary_tract,
    stated_areas_match,
)
from mp_parse import (
    enrich_calls_with_azimuths,
    extract_calls,
    mark_tie_in_calls,
)
from mp_parse.metadata import (
    extract_area_statement,
    extract_poc_and_pob,
    infer_distance_unit,
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
    inferred_distance_unit: str | None = None
    invalid_stated_area: str | None = None


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
    boundary_tracts = [tract for tract in tracts if is_boundary_tract(tract.tract_type)]
    if len(boundary_tracts) > 1:
        raise ValueError(MULTIPLE_PARCELS)
    legal_poc_description: str | None
    if tracts:
        tracts = [
            tract.model_copy(update={"calls": enrich_calls_with_azimuths(tract.calls)})
            for tract in tracts
        ]
        if (
            len(tracts) == 1
            and tracts[0].poc_description is None
            and poc
            and not tracts[0].skipped_courses
        ):
            marked = mark_tie_in_calls(tracts[0].calls, poc)
            if marked and not all(c.is_tie_in for c in marked):
                tracts[0] = tracts[0].model_copy(update={"calls": marked})
        non_empty_boundary = [
            tract for tract in tracts if is_boundary_tract(tract.tract_type) and tract.calls
        ]
        if non_empty_boundary:
            active_tracts = [tract for tract in tracts if tract.tract_type != TractType.EASEMENT]
            calls = [call for tract in active_tracts for call in tract.calls]
        else:
            active_tracts = tracts
            calls = [call for tract in tracts for call in tract.calls]
        legal_poc_description = next(
            (tract.poc_description for tract in active_tracts if tract.poc_description),
            None,
        )
        if legal_poc_description is None and len(tracts) == 1 and tracts[0].poc_description is None:
            legal_poc_description = poc or None
    else:
        calls = mark_tie_in_calls(enrich_calls_with_azimuths(extracted), poc)
        legal_poc_description = poc or None

    area = extract_area_statement(normalized)
    valid_area = area if area and area["value_sq_ft"] > 0 else None
    area_notes = list(
        dict.fromkeys(
            detail
            for call in (*calls, *(c for tract in tracts for c in tract.calls))
            for detail in invalid_stated_area_notes(call.notes)
        )
    )
    if area_notes:
        invalid_stated_area: str | None = "; ".join(area_notes)
    elif (
        not calls
        and not any(t.calls for t in tracts)
        and area is not None
        and area["value_sq_ft"] <= 0
    ):
        invalid_stated_area = f"{area['value_sq_ft']} sq ft ({area['unit']})"
    else:
        invalid_stated_area = None

    boundary_tracts = [tract for tract in tracts if is_boundary_tract(tract.tract_type)]
    legal_stated_area_sq_ft: float | None
    if tracts:
        boundary_area = (
            boundary_tracts[0].stated_area_sq_ft
            if len(boundary_tracts) == 1
            and not any(invalid_stated_area_notes(c.notes) for c in boundary_tracts[0].calls)
            else None
        )
        if boundary_area is not None:
            legal_stated_area_sq_ft = boundary_area
            legal_stated_area_approx = (
                bool(valid_area["approximate"])
                if valid_area is not None
                and stated_areas_match(valid_area["value_sq_ft"], boundary_area)
                else False
            )
        else:
            legal_stated_area_sq_ft = None
            legal_stated_area_approx = False
    else:
        legal_stated_area_sq_ft = valid_area["value_sq_ft"] if valid_area else None
        legal_stated_area_approx = bool(valid_area["approximate"]) if valid_area else False

    inferred_unit = infer_distance_unit(normalized)
    # The tracts (with role bases) travel with the description, so the role gate
    # (``mp_models.roles_need_review``) reads the same extraction its calls came from.
    legal = LegalDescription(
        calls=calls,
        tracts=tracts,
        poc_description=legal_poc_description,
        pob_description=pob or None,
        stated_area_sq_ft=legal_stated_area_sq_ft,
        stated_area_approximate=legal_stated_area_approx,
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
    unresolved_commencement = (
        bool(legal_poc_description)
        and (not any(c.is_tie_in for c in calls) or all(c.is_tie_in for c in calls))
        if len(tracts) > 1
        else has_commencement
        and (
            not legal_poc_description
            or not any(c.is_tie_in for c in calls)
            or all(c.is_tie_in for c in calls)
        )
    )
    return PreparedText(
        normalized_text=normalized,
        legal_description=legal,
        quotes=tuple(quotes),
        multiple_tracts=bool(tracts),
        unresolved_commencement=unresolved_commencement,
        inferred_distance_unit=inferred_unit,
        invalid_stated_area=invalid_stated_area,
    )
