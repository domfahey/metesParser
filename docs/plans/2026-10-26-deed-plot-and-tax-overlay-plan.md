# Deed plotting and optional tax parcel overlays

Date: 2026-10-26
Status: implemented 2026-10-27 through Releases A, B and C; applicable local, browser, packaged-runtime and live-provider gates passed. Native document reading and Claude/Cowork host acceptance remain unrun. See [implementation evidence](2026-10-27-deed-plot-implementation.md).
Baseline: `31aafd3` on `feat/deed-closure-dashboard-skill`.

## Goal and delivery order

Enhance the existing dashboard with a source-linked metes-and-bounds plot and optional tax parcel layers. Make the deed geometry, its placement, and the map evidence independently inspectable. Preserve recorded calls, canonical verification, and the verified-export gate.

Deliver in small, independently reviewable changes:

| Release | Included | Exit condition |
| --- | --- | --- |
| A: plot and supplied vector layer | Honest line/arc/partial plots, selection and source links, zoom/pan, closure detail, immutable baseline and scenario display, supplied projected polygon layer, explicit rigid placement, layer opacity, offline artifacts | Tasks 1–5 and applicable Task 9 gates pass; one supplied vector layer works end to end |
| B: import and scanned maps | GeoJSON import with explicit CRS conversion, PNG/JPEG/WebP tax-map registration, fit diagnostics | Tasks 6–7 and repeated integration gates pass |
| C: optional source acquisition | One official parcel provider adapter, explicit parcel identification, retained response and provenance | Task 8 and provider-specific acceptance pass |

Release A accepts a documented, already projected layer JSON contract through the dashboard bundle. It does **not** accept longitude/latitude as feet or claim to import arbitrary GIS files. GeoJSON file import belongs to Release B. A deed-only dashboard remains fully usable without any overlay.

Do not add interactive curve editing, automated boundary matching, legal boundary corrections, or verified GIS exports in this work. Existing todo item 5 owns cross-description matching; this plan supplies its explicit frame/placement prerequisites and selected-point residuals. Existing item 6 still owns full native document-reading and Claude/Cowork acceptance.

## Starting points and constraints

- `packages/mp-models/src/mp_models/dashboard.py`: immutable v1.0 source bundle, calculation frames, scenarios, prepared results and manifests. Current frames describe local feet and bearing basis, not geolocation.
- `packages/mp-verify/src/mp_verify/dashboard.py`: canonical/relative record calculations and fresh validation of prepared results.
- `packages/mp-verify/src/mp_verify/closure.py`: the traverse helper skips missing bearings and can use a straight fallback for incomplete curves. Do not build partial plots by zipping its points to source calls.
- `packages/mp-bearing/src/mp_bearing/curves.py`: reusable deterministic curve math.
- `packages/mp-review/src/mp_review/dashboard.py`: stage hashing, validated cache reuse, atomic artifact writes, exact input-byte preservation.
- `packages/mp-export/src/mp_export/dashboard_html.py` and `dashboard_assets/`: existing offline renderer, basic SVG plot and straight-course scenario calculator.
- `src/metesparser/dashboard.py`: compatibility facade. Expose new supported APIs through a thin facade where needed; do not duplicate plotting math in the monolith.
- `plugins/metesparser/skills/deed-closure-dashboard/`: skill workflow and focused references; `scripts/build_claude_plugin.py` packages the locked runtime and assets.

Keep the dashboard's `needs_review` command status, no-verified-CSV behavior, existing source/canonical calculations, and fresh export checks unchanged. A valid visual placement must never authorize export or turn an unperformed check into a passed check.

## Agreed design contract

### Separate geometry, placement and map evidence

Introduce immutable models in `packages/mp-models/src/mp_models/plot.py`, integrated with dashboard bundle v1.1:

