"""Deterministic, offline HTML for a validated source ledger and its results.

The browser operates on a separate scenario copy. Its small straight-course
calculator is advisory and never changes canonical findings or export status.
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
from pathlib import Path

from mp_models.closure import CheckResult
from mp_models.dashboard import DashboardBundle, PreparedDashboard
from mp_verify.dashboard import validate_prepared_dashboard

_ASSETS = Path(__file__).with_name("dashboard_assets")


def renderer_fingerprint() -> str:
    """SHA-256 of labelled renderer Python, CSS and JavaScript source bytes.

    This code identity is separate from the prepared presentation data hash.
    No timestamps, absolute paths or cache-hit metadata contribute to it.
    """
    digest = hashlib.sha256()
    for name, path in (
        ("dashboard_html.py", Path(__file__)),
        ("dashboard.css", _ASSETS / "dashboard.css"),
        ("dashboard.js", _ASSETS / "dashboard.js"),
    ):
        digest.update(name.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def _escape(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _number(value: float | None, places: int = 3) -> str:
    return "Unavailable" if value is None else f"{value:,.{places}f}"


def _metric(label: str, value: str) -> str:
    return (
        f'<div class="metric"><strong>{_escape(value)}</strong><span>{_escape(label)}</span></div>'
    )


def _page_label(bundle: DashboardBundle, page_id: str) -> str:
    page = next(p for p in bundle.pages if p.id == page_id)
    document = next(d for d in bundle.documents if d.id == page.document_id)
    return f"{document.label} · page {page.number} · {page.label or page.id}"


def _page_button(bundle: DashboardBundle, page_id: str) -> str:
    return f'<button type="button" data-page-id="{_escape(page_id)}">{_escape(_page_label(bundle, page_id))}</button>'


def _copy_button(target: str, label: str) -> str:
    return f'<button type="button" data-copy-target="{_escape(target)}">{_escape(label)}</button> <span class="copy-status" role="status"></span>'


def _check_outcomes(checks: tuple[CheckResult, ...], method: str) -> str:
    if not checks:
        reason = (
            "Canonical checks were not run by relative analysis. Local geometry does not change the canonical engine status."
            if method == "relative"
            else "Canonical check outcomes are unavailable; this is not a passing check result."
        )
        return f"<h4>Canonical check outcomes</h4><p>{_escape(reason)}</p>"
    rows = "".join(
        f'<tr><td>{_escape(check.name)}</td><td data-check-status="{_escape(check.status)}">{_escape(check.status)}</td><td>{_escape(check.reason)}</td><td>{_escape(check.detail)}</td></tr>'
        for check in checks
    )
    return (
        '<h4>Canonical check outcomes</h4><div class="table-wrap" role="region" '
        'aria-label="Canonical verification check outcomes" tabindex="0"><table><thead>'
        "<tr><th>Check</th><th>Status</th><th>Reason</th><th>Detail</th></tr>"
        f"</thead><tbody>{rows}</tbody></table></div>"
    )


def _findings(prepared: PreparedDashboard) -> str:
    bundle = prepared.bundle
    parts = []
    for occurrence in bundle.occurrences:
        results = [r for r in prepared.calculations if r.occurrence_id == occurrence.id]
        parts.append(
            f'<article class="card" data-record-occurrence="{_escape(occurrence.id)}"><h3>{_escape(occurrence.version_label)}</h3><p class="muted">{_escape(occurrence.id)} · {_escape(next(p.label for p in bundle.parcels if p.id == occurrence.parcel_id))}</p>'
        )
        if not results:
            parts.append(
                '<p class="warning">Unresolved: no calculation supplied for this occurrence.</p>'
            )
        for result in results:
            calculation = next(c for c in bundle.calculations if c.id == result.id)
            conditional = not result.source_review_complete or occurrence.reading_status != "read"
            status = (
                "Conditional / source review incomplete"
                if conditional
                else "Unresolved"
                if result.misclosure_ft is None
                else "Closes geometrically"
                if result.misclosure_ft < 0.01
                else "Does not close"
            )
            precision = (
                "Unavailable / unbounded"
                if result.precision_denominator is None
                else f"1:{result.precision_denominator:,.0f}"
            )
            parts.append(
                f'<div data-record-result="{_escape(result.id)}"><span class="badge">{_escape(status)}</span><p>{_escape(result.method)} · {_escape(calculation.frame.name)} · {_escape(calculation.frame.basis)}</p><div class="metrics">'
            )
            for label, value in (
                ("Record misclosure (ft)", _number(result.misclosure_ft)),
                ("Record precision", precision),
                ("Angle sum (degrees)", _number(result.stated_angle_sum_deg)),
                ("Expected sum (degrees)", _number(result.expected_angle_sum_deg)),
                ("Provisional area (sq ft)", _number(result.area_sq_ft)),
            ):
                parts.append(_metric(label, value))
            parts.append(
                f"</div><p>Canonical engine: <strong>{_escape(result.engine_status)}</strong>. Source review: <strong>{'complete' if result.source_review_complete else 'incomplete'}</strong>. Geometry: {_escape(result.geometry_status)}.</p>"
            )
            parts.append(_check_outcomes(result.checks, result.method))
            if result.warnings:
                parts.append(
                    "<ul>" + "".join(f"<li>{_escape(w)}</li>" for w in result.warnings) + "</ul>"
                )
            parts.append("</div>")
        parts.append(
            f'<p>Reading: {_escape(occurrence.reading_status)} · Review attestation: {_escape(occurrence.source_review_status)}. {_escape(occurrence.notes)}</p><div class="controls">'
        )
        parts.extend(_page_button(bundle, page_id) for page_id in occurrence.page_ids)
        parts.append("</div></article>")
    return "".join(parts)


def _evidence(bundle: DashboardBundle) -> str:
    if not bundle.evidence:
        return '<p class="warning">No evidence crops supplied. Reinspect uncertain figures in the indexed source pages; this dashboard does not invent crops.</p>'
    parts = []
    for item in bundle.evidence:
        image = (
            f'<img class="evidence-image" src="{_escape(item.image)}" alt="{_escape(item.label)}">'
            if item.image
            else '<div class="placeholder">Evidence image unavailable</div>'
        )
        reading = next((c for c in bundle.calls if c.id == item.call_id), None)
        status = (
            f"{reading.reading_status}: {reading.reading_note}"
            if reading
            else "See occurrence reading status; no individual call is linked."
        )
        bounds = (
            f"Crop pixels (x, y, width, height): {item.bounds_px}"
            if item.bounds_px
            else "Crop coordinates unavailable."
        )
        parts.append(
            f'<article class="card"><h3>{_escape(item.label)}</h3>{image}<p>{_escape(item.occurrence_id)} · {_escape(item.call_id or "Occurrence evidence")}</p><p>{_escape(status)}</p><p>{_escape(item.notes)}</p><p class="muted">{_escape(bounds)}</p>{_page_button(bundle, item.page_id)}</article>'
        )
    return "".join(parts)


def _courses_csv(bundle: DashboardBundle, occurrence_id: str) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        [
            "course",
            "direction_as_recorded",
            "angle_as_recorded",
            "distance_as_recorded",
            "distance_ft",
            "along",
            "to",
            "source_page",
            "reading_status",
        ]
    )
    writer.writerow(["POB", "See preserved source transcript", "", "", "", "", "", "", ""])
    for item in bundle.calls:
        if item.occurrence_id == occurrence_id:
            call = item.call
            writer.writerow(
                [
                    call.course if call else item.id,
                    call.direction_text if call else "",
                    item.stated_angle_text or "",
                    item.distance_text or "",
                    call.distance_ft if call else "",
                    call.along if call else "",
                    call.to if call else "",
                    item.page_id,
                    item.reading_status,
                ]
            )
    return output.getvalue()


def _records(bundle: DashboardBundle) -> str:
    parts = []
    for occurrence in bundle.occurrences:
        transcript_id, csv_id = f"transcript-{occurrence.id}", f"courses-{occurrence.id}"
        parts.append(
            f'<details class="panel" open><summary>{_escape(occurrence.version_label)} · {_escape(occurrence.id)}</summary><p>{_escape(occurrence.notes)}</p><div><pre id="{transcript_id}">{_escape(occurrence.transcript)}</pre>{_copy_button(transcript_id, "Copy untouched transcript")}</div><h3>Extracted courses</h3><p class="muted">Source-linked review table in feet; not the engine’s verified 21-column CSV. POB location is retained in the transcript.</p><div class="table-wrap" role="region" aria-label="Recorded courses" tabindex="0"><table><thead><tr><th>Course</th><th>Direction / source quote</th><th>Angle as written / type</th><th>Distance as written / feet</th><th>Along / to</th><th>Reading / source</th></tr></thead><tbody>'
        )
        for item in bundle.calls:
            if item.occurrence_id != occurrence.id:
                continue
            call = item.call
            parts.append(
                f'<tr class="{"uncertain" if item.reading_status != "certain" else ""}"><td>{_escape(call.course if call else item.id)}</td><td>{_escape(call.direction_text if call else "Unknown")}<br>{_escape(item.quote)}</td><td>{_escape(item.stated_angle_text or "Not stated")}<br>{_escape(item.stated_angle_type or "Unknown")}</td><td>{_escape(item.distance_text or "Not transcribed separately")}<br>{_escape(_number(call.distance_ft if call else None))}</td><td>{_escape(call.along if call else "")}<br>{_escape(call.to if call else "")}</td><td>{_escape(item.reading_status)} · {_escape(item.reading_note)}<br>{_page_button(bundle, item.page_id)}</td></tr>'
            )
        parts.append(
            f'</tbody></table></div><div><pre id="{csv_id}" hidden>{_escape(_courses_csv(bundle, occurrence.id))}</pre>{_copy_button(csv_id, "Copy review courses as CSV")}</div></details>'
        )
    return "".join(parts)


def _sources(bundle: DashboardBundle) -> str:
    parts = []
    for document in bundle.documents:
        pages = [p for p in bundle.pages if p.document_id == document.id]
        missing = sorted(
            set(range(1, document.expected_page_count + 1)) - {p.number for p in pages}
        )
        parts.append(
            f'<article class="panel"><h3>{_escape(document.label)}</h3><p>{_escape(document.source_name)} · {_escape(document.id)} · {len(pages)} / {document.expected_page_count} pages indexed</p>'
        )
        if missing:
            parts.append(
                f'<p class="warning">Expected pages not supplied: {_escape(", ".join(map(str, missing)))}</p>'
            )
        parts.append('<div class="gallery">')
        for page in pages:
            image = (
                f'<img class="thumb" src="{_escape(page.image)}" alt="{_escape(_page_label(bundle, page.id))}">'
                if page.image
                else '<div class="placeholder">Source image unavailable</div>'
            )
            description_page = any(page.id in o.page_ids for o in bundle.occurrences)
            parts.append(
                f'<div class="card {"uncertain" if description_page else ""}">{image}<p>{_escape(page.label or page.id)} · page {page.number}</p><p>{_escape(page.reading_status)} · {_escape(page.notes)}</p>{_page_button(bundle, page.id)}</div>'
            )
        parts.append("</div></article>")
    return "".join(parts)


def render_dashboard(prepared: PreparedDashboard) -> str:
    """Render a prepared dashboard reproducibly without reading external assets.

    Fresh validation rejects invalid references, unsafe image URIs, stale stage
    hashes and results that disagree with the deterministic calculation stage.
    """
    prepared = validate_prepared_dashboard(prepared)
    bundle = prepared.bundle
    data = json.dumps(
        prepared.model_dump(mode="json", exclude={"manifest": {"cache_reused"}}),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    for character, replacement in (
        ("&", "\\u0026"),
        ("<", "\\u003c"),
        (">", "\\u003e"),
        ("\u2028", "\\u2028"),
        ("\u2029", "\\u2029"),
    ):
        data = data.replace(character, replacement)
    css = (_ASSETS / "dashboard.css").read_text(encoding="utf-8")
    script = (_ASSETS / "dashboard.js").read_text(encoding="utf-8")
    methods = "".join(f"<li>{_escape(note)}</li>" for note in bundle.presentation.method_notes)
    for calculation in bundle.calculations:
        methods += f"<li>{_escape(calculation.id)}: {_escape(calculation.method)}; {_escape(calculation.frame.name)}; {_escape(calculation.frame.basis)}. Assumptions: {_escape('; '.join(calculation.assumptions) or 'None supplied')}.</li>"
    hashes = "".join(
        f'<p class="hash"><strong>{_escape(name.replace("_", " "))}</strong><br>{_escape(getattr(prepared.manifest, name))}</p>'
        for name in (
            "source_review_hash",
            "calculation_input_hash",
            "calculation_output_hash",
            "presentation_hash",
        )
    )
    for document in bundle.documents:
        hashes += f'<p class="hash">Source {_escape(document.id)} SHA-256: {_escape(document.sha256 or "Unknown; source identity not cryptographically confirmed")}</p>'
    hashes += f'<p class="hash"><strong>Renderer implementation SHA-256</strong><br>{renderer_fingerprint()}</p>'
    parcel_options = "".join(
        f'<option value="{_escape(p.id)}">{_escape(p.label)}</option>' for p in bundle.parcels
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><title>{_escape(bundle.title)}</title><style>{css}</style></head>
<body><header><div class="eyebrow">Metes &amp; bounds · record review</div><h1>{_escape(bundle.title)}</h1><p>{_escape(bundle.presentation.subtitle)}</p><p class="muted">Immutable record findings, source evidence, and a separate advisory scenario workbench.</p><nav aria-label="Dashboard sections"><a href="#findings">Findings</a><a href="#evidence">Evidence</a><a href="#workbench">Workbench</a><a href="#records">As recorded</a><a href="#sources">Source copies</a><a href="#method">Method &amp; limits</a></nav></header>
<main><noscript><p class="warning">JavaScript is disabled. Record findings, transcripts and page images remain visible. Workbench and full-size viewer require JavaScript.</p></noscript>
<section id="findings"><h2>1. Record findings</h2><p>Each occurrence retains its own source values. Findings and canonical engine status stay fixed during workbench edits. Geometric closure does not resolve an uncertain reading.</p><div class="cards">{_findings(prepared)}</div></section>
<section id="evidence"><h2>2. Record evidence</h2><div class="cards">{_evidence(bundle)}</div></section>
<section id="workbench"><h2>3. Scenario workbench</h2><div class="panel"><div class="controls"><label>Parcel<select id="parcel-select"><option value="all">All parcels</option>{parcel_options}</select></label><label>Occurrence / calculation<select id="calculation-select"></select></label><label>Scenario<select id="scenario-select"></select></label><button type="button" id="reset-record">Reset to record</button></div><p id="scenario-rationale" class="muted"></p><p class="warning">Browser edits are hypothetical. They cannot verify a deed or authorize a verified export. Relative calculations permit distance edits; angular interpretations remain the explicit sourced constraints. Absolute bearings accept decimal azimuth or quadrant DMS. No bearings are inferred from direction words.</p><div class="work-grid"><svg id="plot" class="plot" viewBox="0 0 420 380" role="img" aria-label="Scenario traverse with numbered courses, POB and dashed closure gap"></svg><div><h3 id="scenario-status" role="status" aria-live="polite">Loading advisory scenario…</h3><div id="scenario-metrics" class="metrics"></div><p class="muted">Gap vector is endpoint minus POB in the declared frame. Area includes an implicit endpoint-to-start segment and is provisional for an open traverse.</p></div></div><div class="table-wrap" role="region" aria-label="Editable scenario call sheet" tabindex="0"><table><thead><tr><th>Course</th><th>Source quote / direction</th><th>Distance (ft)</th><th>Recorded azimuth (degrees) / basis</th><th>Stated angle</th><th>Derived heading</th><th>ΔX / ΔY (ft)</th></tr></thead><tbody id="call-body"></tbody></table></div><p class="muted">Amber fields differ from the selected record. Uncertain source readings retain their warning stripe. Direction-word agreement is not evaluated as a measured bearing.</p><details><summary>Closing angle and shared corners</summary><p>Stated closing angles remain in the sourced constraints and transcripts. The heading-based closing angle is derived; it is not a replacement reading. A missing closing angle leaves the stated angle sum unavailable.</p><div id="closing-angle-detail"></div><p>Shared-corner comparison is unavailable: this bundle does not declare a supported cross-parcel alignment. Independent arbitrary local frames are not overlaid or silently aligned.</p></details></div></section>
<section id="records"><h2>4. Metes and bounds as recorded</h2><p>Untouched transcripts preserve the supplied wording and whitespace. Uncertain course readings are marked in the course tables; no alternate figure replaces the transcript.</p>{_records(bundle)}</section>
<section id="sources"><h2>5. Source copies</h2><p>Every indexed page appears below, including unavailable images and unread pages. Description pages have an outlined edge. Missing expected pages are listed explicitly; completeness is a separate source-review claim.</p>{_sources(bundle)}</section>
<section id="method"><h2>6. Method, limits, and sources</h2><div class="panel"><p>Bearings use degrees clockwise from North. Local-angle calculations use an explicitly declared arbitrary frame, interior/exterior angle convention, and orientation. Straight-course displacement is distance × sin(heading) in X and distance × cos(heading) in Y. The browser independently propagates explicit constraints, rejects unresolved or contradictory relations, and never adjusts values to close a boundary.</p><p>Browser support is limited to straight boundaries. Curves, exceptions, meanders, indefinite calls and non-tangent geometry require the canonical engine. Source uncertainty remains independent of geometric closure. Precision is perimeter divided by gap; an unavailable denominator is not proof of infinite precision for a nonzero gap. A matching angle sum does not prove the angles are correct.</p><p>Only the canonical verifier’s full checks and its &lt;0.01 ft threshold govern verified export. Browser scenarios have no verified-export control. This dashboard is not a survey, title opinion, or boundary certification. Image presence is not evidence that a person inspected the page. Review sensitive source pages before sharing.</p><ul>{methods}</ul><h3>Stage and source identities</h3><p>Source review: {"complete" if prepared.manifest.source_review_complete else "incomplete"} · calculator {_escape(prepared.manifest.calculator_version)} · schema {_escape(bundle.schema_version)}</p>{hashes}</div></section></main>
<footer>Offline review artifact · self-contained assets · no external runtime or fonts</footer>
<dialog id="source-viewer" aria-labelledby="viewer-label"><div class="viewer-toolbar"><strong id="viewer-label"></strong><button type="button" id="viewer-prev">Previous</button><button type="button" id="viewer-next">Next</button><a id="open-image" target="_blank" rel="noopener noreferrer">Open image</a><button type="button" id="viewer-close">Close</button></div><img id="viewer-image" alt=""><p id="viewer-missing" class="placeholder">This source page image is unavailable. Its ledger entry is preserved.</p><p class="muted">Use Left / Right arrow keys to change pages; Escape to close.</p></dialog>
<script type="application/json" id="dashboard-data">{data}</script><script>{script}</script></body></html>"""
