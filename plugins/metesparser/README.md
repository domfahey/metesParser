# MetesParser Claude plugin

This plugin provides ten focused capabilities and two workflows for reviewing metes-and-bounds material. Claude's native document/image reading prepares text from images and PDFs; the bundled deterministic `mp_review` engine parses selected descriptions and verifies geometry. No separate OCR service or conversion dependency is required.

See the [usage guide](references/usage.md) for input routing, examples, artifact meanings, and troubleshooting, and the [changelog](CHANGELOG.md) for user-visible changes. Each skill directory contains a README with its own usage example.

## Skills

Thirteen skills share the same engine: ten capabilities, two workflows, and one compatibility alias.

| Type | Skill | Purpose | Main deliverable |
| --- | --- | --- | --- |
| Capability | [convert-document-to-text](skills/convert-document-to-text/SKILL.md) | Transcribe a supplied document using Claude's native reading. | Full text, page map, acquisition and uncertainty records |
| Capability | [extract-metes-and-bounds](skills/extract-metes-and-bounds/SKILL.md) | Locate and preserve the intended description in prepared text. | Verbatim description and selection/source records |
| Capability | [verify-traverse](skills/verify-traverse/SKILL.md) | Check an identified structured traverse or run explicitly requested relative analysis. | Deterministic review or separate relative-analysis artifacts |
| Capability | [plot-metes-and-bounds](skills/plot-metes-and-bounds/SKILL.md) | Plot the requested boundary, selecting it from a document when needed. | Plot inputs, geometry, HTML, and manifest |
| Capability | [prepare-parcel-overlay](skills/prepare-parcel-overlay/SKILL.md) | Prepare supplied vector or raster map evidence. | Prepared layer and provenance |
| Capability | [render-online-map](skills/render-online-map/SKILL.md) | Render prepared geographic evidence with Mapbox as a local viewer or requested in-chat MCP preview. | Online display artifacts or vector MCP handoff and acceptance report |
| Capability | [compare-descriptions](skills/compare-descriptions/SKILL.md) | Compare two identified descriptions using source-linked structured inputs and explicit criteria. | Advisory component comparison and tentative structural differences |
| Capability | [plot-corridor](skills/plot-corridor/SKILL.md) | Construct a source-bound centerline ribbon with explicit widths, tapers, joins and caps. | Advisory corridor geometry, error/topology evidence and lossless inputs |
| Capability | [plot-plss-reference](skills/plot-plss-reference/SKILL.md) | Compute a supported aliquot from an identified supplied rectangular section reference. | Computed reference layer and source/dataset provenance |
| Capability | [export-review-package](skills/export-review-package/SKILL.md) | Export an identified published revision with explicit format, layer and coordinate choices. | Frozen SVG/PDF/DXF/geographic GeoJSON package and audit sidecars |
| Workflow | [review-metes-and-bounds](skills/review-metes-and-bounds/SKILL.md) | Locate the intended description, then parse and check closure. | Source-selection context and deterministic review artifacts |
| Workflow | [deed-closure-dashboard](skills/deed-closure-dashboard/SKILL.md) | Build an explicitly requested, source-grounded interactive review dashboard. | Offline dashboard and source/calculation/render snapshots |
| Alias | [review-deed](skills/review-deed/SKILL.md) | Route deed-specific review requests to the shared review workflow. | Same deliverable as `review-metes-and-bounds` |

Choose a capability when the user requests one stage; it stops at that deliverable. Choose a workflow when the user requests an end-to-end closure review or an interactive dashboard. `review-deed` is an alternate entrypoint for deed-specific closure requests, not a separate implementation.

[render-online-map](skills/render-online-map/README.md) owns both local Mapbox rendering and vector-only MCP preview. It reuses prepared evidence, checks provenance, preserves local raster/source review, and reports live client acceptance separately. Dashboard composition delegates requested provider rendering to it; an online map alone does not require a dashboard.

## Route and compose

