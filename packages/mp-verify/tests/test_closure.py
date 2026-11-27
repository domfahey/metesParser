"""Tests for mp_verify closure verification."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest
from mp_models import (
    AuditContext,
    ClosureResult,
    DeedCall,
    Point,
    RunMetadata,
    SkippedCourse,
    Tract,
    TractType,
)
from mp_verify import get_closure_summary, verify_closure
from mp_verify.closure import calculate_area, calculate_perimeter


def _square_calls(
    size: float = 100.0, *, is_exception: bool = False, start: int = 1
) -> list[DeedCall]:
    specs = (
        ("North", "N 00\u00b000' E", 0.0),
        ("East", "N 90\u00b000' E", 90.0),
        ("South", "S 00\u00b000' E", 180.0),
        ("West", "N 90\u00b000' W", 270.0),
    )
    return [
        DeedCall(
            course=start + i,
            direction_text=text,
            bearing_quadrant=quad,
            bearing_azimuth_deg_from_north=az,
            distance_ft=size,
            is_exception=is_exception,
        )
        for i, (text, quad, az) in enumerate(specs)
    ]


def _audit_ctx() -> AuditContext:
    return AuditContext(
        run_metadata=RunMetadata(
            parser_version="test",
            llm_provider="test",
            llm_model="test",
            prompt_hash="abc",
            timestamp_utc=datetime.now(UTC),
            source_pdf="deed.pdf",
            cache_enabled=False,
        )
    )


def test_verify_closure_square():
    """A perfect 100ft square closes, verifies, and reports exact area/perimeter/confidence."""
    result = verify_closure(_square_calls())
    assert isinstance(result, ClosureResult)
    assert result.closure_passed is True
    assert result.geometry_verified is True
    assert result.misclosure_ft < 0.01
    assert result.area_sq_ft == pytest.approx(10000.0)
    assert result.area_acres == pytest.approx(10000.0 / 43560.0)
    assert result.perimeter_ft == pytest.approx(400.0)
    assert result.confidence_score == pytest.approx(1.0)
    assert result.warnings == []
    assert all(c.status in {"passed", "not_applicable"} for c in result.checks)


def test_verify_closure_open_traverse_fails():
    """A traverse that doesn't close should fail."""
    calls = _square_calls()[:2]
    result = verify_closure(calls)
    assert not result.closure_passed
    assert result.misclosure_ft == pytest.approx(math.hypot(100.0, 100.0))
    assert not result.geometry_verified


def test_verify_closure_stated_area_warning():
    """Should warn when computed area differs from stated area by >5%."""
    result = verify_closure(_square_calls(), stated_area_sq_ft=50000.0)
    assert any("differs from stated" in w for w in result.warnings)
    assert not result.geometry_verified


def test_get_closure_summary_contains_sections_and_variants():
    """get_closure_summary formats verified, undetermined, precision-ratio, and legacy results."""
    calls = _square_calls()
    result = verify_closure(calls)
    summary = get_closure_summary(result, calls)
    assert "CLOSURE VERIFICATION SUMMARY" in summary
    assert "Misclosure" in summary
    assert "Area" in summary
    assert "Verification Checks" in summary
    assert "FULLY VERIFIED" in summary

    # Non-zero misclosure shows precision ratio 1:N.
    near = _square_calls()
    near[-1] = near[-1].model_copy(update={"distance_ft": 99.95})
    near_res = verify_closure(near)
    near_summary = get_closure_summary(near_res, near)
    assert "Precision: 1:" in near_summary
    assert "NEEDS REVIEW" in near_summary

    # Undetermined misclosure and legacy empty-checks fallback.
    legacy = ClosureResult(
        misclosure_x_ft=0.0,
        misclosure_y_ft=0.0,
        misclosure_ft=0.0,
        misclosure_available=False,
        area_sq_ft=0.0,
        area_acres=0.0,
        area_available=False,
        perimeter_ft=0.0,
        perimeter_available=False,
        closure_passed=False,
        angle_check_passed=True,
        curve_consistency_passed=False,
        checks=[],
    )
    legacy_summary = get_closure_summary(legacy)
    assert "Misclosure: not determined" in legacy_summary
    assert "Closure: FAIL" in legacy_summary
    assert "Angles: PASS" in legacy_summary
    assert "Curves: FAIL" in legacy_summary


