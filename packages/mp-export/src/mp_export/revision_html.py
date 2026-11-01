"""Offline revision evidence with existing isolated line/arc plot rendering."""

from __future__ import annotations

import base64
import html
import json
from typing import Any

from mp_models.dashboard import DashboardBundle
from mp_models.revisions import DashboardRevision, PreparedRevision, RevisionGeometry

from .plot_html import render_plot


def _escape(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)


def _geometry(items: tuple[RevisionGeometry, ...], view: str) -> str:
    sections = []
    for item in items:
        frame = render_plot(item.plot)
        sections.append(
            f"<article><h3>{_escape(item.calculation_id)} · revision {_escape(item.revision_id)}</h3>"
            f"<p>Geometry SHA-256: {_escape(item.plot.geometry.geometry_hash)}</p>"
            f'<iframe data-view="{view}" data-revision-id="{_escape(item.revision_id)}" '
            f'title="{_escape(view)} plot: {_escape(item.calculation_id)} from revision {_escape(item.revision_id)}" '
            f'sandbox="allow-scripts" srcdoc="{_escape(frame)}"></iframe></article>'
        )
    return "".join(sections)


def _selected(record: Any) -> str:
    call = record.call
    if call is None:
        return "<p>No parsed call: annotation, removed addition, or unresolved draft.</p>"
    bearing = (
        f"{call.bearing_azimuth_deg_from_north:g}° azimuth"
        if call.bearing_azimuth_deg_from_north is not None
        else "Unknown recorded bearing"
    )
    values = [
        f"Course {call.course}: {call.direction_text}",
        bearing,
        (
            f"Distance: {call.distance_ft:g} ft"
            if call.distance_ft is not None
            else "Distance: not determined"
        ),
    ]
    for label, field in [
        ("Radius (ft)", "radius_ft"),
        ("Sweep (degrees)", "delta_deg"),
        ("Arc (ft)", "arc_length_ft"),
        ("Chord (ft)", "chord_length_ft"),
        ("Chord bearing", "chord_bearing"),
    ]:
        value = getattr(call, field)
        if value is not None:
            values.append(f"{label}: {value}")
    if call.curve_dir:
        values.append("Curve direction: " + call.curve_dir)
    if call.notes:
        values.append(call.notes)
    return (
        "<p>"
        + "<br>".join(_escape(v) for v in values)
        + "</p><details><summary>Parsed fields</summary><pre>"
        + _escape(_json(call.model_dump(mode="json")))
        + "</pre></details>"
    )


