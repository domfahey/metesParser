"""PR #60 round 16: exception loops and check fallbacks share traverse positioning.

A tangent-less curve fixed by chord bearing and delta is positioned on a main
traverse; an exception loop must accept the same curve rather than reporting an
incomplete bearing. ``build_verification_checks`` requires the caller's traverse
outcome (``traverse_positions``); it never re-derives positioning itself.
"""

from __future__ import annotations

import mp_models
import pytest
from mp_verify.checks import build_verification_checks
from mp_verify.closure import verify_closure as package_verify
from mp_verify.traverse import traverse_positions

from metesparser import models as monolith_models
from metesparser.closure_checker import ClosureChecker

IMPLS = {
    "package": (mp_models, package_verify),
    "monolith": (monolith_models, ClosureChecker.verify_closure),
}


def _line(m, course, azimuth, distance, **extra):
    return m.DeedCall(
        course=course,
        direction_text="recorded",
        bearing_azimuth_deg_from_north=azimuth,
        distance_ft=distance,
        **extra,
    )


def _square(m):
    return [_line(m, i + 1, a, 100.0) for i, a in enumerate((0.0, 90.0, 180.0, 270.0))]


def _tangentless_curve(m, course, **extra):
    return m.DeedCall(
        course=course,
        direction_text="curve",
        distance_ft=14.14,
        curve_dir="right",
        radius_ft=10.0,
        delta_deg=90.0,
        chord_bearing="S 45°00' E",
        **extra,
    )


def _loop(m, start=1, **extra):
    """N 20; right curve R 10, delta 90, chord S 45 E (no tangent); S 10; W 10."""
    return [
        _line(m, start, 0.0, 20.0, **extra),
        _tangentless_curve(m, start + 1, **extra),
        _line(m, start + 2, 180.0, 10.0, **extra),
        _line(m, start + 3, 270.0, 10.0, **extra),
    ]


@pytest.mark.parametrize("impl", IMPLS)
def test_tangentless_curve_loop_has_area_as_main_tract(impl):
    m, verify = IMPLS[impl]
    result = verify(_loop(m))
    assert result.area_available
    assert result.area_sq_ft == pytest.approx(178.54, abs=0.01)


@pytest.mark.parametrize("impl", IMPLS)
def test_exception_loop_with_tangentless_curve_subtracts_area(impl):
    m, verify = IMPLS[impl]
    calls = _square(m) + _loop(m, start=5, is_exception=True)
    result = verify(calls)

    assert result.area_available
    assert result.area_sq_ft == pytest.approx(10000.0 - 178.54, abs=0.01)
    assert not any("incomplete bearing" in warning for warning in result.warnings)
    assert not any("Cannot calculate exception area" in w for w in result.warnings)
    # Positioning is internal: the exception call is not rewritten.
    assert calls[5].bearing_azimuth_deg_from_north is None


@pytest.mark.parametrize("impl", IMPLS)
def test_exception_loop_with_unpositioned_curve_stays_unavailable(impl):
    m, verify = IMPLS[impl]
    loop = _loop(m, start=5, is_exception=True)
    # No delta or arc: a tangent-less curve without a sweep cannot be positioned.
    loop[1] = loop[1].model_copy(update={"delta_deg": None})
    result = verify(_square(m) + loop)

    assert not result.area_available
    assert any("Exception course 6" in warning for warning in result.warnings)
    assert "Exception tract has 1 incomplete bearing(s)" in result.warnings


def _closure_check(checks):
    return next(check for check in checks if check.name == "traverse_closure")


def _build(calls, **positioning):
    return build_verification_checks(
        calls,
        **positioning,
        closure_passed=True,
        misclosure=0.0,
        tolerance=0.01,
        curve_consistency_passed=True,
        parallel_warnings=[],
        intersection_warnings=[],
        reversal_warnings=[],
        distance_warnings=[],
        stated_area_sq_ft=0.0,
        area_sq_ft=0.0,
        area_available=True,
        double_entry_performed=False,
        discrepancies=[],
    )


def test_checks_require_the_traverse_outcome():
    with pytest.raises(TypeError, match="positioned"):
        _build(_square(mp_models))


def test_check_fallback_positions_tangentless_chord_and_delta_curve():
    calls = _loop(mp_models)
    checks = _build(calls, positioned=traverse_positions(calls)[1])
    closure = _closure_check(checks)
    assert closure.status == "passed"


def test_check_fallback_leaves_infeasible_chord_only_curve_unpositioned():
    calls = _square(mp_models)
    calls[1] = mp_models.DeedCall(
        course=2,
        direction_text="curve",
        distance_ft=100.0,
        curve_dir="right",
        radius_ft=10.0,
        chord_bearing="N 90°00' E",
        chord_length_ft=100.0,
    )
    positioned = traverse_positions(calls)[1]
    closure = _closure_check(_build(calls, positioned=positioned))
    assert closure.status == "blocked"
    assert closure.reason == "unpositioned_courses"


def test_monolith_verify_closure_delegates_to_package(monkeypatch):
    import mp_verify.closure as closure_mod

    seen: list[list[mp_models.DeedCall]] = []
    real = closure_mod.verify_closure

    def spy(calls, **kwargs):
        seen.append(calls)
        return real(calls, **kwargs)

    monkeypatch.setattr(closure_mod, "verify_closure", spy)
    result = ClosureChecker.verify_closure(_square(monolith_models))

    assert len(seen) == 1
    assert all(isinstance(call, mp_models.DeedCall) for call in seen[0])
    assert isinstance(result, monolith_models.ClosureResult)
    assert result.closure_passed


def test_monolith_multi_tract_verify_delegates_once_with_audits(monkeypatch):
    from datetime import UTC, datetime

    import mp_verify.closure as closure_mod

    calls_seen: list[dict] = []
    real = closure_mod.verify_closure

    def spy(calls, **kwargs):
        calls_seen.append(kwargs)
        return real(calls, **kwargs)

    monkeypatch.setattr(closure_mod, "verify_closure", spy)
    m = monolith_models
    ctx = m.AuditContext(
        run_metadata=m.RunMetadata(
            parser_version="t",
            llm_provider="t",
            llm_model="t",
            prompt_hash="t",
            timestamp_utc=datetime.now(UTC),
            source_pdf="t.pdf",
            cache_enabled=False,
        )
    )
    tracts = [m.Tract(label=label, tract_type=m.TractType.MAIN, calls=_square(m)) for label in "AB"]
    results = ClosureChecker.verify_closure(_square(m), tracts=tracts, audit_context=ctx)

    # The package tract loop runs once per tract plus the delegating call.
    assert calls_seen[0]["tracts"] is not None
    assert [type(r) for r in results] == [m.ClosureResult, m.ClosureResult]
    assert ctx.verification_audit is None
    assert [a.tract_label for a in ctx.tract_verification_audits] == ["A", "B"]
    assert all(isinstance(a, m.VerificationAudit) for a in ctx.tract_verification_audits)
