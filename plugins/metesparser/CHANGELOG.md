# Changelog

Record user-visible plugin changes here. Keep pending changes under Unreleased and group entries by Added, Changed, or Fixed. Dates and release versions should describe actual releases; this plugin has not been published to a marketplace.

## [Unreleased]

### Changed

- **License:** MetesParser is now licensed under the GNU Affero General Public License, version 3 only (`AGPL-3.0-only`), replacing MIT, with commercial licenses available from the copyright holder. No version was released publicly under MIT. See [License](../../README.md#license).

## [2.0.0] - 2026-11-01

Included with MetesParser v0.7.0, with the review engine 2.0.0. Reviews saved by the 1.0.0 engine inspect as stale and must be re-run. This is not a marketplace publication.

### Added

- A separate standalone Claude chat Skill build reuses this plugin's engine and capability procedures. The plugin archive and launcher remain unchanged; the chat adapter adds its own entrypoint, paths and explicit runtime setup. Native chat acceptance is pending.

### Changed

- `review-deed` and `review-metes-and-bounds` follow the description-role export policy: a deed with more than one description cannot produce a verified export unless every description's role comes from a plain `PARCEL`/`TRACT` heading, easement and exception tracts are never eligible, and text review takes one description per review. See [multiple descriptions](references/review-limits.md#multiple-descriptions).
- Skill descriptions for `plot-plss-reference`, `prepare-parcel-overlay`, `render-online-map`, `review-deed`, `review-metes-and-bounds` and `verify-traverse` now state what each does, when to use it and which sibling to use instead. `review-deed` is a manual slash alias (`disable-model-invocation`). The shared references state the multiple-description and verified-export rules and the status table once, and the relative-analysis reference moved to `references/relative-analysis.md`.

### Fixed

- Simplify the shared overlay launcher guidance so it remains accurate in the plugin and adapted chat procedure. Chat setup and resume guidance now explicitly distinguish bootstrapping, extraction and artifact inspection.

## [1.0.0] - 2026-10-29

First GitHub-distributed plugin archive, included with MetesParser v0.6.0. The manifest version remains 1.0.0; this is not a marketplace publication.

### Added

- Focused `plot-corridor`, `plot-plss-reference` and `export-review-package` capabilities complete the 13-skill catalog (ten capabilities, two workflows and the `review-deed` compatibility alias). Corridor and PLSS requests retain explicit construction/reference/revision identities and document supported inputs and refusal limits.
- Executable synthetic document-intake, multi-tract resume, guided scan/deed-placement, corridor, PLSS and published-delivery evaluation inputs. Candidate artifacts omit evaluator rubrics; multi-tract turn-two evidence stays withheld until that turn. Materialization/runtime checks are separate from model/native acceptance.

- Read-only schema 1.1 source-handoff validation, bounded artifact freshness inspection with conditional resume recommendations, and standalone identity-bound closure diagnosis; each preserves advisory `needs_review`/exit 1 semantics.
- Durable revision save/load preserves exact incomplete draft fields, source-correction readings and evidence, stable source identities, and immutable published generations. Schema 1.2 retains exact corridor requests, explicit removals, and freshly replayed geometry with each saved revision.
- Structured line and circular-arc editing publishes through the shared revision store and renders from freshly prepared revision geometry. The immediate browser preview remains straight-course only; arc edits use the shared publication/rendering path.
- Immutable review-package delivery exports SVG, PDF, DXF and GeoJSON from a published revision, with independent artifact inspection and freshness checks. An optional raster control-point picker produces validated inputs for the existing registration workflow; it does not assign deed placement.
- Deterministic corridor construction retains interval widths, tapers, joins and caps through revision save and delivery. Supplied PLSS reference data is derived only for the documented supported subset; unsupported or incomplete references remain explicit outcomes.
- Closure sensitivity panel in supported dashboard work, plus independent per-raster visibility, opacity, and layer-order controls with fit/checkpoint, basis, and placement evidence summaries. Controls remain presentation-only.
- Added the focused `compare-descriptions` capability for explicit source-linked `ComparisonRequest` inputs, advisory geometric components, and tentative structural differences.
- Explicit `plot --input-format text` prepares an isolated description through shared parsing, preserves its source bytes, and separates commencement-to-POB tie-ins without running canonical verification.
- Packaged-runtime `compose-map` and `compose-dashboard` commands assemble existing artifacts, preserve provenance, and expose fresh geometry hashes without ad hoc workspace Python setup.
- Behavioral evaluation scenarios cover commencement plotting, packaged composition, and direct relative-analysis routing.
- A paired skill-evaluation protocol reuses existing scenarios, hides grading rubrics from responding agents, and records model/client evidence separately from engine and provider checks. Claude model coverage remains unrun.
- Standalone `render-map` composes prepared plot/map artifacts without a dashboard, revalidates shared geometry and placement identities, and retains an offline evidence fallback. `mapbox-mcp` accepts these intact stages or legacy dashboard stages.
- `render-online-map` capability owns the local Mapbox viewer and requested vector-only MCP preview.
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

- Introduce the plugin as a POC and simplify introductory review wording while retaining runtime requirements and precise verification boundaries.
- Natural document-to-plot and plottability routing reuses native conversion and selection, returns concise source coverage, and stops at the requested scope. Explicit multi-tract requests retain independent results and resume points.
- Guided raster controls and separate deed placement evidence reuse registration/composition APIs; current dashboard control and resume guides preserve source, geometry and map status distinctions. New routing scenarios remain specifications until paired native sessions run.

- `verify-traverse` discovery metadata includes explicitly requested relative-angle analysis as well as canonical verification of selected calls.
- Skill entrypoints link runtime prerequisites and conditional procedures directly; long dashboard references include contents links. Mapbox MCP instructions require the exact discovered, fully qualified host tool identifier.
- Dashboard source/bundle assembly delegates online rendering to `render-online-map`; plot and overlay capabilities route later map requests there without acquiring or verifying sources again. Detailed local-viewer and MCP procedures moved to the renderer skill; prior dashboard reference paths remain compatibility links.

- `review-deed` delegates to the document-agnostic workflow; `verify-traverse` accepts an identified structured boundary and routes unselected documents to description selection.
- Capability skills stop at their requested artifacts; review/dashboard workflows reuse valid handoffs and continue only when requested. `verify-traverse` clearly separates canonical verification from explicitly requested relative analysis.
- Dashboard discovery is limited to explicit dashboard/workbench requests. Renderer guidance now describes supported explicit placements and named-point comparisons while retaining the boundary against automatic matching.
- Closure requests now locate the intended description before calculation. Native conversion, Claude's section selection, and deterministic verification remain distinct evidence stages.
- Scanned documents use Claude's native reading when available instead of always requiring a user-provided transcription. No separate OCR provider or conversion dependency is added.
- Dashboard guidance reflects explicit placement and named-point comparison support. Automatic corner matching remains unsupported. Canonical verification and shared revision publication/rendering support circular arcs; only the immediate browser preview is limited to straight-course scenarios.
- Curve-aware closure diagnosis and description comparison report supported circular-arc effects and explicit unavailable reasons without promoting advisory results to canonical verification.
- Corridor offset and GeoJSON delivery preserve declared approximation bounds through shared arc sampling and coordinate transforms; invalid width coverage and unsupported geometry remain explicit outcomes.

### Removed

- Plugin/skill-authoring guides mistakenly bundled as runtime skills; the runtime catalog now covers document conversion, description selection, traverse verification, plotting, overlay preparation, and the review/dashboard workflows. Project settings remain supported.

### Fixed

- Report missing or changed review/plot HTML separately from replayed geometry during artifact inspection, using the producer-recorded display hashes.
- Preserve per-call delivery provenance so untouched calls remain recorded when another call or tract is edited or source-corrected.
- Keep the raster-control example inside the packaged guide instead of linking to evaluation fixtures omitted from the ZIP.
- Online-map documentation and evaluation expectations now cover standalone composition, map layers without deed placement, and the explicit unavailable viewer with offline evidence when georeferencing is missing.
- Circular boundaries now check line–arc and arc–arc contacts, overlaps, and unsupported geometry before verified export, while allowing legitimate shared endpoints. Unequal-radius intersections are independent of argument order.
- Closing point/place-of-beginning wording no longer causes the spurious multiple-BEGINNING warning, without merging or dropping valid POINT/PLACE OF BEGINNING tract openings.
- Delayed draft input updates are no longer overwritten by an older file load or save completion; source corrections remain bound to their original document, tract, occurrence and call identities.
- DXF class registration is sorted before writing, making delivery bytes deterministic across fresh processes and Python hash seeds.
- Corridor GeoJSON samples analytic arcs using the declared geographic rendering tolerance after placement rotation and unit conversion, subject to explicit vertex and recursion limits. Construction error remains separately recorded.

## Initial local baseline (manifest 1.0.0)

Historical development baseline before the first GitHub-distributed archive.

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
