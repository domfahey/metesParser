"""Offline standalone-map evidence; no geographic derivation or review attestations."""

from __future__ import annotations

import html
import json

from mp_models.webmap import StandaloneWebMapInput
from mp_verify.webmap import normalize_web_map_context

from .plot_html import render_plot
from .raster_guard import require_upright_raster


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _metadata(value: object) -> str:
    return "<pre>" + _escape(json.dumps(value, ensure_ascii=False, indent=2)) + "</pre>"


def render_map_evidence(prepared: StandaloneWebMapInput) -> str:
    """Render retained scans, metadata and shared local plots without external loads.

    Supplied inputs are validated through the shared display math before rendering.
    Source references are preserved; no source pages or reading status are invented.
    """
    prepared = StandaloneWebMapInput.model_validate(prepared.model_dump())
    context = normalize_web_map_context(prepared)
    plots = "".join(
        f"<section><h2>{_escape(plot.request.title)}</h2>"
        f'<iframe title="Local plot: {_escape(plot.request.title)}" '
        f'sandbox="allow-scripts" srcdoc="{_escape(render_plot(plot))}"></iframe></section>'
        for plot in prepared.plots
    )
    for layer in context.raster_layers:
        require_upright_raster(layer)
    rasters = "".join(
        f"<section><h3>{_escape(raster.label)}</h3>"
        f'<img alt="Original supplied scan: {_escape(raster.label)}" '
        f'src="data:{raster.mime_type};base64,{raster.data_base64}">'
        + _metadata(raster.model_dump(mode="json", exclude={"data_base64"}))
        + "</section>"
        for raster in context.raster_layers
    )
    metadata = _metadata(
        {
            "scenes": [scene.model_dump(mode="json") for scene in context.scenes],
            "map_sources": [
                source.model_dump(mode="json", exclude={"data_base64"})
                for source in context.map_sources
            ],
            "vector_layers": [layer.model_dump(mode="json") for layer in context.vector_layers],
            "placements": [p.model_dump(mode="json") for p in context.placements],
            "input_hashes": context.input_hashes,
        }
    )
    csp = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; frame-src 'self'; connect-src 'none'; base-uri 'none'; form-action 'none'; object-src 'none'"
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="{_escape(csp)}"><title>{_escape(context.title)} · Offline map evidence</title><style>body{{font:16px/1.5 system-ui,sans-serif;margin:2rem;max-width:100rem}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f4f4;padding:1rem}}iframe{{width:100%;height:50rem;border:1px solid #aaa}}img{{max-width:100%;height:auto}}section{{margin:2rem 0}}</style></head><body><main><h1>{_escape(context.title)} · Offline map evidence</h1><p>Display evidence only. Source review not supplied. No verified status is granted. Unknown bearings remain unresolved; supplied placement and registration do not establish boundary accuracy.</p><p>This page retains original scans and registration/source metadata. Local plots use the shared renderer in their native frame; they are not fitted to a basemap. No provider connection is required.</p>{plots or "<p>No deed plot was supplied.</p>"}<h2>Original registered scans</h2>{rasters or "<p>No registered scan was supplied.</p>"}<h2>Supplied map metadata and provenance</h2>{metadata}</main></body></html>'''
