# Deed plot implementation evidence

Implemented 2026-10-27 against baseline `31aafd3` on `feat/deed-closure-dashboard-skill`. The pre-existing plan and todo edits were preserved.

## Delivered

- Release A: immutable v1.1 contracts, v1.0 compatibility, source-linked analytic lines/arcs, unresolved prefixes, source selection, zoom/pan/fit/reset, labels, unit scale and gap detail. Explicit rigid placements and named-point residuals remain separate from canonical verification. Scenario edits retain the baseline transform.
- Release B: supplied projected polygon layers and GeoJSON import with explicit CRS/axis/unit validation and offline pyproj operations; PNG/JPEG/WebP affine registration with integer pixel centers, fit/checkpoint residuals and original assets.
- Release C: official NJGIN acquisition by exact municipality/block/lot/qualifier or explicit candidate ID, complete response retention and deterministic offline replay. Rendering performs no provider requests.
- Additive `plot-geometry.json`, `map-layers.json`, `placements.json` and stage hashes; original input bytes and `assets/<source-id>.bin` preserved. Maps and view changes do not alter deed calculation/source-review hashes. Dashboard remains `needs_review` and never produces verified CSV.
- Skill workflow/reference and four evaluation cases updated. Root `metesparser.plot` delegates to package APIs. No duplicate plotting mathematics added to the monolith.

## Red–green record

Workers ran failing behavior tests before implementation. Initial missing-API failures were followed by semantic checks with independently calculated geometry.

| Area | Observed RED | GREEN / follow-up |
| --- | --- | --- |
| Models/geometry | Missing plotting API and incomplete primitives/contracts | Known rectangles, left/right quarter circles, open gaps, unresolved middle calls, foot conversion, rigid placement and named residuals |
| Staging | Seven failures with empty/missing plot stages | Independent source/calculation/map/placement/view hashes, stale placement rejection, tampered cache repair and reproducible cold/warm HTML |
| Asset retention | Supplied raw map rejected before source-byte field/output support | Exact retained bytes, safe ID-based filenames, raster decode/dimension validation and unchanged deed hashes |
| Renderer/browser | Missing controls/geometry; raster image absent in DOM | Source/table selection, keyboard/focus return, zoom/pan/fit/reset, frozen scenario/map behavior, arcs, partial prefixes, mobile/dark and raster controls |
| Browser reset | Real Chromium showed a one-ULP reset serialization difference | Reset restores the original viewport string exactly |
| Import/raster/provider | Missing modules; five rejected CLI/launcher commands | Known XY controls and foot definitions, holes/multipolygons, unavailable grids/nonfinite rejection, affine residuals and provider ambiguity/pagination/schema handling |
| Independent geometry review | Spirals drawn as circles, contradictory tangent/chord bearings accepted, huge offsets collapsed segments, comparison inputs unreachable | Regressions with explicit unresolved/inconsistent outcomes, representability checks and staged named comparisons |
| Independent model review | Four failing hole-crossing/raster-provenance cases; local scene accepted CRS | All polygon rings checked across members; valid islands in holes preserved; raster/source bytes and hashes bound; local CRS bypass rejected |
| Independent CRS review | Nine failures across preparation, serialized validation and direct render | Twelve regressions validate projected CRS/unit semantics at every fresh calculation boundary; local/deed-only path never imports pyproj |
| Provider edge cases | Missing object-ID list accepted; incompatible GeoJSON CRS accepted; live blank qualifier rejected | Fail-closed response validation; exact blank qualifiers supported; unique live retrieval reproduced offline |

Targeted suites used `UV_CACHE_DIR=.uv-cache uv run --no-sync pytest ... --no-cov --import-mode=importlib`. New tests are under `packages/mp-{models,verify,export,review}/tests/`, `tests/browser/`, and `tests/unit/test_plot_facade.py`. Final evidence below supersedes intermediate counts.

## Final gates

| Gate | Result |
| --- | --- |
| `make check UV_RUN='uv run --no-sync'` | Passed: lint, formatting, mypy, **1,495 root tests**, **93.50% coverage**. Ten browser cases skipped here by design and run explicitly below. |
| Six deterministic package suites plus plugin launcher, `--no-cov --import-mode=importlib` | **829 passed**. Includes new plot/raster/scene/provider regressions and existing export safeguards. |
| `make test-dashboard-browser UV_RUN='uv run --no-sync'` | **10 passed**, Chromium and Node preflight passed. |
| Changed production-module Ruff and targeted strict mypy | Passed. |
| Skill creator validator, local links and evaluation JSON | Passed. |
| `make plugin-build UV_RUN='uv run --no-sync'` | Passed; default runtime includes optional geo dependencies, CSS and JS. |
| `scripts/build_claude_plugin.py --without-geo --offline` | Passed; smaller locked runtime excludes pyproj and Pillow. |
| Isolated `uv run --locked --project .../runtime` | Both variants passed. v1.0 absolute/relative, v1.1 deed-only and supplied vector inputs worked; full variant also rendered raster and imported projected GeoJSON. Minimal variant gave actionable missing-extra error. Original inputs unchanged; no CSV. |
| Packaged HTML in offline Chromium | All five full-runtime cases opened with plotted calls, no external requests and no JavaScript errors; raster image present. |
| Live NJGIN metadata and exact unique retrieval | Passed, **2026-10-27T12:25:01Z**, OBJECTID `1`; only required parcel identity/update fields requested. Three responses retained; source date explicitly unknown. |
| Provider offline replay | Entire returned result equal to live result from retained response bytes. |
| Native PDF/source reading and independent transcription evaluation | **Not run**; remains todo item 6. |
| Actual Claude/Cowork target-host acceptance | **Not run**; local browser/plugin evidence does not establish host acceptance. |

The macOS sandbox prevented uv build/runtime initialization and Chromium launch; these checks succeeded after approved escalation. No provider writes or messages were sent.

Screenshots retained locally in `output/playwright/plot-validation/`: desktop/mobile light/dark, partial, arc, placed vector with hole and raster. Parent inspected the mobile-dark, partial, arc, vector and raster screenshots. Build output is `dist/metesparser-plugin.zip`; diagnostic logs and isolated runtime/live snapshot artifacts are under `/tmp/metesparser-plot-validation/` and `/tmp/metesparser-*.log` (temporary, not tracked). Both final ZIPs' wheel source bytes were compared with the workspace and matched.

## Delegation and scope

The parent integrated schemas/stages, compatibility facade, dependency/build changes and final checks. Separate workers handled plotting geometry, interface/browser behavior, GIS/raster/provider work and documentation. GPT-6-luna handled documentation/evaluations; GPT-6.1-sol handled bounded implementation/review work, including the final independent overlay review and model fixes. The GIS worker reported inherited parent-model execution. Independent review findings were reproduced and fixed before completion.

Unimplemented by design: automatic cross-description/shared-boundary matching (todo 5), inferred recorded bearings, map-based boundary correction, interactive curve editing, drag-to-calibrate, automatic ground/grid factors, verified GIS exports and additional parcel providers. Manual assessment-map alignment remains approximate, and fit residuals are never described as survey accuracy.
