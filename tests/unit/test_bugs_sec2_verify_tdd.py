"""Red-Green TDD tests for Section 2 verification parity & geometry fixes."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import mp_verify.checks as mp_checks
import mp_verify.closure as mp_closure
import mp_verify.confidence as mp_confidence
import pytest
from mp_models import (
    AuditContext as PkgAuditContext,
)
from mp_models import (
    ClosureResult as PkgClosureResult,
)
from mp_models import (
    DeedCall as PkgDeedCall,
)
from mp_models import (
    Point as PkgPoint,
)
from mp_models import (
    RunMetadata as PkgRunMetadata,
)
from mp_models import (
    Tract as PkgTract,
)
from mp_models import (
    TractType as PkgTractType,
)

from metesparser.closure_checker import ClosureChecker
from metesparser.models import (
    AuditContext,
    ClosureResult,
    DeedCall,
    Point,
    RunMetadata,
    Tract,
    TractType,
)


@pytest.fixture(params=["package", "monolith"])
def verify_api(request):
    """Provide symmetric package and monolith verification APIs."""
    if request.param == "package":
        return {
            "call": PkgDeedCall,
            "point": PkgPoint,
            "result": PkgClosureResult,
            "tract": PkgTract,
            "tract_type": PkgTractType,
            "audit": PkgAuditContext,
            "run_meta": PkgRunMetadata,
            "verify_closure": mp_closure.verify_closure,
            "compare_double_entry": mp_checks.compare_double_entry,
            "check_intersections": mp_checks.check_straight_boundary_intersections,
            "check_distance": mp_checks.check_distance_reasonableness,
            "calc_confidence": mp_confidence.calculate_confidence_score,
        }
    return {
        "call": DeedCall,
        "point": Point,
        "result": ClosureResult,
        "tract": Tract,
        "tract_type": TractType,
        "audit": AuditContext,
        "run_meta": RunMetadata,
        "verify_closure": ClosureChecker.verify_closure,
        "compare_double_entry": ClosureChecker.compare_double_entry,
        "check_intersections": ClosureChecker.check_straight_boundary_intersections,
        "check_distance": ClosureChecker.check_distance_reasonableness,
        "calc_confidence": ClosureChecker.calculate_confidence_score,
    }


def _square(call_cls, size: float = 100.0, *, start_course: int = 1, is_exception: bool = False):
    return [
        call_cls(
            course=start_course + i,
            direction_text=f"course {start_course + i}",
            bearing_azimuth_deg_from_north=az,
            distance_ft=size,
            is_exception=is_exception,
        )
        for i, az in enumerate((0.0, 90.0, 180.0, 270.0))
    ]


def _make_audit_ctx(api):
    return api["audit"](
        run_metadata=api["run_meta"](
            parser_version="0.5.0",
            llm_provider="test",
            llm_model="test-model",
            prompt_hash="abc",
            timestamp_utc=datetime(2026, 1, 1, tzinfo=UTC),
            source_pdf="deed.pdf",
            cache_enabled=False,
        )
    )


# ---------------------------------------------------------------------------
# Item 1: Curve consistency parity between monolith and mp-verify
# ---------------------------------------------------------------------------


def test_item1_monolith_and_package_curve_consistency_warnings_and_confidence_match():
    """Monolith verify_closure must emit curve warnings matching mp-verify."""
    pkg_calls = [
        PkgDeedCall(
            course=1,
            direction_text="curve",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=100.0,
            curve_dir="right",
            radius_ft=100.0,
            delta_deg=90.0,
            arc_length_ft=10.0,
            chord_length_ft=10.0,
        ),
        *_square(PkgDeedCall, start_course=2)[1:],
    ]
    mono_calls = [DeedCall.model_validate(c.model_dump()) for c in pkg_calls]

    pkg_result = mp_closure.verify_closure(pkg_calls)
    mono_result = ClosureChecker.verify_closure(mono_calls)

    assert pkg_result.curve_consistency_passed is False
    assert mono_result.curve_consistency_passed is False
    assert mono_result.warnings == pkg_result.warnings
    assert any("arc length inconsistency" in w for w in mono_result.warnings)
    assert any("chord length inconsistency" in w for w in mono_result.warnings)
    assert mono_result.confidence_score == pytest.approx(pkg_result.confidence_score)
    # Backward compatibility: ClosureChecker.check_curve_consistency still returns bool
    assert ClosureChecker.check_curve_consistency(mono_calls) is False


# ---------------------------------------------------------------------------
# Item 2: compare_double_entry field coverage & multi-tract wiring
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field_name,val1,val2",
    [
        ("is_exception", False, True),
        ("is_tie_in", False, True),
        ("is_meander", False, True),
    ],
)
def test_item2_compare_double_entry_detects_call_flag_mismatches(
    verify_api, field_name, val1, val2
):
    call_cls = verify_api["call"]
    c1 = call_cls(
        course=1,
        direction_text="N 0° E",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=100.0,
        **{field_name: val1},
    )
    c2 = c1.model_copy(update={field_name: val2})
    discrepancies = verify_api["compare_double_entry"]([c1], [c2])
    assert len(discrepancies) == 1


@pytest.mark.parametrize(
    "field_name,val1,val2",
    [
        ("non_tangent", False, True),
        ("radial_bearing", "N 15°00' E", "S 15°00' W"),
    ],
)
def test_item2_compare_double_entry_detects_non_tangent_and_radial_bearing(
    verify_api, field_name, val1, val2
):
    call_cls = verify_api["call"]
    c1 = call_cls(
        course=1,
        direction_text="curve",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=100.0,
        curve_dir="right",
        radius_ft=100.0,
        delta_deg=90.0,
        **{field_name: val1},
    )
    c2 = c1.model_copy(update={field_name: val2})
    discrepancies = verify_api["compare_double_entry"]([c1], [c2])
    assert len(discrepancies) == 1


def test_item2_multi_tract_verify_closure_runs_double_entry_and_records_audit(verify_api):
    call_cls = verify_api["call"]
    tract_cls = verify_api["tract"]
    tract_type = verify_api["tract_type"]

    c1 = _square(call_cls, 100.0, start_course=1)
    c2 = _square(call_cls, 50.0, start_course=5)
    t1 = tract_cls(label="Tract 1", tract_type=tract_type.MAIN, calls=c1)
    t2 = tract_cls(label="Tract 2", tract_type=tract_type.MAIN, calls=c2)

    de_calls = [*c1, *c2]
    de_calls[5] = de_calls[5].model_copy(update={"distance_ft": 55.0})

    ctx = _make_audit_ctx(verify_api)
    results = verify_api["verify_closure"](
        c1 + c2,
        tracts=[t1, t2],
        double_entry_calls=de_calls,
        audit_context=ctx,
    )

    assert len(results) == 2
    assert any(any("Double-entry discrepancy" in w for w in result.warnings) for result in results)
    assert not all(r.is_fully_verified() for r in results)
    assert ctx.verification_audit is not None
    de_check = next(c for c in ctx.verification_audit.checks if c.name == "double_entry")
    assert de_check.passed is False


# ---------------------------------------------------------------------------
# Item 3: Tolerance propagation & min 3 calls for straight exception loops
# ---------------------------------------------------------------------------


def test_item3_relaxed_tolerance_propagates_to_exception_area(verify_api):
    """Exception tract closing within custom tolerance (0.05 < 0.10) should compute net area."""
    call_cls = verify_api["call"]
    main = _square(call_cls, 100.0, start_course=1)
    exc = _square(call_cls, 20.0, start_course=5, is_exception=True)
    # Make last exception edge 20.05 ft -> 0.05 ft misclosure (> 0.01, < 0.10)
    exc[-1] = exc[-1].model_copy(update={"distance_ft": 20.05})

    result = verify_api["verify_closure"](main + exc, closure_tolerance_ft=0.10)
    assert result.area_sq_ft == pytest.approx(9600.0, abs=5.0)
    assert not any("Cannot calculate exception area" in w for w in result.warnings)


def test_item3_tolerance_propagates_to_self_intersection_check(verify_api):
    """Closing vertex 0.05 ft along first edge is closed under 0.10 tolerance (not a self-intersection)."""
    call_cls = verify_api["call"]
    # Square whose 4th edge ends at (0, 0.05) instead of (0, 0) — right on edge 1 [(0,0)->(0,100)]
    calls = [
        call_cls(
            course=1, direction_text="N", bearing_azimuth_deg_from_north=0.0, distance_ft=100.0
        ),
        call_cls(
            course=2, direction_text="E", bearing_azimuth_deg_from_north=90.0, distance_ft=100.0
        ),
        call_cls(
            course=3, direction_text="S", bearing_azimuth_deg_from_north=180.0, distance_ft=99.95
        ),
        call_cls(
            course=4, direction_text="W", bearing_azimuth_deg_from_north=270.0, distance_ft=100.0
        ),
    ]
    result = verify_api["verify_closure"](calls, closure_tolerance_ft=0.10)
    assert result.closure_passed is True
    assert not any("self-intersection" in w for w in result.warnings)


def test_item3_exception_area_rejects_one_call_tiny_straight_and_two_call_straight(verify_api):
    """1-call <0.01 ft or 2-call straight exception must not prematurely close an exception loop."""
    call_cls = verify_api["call"]
    main = _square(call_cls, 100.0, start_course=1)

    # 1-call straight exception of 0.005 ft (< 0.01 ft)
    one_call_exc = [
        call_cls(
            course=5,
            direction_text="N",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=0.005,
            is_exception=True,
        )
    ]
    res_one = verify_api["verify_closure"](main + one_call_exc)
    assert res_one.area_sq_ft == 0.0
    assert any("Cannot calculate exception area" in w for w in res_one.warnings)

    # 2-call out-and-back straight exception (returns to origin with 0.0 ft misclosure)
    two_call_exc = [
        call_cls(
            course=5,
            direction_text="N",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=10.0,
            is_exception=True,
        ),
        call_cls(
            course=6,
            direction_text="S",
            bearing_azimuth_deg_from_north=180.0,
            distance_ft=10.0,
            is_exception=True,
        ),
    ]
    res_two = verify_api["verify_closure"](main + two_call_exc)
    assert res_two.area_sq_ft == 0.0
    assert any("Cannot calculate exception area" in w for w in res_two.warnings)


# ---------------------------------------------------------------------------
# Item 4: Negative net area guard
# ---------------------------------------------------------------------------


def test_item4_exception_area_exceeding_main_area_clamps_to_zero_and_warns(verify_api):
    call_cls = verify_api["call"]
    main = _square(call_cls, 50.0, start_course=1)  # 2,500 sq ft
    exc = _square(call_cls, 100.0, start_course=5, is_exception=True)  # 10,000 sq ft

    result = verify_api["verify_closure"](main + exc)
    assert result.area_sq_ft == 0.0
    assert result.area_acres == 0.0
    assert not result.is_fully_verified()
    assert any("exceeds main tract area" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# Item 5: Degenerate traverses & self_intersection_passed scoring
# ---------------------------------------------------------------------------


def test_item5_cardinal_only_traverse_has_none_precision_and_zero_confidence(verify_api):
    call_cls = verify_api["call"]
    calls = [
        call_cls(course=1, direction_text="Northerly", distance_ft=100.0),
        call_cls(course=2, direction_text="Easterly", distance_ft=100.0),
        call_cls(course=3, direction_text="Southerly", distance_ft=100.0),
        call_cls(course=4, direction_text="Westerly", distance_ft=100.0),
    ]
    result = verify_api["verify_closure"](calls)
    assert result.closure_passed is False
    assert result.perimeter_ft == pytest.approx(400.0)
    assert result.precision_ratio is None
    assert result.confidence_score == 0.0


def test_item5_empty_traverse_has_none_precision_and_zero_confidence(verify_api):
    result = verify_api["verify_closure"]([])
    assert result.precision_ratio is None
    assert result.confidence_score == 0.0


def test_item5_zero_perimeter_traverse_has_none_precision_and_zero_confidence(verify_api):
    call_cls = verify_api["call"]
    calls = [
        call_cls.model_construct(
            course=1,
            direction_text="N 0° E",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=0.0,
        )
    ]
    result = verify_api["verify_closure"](calls)
    assert result.perimeter_ft == 0.0
    assert result.precision_ratio is None
    assert result.confidence_score == 0.0


def test_item5_self_intersection_reduces_checks_score_in_confidence(verify_api):
    call_cls = verify_api["call"]
    result_cls = verify_api["result"]
    calls = _square(call_cls, 100.0)
    clean_result = result_cls(
        misclosure_x_ft=0.0,
        misclosure_y_ft=0.0,
        misclosure_ft=0.0,
        area_sq_ft=10000.0,
        area_acres=10000.0 / 43560.0,
        perimeter_ft=400.0,
        closure_passed=True,
        angle_check_passed=True,
        curve_consistency_passed=True,
        warnings=[],
    )
    score_pass = verify_api["calc_confidence"](clean_result, calls, self_intersection_passed=True)
    score_fail = verify_api["calc_confidence"](clean_result, calls, self_intersection_passed=False)
    assert score_fail == pytest.approx(score_pass - 0.20 / 3.0)


# ---------------------------------------------------------------------------
# Item 6: check_distance_reasonableness() curve arc lengths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("chord_distance", [0.0, 0.1])
def test_item6_check_distance_reasonableness_uses_arc_length_for_curves(verify_api, chord_distance):
    call_cls = verify_api["call"]
    arc_len = 100.0 * math.pi / 2.0  # ~157.08 ft
    straight = call_cls(
        course=1,
        direction_text="N 0° E",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=150.0,
    )
    # Use model_construct when chord_distance == 0.0 to bypass gt=0 validation if present
    if chord_distance == 0.0:
        curve = call_cls.model_construct(
            course=2,
            direction_text="curve",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=0.0,
            curve_dir="right",
            radius_ft=100.0,
            delta_deg=90.0,
            arc_length_ft=arc_len,
        )
    else:
        curve = call_cls(
            course=2,
            direction_text="curve",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=chord_distance,
            curve_dir="right",
            radius_ft=100.0,
            delta_deg=90.0,
            arc_length_ft=arc_len,
        )
    warnings = verify_api["check_distance"]([straight, curve])
    assert not any("suspiciously short" in w for w in warnings)
