# Plan 001: Display recorded deed geometry and tax maps over Mapbox

> **Executor instructions:** Read this entire plan and the current `AGENTS.md` before changing code. The parent owns integration, shared contracts, acceptance evidence, and `plans/README.md`. Workers implement only their assigned files. Start each behavior with a failing regression, record the failure, implement the smallest passing change, and rerun the owning test suite. Stop the affected packet and report a concrete blocker when a boundary below cannot be met; independent packets may continue.
>
> **Planning status:** No implementation, tests, dependency installation, build, commit, or live Mapbox acceptance was performed while preparing this plan. Three read-only subagents inspected geometry/registration, viewer/runtime integration, and tests/skills/distribution. Proposed files, APIs, commands, and test names below do not exist yet unless identified as current.

## Status and objective

- Priority: P1
- Effort: L; three implementation waves plus integration and acceptance
- Risk: HIGH for geographic correctness; MED for runtime and packaging
- Category: direction / feature
- Planned at: `f05338f93adeb88f1f4fe8b0e43cd1f30a60493b`, 2026-10-27
- Branch observed: `feat/deed-closure-dashboard-skill`, two commits ahead of its upstream
- Dependencies: existing `PreparedDashboard`, plot placement, registered raster, and source-review contracts

Produce an optional, read-only `online-map.html` companion to the existing offline dashboard. A reviewer can connect to Mapbox, see a street or satellite basemap, place an already registered tax-map scan over it, and inspect recorded deed calls above both. Map selections and an accessible course list show the original source evidence. Map interactions must never modify calls, closure results, source-review attestations, placement evidence, or verified-export eligibility.

The tax map helps establish geographic placement through the existing registration workflow. Displaying a scan on Mapbox does not supply missing control points, a datum, or a bearing basis. The example HTML pasted in the conversation is illustrative, not an authoritative property fixture or a source of new boundary data.

## Preflight, drift, and existing work

Run from the repository root:

```sh
git status --short --branch
git worktree list --porcelain
git diff --stat f05338f93adeb88f1f4fe8b0e43cd1f30a60493b..HEAD -- packages/mp-models packages/mp-review packages/mp-export src/metesparser/dashboard.py scripts/build_claude_plugin.py scripts/check_dashboard_browser.py plugins/metesparser tests pyproject.toml uv.lock Makefile AGENTS.md README.md docs plans
```

Expected: identify the actual branch and all current edits before dispatch. Compare any changed implementation against the excerpts below. If an API has drifted, parent revises this plan before workers depend on it. Do not reset, stash, delete, or rebase someone else's work to match this SHA.

At planning time these nine documentation files already had intentional uncommitted changes:

```text
AGENTS.md
README.md
docs/ARCHITECTURE.md
docs/CLAUDE_PLUGIN.md
docs/CONTRIBUTING.md
plugins/metesparser/CHANGELOG.md
plugins/metesparser/README.md
plugins/metesparser/references/usage.md
plugins/metesparser/skills/prepare-parcel-overlay/README.md
```

Preserve them. The documentation worker must read and extend their current content rather than replace it with HEAD. Stay on an appropriate feature branch; never push to `main`. No worker commits. Commit/push/PR work requires a subsequent user instruction; before an authorized commit run the repository's required `make pre-commit` and inspect any formatter changes.

## Current state and extension points

Line numbers refer to the planning SHA and are navigation hints, not patch offsets.

| Existing location | Relevant responsibility |
|---|---|
| `packages/mp-models/src/mp_models/plot.py:21` | `PlotScene`: local/projected XY, explicit CRS and linear units |
| `packages/mp-models/src/mp_models/plot.py:178` | `PlotPlacement`: rotation/translation and evidence bound to a geometry hash |
| `packages/mp-models/src/mp_models/raster.py:29` | Approximate raster registration with fit/checkpoint residuals |
| `packages/mp-verify/src/mp_verify/plot.py:292` | Fresh plot construction and stale-placement rejection |
| `packages/mp-verify/src/mp_verify/plot.py:375` | `arc_point()`; `transform_point()` at line 410 handles placement and units |
| `packages/mp-review/src/mp_review/overlays.py:126` | Existing projection policy: XY order, no ballpark transform, network grids disabled |
| `packages/mp-review/src/mp_review/raster_registration.py:25` | Raster outer edges use half-pixel offsets; actual image validation at line 168 |
| `packages/mp-review/src/mp_review/dashboard.py:58` | Fresh calculation/geometry even when reusable stages exist |
| `packages/mp-review/src/mp_review/dashboard.py:123` | `dashboard_file()` stages exact source and deterministic artifacts |
| `packages/mp-export/src/mp_export/dashboard_html.py:494` | Offline renderer; strict offline CSP at line 538 |
| `packages/mp-export/src/mp_export/dashboard_assets/dashboard.js:95` | Frozen baseline, separate offline scenarios, source selection and layer controls |
| `src/metesparser/dashboard.py` | Thin compatibility facade; do not duplicate projection logic here |
| `scripts/build_claude_plugin.py:28` | Locked runtime dependency assembly; six engine wheels at line 18 |
| `plugins/metesparser/scripts/run-review.py:66` | Command allowlist, settings injection, subprocess execution |
| `tests/browser/test_dashboard_plot_ui.py:101` | Records and aborts outbound requests for offline acceptance |

Personally inspected excerpts establish the boundaries:

```python
# mp_models/plot.py:178 (excerpt)
class PlotPlacement(_Model):
    id: Identifier
    calculation_id: Identifier
    geometry_hash: Digest
    scene_id: Identifier
    rotation_deg: FiniteFloat = 0.0
    translation: XY = (0.0, 0.0)
    status: Literal["unplaced", "approximate", "referenced"] = "approximate"
```

```python
# mp_review/dashboard.py:58 (excerpt)
fresh = calculate_dashboard(bundle)
bundle = fresh.bundle
if bundle.raster_layers:
    from .raster_registration import validate_raster_layer
    scenes = {scene.id: scene for scene in bundle.scenes}
    for layer in bundle.raster_layers:
        validate_raster_layer(layer, scenes[layer.scene_id])
```

```python
# mp_review/raster_registration.py:25 (outer-corner convention)
(-0.5, -0.5)
(width - 0.5, -0.5)
(width - 0.5, height - 0.5)
(-0.5, height - 0.5)
```

Current `dashboard_file(path, output_dir, *, cache_dir=None)` writes `dashboard.html`, exact `source.json`, source-review/calculation/geometry/map/placement stages, manifests, and retained source assets. Its normal review status is `needs_review`; `verified_export_eligible` remains false even when engine calculations pass. New display artifacts must not replace these stages or alter their meaning.

Use existing immutable Pydantic conventions (`extra="forbid"`, finite numbers, frozen models), safe HTML/JSON escaping, validated identifiers, and hashed renderer assets. Only `mp-ocr` calls LLMs; this entire addition is deterministic downstream work.

## Scope and settled design

### Release scope

