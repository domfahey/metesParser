"""Verification distinguishes executed checks, unavailable geometry, and source review."""

import math
from datetime import UTC, datetime

import pytest


@pytest.fixture(params=["package", "monolith"])
def api(request):
    if request.param == "package":
        import mp_models as models
        from mp_export import export_verified_csv
        from mp_export.audit_html import generate_html
        from mp_verify import verify_closure
        from mp_verify.confidence import calculate_confidence_score
    else:
        from metesparser import models
        from metesparser.audit_reporter import AuditReporter
        from metesparser.closure_checker import ClosureChecker
        from metesparser.csv_builder import CSVBuilder

        verify_closure = ClosureChecker.verify_closure
        export_verified_csv = CSVBuilder.export_verified_csv
        generate_html = AuditReporter.generate_html
        calculate_confidence_score = ClosureChecker.calculate_confidence_score
    return models, verify_closure, export_verified_csv, generate_html, calculate_confidence_score


def square(models):
    return [
        models.DeedCall(
            course=i + 1,
            direction_text="boundary",
            distance_ft=100,
            bearing_azimuth_deg_from_north=az,
        )
        for i, az in enumerate((0, 90, 180, 270))
    ]


def context(models):
    return models.AuditContext(
        run_metadata=models.RunMetadata(
            parser_version="test",
            llm_provider="none",
            llm_model="none",
            prompt_hash="none",
            timestamp_utc=datetime.now(UTC),
            source_pdf="deed.pdf",
            cache_enabled=False,
        )
    )


def test_check_result_legacy_roundtrip_and_authoritative_status(api):
    models, *_ = api
    legacy = models.CheckResult(name="angles", passed=True, detail="legacy pass")
    assert legacy.status == "passed"
    assert models.CheckResult.model_validate_json(legacy.model_dump_json()) == legacy
    skipped = models.CheckResult(
        name="angles",
        status="not_applicable",
        passed=True,
        reason="curved_boundary",
        detail="curves present",
    )
    assert skipped.passed is False
    blocked = models.CheckResult(name="angles", status="blocked", detail="bearing missing")
    assert blocked.passed is False


def test_geometry_does_not_imply_source_review(api):
    models, verify, *_ = api
    result = verify(square(models))
    assert result.geometry_verified
    assert result.is_fully_verified()
    assert result.source_review_status == "not_reviewed"
    assert not result.source_review_complete
    assert {c.name for c in result.checks} >= {
        "traverse_closure",
        "interior_angles",
        "curve_consistency",
        "parallelism",
        "area_reasonableness",
        "double_entry",
        "bearing_reversals",
        "distance_reasonableness",
    }
    legacy_data = result.model_dump(exclude={"checks", "source_review_status"})
    assert models.ClosureResult.model_validate(legacy_data).is_fully_verified()


def test_curved_boundary_is_not_applicable_and_still_exports(api, tmp_path):
    models, verify, export, render, _ = api
    calls = [
        models.DeedCall(
            course=i + 1,
            direction_text="semicircle",
            distance_ft=math.pi * 100,
            bearing_azimuth_deg_from_north=az,
            curve_dir="left",
            radius_ft=100,
            delta_deg=180,
            arc_length_ft=math.pi * 100,
        )
        for i, az in enumerate((0, 180))
    ]
    ctx = context(models)
    result = verify(calls, audit_context=ctx)
    angle = next(c for c in result.checks if c.name == "interior_angles")
    assert angle.status == "not_applicable"
    assert not angle.passed
    assert "curv" in angle.detail
    assert result.is_fully_verified()
    assert ctx.verification_audit.checks == result.checks
    page = render(ctx)
    assert "NOT APPLICABLE" in page
    export(calls, result, str(tmp_path / "circle.csv"))
    assert (tmp_path / "circle_verified.csv").exists()


