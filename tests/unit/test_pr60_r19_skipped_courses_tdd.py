"""PR #60 round 19: non-strict extraction never silently drops a course.

A course the non-strict extractor cannot parse is recorded as a ``SkippedCourse``
(audit trail and/or an explicit sink), keeps its course number so the gap stays
visible, and makes verification fail closed: traverse closure is blocked with
reason ``skipped_courses``, misclosure/area/perimeter are unavailable and a warning
names the verbatim course text. With nowhere to record a skip, extraction raises.
Strict extraction (the default) is unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime

import mp_models
import pytest
from mp_parse import extract_calls as package_extract
from mp_verify.closure import verify_closure as package_verify

from metesparser import models as monolith_models
from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker

MALFORMED = "N 12.5960° E 75.00 feet"
# Without course 2 the remaining four courses form a closed 100 ft square.
DEED = (
    "BEGINNING at a point; THENCE due North 100.00 feet; THENCE "
    + MALFORMED
    + "; THENCE due East 100.00 feet; THENCE due South 100.00 feet; "
    "THENCE due West 100.00 feet to the point of beginning."
)
UNPARSED_CURVE = "along a curve to the right having a radius of 50 feet to a point"
DEED_UNPARSED_CURVE = DEED.replace(MALFORMED, UNPARSED_CURVE)


def _package_extract(text, **kwargs):
    return package_extract(text, **kwargs)[0]


IMPLS = {
    "package": (mp_models, _package_extract, package_verify),
    "monolith": (monolith_models, CallExtractor.extract_calls, ClosureChecker.verify_closure),
}


@pytest.fixture(params=sorted(IMPLS))
def impl(request):
    return IMPLS[request.param]


def _ctx(models):
    return models.AuditContext(
        run_metadata=models.RunMetadata(
            parser_version="test",
            llm_provider="test",
            llm_model="test",
            prompt_hash="test",
            timestamp_utc=datetime(2026, 10, 30, tzinfo=UTC),
            source_pdf="test.pdf",
            cache_enabled=False,
        )
    )


def _assert_blocked(result, excerpt):
    assert not result.closure_passed
    assert not result.misclosure_available
    assert not result.area_available
    assert not result.perimeter_available
    assert not result.geometry_verified
    closure = next(check for check in result.checks if check.name == "traverse_closure")
    assert closure.status == "blocked"
    assert closure.reason == "skipped_courses"
    assert any("Course 2" in w and excerpt in w and "skipped" in w for w in result.warnings)


def test_strict_extraction_still_raises(impl):
    _models, extract, _verify = impl
    with pytest.raises(ValueError, match=r"Malformed course 2"):
        extract(DEED)


def test_non_strict_records_skip_in_audit_and_keeps_course_gap(impl):
    models, extract, _verify = impl
    ctx = _ctx(models)
    calls = extract(DEED, strict=False, audit_context=ctx)
    assert [c.course for c in calls] == [1, 3, 4, 5]
    assert len(ctx.skipped_courses) == 1
    skip = ctx.skipped_courses[0]
    assert skip.course == 2
    assert skip.source_excerpt.strip() == MALFORMED
    assert skip.error
    assert [a.course for a in ctx.call_audits] == [1, 3, 4, 5]


def test_non_strict_without_record_target_raises(impl):
    _models, extract, _verify = impl
    with pytest.raises(ValueError, match=r"course 2.*not recorded"):
        extract(DEED, strict=False)


@pytest.mark.parametrize("deed,excerpt", [(DEED, MALFORMED), (DEED_UNPARSED_CURVE, UNPARSED_CURVE)])
def test_verification_via_audit_context_fails_closed(impl, deed, excerpt):
    models, extract, verify = impl
    ctx = _ctx(models)
    calls = extract(deed, strict=False, audit_context=ctx)
    assert [s.course for s in ctx.skipped_courses] == [2]
    result = verify(calls, audit_context=ctx)
    _assert_blocked(result, excerpt)
    summary = ctx.verification_audit.closure_summary
    assert summary["misclosure_ft"] == "not determined"
    assert summary["area_sq_ft"] == "not determined"
    assert summary["perimeter_ft"] == "not determined"


def test_verification_via_explicit_sink_fails_closed(impl):
    _models, extract, verify = impl
    skipped: list = []
    calls = extract(DEED, strict=False, skipped_courses=skipped)
    assert [s.course for s in skipped] == [2]
    _assert_blocked(verify(calls, skipped_courses=skipped), MALFORMED)


def test_package_multi_tract_skip_blocks_only_its_tract():
    tract_one = DEED.replace("BEGINNING", "TRACT 1: BEGINNING")
    tract_two = (
        " TRACT 2: BEGINNING at a point; THENCE due North 50.00 feet; THENCE due East 50.00 "
        "feet; THENCE due South 50.00 feet; THENCE due West 50.00 feet to the point of beginning."
    )
    ctx = _ctx(mp_models)
    calls, tracts = package_extract(tract_one + tract_two, strict=False, audit_context=ctx)
    assert [t.label for t in tracts] == ["Tract 1", "Tract 2"]
    assert [s.course for s in tracts[0].skipped_courses] == [2]
    assert tracts[1].skipped_courses == []
    assert [(s.tract_label, s.course) for s in ctx.skipped_courses] == [("Tract 1", 2)]

    for audit in (None, ctx):
        first, second = package_verify(calls, tracts=tracts, audit_context=audit)
        _assert_blocked(first, MALFORMED)
        assert second.geometry_verified

    # The flat call list carries every tract's skip when verified as one traverse.
    _assert_blocked(package_verify(calls, audit_context=ctx), MALFORMED)


def test_monolith_tract_verification_honours_tract_skips():
    skip = monolith_models.SkippedCourse(
        course=2, source_course=2, source_excerpt=MALFORMED, error_type="ValueError", error="bad"
    )
    calls = CallExtractor.extract_calls(DEED, strict=False, skipped_courses=[])
    tract = monolith_models.Tract(
        label="Tract 1",
        tract_type=monolith_models.TractType.MAIN,
        calls=calls,
        skipped_courses=[skip],
    )
    (result,) = ClosureChecker.verify_closure(calls, tracts=[tract])
    _assert_blocked(result, MALFORMED)


def test_tract_with_only_skipped_courses_is_kept():
    text = (
        "TRACT 1: BEGINNING at a point; THENCE " + MALFORMED + " to the point of beginning. "
        "TRACT 2: BEGINNING at a point; THENCE due North 50.00 feet; THENCE due East 50.00 "
        "feet; THENCE due South 50.00 feet; THENCE due West 50.00 feet to the point of beginning."
    )
    skipped: list = []
    _calls, tracts = package_extract(text, strict=False, skipped_courses=skipped)
    assert [t.label for t in tracts] == ["Tract 1", "Tract 2"]
    assert tracts[0].calls == []
    assert [s.course for s in tracts[0].skipped_courses] == [1]
    first, _second = package_verify(_calls, tracts=tracts)
    assert not first.geometry_verified
    assert first.checks[0].reason == "skipped_courses"


def test_html_audit_reports_list_skipped_courses():
    from mp_export.audit_html import generate_html

    from metesparser.audit_reporter import AuditReporter

    for models, extract, render in (
        (mp_models, _package_extract, generate_html),
        (monolith_models, CallExtractor.extract_calls, AuditReporter.generate_html),
    ):
        ctx = _ctx(models)
        extract(DEED, strict=False, audit_context=ctx)
        page = render(ctx)
        assert "Skipped Courses" in page
        assert "N 12.5960° E 75.00 feet" in page
