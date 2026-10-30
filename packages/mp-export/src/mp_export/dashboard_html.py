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
import math
from pathlib import Path
from typing import cast

from mp_models.closure import CheckResult
from mp_models.dashboard import DashboardBundle, PreparedDashboard
from mp_models.plot import (
    XY,
    LinearUnit,
    MultiPolygon,
    PlotPlacement,
    PlotScene,
    Polygon,
    VectorLayer,
    plot_point_of_beginning,
)
from mp_models.plot_request import PlotCall
from mp_models.raster import RasterLayer
from mp_models.revisions import revision_template
from mp_verify.dashboard import validate_prepared_dashboard

from .plot_svg import fitted_viewbox, primitive_svg_path
from .raster_guard import require_upright_raster

_ASSETS = Path(__file__).with_name("dashboard_assets")


def renderer_fingerprint() -> str:
    """SHA-256 of labelled renderer Python, CSS and JavaScript source bytes.

    This code identity is separate from the prepared presentation data hash.
    No timestamps, absolute paths or cache-hit metadata contribute to it.
    """
    digest = hashlib.sha256()
    for name, path in (
        ("dashboard_html.py", Path(__file__)),
        ("plot_svg.py", Path(__file__).with_name("plot_svg.py")),
        ("dashboard.css", _ASSETS / "dashboard.css"),
        ("dashboard.js", _ASSETS / "dashboard.js"),
        ("revisions.js", _ASSETS / "revisions.js"),
        ("structured_editor.js", _ASSETS / "structured_editor.js"),
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
                f'<tr data-call-row="{_escape(item.id)}" class="{"uncertain" if item.reading_status != "certain" else ""}"><td><button type="button" data-source-call="{_escape(item.id)}">{_escape(call.course if call else item.id)}</button></td><td>{_escape(call.direction_text if call else "Unknown")}<br>{_escape(item.quote)}</td><td>{_escape(item.stated_angle_text or "Not stated")}<br>{_escape(item.stated_angle_type or "Unknown")}</td><td>{_escape(item.distance_text or "Not transcribed separately")}<br>{_escape(_number(call.distance_ft if call else None))}</td><td>{_escape(call.along if call else "")}<br>{_escape(call.to if call else "")}</td><td>{_escape(item.reading_status)} · {_escape(item.reading_note)}<br>{_page_button(bundle, item.page_id)}</td></tr>'
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


def _layer_polygons(layer: VectorLayer) -> MultiPolygon:
    return (
        (cast(Polygon, layer.coordinates),)
        if layer.geometry_type == "Polygon"
        else cast(MultiPolygon, layer.coordinates)
    )


def _raster_corners(layer: RasterLayer) -> list[XY]:
    a, b, c, d, e, f = layer.registration.matrix
    corners = [
        (a * u + b * v + c, d * u + e * v + f)
        for u, v in (
            (-0.5, -0.5),
            (layer.width - 0.5, -0.5),
            (layer.width - 0.5, layer.height - 0.5),
            (-0.5, layer.height - 0.5),
        )
    ]
    if not all(math.isfinite(value) for point in corners for value in point):
        raise ValueError("Raster registration exceeds finite scene range")
    return corners


def _raster_svg(layer: RasterLayer) -> str:
    require_upright_raster(layer)
    a, b, c, d, e, f = layer.registration.matrix
    matrix = " ".join(f"{value:.17g}" for value in (a, d, b, e, c, f))
    return f'<g transform="scale(1 -1)"><image data-raster-layer="{_escape(layer.id)}" x="-0.5" y="-0.5" width="{layer.width}" height="{layer.height}" transform="matrix({matrix})" href="data:{layer.mime_type};base64,{_escape(layer.data_base64)}" preserveAspectRatio="none"><title>{_escape(layer.label)}</title></image></g>'


def _plot_views(prepared: PreparedDashboard) -> str:
    """Render analytic source primitives before browser enhancement."""
    from mp_verify.plot import transform_point

    bundle = prepared.bundle
    plots = prepared.plots
    if plots is None:
        return '<p class="warning">Plot geometry is unavailable.</p>'
    parts = [
        '<p class="plot-legend">Solid teal: recorded boundary · dashed orange: advisory scenario · dashed red: closure gap · shaded blue: supplied map context.</p><div class="controls plot-toolbar" aria-label="Plot controls">'
        '<button type="button" id="plot-zoom-in">Zoom in</button>'
        '<button type="button" id="plot-zoom-out">Zoom out</button>'
        '<button type="button" id="plot-fit">Fit</button>'
        '<button type="button" id="plot-reset">Reset view</button>'
        '<label><input id="plot-labels" type="checkbox" checked> Course labels</label>'
        '<label><input id="plot-bearings" type="checkbox"> Bearings</label>'
        '<label><input id="plot-distances" type="checkbox"> Distances</label>'
        "</div>"
    ]
    if not bundle.vector_layers and not bundle.raster_layers:
        parts.append(
            '<p class="muted">No supplied map layers. Deed geometry uses its native local frame.</p>'
        )
    for index, geometry in enumerate(plots.geometries):
        calculation = next(c for c in bundle.calculations if c.id == geometry.calculation_id)
        placement = next(
            (
                p
                for p in plots.placements
                if p.calculation_id == geometry.calculation_id and p.status != "unplaced"
            ),
            None,
        )
        scene = next((s for s in bundle.scenes if placement and s.id == placement.scene_id), None)
        units = scene.units if scene else "ft"
        north_label = (
            f"↑ {scene.basis.capitalize()} north · documented scene basis"
            if scene and scene.basis in {"grid", "true", "magnetic"}
            else "↑ Local +Y · Recorded bearings do not establish geographic north."
        )
        opacity = dict(bundle.plot_view.opacity) if bundle.plot_view else {}
        native_units = calculation.frame.foot_definition

        def point(
            value: XY,
            placement: PlotPlacement | None = placement,
            native_units: LinearUnit = native_units,
            scene: PlotScene | None = scene,
        ) -> XY:
            return (
                transform_point(
                    value, placement, native_units=native_units, scene_units=scene.units
                )
                if placement and scene
                else value
            )

        bounds: list[XY] = []
        courses = []
        for primitive in geometry.primitives:
            start, end = point(primitive.start), point(primitive.end)
            d, primitive_bounds = primitive_svg_path(primitive, point)
            bounds.extend(primitive_bounds)
            item = next(c for c in bundle.calls if c.id == primitive.call_id)
            label = item.call.course if item.call else item.id
            details = (
                f"{item.call.bearing_quadrant or (item.call.bearing_azimuth_deg_from_north if item.call.bearing_azimuth_deg_from_north is not None else 'unknown')}°"
                if item.call
                else "Unresolved"
            )
            courses.append(
                f'<path data-plot-call="{_escape(item.id)}" d="{d}" class="record-course" marker-end="url(#course-arrow-{_escape(geometry.calculation_id)})" tabindex="0" role="button" aria-label="Course {_escape(label)}: {_escape(item.quote)}"><title>{_escape(item.quote)}</title></path><text class="course-label" x="{start[0]:.17g}" y="{-start[1]:.17g}" data-source-call="{_escape(item.id)}" role="button" tabindex="0">{_escape(label)}</text><text class="bearing-label" x="{(start[0] + end[0]) / 2:.17g}" y="{-(start[1] + end[1]) / 2:.17g}">{_escape(details)}</text><text class="distance-label" x="{(start[0] + end[0]) / 2:.17g}" y="{-(start[1] + end[1]) / 2:.17g}" dy="1.2em">{primitive.length_ft:.3f} ft</text>'
            )
        layers = []
        for raster in bundle.raster_layers:
            if not scene or raster.scene_id != scene.id:
                continue
            bounds.extend(_raster_corners(raster))
            layers.append(
                f'<g style="opacity:{opacity.get(raster.id, 0.45)}" data-map-layer="{_escape(raster.id)}">{_raster_svg(raster)}</g>'
            )
        for vector in bundle.vector_layers:
            if not scene or vector.scene_id != scene.id:
                continue
            polygons = _layer_polygons(vector)
            layer_paths = []
            for polygon in polygons:
                for ring in polygon:
                    bounds.extend(ring)
                    layer_paths.append(
                        "M " + " L ".join(f"{p[0]:.17g} {-p[1]:.17g}" for p in ring) + " Z"
                    )
            layer_opacity = opacity.get(vector.id, 0.45)
            layers.append(
                f'<g style="opacity:{layer_opacity}" data-map-layer="{_escape(vector.id)}"><path d="{" ".join(layer_paths)}" fill-rule="evenodd" class="map-polygon"/></g>'
            )
        box, width, height = fitted_viewbox(bounds)
        fit_box = box
        if bundle.plot_view and bundle.plot_view.viewport:
            left, bottom, view_width, view_height = bundle.plot_view.viewport
            box = f"{left:.17g} {-bottom - view_height:.17g} {view_width:.17g} {view_height:.17g}"
        gap = ""
        gap_detail = ""
        if geometry.completeness == "complete" and geometry.primitives:
            first, last = point(geometry.primitives[0].start), point(geometry.primitives[-1].end)
            gap = f'<line class="plot-gap" x1="{last[0]:.17g}" y1="{-last[1]:.17g}" x2="{first[0]:.17g}" y2="{-first[1]:.17g}"/>'
            margin = max(math.dist(first, last), 0.01)
            gap_box = f"{min(first[0], last[0]) - margin} {-max(first[1], last[1]) - margin} {abs(first[0] - last[0]) + 2 * margin} {abs(first[1] - last[1]) + 2 * margin}"
            gap_detail = f'<svg class="plot gap-magnifier" viewBox="{gap_box}" aria-label="Magnified endpoint to POB gap">{gap}<circle cx="{first[0]}" cy="{-first[1]}" r="{margin * 0.04}"/><circle cx="{last[0]}" cy="{-last[1]}" r="{margin * 0.04}"/></svg><p>Scene gap vector: ΔX {last[0] - first[0]:.6f}; ΔY {last[1] - first[1]:.6f} {_escape(units)}. Magnified view has its own scale.</p>'
        pob = ""
        true_origin = plot_point_of_beginning(geometry)
        if true_origin is not None:
            origin = point(true_origin)
            pob = f'<circle class="pob-marker" cx="{origin[0]:.17g}" cy="{-origin[1]:.17g}" r="{max(width, height) * 0.006}"/><text class="pob-label" x="{origin[0]:.17g}" y="{-origin[1]:.17g}" dy="1.5em">POB</text>'
        scenario_id = 'id="scenario-plot-layer"' if index == 0 else ""
        parts.append(
            f'<article class="record-plot-panel" data-plot-panel="{_escape(geometry.calculation_id)}"><h3>Recorded boundary · {_escape(geometry.occurrence_id)}</h3><p>{_escape(geometry.completeness)} · {_escape(placement.status if placement else "unplaced; native deed frame")}</p><svg class="plot record-plot" data-baseline-plot="{_escape(geometry.calculation_id)}" data-initial-viewbox="{box}" data-fit-viewbox="{fit_box}" data-units="{_escape(units)}" viewBox="{box}" role="group" aria-label="Recorded boundary; source-linked courses, separate closure gap"><defs><marker id="course-arrow-{_escape(geometry.calculation_id)}" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="{max(width, height) * 0.025}" markerHeight="{max(width, height) * 0.025}" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10" fill="none" stroke="currentColor"/></marker></defs><g class="map-layers">{"".join(layers)}</g><g data-baseline-layer="{_escape(geometry.calculation_id)}">{"".join(courses)}{gap}{pob}</g><g data-scenario-layer="{_escape(geometry.calculation_id)}" {scenario_id}></g></svg><p class="plot-axis">{_escape(north_label)}</p><p class="plot-scale" aria-live="polite"></p><details id="{"plot-gap-detail" if index == 0 else "plot-gap-" + str(index)}"><summary>Closure gap detail</summary><p>Record gap: {_number(geometry.misclosure_ft)} ft. Dashed annotation is endpoint to POB; it is not a recorded course. A partial boundary has no full-parcel gap or area.</p>{gap_detail}</details><ul class="plot-notices">'
        )
        if placement:
            parts.append(
                f"<li>Placement {_escape(placement.id)}: clockwise {placement.rotation_deg:g}°; translation {_escape(placement.translation)} {_escape(units)}. {_escape(placement.rationale)} Geometry SHA-256: {_escape(geometry.geometry_hash)}. Position evidence: {_escape(placement.position_evidence or 'unavailable')}; orientation evidence: {_escape(placement.orientation_evidence or 'unavailable')}.</li>"
            )
        parts.extend(
            f'<li data-unresolved-call="{_escape(u.call_id)}">{_escape(u.call_id)}: {_escape(u.reason)}</li>'
            for u in geometry.unresolved
        )
        parts.extend(f"<li>{_escape(reason)}</li>" for reason in geometry.reasons)
        parts.append(
            '</ul><p class="muted">Drag to pan. Arrow keys pan; + / − zoom. Scenario uses the unchanged baseline placement; view controls change only the viewport.</p></article>'
        )
    parts.append(
        '<details class="map-provenance"><summary>Map layers and provenance</summary><p>Tax parcels are assessment/context evidence; visual fit does not establish a survey or legal boundary.</p>'
    )
    map_layers: tuple[VectorLayer | RasterLayer, ...] = (
        *bundle.vector_layers,
        *bundle.raster_layers,
    )
    for layer in map_layers:
        source = next(s for s in bundle.map_sources if s.id == layer.source_id)
        aligned = any(
            p.status != "unplaced" and p.scene_id == layer.scene_id for p in plots.placements
        )
        source_scene = next(scene for scene in bundle.scenes if scene.id == layer.scene_id)
        parts.append(
            f"<p>Scene {_escape(source_scene.name)} · {_escape(source_scene.units)} · {_escape(source_scene.crs or 'local; no CRS')} · axes {_escape(source_scene.axis_order)}. Retrieved: {_escape(source.retrieved_at or 'unknown')}; source date: {_escape(source.source_date or 'unknown')}.</p>"
        )
        parts.append(
            f'<div class="map-layer-control"><label><input type="checkbox" data-layer-toggle="{_escape(layer.id)}" checked> {_escape(layer.label)}</label><label>Opacity <input type="range" min="0" max="1" step="0.05" value="0.45" data-layer-opacity="{_escape(layer.id)}"></label><p>{"Placed in declared scene" if aligned else "Unplaced — separate map evidence; not overlaid with the deed"}</p><pre>{_escape(source.model_dump_json(indent=2))}</pre></div>'
        )
        if isinstance(layer, RasterLayer):
            registration = layer.registration
            parts.append(
                f"<p>Raster registration: {_escape(registration.status)} · {_escape(registration.pixel_convention)}. Fit RMS {_number(registration.fit_rms)}; Checkpoint RMS {_number(registration.checkpoint_rms)} {_escape(source_scene.units)}. Fit residuals are not independent survey accuracy.</p><pre>{_escape(registration.model_dump_json(indent=2))}</pre>"
            )
        if not aligned:
            vertices = (
                _raster_corners(layer)
                if isinstance(layer, RasterLayer)
                else [
                    point
                    for polygon in _layer_polygons(layer)
                    for ring in polygon
                    for point in ring
                ]
            )
            x, y = min(p[0] for p in vertices), max(p[1] for p in vertices)
            w, h = max(p[0] for p in vertices) - x, y - min(p[1] for p in vertices)
            pad = max(w, h) * 0.1
            independent_content = (
                _raster_svg(layer)
                if isinstance(layer, RasterLayer)
                else '<path class="map-polygon" fill-rule="evenodd" d="'
                + " ".join(
                    "M " + " L ".join(f"{p[0]} {-p[1]}" for p in ring) + " Z"
                    for polygon in _layer_polygons(layer)
                    for ring in polygon
                )
                + '"/>'
            )
            parts.append(
                f'<p class="warning">No supported common placement: map comparison is unavailable. Independent map frame below.</p><svg class="plot independent-map" aria-label="Independent map evidence, no deed alignment" viewBox="{x - pad} {-y - pad} {w + 2 * pad} {h + 2 * pad}"><g style="opacity:{dict(bundle.plot_view.opacity).get(layer.id, 0.45) if bundle.plot_view else 0.45}" data-map-layer="{_escape(layer.id)}">{independent_content}</g></svg>'
            )
    for comparison in plots.comparisons:
        comparison_placement = next(p for p in plots.placements if p.id == comparison.placement_id)
        comparison_scene = next(
            scene for scene in bundle.scenes if scene.id == comparison_placement.scene_id
        )
        parts.append(
            f"<p>Named-point comparison {_escape(comparison.comparison_id or comparison.placement_id)}: {_escape(comparison.status)} · {_escape(comparison_placement.status)} placement. RMS {_number(comparison.rms)} {_escape(comparison_scene.units)}; maximum {_number(comparison.maximum)} {_escape(comparison_scene.units)}. Displacement vectors below use {_escape(comparison_scene.units)}. {_escape(comparison.reason)} Fit residuals are separate from deed closure and are not survey accuracy.</p><pre>{_escape(comparison.model_dump_json(indent=2))}</pre>"
        )
    parts.append("</details>")
    return "".join(parts)


def _description_comparison_section(prepared: PreparedDashboard) -> str:
    """Render fresh immutable results; source buttons reuse the existing viewer."""
    if not prepared.description_comparisons:
        return ""
    occurrences = {o.id: o for o in prepared.bundle.occurrences}

    def sources(records: tuple[PlotCall, ...]) -> str:
        items = []
        for record in records:
            if record.occurrence_id is None:
                raise ValueError("dashboard comparison source lacks occurrence identity")
            occurrence = occurrences[record.occurrence_id]
            wording = ""
            if record.call is not None:
                wording = f"<p>Along: {_escape(record.call.along or '')}<br>To: {_escape(record.call.to or '')}</p>"
            items.append(
                f'<div class="comparison-source"><button type="button" data-comparison-source="{_escape(record.id)}">{_escape(occurrence.version_label)} · {_escape(record.id)}</button>'
                f'<p class="muted">{_escape(record.source_reference or "Source reference unavailable")}</p><pre>{_escape(record.quote)}</pre>{wording}</div>'
            )
        return "".join(items) or "No counterpart selected"

    cards = []
    for advisory in prepared.description_comparisons:
        result = advisory.comparison
        pairs = []
        for pair in result.pairs:
            components = []
            values = [
                ("Length", pair.length),
                ("Bearing", pair.bearing),
                ("Displacement", pair.displacement),
                ("Position", pair.position),
            ]
            if pair.curve is not None:
                values.extend(
                    (
                        ("Radius", pair.curve.radius),
                        ("Sweep", pair.curve.sweep),
                        ("Turn", pair.curve.turn),
                    )
                )
            for label, component in values:
                difference = (
                    ("Categorical" if label == "Turn" else "Unavailable")
                    if component.difference is None
                    else f"{_number(component.difference)} {_escape(component.units or '')}"
                )
                components.append(
                    f"<tr><th>{label}</th><td>{_escape(component.outcome)}</td><td>{difference}</td><td>{_escape(component.reason)}</td></tr>"
                )
            pairs.append(
                f'<article class="panel comparison-pair" data-comparison-pair="{_escape(pair.id)}"><h4>Explicit pair {_escape(pair.id)}</h4>'
                f'<div class="comparison-versions"><div>{sources(pair.left_sources)}</div><div>{sources(pair.right_sources)}</div></div>'
                f'<div class="table-wrap"><table><thead><tr><th>Component</th><th>Outcome</th><th>Difference</th><th>Reason</th></tr></thead><tbody>{"".join(components)}</tbody></table></div></article>'
            )
        structural = []
        for structural_difference in result.structural:
            structural.append(
                f"<tr><th>{_escape(structural_difference.kind)}{' · tentative' if structural_difference.tentative else ' · exact content anchor'}</th><td>{sources(structural_difference.left_sources)}</td><td>{sources(structural_difference.right_sources)}</td><td>{_escape(structural_difference.reason)}<p>Changed fields: {_escape(', '.join(structural_difference.changed_fields) or 'none identified')}</p></td></tr>"
            )
        tolerance = result.tolerances
        cards.append(
            f'<article class="panel" data-description-comparison="{_escape(advisory.id)}"><h3>{_escape(occurrences[advisory.left_occurrence_id].version_label)} ↔ {_escape(occurrences[advisory.right_occurrence_id].version_label)}</h3>'
            f"<p>Criteria: length {_number(tolerance.length)}, vector {_number(tolerance.displacement)}, position {_number(tolerance.position)} {_escape(tolerance.linear_unit)}; bearing {_number(tolerance.bearing_deg)} degrees. Criteria source: {_escape('; '.join(tolerance.source_references))}.</p>"
            f"<h4>Explicit geometric selections</h4>{''.join(pairs) or '<p>No explicit geometric pairs requested.</p>'}"
            f'<details><summary>Structural content differences and tentative correspondences</summary><div class="table-wrap"><table><thead><tr><th>Suggestion</th><th>Left version source</th><th>Right version source</th><th>Reason / changed fields</th></tr></thead><tbody>{"".join(structural)}</tbody></table></div></details>'
            f'<p class="hash">Comparison identity {_escape(result.input_hash)} · {_escape(result.algorithm_version)}</p></article>'
        )
    return (
        '<section id="description-comparisons"><h2>Description comparison</h2><p>Recorded versions remain fixed during scenario edits and reset. Same physical or legal boundary is not established. Comparison criteria do not change verification tolerances or export eligibility. Structural suggestions remain tentative when geographic comparison is unavailable.</p>'
        + "".join(cards)
        + "</section>"
    )


def render_dashboard(prepared: PreparedDashboard) -> str:
    """Render a prepared dashboard reproducibly without reading external assets.

    Fresh validation rejects invalid references, unsafe image URIs, stale stage
    hashes and results that disagree with the deterministic calculation stage.
    """
    prepared = validate_prepared_dashboard(prepared)
    bundle = prepared.bundle
    payload = prepared.model_dump(mode="json", exclude={"manifest": {"cache_reused"}})
    payload["revision_template"] = revision_template(bundle).model_dump(mode="json")
    data = json.dumps(
        payload,
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
    script = "\n".join(
        (_ASSETS / name).read_text(encoding="utf-8")
        for name in ("revisions.js", "structured_editor.js", "dashboard.js")
    )
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
<body><header><div class="eyebrow">Metes &amp; bounds · record review</div><h1>{_escape(bundle.title)}</h1><p>{_escape(bundle.presentation.subtitle)}</p><p class="muted">Immutable record findings, source evidence, and a separate advisory scenario workbench.</p><nav aria-label="Dashboard sections"><a href="#findings">Findings</a><a href="#evidence">Evidence</a><a href="#workbench">Workbench</a><a href="#records">As recorded</a>{'<a href="#description-comparisons">Comparison</a>' if prepared.description_comparisons else ""}<a href="#sources">Source copies</a><a href="#method">Method &amp; limits</a></nav></header>
<main><noscript><p class="warning">JavaScript is disabled. Record findings, transcripts and page images remain visible. Workbench and full-size viewer require JavaScript.</p></noscript>
<section id="findings"><h2>1. Record findings</h2><p>Each occurrence retains its own source values. Findings and canonical engine status stay fixed during workbench edits. Geometric closure does not resolve an uncertain reading.</p><div class="cards">{_findings(prepared)}</div></section>
<section id="evidence"><h2>2. Record evidence</h2><div class="cards">{_evidence(bundle)}</div></section>
<section id="saved-alternatives"><h2>Saved alternatives</h2><div class="panel"><div class="controls"><label>Alternative name<input id="revision-label" type="text"></label><label>Reason for this alternative<textarea id="revision-rationale" rows="2"></textarea></label><button id="revision-download" type="button">Download draft</button><label>Load draft JSON<input id="revision-import" type="file" accept="application/json,.json"></label></div><p id="revision-status" role="status" aria-live="polite"></p><p class="muted">Draft recovery is stored in this browser when available and can contain source excerpts. Download a copy for another session. Give the draft and its original source bundle to Cowork to validate and publish a revision. A downloaded or recovered draft does not establish valid geometry or canonical verification.</p></div></section>
<section><details id="structured-editor"><summary>Add, edit, remove or reorder courses</summary><p>Choose the occurrence in the workbench, then edit its exact draft below. Bearings and units are explicit; incomplete values remain recoverable. Circular arcs are computed by the shared geometry engine when Cowork publishes and renders the downloaded revision. Original source wording and record findings remain available.</p><div id="structured-editor-fields" class="panel"></div></details></section>
<section id="workbench"><h2>3. Scenario workbench</h2><div class="panel"><div class="controls"><label>Parcel<select id="parcel-select"><option value="all">All parcels</option>{parcel_options}</select></label><label>Occurrence / calculation<select id="calculation-select"></select></label><label>Scenario<select id="scenario-select"></select></label><button type="button" id="reset-record">Reset to record</button></div><p id="scenario-rationale" class="muted"></p><p class="warning">Browser edits are hypothetical. They cannot verify a deed or authorize a verified export. Relative calculations permit distance edits; angular interpretations remain the explicit sourced constraints. Absolute bearings accept decimal azimuth or quadrant DMS. No bearings are inferred from direction words.</p>{_plot_views(prepared)}<details open class="diagnosis"><summary>Advisory closure diagnosis</summary><p>Unit sensitivity is not a correction or an error probability. Distance and bearing ranks use separate units. Opposing candidates remain tied; closure cannot choose a source reading.</p><div class="diagnosis-grid"><section aria-label="Recorded baseline diagnosis"><h3>Recorded baseline diagnosis</h3><div id="baseline-diagnostics"></div></section><section aria-label="Browser scenario diagnosis"><h3>Browser scenario diagnosis</h3><div id="scenario-diagnostics" aria-live="polite"></div></section></div></details><div class="scenario-summary"><svg id="plot" hidden class="plot" viewBox="0 0 420 380" role="img" aria-label="Scenario traverse with numbered courses, POB and dashed closure gap"></svg><div><h3 id="scenario-status" role="status" aria-live="polite">Loading advisory scenario…</h3><div id="scenario-metrics" class="metrics"></div><p class="muted">Gap vector is endpoint minus POB in the declared frame. Area includes an implicit endpoint-to-start segment and is provisional for an open traverse.</p></div></div><div class="table-wrap" role="region" aria-label="Editable scenario call sheet" tabindex="0"><table><thead><tr><th>Course</th><th>Source quote / direction</th><th>Distance (ft)</th><th>Recorded azimuth (degrees) / basis</th><th>Stated angle</th><th>Derived heading</th><th>ΔX / ΔY (ft)</th></tr></thead><tbody id="call-body"></tbody></table></div><p class="muted">Amber fields differ from the selected record. Uncertain source readings retain their warning stripe. Direction-word agreement is not evaluated as a measured bearing.</p><details><summary>Closing angle and shared corners</summary><p>Stated closing angles remain in the sourced constraints and transcripts. The heading-based closing angle is derived; it is not a replacement reading. A missing closing angle leaves the stated angle sum unavailable.</p><div id="closing-angle-detail"></div><p>Explicit named-point overlay comparisons appear in map provenance when supplied with a compatible placement. Automated boundary matching and inferred cross-parcel alignment are unavailable. Independent arbitrary local frames are not overlaid or silently aligned.</p></details></div></section>
{_description_comparison_section(prepared)}
<section id="records"><h2>4. Metes and bounds as recorded</h2><p>Untouched transcripts preserve the supplied wording and whitespace. Uncertain course readings are marked in the course tables; no alternate figure replaces the transcript.</p>{_records(bundle)}</section>
<section id="sources"><h2>5. Source copies</h2><p>Every indexed page appears below, including unavailable images and unread pages. Description pages have an outlined edge. Missing expected pages are listed explicitly; completeness is a separate source-review claim.</p>{_sources(bundle)}</section>
<section id="method"><h2>6. Method, limits, and sources</h2><div class="panel"><p>Bearings use degrees clockwise from North. Local-angle calculations use an explicitly declared arbitrary frame, interior/exterior angle convention, and orientation. Straight-course displacement is distance × sin(heading) in X and distance × cos(heading) in Y. The browser independently propagates explicit constraints, rejects unresolved or contradictory relations, and never adjusts values to close a boundary.</p><p>The recorded baseline displays determined analytic lines and circular arcs, and preserves known prefixes before unresolved calls. The immediate browser preview supports complete straight boundaries. Structured line and circular-arc drafts are saved here; Cowork computes their fresh revision views with the shared geometry engine. Exceptions, meanders and indefinite connectivity remain explicit unresolved cases. Source uncertainty remains independent of geometric closure. Precision is perimeter divided by gap; an unavailable denominator is not proof of infinite precision for a nonzero gap. A matching angle sum does not prove the angles are correct.</p><p>Only the canonical verifier’s full checks and its &lt;0.01 ft threshold govern verified export. Browser scenarios have no verified-export control. This dashboard is not a survey, title opinion, or boundary certification. Image presence is not evidence that a person inspected the page. Review sensitive source pages before sharing.</p><ul>{methods}</ul><h3>Stage and source identities</h3><p>Source review: {"complete" if prepared.manifest.source_review_complete else "incomplete"} · calculator {_escape(prepared.manifest.calculator_version)} · schema {_escape(bundle.schema_version)}</p>{hashes}</div></section></main>
<footer>Offline review artifact · self-contained assets · no external runtime or fonts</footer>
<dialog id="source-viewer" aria-labelledby="viewer-label"><div class="viewer-toolbar"><strong id="viewer-label"></strong><button type="button" id="viewer-prev">Previous</button><button type="button" id="viewer-next">Next</button><a id="open-image" target="_blank" rel="noopener noreferrer">Open image</a><button type="button" id="viewer-close">Close</button></div><img id="viewer-image" alt=""><p id="viewer-missing" class="placeholder">This source page image is unavailable. Its ledger entry is preserved.</p><p class="muted">Use Left / Right arrow keys to change pages; Escape to close.</p></dialog>
<script type="application/json" id="dashboard-data">{data}</script><script>{script}</script></body></html>"""