@pytest.mark.parametrize("bad_chord", ["S 0 E", "S34-57E", "South"])
def test_unparseable_chord_bearing_blocks_instead_of_raising(bad_chord):
    """#72: an unparseable chord bearing must block the curve check, not crash."""
    calls = [
        DeedCall(
            course=1,
            direction_text="N",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=100.0,
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
            chord_bearing=bad_chord,
        ),
        DeedCall(
            course=3,
            direction_text="S",
            bearing_azimuth_deg_from_north=180.0,
            distance_ft=100.0,
        ),
    ]
    result = verify_closure(calls)
    assert not result.geometry_verified
    assert any("chord bearing" in w.lower() for w in result.warnings)
    curve = next(c for c in result.checks if c.name == "curve_consistency")
    assert curve.status == "blocked"


def test_bad_chord_on_one_call_does_not_strip_chord_from_same_course_number():
    """PR #60 review: a bad chord must only block its own call, not a sibling sharing a course number."""

    def curve(chord: str | None) -> DeedCall:
        return DeedCall(
            course=2,
            direction_text="curve",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=100.0,
            curve_dir="right",
            radius_ft=100.0,
            delta_deg=60.0,
            arc_length_ft=104.72,
            chord_bearing=chord,
        )

    valid = curve("S 30° E")
    bad = curve("South")
    from mp_verify.traverse import traverse_positions

    # Only the unreadable-chord call is blocked; its sibling stays positioned.
    assert traverse_positions([valid, bad])[1] == [True, False]
    combined = verify_closure([valid, bad])
    assert combined.misclosure_available is False
    assert any("South" in w and "chord bearing" in w.lower() for w in combined.warnings)


class TestAreaPerimeterAndParameterValidation:
    def test_calculate_area_requires_at_least_two_points(self):
        with pytest.raises(ValueError, match="Cannot calculate area"):
            calculate_area([Point(x=0.0, y=0.0)])

    def test_calculate_perimeter_rejects_undetermined_spiral_distance(self):
        spiral = DeedCall(
            course=1,
            direction_text="spiral",
            distance_ft=None,
            curve_type="spiral",
            curve_dir="right",
            radius_ft=150.0,
            delta_deg=15.0,
        )
        with pytest.raises(ValueError, match="distance not determined"):
            calculate_perimeter([spiral])

    @pytest.mark.parametrize("bad_value", [-1.0, float("nan"), float("inf"), True])
    def test_invalid_numeric_parameters_rejected(self, bad_value):
        with pytest.raises(ValueError, match="stated_area_sq_ft"):
            verify_closure(_square_calls(), stated_area_sq_ft=bad_value)
        with pytest.raises(ValueError, match="closure_tolerance_ft"):
            verify_closure(_square_calls(), closure_tolerance_ft=bad_value)


