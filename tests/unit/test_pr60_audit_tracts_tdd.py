"""Monolith audit report renders per-tract verification audits."""

from __future__ import annotations

from datetime import UTC, datetime

from metesparser.audit_reporter import AuditReporter
from metesparser.models import AuditContext, CheckResult, RunMetadata, VerificationAudit


def _make_audit_context(**kw):
    rm = RunMetadata(
        parser_version="1.0.0",
        llm_provider="openai",
        llm_model="gpt-5",
        prompt_hash="abc",
        timestamp_utc=datetime.now(UTC),
        source_pdf="deed.pdf",
        cache_enabled=True,
    )
    return AuditContext(run_metadata=rm, **kw)


def _va(label, perimeter):
    return VerificationAudit(
        checks=[CheckResult(name="traverse_closure", status="passed", detail="ok")],
        closure_summary={"perimeter_ft": perimeter},
        tract_label=label,
    )


def test_tract_verification_audits_render_one_labelled_section_each():
    ctx = _make_audit_context(
        tract_verification_audits=[_va("Tract <A>", 400.0), _va("Tract B", 200.0)]
    )
    out = AuditReporter.generate_html(ctx)
    assert out.count("<summary>Verification - ") == 2
    assert "Verification - Tract &lt;A&gt;" in out
    assert "Verification - Tract B" in out
    assert "400.0" in out and "200.0" in out


def test_single_verification_audit_output_unchanged():
    ctx = _make_audit_context(verification_audit=_va(None, 400.0))
    out = AuditReporter.generate_html(ctx)
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
