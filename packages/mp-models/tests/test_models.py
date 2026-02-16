"""Verify core models are importable from mp_models."""


def test_deed_call_importable():
    from mp_models import DeedCall

    call = DeedCall(course=1, direction_text="North 45 degrees East", distance_ft=100.0)
    assert call.course == 1
    assert call.distance_ft == 100.0


def test_legal_description_importable():
    from mp_models import LegalDescription

    ld = LegalDescription()
    assert ld.calls == []


def test_closure_result_importable():
    from mp_models import ClosureResult

    cr = ClosureResult(
        misclosure_x_ft=0.001,
        misclosure_y_ft=0.002,
        misclosure_ft=0.003,
        area_sq_ft=7500.0,
        area_acres=0.172,
        perimeter_ft=350.0,
        closure_passed=True,
        angle_check_passed=True,
        curve_consistency_passed=True,
    )
    assert cr.is_fully_verified()


def test_point_importable():
    from mp_models import Point

    p = Point(x=1.0, y=2.0)
    assert str(p) == "(1.00, 2.00)"


def test_conversion_factors():
    from mp_models import ConversionFactors

    assert ConversionFactors.convert_to_feet(1.0, "chains") == 66.0


def test_audit_context_importable():
    from datetime import UTC, datetime

    from mp_models import AuditContext, RunMetadata

    rm = RunMetadata(
        parser_version="1.0.0",
        llm_provider="openai",
        llm_model="gpt-5",
        prompt_hash="abc123",
        timestamp_utc=datetime.now(UTC),
        source_pdf="deed.pdf",
        cache_enabled=True,
    )
    ctx = AuditContext(run_metadata=rm)
    assert ctx.call_audits == []


def test_bool_coercion():
    from mp_models import DeedCall

    call = DeedCall(course=1, direction_text="North", distance_ft=100.0, is_exception="true")
    assert call.is_exception is True


def test_frozen_model():
    import pytest
    from mp_models import DeedCall
    from pydantic import ValidationError

    call = DeedCall(course=1, direction_text="North", distance_ft=100.0)
    with pytest.raises(ValidationError):
        call.course = 2  # type: ignore[misc]