def test_missing_bearing_blocks_check_and_export(api, tmp_path):
    models, verify, export, render, _ = api
    calls = square(models)
    calls[0] = calls[0].model_copy(update={"bearing_azimuth_deg_from_north": None})
    ctx = context(models)
    result = verify(calls, audit_context=ctx)
    checks = {c.name: c for c in result.checks}
    assert checks["interior_angles"].status == "blocked"
    assert checks["traverse_closure"].status == "blocked"
    assert "BLOCKED" in render(ctx)
    assert not result.is_fully_verified()
    forged = result.model_copy(
        update={
            "closure_passed": True,
            "angle_check_passed": True,
            "curve_consistency_passed": True,
            "warnings": [],
        }
    )
    assert not forged.is_fully_verified()
    with pytest.raises(ValueError):
        export(calls, forged, str(tmp_path / "blocked.csv"))


def test_real_angle_failure_is_failed_with_accurate_audit(api):
    models, verify, _, render, _ = api
    calls = square(models)
    calls[2] = calls[2].model_copy(update={"bearing_azimuth_deg_from_north": 45})
    ctx = context(models)
    result = verify(calls, audit_context=ctx)
    angle = next(c for c in result.checks if c.name == "interior_angles")
    assert angle.status == "failed"
    assert "sum" in angle.detail
    assert "skipped" not in angle.detail
    assert "skipped" not in render(ctx)


@pytest.mark.parametrize("status", ["not_applicable", "blocked", "failed"])
def test_nonpassing_checks_receive_no_confidence_credit(api, status):
    models, verify, _, _, score = api
    calls = square(models)
    result = verify(calls)
    selected = {"interior_angles", "curve_consistency"}
    passing = [models.CheckResult(name=n, status="passed", detail="executed") for n in selected]
    unearned = [models.CheckResult(name=n, status=status, detail="no pass") for n in selected]
    good = result.model_copy(update={"checks": passing})
    other = result.model_copy(update={"checks": unearned})
    assert score(good, calls) - score(other, calls) == pytest.approx(0.2)


def test_forged_structured_pass_cannot_bypass_fresh_export_verification(api, tmp_path):
    models, verify, export, *_ = api
    calls = square(models)
    result = verify(calls)
    calls[0] = calls[0].model_copy(update={"distance_ft": 101})
    with pytest.raises(ValueError, match="fresh verification"):
        export(calls, result, str(tmp_path / "stale.csv"))
    assert not (tmp_path / "stale_verified.csv").exists()


@pytest.mark.parametrize("status", ["complete", "incomplete"])
def test_explicit_source_review_does_not_invalidate_fresh_geometry(api, tmp_path, status):
    models, verify, export, *_ = api
    calls = square(models)
    result = verify(calls).model_copy(update={"source_review_status": status})
    assert result.source_review_complete == (status == "complete")
    assert result.geometry_verified
    export(calls, result, str(tmp_path / "review.csv"))
    assert (tmp_path / "review_verified.csv").exists()
    stale = result.model_copy(update={"area_sq_ft": result.area_sq_ft + 1})
    with pytest.raises(ValueError, match="does not match"):
        export(calls, stale, str(tmp_path / "stale_area.csv"))


@pytest.mark.parametrize(
    "flag", ["closure_passed", "angle_check_passed", "curve_consistency_passed"]
)
def test_contradictory_critical_legacy_flags_deny_verification(api, flag):
    models, verify, *_ = api
    result = verify(square(models))
    # Ensure the selected check is applicable and passed for this mismatch.
    checks = [
        check.model_copy(update={"status": "passed", "passed": True}) for check in result.checks
    ]
    result = result.model_copy(update={"checks": checks, flag: False})
    assert not result.is_fully_verified()


@pytest.mark.parametrize("num_courses", [0, 1, 2])
def test_insufficient_straight_topology_is_blocked(api, num_courses):
    models, verify, *_ = api
    result = verify(square(models)[:num_courses])
    checks = {check.name: check for check in result.checks}
    assert checks["interior_angles"].status == "blocked"
    assert checks["boundary_intersections"].status == "blocked"
    assert "checked" not in checks["boundary_intersections"].detail.lower()


