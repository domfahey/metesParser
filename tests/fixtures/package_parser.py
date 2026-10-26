"""Flat call adapter for regressions shared with the legacy monolith parser."""

from mp_models import AuditContext, DeedCall
from mp_parse import extract_calls as extract_with_tracts


def extract_calls(
    text: str,
    distance_unit: str = "feet",
    *,
    audit_context: AuditContext | None = None,
    strict: bool = True,
) -> list[DeedCall]:
    calls, _tracts = extract_with_tracts(
        text, distance_unit, audit_context=audit_context, strict=strict
    )
    return calls
