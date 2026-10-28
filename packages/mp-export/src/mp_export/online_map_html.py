"""Read-only Mapbox companion shell; all geometry is prepared upstream."""

from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path

from mp_models.dashboard import PreparedDashboard
from mp_models.plot_request import PlotCall
from mp_models.webmap import MapboxViewOptions, WebMapArtifact
from mp_verify import webmap as webmap_validation
from mp_verify.webmap import (
    WebMapInput,
    normalize_web_map_context,
    validate_web_map_artifact,
)

_ASSETS = Path(__file__).with_name("dashboard_assets")


def online_renderer_fingerprint() -> str:
    """Identify renderer and pinned provider descriptor independently of inputs."""
    digest = hashlib.sha256()
    for path in (
        Path(__file__),
        Path(webmap_validation.__file__),
        *(
            Path(__file__).with_name(name)
            for name in (
                "map_evidence_html.py",
                "plot_html.py",
                "plot_svg.py",
            )
        ),
        *(Path(__file__).with_name("plot_assets") / name for name in ("plot.css", "plot.js")),
        *(_ASSETS / name for name in ("online_map.js", "online_map.css", "mapbox-sdk.json")),
    ):
        digest.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def _json(value: object) -> str:
    text = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    for character, replacement in (
        ("&", "\\u0026"),
        ("<", "\\u003c"),
        (">", "\\u003e"),
        ("\u2028", "\\u2028"),
        ("\u2029", "\\u2029"),
    ):
        text = text.replace(character, replacement)
    return text


def render_online_map(
    prepared: WebMapInput, artifact: WebMapArtifact, *, view: MapboxViewOptions
) -> str:
    """Validate stage identities, serialize evidence, and render without GIS work."""
    artifact = validate_web_map_artifact(prepared, artifact)
    view = MapboxViewOptions.model_validate(view.model_dump())
    context = normalize_web_map_context(prepared)
    if isinstance(prepared, PreparedDashboard):
        source = prepared.bundle.model_dump(mode="json")
        offline_path, offline_label = "dashboard.html", "Open offline dashboard"
    else:
        source = {
            "title": context.title,
            "calls": [call.model_dump(mode="json") for call in context.calls],
            "pages": [],
        }
        offline_path, offline_label = "map-evidence.html", "Open offline map evidence"
    descriptor = json.loads((_ASSETS / "mapbox-sdk.json").read_text())
    data = _json(
        {
            "bundle": source,
            "artifact": artifact.model_dump(mode="json"),
            "view": view.model_dump(mode="json"),
            "sdk": descriptor,
        }
    )
    esc = html.escape
    courses = "".join(
        f'<li><button type="button" data-map-call="{esc(call.id)}">{esc(call.id)}: {esc(call.quote or (call.call.direction_text if isinstance(call, PlotCall) and call.call else ""))}</button></li>'
        for call in context.calls
    )
    layers = [("raster-" + r.id, "Registered scan · approximate") for r in artifact.rasters]
    layers += [
        ("parcel_context", "Supplied parcel context"),
        ("recorded_course", "Recorded courses"),
        ("pob", "Point of beginning"),
        ("closure_gap", "Closure gap (annotation)"),
    ]
    controls = "".join(
        f'<label><input type="checkbox" checked data-map-layer="{esc(key)}">{esc(label)}</label>'
        for key, label in layers
    )
    notices = "".join(
        f"<li>{esc(item.item_id)}: {esc(item.code)} · {esc(item.reason)}</li>"
        for item in artifact.unavailable
    )
    registrations = "".join(
        f"<li>{esc(r.id)}: {esc(r.registration_status)}; fit RMS {esc(str(r.fit_rms))}; checkpoint RMS {esc(str(r.checkpoint_rms))} {esc(r.residual_units)}</li>"
        for r in artifact.rasters
    )
    css = (_ASSETS / "online_map.css").read_text()
    script = (_ASSETS / "online_map.js").read_text()
    csp = "default-src 'none'; script-src 'unsafe-inline' 'wasm-unsafe-eval' https://api.mapbox.com; style-src 'unsafe-inline' https://api.mapbox.com; img-src 'self' data: blob: https://api.mapbox.com; connect-src 'self' https://api.mapbox.com https://events.mapbox.com; worker-src blob:; child-src blob:; font-src https://api.mapbox.com; base-uri 'none'; form-action 'none'; object-src 'none'"
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="strict-origin"><meta http-equiv="Content-Security-Policy" content="{esc(csp, quote=True)}"><title>{esc(context.title)} · Online map</title><style>{css}</style></head><body><header><h1>{esc(context.title)} · Online map</h1><a href="{offline_path}" data-testid="offline-link">{offline_label}</a><p>Read-only display. Placement and registration accuracy remain separate from display sampling. No verified status is granted.</p></header><main><section aria-label="Map connection"><p>When you connect, Mapbox receives your public token and viewed map area to serve its basemap. This viewer does not upload deed records or scan files to Mapbox.</p><form id="map-connection"><label for="map-token">Mapbox public access token</label><input id="map-token" type="password" autocomplete="off" spellcheck="false"><button type="submit" data-testid="map-connect">Connect</button><button type="button" data-testid="map-disconnect" disabled>Disconnect</button></form><p data-testid="map-status" role="status" aria-live="polite">{"Geographic display unavailable" if artifact.bounds is None else "Disconnected. Connect to load the basemap."}</p><label>Basemap<select data-testid="map-style"><option value="standard" {"selected" if view.style == "standard" else ""}>Standard</option><option value="standard-satellite" {"selected" if view.style == "standard-satellite" else ""}>Standard satellite</option></select></label><button id="map-fit" type="button">Fit evidence</button><div class="layer-controls">{controls}</div><label>Scan opacity<input id="map-opacity" type="range" min="0" max="1" step="0.05" value="{view.raster_opacity}"></label></section><div id="online-map" role="region" aria-label="Geographic evidence map"></div><aside><h2>Recorded source courses</h2><ol>{courses}</ol><section data-testid="map-source-panel" aria-live="polite"><p>Select a recorded course to inspect its original source.</p><p>Source image unavailable until a supplied page is selected.</p></section><h2>Display availability: {esc(artifact.availability)}</h2><p>{len(artifact.features)} vector features; {len(artifact.rasters)} rasters; {len(artifact.unavailable)} unavailable items.</p><ul>{notices}{registrations}</ul><h2>Legend</h2><p>Blue: recorded deed; red dashed: closure gap; purple: supplied parcel context; green: POB; amber: selection. Tax scans and parcel outlines are context evidence.</p><p>Mapbox attribution appears in the connected map.</p></aside></main><dialog id="map-page-dialog" aria-labelledby="map-page-title"><h2 id="map-page-title">Source page</h2><div id="map-page-content"></div><button type="button" id="map-page-close">Close source page</button></dialog><script type="application/json" id="online-map-data">{data}</script><script>{script}</script></body></html>'''