Start at the stage matching the supplied input and requested deliverable. Document plot/plottability and closure requests coordinate native conversion when needed and tract selection; existing structured calls can go directly to verification or plotting. Reuse valid upstream artifacts for unchanged sources. The [usage guide](references/usage.md#choose-the-entrypoint) provides routing examples and stopping points, including isolated prose and map preparation.

For a requested dashboard, populate a source bundle from actual source/page/call records, then use `compose-dashboard BASE_BUNDLE.json --layer PREPARED_LAYER.json --output-dir NEW_DIR` through the launcher to append prepared maps and obtain fresh geometry hashes. For a standalone online map, use `compose-map PLOT_DIR --layer PREPARED_LAYER.json --output-dir NEW_DIR`. These commands retain original inputs, reject conflicting IDs, and return `needs_review`; they do not infer placement or grant verification. See [artifact handoffs](references/artifact-handoffs.md) for accepted inputs, status boundaries, reuse, and invalidation.

The dashboard workflow keeps Claude's native page reading and description selection separate from deterministic rendering. After preparing a validated bundle (version 1.0 for deed-only input, or 1.1 for plot/map fields), run:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" dashboard bundle.json --output-dir dashboard-new --cache-dir dashboard-cache
```

The `metes-review dashboard` package command accepts the same options. Valid input returns `needs_review` (exit 1) and writes an offline dashboard plus source, calculation, plot/map, placement, and manifest snapshots. It does not read PDFs, create a host review log, publish/share output, or write verified CSV. Explicit placements and named-point residual comparisons are supported; automatic matching and inferred alignment are not. See the [dashboard bundle reference](skills/deed-closure-dashboard/references/dashboard-bundle.md#output-cache-and-invalidation) for the exact output files, status, and cache semantics.

Standalone plots use `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" plot INPUT --output-dir NEW_DIR --input-format auto`. Formats are `auto`, `calls`, `relative`, `plot`, and explicit `text`. Structured inputs include strict CSV, calls-list/LegalDescription JSON, RelativeDescription JSON, and PlotRequest JSON. Use `text` only for an already-isolated UTF-8 description; shared preparation retains commencement calls as tie-ins outside boundary geometry and preserves unknown bearings. Output includes an exact-byte source copy (`source.csv`, `source.json`, or `source.txt`), `plot-input.json`, `plot-geometry.json`, `plot.html`, and `plot-manifest.json`. Its top-level status is `needs_review`; plotting does not verify a traverse or create a verified CSV.

The review and verification skills use `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py"`; the launcher starts the locked runtime using `uv` and prints the engine's JSON result. Runtime environments and package cache are stored under the user's cache directory, keyed by the bundled engine fingerprint, so the plugin directory can remain read-only. Using the `python3` prefix avoids depending on executable mode preservation when the plugin is packaged.

## Corridors, supplied PLSS references and delivery

Use [plot-corridor](skills/plot-corridor/SKILL.md) with `analyze-corridor REQUEST.json --output-dir NEW_DIR` for an identified line/arc centerline and ordered endpoint width intervals. Preserve the full step/taper/cap definition and declared linear error budget; unsupported topology has no apparently complete polygon. Retain `boundary_origin_in_centerline_frame` before reusing its normalized boundary plot in a centerline placement.

Use [plot-plss-reference](skills/plot-plss-reference/SKILL.md) with `derive-plss REQUEST.json --output-dir NEW_DIR` only for a supplied identified reference dataset, compatible projected units and the supported rectangular rule. The output is computed reference geometry and a prepared layer, without an HTML viewer or legal subdivision claim. A PLSS recital alone does not justify nominal section corners or dimensions.

Use [export-review-package](skills/export-review-package/SKILL.md) with `export-review BUNDLE.json --revision-dir REVISION_DIR --request REQUEST.json --output-dir NEW_DIR` for a published intended revision. It freezes requested layer/format/unit choices and reports representation omissions. Presentation rotation affects SVG/PDF only; geographic GeoJSON requires explicit geographic evidence. None of these capabilities promotes source review or canonical verification, and each stops at its own deliverable.

## Validate, inspect, and diagnose

Source records use schema `1.1`; the [source-preparation reference](references/source-preparation.md) documents byte/page/span fields, legacy migration, and validation. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" validate-source BUNDLE_DIR` after creating or receiving acquisition/selection records. When reuse or freshness is unclear, run `inspect-artifacts BUNDLE_DIR --requested-stage STAGE`; it is read-only and reports known dependencies and restart guidance. For a requested explanation of supported line/circular-arc closure sensitivity, use `diagnose-closure REQUEST.json --output-dir NEW_DIR` and the [diagnosis contract](references/closure-diagnostics.md).

These completed advisory operations return `needs_review` and exit 1 even for structurally valid/matching records or supported diagnosis. Exit 2 means invalid input or no result. Inspect each operation's detail fields; neither source validation, artifact usability, nor diagnosis establishes source accuracy or canonical verification. [Artifact handoffs](references/artifact-handoffs.md) defines the discovery and status boundaries.

## Locate before checking closure

Start by locating the boundary description requested, whether it appears in a survey, plat, exhibit, deed, title document, report, correspondence, image, or another source. For document/image sources, use Claude's native conversion to save text, then isolate the description verbatim. Keep page references, exceptions, and uncertainty records. Clarify ambiguous parcels or material illegibility before calculation. For an already selected description or structured call set, identify it as the intended boundary and proceed to the existing deterministic check.

Native conversion and description selection depend on Claude's reading of the source; closure cannot prove those stages were complete or accurate. Retain the acquisition and selection records described in [source preparation](references/source-preparation.md). Native reading must be available in the current Claude session; disclose unsupported or unreadable sources rather than silently substituting another provider.

The engine uses exit code 0 for `checks_passed`, 1 for `needs_review`, and 2 for `error`. A passing status is limited to implemented deterministic checks and is not a legal or survey certification. See `references/review-limits.md`.

## Project settings

From your project root, optionally create `.claude/metesparser.local.md`:

```markdown
---
enabled: true
output_dir: deed-reviews
---
```

Then run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" review description.txt`; each review gets a fresh folder under `deed-reviews`. Explicit `--output-dir` wins. Set `enabled: false` to stop processing. Settings are read on each run, so no restart is needed. Add `.claude/*.local.md` and `.claude/*.local.json` to your project's `.gitignore`; these files are user-local.

See [settings schema and validation](references/plugin-settings.md). Verification tolerances and parsing strictness are not configurable.

## Optional Mapbox companion

Use [render-online-map](skills/render-online-map/SKILL.md) for an explicitly requested online map. The [local viewer procedure](skills/render-online-map/references/local-viewer.md) documents configuration, the `web-map` extra, opt-in `--with-web-map` build, and loopback `serve-map` preview. The [MCP procedure](skills/render-online-map/references/mapbox-mcp.md) covers an in-chat vector preview from retained geographic stages. A local public token is entered at runtime and Connect precedes provider requests; MCP uses the configured connection only within the requested external-preview scope. Neither mode changes verification. Live Mapbox and native-host acceptance remain separate gates.
