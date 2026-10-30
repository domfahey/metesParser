"""PR #60 round 10: area is flagged not determined (not a chord-polygon number)."""

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
from metesparser.review_packet import build_closure_section

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


def _line(model, course, azimuth):
    return model(
        course=course,
        direction_text="recorded",
        bearing_azimuth_deg_from_north=azimuth,
        distance_ft=100.0,
    )


def _chord_square(model):
    curve = model(
        course=4,
        direction_text="recorded",
        distance_ft=100.0,
        curve_dir="right",
        radius_ft=60.0,
        chord_length_ft=100.0,
        chord_bearing="S 90° W",
        bearing_azimuth_deg_from_north=270.0,
    )
    return [_line(model, 1, 0.0), _line(model, 2, 90.0), _line(model, 3, 180.0), curve]


@pytest.mark.parametrize("impl", IMPLS)
def test_chord_only_area_not_determined(impl):
    model, verify, summary, _ = IMPLS[impl]
    result = verify(_chord_square(model))
    assert result.area_available is False
    assert result.perimeter_available is False
    text = summary(result)
    assert "Area: not determined" in text
    assert "10,000" not in text
    assert "Perimeter: not determined" in text


@pytest.mark.parametrize("impl", IMPLS)
def test_plain_square_area_available(impl):
    model, verify, summary, _ = IMPLS[impl]
    calls = [_line(model, i + 1, a) for i, a in enumerate((0.0, 90.0, 180.0, 270.0))]
    result = verify(calls)
    assert result.area_available is True
    assert "Area: 10,000.00 sq ft" in summary(result)


@pytest.mark.parametrize("impl", IMPLS)
def test_audit_summary_marks_area_not_determined(impl):
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
    verify(_chord_square(model), audit_context=ctx)
    closure = ctx.verification_audit.closure_summary
    assert closure["area_sq_ft"] == "not determined"
    assert closure["area_acres"] == "not determined"
    assert closure["perimeter_ft"] == "not determined"
    json.dumps(closure, allow_nan=False)


def test_review_packet_area_not_determined():
    gt = {
        "expected_closure": {
            "closure_passed": False,
            "area_sq_ft": 10000.0,
            "area_acres": 0.2296,
            "area_available": False,
            "perimeter_ft": None,
            "perimeter_available": False,
        }
    }
    html = build_closure_section(gt)
    assert "10000" not in html
    assert html.count("not determined") == 3
