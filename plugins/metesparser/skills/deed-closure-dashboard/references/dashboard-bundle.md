# Dashboard bundle reference

The offline dashboard accepts `schema_version: "1.0"` deed-only bundles and `"1.1"` bundles with plot/map fields. Its Pydantic schema is `mp_models.dashboard.DashboardBundle`; the package is the authoritative, versioned contract. This page summarizes the fields and important validation rules without duplicating every model constraint. Version 1.0 remains supported; version-specific validation rejects plot/overlay fields in a 1.0 input instead of silently dropping them.

## Top-level fields

| Field | Purpose |
| --- | --- |
| `title` | Dashboard title. |
| `documents` | Source identity, label, optional SHA-256, and expected page count. |
| `pages` | One indexed source page, reading status, notes, and optional embedded page image. |
| `parcels` | Parcel labels used to group description occurrences. |
| `occurrences` | Each distinct description/version, transcript, its page IDs, and source reading/review status. Repeated descriptions remain separate occurrences. |
| `calls` | Source-linked course quote/text, reading status/note, and optional structured `DeedCall`. Unknown readings must not include an interpreted call. |
| `evidence` | Optional page/call-linked crops, notes, and pixel bounds. |
| `calculations` | Canonical or relative method, frame, assumptions, and optional stated area. |
| `scenarios` | Optional isolated sensitivity presets linked to a calculation and its calls. |
| `presentation` | Subtitle and method notes rendered with the review. |
| `scenes`, `map_sources`, `vector_layers`, `raster_layers`, `placements`, `comparison_specs`, `plot_view` (1.1 only) | Explicit coordinate frame, retained map provenance, projected polygon or registered raster data, rigid deed placement, named point pairs, and presentation settings. |

All IDs are unique across record groups and references must resolve within the same occurrence. Embedded page and evidence images use PNG, JPEG, or WebP data URIs with matching SHA-256. Keep original source files and external acquisition/selection records separately; an embedded image and hash do not attest that it was reviewed.

Version 1.1 plot and optional map behavior is detailed in [plot-and-overlays.md](plot-and-overlays.md). In brief, the renderer derives source-linked line/arc geometry and unresolved-call notices; it does not infer missing bearings. A deed-only version 1.0 bundle remains useful without maps. A scene name is not a coordinate transformation, and a supplied vector layer must already be represented in its declared scene coordinates. Use explicit foot definitions and a placement hash tied to the freshly prepared deed geometry before adding a placement. Overlay/source status is contextual evidence, never a deed geometry status or verification result.

For `canonical`, use `frame.basis: "recorded_bearings"` and source bearings. For `relative`, provide `relative` constraints, use `frame.basis: "arbitrary_local"`, and match its frame name. See [relative-analysis.md](relative-analysis.md) for its structured contract. Relative calculations accept straight courses with source-linked known distances and preserve the record's bearing values; a local frame does not create a recorded bearing.

## Compose existing plot and map artifacts

Reuse original source/acquisition/selection records and `plot-input.json`; `plot-geometry.json` is a derived display artifact, not accepted authoritative dashboard input. Populate `calls` with the preserved `call`, actual quote, and real occurrence/page references, then construct `calculations` with the intended method and frame. Preserve relative constraints and unknown recorded bearings. A `PlotRequest.source_reference` has no direct dashboard field: retain it in the source ledger or a `reading_note` rather than adding an unsupported key. Required document/page/occurrence links and review fields must come from actual evidence; a CSV-only plot with no such evidence cannot supply them. Report missing prerequisites instead of inventing pages or marking records reviewed.

Map preparation is reusable without repeating the command. Append its supported `scenes`, `map_sources`, `vector_layers`, and/or `raster_layers` arrays to those same bundle fields and set `schema_version` to `1.1`. Validate IDs and references; conflicting IDs require an explicit mapping, not silent overwriting. Retain the complete imported/registered artifact as a sidecar. In particular, vector import's top-level `operation` and `original_base64` are not `DashboardBundle` fields; source bytes and processing history are also retained inside `map_sources`. Do not merge the whole preparation object or any prepared calculation/geometry result into the bundle.

