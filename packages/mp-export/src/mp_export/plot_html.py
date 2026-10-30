"""Standalone, deterministic local plots of validated call geometry."""

from __future__ import annotations

import html
from pathlib import Path

from mp_models.plot import XY, plot_point_of_beginning
from mp_models.plot_request import PreparedPlot
from mp_verify.plot import validate_prepared_plot

from .plot_svg import fitted_viewbox, primitive_svg_path

_ASSETS = Path(__file__).with_name("plot_assets")


def _escape(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _number(value: float | None) -> str:
    return "Unavailable" if value is None else f"{value:,.3f}"


def render_plot(prepared: PreparedPlot) -> str:
    """Recompute and validate the input before rendering an offline HTML artifact.

    Display controls only alter the SVG viewport and source selection. No browser
    geometry, source images, review state or verified-export status is invented.
    """
    prepared = validate_prepared_plot(prepared)
    request, geometry = prepared.request, prepared.geometry
    calls = {item.id: item for item in request.calls}
    bounds: list[XY] = []
    courses = []
    for primitive in geometry.primitives:
        path, extent = primitive_svg_path(primitive)
        bounds.extend(extent)
        item = calls[primitive.call_id]
        label = item.call.course if item.call is not None else item.id
        start = primitive.start
        courses.append(
            f'<path data-plot-call="{_escape(item.id)}" d="{path}" class="record-course" '
            f'tabindex="0" role="button" aria-pressed="false" aria-label="Course {_escape(label)}: {_escape(item.quote)}">'
            f"<title>{_escape(item.quote or item.id)}</title></path>"
            f'<text class="course-label" x="{start[0]:.17g}" y="{-start[1]:.17g}" '
            f'dx=".3em" dy="-.3em" data-source-call="{_escape(item.id)}" '
            f'role="button" tabindex="0" aria-pressed="false">{_escape(label)}</text>'
        )
    box, width, height = fitted_viewbox(bounds)
    gap = ""
    if geometry.completeness == "complete" and geometry.primitives:
        first, last = geometry.primitives[0].start, geometry.primitives[-1].end
        gap = (
            f'<line class="plot-gap" x1="{last[0]:.17g}" y1="{-last[1]:.17g}" '
            f'x2="{first[0]:.17g}" y2="{-first[1]:.17g}"/>'
        )
        summary = (
            f"<p>Endpoint to POB: <strong>{_number(geometry.misclosure_ft)} ft</strong>. "
            "The dashed closure gap is an annotation, not a recorded course.</p>"
            f"<p>Area with implicit closing segment: {_number(geometry.area_sq_ft)} sq ft; "
            f"perimeter: {_number(geometry.perimeter_ft)} ft. Open-traverse area is provisional. "
            "This plot does not establish verification or source review.</p>"
        )
    else:
        summary = '<p class="notice">Full-parcel closure and area unavailable: the boundary has unresolved calls. Only the supported anchored prefix is plotted.</p>'
    pob = ""
    origin = plot_point_of_beginning(geometry)
    if origin is not None:
        pob = (
            f'<circle class="pob-marker" cx="{origin[0]:.17g}" cy="{-origin[1]:.17g}" '
            f'r="{max(width, height) * 0.008:.17g}"/>'
            f'<text class="pob-label" x="{origin[0]:.17g}" y="{-origin[1]:.17g}" dy="1.5em">POB</text>'
        )
    unresolved = {item.call_id: item.reason for item in geometry.unresolved}
    notices = "".join(
        f'<li data-unresolved-call="{_escape(item.call_id)}">{_escape(item.call_id)}: {_escape(item.reason)}</li>'
        for item in geometry.unresolved
    ) + "".join(f"<li>{_escape(reason)}</li>" for reason in geometry.reasons)
    rows = []
    for item in request.calls:
        call = item.call
        label = call.course if call else item.id
        bearing = (
            call.bearing_quadrant
            or (
                f"{call.bearing_azimuth_deg_from_north:g}° azimuth"
                if call.bearing_azimuth_deg_from_north is not None
                else "Unresolved bearing"
            )
            if call
            else "Unresolved call"
        )
        source = (
            " · ".join(
                value
                for value in (
                    item.source_reference,
                    f"Page: {item.page_id}" if item.page_id else None,
                    f"Occurrence: {item.occurrence_id}" if item.occurrence_id else None,
                )
                if value
            )
            or "Source reference unavailable"
        )
        page_attr = f' data-page-id="{_escape(item.page_id)}"' if item.page_id else ""
        status = (
            "Tie-in excluded from boundary"
            if call is not None and call.is_tie_in
            else unresolved.get(item.id, "Supported geometry")
        )
        rows.append(
            f'<tr data-call-row="{_escape(item.id)}"{page_attr}>'
            f'<th scope="row"><button type="button" data-source-call="{_escape(item.id)}" aria-pressed="false">{_escape(label)}</button></th>'
            f'<td><blockquote>{_escape(item.quote)}</blockquote><span class="source-ref">{_escape(source)}</span></td>'
            f"<td>{_escape(bearing)}<br>{_escape(call.direction_text if call else '')}</td>"
            f"<td>{_number(call.distance_ft if call else None)}</td><td>{_escape(status)}</td></tr>"
        )
    relative_note = (
        " Relative headings are derived from the supplied constraints; recorded bearings remain unchanged."
        if request.relative is not None
        else ""
    )
    css = (_ASSETS / "plot.css").read_text(encoding="utf-8")
    script = (_ASSETS / "plot.js").read_text(encoding="utf-8")
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{_escape(request.title)}</title><style>{css}</style></head>
<body><main><h1>{_escape(request.title)}</h1>
<p>Boundary plot · {_escape(geometry.completeness)} · native local frame</p>
<div class="toolbar" aria-label="Plot controls"><button type="button" id="plot-zoom-in">Zoom in</button><button type="button" id="plot-zoom-out">Zoom out</button><button type="button" id="plot-fit">Fit</button><button type="button" id="plot-reset">Reset view</button><label><input type="checkbox" id="plot-labels" checked> Course labels</label></div>
<svg id="plot" class="plot" viewBox="{box}" role="group" tabindex="0" aria-label="Local boundary plot; select a course to highlight its source row" style="font-size:{max(width, height) * 0.025:.17g}px"><g id="record-geometry">{"".join(courses)}{gap}{pob}</g></svg>
<p class="axis">↑ Local +Y · X east / Y north in the declared bearing frame; geographic north is not established. Units: ft ({_escape(request.foot_definition)}).{relative_note}</p>
<p id="plot-scale" class="scale" aria-live="polite"></p><p class="muted">Drag to pan; arrow keys pan; + / − zoom. View controls preserve the supplied calls and calculated geometry.</p>
{summary}<ul class="notices">{notices}</ul>
<h2>Source-linked calls</h2><p id="source-status" role="status">Select a course in the plot or table to highlight its source.</p>
<div class="table-wrap" role="region" aria-label="Source-linked call table" tabindex="0"><table><thead><tr><th>Course</th><th>Verbatim quote / source reference</th><th>Recorded bearing / direction</th><th>Distance (ft)</th><th>Geometry status</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>
<p class="muted">Source references identify supplied evidence; no source page images or review assertions are inferred.</p>
<p class="hash">Input SHA-256: {_escape(prepared.input_hash)}<br>Geometry SHA-256: {_escape(geometry.geometry_hash)}</p>
</main><script>{script}</script></body></html>'''
