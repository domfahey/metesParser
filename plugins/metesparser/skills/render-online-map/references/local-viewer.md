# Mapbox local viewer

Use this mode for a requested local online map. The default dashboard remains offline. Read the [online handoff](../../../references/artifact-handoffs.md#optional-online-map-handoff) for inputs, status, accuracy, and invalidation. The companion is a read-only, baseline-only 2D Mercator view; it does not support online scenario edits, terrain, or globe placement.

In a source checkout, install optional dependencies with `uv sync --extra web-map`. To build a distributable plugin from that checkout, run `uv run python scripts/build_claude_plugin.py --with-web-map --output dist/metesparser-plugin-web-map.zip`; this includes geo support and cannot be combined with `--without-geo`. With an already extracted web-map distribution, use its `scripts/run-review.py` launcher directly; the repository build script is not bundled. Default and minimal distributions retain their offline purpose.

## Compose existing artifacts

The standalone command accepts `StandaloneWebMapInput` (`mp_models.webmap`), not a `DashboardBundle`: `schema_version: "1.0"`, `title`, `plots` (each a `PreparedPlot` containing `request`, `geometry`, `input_hash`), required nonempty `scenes`, and optional `map_sources`, `vector_layers`, `raster_layers`, and `placements`. It creates neither `dashboard.html` nor source-review/verification attestations. IDs must be globally unique across calls, calculations, scenes, map sources, layers, and placements.

Reuse an existing plot's three artifacts and the supported arrays from a prepared overlay. This example assumes `plot-new/`, `prepared-layer.json`, and a separately supplied `placements.json` exist; the latter is an array of supported explicit placements, never an inferred fit:

```python
import json
from pathlib import Path
from mp_models.webmap import StandaloneWebMapInput

plot_dir = Path("plot-new")
manifest = json.loads((plot_dir / "plot-manifest.json").read_text())
prepared_plot = {
    "request": json.loads((plot_dir / "plot-input.json").read_text()),
    "geometry": json.loads((plot_dir / "plot-geometry.json").read_text()),
    "input_hash": manifest["input_hash"],
}
layer = json.loads(Path("prepared-layer.json").read_text())
source = {
    "schema_version": "1.0",
    "title": "Prepared boundary and map evidence",
    "plots": [prepared_plot],
    "placements": json.loads(Path("placements.json").read_text()),
}
for field in ("scenes", "map_sources", "vector_layers", "raster_layers"):
    source[field] = layer.get(field, [])
validated = StandaloneWebMapInput.model_validate(source)
Path("map-input.json").write_text(validated.model_dump_json(indent=2) + "\n")
```

Run the example with `uv run python` in the workspace runtime. Retain original plot source/manifest and complete map-preparation artifacts alongside the map input. Copy named arrays only: import operation metadata and wrapper fields are not standalone input fields. For several layer artifacts, combine their arrays while resolving actual IDs and scene references; do not drop provenance or rename bound identifiers casually.

The renderer recomputes each plot with the shared `mp_verify.plot.prepare_plot` logic and rejects stale or altered geometry/input hashes and placements. Alternatively, call `prepare_plot(PlotRequest.model_validate(existing_plot_input))` and retain its complete `model_dump(mode="json")` as a `plots` entry. This is deterministic display preparation, not verification or document reading. If call/calculation IDs or the plot request change, recompute the plot and bind the supplied placement to its fresh `geometry_hash`; never substitute a dashboard hash. Preserve existing unknown bearings and verbatim source fields.

Each requested placement names the plot's `calculation_id`, its exact `geometry_hash`, and a supplied `scene_id`, rotation/translation, status, and rationale. The standalone contract currently accepts `approximate` or `unplaced` placements; `referenced` requires an orientation-frame contract this input does not provide. Dashboard `evidence_ids`, scenario, and baseline fields are also unsupported here. Keep position/orientation support in the supplied rationale and evidence strings; require compatible units and an explicit foot definition. No automatic geocoding, matching, scale/shear/reflection, or image fitting is allowed. Unplaced or unresolved layers remain unavailable/partial rather than guessed.

## Configure and render

Save this token-free `WebMapRequest` as `online-map-config.json`. Replace `scene-1` with an actual projected scene ID already present in the standalone input (or source bundle for the dashboard compatibility path):

```json
{
  "schema_version": "1.0",
  "scene_id": "scene-1",
  "display": {
    "tolerance_m": 0.05,
    "max_depth": 20,
    "max_vertices": 100000,
    "raster_pixel_size_m": 0.25,
    "max_raster_dimension": 4096,
    "max_raster_pixels": 16777216
  },
  "view": {
    "provider": "mapbox",
    "style": "standard",
    "raster_opacity": 0.55
  }
}
```

Only `scene_id` is required; the other values shown are defaults. `style` also accepts `standard-satellite`. The display tolerance and raster resolution are approximation settings, not ground-accuracy claims. Never add a token to this file, the source bundle, or generated artifacts.

```sh
uv run metes-review render-map map-input.json --online-map-config online-map-config.json --output-dir online-map-new
uv run metes-review serve-map online-map-new --port 8765
```

The plugin launcher accepts the same arguments after `scripts/run-review.py`:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" render-map map-input.json --online-map-config online-map-config.json --output-dir online-map-new
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" serve-map online-map-new --port 8765
```

A valid render returns `needs_review` (exit 1), with `engine_verified`, `verified_export_eligible`, and `source_review_complete` false. Its artifacts are `source-map.json`, `web-map-request.json`, `web-map.json`, `web-map-manifest.json`, `online-map.html`, `map-evidence.html` (offline fallback), and any warped PNGs in `web-map-assets/`. The input retains plots/maps; no implicit filesystem fetch reconstructs missing evidence. Use a fresh output directory.

Existing dashboard callers can still use `dashboard BUNDLE.json --output-dir NEW_DIR --online-map-config CONFIG.json`; that compatibility path delegates the shared online preparation while retaining its offline dashboard. Do not build it just for an online map.

## Preview and provider connection

 Inspect online availability and reasons separately. The preview prints `http://localhost:8765/online-map.html` immediately and binds only to `127.0.0.1`. Open the advertised `localhost` URL, not a file URL or a different host. It serves only declared display assets and the online page and its offline fallback, not the source JSON files. Keep the terminal running; Ctrl-C stops preview. An occupied port fails instead of silently selecting another. For another explicit port, pass it and restrict the token to that exact localhost origin in Mapbox. The viewer sends an origin-only referrer, so do not configure a path-specific restriction.

Enter a public `pk.` Mapbox token only into the page's masked runtime input, then click **Connect**. Use a public token permitted for the advertised localhost URL with only required read scopes. Do not ask for tokens in chat or place them in URLs, configuration, logs, screenshots, or test captures. The page makes no external requests before Connect and does not persist the token; Disconnect clears the map/token references. Connection loads the pinned provider SDK and provider assets over the network.

Layer order is basemap, warped registered scan, parcel context, recorded deed courses, then selection. Opacity/style changes and selecting a course are presentation operations. Use the keyboard-accessible course list and source panel to inspect original call/page evidence; absent page images remain labeled missing. Attribution must remain visible. SDK, authorization, style, tile/network, or WebGL errors leave the source/course panel and offline evidence/dashboard link usable. A constructed map or loaded style alone does not prove complete tile readiness.

Local model, adapter, browser, and ZIP checks do not establish a live three-layer Mapbox view or reachability from a native Claude/Cowork host. Record actual provider/WebGL and native-host outcomes separately as passed, failed, blocked, or not run. These live/native-host acceptance gates have not been established by this documentation or its evaluation cases.