- **Plot geometry:** calculation/occurrence ID, native frame ID, source call IDs, analytic line or circular-arc primitives, unresolved-call records, contiguous chains, completeness and reasons. Endpoints and metrics are derived outputs, not trusted inputs.
- **Scene:** explicit projected/local coordinate frame, axis order and linear unit. A frame's display name never establishes compatibility. Retain native deed units and bearing basis separately.
- **Placement:** geometry ID/hash, scene ID, clockwise rotation, translation, `unplaced` / `approximate` / `referenced` status, rationale and evidence/control references. Permit no manual deed scaling, shear, reflection, snapping, endpoint replacement or closure adjustment.
- **Map source:** retained asset/response hash, source URL or supplied filename, provider, retrieval time and source date (explicitly unknown when unavailable), native CRS/units/axes, feature identifiers and processing history. Hashes establish identity, not review completion or accuracy.
- **Vector layer:** typed projected Polygon/MultiPolygon coordinates, holes, source reference and scene relationship. Validate finite values, closed rings with enough distinct vertices, IDs and supported topology; reject invalid rings rather than repairing them silently. This internal projected format is not RFC 7946 GeoJSON.
- **Raster layer:** embedded PNG/JPEG/WebP with verified content hash and dimensions; pixel-to-scene registration, control pairs, method and residuals. Add this model in Release B, not as an unused Release A abstraction.
- **View settings:** visible layers, opacity, label choices and viewport. These affect presentation only.

Continue accepting v1.0 bundles without overlay fields. Version-specific validation must reject new fields in v1.0 rather than silently dropping them. Preserve exact supplied input bytes. Use the existing absolute/relative v1.0 fixtures to assert stable findings, calculation results, CLI status and input preservation; do not require identical HTML across renderer versions. Existing cache formats may miss safely after a version change; geometry changes require calculator-version changes, while view-only changes must not invalidate canonical math.

### Geometry and placement rules

1. Build plot primitives from identified source calls and validated calculation semantics. Never synthesize numeric recorded bearings for cardinal-only descriptions. Relative-angle results retain their arbitrary local frame.
2. At the first unknown displacement, stop the anchored boundary. Show the known prefix and an unresolved-call notice; keep later calls listed. Do not connect later vectors across that gap. Independently anchored later chains can be a future extension.
3. Draw a real arc only when radius, sweep/direction and starting orientation are determined and supplied elements are consistent. Reuse curve helpers and retain analytic geometry; tessellation is display-only. Conflicting redundant arc/chord elements produce an inconsistency notice and withhold the arc initially; do not silently choose a preferred parameter subset. An available chord may be shown as a clearly labeled chord, never as the curved boundary. Unresolved curve orientation stays unresolved.
4. Do not close open/partial paths for rendering. Draw a complete traverse's endpoint-to-POB gap separately as an annotation, not a deed course. Preserve existing area semantics; do not calculate a new full-parcel area from an incomplete plot.
5. A local plot can have a local-axis arrow. A grid/true/magnetic north arrow requires a documented basis; recorded bearings alone do not establish geographic north. The scale bar must reflect the current displayed linear units and zoom.
6. Keep unit conversion and any documented ground/grid or CRS transformation separate from manual rigid placement. No assumed ground/grid factor. Referenced placement requires supported position **and** orientation, compatible units and documented basis treatment; one position anchor alone is insufficient.
7. Manual alignment to assessment parcels remains approximate even when it looks convincing. A 100-ft deed segment must stay 100 ft against a 100.2-ft map baseline; expose the residual instead of resizing the deed.
8. Freeze the baseline placement when evaluating a scenario. Create a scenario-derived placement bound to the scenario geometry hash, retaining the baseline geometry/placement references and the scenario ID, and applying the unchanged transform. This is distinct from reusing a stale placement after recorded source calls change. Editing a distance must not refit the drawing to the map. Overlay residuals, deed misclosure, and map-source accuracy are separate quantities.
9. Start residual comparison with explicitly named point correspondences. Report displacement vectors, RMS and maximum norm only in a common supported linear frame. Return `not_comparable` when alignment prerequisites are absent. Fit residuals are not survey accuracy.