def _corridors(prepared: PreparedRevision) -> str:
    if not prepared.revision.corridors:
        return ""
    results = {item.id: item for item in prepared.corridor_results}
    sections = []
    for entry in prepared.revision.corridors:
        item = results.get(entry.id)
        content = "<p>Explicitly removed; original definition retained.</p>"
        if entry.action != "remove":
            content = '<p class="warning">Corridor geometry unavailable for this draft.</p>'
            if item is not None:
                content += (
                    "<ul>"
                    + "".join(f"<li>{_escape(reason)}</li>" for reason in item.reasons)
                    + "</ul>"
                )
                result = item.result
                if item.state == "computed" and result is not None:
                    request = result.request
                    rows = "".join(
                        f"<tr><th>{_escape(row.id)}</th><td>{_escape(row.rule)}</td>"
                        f"<td>{_escape(row.start.call_id)}:{row.start.fraction:g} → {_escape(row.end.call_id)}:{row.end.fraction:g}</td>"
                        f"<td>{row.left_start:g} → {row.left_end:g}</td><td>{row.right_start:g} → {row.right_end:g}</td></tr>"
                        for row in request.widths
                    )
                    content = (
                        f"<p>Widths in {_escape(request.width_unit)}, relative to forward centerline. "
                        f"Join: {_escape(request.join)}. Cap: {_escape(request.cap)}.</p>"
                        '<div class="table-wrap"><table><thead><tr><th>Interval</th><th>Rule</th><th>Stations</th><th>Left start → end</th><th>Right start → end</th></tr></thead>'
                        f"<tbody>{rows}</tbody></table></div>"
                    )
                    if result.error:
                        content += (
                            f"<p>Declared construction error: {result.error.total_bound:g} "
                            f"{_escape(result.error.unit)}; requested maximum {result.error.requested_max_error:g}.</p>"
                        )
                    content += (
                        "<p>Centerline and boundary are separate local views. Boundary origin in "
                        f"the centerline frame: {_escape(result.boundary_origin_in_centerline_frame)}. "
                        "These views do not establish map placement or canonical verification.</p>"
                    )
                    for label, plot in [
                        ("corridor-centerline", result.centerline),
                        ("corridor-boundary", result.boundary),
                    ]:
                        if plot is not None:
                            content += _geometry(
                                (
                                    RevisionGeometry(
                                        revision_id=prepared.revision.id,
                                        calculation_id=plot.request.calculation_id,
                                        plot=plot,
                                    ),
                                ),
                                label,
                            )
        sections.append(
            f'<article data-revision-corridor="{_escape(entry.id)}"><h3>{_escape(entry.id)}</h3>{content}'
            f"<details><summary>Exact saved corridor input</summary><pre>{_escape(entry.raw_request_json)}</pre></details></article>"
        )
    return (
        '<section id="saved-corridors"><h2>Saved corridor definitions</h2>'
        + "".join(sections)
        + "</section>"
    )


