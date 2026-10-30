"""PR60 round 3: bad chord bearing blocks curve check only; per-tract audits recorded."""

from __future__ import annotations

from datetime import UTC, datetime

from metesparser.closure_checker import ClosureChecker
from metesparser.models import AuditContext, DeedCall, RunMetadata, Tract, TractType

verify_closure = ClosureChecker.verify_closure


def _curve_calls(chord: str) -> list[DeedCall]:
    return [
        DeedCall(
            course=1, direction_text="N", bearing_azimuth_deg_from_north=0.0, distance_ft=100.0
        ),
        DeedCall(
            course=2,
            direction_text="curve",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=100.0,
            curve_dir="right",
            radius_ft=100.0,
            delta_deg=60.0,
            arc_length_ft=104.72,
            chord_bearing=chord,
        ),
    ]


def _square(size: float) -> list[DeedCall]:
    return [
        DeedCall(
            course=i + 1,
            direction_text=str(a),
            bearing_azimuth_deg_from_north=a,
            distance_ft=size,
        )
        for i, a in enumerate((0, 90, 180, 270))
    ]


def _ctx() -> AuditContext:
    return AuditContext(
        run_metadata=RunMetadata(
            parser_version="t",
            llm_provider="t",
            llm_model="t",
            prompt_hash="t",
            timestamp_utc=datetime.now(UTC),
            source_pdf="t.pdf",
            cache_enabled=False,
        )
    )


def test_bad_chord_bearing_does_not_fail_traverse_closure():
    calls = _curve_calls("N 95° E")
    # Make the misclosure tiny by closing with a single tolerance override.
    result = verify_closure(calls, closure_tolerance_ft=1e6)
    outcomes = {c.name: c.status for c in result.checks}
    assert outcomes["curve_consistency"] == "blocked"
    assert outcomes["traverse_closure"] == "passed"
    assert not result.geometry_verified


def test_multi_tract_records_per_tract_verification_audits():
    tracts = [
        Tract(label="A", tract_type=TractType.MAIN, calls=_square(100.0)),
        Tract(label="B", tract_type=TractType.MAIN, calls=_square(50.0)),
    ]
    ctx = _ctx()
    verify_closure([], tracts=tracts, audit_context=ctx)
    assert [a.tract_label for a in ctx.tract_verification_audits] == ["A", "B"]
    assert ctx.tract_verification_audits[0].closure_summary["perimeter_ft"] == 400.0
    assert ctx.tract_verification_audits[1].closure_summary["perimeter_ft"] == 200.0
    assert ctx.verification_audit is None


def test_repeated_multi_tract_verification_replaces_tract_audits():
    tracts = [
        Tract(label="A", tract_type=TractType.MAIN, calls=_square(100.0)),
        Tract(label="B", tract_type=TractType.MAIN, calls=_square(50.0)),
    ]
    ctx = _ctx()
    verify_closure([], tracts=tracts, audit_context=ctx)
    verify_closure([], tracts=tracts, audit_context=ctx)
    assert [a.tract_label for a in ctx.tract_verification_audits] == ["A", "B"]
