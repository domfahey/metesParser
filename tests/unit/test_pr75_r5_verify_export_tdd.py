"""Red-Green TDD regression tests for PR #75 round 5 (mp-verify, mp-export, ClosureChecker)."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import mp_verify.checks as pkg_checks
import mp_verify.closure as pkg_closure
import mp_verify.confidence as pkg_confidence
import mp_verify.topology as pkg_topology
import pytest
from mp_export.csv_writer import (
    _results_match,
    csv_to_calls,
    export_verified_csv,
    legal_description_to_csv,
)
from mp_models import (
    EASEMENT_TRACT_NOTE,
    EXCEPTION_TRACT_NOTE,
    CheckResult,
    ClosureResult,
    DeedCall,
    LegalDescription,
    SkippedCourse,
    Tract,
    TractType,
    split_notes,
)
from mp_verify import verify_closure, verify_tract
from mp_verify.checks import (
    check_boundary_intersections,
    check_distance_reasonableness,
    check_straight_boundary_intersections,
)
from mp_verify.confidence import calculate_confidence_score
from mp_verify.topology import check_curved_boundary_intersections

from metesparser.closure_checker import ClosureChecker
from metesparser.csv_builder import CSVBuilder
from metesparser.models import DeedCall as MonoDeedCall
from metesparser.models import LegalDescription as MonoLegalDescription
from metesparser.models import Point as MonoPoint
from metesparser.models import Tract as MonoTract
from metesparser.models import TractType as MonoTractType


def _line(course: int, azimuth: float, distance: float, **extra: Any) -> DeedCall:
    return DeedCall(
        course=course,
        direction_text=f"az {azimuth}",
        bearing_azimuth_deg_from_north=azimuth,
        distance_ft=distance,
        **extra,
    )


def _square(size: float = 100.0, course_start: int = 1, **extra: Any) -> list[DeedCall]:
    return [
        _line(course_start + i, az, size, **extra) for i, az in enumerate((0.0, 90.0, 180.0, 270.0))
    ]


def _mono_square(size: float = 100.0) -> list[MonoDeedCall]:
    return [
        MonoDeedCall(
            course=i + 1,
            direction_text=f"az {az}",
            bearing_azimuth_deg_from_north=az,
            distance_ft=size,
        )
        for i, az in enumerate((0.0, 90.0, 180.0, 270.0))
    ]


# ---------------------------------------------------------------------------
# Item 1: _verify_tract treat_exceptions_as_boundary only on EXCEPTION tracts
# ---------------------------------------------------------------------------


def test_main_and_addition_tracts_with_exception_calls_do_not_verify_or_export(
    tmp_path: Path,
) -> None:
    exc_only = _square(100.0, is_exception=True)
    main_tract = Tract(
        label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=exc_only
    )
    add_tract = Tract(
        label="Addition 1", tract_type=TractType.ADDITION, role_basis="heading", calls=exc_only
    )

    # Multi-tract verify_closure and direct verify_tract(..., tract=...) must not fold
    # is_exception calls into boundary geometry for MAIN or ADDITION tracts.
    (main_res,) = verify_closure([], tracts=[main_tract])
    assert main_res.closure_passed is False
    assert main_res.is_fully_verified() is False

    assert verify_tract(exc_only, tract=main_tract).is_fully_verified() is False
    assert verify_tract(exc_only, tract=add_tract).is_fully_verified() is False

    # Tract-unaware verify_tract(exc_only) still computes review closure/area, but blocks
    # full verification (non_boundary_tract); neither it nor a forged verified boundary
    # result can bypass multi-tract export validation.
    exc_unaware = verify_tract(exc_only)
    assert exc_unaware.closure_passed is True
    assert exc_unaware.area_sq_ft == pytest.approx(10000.0)
    assert exc_unaware.is_fully_verified() is False
    assert any(c.name == "non_boundary_tract" and c.status == "blocked" for c in exc_unaware.checks)

    forged = verify_tract(_square(100.0))
    assert forged.is_fully_verified() is True
    for bad_tract in (main_tract, add_tract):
        for candidate in (exc_unaware, forged):
            with pytest.raises(ValueError, match="Cannot export verified CSV"):
                export_verified_csv(
                    [],
                    candidate,
                    str(tmp_path / "deed.csv"),
                    tract_results=[(bad_tract, candidate)],
                )
    assert list(tmp_path.iterdir()) == []

    # Mixed main + exception calls inside a MAIN tract subtract exceptions rather than merging.
    mixed_calls = [
        *_square(100.0, course_start=1),
        *_square(20.0, course_start=5, is_exception=True),
    ]
    mixed_main = Tract(
        label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=mixed_calls
    )
    mixed_res = verify_tract(mixed_calls, tract=mixed_main)
    assert mixed_res.area_available is True
    assert mixed_res.area_sq_ft == pytest.approx(10000.0 - 400.0)
    assert mixed_res.is_fully_verified() is False

    # Positive control: an EXCEPTION tract still computes review-only closure while blocked.
    exc_tract = Tract(
        label="Exception 1", tract_type=TractType.EXCEPTION, role_basis="heading", calls=exc_only
    )
    exc_res = verify_tract(exc_only, tract=exc_tract)
    assert exc_res.closure_passed is True
    assert exc_res.area_sq_ft == pytest.approx(10000.0)
    assert exc_res.is_fully_verified() is False
    assert any(c.name == "non_boundary_tract" and c.status == "blocked" for c in exc_res.checks)


# ---------------------------------------------------------------------------
# Item 2: legal_description_to_csv preserves non-boundary and role-review marks
# ---------------------------------------------------------------------------


def test_legal_description_to_csv_preserves_easement_blocker_on_reimport(tmp_path: Path) -> None:
    easement_calls = _square(30.0)
    easement_tract = Tract(
        label="Easement 1",
        tract_type=TractType.EASEMENT,
        role_basis="heading",
        calls=easement_calls,
    )

    # Empty calls falling back to tracts
    out_empty = tmp_path / "easement_empty.csv"
    legal_description_to_csv(LegalDescription(calls=[], tracts=[easement_tract]), str(out_empty))
    loaded_empty = csv_to_calls(str(out_empty))
    res_empty = verify_closure(loaded_empty)
    assert res_empty.is_fully_verified() is False
    assert any(c.name == "non_boundary_tract" and c.status == "blocked" for c in res_empty.checks)

    # Populated calls on an easement-only LegalDescription
    out_pop = tmp_path / "easement_pop.csv"
    legal_description_to_csv(
        LegalDescription(calls=easement_calls, tracts=[easement_tract]), str(out_pop)
    )
    loaded_pop = csv_to_calls(str(out_pop))
    res_pop = verify_closure(loaded_pop)
    assert res_pop.is_fully_verified() is False
    assert any(c.name == "non_boundary_tract" and c.status == "blocked" for c in res_pop.checks)

    # Original calls remain unmutated.
    assert all(c.notes is None for c in easement_calls)


def test_legal_description_to_csv_preserves_inferred_role_blocker_on_reimport(
    tmp_path: Path,
) -> None:
    calls = _square(100.0)
    inferred_tract = Tract(
        label="Tract 1", tract_type=TractType.MAIN, role_basis="inferred", calls=calls
    )

    for label, legal in (
        ("fallback", LegalDescription(calls=[], tracts=[inferred_tract])),
        ("explicit_calls", LegalDescription(calls=calls, tracts=[inferred_tract])),
        (
            "multi_inferred",
            LegalDescription(
                calls=calls,
                tracts=[
                    Tract(
                        label="Tract 1",
                        tract_type=TractType.MAIN,
                        role_basis="heading",
                        calls=calls,
                    ),
                    Tract(
                        label="Addition 1",
                        tract_type=TractType.ADDITION,
                        role_basis="inferred",
                        calls=_square(50.0),
                    ),
                ],
            ),
        ),
    ):
        out = tmp_path / f"{label}.csv"
        legal_description_to_csv(legal, str(out))
        loaded = csv_to_calls(str(out))
        res = verify_closure(loaded)
        assert res.is_fully_verified() is False, label
        assert any(
            c.name == "description_roles_inferred" and c.status == "blocked" for c in res.checks
        ), label


def test_legal_description_to_csv_preserves_exception_flag_and_blocker(tmp_path: Path) -> None:
    # Calls inside an EXCEPTION tract that omitted is_exception=True
    raw_calls = _square(25.0)
    exc_tract = Tract(
        label="Exception 1", tract_type=TractType.EXCEPTION, role_basis="heading", calls=raw_calls
    )
    out = tmp_path / "exception.csv"
    legal_description_to_csv(LegalDescription(calls=[], tracts=[exc_tract]), str(out))

    loaded = csv_to_calls(str(out))
    assert len(loaded) == 4
    assert all(c.is_exception is True for c in loaded)
    res = verify_closure(loaded)
    assert res.is_fully_verified() is False
    assert any(c.name == "non_boundary_tract" and c.status == "blocked" for c in res.checks)
    # Original calls remain unmutated.
    assert all(c.is_exception is False and c.notes is None for c in raw_calls)


# ---------------------------------------------------------------------------
# Item 3: export_verified_csv fresh summary with double_entry_calls & structural check
# ---------------------------------------------------------------------------


def test_export_verified_csv_historical_result_with_double_entry_writes_fresh_summary(
    tmp_path: Path,
) -> None:
    calls = _square(100.0)
    de = _square(100.0)
    fresh_expected = verify_closure(calls, double_entry_calls=de)
    assert fresh_expected.confidence_score is not None

    payload = fresh_expected.model_dump(exclude={"checks", "source_review_status"})
    payload["confidence_score"] = 0.12
    historical = ClosureResult.model_validate_json(
        ClosureResult.model_validate(payload).model_dump_json(exclude_unset=True)
    )

    # Single-tract with double_entry_calls
    single_out = tmp_path / "single" / "deed.csv"
    export_verified_csv(calls, historical, str(single_out), double_entry_calls=de)
    single_summary = (tmp_path / "single" / "deed_verified.verification.txt").read_text(
        encoding="utf-8"
    )
    assert "Confidence: 0.12" not in single_summary
    assert f"Confidence: {fresh_expected.confidence_score:.2f}" in single_summary
    assert "double_entry: PASS" in single_summary

    # Multi-tract with double_entry_calls
    tract = Tract(label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=calls)
    multi_out = tmp_path / "multi" / "deed.csv"
    export_verified_csv(
        [], historical, str(multi_out), tract_results=[(tract, historical)], double_entry_calls=de
    )
    multi_summary = (tmp_path / "multi" / "deed_verified.verification.txt").read_text(
        encoding="utf-8"
    )
    assert "Confidence: 0.12" not in multi_summary
    assert f"Confidence: {fresh_expected.confidence_score:.2f}" in multi_summary
    assert "double_entry: PASS" in multi_summary


def test_export_verified_csv_multi_tract_without_double_entry_omits_pass_and_keeps_source_review(
    tmp_path: Path,
) -> None:
    calls = _square(100.0)
    tract = Tract(label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=calls)
    (res,) = verify_closure([], tracts=[tract], double_entry_calls=calls)
    reviewed = res.model_copy(update={"source_review_status": "complete"})

    out = tmp_path / "deed.csv"
    export_verified_csv([], reviewed, str(out), tract_results=[(tract, reviewed)])

    summary = (tmp_path / "deed_verified.verification.txt").read_text(encoding="utf-8")
    assert "double_entry: PASS" not in summary
    assert "double_entry: NOT APPLICABLE" in summary
    assert "Source review: complete" in summary


def test_results_match_decouples_double_entry_prose_and_rejects_tampered_checks(
    tmp_path: Path,
) -> None:
    calls = _square(100.0)
    res = verify_closure(calls, double_entry_calls=calls)

    # Alternate non-empty detail prose on structurally valid passing double_entry check is accepted.
    reworded = res.model_copy(
        update={
            "checks": [
                c.model_copy(update={"detail": "Verified by second independent transcription"})
                if c.name == "double_entry"
                else c
                for c in res.checks
            ]
        }
    )
    prose_dir = tmp_path / "prose"
    written = export_verified_csv(calls, reworded, str(prose_dir / "deed.csv"))
    assert written == [prose_dir / "deed_verified.csv"]

    # Negative cases: forged double_entry fields or concurrent mismatch on another check.
    bad_cases: list[tuple[str, ClosureResult]] = [
        (
            "blank_detail",
            res.model_copy(
                update={
                    "checks": [
                        c.model_copy(update={"detail": "   "}) if c.name == "double_entry" else c
                        for c in res.checks
                    ]
                }
            ),
        ),
        (
            "forged_reason",
            res.model_copy(
                update={
                    "checks": [
                        c.model_copy(update={"reason": "forged"}) if c.name == "double_entry" else c
                        for c in res.checks
                    ]
                }
            ),
        ),
        (
            "forged_inputs",
            res.model_copy(
                update={
                    "checks": [
                        c.model_copy(update={"inputs": {"tampered": 1.0}})
                        if c.name == "double_entry"
                        else c
                        for c in res.checks
                    ]
                }
            ),
        ),
        (
            "forged_status_failed",
            res.model_copy(
                update={
                    "checks": [
                        c.model_copy(update={"status": "failed"}) if c.name == "double_entry" else c
                        for c in res.checks
                    ]
                }
            ),
        ),
        (
            "concurrent_other_check_mismatch",
            res.model_copy(
                update={
                    "checks": [
                        c.model_copy(update={"detail": "tampered angles"})
                        if c.name == "interior_angles"
                        else c
                        for c in res.checks
                    ]
                }
            ),
        ),
    ]
    fresh_no_de = verify_closure(calls)
    for name, bad_result in bad_cases:
        assert _results_match(bad_result, fresh_no_de, allow_external_double_entry=True) is False, (
            name
        )
        case_dir = tmp_path / name
        case_dir.mkdir()
        with pytest.raises(ValueError, match="Cannot export verified CSV"):
            export_verified_csv(calls, bad_result, str(case_dir / "deed.csv"))
        assert list(case_dir.iterdir()) == [], name


# ---------------------------------------------------------------------------
# Item 4: calculate_confidence_score tie-in positioning, perf, checks completeness
# ---------------------------------------------------------------------------


def test_confidence_score_zero_for_positioned_tie_in_with_cardinal_only_boundary() -> None:
    tie_in = _line(1, 45.0, 50.0, is_tie_in=True)
    boundary = [
        DeedCall(course=i + 2, direction_text=d, distance_ft=100.0)
        for i, d in enumerate(("Northerly", "Easterly", "Southerly", "Westerly"))
    ]
    calls = [tie_in, *boundary]

    res = verify_closure(calls)
    assert res.misclosure_available is False
    assert res.confidence_score == 0.0
    assert calculate_confidence_score(res, calls) == 0.0


def test_verify_closure_does_not_reanalyze_courses_inside_confidence_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analyze_calls = 0
    real_analyze = pkg_confidence.analyze_courses

    def spy_analyze(calls: list[DeedCall], *args: Any, **kwargs: Any) -> Any:
        nonlocal analyze_calls
        analyze_calls += 1
        return real_analyze(calls, *args, **kwargs)

    monkeypatch.setattr(pkg_confidence, "analyze_courses", spy_analyze)

    calls = [
        _line(1, 0.0, 100.0),
        DeedCall(course=2, direction_text="Easterly", distance_ft=100.0),
    ]
    res = verify_closure(calls)
    assert res.misclosure_available is False
    assert analyze_calls == 0


def test_confidence_score_includes_all_non_closure_checks_and_all_not_applicable_branch() -> None:
    calls = _square(100.0)
    clean = verify_closure(calls)

    # Every non-closure check status (double_entry, area_reasonableness, role blocks)
    # affects checks_score when applicable, independent of warning penalties.
    for check_name, bad_status in (
        ("double_entry", "failed"),
        ("area_reasonableness", "failed"),
        ("non_boundary_tract", "blocked"),
        ("description_roles_inferred", "blocked"),
    ):
        passed_checks = [
            CheckResult(name="interior_angles", status="passed", detail="ok"),
            CheckResult(name=check_name, status="passed", detail="ok"),
        ]
        bad_checks = [
            CheckResult(name="interior_angles", status="passed", detail="ok"),
            CheckResult(name=check_name, status=bad_status, detail="issue"),
        ]
        r_pass = clean.model_copy(update={"warnings": [], "checks": passed_checks})
        r_bad = clean.model_copy(update={"warnings": [], "checks": bad_checks})
        assert calculate_confidence_score(r_bad, calls) < calculate_confidence_score(
            r_pass, calls
        ), check_name

    # All-not_applicable checks (excluding traverse_closure, which has its own weight)
    # yield checks_score == 0.0: 0.30 + 0.00 + 0.25 + 0.15 + 0.10 == 0.80.
    all_na = clean.model_copy(
        update={
            "warnings": [],
            "checks": [
                CheckResult(name="traverse_closure", status="passed", detail="ok"),
                CheckResult(name="interior_angles", status="not_applicable", detail="na"),
                CheckResult(name="curve_consistency", status="not_applicable", detail="na"),
            ],
        }
    )
    assert calculate_confidence_score(all_na, calls) == pytest.approx(0.80)


# ---------------------------------------------------------------------------
# Item 5: Shared CLOSURE_TOLERANCE_FT & directionless spiral distance check
# ---------------------------------------------------------------------------


def test_shared_closure_tolerance_ft_and_defaults() -> None:
    assert hasattr(pkg_topology, "CLOSURE_TOLERANCE_FT")
    assert pkg_topology.CLOSURE_TOLERANCE_FT == 0.01
    assert pkg_closure.CLOSURE_TOLERANCE_FT is pkg_topology.CLOSURE_TOLERANCE_FT
    assert ClosureChecker.CLOSURE_TOLERANCE_FT == pkg_topology.CLOSURE_TOLERANCE_FT

    for fn in (
        check_boundary_intersections,
        check_straight_boundary_intersections,
        check_curved_boundary_intersections,
    ):
        param = inspect.signature(fn).parameters["closure_tolerance_ft"]
        assert param.default == pkg_topology.CLOSURE_TOLERANCE_FT


def test_check_distance_reasonableness_uses_arc_length_for_directionless_spiral() -> None:
    # Directionless spiral (curve_dir=None, curve_type="spiral") with stated arc_length_ft=100.0
    # and tiny placeholder distance_ft=0.1 must use arc_length_ft like calculate_perimeter().
    spiral_ok = DeedCall(
        course=1,
        direction_text="spiral curve",
        distance_ft=0.1,
        curve_type="spiral",
        arc_length_ft=100.0,
    )
    straight = _line(2, 90.0, 100.0)
    assert check_distance_reasonableness([spiral_ok, straight]) == []

    # Conversely, a tiny stated spiral arc_length_ft=0.2 is flagged even if distance_ft=100.0.
    spiral_short = DeedCall(
        course=1,
        direction_text="spiral curve",
        distance_ft=100.0,
        curve_type="spiral",
        arc_length_ft=0.2,
    )
    warnings = check_distance_reasonableness([spiral_short, straight])
    assert any("Course 1: suspiciously short distance (0.20 ft)" in w for w in warnings)


# ---------------------------------------------------------------------------
# Item 6: Monolith facade ClosureChecker sync
# ---------------------------------------------------------------------------


def test_monolith_closure_checker_verify_tract_forwards_double_entry_calls() -> None:
    calls = _mono_square(100.0)
    matching = _mono_square(100.0)
    mismatched = list(_mono_square(100.0))
    mismatched[0] = mismatched[0].model_copy(update={"distance_ft": 105.0})

    ok = ClosureChecker.verify_tract(calls, double_entry_calls=matching)
    assert ok.is_fully_verified() is True
    assert any(c.name == "double_entry" and c.status == "passed" for c in ok.checks)

    bad = ClosureChecker.verify_tract(calls, double_entry_calls=mismatched)
    assert bad.is_fully_verified() is False
    assert any(c.name == "double_entry" and c.status == "failed" for c in bad.checks)


def test_monolith_closure_checker_intersection_methods_forward_closure_tolerance() -> None:
    calls = _mono_square(20.0)
    # Closing endpoint at (0.0, 0.03) lies on edge 1 (0,0)->(0,20) at distance 0.03 ft from origin:
    # closed under tolerance 0.05 (so edges 1 & 4 share closing vertex -> no warning),
    # open under default 0.01 (so edges 1 & 4 are treated as non-adjacent touch -> warning).
    pts = [
        MonoPoint(x=0.0, y=0.0),
        MonoPoint(x=0.0, y=20.0),
        MonoPoint(x=20.0, y=20.0),
        MonoPoint(x=20.0, y=0.0),
        MonoPoint(x=0.0, y=0.03),
    ]
    assert ClosureChecker.check_straight_boundary_intersections(calls, pts) != []
    assert ClosureChecker.check_boundary_intersections(calls, pts) != []
    assert (
        ClosureChecker.check_straight_boundary_intersections(calls, pts, closure_tolerance_ft=0.05)
        == []
    )
    assert ClosureChecker.check_boundary_intersections(calls, pts, closure_tolerance_ft=0.05) == []
    assert (
        inspect.signature(ClosureChecker.check_boundary_intersections)
        .parameters["closure_tolerance_ft"]
        .default
        == pkg_checks.CLOSURE_TOLERANCE_FT
    )
    assert (
        inspect.signature(ClosureChecker.check_straight_boundary_intersections)
        .parameters["closure_tolerance_ft"]
        .default
        == pkg_checks.CLOSURE_TOLERANCE_FT
    )


# ---------------------------------------------------------------------------
# Cycle 2 Track 2 (mp-verify + mp-export)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_area",
    [-10000.0, -0.01, float("nan"), float("inf"), float("-inf"), True, False],
)
def test_verify_stated_area_rejects_invalid_values(bad_area: Any) -> None:
    calls = _square(100.0)
    tract = Tract(label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=calls)

    with pytest.raises(ValueError, match="stated_area_sq_ft must be a finite non-negative number"):
        verify_closure(calls, stated_area_sq_ft=bad_area)
    with pytest.raises(ValueError, match="stated_area_sq_ft must be a finite non-negative number"):
        verify_closure(calls, tracts=[tract], stated_area_sq_ft=bad_area)
    with pytest.raises(ValueError, match="stated_area_sq_ft must be a finite non-negative number"):
        verify_tract(calls, stated_area_sq_ft=bad_area)
    with pytest.raises(ValueError, match="stated_area_sq_ft must be a finite non-negative number"):
        pkg_closure._verify_single(calls, stated_area_sq_ft=bad_area)


def test_verify_stated_area_accepts_zero_and_positive_finite() -> None:
    calls = _square(100.0)

    unset_res = verify_closure(calls, stated_area_sq_ft=0.0)
    assert unset_res.is_fully_verified() is True
    assert any(
        c.name == "area_reasonableness" and c.status == "not_applicable" for c in unset_res.checks
    )

    pos_res = verify_closure(calls, stated_area_sq_ft=10000.0)
    assert pos_res.is_fully_verified() is True
    assert any(c.name == "area_reasonableness" and c.status == "passed" for c in pos_res.checks)

    tract_pos = verify_tract(calls, stated_area_sq_ft=10000.0)
    assert tract_pos.is_fully_verified() is True


def test_verify_tract_without_tract_subtracts_mixed_exception_calls() -> None:
    mixed_calls = [
        *_square(100.0, course_start=1),
        *_square(10.0, course_start=5, is_exception=True),
    ]
    res = verify_tract(mixed_calls)
    assert res.area_available is True
    assert res.area_sq_ft == pytest.approx(9900.0)
    assert res.perimeter_ft == pytest.approx(400.0)
    assert any("calculating exception area to subtract" in w for w in res.warnings)
    assert res.is_fully_verified() is False

    # Positive control: all non-tie-in calls marked is_exception still close as one loop
    # for review, while remaining blocked from full verification.
    exc_only = [
        _line(1, 45.0, 20.0, is_tie_in=True),
        *_square(10.0, course_start=2, is_exception=True),
    ]
    exc_res = verify_tract(exc_only)
    assert exc_res.closure_passed is True
    assert exc_res.area_sq_ft == pytest.approx(100.0)
    assert exc_res.is_fully_verified() is False
    assert any(c.name == "non_boundary_tract" and c.status == "blocked" for c in exc_res.checks)


def test_export_verified_csv_rejects_same_label_tract_conflicts_with_legal_desc(
    tmp_path: Path,
) -> None:
    calls = _square(100.0)
    skip = SkippedCourse(
        course=5,
        source_course=5,
        source_excerpt="thence bad",
        error_type="ValueError",
        error="malformed",
        tract_label="Tract 1",
    )
    clean_tract = Tract(
        label="Tract 1",
        tract_type=TractType.MAIN,
        role_basis="heading",
        calls=calls,
    )
    clean_res = verify_tract(calls, tract=clean_tract)

    conflict_cases: list[tuple[str, Tract, Tract, ClosureResult]] = [
        (
            "dropped_skipped_courses",
            clean_tract.model_copy(update={"skipped_courses": [skip]}),
            clean_tract,
            clean_res,
        ),
        (
            "overridden_role_basis",
            clean_tract.model_copy(update={"role_basis": "inferred"}),
            clean_tract,
            clean_res,
        ),
        (
            "changed_tract_type",
            clean_tract.model_copy(update={"tract_type": TractType.EASEMENT}),
            clean_tract,
            clean_res,
        ),
        (
            "changed_calls",
            clean_tract.model_copy(update={"calls": _square(50.0)}),
            clean_tract,
            clean_res,
        ),
        (
            "dropped_stated_area",
            clean_tract.model_copy(update={"stated_area_sq_ft": 500.0}),
            clean_tract,
            clean_res,
        ),
    ]

    for case_name, orig_tract, supplied_tract, supplied_res in conflict_cases:
        case_dir = tmp_path / case_name
        case_dir.mkdir()
        ld = LegalDescription(calls=orig_tract.calls, tracts=[orig_tract])
        with pytest.raises(
            ValueError,
            match=r"supplied tract 'Tract 1' conflicts with legal_desc\.tracts",
        ):
            export_verified_csv(
                [],
                supplied_res,
                str(case_dir / "deed.csv"),
                legal_desc=ld,
                tract_results=[(supplied_tract, supplied_res)],
            )
        assert list(case_dir.iterdir()) == [], case_name

    # Duplicate same-label tracts in legal_desc.tracts when tract_results supplies only one.
    dup_dir = tmp_path / "duplicate_label_partial"
    dup_dir.mkdir()
    dup_ld = LegalDescription(
        calls=calls,
        tracts=[
            clean_tract,
            clean_tract.model_copy(update={"calls": _square(50.0)}),
        ],
    )
    with pytest.raises(
        ValueError,
        match=r"supplied tract 'Tract 1' conflicts with legal_desc\.tracts",
    ):
        export_verified_csv(
            [],
            clean_res,
            str(dup_dir / "deed.csv"),
            legal_desc=dup_ld,
            tract_results=[(clean_tract, clean_res)],
        )
    assert list(dup_dir.iterdir()) == []

    # Positive control: identical same-label tract (even with closure_result attached) exports.
    ok_dir = tmp_path / "ok"
    ok_dir.mkdir()
    supplied_with_result = clean_tract.model_copy(update={"closure_result": clean_res})
    written = export_verified_csv(
        calls,
        clean_res,
        str(ok_dir / "deed.csv"),
        legal_desc=LegalDescription(calls=calls, tracts=[clean_tract]),
        tract_results=[(supplied_with_result, clean_res)],
    )
    assert written == [ok_dir / "deed_verified_tract1.csv"]


def test_single_tract_export_reconciles_boundary_tract_stated_area(tmp_path: Path) -> None:
    calls = _square(100.0)  # 10,000 sq ft
    tract_500 = Tract(
        label="Tract 1",
        tract_type=TractType.MAIN,
        role_basis="heading",
        calls=calls,
        stated_area_sq_ft=500.0,
    )
    no_area_res = verify_closure(calls)
    assert no_area_res.is_fully_verified() is True

    # LegalDescription.stated_area_sq_ft is None, but boundary tract has 500.0 sq ft -> rejected.
    bad_dir = tmp_path / "tract_area_mismatch"
    bad_dir.mkdir()
    ld_tract_only = LegalDescription(calls=calls, tracts=[tract_500], stated_area_sq_ft=None)
    with pytest.raises(ValueError, match="selected calls failed fresh verification"):
        export_verified_csv(calls, no_area_res, str(bad_dir / "deed.csv"), legal_desc=ld_tract_only)
    assert list(bad_dir.iterdir()) == []

    # LegalDescription.stated_area_sq_ft conflicts with boundary tract stated_area_sq_ft -> rejected.
    conflict_dir = tmp_path / "area_conflict"
    conflict_dir.mkdir()
    area_ok_res = verify_closure(calls, stated_area_sq_ft=10000.0)
    ld_conflict = LegalDescription(calls=calls, tracts=[tract_500], stated_area_sq_ft=10000.0)
    with pytest.raises(
        ValueError,
        match=r"legal_desc\.stated_area_sq_ft conflicts with boundary tract stated_area_sq_ft",
    ):
        export_verified_csv(
            calls, area_ok_res, str(conflict_dir / "deed.csv"), legal_desc=ld_conflict
        )
    assert list(conflict_dir.iterdir()) == []

    # Positive controls: consistent stated area on boundary tract (with or without legal_desc copy).
    tract_10000 = tract_500.model_copy(update={"stated_area_sq_ft": 10000.0})
    for name, ld_ok in (
        ("tract_only_ok", LegalDescription(calls=calls, tracts=[tract_10000])),
        (
            "both_matching_ok",
            LegalDescription(calls=calls, tracts=[tract_10000], stated_area_sq_ft=10000.0),
        ),
    ):
        ok_dir = tmp_path / name
        ok_dir.mkdir()
        written = export_verified_csv(
            calls, area_ok_res, str(ok_dir / "deed.csv"), legal_desc=ld_ok
        )
        assert written == [ok_dir / "deed_verified.csv"]


def test_legal_description_to_csv_populated_calls_preserves_exact_tract_marks_and_exception_flags(
    tmp_path: Path,
) -> None:
    main_calls = _square(100.0, course_start=1)
    raw_exc_calls = _square(20.0, course_start=5)
    easement_calls = _square(30.0, course_start=9)

    main_tract = Tract(
        label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=main_calls
    )
    exc_tract = Tract(
        label="Exception 1",
        tract_type=TractType.EXCEPTION,
        role_basis="heading",
        calls=raw_exc_calls,
    )
    easement_tract = Tract(
        label="Easement 1",
        tract_type=TractType.EASEMENT,
        role_basis="heading",
        calls=easement_calls,
    )

    # 1. Populated calls + exception-only tract -> is_exception=True + EXCEPTION_TRACT_NOTE.
    out_exc = tmp_path / "pop_exc.csv"
    legal_description_to_csv(
        LegalDescription(calls=raw_exc_calls, tracts=[exc_tract]), str(out_exc)
    )
    loaded_exc = csv_to_calls(str(out_exc))
    assert len(loaded_exc) == 4
    assert all(c.is_exception is True for c in loaded_exc)
    assert all(EXCEPTION_TRACT_NOTE in split_notes(c.notes) for c in loaded_exc)
    assert all(EASEMENT_TRACT_NOTE not in split_notes(c.notes) for c in loaded_exc)
    res_exc = verify_closure(loaded_exc)
    assert res_exc.is_fully_verified() is False
    assert any(c.name == "non_boundary_tract" and c.status == "blocked" for c in res_exc.checks)

    # 2. Populated calls + mixed MAIN + EXCEPTION -> only exception calls marked & flagged.
    out_mixed_exc = tmp_path / "mixed_main_exc.csv"
    legal_description_to_csv(
        LegalDescription(calls=[*main_calls, *raw_exc_calls], tracts=[main_tract, exc_tract]),
        str(out_mixed_exc),
    )
    loaded_mixed_exc = csv_to_calls(str(out_mixed_exc))
    assert len(loaded_mixed_exc) == 8
    assert all(c.is_exception is False and c.notes is None for c in loaded_mixed_exc[:4])
    assert all(
        c.is_exception is True and EXCEPTION_TRACT_NOTE in split_notes(c.notes)
        for c in loaded_mixed_exc[4:]
    )
    res_mixed_exc = verify_closure(loaded_mixed_exc)
    assert res_mixed_exc.is_fully_verified() is False
    assert res_mixed_exc.area_sq_ft == pytest.approx(10000.0 - 400.0)
    assert any(
        c.name == "non_boundary_tract" and c.status == "blocked" for c in res_mixed_exc.checks
    )

    # 3. Populated calls = easement calls + mixed MAIN + EASEMENT -> marked EASEMENT_TRACT_NOTE.
    out_easement_only_calls = tmp_path / "mixed_main_easement_calls.csv"
    legal_description_to_csv(
        LegalDescription(calls=easement_calls, tracts=[main_tract, easement_tract]),
        str(out_easement_only_calls),
    )
    loaded_easement = csv_to_calls(str(out_easement_only_calls))
    assert len(loaded_easement) == 4
    assert all(c.is_exception is False for c in loaded_easement)
    assert all(EASEMENT_TRACT_NOTE in split_notes(c.notes) for c in loaded_easement)
    res_easement = verify_closure(loaded_easement)
    assert res_easement.is_fully_verified() is False
    assert any(
        c.name == "non_boundary_tract" and c.status == "blocked" for c in res_easement.checks
    )

    # 4. Populated calls + EASEMENT + EXCEPTION -> each tract gets ONLY its own note (no double stamp).
    out_both_non_boundary = tmp_path / "easement_and_exc.csv"
    legal_description_to_csv(
        LegalDescription(
            calls=[*easement_calls, *raw_exc_calls], tracts=[easement_tract, exc_tract]
        ),
        str(out_both_non_boundary),
    )
    loaded_both = csv_to_calls(str(out_both_non_boundary))
    assert len(loaded_both) == 8
    for c in loaded_both[:4]:
        notes = split_notes(c.notes)
        assert c.is_exception is False
        assert EASEMENT_TRACT_NOTE in notes
        assert EXCEPTION_TRACT_NOTE not in notes
    for c in loaded_both[4:]:
        notes = split_notes(c.notes)
        assert c.is_exception is True
        assert EXCEPTION_TRACT_NOTE in notes
        assert EASEMENT_TRACT_NOTE not in notes
    res_both = verify_closure(loaded_both)
    assert res_both.is_fully_verified() is False
    assert any(c.name == "non_boundary_tract" and c.status == "blocked" for c in res_both.checks)

    # 5. Unmatched populated calls when only non-boundary tracts exist (deduplicated fallback).
    unmatched_calls = _square(15.0, course_start=13)
    empty_exc_tracts = [
        Tract(
            label=f"Exception {i}", tract_type=TractType.EXCEPTION, role_basis="heading", calls=[]
        )
        for i in range(1, 5)
    ]
    out_fallback = tmp_path / "fallback_exc.csv"
    legal_description_to_csv(
        LegalDescription(calls=unmatched_calls, tracts=empty_exc_tracts), str(out_fallback)
    )
    loaded_fallback = csv_to_calls(str(out_fallback))
    assert all(
        c.is_exception is True and split_notes(c.notes) == [EXCEPTION_TRACT_NOTE]
        for c in loaded_fallback
    )

    # 6. Positive control: populated calls = main_calls + headed MAIN + EASEMENT stays unmarked.
    out_main_ok = tmp_path / "main_ok.csv"
    legal_description_to_csv(
        LegalDescription(calls=main_calls, tracts=[main_tract, easement_tract]),
        str(out_main_ok),
    )
    loaded_main_ok = csv_to_calls(str(out_main_ok))
    assert all(c.is_exception is False and c.notes is None for c in loaded_main_ok)
    assert verify_closure(loaded_main_ok).is_fully_verified() is True

    # Original call lists remain completely unmutated.
    assert all(c.is_exception is False and c.notes is None for c in main_calls)
    assert all(c.is_exception is False and c.notes is None for c in raw_exc_calls)
    assert all(c.is_exception is False and c.notes is None for c in easement_calls)


# ---------------------------------------------------------------------------
# Cycle 3 Track 2 (C4, C5, C6, C7, M1, M2, M3, M12)
# ---------------------------------------------------------------------------


def test_export_verified_csv_rejects_unlisted_tract_label_and_allows_valid_subset(
    tmp_path: Path,
) -> None:
    calls_1 = _square(100.0)
    calls_2 = _square(50.0)
    skip = SkippedCourse(
        course=5,
        source_course=5,
        source_excerpt="thence bad",
        error_type="ValueError",
        error="malformed",
        tract_label="Tract 1",
    )
    blocked_orig = Tract(
        label="Tract 1",
        tract_type=TractType.MAIN,
        role_basis="heading",
        calls=calls_1,
        skipped_courses=[skip],
    )
    easement_orig = Tract(
        label="Tract 1",
        tract_type=TractType.EASEMENT,
        role_basis="heading",
        calls=calls_1,
    )
    bad_area_orig = Tract(
        label="Tract 1",
        tract_type=TractType.MAIN,
        role_basis="heading",
        calls=calls_1,
        stated_area_sq_ft=500.0,
    )
    renamed_tract = Tract(
        label="Renamed Tract",
        tract_type=TractType.MAIN,
        role_basis="heading",
        calls=calls_1,
    )
    clean_res = verify_tract(calls_1, tract=renamed_tract)
    assert clean_res.is_fully_verified() is True

    for case_name, orig in (
        ("renamed_over_skipped", blocked_orig),
        ("renamed_over_easement", easement_orig),
        ("renamed_over_bad_area", bad_area_orig),
    ):
        case_dir = tmp_path / case_name
        case_dir.mkdir()
        ld = LegalDescription(calls=calls_1, tracts=[orig])
        with pytest.raises(
            ValueError,
            match=r"supplied tract 'Renamed Tract' is not in legal_desc\.tracts",
        ):
            export_verified_csv(
                [],
                clean_res,
                str(case_dir / "deed.csv"),
                legal_desc=ld,
                tract_results=[(renamed_tract, clean_res)],
            )
        assert list(case_dir.iterdir()) == [], case_name

    # Positive control: supplying a valid subset of legal_desc.tracts still exports.
    t1 = Tract(label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=calls_1)
    t2 = Tract(label="Tract 2", tract_type=TractType.ADDITION, role_basis="heading", calls=calls_2)
    r1 = verify_tract(calls_1, tract=t1)
    subset_dir = tmp_path / "valid_subset"
    subset_dir.mkdir()
    written = export_verified_csv(
        [],
        r1,
        str(subset_dir / "deed.csv"),
        legal_desc=LegalDescription(calls=[*calls_1, *calls_2], tracts=[t1, t2]),
        tract_results=[(t1, r1)],
    )
    assert written == [subset_dir / "deed_verified_tract1.csv"]


def test_multi_tract_export_reconciles_legal_desc_stated_area(tmp_path: Path) -> None:
    calls = _square(100.0)  # 10,000 sq ft
    main_no_area = Tract(
        label="Tract 1",
        tract_type=TractType.MAIN,
        role_basis="heading",
        calls=calls,
        stated_area_sq_ft=None,
    )
    easement = Tract(
        label="Easement 1",
        tract_type=TractType.EASEMENT,
        role_basis="heading",
        calls=_square(20.0),
    )
    no_area_res = verify_tract(calls, tract=main_no_area)
    assert no_area_res.is_fully_verified() is True
    easement_res = verify_tract(easement.calls, tract=easement)

    # 1. tract.stated_area_sq_ft=None while legal_desc.stated_area_sq_ft=500.0 -> must fail!
    for case_name, tracts, pairs in (
        ("single_boundary", [main_no_area], [(main_no_area, no_area_res)]),
        (
            "single_boundary_plus_easement",
            [main_no_area, easement],
            [(main_no_area, no_area_res), (easement, easement_res)],
        ),
    ):
        bad_dir = tmp_path / case_name
        bad_dir.mkdir()
        ld = LegalDescription(calls=calls, tracts=tracts, stated_area_sq_ft=500.0)
        with pytest.raises(ValueError, match="selected calls failed fresh verification"):
            export_verified_csv(
                [],
                no_area_res,
                str(bad_dir / "deed.csv"),
                legal_desc=ld,
                tract_results=pairs,
            )
        assert list(bad_dir.iterdir()) == [], case_name

    # 2. tract.stated_area_sq_ft=None, legal_desc.stated_area_sq_ft=10000.0:
    #    - stale res verified without stated_area_sq_ft must fail result-matching check.
    stale_dir = tmp_path / "stale_no_area_res"
    stale_dir.mkdir()
    ld_10k = LegalDescription(calls=calls, tracts=[main_no_area], stated_area_sq_ft=10000.0)
    with pytest.raises(ValueError, match="closure result does not match selected calls"):
        export_verified_csv(
            [],
            no_area_res,
            str(stale_dir / "deed.csv"),
            legal_desc=ld_10k,
            tract_results=[(main_no_area, no_area_res)],
        )
    assert list(stale_dir.iterdir()) == []

    #    - matching res verified with stated_area_sq_ft=10000.0 succeeds.
    ok_dir = tmp_path / "matching_area_res"
    ok_dir.mkdir()
    res_10k = verify_tract(calls, stated_area_sq_ft=10000.0, tract=main_no_area)
    written = export_verified_csv(
        [],
        res_10k,
        str(ok_dir / "deed.csv"),
        legal_desc=ld_10k,
        tract_results=[(main_no_area, res_10k)],
    )
    assert written == [ok_dir / "deed_verified_tract1.csv"]

    # 3. Conflicting stated_area_sq_ft between legal_desc and single boundary tract -> ValueError.
    conflict_dir = tmp_path / "conflict"
    conflict_dir.mkdir()
    main_500 = main_no_area.model_copy(update={"stated_area_sq_ft": 500.0})
    ld_conflict = LegalDescription(calls=calls, tracts=[main_500], stated_area_sq_ft=10000.0)
    with pytest.raises(
        ValueError,
        match=r"legal_desc\.stated_area_sq_ft conflicts with boundary tract stated_area_sq_ft",
    ):
        export_verified_csv(
            [],
            res_10k,
            str(conflict_dir / "deed.csv"),
            legal_desc=ld_conflict,
            tract_results=[(main_500, res_10k)],
        )
    assert list(conflict_dir.iterdir()) == []

    # 4. Two boundary tracts with combined legal_desc.stated_area_sq_ft -> not forced onto one.
    two_dir = tmp_path / "two_boundary"
    two_dir.mkdir()
    add_no_area = Tract(
        label="Addition 1",
        tract_type=TractType.ADDITION,
        role_basis="heading",
        calls=_square(50.0),
        stated_area_sq_ft=None,
    )
    add_res = verify_tract(add_no_area.calls, tract=add_no_area)
    ld_two = LegalDescription(
        calls=[*calls, *add_no_area.calls],
        tracts=[main_no_area, add_no_area],
        stated_area_sq_ft=12500.0,
    )
    written_two = export_verified_csv(
        [],
        no_area_res,
        str(two_dir / "deed.csv"),
        legal_desc=ld_two,
        tract_results=[(main_no_area, no_area_res), (add_no_area, add_res)],
    )
    assert [p.name for p in written_two] == [
        "deed_verified_tract1.csv",
        "deed_verified_tract2.csv",
    ]


def test_export_verified_csv_uses_shared_stated_area_tolerance(tmp_path: Path) -> None:
    calls = _square(100.0)
    tract = Tract(
        label="Tract 1",
        tract_type=TractType.MAIN,
        role_basis="heading",
        calls=calls,
        stated_area_sq_ft=10000.0,
    )
    # 5e-7 relative diff: within shared STATED_AREA_REL_TOL (1e-6), outside old 1e-9.
    ld_within = LegalDescription(calls=calls, tracts=[tract], stated_area_sq_ft=10000.005)
    single_res = verify_closure(calls, stated_area_sq_ft=10000.005)
    single_dir = tmp_path / "single_within"
    single_dir.mkdir()
    assert export_verified_csv(
        calls, single_res, str(single_dir / "deed.csv"), legal_desc=ld_within
    ) == [single_dir / "deed_verified.csv"]

    tract_res = verify_tract(calls, stated_area_sq_ft=10000.0, tract=tract)
    multi_dir = tmp_path / "multi_within"
    multi_dir.mkdir()
    assert export_verified_csv(
        [],
        tract_res,
        str(multi_dir / "deed.csv"),
        legal_desc=ld_within,
        tract_results=[(tract, tract_res)],
    ) == [multi_dir / "deed_verified_tract1.csv"]

    # 5e-6 relative diff: outside shared STATED_AREA_REL_TOL (1e-6) -> rejected in both modes.
    ld_outside = LegalDescription(calls=calls, tracts=[tract], stated_area_sq_ft=10000.05)
    for mode, out_sub in (("single", "single_outside"), ("multi", "multi_outside")):
        out_dir = tmp_path / out_sub
        out_dir.mkdir()
        with pytest.raises(
            ValueError,
            match=r"legal_desc\.stated_area_sq_ft conflicts with boundary tract stated_area_sq_ft",
        ):
            if mode == "single":
                export_verified_csv(
                    calls, single_res, str(out_dir / "deed.csv"), legal_desc=ld_outside
                )
            else:
                export_verified_csv(
                    [],
                    tract_res,
                    str(out_dir / "deed.csv"),
                    legal_desc=ld_outside,
                    tract_results=[(tract, tract_res)],
                )
        assert list(out_dir.iterdir()) == [], mode


def test_legal_description_to_csv_fails_closed_on_ambiguous_equal_calls_and_covers_all_passes(
    tmp_path: Path,
) -> None:
    # 1. C7: Identical MAIN and EASEMENT calls, partial subset selecting easement calls.
    #    - Direct package call with distinct copied DeedCall instances (no shared id)
    main_eq = _square(100.0, course_start=1)
    ease_eq = _square(100.0, course_start=1)
    flat_eq_copy = _square(100.0, course_start=1)
    main_t = Tract(label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=main_eq)
    ease_t = Tract(
        label="Easement 1", tract_type=TractType.EASEMENT, role_basis="heading", calls=ease_eq
    )
    out_pkg_partial = tmp_path / "pkg_eq_partial.csv"
    legal_description_to_csv(
        LegalDescription(calls=flat_eq_copy, tracts=[main_t, ease_t]), str(out_pkg_partial)
    )
    loaded_pkg_partial = csv_to_calls(str(out_pkg_partial))
    assert all(EASEMENT_TRACT_NOTE in split_notes(c.notes) for c in loaded_pkg_partial)
    res_pkg_partial = verify_closure(loaded_pkg_partial)
    assert res_pkg_partial.is_fully_verified() is False
    assert any(
        c.name == "non_boundary_tract" and c.status == "blocked" for c in res_pkg_partial.checks
    )

    #    - Monolith CSVBuilder.legal_description_to_csv (package_bridge reconstructs DeedCalls)
    mono_main_calls = _mono_square(100.0)
    mono_ease_calls = _mono_square(100.0)
    mono_ld_partial = MonoLegalDescription(
        calls=mono_ease_calls,
        tracts=[
            MonoTract(
                label="Tract 1",
                tract_type=MonoTractType.MAIN,
                role_basis="heading",
                calls=mono_main_calls,
            ),
            MonoTract(
                label="Easement 1",
                tract_type=MonoTractType.EASEMENT,
                role_basis="heading",
                calls=mono_ease_calls,
            ),
        ],
    )
    out_mono_partial = tmp_path / "mono_eq_partial.csv"
    CSVBuilder.legal_description_to_csv(mono_ld_partial, str(out_mono_partial))
    loaded_mono_partial = csv_to_calls(str(out_mono_partial))
    assert all(EASEMENT_TRACT_NOTE in split_notes(c.notes) for c in loaded_mono_partial)
    res_mono_partial = verify_closure(loaded_mono_partial)
    assert res_mono_partial.is_fully_verified() is False
    assert any(
        c.name == "non_boundary_tract" and c.status == "blocked" for c in res_mono_partial.checks
    )

    # 2. C7 positive control: Full 8-call deed with identical MAIN + EASEMENT calls preserves
    #    original tract order (both direct copied calls and monolith bridge).
    out_pkg_full = tmp_path / "pkg_eq_full.csv"
    legal_description_to_csv(
        LegalDescription(calls=[*_square(100.0), *_square(100.0)], tracts=[main_t, ease_t]),
        str(out_pkg_full),
    )
    loaded_pkg_full = csv_to_calls(str(out_pkg_full))
    assert len(loaded_pkg_full) == 8
    assert all(c.notes is None for c in loaded_pkg_full[:4])
    assert all(EASEMENT_TRACT_NOTE in split_notes(c.notes) for c in loaded_pkg_full[4:])

    out_mono_full = tmp_path / "mono_eq_full.csv"
    CSVBuilder.legal_description_to_csv(
        MonoLegalDescription(
            calls=[*mono_main_calls, *mono_ease_calls],
            tracts=mono_ld_partial.tracts,
        ),
        str(out_mono_full),
    )
    loaded_mono_full = csv_to_calls(str(out_mono_full))
    assert len(loaded_mono_full) == 8
    assert all(c.notes is None for c in loaded_mono_full[:4])
    assert all(EASEMENT_TRACT_NOTE in split_notes(c.notes) for c in loaded_mono_full[4:])

    # Reversed original tract order [EASEMENT, MAIN] preserves tract order on full deed too.
    out_rev_full = tmp_path / "rev_eq_full.csv"
    legal_description_to_csv(
        LegalDescription(calls=[*_square(100.0), *_square(100.0)], tracts=[ease_t, main_t]),
        str(out_rev_full),
    )
    loaded_rev_full = csv_to_calls(str(out_rev_full))
    assert all(EASEMENT_TRACT_NOTE in split_notes(c.notes) for c in loaded_rev_full[:4])
    assert all(c.notes is None for c in loaded_rev_full[4:])

    # 3. M12 pass 3: JSON-roundtripped pre-marked / is_exception=True flat calls vs raw tracts.
    raw_main = _square(100.0, course_start=1)
    raw_exc = _square(20.0, course_start=5)
    premarked_flat = [
        *raw_main,
        *[
            c.model_copy(update={"is_exception": True, "notes": EXCEPTION_TRACT_NOTE})
            for c in raw_exc
        ],
    ]
    json_flat = [
        DeedCall.model_validate(item)
        for item in json.loads(json.dumps([c.model_dump(mode="json") for c in premarked_flat]))
    ]
    out_pass3 = tmp_path / "pass3_json.csv"
    legal_description_to_csv(
        LegalDescription(
            calls=json_flat,
            tracts=[
                Tract(
                    label="Tract 1",
                    tract_type=TractType.MAIN,
                    role_basis="heading",
                    calls=raw_main,
                ),
                Tract(
                    label="Exception 1",
                    tract_type=TractType.EXCEPTION,
                    role_basis="heading",
                    calls=raw_exc,
                ),
            ],
        ),
        str(out_pass3),
    )
    loaded_pass3 = csv_to_calls(str(out_pass3))
    assert all(c.is_exception is False and c.notes is None for c in loaded_pass3[:4])
    assert all(
        c.is_exception is True and split_notes(c.notes) == [EXCEPTION_TRACT_NOTE]
        for c in loaded_pass3[4:]
    )

    # 4. M12 pass 4: Course-renumbered flat calls (1..8) vs per-tract 1-based calls (1..4, 1..4).
    exc_one_based = _square(20.0, course_start=1)
    renumbered_flat = [*_square(100.0, course_start=1), *_square(20.0, course_start=5)]
    out_pass4 = tmp_path / "pass4_renumbered.csv"
    legal_description_to_csv(
        LegalDescription(
            calls=renumbered_flat,
            tracts=[
                Tract(
                    label="Tract 1",
                    tract_type=TractType.MAIN,
                    role_basis="heading",
                    calls=_square(100.0, course_start=1),
                ),
                Tract(
                    label="Exception 1",
                    tract_type=TractType.EXCEPTION,
                    role_basis="heading",
                    calls=exc_one_based,
                ),
            ],
        ),
        str(out_pass4),
    )
    loaded_pass4 = csv_to_calls(str(out_pass4))
    assert [c.course for c in loaded_pass4] == list(range(1, 9))
    assert all(c.is_exception is False and c.notes is None for c in loaded_pass4[:4])
    assert all(
        c.is_exception is True and EXCEPTION_TRACT_NOTE in split_notes(c.notes)
        for c in loaded_pass4[4:]
    )


@pytest.mark.parametrize(
    "bad_tol",
    [-0.01, -1.0, float("nan"), float("inf"), float("-inf"), True, False, "0.01"],
)
def test_verify_closure_tolerance_rejects_invalid_values(bad_tol: Any) -> None:
    calls = _square(100.0)
    tract = Tract(label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=calls)

    with pytest.raises(
        ValueError, match="closure_tolerance_ft must be a finite non-negative number"
    ):
        verify_closure(calls, closure_tolerance_ft=bad_tol)
    with pytest.raises(
        ValueError, match="closure_tolerance_ft must be a finite non-negative number"
    ):
        verify_closure(calls, tracts=[tract], closure_tolerance_ft=bad_tol)
    with pytest.raises(
        ValueError, match="closure_tolerance_ft must be a finite non-negative number"
    ):
        verify_closure(calls, tracts=[], closure_tolerance_ft=bad_tol)
    with pytest.raises(
        ValueError, match="closure_tolerance_ft must be a finite non-negative number"
    ):
        verify_tract(calls, closure_tolerance_ft=bad_tol)
    with pytest.raises(
        ValueError, match="closure_tolerance_ft must be a finite non-negative number"
    ):
        pkg_closure._verify_single(calls, closure_tolerance_ft=bad_tol)


def test_verify_closure_tolerance_accepts_none_and_non_negative_finite() -> None:
    calls = _square(100.0)
    assert verify_closure(calls, closure_tolerance_ft=None).is_fully_verified() is True
    assert verify_closure(calls, closure_tolerance_ft=0.01).is_fully_verified() is True
    strict_res = verify_closure(calls, closure_tolerance_ft=0.0)
    assert strict_res.closure_passed is False
    assert strict_res.is_fully_verified() is False
    assert verify_tract(calls, closure_tolerance_ft=1).closure_passed is True
    assert verify_closure(calls, tracts=[], closure_tolerance_ft=0.05) == []


def test_confidence_score_zero_for_non_computable_main_traverse_with_positioned_exceptions() -> (
    None
):
    cardinal_main = [
        DeedCall(course=i + 1, direction_text=d, distance_ft=100.0)
        for i, d in enumerate(("Northerly", "Easterly", "Southerly", "Westerly"))
    ]
    positioned_exc = _square(20.0, course_start=5, is_exception=True)
    calls = [*cardinal_main, *positioned_exc]

    res = verify_closure(calls)
    assert res.misclosure_available is False
    assert any("No computable traverse" in w for w in res.warnings)
    assert res.confidence_score == 0.0
    assert calculate_confidence_score(res, calls) == 0.0

    # M12: Direct calculate_confidence_score with chord_flags & indefinite_flags,
    # WITHOUT positioned_flags, returns 0.0 (both with and without positioned exceptions).
    assert (
        calculate_confidence_score(
            res,
            calls,
            chord_flags=[False] * len(calls),
            indefinite_flags=[False] * len(calls),
        )
        == 0.0
    )

    tie_and_cardinal = [_line(1, 45.0, 25.0, is_tie_in=True), *cardinal_main]
    res_no_exc = verify_closure(tie_and_cardinal)
    assert res_no_exc.misclosure_available is False
    assert (
        calculate_confidence_score(
            res_no_exc,
            tie_and_cardinal,
            chord_flags=[False] * len(tie_and_cardinal),
            indefinite_flags=[False] * len(tie_and_cardinal),
        )
        == 0.0
    )

    # Positive control: standalone exception-only traverse with at least one positioned call
    # falls back to evaluating the exception calls (matching _verify_tract).
    partial_exc = [
        _line(1, 0.0, 20.0, is_exception=True),
        DeedCall(course=2, direction_text="Easterly", distance_ft=20.0, is_exception=True),
    ]
    partial_exc_res = verify_tract(partial_exc)
    assert partial_exc_res.misclosure_available is False
    assert partial_exc_res.confidence_score is not None and partial_exc_res.confidence_score > 0.0
    assert calculate_confidence_score(
        partial_exc_res,
        partial_exc,
        chord_flags=[False, False],
        indefinite_flags=[False, False],
    ) == pytest.approx(partial_exc_res.confidence_score)


# ---------------------------------------------------------------------------
# Cycle 3 Follow-up Track 2 (#1 stated_area alignment, #2 shared leg export, A1)
# ---------------------------------------------------------------------------


def test_multi_tract_verify_and_export_align_stated_area_with_easement_and_exception(
    tmp_path: Path,
) -> None:
    main_calls = _square(100.0, course_start=1)  # 10,000 sq ft
    easement_calls = _square(20.0, course_start=1)  # 400 sq ft
    exception_calls = _square(40.0, course_start=1, is_exception=True)  # 1,600 sq ft

    main_no_area = Tract(
        label="Tract 1",
        tract_type=TractType.MAIN,
        role_basis="heading",
        calls=main_calls,
        stated_area_sq_ft=None,
    )
    easement = Tract(
        label="Easement 1",
        tract_type=TractType.EASEMENT,
        role_basis="heading",
        calls=easement_calls,
    )
    exception = Tract(
        label="Exception 1",
        tract_type=TractType.EXCEPTION,
        role_basis="heading",
        calls=exception_calls,
    )

    # (a) MAIN (stated_area_sq_ft=None) + EASEMENT + matching deed stated_area_sq_ft=10000.0:
    #     verify_closure checks area_reasonableness=passed and export_verified_csv succeeds.
    legal_ok = LegalDescription(
        calls=[*main_calls, *easement_calls],
        tracts=[main_no_area, easement],
        stated_area_sq_ft=10000.0,
    )
    res_ok = verify_closure(
        legal_ok.all_calls,
        stated_area_sq_ft=legal_ok.stated_area_sq_ft or 0.0,
        tracts=legal_ok.tracts,
    )
    assert len(res_ok) == 2
    assert res_ok[0].is_fully_verified() is True
    assert any(c.name == "area_reasonableness" and c.status == "passed" for c in res_ok[0].checks)
    assert res_ok[1].is_fully_verified() is False
    assert any(
        c.name == "area_reasonableness" and c.status == "not_applicable" for c in res_ok[1].checks
    )

    ok_dir = tmp_path / "main_easement_ok"
    ok_dir.mkdir()
    written_ok = export_verified_csv(
        legal_ok.all_calls,
        res_ok[0],
        str(ok_dir / "deed.csv"),
        legal_desc=legal_ok,
        tract_results=list(zip(legal_ok.tracts, res_ok, strict=True)),
    )
    assert written_ok == [ok_dir / "deed_verified_tract1.csv"]

    # (b) Same MAIN + EASEMENT with mismatched deed stated_area_sq_ft=500.0:
    #     BOTH verify_closure and export_verified_csv fail area_reasonableness.
    legal_bad = LegalDescription(
        calls=[*main_calls, *easement_calls],
        tracts=[main_no_area, easement],
        stated_area_sq_ft=500.0,
    )
    res_bad = verify_closure(
        legal_bad.all_calls,
        stated_area_sq_ft=legal_bad.stated_area_sq_ft or 0.0,
        tracts=legal_bad.tracts,
    )
    assert res_bad[0].is_fully_verified() is False
    assert any(c.name == "area_reasonableness" and c.status == "failed" for c in res_bad[0].checks)
    assert any("differs from stated" in w for w in res_bad[0].warnings)

    bad_dir = tmp_path / "main_easement_bad"
    bad_dir.mkdir()
    with pytest.raises(ValueError, match="Cannot export verified CSV"):
        export_verified_csv(
            legal_bad.all_calls,
            res_bad[0],
            str(bad_dir / "deed.csv"),
            legal_desc=legal_bad,
            tract_results=list(zip(legal_bad.tracts, res_bad, strict=True)),
        )
    assert list(bad_dir.iterdir()) == []

    # Conflicting deed stated_area_sq_ft vs sole boundary tract's own stated_area_sq_ft raises.
    main_10k = main_no_area.model_copy(update={"stated_area_sq_ft": 10000.0})
    with pytest.raises(
        ValueError,
        match=r"stated_area_sq_ft conflicts with boundary tract stated_area_sq_ft",
    ):
        verify_closure(
            legal_bad.all_calls,
            stated_area_sq_ft=500.0,
            tracts=[main_10k, easement],
        )
    # Within shared tolerance (5e-7 < 1e-6) does not conflict.
    res_within = verify_closure(
        legal_ok.all_calls,
        stated_area_sq_ft=10000.005,
        tracts=[main_10k, easement],
    )
    assert res_within[0].is_fully_verified() is True

    # (c) MAIN (10,000 sq ft, tract.stated_area_sq_ft=None) + EXCEPTION (1,600 sq ft)
    #     + net deed stated_area_sq_ft=8400.0:
    #     neither verify_closure nor export_verified_csv compares gross 10,000 against net 8,400.
    legal_exc = LegalDescription(
        calls=[*main_calls, *exception_calls],
        tracts=[main_no_area, exception],
        stated_area_sq_ft=8400.0,
    )
    res_exc = verify_closure(
        legal_exc.all_calls,
        stated_area_sq_ft=legal_exc.stated_area_sq_ft or 0.0,
        tracts=legal_exc.tracts,
    )
    assert res_exc[0].is_fully_verified() is True
    assert any(
        c.name == "area_reasonableness" and c.status == "not_applicable" for c in res_exc[0].checks
    )
    assert res_exc[1].is_fully_verified() is False

    exc_dir = tmp_path / "main_exception_net_area"
    exc_dir.mkdir()
    written_exc = export_verified_csv(
        legal_exc.all_calls,
        res_exc[0],
        str(exc_dir / "deed.csv"),
        legal_desc=legal_exc,
        tract_results=list(zip(legal_exc.tracts, res_exc, strict=True)),
    )
    assert written_exc == [exc_dir / "deed_verified_tract1.csv"]

    # Also when MAIN has its own gross 10,000 and deed has net 8,400 alongside EXCEPTION:
    # no false conflict error; MAIN verifies against its own 10,000 and exports cleanly.
    legal_exc_gross = LegalDescription(
        calls=[*main_calls, *exception_calls],
        tracts=[main_10k, exception],
        stated_area_sq_ft=8400.0,
    )
    res_exc_gross = verify_closure(
        legal_exc_gross.all_calls,
        stated_area_sq_ft=legal_exc_gross.stated_area_sq_ft or 0.0,
        tracts=legal_exc_gross.tracts,
    )
    assert res_exc_gross[0].is_fully_verified() is True
    assert any(
        c.name == "area_reasonableness" and c.status == "passed" for c in res_exc_gross[0].checks
    )
    exc_gross_dir = tmp_path / "main_exception_gross_vs_net"
    exc_gross_dir.mkdir()
    written_exc_gross = export_verified_csv(
        legal_exc_gross.all_calls,
        res_exc_gross[0],
        str(exc_gross_dir / "deed.csv"),
        legal_desc=legal_exc_gross,
        tract_results=list(zip(legal_exc_gross.tracts, res_exc_gross, strict=True)),
    )
    assert written_exc_gross == [exc_gross_dir / "deed_verified_tract1.csv"]


def test_pipeline_multi_tract_forwards_stated_area_to_verify_closure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from metesparser import pipeline as pipeline_mod
    from metesparser.pipeline import Pipeline

    main_calls = _square(100.0, course_start=1)
    easement_calls = _square(20.0, course_start=1)
    main_no_area = Tract(
        label="Tract 1",
        tract_type=TractType.MAIN,
        role_basis="heading",
        calls=main_calls,
        stated_area_sq_ft=None,
    )
    easement = Tract(
        label="Easement 1",
        tract_type=TractType.EASEMENT,
        role_basis="heading",
        calls=easement_calls,
    )

    # Matching deed stated_area_sq_ft=10000.0 passes area_reasonableness.
    ld_ok = LegalDescription(
        calls=main_calls,
        tracts=[main_no_area, easement],
        stated_area_sq_ft=10000.0,
    )
    monkeypatch.setattr(
        pipeline_mod,
        "PDFProcessor",
        lambda **_: SimpleNamespace(process_deed_pdf=lambda _p, *, audit: ld_ok),
    )
    ok_results = Pipeline(provider="openai", cache=False).run(Path("deed.pdf"))
    assert isinstance(ok_results, list)
    assert ok_results[0].is_fully_verified() is True
    assert any(
        c.name == "area_reasonableness" and c.status == "passed" for c in ok_results[0].checks
    )

    # Mismatched deed stated_area_sq_ft=500.0 fails area_reasonableness.
    ld_bad = LegalDescription(
        calls=main_calls,
        tracts=[main_no_area, easement],
        stated_area_sq_ft=500.0,
    )
    monkeypatch.setattr(
        pipeline_mod,
        "PDFProcessor",
        lambda **_: SimpleNamespace(process_deed_pdf=lambda _p, *, audit: ld_bad),
    )
    bad_results = Pipeline(provider="openai", cache=False).run(Path("deed.pdf"))
    assert isinstance(bad_results, list)
    assert bad_results[0].is_fully_verified() is False
    assert any(
        c.name == "area_reasonableness" and c.status == "failed" for c in bad_results[0].checks
    )


def test_single_tract_export_and_legal_desc_csv_preserve_shared_leg_with_easement(
    tmp_path: Path,
) -> None:
    # MAIN (100x100 square) and companion EASEMENT (20x100 strip) share course 1 (N 0° E 100 ft).
    main_calls = _square(100.0, course_start=1)
    easement_calls = [
        _line(1, 0.0, 100.0),  # identical to main_calls[0]
        _line(2, 90.0, 20.0),
        _line(3, 180.0, 100.0),
        _line(4, 270.0, 20.0),
    ]
    main_tract = Tract(
        label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=main_calls
    )
    easement_tract = Tract(
        label="Easement 1",
        tract_type=TractType.EASEMENT,
        role_basis="heading",
        calls=easement_calls,
    )

    # JSON round-trip produces distinct DeedCall instances across calls and tracts.
    raw_ld = LegalDescription(
        source_doc="shared_leg.pdf",
        calls=main_calls,
        tracts=[main_tract, easement_tract],
        stated_area_sq_ft=10000.0,
    )
    rt_ld = LegalDescription.model_validate_json(raw_ld.model_dump_json())

    # 1. Package export_verified_csv (single-tract mode)
    res = verify_closure(rt_ld.calls, stated_area_sq_ft=10000.0)
    assert res.is_fully_verified() is True
    pkg_dir = tmp_path / "pkg_verified"
    pkg_dir.mkdir()
    written_pkg = export_verified_csv(rt_ld.calls, res, str(pkg_dir / "deed.csv"), legal_desc=rt_ld)
    assert written_pkg == [pkg_dir / "deed_verified.csv"]
    assert (pkg_dir / "deed_verified.metadata.txt").exists()
    assert "shared_leg.pdf" in (pkg_dir / "deed_verified.metadata.txt").read_text(encoding="utf-8")

    loaded_pkg = csv_to_calls(str(pkg_dir / "deed_verified.csv"))
    assert all(EASEMENT_TRACT_NOTE not in split_notes(c.notes) for c in loaded_pkg)
    assert [c.model_dump() for c in loaded_pkg] == [c.model_dump() for c in rt_ld.calls]
    assert verify_closure(loaded_pkg, stated_area_sq_ft=10000.0).is_fully_verified() is True

    # 2. Package legal_description_to_csv directly on the same JSON-roundtripped LegalDescription
    pkg_raw = tmp_path / "pkg_raw.csv"
    legal_description_to_csv(rt_ld, str(pkg_raw))
    loaded_pkg_raw = csv_to_calls(str(pkg_raw))
    assert all(EASEMENT_TRACT_NOTE not in split_notes(c.notes) for c in loaded_pkg_raw)
    assert verify_closure(loaded_pkg_raw, stated_area_sq_ft=10000.0).is_fully_verified() is True

    # 3. Monolith CSVBuilder.export_verified_csv & CSVBuilder.legal_description_to_csv
    #    (package_bridge constructs distinct DeedCall instances for calls vs tracts)
    mono_main_calls = _mono_square(100.0)
    mono_easement_calls = [
        MonoDeedCall(
            course=1,
            direction_text="az 0.0",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=100.0,
        ),
        MonoDeedCall(
            course=2,
            direction_text="az 90.0",
            bearing_azimuth_deg_from_north=90.0,
            distance_ft=20.0,
        ),
        MonoDeedCall(
            course=3,
            direction_text="az 180.0",
            bearing_azimuth_deg_from_north=180.0,
            distance_ft=100.0,
        ),
        MonoDeedCall(
            course=4,
            direction_text="az 270.0",
            bearing_azimuth_deg_from_north=270.0,
            distance_ft=20.0,
        ),
    ]
    mono_ld = MonoLegalDescription(
        source_doc="shared_leg_mono.pdf",
        calls=mono_main_calls,
        tracts=[
            MonoTract(
                label="Tract 1",
                tract_type=MonoTractType.MAIN,
                role_basis="heading",
                calls=mono_main_calls,
            ),
            MonoTract(
                label="Easement 1",
                tract_type=MonoTractType.EASEMENT,
                role_basis="heading",
                calls=mono_easement_calls,
            ),
        ],
        stated_area_sq_ft=10000.0,
    )
    mono_res = ClosureChecker.verify_closure(mono_main_calls, stated_area_sq_ft=10000.0)
    assert mono_res.is_fully_verified() is True

    mono_dir = tmp_path / "mono_verified"
    mono_dir.mkdir()
    written_mono = CSVBuilder.export_verified_csv(
        mono_main_calls, mono_res, str(mono_dir / "deed.csv"), legal_desc=mono_ld
    )
    assert written_mono == [mono_dir / "deed_verified.csv"]
    loaded_mono = csv_to_calls(str(mono_dir / "deed_verified.csv"))
    assert all(EASEMENT_TRACT_NOTE not in split_notes(c.notes) for c in loaded_mono)
    assert [c.model_dump() for c in loaded_mono] == [c.model_dump() for c in rt_ld.calls]
    assert verify_closure(loaded_mono, stated_area_sq_ft=10000.0).is_fully_verified() is True

    mono_raw = tmp_path / "mono_raw.csv"
    CSVBuilder.legal_description_to_csv(mono_ld, str(mono_raw))
    loaded_mono_raw = csv_to_calls(str(mono_raw))
    assert all(EASEMENT_TRACT_NOTE not in split_notes(c.notes) for c in loaded_mono_raw)
    assert verify_closure(loaded_mono_raw, stated_area_sq_ft=10000.0).is_fully_verified() is True

    # 4. Negative control: flat calls selecting easement_calls still get EASEMENT_TRACT_NOTE.
    ease_selected = LegalDescription.model_validate_json(
        LegalDescription(
            calls=easement_calls, tracts=[main_tract, easement_tract]
        ).model_dump_json()
    )
    ease_out = tmp_path / "ease_selected.csv"
    legal_description_to_csv(ease_selected, str(ease_out))
    loaded_ease = csv_to_calls(str(ease_out))
    assert all(EASEMENT_TRACT_NOTE in split_notes(c.notes) for c in loaded_ease)
    assert verify_closure(loaded_ease).is_fully_verified() is False