def render_revision(
    bundle: DashboardBundle, prepared: PreparedRevision, *, draft_bytes: bytes | None = None
) -> str:
    """Render replayed evidence; no edits, source reading or browser geometry engine."""
    draft = (
        draft_bytes
        if draft_bytes is not None
        else (_json(prepared.revision.model_dump(mode="json")) + "\n").encode()
    )
    if DashboardRevision.model_validate_json(draft) != prepared.revision:
        raise ValueError("Download draft does not match the selected revision")
    encoded = base64.b64encode(draft).decode()
    rows = []
    page_ids = set()
    for record in prepared.prepared_calls:
        if record.page_id:
            page_ids.add(record.page_id)
        refs = "".join(
            f'<li><a href="#page-{_escape(ref.page_id)}">{_escape(ref.page_id)}</a>: {_escape(ref.quote)}</li>'
            for ref in record.source_refs
        )
        source = (
            f'<a href="#page-{_escape(record.page_id)}">{_escape(record.page_id)}</a>'
            if record.page_id
            else "No source page supplied"
        )
        original = (
            _json(record.original_source)
            if record.original_source is not None
            else "No original source record: added input"
        )
        selected = _selected(record)
        rows.append(
            f'<tr data-revision-call="{_escape(record.id)}"><th scope="row">{_escape(record.id)}<br>'
            f"{_escape(record.occurrence_id)} · {_escape(record.tract_id)}<br>{_escape(record.document_id)}</th>"
            f"<td>{_escape(record.source_status)} · {_escape(record.role)} · {'removed' if record.removed else 'retained'}<br>{source}"
            f"<blockquote>{_escape(record.quote)}</blockquote><ul>{refs}</ul></td>"
            f"<td><details><summary>Original source</summary><pre>{_escape(original)}</pre></details>"
            f"<h3>Selected call</h3>{selected}"
            f"<details><summary>Exact raw_input</summary><pre>{_escape(_json(record.raw_input))}</pre></details></td></tr>"
        )
    pages = []
    documents = {d.id: d for d in bundle.documents}
    for page in bundle.pages:
        if page.id not in page_ids:
            continue
        document = documents[page.document_id]
        image = (
            f'<img src="{_escape(page.image)}" alt="{_escape(document.label)}, source page {page.number}">'
            if page.image
            else "<p>Source page image unavailable; reference preserved.</p>"
        )
        pages.append(
            f'<details id="page-{_escape(page.id)}"><summary>{_escape(document.label)} · page {page.number} · {_escape(page.id)}</summary><p>Recorded reading status: {_escape(page.reading_status)}. {_escape(page.notes)}</p>{image}</details>'
        )
    errors = "".join(
        f"<li>{_escape(error.call_id or 'revision')} · {_escape(error.field)}: {_escape(error.message)}</li>"
        for error in prepared.errors
    )
    current = (
        _geometry(prepared.current_geometry, "current")
        if prepared.current_geometry
        else '<p class="warning">Current geometry unavailable. Resolve this draft before using or exporting current geometry.</p>'
    )
    fallback = (
        _geometry(prepared.last_valid_geometry, "last-valid")
        if prepared.last_valid_geometry
        else "<p>No separately retained last-valid geometry is available.</p>"
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; frame-src 'self' about:; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>{_escape(prepared.revision.label)} · revision review</title>
<style>body{{font:16px/1.5 system-ui;max-width:90rem;margin:2rem auto;padding:0 1rem;color:#18352e;background:#f6f8f6}}h1,h2,h3{{line-height:1.2}}article,section{{margin:1rem 0;padding:1rem;background:white;border:1px solid #cad9d1;border-radius:.5rem}}iframe{{display:block;width:100%;height:58rem;border:1px solid #b6c7bd;background:white}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;margin:.5rem 0}}table{{border-collapse:collapse;width:100%}}td,th{{vertical-align:top;text-align:left;border:1px solid #cad9d1;padding:.7rem}}.table-wrap{{overflow:auto}}blockquote{{margin:.7rem 0;white-space:pre-wrap}}img{{max-width:100%;height:auto}}.warning{{border-left:4px solid #9b5b10;padding:.7rem;background:#fff2da}}a{{color:#145c48}}details{{margin:.7rem 0}}summary{{cursor:pointer}}@media(max-width:700px){{td,th{{min-width:12rem}}iframe{{height:52rem}}}}</style></head><body><main>
<h1>{_escape(prepared.revision.label)}</h1><p>Revision {_escape(prepared.revision.id)} · generation {prepared.revision.generation} · {_escape(prepared.state)} · {_escape(prepared.revision.kind)}</p>
<p class="warning">Advisory revision review. Original source remains unchanged. Hypothetical alternatives and supplied corrections do not establish source review, canonical verification or verified-export eligibility. Last-valid geometry is separately labeled and never substitutes for the current draft.</p>
<p><a download="revision.json" href="data:application/json;base64,{encoded}">Download draft</a></p><p>Baseline: {_escape(prepared.revision.baseline.id)} · {_escape(prepared.revision.baseline.bundle_sha256)}</p>
<p>Rationale: {_escape(prepared.revision.rationale)}</p><section><h2>Current draft errors</h2>{"<ul>" + errors + "</ul>" if errors else "<p>No input or geometry errors in this selected revision. This is not canonical verification.</p>"}</section>
<section id="current-geometry"><h2>Current geometry · {_escape(prepared.revision.id)}</h2>{current}</section>
<section id="last-valid-geometry"><h2>Last valid geometry · separate prior revision</h2><p>Retained for comparison only; it is not the result of unresolved current inputs.</p>{fallback}</section>
{_corridors(prepared)}
<section><h2>Source-backed call inventory</h2><p>Removed, reference and intentionally omitted entries remain evidence. Participation is explicit; source quotes and original payloads remain separate from selected parsed values and exact raw input.</p><div class="table-wrap" role="region" aria-label="Revision call inventory" tabindex="0"><table><thead><tr><th>Stable identity</th><th>Role / source</th><th>Original / selected / raw</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></section>
<section><h2>Source pages</h2>{"".join(pages) or "<p>No source page references available.</p>"}</section>
</main></body></html>"""
