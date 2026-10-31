"""PR #60 round 52: easement and exception tracts are never parcel boundaries.

Their traverses are checked like any tract so closure, area and perimeter stay
available for review, but a blocking ``non_boundary_tract`` check keeps them from
geometry eligibility. MAIN and ADDITION tracts are unaffected.
"""

from __future__ import annotations

import pytest
from mp_models import AuditContext, DeedCall, RunMetadata, Tract, TractType
from mp_verify import verify_closure


def _square(side: float = 100.0) -> list[DeedCall]:
    return [
        DeedCall(
            course=i + 1,
            direction_text=d,
            bearing_azimuth_deg_from_north=a,
            distance_ft=side,
        )
        for i, (d, a) in enumerate((("N", 0.0), ("E", 90.0), ("S", 180.0), ("W", 270.0)))
    ]


@pytest.mark.parametrize("kind", [TractType.EASEMENT, TractType.EXCEPTION])
def test_non_boundary_tract_is_blocked_but_keeps_geometry(kind: TractType) -> None:
    main = Tract(label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=_square())
    other = Tract(label="Other 1", tract_type=kind, role_basis="heading", calls=_square(10.0))

    main_result, other_result = verify_closure([], tracts=[main, other])

    assert main_result.is_fully_verified()
    assert not other_result.is_fully_verified()
    assert other_result.misclosure_available and other_result.misclosure_ft < 0.01
    assert other_result.area_sq_ft == pytest.approx(100.0)
    check = next(c for c in other_result.checks if c.name == "non_boundary_tract")
    assert check.status == "blocked"
    assert check.reason == kind.value
    assert any("not a parcel boundary" in w for w in other_result.warnings)
    assert not any(c.name == "non_boundary_tract" for c in main_result.checks)


def test_easement_only_tracts_never_verify() -> None:
    easement = Tract(
        label="Easement 1", tract_type=TractType.EASEMENT, role_basis="heading", calls=_square()
    )
    (result,) = verify_closure([], tracts=[easement])
    assert not result.is_fully_verified()
    assert result.get_closure_status() == "NEEDS REVIEW"


def test_addition_tract_still_verifies() -> None:
    addition = Tract(
        label="Addition 1", tract_type=TractType.ADDITION, role_basis="heading", calls=_square()
    )
    (result,) = verify_closure([], tracts=[addition])
    assert result.is_fully_verified()


def test_non_boundary_block_is_audited_per_tract() -> None:
    from datetime import UTC, datetime

    audit = AuditContext(
        run_metadata=RunMetadata(
            parser_version="0",
            llm_provider="none",
            llm_model="none",
            prompt_hash="",
            timestamp_utc=datetime(2026, 10, 30, tzinfo=UTC),
            source_pdf="x",
            cache_enabled=False,
        )
    )
    tracts = [
        Tract(label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=_square()),
        Tract(
            label="Easement 1",
            tract_type=TractType.EASEMENT,
            role_basis="heading",
            calls=_square(10.0),
        ),
    ]
    verify_closure([], tracts=tracts, audit_context=audit)
    main_audit, easement_audit = audit.tract_verification_audits
    assert not any(c.name == "non_boundary_tract" for c in main_audit.checks)
    assert any(c.name == "non_boundary_tract" for c in easement_audit.checks)
    assert easement_audit.closure_summary["status"] == "NEEDS REVIEW"
    # Audit summaries coerce booleans to numbers for every tract.
    assert easement_audit.closure_summary["geometry_verified"] == 0


def test_non_boundary_confidence_includes_the_block_penalty() -> None:
    from datetime import UTC, datetime

    from mp_verify import calculate_confidence_score, get_closure_summary

    audit = AuditContext(
        run_metadata=RunMetadata(
            parser_version="0",
            llm_provider="none",
            llm_model="none",
            prompt_hash="",
            timestamp_utc=datetime(2026, 10, 30, tzinfo=UTC),
            source_pdf="x",
            cache_enabled=False,
        )
    )
    main = Tract(label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=_square())
    easement = Tract(
        label="Easement 1", tract_type=TractType.EASEMENT, role_basis="heading", calls=_square()
    )
    main_result, easement_result = verify_closure([], tracts=[main, easement], audit_context=audit)

    assert easement_result.confidence_score is not None
    assert main_result.confidence_score is not None
    assert easement_result.confidence_score < main_result.confidence_score
    assert easement_result.confidence_score == pytest.approx(
        calculate_confidence_score(easement_result, easement.calls)
    )
    assert f"Confidence: {easement_result.confidence_score:.2f}" in get_closure_summary(
        easement_result
    )
    summary = audit.tract_verification_audits[1].closure_summary
    assert summary["confidence_score"] == easement_result.confidence_score
