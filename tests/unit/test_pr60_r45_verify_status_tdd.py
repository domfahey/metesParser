"""PR #60 round 45: no fabricated misclosure input; missing bearings outrank curved boundary."""

from __future__ import annotations

from datetime import UTC, datetime

import mp_models
import pytest
from mp_verify.closure import verify_closure as package_verify

from metesparser import models as monolith_models
from metesparser.closure_checker import ClosureChecker

IMPLS = {
    "package": (mp_models, package_verify),
    "monolith": (monolith_models, ClosureChecker.verify_closure),
}


def _check(result, name):
    return next(check for check in result.checks if check.name == name)


def _line(m, course, azimuth, distance=100.0):
    return m.DeedCall(
        course=course,
        direction_text="recorded",
        bearing_azimuth_deg_from_north=azimuth,
        distance_ft=distance,
    )


def _cardinal_parcel(m):
    # N 100 / easterly 100 (cardinal only, unpositioned) / S 100 / W 170
    return [
        _line(m, 1, 0.0),
        m.DeedCall(course=2, direction_text="easterly", distance_ft=100.0),
        _line(m, 3, 180.0),
        _line(m, 4, 270.0, 170.0),
    ]


@pytest.mark.parametrize("impl", IMPLS)
def test_undetermined_misclosure_is_not_recorded_as_a_measurement(impl):
    m, verify = IMPLS[impl]
    audit = m.AuditContext(
        run_metadata=m.RunMetadata(
            parser_version="test",
            llm_provider="test",
            llm_model="test",
            prompt_hash="test",
            timestamp_utc=datetime.now(UTC),
            source_pdf="deed.pdf",
            cache_enabled=False,
        )
    )
    result = verify(_cardinal_parcel(m), audit_context=audit)

    assert result.misclosure_available is False
    closure = _check(result, "traverse_closure")
    assert closure.status == "blocked"
    # No made-up 0.0 ft measurement: the input is absent and flagged unavailable.
    assert "misclosure_total_ft" not in closure.inputs
    assert closure.inputs["misclosure_available"] is False
    assert closure.inputs["tolerance_ft"] == 0.01
    assert audit.verification_audit is not None
    audited = _check(audit.verification_audit, "traverse_closure")
    assert "misclosure_total_ft" not in audited.inputs
    assert audit.verification_audit.closure_summary["misclosure_ft"] == "not determined"


@pytest.mark.parametrize("impl", IMPLS)
def test_determined_misclosure_is_recorded_with_its_availability(impl):
    m, verify = IMPLS[impl]
    calls = [_line(m, 1, 0.0), _line(m, 2, 90.0), _line(m, 3, 180.0), _line(m, 4, 270.0, 99.0)]
    closure = _check(verify(calls), "traverse_closure")
    assert closure.status == "failed"
    assert closure.inputs["misclosure_total_ft"] == pytest.approx(1.0)
    assert closure.inputs["misclosure_available"] is True


def _curve(m):
    return m.DeedCall(
        course=2,
        direction_text="recorded",
        bearing_azimuth_deg_from_north=90.0,
        distance_ft=100.0,
        curve_dir="right",
        radius_ft=500.0,
        delta_deg=10.0,
    )


@pytest.mark.parametrize("impl", IMPLS)
def test_curved_boundary_with_missing_bearing_is_blocked_not_not_applicable(impl):
    m, verify = IMPLS[impl]
    calls = [
        _line(m, 1, 0.0),
        _curve(m),
        m.DeedCall(course=3, direction_text="southerly", distance_ft=100.0),
        _line(m, 4, 270.0),
    ]
    result = verify(calls)
    angles = _check(result, "interior_angles")
    assert angles.status == "blocked"
    assert angles.reason == "missing_bearings"
    assert "3" in angles.detail
    assert not result.is_fully_verified()


@pytest.mark.parametrize("impl", IMPLS)
def test_complete_curved_boundary_remains_not_applicable(impl):
    m, verify = IMPLS[impl]
    calls = [_line(m, 1, 0.0), _curve(m), _line(m, 3, 180.0), _line(m, 4, 270.0)]
    angles = _check(verify(calls), "interior_angles")
    assert angles.status == "not_applicable"
    assert angles.reason == "curved_boundary"
