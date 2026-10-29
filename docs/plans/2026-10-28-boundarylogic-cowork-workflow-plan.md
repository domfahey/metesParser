# BoundaryLogic inspired Claude Cowork workflow improvements

Date: 2026-10-28

Status: **local implementation complete; native Claude/Cowork acceptance not run**. Current results and remaining acceptance gates are recorded in the [implementation evidence ledger](../implementation/2026-10-28-cowork-workflow-ledger.md).

Revision: incorporates findings A01–A10 from the [research and REA audit](2026-10-28-boundarylogic-cowork-plan-audit.md). Checked implementation items have local evidence in the linked ledger. Native acceptance and release gates remain separately recorded; implementation checkmarks do not establish observed Cowork behavior.

## Goal and relationship to existing work

Provide a coherent Cowork workflow: bring a deed, understand the source, inspect its geometry, explore documented changes, compare versions, and deliver a reproducible review package. Preserve independently useful capabilities and stop after the user's requested output.

This is a follow-on to the [source evidence and review improvements plan](2026-10-28-skill-evidence-and-review-improvements.md), whose current results are recorded in the [implementation evidence ledger](../implementation/2026-10-28-evidence-review-ledger.md). It also builds on the [plot and overlay plan](2026-10-26-deed-plot-and-tax-overlay-plan.md). Do not reopen their completed implementation tasks or duplicate their native-client evaluation backlog.

The [BoundaryLogic reconstruction](../reference/boundarylogic-reverse-engineering.md) supplies functional design input from public documentation and captured client code. It does not establish authenticated behavior, backend implementation, or numerical correctness. Target observable user outcomes; retain MetesParser's own verification requirements.

## Existing foundation and remaining gaps

| Area | Already available | Improvement in this plan |
| --- | --- | --- |
| Source intake | Native-reading instructions, description selection, source records and validation; native Claude/Cowork acceptance remains unrecorded | Natural document-to-plot routing, explicit multi-tract composition and a concise intake assessment |
| Resume | Read-only artifact inspection, dependency hashes and restart guidance | Consistent conversational handoff and cross-session reuse |
| Workbench | Source/call/segment linkage, straight-call scenarios, live diagnostics and reset | Discoverable controls, durable alternatives and richer call editing |
| Geometry review | Circular plotting; straight-course diagnosis and description comparison | Curve-aware diagnosis and comparison |
| Mapping | Explicit placement, affine raster registration, layer controls and map composition | Guided preparation of placement/registration inputs; optional control-point UI |
| Delivery | CSV, HTML, internal SVG rendering, geographic feature handoffs and manifests | User-facing revision-specific SVG/PDF, DXF and GeoJSON delivery |
| Domain coverage | Easement classification and PLSS metadata extraction | Centerline corridors and a supplied-reference PLSS geometry adapter |

## Architecture and invariants