class TestExceptionAreaSubtractionInvariants:
    def test_valid_closed_exception_with_tie_in_subtracts_from_main_area(self):
        main = _square_calls(100.0, start=1)
        exc_tie = DeedCall(
            course=5,
            direction_text="East",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=10.0,
            is_exception=True,
            is_tie_in=True,
        )
        exc = _square_calls(50.0, is_exception=True, start=6)
        result = verify_closure([*main, exc_tie, *exc])
        assert result.area_available is True
        assert result.area_sq_ft == pytest.approx(10000.0 - 2500.0)
        assert any("subtract" in w for w in result.warnings)

    def test_exception_larger_than_main_clamps_to_zero_and_marks_unavailable(self):
        main = _square_calls(50.0, start=1)
        exc = _square_calls(100.0, is_exception=True, start=5)
        result = verify_closure([*main, *exc])
        assert result.area_available is False
        assert result.area_sq_ft == 0.0
        assert any("exceeds main parcel area" in w for w in result.warnings)

    def test_unclosed_exception_leaves_net_area_unavailable(self):
        main = _square_calls(100.0, start=1)
        exc_open = _square_calls(50.0, is_exception=True, start=5)[:3]
        result = verify_closure([*main, *exc_open])
        assert result.area_available is False
        assert result.area_sq_ft == 0.0
        assert any("does not close" in w for w in result.warnings)

    def test_exception_incomplete_bearing_reports_both_warnings(self):
        main = _square_calls(100.0, start=1)
        exc_bad = [
            DeedCall(course=5, direction_text="northerly", distance_ft=50.0, is_exception=True)
        ]
        result = verify_closure([*main, *exc_bad])
        assert result.area_available is False
        assert any("incomplete bearing; net area unavailable" in w for w in result.warnings)
        assert any("Exception tract has 1 incomplete bearing(s)" in w for w in result.warnings)

    def test_exception_chord_only_curve_and_infeasible_curve_block_net_area(self):
        main = _square_calls(100.0, start=1)
        chord_only = DeedCall(
            course=5,
            direction_text="curve",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=50.0,
            curve_dir="right",
            radius_ft=100.0,
            chord_bearing="N 45° E",
            chord_length_ft=50.0,
            is_exception=True,
        )
        res_chord = verify_closure([*main, chord_only])
        assert res_chord.area_available is False
        assert any(
            "curve delta/arc not stated; net area unavailable" in w for w in res_chord.warnings
        )

        # Bad chord bearing with sweep cannot be positioned in exception loop.
        unpos = DeedCall(
            course=5,
            direction_text="curve",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=104.72,
            curve_dir="right",
            radius_ft=100.0,
            delta_deg=60.0,
            arc_length_ft=104.72,
            chord_bearing="BAD",
            is_exception=True,
        )
        res_unpos = verify_closure([*main, unpos])
        assert res_unpos.area_available is False
        assert any("cannot be positioned; net area unavailable" in w for w in res_unpos.warnings)

    def test_exception_self_intersection_and_inconsistent_curve_block_net_area(self):
        main = _square_calls(200.0, start=1)
        # Closed bow-tie exception: N 100, SE sqrt(2)*100, N 100, SW sqrt(2)*100 -> closes at origin.
        diag = math.hypot(100.0, 100.0)
        bowtie = [
            DeedCall(
                course=5,
                direction_text="N",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
                is_exception=True,
            ),
            DeedCall(
                course=6,
                direction_text="SE",
                bearing_azimuth_deg_from_north=135.0,
                distance_ft=diag,
                is_exception=True,
            ),
            DeedCall(
                course=7,
                direction_text="N",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=100.0,
                is_exception=True,
            ),
            DeedCall(
                course=8,
                direction_text="SW",
                bearing_azimuth_deg_from_north=225.0,
                distance_ft=diag,
                is_exception=True,
            ),
        ]
        res_bow = verify_closure([*main, *bowtie])
        assert res_bow.area_available is False
        assert any("Exception tract topology failed" in w for w in res_bow.warnings)

        # Closed 2-semicircle exception where arc_length_ft contradicts R*delta.
        bad_arc = [
            DeedCall(
                course=5,
                direction_text="curve",
                bearing_azimuth_deg_from_north=0.0,
                distance_ft=200.0,
                curve_dir="right",
                radius_ft=20.0,
                delta_deg=180.0,
                arc_length_ft=200.0,
                is_exception=True,
            ),
            DeedCall(
                course=6,
                direction_text="curve",
                bearing_azimuth_deg_from_north=180.0,
                distance_ft=20.0 * math.pi,
                curve_dir="right",
                radius_ft=20.0,
                delta_deg=180.0,
                arc_length_ft=20.0 * math.pi,
                is_exception=True,
            ),
        ]
        res_curve = verify_closure([*main, *bad_arc])
        assert res_curve.area_available is False
        assert any("inconsistent curves; net area unavailable" in w for w in res_curve.warnings)


