"""Keep hardened verification/export gates when integrating multi-tract support."""

from datetime import UTC, datetime

import pytest
from mp_export import export_verified_csv
from mp_models import AuditContext, DeedCall, RunMetadata, Tract, TractType
from mp_verify import verify_closure, verify_tract

from metesparser.closure_checker import ClosureChecker
from metesparser.csv_builder import CSVBuilder
from metesparser.models import (
    AuditContext as LegacyAuditContext,
)
from metesparser.models import (
    ClosureResult as LegacyClosureResult,
)
from metesparser.models import (
    DeedCall as LegacyCall,
)
from metesparser.models import (
    RunMetadata as LegacyRunMetadata,
)
from metesparser.models import (
    Tract as LegacyTract,
)
from metesparser.models import (
    TractType as LegacyTractType,
)


def square(size=100):
    return [
        DeedCall(
            course=i + 1, direction_text=str(a), bearing_azimuth_deg_from_north=a, distance_ft=size
        )
        for i, a in enumerate((0, 90, 180, 270))
    ]


@pytest.mark.parametrize("verify", [verify_tract, ClosureChecker.verify_tract])
def test_multi_tract_verification_rejects_crossing_boundaries(verify):
    calls = [
        DeedCall(
            course=i + 1, direction_text=str(a), bearing_azimuth_deg_from_north=a, distance_ft=d
        )
        for i, (a, d) in enumerate(
            ((45, 2**0.5 * 100), (270, 100), (135, 2**0.5 * 100), (270, 100))
        )
    ]
    result = verify(calls)
    assert not result.is_fully_verified()
    assert any("intersect" in w.lower() for w in result.warnings)


@pytest.mark.parametrize("export", [export_verified_csv, CSVBuilder.export_verified_csv])
def test_multi_tract_export_rechecks_result_against_selected_calls(export, tmp_path):
    calls = square()
    result = verify_closure(calls)
    changed = calls[:-1] + [calls[-1].model_copy(update={"distance_ft": 150})]
    if export == CSVBuilder.export_verified_csv:
        calls = [LegacyCall.model_validate(c.model_dump()) for c in calls]
        changed = [LegacyCall.model_validate(c.model_dump()) for c in changed]
        result = ClosureChecker.verify_closure(calls)
        tract = LegacyTract(label="Tract A", tract_type=LegacyTractType.MAIN, calls=changed)
    else:
        tract = Tract(label="Tract A", tract_type=TractType.MAIN, calls=changed)
    with pytest.raises(ValueError, match="fresh verification|does not match"):
        export(calls, result, str(tmp_path / "calls.csv"), tract_results=[(tract, result)])
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    ("verify_fn", "call_cls"),
    [
        (verify_tract, DeedCall),
        (ClosureChecker.verify_tract, LegacyCall),
    ],
)
def test_verify_tract_mixed_main_and_exception_preserves_net_area(verify_fn, call_cls):
    main_calls = [call_cls.model_validate(c.model_dump()) for c in square(100)]
    exc_calls = [
        call_cls.model_validate(
            c.model_copy(update={"course": c.course + 4, "is_exception": True}).model_dump()
        )
        for c in square(20)
    ]
    result = verify_fn(main_calls + exc_calls)
    assert result.closure_passed is True
    assert result.area_sq_ft == pytest.approx(9600.0)
    assert result.angle_check_passed is True
    assert not any("intersect" in w.lower() for w in result.warnings)


@pytest.mark.parametrize(
    ("verify_fn", "call_cls"),
    [
        (verify_tract, DeedCall),
        (ClosureChecker.verify_tract, LegacyCall),
    ],
)
def test_verify_tract_standalone_exception_only_tract_closes(verify_fn, call_cls):
    exc_only = [
        call_cls.model_validate(c.model_copy(update={"is_exception": True}).model_dump())
        for c in square(50)
    ]
    result = verify_fn(exc_only)
    assert result.closure_passed is True
    assert result.area_sq_ft == pytest.approx(2500.0)
    assert result.angle_check_passed is True


@pytest.mark.parametrize(
    ("verify_fn", "call_cls", "tract_cls", "tract_type_cls", "audit_cls", "meta_cls"),
    [
        (verify_closure, DeedCall, Tract, TractType, AuditContext, RunMetadata),
        (
            ClosureChecker.verify_closure,
            LegacyCall,
            LegacyTract,
            LegacyTractType,
            LegacyAuditContext,
            LegacyRunMetadata,
        ),
    ],
)
def test_multi_tract_verify_closure_does_not_overwrite_audit_context(
    verify_fn, call_cls, tract_cls, tract_type_cls, audit_cls, meta_cls
):
    c1 = [call_cls.model_validate(c.model_dump()) for c in square(100)]
    c2 = [call_cls.model_validate(c.model_dump()) for c in square(50)]
    t1 = tract_cls(label="Tract 1", tract_type=tract_type_cls.MAIN, calls=c1)
    t2 = tract_cls(label="Tract 2", tract_type=tract_type_cls.MAIN, calls=c2)
    ctx = audit_cls(
        run_metadata=meta_cls(
            parser_version="0.5.0",
            llm_provider="openai",
            llm_model="gpt-5.2",
            prompt_hash="abc123",
            timestamp_utc=datetime.now(UTC),
            source_pdf="deed.pdf",
            cache_enabled=False,
        )
    )
    results = verify_fn(c1, tracts=[t1, t2], audit_context=ctx)
    assert len(results) == 2
    assert ctx.verification_audit is None


def test_csv_builder_all_tracts_fail_verification_nested_dir(tmp_path):
    """When all tracts fail verification and parent directories don't exist yet,
    CSVBuilder.export_verified_csv should create parent dirs and return []."""
    calls = [LegacyCall.model_validate(c.model_dump()) for c in square(100)]
    t1 = LegacyTract(label="Tract 1", tract_type=LegacyTractType.MAIN, calls=calls)
    bad_closure = LegacyClosureResult(
        misclosure_x_ft=5.0,
        misclosure_y_ft=5.0,
        misclosure_ft=7.07,
        area_sq_ft=2500.0,
        area_acres=2500.0 / 43560.0,
        perimeter_ft=200.0,
        closure_passed=False,
        angle_check_passed=True,
        curve_consistency_passed=True,
        warnings=["Closure failed"],
    )
    nested_path = tmp_path / "nested" / "sub" / "deed.csv"
    res = CSVBuilder.export_verified_csv(
        calls,
        bad_closure,
        str(nested_path),
        tract_results=[(t1, bad_closure)],
    )
    assert res == []
    assert (tmp_path / "nested" / "sub" / "deed_verified.verification.txt").exists()
