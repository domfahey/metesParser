"""PR #60 round 11: a course the traverse cannot position blocks closure and misclosure."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from mp_models import AuditContext as PackageAuditContext
from mp_models import DeedCall as PackageDeedCall
from mp_models import RunMetadata as PackageRunMetadata
from mp_verify.closure import get_closure_summary as package_summary
from mp_verify.closure import verify_closure as package_verify

from metesparser.closure_checker import ClosureChecker
from metesparser.models import AuditContext as MonolithAuditContext
from metesparser.models import DeedCall as MonolithDeedCall
from metesparser.models import RunMetadata as MonolithRunMetadata

IMPLS = {
    "package": (PackageDeedCall, package_verify, package_summary, PackageAuditContext),
    "monolith": (
        MonolithDeedCall,
        ClosureChecker.verify_closure,
        ClosureChecker.get_closure_summary,
        MonolithAuditContext,
    ),
}
RUN_METADATA = {"package": PackageRunMetadata, "monolith": MonolithRunMetadata}


def _line(model, course, azimuth, distance=100.0):
    return model(
        course=course,
        direction_text="recorded",
        bearing_azimuth_deg_from_north=azimuth,
        distance_ft=distance,
    )


def _garbage_chord_curve(model):
    return model(
        course=3,
        direction_text="recorded",
        distance_ft=50.0,
        curve_dir="right",
        radius_ft=100.0,
        delta_deg=30.0,
        chord_bearing="garbage",
        bearing_azimuth_deg_from_north=None,
    )


def _infeasible_deed(model):
    curve = model(
        course=2,
        direction_text="recorded",
        distance_ft=450.0,
        curve_dir="right",
        radius_ft=200.0,
        chord_length_ft=450.0,
        chord_bearing="N 90° E",
    )
    return [
        _line(model, 1, 0.0),
        curve,
        _line(model, 3, 180.0),
        _line(model, 4, 270.0),
        _line(model, 5, 0.0),
        _line(model, 6, 180.0),
    ]


def _assert_not_determined(result, text):
    assert result.misclosure_available is False
    assert result.closure_passed is False
    assert result.area_available is False
    assert result.perimeter_available is False
    assert result.precision_ratio is None
    assert result.geometry_verified is False
    assert "Misclosure: not determined" in text
    assert "Area: not determined" in text
    assert "Perimeter: not determined" in text


@pytest.mark.parametrize("impl", IMPLS)
def test_curve_with_delta_but_no_tangent_and_bad_chord_is_unpositioned(impl):
    model, verify, summary, _ = IMPLS[impl]
    calls = [
        _line(model, 1, 0.0),
        _line(model, 2, 90.0),
        _garbage_chord_curve(model),
        _line(model, 4, 180.0),
    ]
    result = verify(calls)
    assert any("Course 3" in w and "cannot be positioned" in w for w in result.warnings)
    _assert_not_determined(result, summary(result))
    assert {c.name: c.status for c in result.checks}["traverse_closure"] != "passed"


@pytest.mark.parametrize("impl", IMPLS)
def test_infeasible_chord_blocks_later_courses_and_misclosure(impl):
    model, verify, summary, _ = IMPLS[impl]
    result = verify(_infeasible_deed(model))
    _assert_not_determined(result, summary(result))
    assert any("Course 2" in w and "cannot be positioned" in w for w in result.warnings)
    # Courses 3-6 follow an unpositioned course, so their absolute positions are unknown.
    joined = " ".join(result.warnings)
    assert "3, 4, 5, 6" in joined
    assert result.misclosure_ft == 0.0
    assert {c.name: c.status for c in result.checks}["traverse_closure"] == "blocked"


@pytest.mark.parametrize("impl", IMPLS)
def test_ordinary_traverse_misclosure_available(impl):
    model, verify, summary, _ = IMPLS[impl]
    result = verify([_line(model, i + 1, a) for i, a in enumerate((0.0, 90.0, 180.0, 270.0))])
    assert result.misclosure_available is True
    assert "Misclosure: 0.0000 ft" in summary(result)


@pytest.mark.parametrize("impl", IMPLS)
def test_audit_summary_marks_misclosure_not_determined(impl):
    model, verify, _, ctx_cls = IMPLS[impl]
    ctx = ctx_cls(
        run_metadata=RUN_METADATA[impl](
            parser_version="0",
            llm_provider="none",
            llm_model="none",
            prompt_hash="x",
            timestamp_utc=datetime(2026, 1, 1, tzinfo=UTC),
            source_pdf="t.pdf",
            cache_enabled=False,
        )
    )
    verify(_infeasible_deed(model), audit_context=ctx)
    closure = ctx.verification_audit.closure_summary
    assert closure["misclosure_ft"] == "not determined"
    assert closure["precision_ratio"] == "N/A"
    json.dumps(closure, allow_nan=False)