This development-workspace example composes a valid source bundle (`BASE_BUNDLE.json`) with an existing map-preparation artifact (`PREPARED_LAYER.json`). It writes a new input file and prints freshly computed dashboard geometry hashes. It has been checked with supplied GeoJSON imported to EPSG:3857 and the synthetic absolute-bearing source bundle; it does not infer placement or source-review evidence.

```sh
uv run python - BASE_BUNDLE.json PREPARED_LAYER.json NEW_BUNDLE.json <<'PYTHON'
import json
import sys
from pathlib import Path
from mp_models.dashboard import DashboardBundle
from mp_review.dashboard import prepare_dashboard

base_path, layer_path, output_path = map(Path, sys.argv[1:])
base = json.loads(base_path.read_text())
layer = json.loads(layer_path.read_text())
base["schema_version"] = "1.1"
for key in ("scenes", "map_sources", "vector_layers", "raster_layers"):
    base[key] = base.get(key, []) + layer.get(key, [])
bundle = DashboardBundle.model_validate(base)
prepared = prepare_dashboard(bundle)
with output_path.open("x") as output:
    output.write(bundle.model_dump_json(indent=2) + "\n")
for geometry in prepared.plots.geometries:
    print(geometry.calculation_id, geometry.geometry_hash)
PYTHON
uv run metes-review dashboard NEW_BUNDLE.json --output-dir NEW_DASHBOARD_DIR
```

An unplaced layer remains independent map context. If placement is requested, finalize the dashboard calls, calculation identity, frame, and explicit foot definition before computing its geometry. Use the freshly computed dashboard hash for the placement's `geometry_hash`, its calculation ID for `calculation_id`, and the imported scene ID for `scene_id`. Supply only the documented rotation/translation and evidence; see [placement and comparison](plot-and-overlays.md). Standalone and dashboard geometry hashes differ because their source/calculation identities differ even when XY coordinates match. Copying the standalone hash produces a stale-placement error; changing the hash alone does not revalidate an old transform. Revalidate the transform against the current geometry and evidence. Rendering recomputes geometry and rejects tampered or stale prepared results.

## Status fields

The renderer reports three separate concepts:

1. `geometry_status`: `analyzed`, `unresolved`, `inconsistent`, or `blocked`. This describes whether the selected calculation could be performed and what it found.
2. `engine_status`: `checks_passed` or `needs_review`. This is canonical engine status. Relative calculations always remain `needs_review`.
3. `source_review_complete`: a derived completeness flag based on supplied page/occurrence/call attestations and expected page coverage. It cannot validate the truth of those attestations or establish source acquisition/selection quality.

For a canonical calculation, `verified_export_eligible` is true only when the canonical geometry checks pass and the calculation's source review and bundle-wide source review are complete. Relative calculations are never engine-verified or export-eligible. The dashboard CLI's top-level `verified_export_eligible` is always false and the command does not write a verified CSV. Scenario outputs are browser-only advisory results and do not change record result fields.

Per-check engine outcomes use `passed`, `failed`, `not_applicable`, and `blocked`. Legacy `CheckResult` payloads with only a `passed` boolean are supported: absent explicit status, true maps to `passed`, false to `failed`; explicit status wins when both fields exist, and serialization synchronizes `passed` to true only for `passed`. A historic boolean is not evidence that a check was skipped or performed; do not upgrade a skip to a pass.

## Output, cache, and invalidation