@pytest.mark.parametrize("element", ["delta_deg", "arc_length_ft"])
def test_curve_consistency_requires_redundant_measure_for_pass_credit(api, element):
    models, verify, *_ = api
    values = {"delta_deg": 360} if element == "delta_deg" else {"arc_length_ft": math.tau * 100}
    call = models.DeedCall(
        course=1,
        direction_text="full circle",
        distance_ft=math.tau * 100,
        bearing_azimuth_deg_from_north=0,
        curve_dir="left",
        radius_ft=100,
        **values,
    )
    result = verify([call])
    check = next(check for check in result.checks if check.name == "curve_consistency")
    assert check.status == "not_applicable"
    assert "redundant" in check.detail.lower()
    assert result.is_fully_verified()


@pytest.mark.parametrize("missing", ["curve_dir", "radius_ft", "elements"])
def test_bypassed_incomplete_curve_geometry_is_blocked(api, missing):
    models, verify, *_ = api
    call = models.DeedCall(
        course=1,
        direction_text="curve",
        distance_ft=math.pi * 100,
        bearing_azimuth_deg_from_north=0,
        curve_dir="left",
        radius_ft=100,
        delta_deg=180,
        arc_length_ft=math.pi * 100,
    )
    update = (
        {"delta_deg": None, "arc_length_ft": None} if missing == "elements" else {missing: None}
    )
    result = verify([call.model_copy(update=update)])
    check = next(check for check in result.checks if check.name == "curve_consistency")
    assert check.status == "blocked"
    assert not check.passed
    assert not result.is_fully_verified()


def test_schema_rejects_absent_distances_and_chord_only_geometry(api):
    models, *_ = api
    with pytest.raises(ValueError, match="distance_ft"):
        models.DeedCall(course=1, direction_text="north")
    with pytest.raises(ValueError, match="radius_ft"):
        models.DeedCall(
            course=1, direction_text="curve", distance_ft=100, curve_dir="left", chord_length_ft=100
        )


def test_legacy_result_with_historical_confidence_exports_verified_geometry(api, tmp_path):
    models, verify, export, *_ = api
    calls = square(models)
    payload = verify(calls).model_dump(exclude={"checks", "source_review_status"})
    payload["confidence_score"] = 0.99
    legacy = models.ClosureResult.model_validate_json(
        models.ClosureResult.model_validate(payload).model_dump_json(exclude_unset=True)
    )
    export(calls, legacy, str(tmp_path / "legacy.csv"))
    assert (tmp_path / "legacy_verified.csv").exists()
    forged = legacy.model_copy(update={"area_sq_ft": legacy.area_sq_ft + 1})
    with pytest.raises(ValueError, match="does not match"):
        export(calls, forged, str(tmp_path / "forged.csv"))
    assert not (tmp_path / "forged_verified.csv").exists()


def test_modern_result_cannot_change_heuristic_confidence(api, tmp_path):
    models, verify, export, *_ = api
    calls = square(models)
    result = verify(calls).model_copy(update={"confidence_score": 0.01})
    with pytest.raises(ValueError, match="does not match"):
        export(calls, result, str(tmp_path / "modern.csv"))


@pytest.mark.parametrize("exception_issue", ["missing_bearing", "unclosed"])
def test_unavailable_exception_area_blocks_net_area_comparison(api, exception_issue):
    models, verify, *_ = api
    exceptions = [call.model_copy(update={"is_exception": True}) for call in square(models)]
    if exception_issue == "missing_bearing":
        exceptions[0] = exceptions[0].model_copy(update={"bearing_azimuth_deg_from_north": None})
    else:
        exceptions = exceptions[:-1]
    result = verify(square(models) + exceptions, stated_area_sq_ft=5000)
    check = next(check for check in result.checks if check.name == "area_reasonableness")
    assert check.status == "blocked"
    assert check.reason == "missing_required_inputs"
    assert check.inputs["area_available"] is False
    assert "complete" in check.detail.lower()
    assert not any("Computed area differs" in warning for warning in result.warnings)
    assert not result.is_fully_verified()


def test_area_availability_is_reported_without_stated_area(api):
    models, verify, *_ = api
    incomplete_exception = square(models)[0].model_copy(
        update={"is_exception": True, "bearing_azimuth_deg_from_north": None}
    )
    result = verify(square(models) + [incomplete_exception])
    check = next(check for check in result.checks if check.name == "area_reasonableness")
    assert check.status == "not_applicable"
    assert check.inputs["area_available"] is False