- Keep skills responsible for discovery, composition, evidence handling and explanation. Use the [skill maintenance guide](../CLAUDE_PLUGIN.md#maintain-the-skill-composition); extend existing owners before adding a capability with a separate deliverable.
- Keep schemas in `mp_models`, numerical work in `mp_parse`, `mp_bearing` and `mp_verify`, command/file adapters in `mp_review`, and rendering/exporters in `mp_export`. Maintain existing compatibility facades rather than duplicating implementations.
- Preserve exact source wording and unresolved values. Account for every source course, including rejected or incomplete calls. A closing subset must not hide omitted evidence.
- Keep source completeness, geometry availability, canonical verification, scenario results, placement and registration findings separate. Advisory `needs_review` exit 1 is a completed result, not an invocation failure.
- Retain the fresh canonical verification gate for `_verified.csv`, including closure below 0.01 ft and the applicable check/warning rules. Rendering, comparison, scenarios and successful exports cannot grant eligibility or source-review approval.
- Preserve original source and record values. Write revisions to new artifacts/directories; bind dependent results to source and geometry identities. A source correction requires supporting evidence; a hypothetical edit remains a scenario even if it closes.
- Require explicit CRS, units, placement and registration evidence. Mapbox credentials stay in the runtime connection flow. Do not infer geography, fit a deed to imagery or silently replace a PLSS reference with a nominal square.
- Keep Claude native source reading separate from the provider-backed `mp-ocr` pipeline. Downstream calculations remain deterministic.

## Delivery sequence

| Phase | Deliverable | Dependency and release boundary |
| --- | --- | --- |
| A | Natural routing, intake, dashboard guidance and resume | First independently useful release; evaluate actual native behavior |
| B | Persistent scenarios and documented source corrections | Reuse A's handoffs; first editing release |
| C | Reproducible review package and portable exports | Baseline exports can start early; scenario exports depend on B |
| D | Guided placement and registration | Can proceed after A using existing preparation APIs |
| E | Curve-aware review and complete call editing | Saved editing depends on B; curve analysis can proceed independently |
| F | Centerline corridor capability | Separate domain release with independent geometry validation |
| G | PLSS reference geometry | Separate domain release using supplied authoritative data |

Recommended initial scope: A and B, then C. Deliver D as a bounded workflow improvement. Treat E, F and G as subsequent capabilities with their own supported-input contracts.

## Phase A Natural routing and resumable review

Example requests: “Plot the boundary in this deed,” “Can this description be plotted?” and “Continue yesterday's review with this new scan.”

Implementation:

- [x] Add explicit document → conversion when needed → description selection → plot composition to existing skill metadata and the [usage guide](../../plugins/metesparser/references/usage.md). Keep plot-only requests free of automatic verification or dashboard creation.
- [x] Return a compact intake outcome: intended tract, source coverage, supported/unresolved geometry, available/missing placement evidence, and the exact missing input needed. Ask for tract selection when multiple candidates remain ambiguous.
- [x] Expose source-linked accounting for parsed boundary, tie/reference, intentionally excluded and unresolved/rejected material, with reasons and actual page/span identities. Reuse source/audit records; unknown coverage remains unknown rather than an invented total course count.
- [x] For an explicit request to review several identified tracts, reuse one acquisition with separate selection/review identities and results per tract. Return a combined inventory; record why historical quotations or other descriptions are outside the requested set. One blocked tract must not prevent independent requested results or imply that the whole set passed.
- [x] Add a short delivery guide for existing source selection, straight-call scenario editing, diagnostics and reset controls.
- [x] Standardize resume responses around the [artifact handoff contract](../../plugins/metesparser/references/artifact-handoffs.md): selected source, current result, unresolved issues, retained artifact location and earliest required next stage. Reuse `inspect-artifacts`; do not create another resume engine.
- [x] Extend existing routing/restart cases and materialize actual source fixtures with hidden evaluator rubrics.
- [ ] Run fresh baseline/with-skill native sessions using the existing evaluation protocol. After isolating a stalled custom endpoint, CLI readiness reports expired OAuth; native desktop window access was unavailable. See the implementation ledger.

Acceptance: complete calls produce the requested plot; missing exhibits, unreadable digits, cardinal-only bearings and lot/block-only inputs retain their distinct limitations. Valid local geometry does not imply map placement. Unchanged artifacts are reused; changed dependencies restart at the correct stage. No unnecessary provider call or downstream capability runs.

Required negative cases: an unreadable middle course surrounded by cancelling valid courses; duplicate/missing courses; an exception after the POB; a missing continuation; and comma-separated lot/block prose. A closing surviving subset cannot imply complete source review, conceal excluded material or produce nominal PLSS geometry. For two requested operative tracts plus a historical quotation, with one unreadable operative course, retain separate outcomes and resume only the affected tract without merging traverses.

Primary ownership: existing `plugins/metesparser/skills/` instructions, shared usage/source/handoff references, and `plugins/metesparser/evals/`. Keep the ten-skill catalog unless an independently useful new capability warrants expansion.

## Phase B Durable scenarios and source corrections

Example requests: “Save this alternative and compare it tomorrow” and “The scan says 177.72 on page 3; update the reading and show what changed.”

Implementation:

- [x] Extend the existing `DashboardScenario` and `DashboardEdit` contracts with a versioned saved-revision envelope: baseline identity/hash, stable document/tract/occurrence/call identities, edit values, rationale and available source references. Preserve identities across rename/reorder; identical names or calls cannot substitute for identity.
- [x] Distinguish exact draft input, parsed revision, last-valid geometry and published revision. Phase B must save and reopen incomplete inputs in its existing editable fields, including raw text/form values, errors and identities. Phase E extends this contract to new line/curve entry. A saved draft establishes recoverability, not successful parsing or updated geometry; retain the last-valid geometry under its own revision label.
- [x] Add save/load controls and a deterministic import adapter. Reject malformed revision envelopes and mismatched baselines; retain incomplete domain input as an explicit draft rather than silently applying or discarding it.
- [x] Publish a revision manifest only after all required local artifacts succeed. Interrupted writes remain identifiable as incomplete, leave the prior published revision intact and support retry without duplicate tracts. Require an explicit remove action; missing or unparseable input is not deletion. Bind save results to their originating revision so late completion cannot overwrite newer edits.
- [x] Expose pending/failed/published save states. Preserve pending drafts across supported navigation/reload, or offer retry/discard before leaving when recovery is unavailable. Exports must name a published revision; a pending or failed save cannot silently fall back to older geometry. Selecting an older published revision is explicit and labeled.
- [x] Document separate amendment paths: hypothetical edits remain advisory scenarios; supported transcription corrections create fresh source-selection/call artifacts while retaining the earlier reading and page/quote evidence.
- [x] Recompute affected geometry and comparisons using shared APIs. Invalidate stale placements and dependent exports; require a separately requested fresh canonical verification for revised record calls.

Acceptance: save → close → reopen reproduces the exact alternative and rationale; stale or malformed revisions fail explicitly; reset restores the unchanged baseline. A closing scenario cannot modify canonical status. A supported source correction retains both readings and invalidates downstream identities correctly.

Failure acceptance: delay a save beyond 2.5 seconds, reject it, edit again while saving and switch documents. Fail the second of two tract writes, interrupt manifest publication, retry create/remove and rename/reorder identically named tracts. The prior revision survives; incomplete publication is not reusable as complete; no late save, retry or heuristic match loses or reassigns content. Reopen a partly entered bearing and text-only annotation exactly; Phase E repeats this with unsupported/incomplete curve entry. Old geometry must never appear to be the result of an unresolved current draft.

Primary ownership: `mp_models.dashboard`, `mp_review` revision adapters, `mp_export/dashboard_assets/dashboard.js`, and the dashboard skill references. Version schema changes and retain compatibility with existing bundles.

## Phase C Reproducible review packages and exports

Example request: “Prepare this named version for my surveyor.”

Implementation:

- [x] Define an explicit export request selecting a published source/call revision, recorded or scenario geometry, coordinate mode, placement ID/hash/status, CRS, units and foot definition, rotation convention/pivot, included layers/order, labels and output formats. Freeze effective visibility and membership in the request; do not infer scope from the last browser viewport. Unknown units remain explicit and block conversions that require a known definition.
- [x] Generate drawing, call table, metrics and manifest from one validated immutable snapshot. Pending/failed saves block export of that draft until publication or explicit selection of a labeled older revision. Never substitute last-valid geometry for current unresolved input. Publish the package manifest only after all components succeed; interrupted generation leaves a clearly incomplete, retryable result.
- [x] Package source references, selected calls, plot, unresolved findings and input identities/exporter versions. Keep unavailable metrics null/unavailable with reasons, never numeric zero. Include full source documents only when requested.
- [x] Expose SVG and PDF output from existing geometry/rendering primitives. Keep recorded and hypothetical results clearly identified.
- [x] Add DXF preserving line/arc geometry, units, stable call identifiers and layers. Add general GeoJSON export by reusing existing geographic preparation; require valid geographic evidence for geographic coordinates and declare any curve approximation tolerance.

Coordinate policy: record-local export uses unchanged local geometry; placed export applies the selected evidence-bound placement. Preserve recorded bearings separately from transformed geometry. Presentation rotation affects SVG/PDF appearance only; CAD/GIS coordinates change only through the explicitly selected placement. Source, placement and presentation transforms remain separately identifiable.

| Format | Initial content contract | Fidelity and omission policy |
| --- | --- | --- |
| SVG/PDF | Line/arc drawing, requested labels/table and requested supplied raster backgrounds | Honor snapshot order, visibility and opacity; visually check clipping and alignment. Unsupported required content blocks delivery. |
| DXF | Local or explicitly placed line/arc entities, call IDs, units and layers | Raster embedding and presentation labels are outside the initial adapter. Report omissions; required unsupported content blocks delivery. |
| GeoJSON | Geographic features and source/call/status properties from validated geographic preparation | Report curve linearization tolerance. Raster content and drawing appearance are not reproduced; report these limits and block requests requiring them. |

Zero opacity is a display setting, not geometry exclusion. Explicit request membership controls export; flattened group visibility/order must agree with it. Optional omissions appear in the manifest and delivery summary; required content cannot be silently dropped.

Acceptance: independent readers recover expected endpoints, arc sweep, units and layer selection. PDF visual inspection verifies labels, clipping, page layout and status. All formats identify the same selected revision, and changed inputs cannot silently produce a stale package. Unplaced geometry remains local; unsupported geographic export reports the missing evidence. Export success does not create verified status.

Adversarial acceptance: use an asymmetric line/arc parcel with placement, presentation rotation, raster background, hidden layer/group and zero-opacity vector. Compare preview, tables, metrics, manifest and independently read files against the frozen request and declared transform policy. Repeat with delayed/failed saves, changed placement, unavailable metrics and interrupted generation; reopening cannot mistake an incomplete package for a complete one. Do not use the inconsistent published BoundaryLogic API sample as a numerical golden fixture.

Primary ownership: versioned requests in `mp_models`, adapters in `mp_review`, exporters in `mp_export`, and thin delivery instructions in existing workflows.

## Phase D Guided placement and registration

Example request: “Put this scan behind my plot using these control points.”

Implementation:

- [x] Guide the user through supplied map identity, CRS, units, pixel convention, named fit controls and independent checkpoints.
- [x] Produce validated inputs for the existing raster-registration, composition and rendering commands. Explain fit residuals, checkpoint residuals and deed misclosure separately.
- [x] Separately collect deed position/orientation evidence and author a translation/rotation placement using the existing permitted transform contract. Bind it to fresh deed geometry and the selected scene. Raster controls do not establish deed placement; preserve approximate/unplaced status when evidence is insufficient, and do not upgrade standalone placement to referenced outside its supported contract.
- [x] Add an optional control-point picker only after the guided input-file workflow succeeds. Reuse existing opacity, visibility and ordering controls.

Acceptance: supplied independent controls produce the expected transform and residuals. A good fit with poor checkpoints remains visibly problematic. Changes to controls, units, CRS or deed geometry invalidate affected results. Missing alignment evidence remains unresolved; no automatic fit-to-deed operation is introduced.

Separation acceptance: a registered raster with good checkpoints but no deed control leaves the deed unplaced. Changing deed geometry invalidates its placement without invalidating an unchanged independent raster registration. Rebuilding the combined display revalidates both dependencies.

Primary ownership: overlay/map skill references first; existing `mp_review.raster_registration`, composition adapters and renderer UI only where additional authoring support is needed.

## Phase E Richer geometry review and call editing

Example requests: “Explain how this amended road curve changes the parcel” and “Insert the omitted course shown on page 3.”

Implementation:

- [x] Extend comparison and closure diagnosis to explicitly supported circular arcs, reusing analytic plotting/curve math. Define supported parameters and unavailable-result reasons before adding UI.
- [x] Preserve existing redundant-measurement and orientation consistency checks in diagnosis, comparison, editing and export. Define independent parameters and constraints for sensitivity calculations; do not perturb redundant inputs inconsistently or adopt precedence rules that discard conflicting evidence.
- [x] Add structured line/curve entry and add/delete/reorder actions to the existing editor, with stable identities and source links. Retain unresolved drafts instead of replacing them with last-valid geometry.
- [x] Freeze a supported-input matrix for forms/adapters before implementation, using the contract below. Expose unsupported inputs as source evidence with reasons; do not promise BoundaryLogic DSL compatibility.
- [x] Save edits through Phase B and regenerate plots through shared adapters. Prefer structured forms/table entry over introducing another surveying language.

| Input concern | Required semantics |
| --- | --- |
| Angle representation | Explicit quadrant/DMS, decimal-degree or packed-DMS type; `45.3020` cannot select its own interpretation |
| Distance and units | Retain original values/units and deterministic conversions; unsupported or unknown units remain explicit |
| Orientation | Distinguish supplied and derived/inherited orientation; inheritance requires sufficient preceding evidence, otherwise remain unresolved |
| Course roles | Declare supported boundary, commencement/tie, reference, intentionally omitted and derived roles; roles determine calculation participation, not loss of source evidence |
| Relative inputs and annotations | Route supported relative inputs through existing relative analysis; comments/monuments do not invent coordinates; any future derived closing call remains a scenario |

Acceptance: independent analytic fixtures and finite-difference checks cover radius/sweep/orientation sensitivity, reversed traversal and partial curve evidence. Curves are not silently replaced by chords. Insert/delete/reorder retains identity and source association, preserves the original, and invalidates dependent placement. Incomplete draft courses remain visible.

Required consistency cases: conflicting radius/arc/chord measurements and tangent/chord orientations remain rejected. Cover 180-degree and major-arc boundaries; explicitly support or refuse full circles and multi-revolution inputs. Test packed DMS versus decimal degrees, tie-ins outside boundary area/closure, annotations without geometric effect, and incomplete curve save/reopen. Unsupported input cannot become a preferred curve branch, an invented bearing or nominal section geometry.

Primary ownership: `mp_verify.comparison`, `mp_verify.diagnostics`, shared curve models/math, review adapters and existing plot/dashboard assets.

## Phase F Centerline corridors

Example request: “Plot this utility easement with 20-foot left and 10-foot right widths, then the taper described here.”

- [x] Define first-class centerline, width interval/taper, side, join and end-cap contracts with provenance and explicit unsupported cases. Easement classification alone is insufficient.
- [x] Preserve interval ordering, start/end left/right widths, step/taper rules, join/cap choices and source references through the Phase B revision and Phase C export contracts. Reject unsupported overlap/precedence rules and missing width coverage explicitly; do not replace endpoint widths with per-course averages.
- [x] Implement deterministic offsets and topology checks using shared line/arc geometry. Keep open-centerline analysis separate from parcel closure. Declare and verify approximation error in linear units with an error budget; a fixed angular sampling step is not sufficient.
- [x] Expose a focused capability only once standalone inputs, outputs, CLI and tests work; compose its outputs into existing plots/maps/exports.

Acceptance: independently verify straight-strip area, reversed traversal with side swapping, curved offsets, tapers, cap behavior, missing widths and self-intersections. Do not silently repair topology or grant canonical parcel verification to an open centerline.

Round-trip acceptance: save → reopen → plot → export retains the full width/taper/cap definition and reproduces geometry within the declared error budget. Each supported cap has its specified effect. Overlapping width rows, missing coverage and self-intersections produce explicit outcomes rather than an apparently normal area; test step/taper boundaries and reversal together.

## Phase G PLSS geometry from supplied reference data

Example request: “Locate NW quarter SE quarter using this supplied section dataset.”

- [x] Define accepted authoritative section/corner inputs, source/date/CRS provenance and supported subdivision rules. Preserve existing metadata-only extraction.
- [x] Require unique section/reference identity, including principal-meridian context where applicable. Record the versioned derivation rule and supported subset; a township/range/section label alone cannot resolve ambiguous references.
- [x] Implement a reference-data adapter and deterministic derivation for the supported subset, reusing existing projection and geographic-display contracts.
- [x] Return unsupported irregular subdivisions or missing controls explicitly; do not substitute a nominal 640-acre section or manufacture survey authority.

Acceptance: known reference corners and independently computed transformations/subdivisions match within declared tolerances. Missing or conflicting evidence cannot produce an apparently established boundary. Derived geometry remains traceable to its reference inputs.

Refusal acceptance: duplicate township/range/section labels, missing corners, government lots and irregular/excess-deficiency cases must resolve from explicit supported evidence or stop. Unsupported cases cannot default to rectangular midpoint division or nominal acreage.

## Evaluation and release gates

Use the existing [evaluation protocol](../../plugins/metesparser/evals/README.md) and case catalog. Native Claude/Cowork acceptance is an outstanding gate carried forward from the earlier plan; local tests and Codex smoke checks cannot satisfy it.

| Gate | Required evidence |
| --- | --- |
| Routing and task scope | Fresh-session document-to-plot, ambiguous/multiple requested tracts, closing subsets with rejected source calls, missing exhibit, comparison, resume and requested-stop cases |
| Native document and client behavior | Exact model/version and client, equivalent baseline/with-skill conditions, transcripts, tool evidence, artifacts and independent scoring |
| Revision and geometry correctness | Source-grounded fixtures; exact invalid-draft recovery; stable identities; interrupted/retried publication; stale/superseded-save rejection; independent expected results and appropriate tolerances |
| Browser and delivery behavior | Save/reopen/reset/navigation, source links, editing operations, immutable export snapshots, transform/layer/raster fidelity, PDF inspection and independently parsed exports |
| Distribution | Rebuilt plugin exercised outside the checkout with its locked runtime and advertised prerequisites |
| Optional live provider | Actual provider/client evidence recorded separately from local map, SDK and browser checks |

Test smaller models for routing, artifact inventory and summaries; evaluate more capable models for ambiguous source reading and selection. Record observed quality, time and cost where available before choosing defaults. Model allocation is an evaluation hypothesis, not an accuracy claim.

For instruction-only changes, validate links, commands and routing behavior. Runtime changes need meaningful affected-package regressions, cross-package import checks and relevant browser/corpus tests. Follow the commands in the [maintenance guide](../CLAUDE_PLUGIN.md#validation), run `make check` for integrated runtime releases, and run `make pre-commit` before an authorized commit. Record passed, failed and not-run gates separately.

## Parallel execution and completion

Use up to three bounded workers plus the parent. Assign a skill/evaluation worker, a contract/engine worker and a UI/export worker only when their interfaces and file ownership are clear. Use smaller models for bounded documentation, inventories and evidence checks; retain independent review for geometry and provenance changes. The parent owns shared CLI/exports, packaging, dependencies and final integration. Workers must preserve concurrent edits and report shared-file changes rather than reverting others' work.

Track implementation outcomes in a linked evidence ledger when work starts. Local implementation is complete only when all applicable implementation, regression, documentation and distribution gates pass; an applicable failed or not-run local gate remains open. Native Claude/Cowork behavior, model evaluations and optional live-provider acceptance each retain separate passed/failed/not-run results. A phase is fully accepted only when its applicable native/provider gates also pass. If native-client access is unavailable, local implementation may be complete while Cowork acceptance remains not run; do not claim full parity or treat startup/authentication failures as observed model behavior.

Hosted accounts, billing, role-based collaboration, proprietary backend reconstruction and automatic boundary correction are outside this plan. The initial deliverable is a reliable local Cowork review workflow with portable artifacts.

Explicitly deferred: KML/KMZ/Shapefile adapters, coordinate-to-call inversion, automatic closing-call suggestions, exact BoundaryLogic manual-language compatibility, Partner API parity and managed batch-service parity. Trace behavior does not establish Partner API support. These exclusions do not defer the bounded multi-tract composition in Phase A or lossless corridor delivery in Phase F.