1. One explicit projected scene per online companion, with already validated deed placements and optional registered rasters/supplied parcel vectors in that scene.
2. Recorded baseline geometry only, including genuine curve shapes, partial traverses, POB, and separately styled closure gaps.
3. Mapbox Standard and Standard Satellite, pan/zoom, fit to available evidence, layer visibility/opacity, source-linked selection, accessible course list, and offline fallback.
4. Deterministic geographic display preparation, inspectable provenance, runtime-only public token, loopback preview, plugin packaging, and composable skill documentation.

Deferred: online scenario editing; registration/control-point editing; automatic address geocoding or alignment; fitted deed stretching; boundary editing; new parcel-data acquisition; terrain/globe/3D; dateline-spanning parcels; provider uploads; map image/PDF export; hosted deployment; alternate providers. Existing offline scenarios continue unchanged. No new vendor-specific skill and no new web application framework.

### Composition

```text
Existing source preparation / review / verification
                     |
              PreparedDashboard
                     |
       +-------------+--------------------+
       |                                  |
existing offline renderer       geographic display preparation
       |                         /                      \
 dashboard.html       placed calls / vectors       registered scan
                                 |                raster reprojection
                                 +-----------+----------+
                                             |
                               provider-independent WebMapArtifact
                                             |
                                 Mapbox companion renderer
                                             |
                                online-map.html + local assets
```

Bottom-to-top online stack: Mapbox basemap → registered tax-map rasters → supplied parcel outlines → recorded deed lines/labels/POB/closure gap → selection. Keep source map labels/attribution and registration quality accessible. Parcel outlines and tax scans remain assessment/context evidence, distinct from deed calls.

Keep `DashboardBundle` unchanged unless Phase 0 proves an existing contract cannot represent required evidence. Store online configuration separately. Omission of the new option must leave the offline HTML, stages, fingerprints, and public behavior unchanged. Online generation must produce that same offline dashboard as its companion; navigation back to it lives in the online shell and CLI result, not a conditional rewrite of offline HTML.

### Mapbox runtime choice

