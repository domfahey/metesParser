"""Tests for mp_export audit HTML writer module."""

from __future__ import annotations

from datetime import UTC, datetime

from mp_export.audit_html import generate_html as _gen
from mp_models import CheckResult as _CR
from mp_models import VerificationAudit as _VA


def _make_audit_context(**overrides):
    """Create a minimal AuditContext for testing."""
    from mp_models import AuditContext, RunMetadata

    rm_defaults = {
        "parser_version": "1.0.0",
        "llm_provider": "openai",
        "llm_model": "gpt-5",
        "prompt_hash": "abc123",
        "timestamp_utc": datetime.now(UTC),
        "source_pdf": "deed.pdf",
        "cache_enabled": True,
    }
    rm_defaults.update(overrides.pop("run_metadata", {}))
    rm = RunMetadata(**rm_defaults)
    return AuditContext(run_metadata=rm, **overrides)


def test_generate_html_basic():
    """generate_html should produce valid HTML with source PDF in output."""
    from mp_export.audit_html import generate_html

    ctx = _make_audit_context()
    html = generate_html(ctx)
    assert "<!DOCTYPE html>" in html
    assert "deed.pdf" in html
    assert "<html lang='en'>" in html
    assert "</html>" in html


def test_generate_html_with_extraction_record():
    """generate_html should include extraction section when extraction_record present."""
    from mp_export.audit_html import generate_html
    from mp_models import ExtractionRecord

    er = ExtractionRecord(
        raw_llm_response="raw response text",
        normalized_text="normalized text",
        confidence_signals={"has_pob": True, "has_bearings": False},
    )
    ctx = _make_audit_context(extraction_record=er)
    html = generate_html(ctx)
    assert "LLM Extraction" in html
    assert "raw response text" in html
    assert "normalized text" in html
    assert "has_pob" in html
    assert "PASS" in html
    assert "FAIL" in html


def test_generate_html_with_call_audits():
    """generate_html should include call-by-call section when call_audits present."""
    from mp_export.audit_html import generate_html
    from mp_models import CallAudit, Decision, Transformation

    ca = CallAudit(
        course=1,
        source_excerpt="North 45 degrees East 100 feet",
        transformations=[
            Transformation(
                step="bearing_parse",
                input="North 45 degrees East",
                output="N 45\u00b000' E",
                rule="quadrant_bearing",
            ),
        ],
        decisions=[
            Decision(
                field="bearing_quadrant",
                value="N 45\u00b000' E",
                reason="parsed from text",
                confidence=0.95,
                alternatives=[],
            ),
        ],
        flags=["has_bearing"],
    )
    ctx = _make_audit_context(call_audits=[ca])
    html = generate_html(ctx)
    assert "Call-by-Call Audit" in html
    assert "North 45 degrees East 100 feet" in html
    assert "bearing_quadrant" in html


def test_generate_html_with_verification_audit():
    """generate_html should include verification section when verification_audit present."""
    from mp_export.audit_html import generate_html
    from mp_models import CheckResult, VerificationAudit

    va = VerificationAudit(
        checks=[
            CheckResult(name="traverse_closure", passed=True, detail="0.0000 ft"),
            CheckResult(name="area_check", passed=False, detail="Area mismatch"),
        ],
        closure_summary={"misclosure_ft": 0.0, "area_sq_ft": 10000.0},
    )
    ctx = _make_audit_context(verification_audit=va)
    html = generate_html(ctx)
    assert "Verification" in html
    assert "traverse_closure" in html
    assert "area_check" in html
    assert "Area mismatch" in html


def test_generate_html_escapes_xss():
    """generate_html should escape HTML special characters to prevent XSS."""
    from mp_export.audit_html import generate_html

    ctx = _make_audit_context(run_metadata={"source_pdf": "<script>alert('xss')</script>.pdf"})
    html = generate_html(ctx)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_write_report(tmp_path):
    """write_report should create an HTML file on disk."""
    from mp_export.audit_html import write_report

    ctx = _make_audit_context()
    out = tmp_path / "report.html"
    write_report(ctx, out)
    assert out.exists()
    content = out.read_text()
    assert "<!DOCTYPE html>" in content
    assert "deed.pdf" in content


def test_confidence_class_thresholds():
    """_confidence_class should return correct CSS class for score thresholds."""
    from mp_export.audit_html import _confidence_class

    assert _confidence_class(0.9) == "confidence-high"
    assert _confidence_class(0.8) == "confidence-high"
    assert _confidence_class(0.79) == "confidence-medium"
    assert _confidence_class(0.5) == "confidence-medium"
    assert _confidence_class(0.49) == "confidence-low"
    assert _confidence_class(0.0) == "confidence-low"


def _va(label, perimeter):
    return _VA(
        checks=[_CR(name="traverse_closure", status="passed", detail="ok")],
        closure_summary={"perimeter_ft": perimeter},
        tract_label=label,
    )


def test_tract_verification_audits_render_one_labelled_section_each():
    ctx = _make_audit_context(
        tract_verification_audits=[_va("Tract <A>", 400.0), _va("Tract B", 200.0)]
    )
    out = _gen(ctx)
    assert out.count("<summary>Verification - ") == 2
    assert "Verification - Tract &lt;A&gt;" in out
    assert "Verification - Tract B" in out
    assert "400.0" in out and "200.0" in out


def test_single_verification_audit_output_unchanged():
    ctx = _make_audit_context(verification_audit=_va(None, 400.0))
    out = _gen(ctx)
    assert out.count("<summary>Verification</summary>") == 1
    assert "Verification - " not in out
    # byte-identical to the pre-change section layout
    assert (
        "<div class='section'>\n<details>\n<summary>Verification</summary>\n<table>\n"
        "<tr><th>Check</th><th>Result</th><th>Detail</th></tr>\n"
        "<tr><td>traverse_closure</td><td class='pass'>PASS</td><td>ok</td></tr>\n</table>\n"
        "<h4>Closure Summary</h4>\n<table>\n<tr><th>Metric</th><th>Value</th></tr>\n"
        "<tr><td>perimeter_ft</td><td>400.0</td></tr>\n</table>\n</details>\n</div>\n</body>"
    ) in out
