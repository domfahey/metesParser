# Source evidence, diagnostics, maps, and composable skill improvements

Date: 2026-10-28

Status: **local implementation and completion-audit fixes passed renewed integration/package/browser/distribution checks; observed paired evaluations and live provider/native-client acceptance remain outstanding**

Current results: [implementation evidence ledger](../implementation/2026-10-28-evidence-review-ledger.md).
Inspected baseline: `c0d6074`, branch `feat/deed-closure-dashboard-skill`

This plan implements the recommendations from the three-agent review of the BoundaryLogic research. It covers source-handoff validation, closure diagnosis, artifact inspection, map controls/evidence summaries, paired evaluations, and a separate description-comparison capability. The parent integrates work; bounded subagents implement and independently review it.

The research is based on public interactions, pictured controls, and vendor claims. It is design input, not evidence of BoundaryLogic's numerical correctness or authenticated-app behavior.

## Contents

- [Scope and existing behavior](#scope-and-existing-behavior)
- [Architecture and shared decisions](#architecture-and-shared-decisions)
- [Subagent execution schedule](#subagent-execution-schedule)
- [A. Validated source handoffs](#a-validated-source-handoffs)
- [B. Closure diagnostics](#b-closure-diagnostics)
- [C. Artifact inspection and resume guidance](#c-artifact-inspection-and-resume-guidance)
- [D. Map controls and evidence summaries](#d-map-controls-and-evidence-summaries)
- [E. Paired behavior evaluations](#e-paired-behavior-evaluations)
- [F. Description comparison](#f-description-comparison)
- [G. Skill integration and distribution](#g-skill-integration-and-distribution)
- [Validation and completion gates](#validation-and-completion-gates)

## Scope and existing behavior

| Recommendation | Delivery | Existing owner |
| --- | --- | --- |
| Validate source handoffs | Versioned models, byte/range/hash validation, standalone validation command | Conversion and extraction skills; `mp-models` / `mp-review` |
| Explain closure problems | Deterministic sensitivity results and source-linked diagnosis presentation | Verification skill; `mp-verify`; dashboard renderer |
| Inspect and resume work | Read-only inventory, dependency validation, actionable restart guidance | Shared CLI; existing workflows |
| Improve maps | Independent scan opacity/order plus explicit fit/checkpoint evidence | Overlay and online-map skills; existing renderer |
| Evaluate actual skill behavior | Materialized fixtures, paired sessions, transcripts and criterion-level scoring | Existing evaluation catalog/protocol |
| Compare descriptions | Independent comparison engine/CLI, then `compare-descriptions` skill | New focused capability, optional dashboard consumer |

Preserve these already implemented behaviors:

- Bidirectional call/plot selection and source-page/quote/crop inspection: `packages/mp-export/src/mp_export/dashboard_assets/dashboard.js`, tested in `tests/browser/test_dashboard_plot_ui.py`.
- Workbench metrics and immutable record versus scenario views: `dashboard_html.py` and `dashboard.js`. Do not rebuild the workbench or add a second source viewer.
- Affine registration, control roles, residuals, and separate fit/checkpoint RMS: `packages/mp-models/src/mp_models/raster.py` and existing raster-preparation code.
- Online layer visibility and registration summaries: `online_map_html.py` and `dashboard_assets/online_map.js`. Extend the current controls.
- Stage hashes, explicit placement, composition validation, and offline/online/MCP separation: the [handoff contract](../../plugins/metesparser/references/artifact-handoffs.md).

Diagnostics implements existing [todo 4](../todos.md); comparison implements todo 5; evaluations extend todo 6. Do not create duplicate backlog entries or mark those items complete when only an initial slice is done.

Interactive curve editing, a placement editor, automatic deed-to-map fitting, new export formats, and a numerical placement-confidence score are outside this plan. These were not recommended as immediate work. In particular, omit a layer-lock control while the viewer cannot move or edit layers. Continue reporting placement uncertainty as unknown when no supported measurement exists.

## Architecture and shared decisions

1. **Keep computation outside skill prose.** Schemas belong in `mp-models`, math in `mp-verify`, filesystem orchestration in `mp-review`, and display in `mp-export`. Skills select operations, preserve task scope, and interpret results.
2. **Retain nine skills until comparison is implemented.** Validation and inspection are utilities used by existing skills. Add `compare-descriptions` only after its standalone engine, CLI, fixtures, and discovery tests work; the resulting catalog has seven capabilities, two workflows, and one alias.
3. **Preserve canonical verification.** None of these operations can change `verify_closure()` results, confidence scoring, source readings, or verified-export eligibility. Reuse the existing fresh verification gate; never use a supplied result or closing scenario as authorization to export.
4. **Keep result namespaces separate.** Source validation reports structural/identity findings; diagnosis reports analysis availability; comparison reports comparability/differences; inspection reports artifact freshness. None means legal correctness or source-reading accuracy.
5. **CLI envelope:** new advisory commands return top-level `needs_review` and exit 1 on a completed advisory result, including a structurally valid source record. Invalid invocation/schema or failure to produce a result returns `error`, exit 2. Detailed operation outcomes live below the top level. Existing commands and their exit behavior remain unchanged. Document expected exit 1 in tests and shell examples.
6. **Compatibility:** use source-handoff schema `1.1`, since the current prose already shows informal `1.0` records. Read legacy records as legacy/unverifiable; provide an explicit migration recipe without inventing missing facts. Keep existing direct text/CSV/JSON entrypoints working without acquisition records. New diagnostic/comparison request/result schemas start at `1.0`.
7. **Reuse narrow modules.** Add thin `src/metesparser/` facades for new public capabilities where consistent with existing `relative.py` / `plot.py`; do not duplicate math. Protect package/root import parity with regressions.
8. **Retain exact inputs and fresh outputs.** New commands that produce files use a new directory, keep input bytes and hashes, and record algorithm/schema versions. Inspection and validation do not mutate their input folders. A view-only change affects presentation, not source or geometry identity.

Proposed public entrypoints, to be frozen with example request/result fixtures before workers code:

```text
metes-review validate-source BUNDLE_DIR [--acquisition FILE] [--selection FILE]
metes-review diagnose-closure REQUEST.json --output-dir NEW_DIR
metes-review inspect-artifacts BUNDLE_DIR --requested-stage STAGE
metes-review compare-descriptions REQUEST.json --output-dir NEW_DIR
```

`STAGE` is one of `convert`, `extract`, `verify`, `review`, `plot`, `dashboard`, `render-map`, or `compare-descriptions`. CLI handlers support the existing `--settings` behavior; read-only operations must not create the configured output directory. Filenames above are proposed interfaces, not commands available at the inspected baseline.

## Subagent execution schedule

Use at most **three workers plus the parent** concurrently. Each worker receives exact files, immutable interface fixtures, and this instruction: **You are not alone in the codebase. Do not revert others' changes; accommodate concurrent work and report shared-file integration needs to the parent.**

| Wave | Worker 1 | Worker 2 | Worker 3 | Parent responsibility |
| --- | --- | --- | --- | --- |
| 0 | Source contract/fixture proposal | Diagnostic/comparison fixture proposal | Evaluation fixtures and map fixture proposal | Freeze interfaces, verify baseline and ownership, establish expected independent results |
| 1 | A: source models and validator | B1: diagnosis models and engine | E1: fixture materializer and run-record validation | Shared CLI/public exports; review numerical and provenance decisions |
| 2 | C: artifact inspector, after A | B2: dashboard diagnosis adapter/UI, after B1 | D: map controls/evidence | Integrate APIs; run cross-package checks; keep renderer ownership separate |
| 3 | F1: explicit comparison and grouped segments | G: completed-feature skill/reference updates | E2: evaluate completed A–D workflows | Comparison CLI/facades and independent geometry review |
| 4 | F2: structural version comparison and dashboard adapter | Independent F1/F2 geometry review as slices land | Prepare comparison evaluation inputs/rubrics | Integrate comparison; freeze its supported behavior |
| 5 | G: comparison skill and release docs, after F2 | E2: comparison/discovery sessions, after the skill is packaged | Independent evidence/acceptance review | Distribution smoke, full integration, acceptance ledger |

Run independent reviews as workers finish, reusing freed slots. Never have the same agent be the only reviewer of its numerical algorithm or its evaluation scores.

Model allocation: use a smaller model such as GPT-6-luna for fixture inventory, bounded docs, link checks, and run-record validation. Use a capable coding model such as GPT-6.1-sol for implementation, and a stronger reasoning setting for geometry, dependency validation, and independent review. Record actual models used; a suggested assignment is not a completed model evaluation.

The parent exclusively owns shared integration files: `mp_review/cli.py`, package `__init__.py` exports, `plugins/metesparser/scripts/run-review.py`, root facades/import tests, build metadata, dependency/lock changes, top-level docs, and release coordination. Workers may propose patches for these files but do not edit them concurrently. If a worker needs another worker's file, negotiate ownership before editing.

## A. Validated source handoffs

**Worker ownership:** new `packages/mp-models/src/mp_models/source_handoff.py`, `packages/mp-review/src/mp_review/source_handoff.py`, and corresponding package tests. Parent wires `validate-source`; docs worker updates the existing source-preparation reference after the contracts settle.

### Contract and behavior

- `SourceAcquisitionRecord`: schema version, stable source IDs, local file references or opaque attachment IDs, optional known hashes/model identifier, actual reading request/instructions/method, transcript reference/hash, page map, supplied/read/unreadable/missing page declarations, and uncertainties.
- `DescriptionSelectionRecord`: acquisition/transcript identity, separate candidate IDs, selected text file/hash, source ranges, exact opening/closing wording, rationale, unresolved references, and carried uncertainty IDs. Do not merge historical and operative candidates.
- Local references resolve under an explicit bundle root, never process cwd. Reject absolute paths inside records, traversal, and symlink escapes; for v1.1, reject symlink components below the resolved root. Opaque attachment IDs are identifiers, never executable paths or URLs to fetch.
- Bind selected text to the exact bytes of the declared transcript file, identified by its acquisition-record hash; offsets never address PDF bytes. Use documented zero-based, half-open UTF-8 byte offsets with valid character boundaries, plus page/line references for display. Reject invalid UTF-8; hash raw bytes and preserve any BOM, CRLF, and other whitespace without normalization. Noncontiguous selections retain separate ordered spans and explicitly declared separators. Validate the reconstructed selected bytes.
- Check declared page ranges against available transcript lines and page IDs. Unknown page count remains unknown; absence of an original file or unreadable page cannot become a completeness claim.
- Report structural validity, identity checks, and source uncertainties as separate nested outcomes. Distinguish malformed records, changed bytes, missing files, and unavailable identity. A null hash or unavailable attachment means identity is unverifiable, not a match. A structurally valid record may explicitly declare an unreadable page; preserve that uncertainty without turning it into either a schema error or an accuracy claim.
- Validate standalone acquisition or selection records when possible, with precise missing-prerequisite findings. Existing isolated-text and structured-call routes remain independent of these records.

**RED fixtures:** valid multi-page and noncontiguous selections; multibyte character boundaries, BOM, CRLF, invalid UTF-8, and exact whitespace; duplicate/dangling IDs; out-of-bounds spans; unrecorded separators; mismatched source/transcript/selected-text hashes; missing original; attachment-only input; null hashes; valid structure with declared unreadable pages; legacy v1.0; unknown versions; unsafe paths; uncertainty references dropped during selection.

**GREEN:** implement the smallest schema/validator satisfying those behaviors. Tests assert both machine-readable codes and affected IDs/paths, not exact prose. A valid structure must never emit an accuracy attestation. Migration writes a separate record only when explicitly requested and leaves unavailable evidence null.

**Completion:** `validate-source` works from an extracted plugin outside the checkout; direct `review`, `verify`, and `plot` remain compatible; no source file is modified.

## B. Closure diagnostics

**B1 worker ownership:** new `mp_models/diagnostics.py`, `mp_verify/diagnostics.py`, and their unit tests. Proposed public API: `diagnose_closure(request) -> ClosureDiagnostics`. Parent adds `mp_review/diagnostics.py` orchestration, CLI and facade.

**B2 worker ownership:** diagnosis integration in `packages/mp-verify/src/mp_verify/dashboard.py`, `packages/mp-review/src/mp_review/dashboard.py`, `mp_export/dashboard_html.py`, `dashboard_assets/dashboard.js` / `dashboard.css`, and affected renderer/browser tests. Coordinate any shared dashboard-model extension with the parent.

### Computation and limits

Compute the endpoint residual from the request's immutable calls using supported deterministic traversal; never trust a caller-supplied residual or reuse stale scenario geometry. Every result retains request/input identity, call IDs, any supplied source references, analysis frame, units, algorithm version, and limitations.

For a straight course with distance `d` and azimuth `theta` clockwise from north:

```text
delta E = d sin(theta)                delta N = d cos(theta)
dR/dd = (sin(theta), cos(theta))      units: ft/ft
dR/dtheta = (d cos(theta), -d sin(theta))  units: ft/radian
```

Convert explicitly for displayed angular units such as feet per arcsecond. Validate derivatives against independently calculated finite differences and hand-computed examples. Use finite-number checks and accurate summation.

- First release supports complete canonical straight boundaries. Exclude explicitly marked commencement tie-ins using existing semantics and report that exclusion. Curves, unresolved azimuths, meanders, and mixed exception boundaries produce explicit unsupported/incomplete results until separately supported; never skip an unknown course to manufacture a total residual.
- Keep distance and angle sensitivity separate; do not compare their raw values as though they have the same units. Candidate ordering may use a documented projection onto residual direction within each category. Equal evidence stays tied, including opposing east/west distance candidates.
- Unit sensitivity is not a proposed correction or an error probability. At zero residual, residual-direction ranking is unavailable; do not divide by zero or create a diagnosis.
- Quantization bounds require explicit source precision and a declared rounding assumption. Decimal formatting alone does not establish a statistical bound. Report these bounds separately from the existing confidence heuristic.
- Record alternative digit readings as explicit scenarios with source evidence. Do not select one because it reduces closure, insert a closing course, or mutate the canonical call set.

The CLI writes exact request bytes, `diagnostics.json`, and a versioned manifest. The dashboard consumes freshly validated results tied to the current calculation hash. Candidate actions reuse existing source selection/page/crop handlers. Baseline diagnosis remains separate from scenario diagnosis, with reset restoring the baseline; old caches safely miss after calculator/renderer version changes.

**RED tests:** a 100-ft rectangle with one 0.5-ft excess eastward leg identifies both east/west distance candidates without naming a culprit; north/south and rotated variants behave consistently; derivative/finite-difference agreement; zero residual; missing bearing; unsupported curve; tie-in exclusion; uncertainty and source-link preservation; no mutation or export promotion; scenario/reset source selection opens the correct occurrence.

**Completion:** standalone and dashboard results agree for the same request; supported math passes independent review; unsupported cases are visible; original findings, calls, placement, and export eligibility remain unchanged.

## C. Artifact inspection and resume guidance

**Worker ownership:** new `mp_models/artifact_inspection.py`, `mp_review/artifact_inspect.py`, corresponding unit tests and fixture manifests. Parent owns CLI/public exports and any small hooks required in existing producers.

Use a small set of adapters over existing artifacts, not a new workflow executor. Require an explicit directory as the bundle root; a file argument is an invocation error. Resolve that root once, discover known root filenames and recognized manifests in immediate child directories, then follow only declared references confined to the root. Reject symlink components below the root; do not recursively scan arbitrary folders or adopt sibling bundles. Recognize source records, review results, plots, prepared maps, placements, dashboards, diagnostics, and comparisons as their workstreams land.

Each stage reports `present_valid`, `missing`, `stale`, `invalid`, `unverifiable`, `blocked`, or `not_requested`, with reasons and dependency IDs. These states describe artifact usability, not engine verification outcomes. Preserve any recorded canonical status as a separately attributed field.

### Dependency rules

| Change | Invalidated descendants |
| --- | --- |
| Original source or transcript | Dependent acquisition/selection, review, plot, diagnostics, comparison, placement, rendering |
| Selected calls | Review/plot, diagnosis/comparison, geometry-bound placement, rendering |
| Map bytes, CRS, controls, registration | Dependent map preparation, placement/comparison, map rendering |
| Opacity, layer order, viewport | Presentation only |

Use conditional edges: supplied calls can go straight to verification or plotting; isolated prose can go to review/plot; document workflows use acquisition and selection; optional maps are outside a closure-only request. Dashboard composition and online rendering remain distinct destinations.

- Establish edges from actual declared source IDs/hashes and validated manifests. Matching filenames or timestamps do not establish lineage. If identical bytes could refer to several occurrences, report ambiguity instead of choosing the newest folder.
- Reuse existing input/provenance validators; do not treat a self-consistent hash of fabricated derived data as proof of a reusable result. Recompute through an existing pure validator where required, without rewriting artifacts or promoting status.
- For plots/maps/dashboards, use their existing identity and pure validation checks. For review artifacts, an input hash in `audit.json` alone does not validate saved calls or verification. Replay retained source bytes in memory using the recorded original input kind, options such as stated area, and compatible deterministic algorithm version; compare semantic calls/verification with saved outputs. Never infer the original kind from the retained `source.txt` filename. Reuse or extract a pure input dispatcher with output disabled, so replay never writes files or invokes verified export. Add a small producer manifest for new reviews recording these replay parameters and versions; missing legacy parameters or incompatible versions produce `unverifiable` or `stale`, as appropriate. Report stored canonical status separately from inspector findings.
- Legacy manifests, unavailable original documents, and null identities retain explicit limitations. Report individually usable artifacts while declining to certify an unproven full chain.
- Return the earliest invalid stage and required inputs for the **requested destination**. Emit structured command arguments only when unambiguous, never auto-run them. Existing-output paths must not be suggested as new output destinations.

**RED tests:** unchanged source-to-review chain; source/transcript/call changes; map-only change; presentation-only change; absent optional maps; direct-call route without acquisition; ambiguous multiple occurrences; legacy/bad hashes; tampered audit/calls/verification; stale algorithm version; absent replay parameters; CSV/JSON retained under `source.txt`; explicit nested bundle root; file input and outside-root/symlink references rejected; unknown version; no writes/network/provider calls; recommendations do not execute or create directories.

**Completion:** users can identify what to reuse and where to resume without rereading or rerunning unrelated stages. The inspector makes no source-accuracy or canonical-pass claim.

## D. Map controls and evidence summaries

**Worker ownership:** `packages/mp-export/src/mp_export/online_map_html.py`, `dashboard_assets/online_map.js`, `online_map.css`, HTML tests, and `packages/mp-export/tests/browser/test_online_map_ui.py`. Existing standalone-map UI coverage must also pass.

### UI behavior

- Replace the one global scan-opacity control with one labeled slider per raster layer. Keep `WebMapRequest.raster_opacity` as the backward-compatible initial value; no model version change is needed for ephemeral controls.
- Add accessible up/down controls for ordering raster scans among themselves. Basemap stays below scans; vector context, courses, POB, closure, and selection retain their existing semantic ordering above scans. Disable unavailable moves at the ends.
- Preserve each raster's opacity, order, and visibility across style reloads. Reapply them by stable raster ID after provider layers are recreated.
- Keep UI state in the viewer session. Do not write it into input bytes, geometry hashes, registration controls, placement, or verification results. Page reload may restore documented defaults; cross-session persistence is not required.
- Expand existing evidence summaries with fit/checkpoint counts, respective RMS values and units, source provenance, scene/bearing-basis information where available, and placement status. Zero checkpoints must explicitly mean independent checkpoint accuracy is unknown. A small fitting residual is not an accuracy estimate.
- Show existing `unplaced` / `approximate` / `referenced` meaning without inventing numeric uncertainty or converting an approximate placement into a referenced one.

**RED fixture:** two visibly different synthetic scans, a parcel polygon, and deed courses with stable IDs. Assert one opacity slider affects only its raster; reordering changes raster stacking; vectors remain readable above scans; toggles and state survive style reload; metadata and bytes remain identical; malicious/long labels are escaped; keyboard controls work. Test zero checkpoints, good fit/poor checkpoints, and unavailable placement evidence separately.

**GREEN:** extend existing Mapbox adapter calls and evidence markup. Test local state wiring separately from a live provider pixel check. Do not add a placement editor, layer lock, auto-fit, or remote request to prepare this UI.

**Completion:** `make test-mapbox-browser` passes with the new fixtures; a live-provider check has a separately recorded outcome. Update the overlay/map skills to summarize these existing evidence fields and point users to the new controls.

## E. Paired behavior evaluations

**Worker ownership:** `plugins/metesparser/evals/`, new `scripts/skill_evals.py`, and `tests/unit/test_skill_evals.py`. Reuse the [existing protocol](../../plugins/metesparser/evals/README.md); do not create a competing case catalog.

### E1: executable preparation and evidence checks

Build a lightweight helper with `materialize`, `validate-run`, and `summarize` operations. It prepares synthetic input files, hashes artifacts, validates run records/transcript references and criterion coverage, and summarizes observed results. It must not claim to judge transcription truth automatically or silently launch paid/provider sessions. Reuse `mp_review.corpus` for deterministic assertions where suitable.

Keep candidate input packages separate from evaluator-only rubrics. Baseline packages contain the request, artifacts, and identical tools but no skills or repo access that leaks the plugin/rubric. With-skill sessions expose the actual packaged metadata and resources without telling the agent which skill to choose. If that isolation cannot be established in a client, mark the run non-equivalent rather than calling it paired evidence.

Run records retain exact model/version and client, condition, input/skill hashes, available tools, complete transcript reference/hash, artifact paths, criterion-level evidence, and `pass` / `fail` / `not_run` outcomes. Prevent missing transcripts, missing criteria, or unrun required actions from yielding a pass. Report per-case/model/client results and regressions; do not aggregate unlike environments into an improvement score.

### Required fixture matrix

| Case family | Required observation |
| --- | --- |
| Source reading | Actual synthetic PDF/image pages with obscured digits, missing/repeated exhibits, and distinct occurrences; uncertainties remain explicit |
| Selection only | Verbatim selected spans and all exclusions retained; stops before calculation |
| Reuse/restart | Unchanged artifacts reused; changed transcript restarts affected stages only |
| Closure diagnosis | Opposing candidate explanations preserved; no source correction chosen from closure |
| Map presentation routing | Correct map artifacts and control guidance; no invented interaction or artifact mutation |
| Optional paired map interaction | With identical browser tools in both conditions, two raster controls and order/visibility changes work and preserve evidence |
| Map evidence | Poor/absent checkpoints are disclosed despite low fitting RMS |
| Comparison | Reversed lines agree within declared comparison tolerance; incompatible basis stays uncomparable; structural suggestions remain tentative |
| End-to-end review | Source occurrence, source uncertainty, calculations, scenario/reset, and requested output remain correctly linked |

### E2: observed sessions

Run the smallest available model first to validate fixture usability, then independent baseline/with-skill pairs. Repeat in native Claude Haiku, Sonnet, and Opus when available, recording exact versions; keep Codex and Claude lanes separate. Use fresh sessions and randomize condition order where practical. A blinded second source reader must not see first-reader values or closure results when evaluating disputed figures.

Separate deterministic engine/browser tests, model routing/behavior, native document reading, live Mapbox provider behavior, and native-client visible display. Missing credentials, clients, tools, or UI control are `not_run` gates with reasons. A mocked Mapbox tool cannot pass live acceptance. Keep real matter documents and sensitive transcripts outside the repository; committed fixtures must be synthetic or sanitized and approved.

The plugin alone does not supply browser control. Ordinary model map cases assess routing, output artifacts, and truthful instructions about available controls; they must not require a model to manipulate the viewer. Workstream D owns actual control behavior tests. An optional paired UI case requires the same explicit browser tool and viewer access in both sessions, with tool schemas and observed actions retained. Without those tools, mark that UI case `not_run`; do not fail a successful ordinary routing case or claim the UI action occurred.

**RED tests for the helper:** missing/wrong transcript hash, rubric leakage into candidate bundle, absent criterion, stale input hash, contradictory overall pass, unrun required native/UI action, and incorrect model/condition pairing. **GREEN:** validate observable evidence and render an honest ledger, without adding an LLM judging framework.

**Completion:** the helper and matrix are executable; actual paired results and limitations are recorded. Do not mark full native acceptance or todo 6 complete while its required client/document gates remain unrun.

## F. Description comparison

**Worker ownership:** new `mp_models/comparison.py`, `mp_verify/comparison.py`, their tests, and `mp_review/comparison.py`. Parent wires `compare-descriptions`, public exports, facade, and packaging. A later UI worker adds a comparison section using existing dashboard source-selection components after diagnosis UI work is merged.

Proposed API: `compare_descriptions(request) -> DescriptionComparison`. Requests identify two immutable description/call sets, stable IDs/source refs, units and bearing bases, and explicit comparison pairs/groups. Direct structured inputs are sufficient; neither a dashboard nor document reading is required. Do not change `checks.compare_double_entry()` or its positional same-traverse behavior.

### F1: explicit line and grouped-course comparison

- Compare selected straight lines with explicit traversal direction, including reversal. Report length, bearing, and displacement differences with units and provenance.
- Require a declared compatible bearing basis and unit definition for directional comparison. Unknown basis must not become common merely because both inputs use the same display label. A sourced rigid transform may establish alignment; no automatic translation/rotation, snapping, or scale fitting.
- Length/direction agreement does not prove the same physical/legal boundary. Positional coincidence additionally requires a validated common scene and placements; report positional comparison as unavailable otherwise.
- Accept explicit one-to-many/many-to-one groups for split/merged courses. Verify collinearity, direction, ordering/connectivity, aggregate displacement and lengths; preserve every contributing source ID. Do not accept a curved path merely because its chord agrees.
- Comparison tolerances are explicit request values with recorded units; they are comparison criteria only and cannot change canonical verification tolerances.
- Preserve structural results even when geometric comparison is `not_comparable`. Report per-component outcomes and reasons; unsupported curves/relative-only geometry remain explicit, not straightened or reoriented silently.

**RED tests:** identical and reversed line; 0.45-ft discrepancy; bearing wrap at 0/360; tolerance boundary; incompatible/unknown basis; different foot definitions; explicit sourced transform; no placement but valid vector comparison; invalid/dangling/duplicate pair IDs; exact and reversed one-to-many split agreement; noncollinear, disconnected/noncontiguous, wrongly ordered/directed groups; aggregate length mismatch and vector cancellation despite matching endpoints; source mutation; `compare_double_entry()` regressions. Include an unknown-basis fixture that retains structural differences while returning vector `not_comparable` and positional `unavailable`, each with a reason.

### F2: structural version differences and optional display

Compare sequence content to identify changed distances/bearings/monuments, unmatched calls, reordered sections, and split/merge candidates. Exact matches may be anchors; ambiguous repeated patterns remain multiple tentative correspondences. Use documented, deterministic matching rules and report why each candidate was proposed. Do not turn an unmatched item into a definitive omission or a tentative pair into an established adjoining boundary.

Keep source quotes unchanged and numerical normalization separate. A structural diff can operate when geographic basis is unknown, but must not produce a geometric-agreement claim. Any sequence-alignment cost/tie-break rules require fixtures and documented rationale, not unexplained constants.

The CLI writes exact request bytes, `comparison.json`, and a versioned manifest. The optional dashboard adapter validates identities and renders changed calls/explicit pairs with source links. Adding comparison output must not alter original findings or status. Add `compare-descriptions` as a focused skill only now, with direct structured-input examples and routing back to selection when two intended descriptions have not been identified.

**RED tests:** inserted/deleted call; reordered sequence; duplicate/ambiguous motifs; one-to-many split suggestion; changed monument wording retained verbatim; unresolved bearing basis still permits textual differences; source links point to the right version/occurrence; comparison reset/display preserves both records.

**Completion:** F1 and F2 both pass before todo 5 is considered complete within the documented supported scope. Automatic boundary establishment and unsupported curve comparison remain explicitly out of scope, rather than being silently treated as matches.

## G. Skill integration and distribution

The documentation worker updates only capabilities that have landed. Keep entrypoints short and reference authoritative schemas/helpers; do not paste algorithms or the entire research document into skills.

- Conversion/extraction: create v1.1 records, run validation when handing them off, preserve unresolved facts, and return the requested stage only.
- Verification: offer/run diagnosis when requested or needed to explain a failed check, preserving its advisory meaning; link the deterministic command/reference.
- Review/dashboard: reuse valid handoffs; use inspection when reuse/invalidation is unclear, not as a mandatory step for every simple request.
- Overlay/map: summarize actual fit/checkpoint evidence, source/frame/placement status, and per-raster presentation controls. Local viewer and vector-only MCP capabilities remain distinct.
- Comparison: a new precise description, request/output example, limitations, and standalone usage after F completes.
- Shared references/catalog: update composition, invalidation, status meanings, versions, packaging instructions and changelog once. Retain `review-deed` as an alias. Do not rename existing skills or split their ownership unnecessarily.

Behavioral routing tests must cover direct calls, isolated text, document selection, standalone map, and two-description comparison. Avoid tests that merely assert headings or duplicate implementation strings. Validate all local links and release metadata, then exercise the extracted plugin in a directory outside the checkout.

## Validation and completion gates

For every production slice: **RED** behavior regression with independent expected values → **GREEN** minimal implementation and affected suite → **REFACTOR** within ownership → independent review. Import failures may establish an initial RED, but follow with behavioral assertions that fail against an incomplete implementation. Do not alter expected numerical results to match code.

Record task ID, worker/model, exact red command/failure, green command/result, reviewed commit or diff identity, produced artifacts/hashes, and unrun gates in a separate implementation evidence file when work begins. This plan is not test evidence.

Use targeted package tests during implementation, for example:

```sh
uv run pytest packages/mp-models/tests/ packages/mp-verify/tests/ packages/mp-review/tests/ packages/mp-export/tests/ plugins/metesparser/tests/ --no-cov --import-mode=importlib
uv run pytest tests/unit/test_cross_package_imports.py tests/unit/test_plugin_build.py --no-cov
make test-dashboard-browser
make test-mapbox-browser
make check
```

Before a requested commit, run `make pre-commit` as required by the repository and inspect the resulting diff. Broaden/repeat tests only for new changes, failures, or unresolved risks. Do not run `make ci` blindly over dirty work: its `clean` prerequisite requires reviewing affected paths first.

Build both plugin variants with separate outputs and test the extracted locked runtime:

```sh
uv run python scripts/build_claude_plugin.py --output dist/metesparser-evidence-plugin.zip
uv run python scripts/build_claude_plugin.py --with-web-map --output dist/metesparser-evidence-web-map-plugin.zip
```

Smoke-test all new commands plus existing direct review/plot, relative analysis, composition, and map handoff routes outside the repository. Account explicitly for successful advisory exit 1. Check runtime resources, exact input retention, source hashes, new-directory behavior, legacy input compatibility, and absence of verified exports from advisory operations.

| Gate | Completion evidence |
| --- | --- |
| Source contracts | A fixtures, CLI validation, compatibility and no-mutation checks |
| Diagnostics | Independent numerical review, standalone/dashboard agreement, source links and scenario isolation |
| Inspection | Correct conditional invalidation/restart decisions, truthful legacy/missing evidence, no writes |
| Map UI | Local browser controls and evidence semantics, immutable input and placement |
| Comparison | Explicit/groups plus structural-version cases, tentative/established distinction, independent skill use |
| Skills | Correct discovery/stopping points and maintained shared references |
| Distribution | Both extracted runtimes, new and existing commands, facade/import compatibility |
| Model evaluations | Actual paired transcripts and criterion scores, separated by exact model/client |
| Live Mapbox / native clients | Separately observed provider and visible-client outcomes; unavailable gates remain `not_run` |

Code implementation may be reported as locally complete when local gates pass, while external acceptance remains explicitly outstanding. Do not report the entire evaluation recommendation complete until its required observed runs exist. Preserve unrelated working-tree changes; do not commit or push without the user's instruction.