The official CDN guide currently shows GL JS **3.33.0**. Treat that as the candidate for Phase 0: retrieve the exact matching JS/CSS bytes, verify they work, then pin version, URLs, and computed integrity digests in one descriptor. Never invent digests or use a floating version. No npm project or Python Mapbox SDK is needed. [Official CDN guide](https://docs.mapbox.com/mapbox-gl-js/guides/get-started/use-with-cdn/)

Use `mapbox://styles/mapbox/standard` and `mapbox://styles/mapbox/standard-satellite`. Keep Mercator, pitch zero, terrain disabled, and supported 3D-object configuration disabled. Reapply these constraints after style changes. These are live provider styles: record their identifiers and SDK version, but do not promise deterministic provider imagery. [Standard](https://docs.mapbox.com/map-styles/reference/standard/), [Standard Satellite](https://docs.mapbox.com/map-styles/reference/standard-satellite/)

Add review layers without a Standard basemap slot, in explicit review order above the basemap. Use an idempotent `ensureReviewLayers()` after `style.load`; preserve selected call, layer visibility, opacity, and camera across style reloads. Verify actual rendering order with the pinned SDK: globe/terrain draping can change ordering, which is why those modes are excluded. [Layer ordering](https://docs.mapbox.com/mapbox-gl-js/guides/styles/work-with-layers/)

The online CSP is separate from the offline CSP. Derive allowed SDK, style/font/tile/session/event origins and worker/WASM requirements from the pinned runtime, document them in its descriptor, and verify them in browser acceptance. Standard currently needs WASM permission; use only the permissions the selected runtime requires. Do not solve a failure with wildcard network access or relax the offline policy. [Security and testing](https://docs.mapbox.com/mapbox-gl-js/guides/security-and-testing/)

## Contracts to freeze before parallel implementation

The parent writes contract tests and model definitions first. Downstream workers import these definitions; they do not create competing shapes. The names below are the intended public API. Any necessary change must be broadcast before dependent work resumes.

### Input configuration

New immutable models in `mp_models/webmap.py`:

- `WebMapOptions`: display sampling and raster limits, independent of Mapbox.
- `MapboxViewOptions`: `provider="mapbox"`, `style` enum `standard|standard-satellite`, initial raster opacity in `[0,1]`. No free-form remote URLs or access tokens.
- `WebMapRequest`: `schema_version="1.0"`, `scene_id`, `display: WebMapOptions`, `view: MapboxViewOptions`.

Initial explicit defaults: display tolerance `0.05` EPSG:3857 meters; maximum subdivision depth `20`; maximum total vector vertices `100000`; raster output pixel size `0.25` EPSG:3857 meters; maximum output width/height `4096`; maximum total output raster pixels `16777216`. All limits apply before allocation and across the selected scene. Validate positive finite values and enforce these resource ceilings; users can request lower budgets or a coarser raster resolution, not silently override the ceilings. These are display settings, not survey tolerances. If requested resolution exceeds the budget, report it; never silently coarsen imagery.

Example of the **planned** config, with defaults omitted:

```json
{
  "schema_version": "1.0",
  "scene_id": "nj-grid",
  "display": {},
  "view": {"provider": "mapbox", "style": "standard", "raster_opacity": 0.55}
}
```

Reject unknown fields including token/credential fields without echoing their values. Do not persist invalid raw configs in error artifacts. Scene IDs and placements must come from the actual bundle; the example ID does not establish a CRS.

### Derived display artifact

`WebMapArtifact` is a provider-independent JSON sidecar with:

| Field group | Required meaning |
|---|---|
| Identity | Schema/adapter version, scene ID, canonical input-stage hashes, normalized display-options hash |
| Projection | Source CRS definition, scene units, selected operation(s)/pipeline(s), target EPSG:3857/4326, library and projection-database versions, reported operation accuracy where available |
| Vectors | Typed GeoJSON features: `LineString` per recorded primitive; separate POB `Point` and closure-gap `LineString`; supplied parcel Polygon/MultiPolygon features with holes preserved |
| Feature identity | Stable `id`, `kind`, calculation/call/occurrence/page IDs where applicable, source/layer ID, geometry and placement hashes/status; absence is explicit when an upstream ID is absent |
| Raster records | Source/layer/registration hashes, derived PNG path/hash, source/target CRS and operation, grid affine/dimensions/resolution, resampling/nodata policy, outer WGS84 corners, original registration status and residuals |
| Availability | Per-calculation/layer code and reason, aggregate `ready|partial|unavailable`, counts of included/omitted items; no invalid input disguised as an omission |
| Bounds | Finite WGS84 bounds from included evidence, or null when unavailable; no guessed address/location |

Feature `kind` must distinguish `recorded_course`, `closure_gap`, `pob`, and `parcel_context`. A closure gap has no call ID and never participates in measured courses. Closed parcel context polygons are allowed; converting an open deed traverse into a polygon is not. Derived feature coordinates are `[longitude, latitude]`; model validation rejects nonfinite or out-of-domain values.

Define `PreparedWebMap` as a frozen in-memory review-layer result containing `artifact` plus a tuple of `(relative_path, PNG_bytes)` for generated rasters. The model artifact stores references/hashes, not base64 copies. Sorting, stable IDs, and canonical JSON produce repeatable outputs within a pinned runtime; compare hashes across repeat runs. Do not promise PNG byte equality across different GDAL/PROJ builds.

Public interfaces:

```python
# mp_review.webmap -- fresh validation is mandatory, including direct API callers
prepare_web_map(
    prepared: PreparedDashboard, *, scene_id: str, options: WebMapOptions
) -> PreparedWebMap

# mp_review.webmap_projection -- shared operation selection for both workers
build_web_map_projection(scene: PlotScene) -> WebMapProjection

# mp_review.webmap_raster -- no arbitrary filenames or network sources
prepare_web_map_raster(
    layer: RasterLayer, scene: PlotScene, *,
    projection: WebMapProjection, options: WebMapOptions
) -> PreparedRaster

# mp_export.online_map_html -- serializes and renders; performs no geographic math
render_online_map(
    prepared: PreparedDashboard, artifact: WebMapArtifact, *, view: MapboxViewOptions
) -> str
online_renderer_fingerprint() -> str

# extend existing API with an optional validated request
dashboard_file(path, output_dir, *, cache_dir=None, online_map: WebMapRequest | None = None)
```

`WebMapProjection` and `PreparedRaster` are private review-layer helper contracts; freeze their fields in Phase 0 along with the public models. The projection helper supplies the shared axis-aware scene→3857 operation and 3857→4326 conversion. Record/hash those operations in every dependent artifact. It must not make `mp-models` import pyproj/Rasterio, or make `mp-export` depend on `mp-review`.

### Geographic correctness

1. Validate prepared inputs against fresh calculations and raster validation. Never trust a caller's copied `PreparedDashboard` or persisted map sidecar solely because hashes are present.
2. Follow existing `transform_point()` for primitive→placed scene coordinates, with declared native and scene units. Distinguish international feet from US survey feet; reject unknown feet for geographic display.
3. Transform scene→EPSG:3857 with explicit XY ordering, required grids available, and ballpark disabled. Disable network grids in both pyproj and GDAL; never silently select a lower-quality fallback.
4. Adaptively sample true curves **and straight segments** when projection bends them. Check quarter, midpoint, and three-quarter deviations against the projected chord; preserve exact endpoints. Test withheld positions independently. At resource/depth limits report an unavailable feature/calculation rather than accepting excess error.
5. Convert the accepted 3857 samples to EPSG:4326. Preserve source call identity and already established partial-traverse boundaries. Never bridge a missing-bearing gap or extrapolate an unknown endpoint.
6. Reject unsupported antimeridian crossing, invalid projection domain, and latitudes beyond Web Mercator's approximately ±85.05112878°. Do not wrap or clamp them into a plausible parcel.
7. A display-error bound does not establish registration accuracy, ground distance, or verified status. Retain each placement's `approximate`/`referenced` status and source residual units.

### Raster correctness

Use maintained Rasterio reprojection under a new optional `web-map` extra. Keep current default/`geo` dependency behavior intact; no home-grown warp engine. Declare NumPy directly if the implementation imports it. Root extra forwards `mp-review[web-map]`. Lock supported versions only after the Phase 0 compatibility test. [Rasterio reprojection](https://rasterio.readthedocs.io/en/stable/topics/reproject.html)

Always create a derived, north-up EPSG:3857 RGBA PNG for MVP. Preserve original bytes, registration, controls, and residuals. The registration matrix maps pixel **centers**; when constructing a corner-based GDAL affine, convert:

```text
x = a*u + b*v + c       y = d*u + e*v + f
c_edge = c - 0.5*a - 0.5*b
f_edge = f - 0.5*d - 0.5*e
```

Densify projected image bounds before choosing the output grid; validate finite extent and budgets first. Use a recorded bilinear resampling policy with transparent nodata and alpha-aware handling; test dark text/transparent edges to prevent halos or a black background. Derive Mapbox image corners from output **outer edges**, clockwise top-left, top-right, bottom-right, bottom-left. A four-corner-only transform of the original scan is not an allowed fallback.

Use the same selected scene→3857 coordinate operation for vector and raster paths. Pyproj and Rasterio may bundle different PROJ databases/grids. Prove an explicit, axis-correct GDAL `COORDINATE_OPERATION` works with the selected runtime and independent controls. `ALLOW_BALLPARK`/`ONLY_BEST` transformer options are version-dependent (documented for GDAL 3.11+); setting unsupported flags is not proof. If exact operation enforcement or needed grids cannot be established, the affected raster is unavailable and three-layer acceptance remains incomplete. [GDAL transformation options](https://gdal.org/en/stable/api/gdal_alg.html)

### Staging, tokens, and preview

Additional staged artifacts: `web-map-request.json`, `web-map.json`, `online-map.html`, `web-map-manifest.json`, and `web-map-assets/<validated-layer-id>.png`. The separate manifest covers canonical input hashes, normalized request, artifact, renderer/SDK descriptor, HTML, and derived asset hashes. Changing view options invalidates only online presentation; changing display options/registration/placement/geometry invalidates the relevant derived data. Do not store timestamps in deterministic payloads.

Planned CLI:

```sh
uv run metes-review dashboard bundle.json --output-dir output/map-review --online-map-config map-view.json
uv run metes-review serve-map output/map-review --port 8765
```

The output directory must be new, matching current behavior. Preparation never contacts Mapbox. Valid but non-geographic evidence produces an explicit online `partial`/`unavailable` summary alongside a usable offline artifact; malformed inputs, stale placements, or tampering are errors. No included evidence means no Connect action. Preserve the existing top-level review/verified status and add online availability separately. Stage/validate the complete optional artifact set before advertising a runnable online URL; do not expose half-written online assets.

`serve-map` is a foreground read-only loopback server. Bind `127.0.0.1` and advertise **`http://localhost:<port>/online-map.html`**, with default port **8765**. An explicit `--port` accepts 1–65535; port zero/automatic assignment is unsupported. On conflict fail with an actionable message, never silently choose another port. Validate a bounded generated-file allowlist and hashes at startup; serve only the two HTML views and their declared display assets. Deny traversal, symlink escapes, unexpected Host headers (allow only `localhost:<selected-port>`), directory listing, raw source/stage/config files, and writes. Use matching MIME types and `Referrer-Policy: strict-origin`. Do not proxy provider requests or launch a browser automatically.

The hostname matters: Mapbox URL restrictions do not support IP-address URLs and localhost must be explicitly allowed. Document a dedicated URL-restricted public token for the advertised origin/port; choosing an explicit different port requires a matching token URL restriction. Restricted tokens require referrer information. [Mapbox token restrictions](https://docs.mapbox.com/accounts/guides/tokens/)

Enter the public browser token in a password field and click **Connect map**. Reject secret-token input; keep accepted tokens in memory only, clearing the input after connection and clearing app/SDK token references on disconnect. No token in config, bundle, settings, URL/query/fragment, browser storage, generated files, manifests, CLI arguments, screenshots, or logs. The browser SDK necessarily sends its public token to Mapbox; do not describe it as hidden from the provider or browser developer tools. Explain before connection that online basemap requests reveal the viewed area to Mapbox; no deed or scan upload API is part of this feature.

Before Connect, loading either local view must cause **zero external HTTP(S) attempts**: no SDK, CSS, preconnect, remote fonts, tiles, or telemetry. On connect load only pinned SDK/CSS, then initialize the map. Failures retain the accessible course/source view and offline link. Use sanitized error codes for missing/invalid token, 401/403, timeout/network, style, WebGL/context loss, and missing georeference. Avoid rendering provider error objects or token-bearing request URLs. Retry/disconnect must not accumulate map instances or event handlers. Do not claim that removing the map can retract already in-flight requests.

## Agent ownership and execution waves

At most **three workers plus parent**. Prefer `gpt-6.1-sol` with medium reasoning for bounded implementation. Use the parent/current stronger model for projection decisions and integration review. `gpt-6-luna` is suitable for the documentation packet once commands/contracts are settled; escalate a concrete blocker to the parent rather than repeatedly retrying with a small model. If these models are unavailable, retain the same bounded ownership with available models.

| Packet | Exclusive ownership | Dependencies |
|---|---|---|
| P0 — parent | New models `mp_models/webmap.py`, their tests/public exports; `mp_review/webmap_projection.py` and its tests; root/package extras, `uv.lock`; SDK descriptor; contract decisions | Preflight |
| A — geographic vectors | New `mp_review/webmap.py`, `tests/test_webmap.py` under mp-review, vector fixtures | P0 |
| B — tax raster warp | New `mp_review/webmap_raster.py`, `tests/test_webmap_raster.py`, raster fixtures under mp-review | P0 |
| C — online renderer | New `mp_export/online_map_html.py`, `dashboard_assets/online_map.js`, `online_map.css`, `mp-export/tests/test_online_map_html.py` | P0; synthetic frozen contract fixture |
| D — staging and preview | `mp_review/dashboard.py`, `mp_review/cli.py`, new `mp_review/map_preview.py`; dashboard/preview tests; plugin launcher and launcher tests | A/B/C integrated by parent |
| E — browser acceptance | New `tests/browser/test_online_map_ui.py`, `test_mapbox_sdk.py`, `test_mapbox_live.py`; new synthetic browser fixtures and `scripts/check_mapbox_browser.py` | C contract/UI selectors; D server |
| F — skill/docs | Documentation and eval files listed below | Final CLI/artifact contract from D |
| P1 — parent integration | Package public exports, compatibility facade, Makefile, build script, build tests, index, shared contract fixes, final review/evidence | All packets |

Wave 0: P0 only. Wave 1: A/B/C concurrently. Parent integrates A's orchestration with B's helper after both pass; B must not edit A's file. Wave 2: D/E/F concurrently after A/B/C integration; E can begin with fixtures while D completes the server. Wave 3: parent packaging, all gates, and an independent read-only reviewer. No worker changes shared manifests, dependency files, public exports, or another worker's tests without reassignment.

### P0: Freeze contracts and prove runtime compatibility

1. Read current plot/source/registration models, tests, package extras, and handoff docs. Capture a baseline test result before edits; distinguish preexisting failures from new failures.
2. Write failing model tests for absent/extra/token fields, finite coordinate ranges, defaults/limits, feature ID/provenance requirements, explicit unavailable states, deterministic serialization, and separate view/display hashing.
3. Implement the small model/helper contracts. Establish shared `WebMapProjection` selection/serialization, no-network policy, axis order, operation/domain checks, and dependency absence behavior. Private helper types must not leak GIS imports into zero-GIS packages.
4. In an isolated test environment, choose/lock Rasterio compatible with supported Python/macOS and the intended plugin host. Compare independently known vector and raster controls under the exact selected operation; check actual GDAL/PROJ versions/grids. Network and ballpark must be disabled. Resolve this before delegating production warp logic.
5. Retrieve candidate Mapbox SDK/CSS, compute descriptor hashes, verify official runtime/CSP/Standard configuration with a minimal local probe. Do not require a user token for model work; report live provider proof separately. Fetching SDK assets requires normal network authorization; do not add automatic downloads to ordinary tests.
6. Freeze fixture/model/API/selector contracts and broadcast them. Create `test_webmap_models.py` under mp-models and `test_webmap_projection.py` under mp-review. Record red and green commands/output in the parent handoff.

Verify: `uv run pytest packages/mp-models/tests/test_webmap_models.py packages/mp-review/tests/test_webmap_projection.py --no-cov --import-mode=importlib` → all new tests pass after an observed RED. Import `mp_models` and existing offline review/export in an environment without the `web-map` extra → no GIS import error. Missing mandatory transform/dependency → typed unavailable reason, never a corner-only fallback.

### A: Prepare geographic vectors from canonical primitives

Implement `prepare_web_map()` using freshly validated prepared inputs, existing placement math, P0's operation, adaptive sampling, and stable source-linked GeoJSON. Coordinate with B through the frozen raster helper interface; initial tests can provide a synthetic `PreparedRaster`, but final parent integration must call the real helper.

RED cases in `packages/mp-review/tests/test_webmap.py`:

- Independently calculated placed square/rotated triangle in meters, international feet, and US survey feet; known longitude/latitude axis order and coordinates.
- Quarter and major arcs keep analytic endpoints and correct bulge; independent withheld samples meet display tolerance. An endpoint-only chord implementation fails.
- A long/nonlinear transformed straight segment is subdivided; endpoint-only transformation fails the tolerance test.
- Partial traverse stops where numeric information ends; no invented bridge, call, polygon, or POB-to-end closure course.
- An actual closure gap is a separate feature with no recorded call ID; a true closing recorded call retains its identity.
- Supplied polygon holes and MultiPolygon components retain topology and source IDs after bounded edge sampling.
- Unplaced/local/unknown-unit/out-of-domain/dateline/missing-grid cases are explicit omissions; stale or tampered prepared content is an error. Limit failure omits the affected calculation/layer, not an arbitrary portion that looks complete.
- Source, calculations, native geometry, placement, verification and registration dumps/hashes are equal before/after preparation; repeat run is identical.

Verify: `uv run pytest packages/mp-review/tests/test_webmap.py packages/mp-review/tests/test_scene_validation.py packages/mp-review/tests/test_dashboard_plot_stages.py --no-cov --import-mode=importlib` → all pass; provide independent fixture derivation and RED failure evidence, not expected values copied from actual output.

### B: Reproject registered tax-map scans

Implement `prepare_web_map_raster()` with validated source bytes/registration, the shared operation, center→edge affine conversion, densified bounds, bounded north-up output, recorded resampling, and a hash-addressed derived record. Use synthetic images generated by test code; do not copy commercial map tiles or use the pasted example as ground truth.

RED cases in `packages/mp-review/tests/test_webmap_raster.py`:

- Asymmetric checkerboard with four distinct corners, a center mark, rotation/skew, and independently known outer-edge coordinates exposes half-pixel/top-bottom errors.
- Nonlinear projected scan: withheld interior checkpoints match independent transforms within the documented pixel/resampling allowance; original four-corner overlay fails this fixture.
- Same coordinate operation is used for vector controls and raster reprojection despite separate library runtimes; missing required grids/unsupported enforcement produces unavailable.
- Source alpha, opaque white background, dark text, nodata edges and bilinear resampling render correctly; transparent pixels do not create black margins/halos.
- Tampered image bytes/dimensions/registration, nonfinite extents, excessive decoded/output pixels and resource limits fail before warp allocation.
- Original controls, residuals and source bytes remain unchanged; output manifest describes derivation rather than replacing original registration accuracy.

Verify: `uv run pytest packages/mp-review/tests/test_webmap_raster.py packages/mp-review/tests/test_raster_registration.py --no-cov --import-mode=importlib` → all pass, with independent center/checkpoint assertions. Missing raster dependencies must never pass the three-layer acceptance case by skipping the raster.

### C: Build the baseline Mapbox companion

Implement `render_online_map()` and small browser assets. Consume supplied geographic features; no browser projection engine or copied traverse calculator. Render source details from the validated bundle with escaping/`textContent`; resolve feature IDs to original call/occurrence/page records. Source images absent upstream remain explicitly unavailable. No need to refactor offline `dashboard.js` for this baseline-only release.

Freeze accessible selectors for E: `data-testid="map-connect"`, `map-disconnect`, `map-status`, `map-style`, `map-source-panel`, `offline-link`, plus `data-map-call="<call-id>"` course controls and `data-map-layer="<layer-id>"` layer controls. Token entry has an accessible label. Use a small dependency-injected provider adapter for mocked tests without exposing a production arbitrary-script URL setting.

RED tests cover safe script serialization (`</script>`, HTML metacharacters, U+2028/U+2029), exact allowed descriptor/config use, no token persistence/value echo, offline renderer unchanged, renderer fingerprint coverage, absent-georeference status, and immutable inputs. Browser behavior includes keyboard selection, source-page modal/focus return, visible placement/registration status, unavailable counts, source legend, and map attribution. Avoid canvas-only access.

Connect is the only provider activation. Style switching preserves review layers/state, with one handler per event; disconnect tears down instances and clears token references. Keep a persistent offline link and local source/course panel through SDK, authorization, style, network, and WebGL failures. Keep a visible status for missing/unavailable tiles; do not equate a map constructor or `style.load` alone with complete live readiness.

Verify: `uv run pytest packages/mp-export/tests/test_online_map_html.py packages/mp-export/tests/test_dashboard_html.py packages/mp-export/tests/test_dashboard_plot.py --no-cov --import-mode=importlib` → all pass; offline default remains byte-identical for identical prepared input and retains its no-network CSP. Parent verifies the asset descriptor is included in the online fingerprint.

### D: Add optional staging and a bounded preview command

Extend `dashboard_file()` and CLI with the optional request; generate the offline result as before and stage optional artifacts/manifests with their own availability. Add `serve-map`. Use established result/error conventions, but do not echo invalid token/config values through validation exceptions. Server request logging must not retain query strings. Reject query-bearing application requests if they are unnecessary.

Update launcher allowlist/settings support. Its current `subprocess.run(..., capture_output=True)` buffers output until exit; a long-running preview needs a **serve-map-only foreground streaming path** so the URL is visible immediately and interrupt signals/exit codes propagate. Retain current JSON capture behavior for existing commands. Parent owns build-script changes.

RED tests in new `test_webmap_cli.py`/`test_map_preview.py` and existing launcher tests:

- Omitted flag leaves offline artifacts/result behavior unchanged; valid config stages expected files with matching hashes; view changes affect only online presentation; source/geometry changes invalidate online preparation.
- `partial` and `unavailable` render usable offline output and explicit reasons; malformed config, stale geometry or tampering is an error, with no runnable incomplete online stage.
- Config with token-like unknown fields never echoes/persists the submitted value.
- Preview serves declared files with correct content types/referrer policy, binds loopback only, rejects other Host values, traversal/encoded traversal, symlinks, raw source JSON/assets and nonallowlisted paths. Tampered declared assets fail validation.
- Occupied default port fails; an explicit different port is printed/documented. URL arrives before process exit; Ctrl-C stops parent/child cleanly with no orphan listener.
- Plugin settings/disabled behavior and existing launcher command output remain compatible.

Verify: `uv run pytest packages/mp-review/tests/test_webmap_cli.py packages/mp-review/tests/test_map_preview.py packages/mp-review/tests/test_dashboard_cli.py plugins/metesparser/tests/ --no-cov --import-mode=importlib` → all pass. Add a subprocess test proving the launcher URL appears while the preview process is alive.

### E: Prove browser behavior at distinct acceptance levels

Use existing Playwright patterns. Keep the offline outbound-request assertion unchanged in intent. Default test collection must not accidentally perform live requests; dedicated targets must fail clearly when opted-in prerequisites are absent instead of reporting an all-skipped success.

| Lane | Test location / implementation | What it proves |
|---|---|---|
| Offline | Existing browser files plus unopened online companion case | Zero external request attempts before Connect; offline functionality |
| Adapter | `tests/browser/test_online_map_ui.py`, synthetic provider stub | Layer order/state, event wiring, failure recovery, source links, keyboard/mobile usability, immutable records |
| Real SDK local | `tests/browser/test_mapbox_sdk.py`, pinned SDK cached outside tracked files; synthetic local style/data | Actual SDK/API integration and CSP/worker startup where supported; token-free `testMode` is logic coverage, not live map/visual acceptance |
| Live provider | `tests/browser/test_mapbox_live.py`, explicit opt-in and runtime public token | Actual Standard/satellite tiles, WebGL visual composition, attribution, style reload, authorization, source selection and errors |

Required adapter scenarios: baseline/scan/parcel/deed/selection ordering; opacity zero/half/full; style switch repeated twice; call selection from map and keyboard list; page evidence/missing page; disconnect/retry; no duplicate instances/listeners; missing token, 401, 403, timeout, blocked network, SDK load error, style error, WebGL unavailable/context loss; no guessed map placement; baseline hashes unchanged throughout. Test at desktop and narrow mobile widths.

Real-SDK tests must not pretend the fake adapter tests WebGL. Mapbox documents `testMode` as token-free, browser-based and without visual output; label its evidence accordingly. For visual acceptance use live styles and inspect a synthetic referenced deed plus asymmetric registered raster at a known coordinate. Assertions must confirm all three layers are visibly present, not merely that sources exist in the SDK. [Official testing limitations](https://docs.mapbox.com/mapbox-gl-js/guides/security-and-testing/)

New preflight `scripts/check_mapbox_browser.py` verifies Chromium/WebGL requirements and exact SDK cache bytes against the descriptor. Parent adds `make test-mapbox-browser` for deterministic adapter/local-SDK tests and `make test-mapbox-live` for explicit provider smoke. SDK fetching is an explicit setup action; missing cache is a prerequisite failure in that lane. Keep real tokens out of Playwright traces, video, HARs, screenshots of inputs, stdout and failure dumps. Disable raw capture; retain sanitized host/path-category/status counts and safe screenshots after clearing token input. Supply a live token via an existing secret/environment facility, never ask for it in chat.

Verify: `make test-dashboard-browser` and proposed `make test-mapbox-browser` → non-skipped mandatory cases pass; zero pre-connect outbound attempts. Proposed `make test-mapbox-live` → passes with real network/credential or is explicitly reported `blocked`/`not run`. A mocked pass cannot satisfy that gate.

### F: Document composition and update skill evaluations

Exclusive documentation/eval scope:

- `plugins/metesparser/references/artifact-handoffs.md`
- `plugins/metesparser/references/usage.md`
- `plugins/metesparser/skills/prepare-parcel-overlay/SKILL.md`, `README.md`, `references/overlay-preparation.md`
- `plugins/metesparser/skills/plot-metes-and-bounds/SKILL.md`, `README.md`
- `plugins/metesparser/skills/deed-closure-dashboard/SKILL.md`, `README.md`, `references/dashboard-bundle.md`, `references/plot-and-overlays.md`
- `plugins/metesparser/evals/cases.json`
- `plugins/metesparser/README.md`, `CHANGELOG.md`, `docs/CLAUDE_PLUGIN.md`, `docs/ARCHITECTURE.md`, `docs/CONTRIBUTING.md`, root `README.md`, `AGENTS.md`

Read the available skill-creator guidance when editing skills. Keep entrypoints concise; place schema/runtime examples in existing references. Explain the inputs/outputs and invalidation boundary once in shared handoff docs, then link to it.

`prepare-parcel-overlay` remains independent registration/import; `plot-metes-and-bounds` remains an independent offline plot; `deed-closure-dashboard` orchestrates the optional Mapbox companion when explicitly requested. No duplicated math, new skill, automatic provider activation, inferred controls, or verification promotion. Document the exact implemented CLI/extra/build flags only after D/P1 establish them. Include localhost token restrictions, layer order, failure/fallback behavior, separate accuracy measures, and live/host acceptance limitations.

Correct the existing eval near `plugins/metesparser/evals/cases.json:153` that says unchanged geometry is reused without recomputation: source reading/preparation can be reused, but dashboard geometry/placement bindings require fresh validation. Add cases for artifact reuse, missing georeference, provider unavailable, no status promotion, and source reading not repeated. New eval specs are not evidence of native-host execution.

Verify: `uv run pytest plugins/metesparser/tests/ --no-cov --import-mode=importlib` → passes; examples parse through implemented CLI/model tests; all new relative links resolve. Use meaningful contract/example validation, not prose snapshot tests. Parent reviews that all eight existing skills retain independent purpose and no earlier documentation edits are lost.

## Parent integration and distribution

1. Integrate A/B/C through the frozen API, then D/E/F. Parent owns changes to package `__init__.py` exports and `src/metesparser/dashboard.py`; keep the facade thin. Do not mirror new GIS math into the historical monolith.
2. Update `scripts/build_claude_plugin.py` with opt-in `--with-web-map`, implying existing geo support; reject combination with `--without-geo`. Include locked web-map dependencies and all renderer assets/descriptor. Default plugin footprint/behavior stays as currently documented. Verify extraction in a directory outside the checkout so local imports cannot hide missing wheel contents.
3. Update `tests/unit/test_plugin_build.py` for default, without-geo, and with-web-map distributions, immutable runtime fingerprint coverage, optional dependency behavior, and new launcher command. Add new Makefile browser gates; preserve existing offline target semantics.
4. Exercise a built, extracted plugin with a synthetic source bundle/config: generate both views, launch preview, verify hashes/source links and runtime lookup. Default/no-geo runtimes still render supported offline content and report missing online prerequisites explicitly.
5. Run an independent read-only review focused on projection/units, half-pixel correctness, alpha/resampling, partial-traverse honesty, token/log hygiene, source-link integrity, package boundaries, and preservation of dirty work. Any concrete correctness bug gets a failing regression before its fix.
6. Record command, exit status, test counts, platform/library versions, and sanitized artifacts per gate. The parent maintains the index and a completion note in this plan. Never equate local tests, ZIP generation, or authored evals with live/provider/native-host acceptance.

## Verification commands and evidence

Use `uv`, never pip/conda/poetry. After the parent updates dependencies, `uv sync --all-extras --dev` prepares the repo environment. For reproducible reruns use `UV_CACHE_DIR=.uv-cache uv run --no-sync ...` if that environment has already been synced. Network/sandbox failures are prerequisites to resolve through the normal tool approval path, not permission to silently omit tests.

| Gate | Command | Expected result |
|---|---|---|
| Package regression | `uv run pytest packages/mp-models/tests/ packages/mp-bearing/tests/ packages/mp-verify/tests/ packages/mp-review/tests/ packages/mp-export/tests/ --no-cov --import-mode=importlib` | All pass; no skipped mandatory web-map cases in full-extra environment |
| Compatibility | `uv run pytest tests/unit/test_cross_package_imports.py --no-cov` | All pass |
| Plugin contracts/build tests | `uv run pytest plugins/metesparser/tests/ tests/unit/test_plugin_build.py --no-cov --import-mode=importlib` | All pass |
| Corpus | `make review-corpus` | Existing review classifications remain correct |
| Root quality/types/tests | `make quality`, `make type`, `make test` | Exit zero; distinguish preexisting issues before changing unrelated code |
| New package lint/format | Explicit new-module commands below, plus assigned changed tests/existing modules | Exit zero |
| Offline browser | `make test-dashboard-browser` | Mandatory cases pass; zero external attempts |
| Deterministic Mapbox browser (new) | `make test-mapbox-browser` | Adapter and pinned-SDK local tests execute and pass |
| Distribution | Three build commands below; extracted-runtime smoke | Assets/dependencies/hashes complete; foreground preview works |
| Live provider (new, explicit) | `make test-mapbox-live` | Actual provider/network/WebGL tests pass or gate marked blocked/not run |
| Native host | Run new eval cases in supported Claude/Cowork host with extracted plugin | Record actual host outcomes separately; lack of loopback access is an explicit limitation |
| Final scope | `git diff --check` and `git status --short` | No whitespace errors; only assigned changes plus preserved preexisting work |

New-module checks after implementation:

```sh
uv run ruff check packages/mp-models/src/mp_models/webmap.py packages/mp-review/src/mp_review/webmap.py packages/mp-review/src/mp_review/webmap_projection.py packages/mp-review/src/mp_review/webmap_raster.py packages/mp-review/src/mp_review/map_preview.py packages/mp-export/src/mp_export/online_map_html.py
uv run ruff format --check packages/mp-models/src/mp_models/webmap.py packages/mp-review/src/mp_review/webmap.py packages/mp-review/src/mp_review/webmap_projection.py packages/mp-review/src/mp_review/webmap_raster.py packages/mp-review/src/mp_review/map_preview.py packages/mp-export/src/mp_export/online_map_html.py
uv run mypy packages/mp-models/src/mp_models/webmap.py packages/mp-review/src/mp_review/webmap.py packages/mp-review/src/mp_review/webmap_projection.py packages/mp-review/src/mp_review/webmap_raster.py packages/mp-review/src/mp_review/map_preview.py packages/mp-export/src/mp_export/online_map_html.py
```

Build commands after adding the new flag; output archives are local build artifacts:

```sh
uv run python scripts/build_claude_plugin.py --output dist/metesparser-plugin-default.zip
uv run python scripts/build_claude_plugin.py --without-geo --output dist/metesparser-plugin-no-geo.zip
uv run python scripts/build_claude_plugin.py --with-web-map --output dist/metesparser-plugin-web-map.zip
```

Root pytest discovers `tests/`, not every package suite; browser tests are opt-in. `make type` covers the root monolith, so the additional module command above is required; follow existing mypy conventions for third-party GIS stubs rather than globally disabling checking. `make ci` starts `clean` and does not replace these package/plugin/browser gates; do not run it as a shortcut that removes existing artifacts. Inspect package tests for actual execution rather than accepting an all-skipped total.

## Copyable subagent dispatch

Use one prompt per owned packet. Supply the absolute repository path, packet letter, current SHA, and current shared-contract status; do not require the worker to remember this conversation.

```text
Work in /Users/dfahey/projects/metesParser. Read AGENTS.md and
plans/001-mapbox-online-viewer.md completely. Implement packet <LETTER> only.
The parent has completed P0 and frozen the contracts at <CURRENT SHA/STATE>.
Your exclusive files are the packet's ownership row and named tests/fixtures.
You are not alone in this codebase. Preserve all existing dirty work and other
agents' edits; adapt to them, and do not revert or overwrite shared files.
Use red-green TDD: record the failing command/assertion before implementation,
then the passing result. Use independent numerical expectations when applicable.
Do not change shared contracts/dependencies/exports without messaging the parent.
Do not commit, push, deploy, access real property sources, or put credentials in
artifacts. Stop the affected work and report a specific contract/prerequisite
blocker rather than substituting fabricated placement, weaker geometry, or mocks
for a required real-world gate. Return files changed, behavior, red/green evidence,
remaining limitations, and integration instructions. Parent updates the plan index.
```

For F, replace the TDD sentence with: “Validate executable examples and skill/eval contracts; do not create tests that merely snapshot documentation wording.” For the final reviewer use the same context, request read-only review, and explicitly prohibit fixes until findings are assigned.

## Done criteria and gate ledger

Implementation evidence recorded on 2026-10-27. Deterministic acceptance and provider/host acceptance are separate. Work remains uncommitted on `feat/deed-closure-dashboard-skill`; preexisting documentation edits were retained.

| Required gate | Status | Completion evidence |
|---|---|---|
| P0 operation/runtime/contracts | passed | 11 model and 23 projection/runtime tests; enforced operation, axis and missing-grid controls |
| A vectors and immutable record | passed | 28 tests including both foot definitions, curves, partial traverses, budgets, provenance and independent controls |
| B raster interior alignment | passed | 13 tests including nonlinear interior checkpoints, curved extent, half-pixel, alpha, tampering and pre-allocation limits |
| C/D renderer, staging and server | passed | 39 online renderer, 5 optional staging, 3 preview and 13 launcher contract tests; offline regression retained |
| E deterministic browser | passed | Offline browser 12 passed; `make test-mapbox-browser` preflight and 17 adapter/pinned-SDK tests passed, zero skips |
| F composition/docs/evals | passed | Examples parsed, relative links resolved, three edited skill validations passed, 23 unique eval IDs, eight skills retained |
| Integrated regression/types/lint | passed | 662 passed / 17 explicitly opted-out browser cases at that run; final root 1500 passed / 12 browser opt-outs; lint/format/mypy and five-case corpus passed |
| Built/extracted distributions | passed | Default/no-geo/web-map archives rebuilt from final source; isolated runtime/real raster/preview smoke passed; 19 builder/launcher/streaming tests passed |
| Live Mapbox three-layer view | blocked | Live preflight exits 1: no valid public token in the environment. Visual gate authored, not executed |
| Native plugin host | not run | Claude/Cowork workflow and loopback reachability not exercised |
| Independent review | passed | Projection review found no concrete issues; forged renderer provenance fixed with 22 failing regressions before GREEN |

- [ ] Basemap + correctly warped tax scan + recorded deed courses are visibly composited at a known synthetic reference location.
- [x] Same data gives the same deterministic artifacts within the pinned runtime; original source/calculation/geometry/registration/placement hashes remain unchanged.
- [x] Both foot definitions, curves, partial traverses, missing evidence, domain limits, and independent raster interior checkpoints are tested.
- [x] Offline artifacts remain independently usable and make zero external attempts; online shell makes none before explicit Connect.
- [ ] Tokens are absent from persisted artifacts/logs/test captures; attribution remains visible on a live map.
- [x] Map and keyboard selections resolve to original source records; absent source images are labeled honestly.
- [ ] All required gates have actual evidence. Use `passed`, `failed`, `blocked`, or `not run`; no blanket “complete” while live/provider/host gates remain outstanding.
- [x] Scope and prior dirty documentation are preserved; no commit/push without later authorization.

Execution notes:

- Red/green development covered missing model/API imports, vector/raster behavior, optional CLI staging, preview allowlists and launcher dispatch. Review added 22 failing renderer binding cases before fixing them. A real-SDK style-switch regression required `{diff: false}` so review sources reload reliably.
- Runtime: macOS, Python 3.12.11; Mapbox GL JS 3.33.0 with verified SHA-256/SRI descriptor; Rasterio 1.5.2 / GDAL 3.12.2 / PROJ 9.8.1; pyproj 3.8.0 / PROJ 9.8.1 / EPSG database 12.029. The two bundled database files differ; independent controls establish compatibility of the exact enforced operation, rather than assuming file identity.
- Vector and raster projection disable network grid fetching and reject ballpark/unavailable operations. A deliberate 100 m operation offset moved the raster as expected; invalid operations and missing grids failed. A north/east-axis NZTM fixture verifies explicit axis handling.
- The nonlinear raster fixture defeats original four-corner stretching by more than five color units; withheld interior samples agree within 1.1 quantization units. Densified NZTM bounds include a curved edge extending over 1,000 m beyond corner-only bounds; 129 withheld edge samples remain inside.
- Integration command: `UV_CACHE_DIR=.uv-cache uv run --no-sync pytest packages/mp-models/tests/ packages/mp-bearing/tests/ packages/mp-verify/tests/ packages/mp-review/tests/ packages/mp-export/tests/ plugins/metesparser/tests/ tests/unit/test_plugin_build.py tests/unit/test_cross_package_imports.py --no-cov --import-mode=importlib -q` → 662 passed, 17 opt-in skips. Browser lanes are executed separately; these skips are not acceptance evidence.
- Final `make test UV_RUN='uv run --no-sync'` → 1500 passed, 12 opt-in skips, 93.51% coverage. `make quality`, `make type`, explicit new-module Ruff/format/mypy checks and `make review-corpus` passed. `make test-dashboard-browser` → 12 executed and passed.
- `make test-mapbox-browser` → exact SDK-cache hashes and Chromium WebGL2 preflight passed; 17 tests passed with zero skips. Actual pinned SDK `testMode` exercised workers, local source/image loading and repeated style reloads with zero SDK errors; this is API integration evidence, not live basemap acceptance. Playwright 1.64.1 on macOS.
- The preview URL streams on stderr through the existing CLI output convention. It is available while the foreground process is alive; the final structured result is reserved for stdout on exit.
- All three `scripts/build_claude_plugin.py --offline` variants (default, `--without-geo`, `--with-web-map`) exited zero. Archives are under ignored `.uv-cache/mapbox-build/`. Final extracted smoke used isolated virtual environments and `python -I` in `/private/tmp/metesparser-dist-smoke-avfloqrm`, outside the checkout. Packaged source/asset bytes and fingerprints matched the final implementation. Default/no-geo missing dependencies produce explicit partial/unavailable results; web-map prepares six vector features and one real RGBA scan while preserving baseline artifact bytes.
- Extracted launcher smoke verified immediate URL, HTML/PNG responses, referrer policy, raw-source/query/traversal/Host rejection and SIGINT cleanup. The permanent subprocess regression is `tests/unit/test_webmap_distribution.py`; the builder/launcher/streaming suite passed 19 tests. The standalone smoke driver used for this run is `/tmp/metesparser-distribution-smoke.py` (ephemeral evidence, not an installed component).
- Archive SHA-256: default `e6bddbd86459aface8882e5e0dfac2b5d9e1b804315d8538d9eab93d79cf5591`; no-geo `14ad1d73f19cf1da60f294d64daaee206a5bfc5cbef72c4495104676c2a15997`; web-map `0b5d9bdb36c29c58014b63a2d41cae0d9620d9e105f498b5467c58cd7c88b069`.
- Dedicated live preflight never prints the missing/rejected token. Native-host eval specifications were updated, but no host pass is claimed. Online scenarios, automatic alignment and other providers remain deferred.

## Optional Mapbox MCP handoff follow-up

Implemented on 2026-10-27 through three subagents, retaining the existing eight skills. The dashboard skill links to [the MCP procedure](../plugins/metesparser/skills/deed-closure-dashboard/references/mapbox-mcp.md). `metes-review mapbox-mcp EXISTING_DASHBOARD_DIR --output-dir NEW_DIR` validates retained source/request/artifact hashes and local fallback files, then emits exact vector arguments plus a local provenance/omission report. Shared identity validation lives in `mp_verify.webmap`; `mp_export.mapbox_mcp` performs only serialization. The handoff never projects, warps, calls a provider, or grants verified status. CRS/unit validation still requires the geo runtime.

The adapter pins the upstream contract to commit `6ee4589df5433234969bc525d9342bb7210a529f`, preserves coordinates and feature IDs, keeps closure annotations separate, omits rasters explicitly, and refuses requests over a conservative 48 KiB budget without simplifying geometry. Existing local views retain scans and source-page review.

| Gate | Status | Evidence |
|---|---|---|
| Red/green behavior | passed | Missing API/CLI/launcher tests failed before implementation; four missing/changed fallback-file regressions failed before reusing the existing preview allowlist validator |
| Integrated package regression | passed | 694 passed; 18 opt-in browser/provider tests skipped. Sandbox blocked localhost binding on the first run; permitted rerun passed |
| Root regression | passed | 1,501 passed; 12 opt-in browser tests skipped; 93.51% coverage. Permitted rerun enabled the launcher localhost test |
| Static checks | passed | Root lint/format/mypy and explicit new-module Ruff/format/mypy checks passed |
| Skill forward test | passed | Synthetic staged dashboard with a scan produced a partial handoff with four courses and one POB, identical coordinates, matching arguments digest, explicit scan omission and intact local links |
| Default plugin build | passed | Offline archive built at `.uv-cache/mapbox-build/metesparser-mcp.zip`; SHA-256 `77bf42fdf2e73740ad2ceda85068f8f2d09b083a9c48b1cfbe44a749fd503da2` |
| Extracted plugin handoff | passed | Actual extracted launcher ran offline outside the checkout with `PYTHONPATH` unset and a fresh venv; exit 1, partial/needs_review, no errors, exact five-feature coordinate equality, one explicit scan omission; rasterio absent. Evidence under `/private/tmp/metes-package-smoke-mzdee44s` |
| Connected Mapbox schema/call and OAuth | not run | No Mapbox MCP tool connected in this session; no provider configuration or authentication changed |
| Visible Claude MCP Apps map | not run | Requires a connected server and native-client visual acceptance |

Browser lanes were not rerun for this serializer/validator extraction; their preceding GL JS evidence is recorded above and does not substitute for MCP acceptance. The [manual testing guide](../docs/CONTRIBUTING.md#manual-mapbox-smoke-test) now supplies a reusable synthetic fixture and separate MCP/local-viewer steps. Its fixture, dashboard, and MCP-generation commands were executed successfully; authentication and live rendering remain the separate gates above.

## Stop conditions and maintenance

Stop the affected packet and tell the parent when: the live code contradicts a load-bearing contract; a required coordinate operation/grid cannot be enforced; no genuine position/orientation evidence is supplied; the pinned SDK/CSP or optional raster stack cannot run on the supported platform; a correct fix needs files outside ownership; or a meaningful test still fails after two focused fixes. Parent resolves/reassigns a blocker while independent work continues. Never substitute an invented anchor, rounded bearing, stretched deed, four-corner scan, or mocked live success.

Missing georeference in a user's valid dataset is a supported unavailable state, not a reason to fabricate location or block unrelated offline review. Missing test fixtures/prerequisites for the required three-layer acceptance gate are execution blockers and must be reported as such.

Future SDK changes require descriptor hashes, CSP review, browser tests, and live acceptance. Future CRS/grid changes require rerunning independent vector/raster controls and invalidating dependent display artifacts. Online scenarios, interactive control-point registration, MapLibre adapters, print exports, and hosted sharing are follow-ups; each should consume these display/evidence contracts rather than fork the calculator or create another all-purpose skill.
