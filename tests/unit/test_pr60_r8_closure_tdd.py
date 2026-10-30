"""PR #60 round 8: audit mode reset, infeasible chord-only curves, #49 continuation, curve precedence.

Each behavior runs through the package and the compatibility monolith.
"""

from __future__ import annotations

from datetime import UTC, datetime

import mp_models
import pytest
from mp_verify.closure import compute_traverse as package_traverse
from mp_verify.closure import verify_closure as package_verify

from metesparser import models as monolith_models
from metesparser.closure_checker import ClosureChecker

IMPLS = {
    "package": (mp_models, package_verify, package_traverse),
    "monolith": (monolith_models, ClosureChecker.verify_closure, ClosureChecker.compute_traverse),
}


def _line(m, course, azimuth, distance=100.0, **extra):
    return m.DeedCall(
        course=course,
        direction_text="recorded",
        bearing_azimuth_deg_from_north=azimuth,
        distance_ft=distance,
        **extra,
    )


def _square(m):
    return [_line(m, i + 1, a) for i, a in enumerate((0.0, 90.0, 180.0, 270.0))]


def _ctx(m):
    return m.AuditContext(
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


def _tracts(m):
    return [
        m.Tract(label="A", tract_type=m.TractType.MAIN, calls=_square(m)),
        m.Tract(label="B", tract_type=m.TractType.MAIN, calls=_square(m)),
    ]


@pytest.mark.parametrize("impl", IMPLS)
def test_single_run_after_multi_tract_clears_tract_audits(impl):
    m, verify, _ = IMPLS[impl]
    ctx = _ctx(m)
    verify(_square(m), tracts=_tracts(m), audit_context=ctx)
    assert len(ctx.tract_verification_audits) == 2
    verify(_square(m), audit_context=ctx)
    assert ctx.verification_audit is not None
    assert ctx.tract_verification_audits == []


@pytest.mark.parametrize("impl", IMPLS)
def test_multi_tract_run_after_single_clears_single_audit(impl):
    m, verify, _ = IMPLS[impl]
    ctx = _ctx(m)
    verify(_square(m), audit_context=ctx)
    assert ctx.verification_audit is not None
    verify(_square(m), tracts=_tracts(m), audit_context=ctx)
    assert ctx.verification_audit is None
    assert len(ctx.tract_verification_audits) == 2


def _chord_curve(m, chord_length, radius=500.0):
    return m.DeedCall(
        course=2,
        direction_text="recorded",
        bearing_azimuth_deg_from_north=None,
        distance_ft=chord_length,
        curve_dir="right",
        radius_ft=radius,
        chord_bearing="S 90° E",
        chord_length_ft=chord_length,
        is_indefinite=True,
    )


@pytest.mark.parametrize("impl", IMPLS)
def test_infeasible_chord_only_curve_is_not_positioned_by_traverse(impl):
    m, _, traverse = IMPLS[impl]
    assert len(traverse([_chord_curve(m, 1001.0)])) == 1
    assert len(traverse([_chord_curve(m, 1000.0)])) == 2


@pytest.mark.parametrize("impl", IMPLS)
def test_infeasible_chord_only_curve_blocks_closure_area_and_perimeter(impl):
    m, verify, _ = IMPLS[impl]
    calls = [_line(m, 1, 0.0), _chord_curve(m, 1001.0), _line(m, 3, 180.0), _line(m, 4, 270.0)]
    result = verify(calls)
    checks = {c.name: c for c in result.checks}
    assert result.closure_passed is False
    assert checks["traverse_closure"].status == "blocked"
    # The impossible chord is itself a detected curve inconsistency (failed stays failed).
    assert checks["curve_consistency"].status == "failed"
    assert checks["area_reasonableness"].inputs["area_available"] is False
    assert result.perimeter_available is False
    assert result.geometry_verified is False
    assert any("Course 2" in w and "cannot be positioned" in w for w in result.warnings)


@pytest.mark.parametrize("impl", IMPLS)
def test_feasible_chord_only_curve_is_still_positioned(impl):
    m, verify, _ = IMPLS[impl]
    calls = [_line(m, 1, 0.0), _chord_curve(m, 100.0), _line(m, 3, 180.0), _line(m, 4, 270.0)]
    result = verify(calls)
    assert len(result.points) == 5
    assert not any("cannot be positioned" in w for w in result.warnings)


@pytest.mark.parametrize("impl", IMPLS)
@pytest.mark.parametrize("along", ["continuing along the same line", "same line as above"])
def test_first_course_continuation_does_not_block_parallelism(impl, along):
    """#49: course 0 has no predecessor to compare, so it must not block verification."""
    m, verify, _ = IMPLS[impl]
    calls = _square(m)
    calls[0] = calls[0].model_copy(update={"along": along})
    result = verify(calls)
    parallel = next(c for c in result.checks if c.name == "parallelism")
    assert parallel.status != "blocked"
    assert result.geometry_verified is True


@pytest.mark.parametrize("impl", IMPLS)
def test_later_continuation_with_predecessor_still_passes(impl):
    m, verify, _ = IMPLS[impl]
    calls = _square(m)
    calls[1] = calls[1].model_copy(
        update={"along": "continuing", "bearing_azimuth_deg_from_north": 0.0}
    )
    parallel = next(c for c in verify(calls).checks if c.name == "parallelism")
    assert parallel.status != "blocked"


def _delta_curve(m, course, **extra):
    return m.DeedCall(
        course=course,
        direction_text="curve",
        bearing_azimuth_deg_from_north=90.0,
        distance_ft=100.0,
        curve_dir="right",
        radius_ft=100.0,
        delta_deg=60.0,
        **extra,
    )


@pytest.mark.parametrize("impl", IMPLS)
def test_failed_curve_check_stays_failed_with_bad_chord(impl):
    m, verify, _ = IMPLS[impl]
    calls = [
        _line(m, 1, 0.0),
        _delta_curve(m, 2, arc_length_ft=200.0),  # inconsistent with radius/delta
        _delta_curve(m, 3, chord_bearing="northeasterly"),
    ]
    result = verify(calls)
    assert {c.name: c.status for c in result.checks}["curve_consistency"] == "failed"


@pytest.mark.parametrize("impl", IMPLS)
def test_curve_blocks_combine_every_applicable_reason(impl):
    m, verify, _ = IMPLS[impl]
    calls = [
        _line(m, 1, 0.0),
        _chord_curve(m, 100.0),
        _delta_curve(m, 3, chord_bearing="northeasterly"),
    ]
    check = next(c for c in verify(calls).checks if c.name == "curve_consistency")
    assert check.status == "blocked"
    assert "curve_delta_not_stated" in check.reason
    assert "invalid_chord_bearing" in check.reason
    assert "course(s) 2" in check.detail and "course(s) 3" in check.detail
