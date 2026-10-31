# Mapbox local viewer

Commands below use the plugin root that the invoking skill printed; substitute it for `${CLAUDE_PLUGIN_ROOT}`.

Use this mode for a requested local online map. The default dashboard remains offline. Read the [online handoff](../../../references/artifact-handoffs.md#optional-online-map-handoff) for inputs, status, accuracy, and invalidation. The companion is a read-only, baseline-only 2D Mercator view; it does not support online scenario edits, terrain, or globe placement.

In a source checkout, install optional dependencies with `uv sync --extra web-map`. To build a distributable plugin from that checkout, run `uv run python scripts/build_claude_plugin.py --with-web-map --output dist/metesparser-plugin-web-map.zip`; this includes geo support and cannot be combined with `--without-geo`. With an already extracted web-map distribution, use its `scripts/run-review.py` launcher directly; the repository build script is not bundled. Default and minimal distributions retain their offline purpose.

## Compose existing artifacts

The standalone command accepts `StandaloneWebMapInput` (`mp_models.webmap`), not a `DashboardBundle`: `schema_version: "1.0"`, `title`, `plots` (each a `PreparedPlot` containing `request`, `geometry`, `input_hash`), required nonempty `scenes`, and optional `map_sources`, `vector_layers`, `raster_layers`, and `placements`. It creates neither `dashboard.html` nor source-review/verification attestations. IDs must be globally unique across calls, calculations, scenes, map sources, layers, and placements.

Compose an intact existing `plot-new/` stage with supported arrays from one or more prepared overlays. Use the bundled launcher in an extracted distribution; no developer workspace or arbitrary Python execution is required:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" compose-map plot-new --layer prepared-layer.json --output-dir map-composed-new
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" render-map map-composed-new/map-input.json --online-map-config online-map-config.json --output-dir online-map-new
```

In a source checkout, the equivalent first command is `uv run metes-review compose-map plot-new --layer prepared-layer.json --output-dir map-composed-new`. Repeat `--layer` for additional prepared artifacts. Supply enough explicit map evidence to provide at least one scene; a plot alone cannot invent a geographic frame. `import-overlay`, `register-raster`, and `fetch-parcel` outputs provide supported map arrays. Only `scenes`, `map_sources`, `vector_layers`, and `raster_layers` are appended; wrapper metadata and original source bytes remain in the retained preparation sidecars.

Composition writes validated `map-input.json`, `composition-manifest.json`, byte-exact plot inputs/source/manifest under `inputs/plot/`, and complete preparation artifacts under `inputs/layer-N.json`. Its single JSON result and manifest expose `geometry_hashes` keyed by calculation ID. It returns `needs_review` (exit 1), with all three review/verification flags false. Invalid artifacts, ID collisions, stale geometry/hashes, and existing output paths return `error` (exit 2) without overwriting inputs. Composition does not render or contact a provider. Use a fresh output directory.

The command recomputes each plot with shared deterministic geometry and rejects altered geometry or a mismatched plot manifest/source. It preserves requests, relative constraints, unknown bearings, verbatim text, source references, IDs, and provenance. Conflicting IDs require an explicit mapping followed by regeneration of the bound stages; they are never silently renamed. No dashboard source ledger or source-review evidence is created.

The initial composed map has no inferred placements. If placement is requested, use the fresh `geometry_hashes` and actual supplied positioning evidence to add supported `placements` to `map-input.json`, then render it. Keep the composition manifest and original preparation sidecars. The renderer independently recomputes plots and rejects stale or altered geometry/input hashes and placements. If call/calculation IDs or the plot request change, regenerate the plot and compose again; never substitute a dashboard hash. This deterministic display preparation is not verification or document reading.

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

Each raster scan has its own visibility checkbox, opacity slider, and accessible raise/lower controls; controls and stacking order are reapplied after a style reload. Scans can be reordered among themselves, while basemap stays below, and parcel context, deed courses, closure, and selection stay above them. The controls are in-session presentation state only. They do not alter original raster bytes, registration controls/residuals, geometry, placement, or verification, and no cross-session persistence is claimed.

The offline evidence panel reports each scan's registration status, fit-control count and RMS, independent checkpoint count and RMS (with units), source label/file/hash/provider/date, and scene/CRS/units. Zero checkpoints explicitly means independent checkpoint accuracy is unknown. A small fit residual is not an accuracy estimate. The deed summary reports frame, bearing basis, foot definition, placement status, and unknown numerical placement uncertainty. Recorded bearings alone do not establish geographic north; display/projection tolerances are not ground-accuracy claims. Preserve the supplied `unplaced` / `approximate` / `referenced` statuses.

Layer controls, style changes, and selecting a course are presentation operations. Use the keyboard-accessible course list and source panel to inspect original call/page evidence; absent page images remain labeled missing. Attribution must remain visible. SDK, authorization, style, tile/network, or WebGL errors leave the source/course panel and offline evidence/dashboard link usable. A constructed map or loaded style alone does not prove complete tile readiness.

Local model, adapter, browser, and ZIP checks do not establish a live three-layer Mapbox view or reachability from a native Claude/Cowork host. Record actual provider/WebGL and native-host outcomes separately as passed, failed, blocked, or not run. These live/native-host acceptance gates have not been established by this documentation or its evaluation cases.
