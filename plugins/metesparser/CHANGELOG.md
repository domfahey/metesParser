# Changelog

Record user-visible plugin changes here. Keep pending changes under Unreleased and group entries by Added, Changed, or Fixed. Dates and release versions should describe actual releases; this plugin has not been published to a marketplace.

## [Unreleased]

### Added

- A paired skill-evaluation protocol reuses existing scenarios, hides grading rubrics from responding agents, and records model/client evidence separately from engine and provider checks. Claude model coverage remains unrun.
- Standalone `render-map` composes prepared plot/map artifacts without a dashboard, revalidates shared geometry and placement identities, and retains an offline evidence fallback. `mapbox-mcp` accepts these intact stages or legacy dashboard stages.
- `render-online-map` capability owns local Mapbox viewer and requested vector-only MCP preview, bringing the catalog to six capabilities, two workflows, and one alias.
- Optional `mapbox-mcp` handoff in `render-online-map`: validates retained geographic artifacts, prepares vector-only render arguments, records omissions and digests, and keeps connected-tool/provider/client acceptance separate from local preparation and verification.
- `plot-metes-and-bounds` creates a standalone plot from structured calls, RelativeDescription JSON, or PlotRequest JSON and stops after plot artifacts.
- `prepare-parcel-overlay` prepares supplied vector/raster evidence and provenance without placing deed geometry or building a dashboard.
- Shared artifact handoff guidance defines accepted inputs, outputs, status boundaries, source identity, invalidation, and resume behavior.
- `analyze-relative` command for source-linked straight-course interior/exterior, perpendicular, and parallel constraints in a declared local frame. Reports unresolved/contradictory constraints separately, preserves unknown recorded bearings, and never authorizes verified CSV export. Includes a runnable synthetic rectangle and replaces the dashboard playbook's inline calculation.
- `deed-closure-dashboard` skill now builds from a validated version 1.0 source bundle and the offline renderer, with separate source-review status and advisory scenarios. Includes a synthetic runnable bundle example.
- `convert-document-to-text` uses Claude's native document/image reading for PDFs, scans, images, and other supported sources, with source coverage and uncertainty records.
- `extract-metes-and-bounds` locates complete descriptions in any document, preserves source wording and locations, and separates candidate tracts.
- `review-metes-and-bounds` coordinates description identification before deterministic closure checks.
- Shared usage and source-preparation documentation, plus a README for each skill.
- Evaluation cases for native conversion, illegible survey bearings, historical versus requested descriptions, ambiguous tracts, and missing exhibits.

### Changed

- Skill entrypoints link runtime prerequisites and conditional procedures directly; long dashboard references include contents links. Mapbox MCP instructions require the exact discovered, fully qualified host tool identifier.
- Dashboard source/bundle assembly delegates online rendering to `render-online-map`; plot and overlay capabilities route later map requests there without acquiring or verifying sources again. Detailed local-viewer and MCP procedures moved to the renderer skill; prior dashboard reference paths remain compatibility links.

- `review-deed` delegates to the document-agnostic workflow; `verify-traverse` accepts an identified structured boundary and routes unselected documents to description selection.
- Capability skills stop at their requested artifacts; review/dashboard workflows reuse valid handoffs and continue only when requested. `verify-traverse` clearly separates canonical verification from explicitly requested relative analysis.
- Dashboard discovery is limited to explicit dashboard/workbench requests. Renderer guidance now describes supported explicit placements and named-point comparisons while retaining the boundary against automatic matching.
- Closure requests now locate the intended description before calculation. Native conversion, Claude's section selection, and deterministic verification remain distinct evidence stages.
- Scanned documents use Claude's native reading when available instead of always requiring a user-provided transcription. No separate OCR provider or conversion dependency is added.
- Dashboard guidance now reflects explicit placement and named-point comparison support. Automatic corner matching remains unsupported; canonical baseline calculations support curves, while browser edits are limited to straight-course scenarios.

### Removed

- Plugin/skill-authoring guides mistakenly bundled as runtime skills; the runtime catalog now covers document conversion, description selection, traverse verification, plotting, overlay preparation, and the review/dashboard workflows. Project settings remain supported.

### Fixed

- Online-map documentation and evaluation expectations now cover standalone composition, map layers without deed placement, and the explicit unavailable viewer with offline evidence when georeferencing is missing.
- Circular boundaries now check line–arc and arc–arc contacts, overlaps, and unsupported geometry before verified export, while allowing legitimate shared endpoints. Unequal-radius intersections are independent of argument order.
- Closing point/place-of-beginning wording no longer causes the spurious multiple-BEGINNING warning, without merging or dropping valid POINT/PLACE OF BEGINNING tract openings.

## [1.0.0]

Initial local plugin baseline, recorded for the existing manifest version; not a public marketplace release.

### Added

- Deterministic text/CSV/JSON review engine, guarded verified export, field-level audits, and an analytic regression corpus.
- `review-deed` and `verify-traverse` skills with a locked, fingerprinted runtime and portable launcher.
- Project-local `enabled` and `output_dir` settings, with safe YAML validation and per-run reloads.

## Validation limits

Local checks cover skill/frontmatter validation, reference links, deterministic engine behavior, runtime provisioning, and packaged launcher workflows. Native Claude document conversion and end-to-end Claude client behavior have not been exercised. Evaluation scenarios are specifications unless accompanied by recorded execution evidence.

## Optional online map companion

- Added explicit Mapbox renderer composition to the existing dashboard workflow, with shared handoff/invalidation rules, token-free configuration, loopback preview guidance, and offline fallback.
- Documented `web-map` dependencies and opt-in `--with-web-map` distribution, baseline-only 2D display, warped registered rasters, independent accuracy/status measures, and runtime public-token connection.
- Updated artifact-reuse evaluation to require fresh dashboard geometry/placement validation; added online reuse, missing-georeference, provider-failure, and status-separation cases. Authored evaluations do not establish native-host or live-provider acceptance.