Run with the plugin's launcher or the package CLI and use an unused output directory:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" dashboard bundle.json --output-dir dashboard-new --cache-dir dashboard-cache
# or, in the development workspace:
uv run metes-review dashboard bundle.json --output-dir dashboard-new --cache-dir dashboard-cache
```

Valid bundles produce top-level `needs_review` (exit 1), not `checks_passed`. The output directory contains these exact artifacts:

| File | Contents |
| --- | --- |
| `source.json` | Original input bundle bytes. |
| `dashboard.html` | Self-contained offline dashboard. |
| `source-review.json` | Source/page/occurrence/call/evidence stage used by calculations. |
| `calculations.json` | Deterministically calculated record results. |
| `plot-geometry.json` | Source-linked plot primitives, chains, and unresolved geometry. |
| `map-layers.json` | Supplied vector/raster layers and retained map sources. |
| `placements.json` | Validated placements and named-point comparisons/residuals. |
| `stage-manifest.json` | Source, calculation, and presentation hashes plus calculator and cache metadata. |
| `render-manifest.json` | Renderer fingerprint, HTML SHA-256, and presentation hash. |

Invalid input/rendering produces `error` (exit 2) with an `invalid_dashboard` detail.

The manifest separates hashes for source-review data, calculation inputs/results, and presentation. A cache hit requires matching source and calculation input hashes plus intact, validated saved stages. Editing source records, page evidence, or calculation specs/assumptions invalidates calculation reuse. Presentation changes, including title, method notes, or scenario presets, have their own hash and can reuse valid calculations. Even after a cache hit, rendering freshly recomputes and validates the deterministic geometry against the bundle before producing HTML; `cache_reused` does not mean geometry checks were skipped. Hash equality proves only that the checked data bytes/stages match; it is not a review log or evidence of a human reading a document.

## Runnable example

[`dashboard-example.json`](dashboard-example.json) is copied from the package's absolute-bearing rectangular fixture. It is synthetic, includes a tiny placeholder image, and demonstrates schema shape and a scenario only. It is not a real deed, native-reading demonstration, evidence of page coverage, or proof that the reader or host reviewed a source.

From the repository root, run it with fresh output/cache paths:

```sh
uv run metes-review dashboard plugins/metesparser/skills/deed-closure-dashboard/references/dashboard-example.json --output-dir /tmp/metesparser-dashboard-example --cache-dir /tmp/metesparser-dashboard-cache
```

## Optional Mapbox companion

Request this renderer step explicitly; the default command remains offline. Read the [online handoff](../../../references/artifact-handoffs.md#optional-online-map-handoff) for inputs, status, accuracy, and invalidation. The companion is a read-only, baseline-only 2D Mercator view; it does not support online scenario edits, terrain, or globe placement.

Install the optional workspace dependencies with `uv sync --extra web-map`. For a packaged plugin, build with `uv run python scripts/build_claude_plugin.py --with-web-map --output dist/metesparser-plugin-web-map.zip`; this includes geo support and cannot be combined with `--without-geo`. Default and minimal distributions retain their offline purpose.

Save this token-free `WebMapRequest` as `online-map-config.json`. Replace `scene-1` with an actual projected scene ID already present in the source bundle:

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
uv run metes-review dashboard bundle.json --output-dir dashboard-online-new --online-map-config online-map-config.json
uv run metes-review serve-map dashboard-online-new --port 8765
```

The plugin launcher accepts the same arguments after `scripts/run-review.py`:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" dashboard bundle.json --output-dir dashboard-online-new --online-map-config online-map-config.json
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" serve-map dashboard-online-new --port 8765
```

A valid dashboard still returns `needs_review` (exit 1). Inspect online availability and reasons separately. The preview prints `http://localhost:8765/online-map.html` immediately and binds only to `127.0.0.1`. Open the advertised `localhost` URL, not a file URL or a different host. It serves only declared display assets and the two HTML views, not the source JSON files. Keep the terminal running; Ctrl-C stops preview. An occupied port fails instead of silently selecting another. For another explicit port, pass it and restrict the token to that exact localhost origin in Mapbox. The viewer sends an origin-only referrer, so do not configure a path-specific restriction.

Enter a public `pk.` Mapbox token only into the page's masked runtime input, then click **Connect**. Use a public token permitted for the advertised localhost URL with only required read scopes. Do not ask for tokens in chat or place them in URLs, configuration, logs, screenshots, or test captures. The page makes no external requests before Connect and does not persist the token; Disconnect clears the map/token references. Connection loads the pinned provider SDK and provider assets over the network.

Layer order is basemap, warped registered scan, parcel context, recorded deed courses, then selection. Opacity/style changes and selecting a course are presentation operations. Use the keyboard-accessible course list and source panel to inspect original call/page evidence; absent page images remain labeled missing. Attribution must remain visible. SDK, authorization, style, tile/network, or WebGL errors leave the source/course panel and offline-dashboard link usable. A constructed map or loaded style alone does not prove complete tile readiness.

Local model, adapter, browser, and ZIP checks do not establish a live three-layer Mapbox view or reachability from a native Claude/Cowork host. Record actual provider/WebGL and native-host outcomes separately as passed, failed, blocked, or not run. These live/native-host acceptance gates have not been established by this documentation or its evaluation cases.