Tax parcels are assessment/context evidence. NJGIN specifically disclaims their use as survey or legal boundary data; carry this distinction into the skill and map provenance panel. [NJGIN parcel documentation](https://www.nj.gov/njgin/edata/parcels/)

### Stage and cache boundaries

Extend existing stage machinery rather than introducing a new pipeline framework:

| Stage | Inputs that invalidate it | Must remain unaffected by |
| --- | --- | --- |
| Source review | Deed documents, pages, occurrences, calls and source evidence | Maps, placement, layer visibility, opacity |
| Canonical/relative calculation | Existing source and calculation assumptions/version | Overlay data and all view changes |
| Plot geometry | Calls, calculation outputs, plot-builder version | Map alignment, opacity, viewport |
| Map preparation | Imported bytes, CRS/unit/axis metadata, conversion parameters/version | Deed reading and scenario edits |
| Placement/comparison | Geometry hash, map/scene hash, explicit placements and controls | Opacity and viewport |
| Presentation/render | Display settings, scenarios, stage-output hashes, renderer fingerprint | Nothing relevant to the rendered artifact |

Preserve the six existing artifact filenames. Add inspectable `plot-geometry.json`, `map-layers.json` and `placements.json` when applicable; extend manifests with their hashes. All required map bytes must be embedded in the offline HTML, with original imported assets retained in the delivery directory. Validate asset types, declared size limits and references; never let an asset reference overwrite the input bundle or existing files.

Use separate map provenance, not the deed's `source-review.json`, for map preparation. Recompute/validate derived results before trusting cached data, as the dashboard already does. A canonical-call change invalidates dependent geometry and placements; stale placements must be explicitly revalidated rather than silently rebound to changed geometry.

## Red–green–refactor working rules

For each task below:

1. **RED:** add the smallest behavior test against a hand-computed fixture; run the exact targeted test and record the expected failure. New API import failures are acceptable initially, but follow with assertions that fail against a stub or incomplete implementation.
2. **GREEN:** implement only enough production behavior to satisfy the regression and existing affected tests. Do not change expected numbers to match implementation output.
3. **REFACTOR:** remove duplication, improve names/types, and rerun the affected suite. Keep recorded inputs and expected math independent of the implementation under test.
4. Record commands, failure reason, green result, unrun checks and actual worker/model in the implementation PR. Never describe this planning document as evidence of tests already executed.

Use synthetic fixtures; do not copy the example HTML's property data, source claims, base64 scans or injected host runtime. Preserve source quotes verbatim. Share a stable fixture/schema contract before parallel coding.

## Task 1 — Versioned plotting and overlay contracts

**Owner:** models worker.
**Files:** new `mp_models/plot.py`, existing `mp_models/dashboard.py`, public exports, `packages/mp-models/tests/test_plot_models.py`, dashboard model tests.

**RED tests:**

- `test_v1_bundle_renders_without_plot_options`: legacy fixture remains valid, no overlay required.
- `test_v1_rejects_v11_overlay_fields`: incompatible fields are not discarded.
- `test_plot_references_resolve_to_same_occurrence`: reject dangling or cross-occurrence source/geometry/control references.
- `test_plot_inputs_are_immutable`: mutations fail; source serialization is unchanged after preparing a scene.
- `test_layer_rejects_nonfinite_invalid_rings_and_unknown_units`: reject NaN/infinity, unclosed/degenerate/self-intersecting rings, invalid hole relationships and unknown unit strings. Preserve valid holes and multipolygons.
- `test_referenced_placement_requires_position_and_orientation_evidence`: prevent a lone geocoded address/anchor from establishing referenced placement.
- `test_placement_rejects_scale_shear_reflection`: unsupported transform fields fail validation.

**GREEN:** minimal v1.1 schema and validators, with no GIS dependency in `mp-models`. Use projected-layer fixtures with units/axes/CRS explicitly supplied. Keep unsupported geometry rejected with a useful reason.

**Run:** `UV_CACHE_DIR=.uv-cache uv run --no-sync pytest packages/mp-models/tests/test_plot_models.py packages/mp-review/tests/test_dashboard_bundle.py --no-cov --import-mode=importlib`.

## Task 2 — Deterministic plot primitives and rigid placement

**Owner:** geometry worker; independent stronger geometry review required.
**Files:** new `mp_verify/plot.py`, `packages/mp-verify/tests/test_plot_geometry.py`, `test_plot_placement.py`, affected dashboard integration; thin root facade/import tests.

**RED tests with independent expected values:**

| Test | Assertion |
| --- | --- |
| `test_rigid_clockwise_rotation_and_translation` | North vector `(0,10)` rotated 90° becomes `(10,0)`; origin translates to `(1000,2000)` |
| `test_placement_preserves_native_metrics` | 100 × 60 ft rectangle stays 6000 ft², perimeter 320 ft, unchanged source bytes and segment lengths |
| `test_open_gap_is_not_closed_or_adjusted` | 0.2-ft gap remains 0.2 ft; no closing source primitive is inserted |
| `test_unknown_middle_call_stops_anchored_chain` | Prefix is visible, remaining IDs remain unresolved/unpositioned, no full plot area or misclosure is manufactured |
| `test_right_quarter_circle_uses_arc_geometry` | North tangent from `(0,0)`, R=100, sweep=90°: center `(100,0)`, end `(100,100)`, arc length `50π`, midpoint `(100−100/√2,100/√2)` |
| `test_left_quarter_circle_and_chord_semantics` | Left counterpart ends `(-100,100)`; separate tangent/chord inputs produce the intended geometry |
| `test_underdetermined_curve_has_no_straight_fallback` | Missing orientation/radius/direction gives unresolved geometry, not a fabricated boundary |
| `test_conflicting_curve_elements_withhold_arc` | R=100, sweep=90° and an incompatible supplied arc length produce an inconsistency notice, not parameter selection |
| `test_identically_named_local_frames_are_not_aligned` | Frame names alone never allow comparison |
| `test_anchor_fit_does_not_scale_deed` | 100-ft deed vs 100.2-ft controls: fixed first anchor and aligned orientation leave 0.2-ft second-anchor residual |
| `test_point_residuals_are_separate_from_closure` | Named vectors, RMS `sqrt(mean(dx²+dy²))`, maximum norm; canonical closure/status unchanged |
| `test_scenario_keeps_baseline_placement` | Distance edit moves the endpoint in the same scene; no automatic recentering/refitting |

Also test large coordinate offsets, nonfinite arithmetic, reverse direction, angle-only local geometry, and unsupported exceptions/meanders. Initially render unsupported components as explicit notices instead of inventing tract connectivity. Preserve the relative solver's existing no-geometry result for unresolved/conflicting constraints.

**GREEN:** pure geometry construction, supported arc primitives, explicit unresolved states and rotation/translation. Apply unit conversions at a declared boundary; preserve the exact foot definition or mark it unresolved for geographic comparison. Do not change the canonical verifier to make the renderer work.

**Run:** `UV_CACHE_DIR=.uv-cache uv run --no-sync pytest packages/mp-verify/tests/test_plot_geometry.py packages/mp-verify/tests/test_plot_placement.py tests/unit/test_cross_package_imports.py --no-cov --import-mode=importlib`.

## Task 3 — Offline stages and cache independence

**Owner:** staging worker, after Task 1 and geometry API agreement.
**Files:** `mp_review/dashboard.py`, manifest/prepared-result integration, `packages/mp-review/tests/test_dashboard_bundle.py`, new `test_dashboard_plot_stages.py`, CLI integration tests.

**RED:**

- `test_overlay_only_changes_do_not_invalidate_deed_calculations`: preserve source-review and canonical calculation hashes across placement/layer changes.
- `test_opacity_changes_only_presentation`: no map or geometry recomputation required.
- `test_map_bytes_crs_or_controls_invalidate_only_dependents`: invalidate the correct stage for each input mutation.
- `test_changed_deed_geometry_rejects_stale_placement`: matching IDs with changed geometry hashes cannot reuse placement.
- `test_forged_plot_or_map_cache_is_recomputed_or_rejected`: changed derived coordinates/status cannot be trusted by editing hashes.
- `test_cold_and_warm_render_match`: identical bytes for the same inputs and renderer version.
- `test_delivery_preserves_input_and_embeds_required_assets`: exact original bundle/assets retained, HTML opens without source directories or internet.
- `test_dashboard_plot_never_changes_export_eligibility`: existing status/exit behavior and no verified CSV; no-plot v1.0 command still works.

**GREEN:** additive stage files/manifests, existing atomic-write and fresh-validation patterns, explicit asset import limits and failure messages. No changes to document-reading completeness.

**Run:** `UV_CACHE_DIR=.uv-cache uv run --no-sync pytest packages/mp-review/tests/test_dashboard_plot_stages.py packages/mp-review/tests/test_dashboard_bundle.py packages/mp-review/tests/test_dashboard_cli.py --no-cov --import-mode=importlib`.

## Task 4 — Plot and vector-layer interface

**Owner:** interface worker, after schema/geometry contracts are fixed.
**Files:** `mp_export/dashboard_html.py`, `dashboard_assets/dashboard.js`, `dashboard_assets/dashboard.css`, `packages/mp-export/tests/test_dashboard_html.py`, new `test_dashboard_plot.py`.

**RED:**

- `test_baseline_svg_preserves_gap_and_arc`: actual SVG paths have open endpoints/arc shape; annotations are separate from source courses.
- `test_plot_selection_resolves_call_and_source_occurrence`: plot/call table selection carries stable call IDs to the correct source page/crop.
- `test_record_and_scenario_layers_are_separate`: scenario changes leave baseline geometry, findings, transcripts and engine status unchanged.
- `test_overlay_is_optional_and_unplaced_is_explicit`: deed-only layout works; incompatible/unplaced maps do not appear aligned.
- `test_layer_visibility_opacity_and_holes`: toggles affect only the intended layer; holes stay transparent.
- `test_north_label_and_scale_follow_scene`: local-axis labels cannot masquerade as grid north; scale changes with zoom.
- `test_map_metadata_is_escaped_and_no_remote_resources_exist`: malicious source labels/URLs cannot execute code; no external tiles, fonts or scripts load.
- `test_python_browser_plot_agreement`: shared hand-computed fixtures agree within 0.001 ft for supported geometry/transforms; unknown remains unknown.

**GREEN:** render an immutable baseline SVG in Python, then enhance it with existing plain JavaScript. Add course-number/bearing/distance label controls, direction indicators, selection, fit/reset, zoom/pan, closure magnifier, layer legend/opacity and provenance details. Keep viewport state separate from geometric placement. Choose an explicit comparison view for unplaced layers rather than stacking unrelated origins.

Keep scenario editing limited to the existing supported straight-course inputs. Baseline arcs can be displayed without claiming browser curve editing. Source inspection uses the existing viewer and handles missing assets honestly.

**Run:** `UV_CACHE_DIR=.uv-cache uv run --no-sync pytest packages/mp-export/tests/test_dashboard_html.py packages/mp-export/tests/test_dashboard_plot.py --no-cov --import-mode=importlib`. Node numerical tests are required for this gate; a missing Node executable is an unrun gate, not a passing implementation.

## Task 5 — Real browser regressions and Release A skill integration

**Owner:** QA/docs worker; parent owns final integration.
**Files:** new `tests/browser/test_dashboard_plot_ui.py`, browser fixtures, test dependency/config and explicit Makefile target; skill `SKILL.md`, `references/playbook.md`, `references/dashboard-bundle.md`, new `references/plot-and-overlays.md`; relevant package/plugin changelogs.

**RED browser tests:** selecting a numbered course highlights the row and opens its exact source; keyboard selection and viewer focus return work; zoom/pan/fit/reset behave; scale bar stays correct; map toggle/opacity change no record data; preset/edit/reset and occurrence changes keep the correct frozen placement; invalid input is rejected. Open a copied standalone HTML with all network requests blocked. Cover 400 px and desktop light/dark layouts and readable closure detail.

**GREEN:** use Python Playwright with a dedicated `make test-dashboard-browser` target. Pin it via uv in a browser-test extra; document the one-time browser installation. Ordinary unit suites need not install a browser. The explicit browser target must preflight dependencies/browser availability and fail if required tests cannot run. Use DOM/geometry assertions for behavior; inspect screenshots for layout instead of relying on brittle pixel goldens.

Update the skill with a short routing paragraph and the focused plot/overlay reference: default deed plot, optional supplied map, required frame evidence, partial/curve limits, frozen scenario placement, offline delivery and source limitations. Document the exact projected layer JSON and a synthetic example. Replace only limitations actually removed by Release A; keep GeoJSON/raster/provider steps explicitly deferred until implemented.

**Run:** `make test-dashboard-browser`; `UV_CACHE_DIR=.uv-cache uv run --no-sync pytest tests/unit/test_plugin_build.py plugins/metesparser/tests/test_launcher.py --no-cov --import-mode=importlib`; rebuild and smoke-test the plugin with a synthetic v1.1 vector bundle in an isolated locked runtime. Confirm the built wheel/runtime contains the CSS/JS assets, the plot renders, v1.0 still works and no verified CSV appears. Native source-reading and target-host acceptance remain separately reported.

## Task 6 — GeoJSON import and explicit reprojection (Release B)

**Owner:** GIS import worker with geometry reviewer.
**Files:** new `mp_review/overlays.py`, `packages/mp-review/tests/test_overlay_import.py`, optional geo extra/uv lock, CLI and launcher routing, plugin runtime builder if needed.

Add `metes-review import-overlay INPUT --format FORMAT --target-crs CRS --output NEW_LAYER.json` for supplied files. Define distinct input modes for RFC 7946 GeoJSON and the internal projected layer format. RFC 7946 positions use longitude/latitude in WGS 84 decimal degrees; projected feet cannot be accepted as that format. Its source CRS is fixed by the format: reject conflicting overrides. For projected-layer input, require source CRS in its metadata or an explicit `--source-crs` argument, rejecting conflicts. [RFC 7946](https://www.rfc-editor.org/rfc/rfc7946)

**RED:** known longitude/latitude control prevents axis swaps; geographic degrees cannot be used as feet; 100 international feet = 30.48 m, 100 US survey feet = `100×1200/3937` m; unknown/ambiguous units block comparison; holes/multipolygons and feature IDs survive import; invalid/self-intersecting geometries fail; unsupported geometry and CRS operations produce explicit errors. Check an independently calculated projected point pair and round trip with a declared tolerance.

Test missing CRS on projected-layer input, unavailable grids, nonfinite results, missing optional dependency and mismatched ground/grid basis. GeoJSON needs no separate CRS field because its format defines one. All import fixtures run with projection-network access disabled; required local resources must be pinned/recorded. A failed map import leaves the deed-only workflow usable and does not silently produce a misregistered layer.

**GREEN:** use optional `pyproj` in `mp-review`, keeping the core model/verify packages free of GIS dependencies. Set explicit XY order, fail on transformation errors, reject unavailable/ballpark operations where the selected mode requires a referenced transformation, and record operation definition, reported accuracy (including unknown), library/resource versions and CRS metadata. Select/pin a supported version during implementation. [pyproj Transformer API](https://pyproj4.github.io/pyproj/stable/api/transformer.html)

Document which conversion is visualization-only. CRS conversion cannot establish a missing deed datum or orientation. Preserve native deed metrics even when map projection changes displayed lengths. Before exposing this in the plugin, package and smoke-test the optional geo runtime; missing extras must give an actionable error, never a silent fallback.

**Run:** new import tests with the geo extra installed, no-network fixture run, CLI/launcher tests and locked plugin smoke with/without the extra.

## Task 7 — Scanned tax-map calibration (Release B)

**Owner:** raster worker, after scene contracts and Task 6 unit conventions.
**Files:** overlay models/loader, new `mp_review/raster_registration.py`, `packages/mp-review/tests/test_raster_registration.py`, renderer/browser tests and focused skill reference.

Accept supplied PNG/JPEG/WebP and an explicit control-point JSON or affine transform. PDF rendering remains a separate preparation step with original PDF/page/hash provenance. Start with supplied controls; drag-to-calibrate interaction is deferred.

**RED:** a hand-computed rotated affine maps pixel centers correctly with image Y increasing downwards. With integer coordinates denoting pixel centers, assert the outer image edges at `(-0.5,-0.5)` and `(width−0.5,height−0.5)` so SVG rendering does not introduce a half-pixel shift. Reject collinear/duplicate/insufficient controls, singular/nonfinite matrices and incompatible scene units; report named control residuals and distinguish fit controls from independent checkpoints. Three noncollinear controls can define an affine transform exactly but do not provide an independent accuracy check. Four or more controls exercise nonzero fit residuals.

Test image dimensions/hash validation, crop/resize provenance, explicit pixel-center convention, opacity/toggle, persistence and network-free standalone display. Deed metrics and canonical hashes remain unchanged by every raster calibration change.

**GREEN:** deterministic affine registration from at least three noncollinear control pairs, or a validated supplied transform. Record calibration method and controls. Transform the map image, not the deed. Printed scale or a visually selected corner alone is insufficient for referenced alignment; retain approximate status when appropriate. Do not auto-warp a scan to make the boundary match.

**Run:** raster registration unit tests, applicable renderer tests, browser target and a packaged raster-bundle smoke test.

## Task 8 — Optional official parcel retrieval (Release C)

**Owner:** bounded provider worker; parent reviews selection/provenance.
**Files:** a single provider adapter under `mp_review`, fixture-backed provider tests, CLI/launcher routing and skill guidance.

Start with NJGIN if the initial users need New Jersey. Verify the current official endpoint/schema before implementation. Require municipality/block/lot or another official unique identifier; return ambiguous candidates for explicit selection. Do not silently choose by address, visual fit or best closure. NJGIN offers multiple coordinate representations; inspect the selected service/download metadata rather than hard-coding a datum. [NJGIN parcel documentation](https://www.nj.gov/njgin/edata/parcels/)

**RED:** unique/empty/multiple matches; municipality collisions; pagination/incomplete responses; invalid geometry; changed schema; timeouts; retained feature IDs/query/source date/response hashes. Fixtures mock network access and contain no owner/taxpayer data that is unnecessary for plotting.

**GREEN:** explicit acquisition command, complete response retention and normalization through Task 6. Renderer never queries the provider. A stale saved snapshot remains labeled with its actual retrieval/source dates. No provider-specific source selection or automatic fetching in the pure plotting packages.

**Run:** fixture provider tests first, then a separately labeled live read-only smoke test when network access is available. Live acquisition, offline replay and native document reading are distinct acceptance gates.

## Task 9 — Integration and release gates

Run these after each release, not after every small red–green cycle:

1. Affected package suites with `--no-cov --import-mode=importlib`; root facade/import regressions; existing canonical verification/export safeguards.
2. `make check`. It runs formatting as part of the workflow: inspect the diff afterward and preserve unrelated edits. Resolve failures before declaring the release complete.
3. `make test-dashboard-browser`, requiring actual browser and Node execution; retain screenshots of partial geometry, arcs, map alignment, mobile and dark mode.
4. `make plugin-build` and isolated locked-runtime smoke tests for v1.0, v1.1 deed-only and each overlay type supported by that release. Verify packaged CSS/JS and any optional projection dependencies/resources.
5. A second reviewer checks coordinate convention, arc/chord semantics, incomplete-call handling, foot definition, residual math, immutable scenarios and cache invalidation independently.
6. Update the skill/docs and `plugins/metesparser/evals/cases.json` with release-appropriate dashboard cases. Record native-reading, actual Claude/Cowork UI and live-provider gates as passed/failed/not run, separately from deterministic/browser tests. Never infer host acceptance from local HTML or a locked-runtime smoke test.

Before an authorized commit, run `make pre-commit`, inspect all changes and hook edits, and report any remaining unrun gates. Use feature branches and PRs; this plan does not authorize committing, pushing or publishing.

## Delegation and dependency order

The coordinating agent owns final integration, release boundaries, shared schemas and root build/config changes. Workers are not alone in the repository: each receives exclusive file ownership, must preserve others' edits, and must communicate contract changes before touching shared files.

1. Agree the contracts/fixtures; implement Task 1 first.
2. Fix the serialized/embedded stage shape and scene/viewport contract before parallel work. Run geometry (Task 2), staging (Task 3), and interface test scaffolding (Task 4) against that contract. Coordinate shared `dashboard.py` model changes through the models owner.
3. Integrate geometry/staging, finish Task 4, then Task 5 and Release A gates.
4. Run Tasks 6 and 7 only after scene/unit conventions are stable; share overlay model ownership explicitly. Gate Release B separately.
5. Implement Task 8 after importer/replay behavior is accepted; gate Release C separately.

Use smaller capable models for model-validation tests, CLI wiring, documentation and fixture organization. Use a stronger geometry worker/reviewer for arc interpretation, CRS/ground-grid treatment, registration and numerical disagreements. Parent integration checks actual results and records the models used; do not claim delegated or cheaper-model work that was not performed.

## Definition of done

- The plot exposes what the supplied calls determine, including unresolved geometry and the real closure gap.
- Optional maps have explicit provenance, units, placement and status; turning them off leaves a useful deed plot.
- A scenario changes only scenario geometry; it never mutates the record, refits placement or improves verification status.
- Offline delivery includes the required map snapshots and reproducible stage hashes.
- Meaningful RED failures and GREEN results are recorded, package/monolith compatibility is covered, and release-specific browser/plugin checks pass or remain clearly unrun.
- The skill explains supported plotting/overlay steps concisely and retains existing source-reading and export safeguards.
