"""A record call excluded from the course is kept verbatim in the call's notes."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from mp_models import AuditContext, RunMetadata
from mp_parse import extract_calls, extract_single_call

POB = "BEGINNING at a point; "
CLOSING = "; THENCE S 45° W 100 feet to the point of beginning."
STRICT = pytest.mark.parametrize("strict", [True, False], ids=["strict", "non-strict"])

ROWS = {
    "parenthetical-per-deed": (
        "THENCE N 45° E 100 feet (N 45°10' E 100.5 feet per deed) to a point",
        "(N 45°10' E 100.5 feet per deed)",
    ),
    "parenthetical-deed-label": (
        "THENCE N 45° E 100 feet (deed N 45° 10' E 100.5 feet) to a point",
        "(deed N 45° 10' E 100.5 feet)",
    ),
    "parenthetical-before-measured": (
        "THENCE (deed N 45° 10' E 100.5 feet) N 45° E 100 feet to a point",
        "(deed N 45° 10' E 100.5 feet)",
    ),
    "labelled-R": (
        "THENCE N 45° E 100 feet, N 45°10' E 100.5 feet (R), to a point",
        "N 45°10' E 100.5 feet (R)",
    ),
    "of-record": (
        "THENCE N 45° E 100 feet, being N 45°10' E 100.5 feet of record, to a point",
        "N 45°10' E 100.5 feet of record",
    ),
    "per-record": (
        "THENCE N 45° E 100 feet, per record N 45°10' E 100.5 feet, to a point",
        "per record N 45°10' E 100.5 feet",
    ),
}


@STRICT
@pytest.mark.parametrize("name", sorted(ROWS))
def test_record_text_in_notes_not_in_course(name: str, strict: bool) -> None:
    fragment, record = ROWS[name]
    calls, _ = extract_calls(POB + fragment + CLOSING, strict=strict)
    first = calls[0]
    # extract_calls first joins "45° 10'" into "45°10'"; the call text is otherwise verbatim.
    assert first.notes == f"record call: {record.replace('° ', '°')}"
    assert first.bearing_azimuth_deg_from_north == pytest.approx(45.0)
    assert first.distance_ft == pytest.approx(100.0)
    assert calls[1].notes is None


@pytest.mark.parametrize("name", sorted(ROWS))
def test_single_call_record_in_notes(name: str) -> None:
    fragment, record = ROWS[name]
    call = extract_single_call(fragment, 1)
    assert call is not None
    assert call.notes == f"record call: {record}"
    assert call.distance_ft == pytest.approx(100.0)


@pytest.mark.parametrize(
    "fragment",
    [
        "THENCE N 45° E 100 feet to an iron pin, said pin being N 30° E 2 feet from a stone",
        "THENCE N 45° E 100 feet to a point (see plan) in the road",
        "THENCE N 45° E 100 feet to a point",
        "THENCE N 45° E 100 feet to a point in the line of Smith, which line bears S 45° E 300 feet",
    ],
)
def test_calls_without_record_text_have_no_notes(fragment: str) -> None:
    call = extract_single_call(fragment, 1)
    assert call is not None
    assert call.notes is None


def test_audit_trail_records_excluded_record_call() -> None:
    audit = AuditContext(
        run_metadata=RunMetadata(
            parser_version="1.0.0",
            llm_provider="none",
            llm_model="none",
            prompt_hash="x",
            timestamp_utc=datetime.now(UTC),
            source_pdf="deed.pdf",
            cache_enabled=False,
        )
    )
    fragment, record = ROWS["parenthetical-per-deed"]
    extract_calls(POB + fragment + CLOSING, strict=True, audit_context=audit)
    first, second = audit.call_audits
    assert [d.value for d in first.decisions if d.field == "record_call"] == [record]
    assert not [d for d in second.decisions if d.field == "record_call"]
