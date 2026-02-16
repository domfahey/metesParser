"""HTML audit report generator.

Renders AuditContext as a self-contained HTML report with embedded CSS.
No external dependencies (no Jinja, no JS frameworks).
"""

import html
from pathlib import Path

from .models import AuditContext


class AuditReporter:
    """Generate HTML audit reports from AuditContext."""

    @staticmethod
    def _confidence_class(score: float) -> str:
        """Return CSS class name for a confidence score."""
        if score >= 0.8:
            return "confidence-high"
        if score >= 0.5:
            return "confidence-medium"
        return "confidence-low"

    @classmethod
    def generate_html(cls, ctx: AuditContext) -> str:
        """Generate a self-contained HTML audit report."""
        parts: list[str] = []
        parts.append("<!DOCTYPE html>")
        parts.append("<html lang='en'>")
        parts.append("<head>")
        parts.append("<meta charset='utf-8'>")
        parts.append("<meta name='viewport' content='width=device-width, initial-scale=1'>")
        parts.append(
            f"<title>Audit Report &mdash; {html.escape(ctx.run_metadata.source_pdf)}</title>"
        )
        parts.append("<style>")
        parts.append(cls._css())
        parts.append("</style>")
        parts.append("</head>")
        parts.append("<body>")

        # --- Header ---
        parts.append(cls._build_header(ctx))

        # --- Extraction section ---
        if ctx.extraction_record is not None:
            parts.append(cls._build_extraction_section(ctx))

        # --- Call-by-Call section ---
        if ctx.call_audits:
            parts.append(cls._build_calls_section(ctx))

        # --- Verification section ---
        if ctx.verification_audit is not None:
            parts.append(cls._build_verification_section(ctx))

        parts.append("</body>")
        parts.append("</html>")
        return "\n".join(parts)

    @classmethod
    def write_report(cls, ctx: AuditContext, path: Path) -> None:
        """Write HTML audit report to file."""
        html_content = cls.generate_html(ctx)
        path.write_text(html_content, encoding="utf-8")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _css() -> str:
        """Return embedded CSS for the report."""
        return (
            "body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; "
            "max-width: 1200px; margin: 0 auto; padding: 20px; background: #f8f9fa; color: #333; }\n"
            ".header { background: #2c3e50; color: white; padding: 20px; "
            "border-radius: 8px; margin-bottom: 20px; }\n"
            ".header h1 { margin: 0 0 8px 0; }\n"
            ".header-meta { display: flex; flex-wrap: wrap; gap: 16px; font-size: 0.9em; }\n"
            ".section { background: white; border: 1px solid #dee2e6; "
            "border-radius: 8px; margin-bottom: 16px; padding: 16px; }\n"
            "details { margin-bottom: 8px; }\n"
            "summary { cursor: pointer; font-weight: 600; padding: 8px; "
            "background: #f1f3f5; border-radius: 4px; }\n"
            "table { width: 100%; border-collapse: collapse; margin-top: 8px; }\n"
            "th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid #dee2e6; }\n"
            "th { background: #f8f9fa; font-weight: 600; }\n"
            ".confidence-high { color: #2d6a4f; background: #d8f3dc; }\n"
            ".confidence-medium { color: #9c6500; background: #fff3cd; }\n"
            ".confidence-low { color: #842029; background: #f8d7da; }\n"
            ".pass { color: #2d6a4f; } .fail { color: #842029; }\n"
            ".flag { display: inline-block; padding: 2px 8px; border-radius: 12px; "
            "font-size: 0.85em; background: #fff3cd; color: #9c6500; margin: 2px; }\n"
            ".source-excerpt { background: #f8f9fa; padding: 8px; "
            "border-left: 3px solid #6c757d; font-family: monospace; "
            "font-size: 0.9em; white-space: pre-wrap; }\n"
            ".transformation { padding: 4px 0; border-bottom: 1px solid #f1f3f5; }\n"
            ".side-by-side { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }\n"
            ".side-by-side pre { background: #f8f9fa; padding: 12px; border-radius: 4px; "
            "white-space: pre-wrap; overflow-x: auto; font-size: 0.85em; }\n"
            ".confidence-bar { height: 8px; border-radius: 4px; margin-top: 4px; }\n"
        )

    @classmethod
    def _build_header(cls, ctx: AuditContext) -> str:
        """Build the header section."""
        rm = ctx.run_metadata
        parts: list[str] = []
        parts.append("<div class='header'>")
        parts.append("<h1>Audit Report</h1>")
        parts.append("<div class='header-meta'>")
        parts.append(f"<span>Source: <strong>{html.escape(rm.source_pdf)}</strong></span>")
        parts.append(f"<span>Timestamp: {html.escape(str(rm.timestamp_utc))}</span>")
        parts.append(f"<span>Parser: {html.escape(rm.parser_version)}</span>")
        parts.append(
            f"<span>LLM: {html.escape(rm.llm_provider)} / {html.escape(rm.llm_model)}</span>"
        )
        if rm.cache_enabled:
            parts.append("<span>Cache: ENABLED</span>")
        parts.append("</div>")

        # Overall confidence bar (from extraction if available)
        if ctx.extraction_record and ctx.extraction_record.llm_confidence is not None:
            conf = ctx.extraction_record.llm_confidence
            css_cls = cls._confidence_class(conf)
            pct = int(conf * 100)
            parts.append(
                f"<div style='margin-top:12px'>Extraction Confidence: "
                f"<span class='{css_cls}' style='padding:2px 8px;border-radius:4px'>"
                f"{pct}%</span></div>"
            )

        parts.append("</div>")
        return "\n".join(parts)

    @classmethod
    def _build_extraction_section(cls, ctx: AuditContext) -> str:
        """Build the LLM extraction details section."""
        er = ctx.extraction_record
        if er is None:
            return ""
        parts: list[str] = []
        parts.append("<div class='section'>")
        parts.append("<details>")
        parts.append("<summary>LLM Extraction</summary>")
        parts.append("<div class='side-by-side'>")
        parts.append("<div>")
        parts.append("<h4>Raw LLM Response</h4>")
        parts.append(f"<pre>{html.escape(er.raw_llm_response)}</pre>")
        parts.append("</div>")
        parts.append("<div>")
        parts.append("<h4>Normalized Text</h4>")
        parts.append(f"<pre>{html.escape(er.normalized_text)}</pre>")
        parts.append("</div>")
        parts.append("</div>")

        # Confidence signals table
        if er.confidence_signals:
            parts.append("<h4>Confidence Signals</h4>")
            parts.append("<table>")
            parts.append("<tr><th>Signal</th><th>Result</th></tr>")
            for signal_name, signal_val in er.confidence_signals.items():
                css = "pass" if signal_val else "fail"
                label = "PASS" if signal_val else "FAIL"
                parts.append(
                    f"<tr><td>{html.escape(signal_name)}</td><td class='{css}'>{label}</td></tr>"
                )
            parts.append("</table>")

        parts.append("</details>")
        parts.append("</div>")
        return "\n".join(parts)

    @classmethod
    def _build_calls_section(cls, ctx: AuditContext) -> str:
        """Build the call-by-call audit section."""
        parts: list[str] = []
        parts.append("<div class='section'>")
        parts.append("<h2>Call-by-Call Audit</h2>")
        parts.append("<table>")
        parts.append(
            "<tr><th>Course</th><th>Source Excerpt</th><th>Parsed Values</th>"
            "<th>Confidence</th><th>Flags</th></tr>"
        )
        for ca in ctx.call_audits:
            # Truncate source excerpt for the summary row
            excerpt = ca.source_excerpt
            truncated = excerpt[:80] + "..." if len(excerpt) > 80 else excerpt

            # Gather parsed values from decisions
            parsed_vals = ", ".join(f"{d.field}={html.escape(d.value)}" for d in ca.decisions)

            # Average confidence from decisions
            if ca.decisions:
                avg_conf = sum(d.confidence for d in ca.decisions) / len(ca.decisions)
                conf_cls = cls._confidence_class(avg_conf)
                conf_str = f"{avg_conf:.0%}"
            else:
                conf_cls = ""
                conf_str = "N/A"

            # Flags
            flags_html = " ".join(f"<span class='flag'>{html.escape(f)}</span>" for f in ca.flags)

            parts.append("<tr>")
            parts.append(f"<td>{ca.course}</td>")
            parts.append(f"<td>{html.escape(truncated)}</td>")
            parts.append(f"<td>{parsed_vals or '&mdash;'}</td>")
            parts.append(f"<td class='{conf_cls}'>{conf_str}</td>")
            parts.append(f"<td>{flags_html or '&mdash;'}</td>")
            parts.append("</tr>")

            # Expandable detail row
            if ca.transformations or ca.decisions:
                parts.append("<tr><td colspan='5'>")
                parts.append(f"<details><summary>Course {ca.course} details</summary>")
                parts.append(f"<div class='source-excerpt'>{html.escape(ca.source_excerpt)}</div>")

                if ca.transformations:
                    parts.append("<h4>Transformations</h4>")
                    for t in ca.transformations:
                        parts.append("<div class='transformation'>")
                        parts.append(
                            f"<strong>{html.escape(t.step)}</strong>: "
                            f"{html.escape(t.input)} &rarr; {html.escape(t.output)}"
                        )
                        if t.rule:
                            parts.append(f" <em>(rule: {html.escape(t.rule)})</em>")
                        parts.append("</div>")

                if ca.decisions:
                    parts.append("<h4>Decisions</h4>")
                    parts.append("<table>")
                    parts.append(
                        "<tr><th>Field</th><th>Value</th><th>Reason</th>"
                        "<th>Confidence</th><th>Alternatives</th></tr>"
                    )
                    for d in ca.decisions:
                        d_cls = cls._confidence_class(d.confidence)
                        alts = ", ".join(html.escape(a) for a in d.alternatives) or "&mdash;"
                        parts.append(
                            f"<tr><td>{html.escape(d.field)}</td>"
                            f"<td>{html.escape(d.value)}</td>"
                            f"<td>{html.escape(d.reason)}</td>"
                            f"<td class='{d_cls}'>{d.confidence:.0%}</td>"
                            f"<td>{alts}</td></tr>"
                        )
                    parts.append("</table>")

                parts.append("</details>")
                parts.append("</td></tr>")

        parts.append("</table>")
        parts.append("</div>")
        return "\n".join(parts)

    @classmethod
    def _build_verification_section(cls, ctx: AuditContext) -> str:
        """Build the verification audit section."""
        va = ctx.verification_audit
        if va is None:
            return ""
        parts: list[str] = []
        parts.append("<div class='section'>")
        parts.append("<details>")
        parts.append("<summary>Verification</summary>")

        # Checks table
        if va.checks:
            parts.append("<table>")
            parts.append("<tr><th>Check</th><th>Result</th><th>Detail</th></tr>")
            for check in va.checks:
                css = "pass" if check.passed else "fail"
                label = "PASS" if check.passed else "FAIL"
                parts.append(
                    f"<tr><td>{html.escape(check.name)}</td>"
                    f"<td class='{css}'>{label}</td>"
                    f"<td>{html.escape(check.detail)}</td></tr>"
                )
            parts.append("</table>")

        # Closure summary
        if va.closure_summary:
            parts.append("<h4>Closure Summary</h4>")
            parts.append("<table>")
            parts.append("<tr><th>Metric</th><th>Value</th></tr>")
            for key, value in va.closure_summary.items():
                parts.append(
                    f"<tr><td>{html.escape(str(key))}</td><td>{html.escape(str(value))}</td></tr>"
                )
            parts.append("</table>")

        parts.append("</details>")
        parts.append("</div>")
        return "\n".join(parts)
