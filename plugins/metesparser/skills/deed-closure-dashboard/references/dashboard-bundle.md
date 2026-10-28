# Dashboard bundle reference

The offline dashboard accepts `schema_version: "1.0"` deed-only bundles and `"1.1"` bundles with plot/map fields. Its Pydantic schema is `mp_models.dashboard.DashboardBundle`; the package is the authoritative, versioned contract. This page summarizes the fields and important validation rules without duplicating every model constraint. Version 1.0 remains supported; version-specific validation rejects plot/overlay fields in a 1.0 input instead of silently dropping them.

Contents: [Top-level fields](#top-level-fields) · [Compose existing plot and map artifacts](#compose-existing-plot-and-map-artifacts) · [Status fields](#status-fields) · [Output, cache, and invalidation](#output-cache-and-invalidation) · [Runnable example](#runnable-example) · [Optional Mapbox companion](#optional-mapbox-companion)

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

Compose a valid source bundle (`BASE_BUNDLE.json`) with existing map-preparation artifacts through the bundled locked runtime. Use the launcher in an extracted distribution:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" compose-dashboard BASE_BUNDLE.json --layer PREPARED_LAYER.json --output-dir COMPOSED_NEW
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" dashboard COMPOSED_NEW/bundle.json --output-dir NEW_DASHBOARD_DIR
```

In a source checkout, use `uv run metes-review compose-dashboard BASE_BUNDLE.json --layer PREPARED_LAYER.json --output-dir COMPOSED_NEW`. Repeat `--layer` for additional artifacts, or omit it to validate an existing bundle and obtain freshly computed geometry hashes. The command validates the original source ledger, appends only supported map arrays, upgrades the output schema to `1.1`, and uses the shared dashboard preparer. It does not import standalone plot geometry, infer placement, create source records, or add reading/review attestations.

The new directory contains validated `bundle.json`, `composition-manifest.json`, the byte-exact original `inputs/base-bundle.json`, and complete preparation sidecars `inputs/layer-N.json`. The single JSON result and manifest expose `geometry_hashes` keyed by calculation ID. Source quotes, relative constraints, IDs, review fields, and provenance are retained. Wrappers such as `operation` and `original_base64` stay in their complete preparation sidecars rather than being added as unsupported bundle fields.

Composition does not render or call providers. Valid composition returns `needs_review` (exit 1), with `engine_verified`, `verified_export_eligible`, and `source_review_complete` false at the command level. Invalid source/overlay records, ID collisions, stale placements, and existing output paths return `error` (exit 2) without overwriting inputs. Source review and canonical verification remain separate stages. Use a fresh output directory.

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

Online rendering is owned by [render-online-map](../../render-online-map/SKILL.md). The dashboard workflow owns source/bundle assembly and delegates the requested provider view. Follow the [local viewer procedure](../../render-online-map/references/local-viewer.md) for configuration, optional dependencies, rendering, runtime tokens, preview, and fallback. The existing `dashboard --online-map-config` command remains a compatibility path.