class TestMultiTractDoubleEntrySkipsAndAudit:
    def test_multi_tract_stated_area_conflict_and_sole_boundary_fallback(self):
        t1 = Tract(
            label="Tract 1",
            tract_type=TractType.MAIN,
            role_basis="heading",
            stated_area_sq_ft=10000.0,
            calls=_square_calls(100.0),
        )
        easement = Tract(
            label="Easement 1",
            tract_type=TractType.EASEMENT,
            role_basis="heading",
            calls=_square_calls(20.0),
        )
        # Conflicting deed-level stated_area_sq_ft raises ValueError.
        with pytest.raises(ValueError, match="conflicts with boundary tract"):
            verify_closure([], tracts=[t1, easement], stated_area_sq_ft=20000.0)

        # Matching deed-level stated_area_sq_ft uses tract's stated_area_sq_ft cleanly.
        res_match = verify_closure([], tracts=[t1, easement], stated_area_sq_ft=10000.0)
        assert res_match[0].geometry_verified is True

        # When sole boundary tract has stated_area_sq_ft=None, deed-level area applies to it.
        t1_no_area = t1.model_copy(update={"stated_area_sq_ft": None})
        res_fallback = verify_closure([], tracts=[t1_no_area, easement], stated_area_sq_ft=50000.0)
        assert any("differs from stated" in w for w in res_fallback[0].warnings)
        assert not any("differs from stated" in w for w in res_fallback[1].warnings)

    def test_single_and_multi_tract_double_entry_validation(self):
        calls = _square_calls(100.0)
        altered = list(calls)
        altered[0] = altered[0].model_copy(update={"distance_ft": 105.0})

        # Single tract double-entry discrepancy fails double_entry check.
        res_single = verify_closure(calls, double_entry_calls=altered)
        assert any("Double-entry discrepancy" in w for w in res_single.warnings)
        assert res_single.geometry_verified is False

        # Multi-tract matching count slices per tract.
        t1 = Tract(
            label="A", tract_type=TractType.MAIN, role_basis="heading", calls=_square_calls(100.0)
        )
        t2 = Tract(
            label="B", tract_type=TractType.MAIN, role_basis="heading", calls=_square_calls(50.0)
        )
        res_ok = verify_closure([], tracts=[t1, t2], double_entry_calls=[*t1.calls, *t2.calls])
        assert all(r.geometry_verified for r in res_ok)

        # Multi-tract mismatched total call count flags every tract with override error.
        res_bad = verify_closure([], tracts=[t1, t2], double_entry_calls=t1.calls)
        assert all(any("multi-tract total" in w for w in r.warnings) for r in res_bad)
        assert all(not r.geometry_verified for r in res_bad)

    def test_skipped_courses_block_closure_and_audit_precision_ratio_formatted(self):
        from mp_models import mark_non_boundary

        skip = SkippedCourse(
            course=2,
            source_course=2,
            source_excerpt="garbled line",
            error_type="parse_error",
            error="unreadable bearing",
        )
        res_skip = verify_closure(_square_calls(), skipped_courses=[skip])
        assert res_skip.closure_passed is False
        assert res_skip.misclosure_available is False
        assert res_skip.area_available is False
        assert res_skip.perimeter_available is False
        closure_check = next(c for c in res_skip.checks if c.name == "traverse_closure")
        assert closure_check.status == "blocked"
        assert closure_check.reason == "skipped_courses"

        # Calls marked as easement tract stay blocked even when verified flat without their tract.
        marked_easement = mark_non_boundary(_square_calls(), TractType.EASEMENT)
        res_marked = verify_closure(marked_easement)
        assert res_marked.closure_passed is True
        assert res_marked.geometry_verified is False
        nb_check = next(c for c in res_marked.checks if c.name == "non_boundary_tract")
        assert nb_check.status == "blocked"
        assert nb_check.reason == "easement"

        # Non-zero misclosure records a 1:N precision ratio in VerificationAudit.
        near = _square_calls()
        near[-1] = near[-1].model_copy(update={"distance_ft": 99.95})
        ctx = _audit_ctx()
        verify_closure(near, audit_context=ctx)
        assert ctx.verification_audit is not None
        assert ctx.verification_audit.closure_summary["precision_ratio"].startswith("1:")
