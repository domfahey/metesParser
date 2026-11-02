# BoundaryLogic Cowork plan audit

Date: 2026-10-28

Status: **audit complete; A01–A10 incorporated into the revised implementation plan**. These specification gaps are addressed; implementation and behavioral acceptance remain planned work.

## Verdict

The [workflow plan](2026-10-28-boundarylogic-cowork-workflow-plan.md) has the right architecture and scope. It correctly reuses implemented capabilities, keeps numerical work outside skill prose, separates source corrections from hypothetical scenarios, and retains native-client acceptance as an outstanding gate.

The audited version needed more specific failure contracts, especially for saved revisions and exports. Its broad invariants covered many research findings, but several phase acceptance criteria did not exercise the failure that motivated the invariant. All ten amendments are now incorporated in the plan; their priorities apply before the affected phase is released, not as a demand to implement every later phase immediately. The findings below retain the original assessment and proposed remedies for traceability; their line numbers refer to the pre-amendment plan hash, not the revised file. See the [amendment disposition](#amendment-disposition) for current locations.

No finding below establishes a current MetesParser defect or a newly reproduced BoundaryLogic runtime defect. The findings concern specification gaps. No new vendor session, backend test or REA producer run was needed to audit the retained evidence.

## Evidence and audit boundary

The audit used the research reconstruction, its retained workflow/product/static reviews, the saved REA result, the current plan and targeted current-code contracts. Three smaller-model reviewers independently covered geometry, persistence/intake, and exports/placement; the parent reconciled findings and checked evidence integrity.

Fresh integrity checks passed:

- All **32** artifacts listed in the retained research manifest match their recorded SHA-256 values.
- All **131** static source ranges across six ledgers match their character/UTF-8 byte slices, range hashes and starting line numbers in the captured bundle.
- The **61,022-byte** kernel excerpt matches its recorded source slice and hash.

Audited identities:

| Artifact | Identity |
| --- | --- |
| Plan before audit | SHA-256 `24ccde3c0d52918b89b8cf23024f3852f7345d302a4c72a3705e00c20e85f404` |
| Plan after amendments | SHA-256 `c0b13a6bd2893d20aab815fd3aa63ec74b8af92c41edb6b967be17998c015998` |
| Captured client bundle | SHA-256 `6444f1580504329b1a86c6e1ffbb53884a8f52e6a336481d68a4c95d4a5440e0` |
| Selected kernel excerpt | SHA-256 `58b11465f224e3bb7f8aa8fc8ba5f6aaef7a70bef18bda352f24a3f4015af3c3` |
| REA parent evidence | `ev_8c6e4f5bb43e4b5f4b4446f8612ee6771680d8a2f4513f6f591bcdf2f42704dd` |

REA parsed one selected JavaScript file with zero parse failures and 21,601 AST nodes. Application coverage is partial; semantic coverage is unknown, with 4,965 semantic unknowns. Summary `complete-within-view` does not mean complete application recovery. Static observations and source-derived candidates cannot establish save failures, exported-file behavior or server calculations in production.

The raw corpus, the REA files and the research reconstruction cited below are kept outside the repository and are not linked. Hash integrity establishes artifact identity, not semantic correctness.

## Original findings and required amendments

### A01 P1 Durable revisions need a recoverability and publication contract

**Affected:** Phase B, with dependencies in C and E; plan lines 74–79.

Stable call IDs and new output directories do not define what happens when a save is pending, rejected, superseded or interrupted. Phase B also leaves ambiguous whether an invalid draft can be saved or only a validated scenario payload. Multi-tract publication lacks explicit tract identity and partial-write semantics.

The captured BoundaryLogic callback skips writes for errorful matched blocks, matches blocks heuristically by calls/name/ordinal position, performs separate writes/deletions, and catches failures internally. Export waits at most 2.5 seconds before navigation. These are static observations; stale exports, orphan records and data loss remain runtime candidates. See persistence analysis, S05/S07/S08 and C01–C03, and the reconstruction's persistence section.

Recommended amendment:

- Distinguish exact draft input, parsed revision, last-valid geometry and committed revision. Preserve invalid text, errors and identities; a saved draft must not imply updated geometry. If B supports only validated scenarios, state that boundary and assign recoverable raw drafts explicitly to E.
- Use stable document/tract/occurrence identities as well as call IDs. Missing or unparseable input is not a delete instruction.
- Publish a revision manifest only after every required artifact succeeds. Incomplete publication remains detectable and retryable; retries cannot duplicate tracts or overwrite a later revision.
- Export only an explicitly committed revision. Preserve pending edits across navigation, or offer retry/discard. Selecting an older revision must be explicit and labeled.

Acceptance: delay a save beyond 2.5 seconds, reject it, edit while saving, switch documents, interrupt the second tract write, retry removal and reorder identically named tracts. Reopen must preserve the intended draft and prior committed revision without silent reassignment or omission. This is a local artifact protocol, not a new database service.

### A02 P1 Export scope needs one immutable snapshot and explicit format semantics

**Affected:** Phase C; plan lines 89–94.

Selecting a revision and layer set is necessary but leaves transform policy, raster inclusion, opacity, label/table fidelity and unavailable metrics underspecified. All package components need the same immutable input snapshot.

The captured client uses different export paths, separate screenshot and summary inputs, a visual/PDF rotation notice, Sheet image exclusions and zero defaults for unavailable summary metrics. These motivate tests; actual server files and the suspected preview/output discrepancies remain unobserved. See export analysis, F01/F02/F03/F08/F15/F21.

Recommended amendment:

- Freeze source/call revision, placement identity/status, layer membership/order, labels and presentation choices in a single export snapshot. Generate the drawing, table, metrics and manifest from that snapshot.
- Select record-local or placed coordinates explicitly. Declare CRS, exact foot definition, rotation convention/pivot and display rotation policy; retain source bearings separately.
- Declare vector/raster/label support for each format and report omissions. Distinguish opacity from export exclusion; zero opacity must not silently delete geometry.
- Keep unavailable metrics null/unavailable with a reason, never a fabricated zero. If generation fails, no partial package may appear complete.

Acceptance: export an asymmetric line/arc parcel with a placement and display rotation, raster background, hidden layer/group and zero-opacity vector. Independently compare requested scope with SVG/PDF, CAD/GIS geometry, call tables and manifests. Repeat after a placement change and interrupted generation. Record raster handling explicitly, including rejection where a format does not support it.

### A03 P1 Source completeness needs the decisive negative fixtures

**Affected:** Phase A and the release gates; plan lines 31 and 59–64.

The invariant already says to account for every source course, but the acceptance criteria do not test a rejected course whose surviving subset closes. That is one of the strongest research lessons.

The vendor documents unplottable calls being omitted while the remaining geometry can report Closed; static parser/closure flow supports that separation. Its comma/aliquot fallback also admits some ordinary lot prose. See parser analysis, E01/E02/E04/E08/E12, and unplottable-call documentation.

Recommended amendment: expose source-linked accounting for parsed boundary, tie/reference, intentionally excluded and unresolved/rejected material, with reasons and actual page/span identities. Unknown coverage stays unknown; do not invent a total source-call count.

Acceptance: use an unreadable middle course surrounded by cancelling valid courses, duplicate/missing courses, an exception after the POB, a missing continuation and comma-separated lot/block prose. Show affected source material and geometric limitations even when the accepted subset closes. Reuse existing source/audit contracts.

### A04 P1 Curve extensions must preserve existing consistency rejection

**Affected:** Phase E and curve exports; plan lines 118–122.

Sensitivity checks and partial-curve fixtures do not explicitly preserve the current rejection of contradictory redundant measurements or orientations.

BoundaryLogic's inspected solver chooses precedence branches and can ignore contradictory extra inputs; these are static facts about the selected solver. MetesParser already validates redundant evidence in [plot geometry preparation](../../packages/mp-verify/src/mp_verify/plot.py). See curve analysis, C03/C04.

Recommended amendment: diagnosis, comparison, editing and export must reuse the current consistency/orientation checks. Define independent parameters for sensitivity calculations rather than perturbing constrained inputs inconsistently.

Acceptance: contradictory radius/arc/chord values and tangent/chord orientations remain rejected. Cover 180-degree and major-arc boundaries; explicitly define support or refusal for full circles and multi-revolution inputs. Keep unsupported cases visible instead of coercing them into a preferred branch. This preserves an existing feature rather than adding a duplicate validator.

### A05 P1 Corridor semantics must survive saving and export

**Affected:** Phases B/C/F; plan lines 130–134.

Phase F defines widths, tapers and caps, but does not require their lossless passage through the earlier revision and export contracts.

The captured adapter serializes per-course average side widths; its local corridor path samples curves and does not distinguish the accepted end modes in construction. Backend reconstruction from raw text remains unknown. See curve/corridor analysis, C09/C10/C17.

Recommended amendment: retain interval order, start/end left/right widths, step/taper rules, joins, caps and source references through save → reopen → plot → export. Specify overlapping width-row handling and explicit missing-width outcomes. Declare approximation error in linear units; a fixed angular step alone is insufficient.

Acceptance: reconstructed geometry agrees within the declared error budget, reversal swaps sides consistently, each supported cap has its defined effect, and overlapping/missing widths and self-intersections cannot silently produce a normal area result.

### A06 P2 Separate deed placement authoring from raster registration

**Affected:** Phase D; plan lines 102–108.

The phase promises both placement and registration, while its tasks only explain raster controls. A registered image does not supply the deed's location or orientation.

The existing [plot/overlay contract](../../plugins/metesparser/skills/deed-closure-dashboard/references/plot-and-overlays.md) and [standalone map limits](../../plugins/metesparser/skills/render-online-map/references/local-viewer.md) already distinguish these operations. The research likewise separates image alignment from description placement.

Recommended amendment: separately collect deed position/orientation evidence and author a translation/rotation placement bound to fresh deed geometry and the selected scene. Reuse the existing permitted transform contract. Preserve approximate/unplaced status when support is insufficient; do not grant standalone referenced status merely because raster checkpoints pass.

Acceptance: a registered raster with no deed control leaves the deed unplaced. Changing deed geometry invalidates the deed placement independently of unchanged raster registration.

### A07 P2 Define manual input semantics without promising DSL compatibility

**Affected:** Phase E; plan lines 118–122.

Structured forms are an appropriate scope choice, but the plan needs an explicit supported-input matrix to avoid ambiguous angle, unit and course-role interpretation.

The documented manual language distinguishes packed DMS from decimal degrees, relative angles, POC/POB ties, reference/omitted calls and derived closing courses. The manual and AI/API paths have different support. See syntax reference and the reconstruction's interpretation paths.

Recommended amendment: declare angle representation, units, explicit/inherited orientation and supported course roles. Route supported relative inputs through the existing relative-analysis contract. Unsupported forms remain source evidence. A derived closing course, if offered, remains a scenario rather than a source correction.

Acceptance: `45.3020` cannot silently switch meanings; commencement ties stay outside boundary area/closure; annotations do not create coordinates; unsupported syntax cannot become nominal geometry. Exact BoundaryLogic text-language compatibility remains deferred.

### A08 P2 Support an explicit request to review multiple tracts

**Affected:** Phase A and Phase B identities; plan lines 59–64 and 74.

Asking which tract is intended is correct when selection is ambiguous. The plan does not cover an explicit request to review several identified operative tracts together.

The research documents separate descriptions within one document and per-tract state; see manual multi-tract documentation and the reconstruction's domain model.

Recommended amendment: reuse one acquisition with separate selection/review identities for each requested tract, return a combined inventory and preserve independent outcomes. This is bounded local composition, not hosted bulk processing.

Acceptance: a document has two requested operative tracts plus a historical quotation; one operative tract has an unreadable course. Produce separate outcomes for the intended tracts, exclude the quotation with recorded rationale, and resume only the affected tract without merging traverses or implying all passed.

### A09 P2 PLSS inputs need unique reference identity and derivation rules

**Affected:** Phase G; plan lines 140–144.

Authoritative source/date/CRS provenance alone does not establish unique section selection or the validity of a subdivision method.

The saved PLSS guide distinguishes nominal shape from reference placement and computed subdivisions from survey evidence. The proposed stronger requirements are independent design choices, not claims about recovered vendor logic.

Recommended amendment: require an unambiguous section/reference ID, including principal-meridian context where applicable, and record the versioned derivation rule and its supported subset.

Acceptance: duplicate township/range/section labels, missing corners, government lots and irregular/excess-deficiency cases either resolve from explicit supported evidence or stop. Never silently use rectangular midpoint division for an unsupported case.

### A10 P2 Define completion by passed applicable gates

**Affected:** Parallel execution and completion; plan line 167.

The current wording requires gates to “have recorded results.” Failed checks also have recorded results, so that phrase is too weak as the completion criterion.

Recommended amendment: require all applicable implementation/regression/distribution gates to pass. Keep native Cowork, actual model behavior and optional provider acceptance in separate explicitly passed/failed/not-run fields. Local completion with native acceptance not run must not become a full Cowork parity claim. A failing applicable gate remains open.

This follows the existing [evaluation protocol](../../plugins/metesparser/evals/README.md), which does not turn startup/authentication failure or an unrun session into behavioral evidence.

## Scope decisions to retain or clarify

- Keep hosted accounts, billing, permissions, public sharing and Partner API reconstruction excluded. No local review requirement needs those services.
- Treat KML/KMZ/Shapefile, coordinate-to-call inversion, automatic closing-call suggestions, exact manual DSL compatibility and managed batch-service parity as explicit deferred features, not silently promised by the phrase “reproduce BoundaryLogic.” Product paths matter: Trace export support is not proof of Partner API support.
- Preserve MetesParser's canonical verification rules. Vendor editor/report rating differences are surface policies and are not evidence that MetesParser should adopt their thresholds.
- Keep expected numerical values independently derived. The published API example disagrees with its own calls and is unsuitable as a golden fixture.
- Preserve the current distinction between implemented native-reading instructions/adapters and actual native Claude/Cowork acceptance. The latter remains unrecorded.

## Amendment disposition

All findings are addressed at the specification level. Implementation checkboxes remain open, and no software or native-client acceptance result is implied by this disposition.

| Finding | Revised plan location | Requirement and acceptance added |
| --- | --- | --- |
| A01 | [Phase B](2026-10-28-boundarylogic-cowork-workflow-plan.md#phase-b-durable-scenarios-and-source-corrections), carried into C/E | Exact draft recovery, distinct revision states, stable tract identities, complete publication, retry/late-save protection and interrupted multi-tract cases |
| A02 | [Phase C](2026-10-28-boundarylogic-cowork-workflow-plan.md#phase-c-reproducible-review-packages-and-exports) | Immutable export snapshot, transform policy, per-format content/omissions, explicit visibility/order, unavailable metrics and interrupted-generation checks |
| A03 | [Phase A](2026-10-28-boundarylogic-cowork-workflow-plan.md#phase-a-natural-routing-and-resumable-review) | Source-linked accounting and closing-subset, missing/duplicate course, exception, continuation and comma-lot negative cases |
| A04 | [Phase E](2026-10-28-boundarylogic-cowork-workflow-plan.md#phase-e-richer-geometry-review-and-call-editing) | Existing curve consistency rejection, independent sensitivity parameters and explicit arc-support boundaries |
| A05 | [Phase F](2026-10-28-boundarylogic-cowork-workflow-plan.md#phase-f-centerline-corridors) | Lossless width/taper/join/cap round trips through B/C, linear error budgets and explicit invalid-width/topology outcomes |
| A06 | [Phase D](2026-10-28-boundarylogic-cowork-workflow-plan.md#phase-d-guided-placement-and-registration) | Separate deed translation/rotation evidence, fresh geometry binding, retained placement limits and independent registration invalidation |
| A07 | [Phase E](2026-10-28-boundarylogic-cowork-workflow-plan.md#phase-e-richer-geometry-review-and-call-editing) | Supported angle/unit/orientation/role matrix, relative-analysis routing, incomplete-entry recovery and unsupported-input cases |
| A08 | [Phase A](2026-10-28-boundarylogic-cowork-workflow-plan.md#phase-a-natural-routing-and-resumable-review) | Shared acquisition with separate requested-tract identities/outcomes, quotation exclusion and per-tract resume |
| A09 | [Phase G](2026-10-28-boundarylogic-cowork-workflow-plan.md#phase-g-plss-geometry-from-supplied-reference-data) | Unique section reference, versioned derivation rule and ambiguous/irregular/unsupported subdivision refusal tests |
| A10 | [Completion](2026-10-28-boundarylogic-cowork-workflow-plan.md#parallel-execution-and-completion) | Applicable local gates must pass; native/model/provider acceptance remains separately passed, failed or not run |

The plan also makes deferred formats, language compatibility, coordinate inversion, automatic closing-call suggestions and Partner API/batch-service parity explicit. Native-reading instructions are distinguished from unrecorded native-host acceptance, and numerical fixtures must be independently derived.

Audit evidence was checked in the original pass. This amendment pass changes documentation only; implementation and behavioral tests were not run.
