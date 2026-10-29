# Pydantic Audit To-Dos

- [x] High: Add cross-field validation for `DeedCall` curve geometry in `src/metesparser/models.py`.
  - Use `@model_validator(mode="after")` to enforce consistency for `curve_dir`, `radius_ft`, `delta_deg`, `arc_length_ft`, and `chord_length_ft`.
- [x] Medium: Harden assignment behavior for mutable models in `src/metesparser/models.py`.
  - Enable `validate_assignment=True` in model config.
  - Replace in-place mutation of `DeedCall` instances (e.g., `call.bearing_azimuth_deg_from_north = ...`) with `call.model_copy(update={...})` where practical.
- [x] Medium: Normalize enum-like textual inputs for `curve_dir` and `monument_type`.
  - Add normalization/validation so case and formatting differences from CSV/LLM inputs are handled consistently.
- [x] Medium: Reject non-finite numeric values across models.
  - Add finite-number constraints (`finite=True`) for `DeedCall`, `Point`, and `ClosureResult` numeric fields.
- [x] Medium: Tighten model config defaults for external payloads.
  - Set explicit `extra` handling (`"forbid"` or equivalent), and normalize/strip strings at model boundaries.
- [x] Low: Remove redundant azimuth validation overlap.
  - Keep range checks in field constraints and simplify custom azimuth validator to only enforce non-field expressible rules.
- [x] Low: Align `LegalDescription.distance_unit` typing with conversion support.
  - Ensure supported units match `ConversionFactors.convert_to_feet` (including any aliases like `perches` / `links`).

## Documentation Audit To-Dos (2026-02-14)

- [x] High: Fix broken public API examples in docs that import non-exported package symbols.
  - Update `README.md:99`, `docs/API.md:8`, and `docs/API.md:214` imports to import concrete modules or export symbols in `src/metesparser/__init__.py:6`.
  - **Resolved**: `__init__.py` now exports all 7 public symbols; all doc examples use valid imports.
- [x] High: Correct `CHANGELOG.md` backfill completeness claims.
  - `CHANGELOG.md:10-36` says all commits are included in Unreleased, but `git log -n 30` includes commits not represented (e.g., `602557b`, `8eda598`).
  - Either include missing entries or adjust scope wording.
  - **Resolved**: Both commits `602557b` and `8eda598` are present in the CHANGELOG backfill.
- [x] High: Replace or guard references to missing scripts in docs.
  - `README.md:35`, `README.md:44`, and `prompts/README.md:181` reference `scripts/generate_ground_truth.py` / `extract_sample_deeds.py`.
  - These files are not tracked by git (`git ls-files` does not return them).
  - **Resolved**: Both scripts now exist and are git-tracked (organized in `d1bb11b`, updated in `55f9948`).
- [x] Medium: Update stale test-count language.
  - `README.md:185` and `README.md:306`, `docs/ARCHITECTURE.md:33`, and `docs/TESTING.md:3,20,35` now reflect current test volume.
  - **Resolved**: Updated to **643 collected tests** (`uv run pytest --collect-only -q`) as of 2026-02-15.
- [x] Medium: Reconcile versioning mismatch across docs and package metadata.
  - `CLAUDE.md:9` previously stated `0.3.1` while `src/metesparser/__init__.py:13` is `0.1.0`.
  - **Resolved**: `CLAUDE.md` now matches package version `0.2.0`.
- [x] Medium: Update test path guidance to current layout.
  - `CLAUDE.md` development and test-location examples now use `tests/unit/...` paths.
  - **Resolved**: Removed stale `tests/test_*.py` references in commands and guidance.
- [x] Medium: Align docs coverage targets with current status.
  - `docs/TESTING.md` coverage section now treats `>95%` critical-module coverage as a stretch target and shows current baselines.
  - **Resolved**: Captures current metrics (overall 93%, `bearing_converter.py` 80%, `call_extractor.py` 88%, `closure_checker.py` 99%).
- [x] Low: Correct legal wording for deed dataset documentation.
  - Replace "public domain" phrasing in `sample_deeds/README.md:73` with public-records language.
  - **Resolved**: Legal note now says "public records" consistently.
- [x] Low: Update fixture-path reference in `AGENTS.md`.
  - `AGENTS.md:8-9` and `AGENTS.md:21` now reference `tests/fixtures` instead of `tests/data`.
  - **Resolved**: Fixture guidance now matches current repository layout.

## Metes & Bounds Reference Audit To-Dos (2026-02-15)

- [x] High: Align curve sign guidance with project schema.
  - Update `docs/METES_AND_BOUNDS_REFERENCE.md:336-337` and `docs/METES_AND_BOUNDS_REFERENCE.md:751` to reflect that `radius_ft` is positive and handedness is carried by `curve_dir` (`left`/`right`), matching `src/metesparser/models.py:71-75`.
  - **Resolved**: Updated Section 5.3 and COGO field table to document project convention (`curve_dir` + positive `radius_ft`, with note on signed-radius variants).
- [x] High: Clarify six-guardrail runtime scope vs helper methods.
  - Revise `docs/METES_AND_BOUNDS_REFERENCE.md:1083-1090` to distinguish checks performed by `verify_closure()` from separate workflows like `compare_double_entry()` in `src/metesparser/closure_checker.py:376`.
  - **Resolved**: Updated Section 18.7 to state that `verify_closure()` runs checks 1-5 by default and check 6 when `double_entry_calls` is provided.
- [x] Medium: Fix precision-ratio definition wording.
  - Correct `docs/METES_AND_BOUNDS_REFERENCE.md:1033` so "1:X" precision is expressed as total perimeter divided by misclosure (or explicitly label if using inverse form).
  - **Resolved**: Changed to "Misclosure / Total perimeter, stored as a decimal" with worked example showing inverse 1:X display convention. Matches code storage format (`misclosure / perimeter`).
- [x] Medium: Resolve area precision contradiction.
  - Update `docs/METES_AND_BOUNDS_REFERENCE.md:124` so the stated rounding precision is consistent with example `0.1722` acres.
  - **Resolved**: Changed "nearest hundredth" to "four decimal places" to match 0.1722 example.
- [x] Medium: Soften absolute legal validity statements.
  - Reword `docs/METES_AND_BOUNDS_REFERENCE.md:527` and `docs/METES_AND_BOUNDS_REFERENCE.md:944` from universal "legally required/must" language to jurisdiction-dependent guidance.
  - **Resolved**: Changed to "Generally required in most jurisdictions" (line 529) and "should close / in most jurisdictions" with riparian exception note (line 946).
- [x] Low: Correct geodetic north definition.
  - Replace/reframe `docs/METES_AND_BOUNDS_REFERENCE.md:210` to avoid the inaccurate "derived using the Laplace equation" definition.
  - **Resolved**: Replaced with "direction of the meridian at a point on the reference ellipsoid (e.g., NAD 83)" with deflection-of-the-vertical note.

## Reference-Doc Gap Improvements (2026-02-15)

Phased rollout based on gap analysis between `docs/METES_AND_BOUNDS_REFERENCE.md` and current parser capabilities. New verification checks add warnings only (no export blocking). Approach: bottom-up (models → parsing → verification → output).

**Dependency graph**: Phase 1 → Phases 2 & 3 (parallel) → Phase 4 (after Phase 2) → Phase 5 (after all).

### Phase 1: Foundation — Units, Models & Monument Types

- [x] High: Add missing distance units to `DistanceUnit` and `ConversionFactors` in `models.py`.
  - Add: `varas` (2.778 ft), `arpents` (191.8 ft), `toises` (6.395 ft), `furlongs` (660 ft), `meters` (3.28084 ft), `miles` (5280 ft), `engineer_chains` (100 ft), `engineer_links` (1.0 ft).
- [x] Medium: Add missing monument types to `MonumentType` in `models.py`.
  - Add: `pk_nail`, `hub_and_tack`, `monitoring_well`, `capped_pin`, `capped_rod`, `txdot_monument`.
- [x] Medium: Add monument patterns to `MonumentClassifier` in `call_extractor.py`.
  - Regex patterns for PK nail, hub and tack, monitoring well, capped pin/rod, TxDOT monument.
- [x] Medium: Add `precision_ratio` field (float | None) to `ClosureResult` in `models.py`.
- [x] Low: Add `non_tangent` (bool, default False) and `radial_bearing` (str | None) fields to `DeedCall` in `models.py`.

### Phase 2: Enhanced Parsing — Packed DMS, Chord Bearings, Non-Tangent Curves

- [x] High: Add `parse_packed_dms(value: float) -> float` to `bearing_converter.py`.
  - Convert packed DMS format (46.1631 → 46.2753°) to decimal degrees.
- [x] High: Extract chord bearing from curve text in `call_extractor.py`.
  - Pattern: `chord of which bears S 34°57'37" E, 254.22 feet`.
- [x] Medium: Detect non-tangent curves in `call_extractor.py`.
  - Patterns: `non-tangent curve`, `radial line...bears`.
- [x] Medium: Add `extract_basis_of_bearing(text) -> str | None` to `text_parser.py`.
- [x] Medium: Add `extract_surveyor_certification(text) -> str | None` to `text_parser.py`.
- [x] Medium: Add `extract_prior_conveyance(text) -> str | None` to `text_parser.py`.
- [x] Low: Add distance extraction support for varas, arpents, toises, furlongs, meters, miles in `text_parser.py`.
- [x] Low: Add unit-inference heuristics from reference Section 4.3 (Texas pre-1900 → varas, Louisiana → arpents, etc.).

### Phase 3: Verification Guardrails — Bearing Reversal, Distance Reasonableness, Precision Ratio

- [x] High: Add `check_bearing_reversal(calls) -> list[str]` to `closure_checker.py`.
  - Flag consecutive courses with azimuths within 5° of ±180° reversal (possible quadrant transcription error).
- [x] High: Add `check_distance_reasonableness(calls) -> list[str]` to `closure_checker.py`.
  - Flag: distance < 0.1 ft, distance > 5,280 ft, distance ratio > 100× median.
- [x] Medium: Compute and store `precision_ratio` in `verify_closure()`.
  - Formula: `misclosure_ft / perimeter_ft`. Display as ratio (e.g., "1:15,000") in `get_closure_summary()`.
- [x] Medium: Wire new checks into `verify_closure()` as warnings (no blocking).

### Phase 4: Water Boundaries & Meander Detection

- [x] High: Add `detect_water_boundary(text) -> dict | None` to `text_parser.py`.
  - Detect riparian language: creek, river, stream, shore, bank, high-water mark, thread, thalweg.
- [x] Medium: Add `is_meander_call(call_text) -> bool` to `text_parser.py`.
  - Detect meander keywords and "along the creek/river/stream" patterns.
- [x] Medium: Add `is_meander` bool field (default False) to `DeedCall` in `models.py`.
- [x] Medium: Flag meander calls in `call_extractor.py` with `notes="meander / water boundary"`.
- [x] Low: Add closure warning when meander calls are present in `closure_checker.py`.

### Phase 5a: Production Completeness (COMPLETE — PR #5)

- [x] Degree of curvature parsing (D° → radius)
- [x] Extended curve properties (T, E, M)
- [x] Natural monument classification (tree, rock, natural_feature)
- [x] 32-point compass system (mariner's notation → azimuth)
- [x] Clause taxonomy (reservation, subject_to, together_with)
- [x] Subdivision lot/block + TPOB/RPOB recognition
- [x] Witness tree extraction
- [x] Spiral/transition curve detection
- [x] State Plane Coordinate System metadata + FIPS code
- [x] Pipeline wiring (all new methods into `process_deed_pdf()`)

### Phase 5b: Output & Reporting Enhancements (COMPLETE)

- [x] Medium: Add `score_call_quality(call) -> str` to `closure_checker.py`.
  - Returns "high" / "medium" / "low" based on bearing completeness, monument permanence, meander flags.
- [x] Medium: Add `calculate_confidence_score(result, calls) -> float` (0.0–1.0) to `closure_checker.py`.
  - Incorporates: closure quality (30%), verification checks (20%), bearing completeness (25%), call quality (15%), warning penalty (10%).
- [x] Medium: Add `confidence_score` (float | None) and `quality` (str | None) fields to `ClosureResult` and `DeedCall` in `models.py`.
- [x] Low: Update `get_closure_summary()` with confidence score, precision ratio, per-call quality breakdown.

## Extraction Error Fixes (2026-02-16)

Found by running all 6 sample deeds and comparing extraction output against ground truth JSON files.

### Bug E1: Phantom Calls from POB Preamble (P0 — High)

**Affects**: 18 Pennbrook, 31 Pennbrook (10989), 31 Pennbrook (11191) — 3 of 6 deeds
**Symptom**: Distances in BEGINNING AT text parsed as extra calls (e.g., "50 feet wide" → phantom 50 ft call, "310.00 FEET SOUTHEASTWARDLY" → phantom 310 ft call)
**Root cause**: `split_into_calls()` in `text_parser.py:359` receives full legal description including POB preamble. Cardinal direction words ("southwesterly", "northeasterly") + distances in POB text pass through all three defense layers.
**Fix location**: `call_extractor.py:extract_calls()` (~line 196) — strip everything before the first `THENCE` keyword before calling `split_into_calls()`.

- [x] High: Strip POB preamble before first THENCE in `call_extractor.py:extract_calls()`.
  - Find first `\bTHENCE\b` in normalized text and discard everything before it.
  - POB is already captured separately by `extract_poc_and_pob()`, so no data is lost.
  - Add regression tests for all three affected deeds' POB text patterns.

### Bug E2: Wrong Legal Description Extracted by LLM (P1 — High)

**Affects**: 24 Pennbrook — completely wrong parcel extracted (Lot 22 "Pembrook" instead of Lot 12 "Pennbrook")
**Symptom**: LLM extracted an older prior conveyance from Exhibit A instead of the current deed description. 8 calls with wrong bearings, 365 sq ft instead of 17,750 sq ft.
**Root cause**: Prompt in `prompts/extract_legal_description.yaml:29` says "Prefer Exhibit A" and "choose the section with the most bearings and distances" — the older description had MORE calls, so the LLM picked it.
**Fix location**: `prompts/extract_legal_description.yaml` — rewrite multi-description guidance to prioritize current conveyance over "most detailed".

- [x] High: Rewrite multi-description selection guidance in `prompts/extract_legal_description.yaml`.
  - Replace "prefer Exhibit A / most detailed" with "prefer current conveyance" logic.
  - Add instructions to IGNORE prior conveyance sections ("BEING the same premises", "previously conveyed", older deed book references).
  - Add lot/block consistency guidance (extracted description should match deed's subject property).
- [x] Medium: Add post-extraction prior conveyance detection in `pdf_processor.py`.
  - Log warning if extracted text contains prior conveyance language.

### Bug E3: Along/To Field Bleeding into Metadata (P2 — Medium)

**Affects**: 18 Pennbrook last call — `along` captures "THE ABOVE DESCRIBED tract...", `to` captures "a Survey of Premises made by Walter H"
**Symptom**: Last call's `along` and `to` fields include text from survey certification that follows the legal description.
**Root cause**: `split_into_calls()` in `text_parser.py:359` has no termination logic for the last call — all text after the final delimiter becomes part of that call. `extract_along_to_fields()` then captures the contaminated text.
**Fix location**: `text_parser.py:split_into_calls()` — truncate last call at known metadata boundaries.

- [x] Medium: Truncate last call text at metadata section boundaries in `text_parser.py:split_into_calls()`.
  - Detect patterns like `. THE ABOVE DESCRIBED`, `. BEING the same premises`, `. CONTAINING`, `. SUBJECT TO`, `. TOGETHER WITH`, `. Surveyed by`.
  - Alternatively, detect POB closure phrase ("to the point and place of beginning") and truncate after it.
  - Add regression test with 18 Pennbrook's trailing survey certification text.

### Bug E4: OCR Bearing Error (P3 — Low, no code fix)

**Affects**: 31 Pennbrook (11191) call 3 — N 56°40'00" E read as N 56°40'50" E
**Symptom**: Misclosure 0.0167 ft instead of 0.0116 ft, area off by 1.25 sq ft.
**Root cause**: LLM misread "00" as "50" from scanned PDF. Inherent OCR limitation.
**Mitigation**: Try different LLM provider; add image preprocessing; cross-validate bearings across chain-of-title deeds.

- [x] Low: Document OCR bearing error as known limitation; consider cross-validation heuristic for chain-of-title deeds.

### Bug E5: LLM Extraction Failure on Old Scanned PDF (P3 — Low, no code fix)

**Affects**: 31 Pennbrook (4618) — 0 calls extracted, GT expects 5
**Symptom**: Oldest deed (1993), poor scan quality. LLM returned text but call extractor found nothing parseable.
**Root cause**: Scanned PDF quality too poor for LLM OCR.
**Mitigation**: Pre-process with dedicated OCR (Tesseract, Adobe PDF Services); retry with different LLM provider.

- [x] Low: Document old-scan extraction failure as known limitation; consider Tesseract preprocessing fallback.

## Dashboard Skill and Metes & Bounds Checking Improvements (2026-10-26)

Skill composability refactor implemented 2026-10-27: five focused capabilities (conversion, selection, verification, plotting, overlay preparation), two composing workflows (review, dashboard), and the deed-review compatibility alias. Standalone plotting reuses the shared geometry/SVG engine; explicit artifact contracts preserve source identity, unresolved values, and separate verification status. [Design and validation evidence](plans/2026-10-27-composable-skills-refactor.md). Native Claude/Cowork behavior remains part of item 6.

Plot and optional tax-map overlays implemented 2026-10-27: source-linked line/arc/partial plotting, explicit rigid placement, supplied vector layers, GeoJSON import, scanned-map calibration and optional exact-identifier NJGIN retrieval. [Plan](plans/2026-10-26-deed-plot-and-tax-overlay-plan.md) · [red–green and release evidence](plans/2026-10-27-deed-plot-implementation.md). Validation: 1,495 root tests, 829 package/plugin tests, 10 actual browser cases, both locked plugin runtime variants and live retrieval/offline replay passed. This supplies alignment prerequisites for item 5; structural boundary matching and item 6's native-reading/Claude/Cowork acceptance remain open.

Recommended sequence: first complete item 1, the data-schema portion of item 2, and a small fixture suite from item 6. Then build the reusable renderer and angle-analysis module against those contracts. Add diagnostics and cross-description comparison afterward. Keep package and backward-compatible monolith behavior in sync, and preserve the existing verified-export gate.

- [x] High — 1. Distinguish successful checks from checks that were not performed. **Effort: Medium.** Completed 2026-10-26.
  - Add structured `passed`, `failed`, `not_applicable`, and `blocked` outcomes with reasons; display geometric results separately from source-review completeness.
  - Correct the current angle-check reporting: `packages/mp-verify/src/mp_verify/checks.py:check_interior_angles()` returns `True` for curves or incomplete bearings, while `closure.py:verify_closure()` can describe that as "all-straight polygon angles sum correctly."
  - Update `packages/mp-models/src/mp_models/closure.py:CheckResult`, audit rendering, and confidence scoring with compatibility handling for existing consumers.
  - Acceptance: a valid curved boundary reports the straight-angle check as `not_applicable`; missing required bearings report `blocked`; an actual failed angle check is not described as skipped. Test structured results and audit wording through package and monolith APIs.
  - Implemented four-state outcomes with reasons/inputs on `ClosureResult`, separate source-review status, truthful audit HTML/text, and confidence scoring that gives no pass credit to skipped checks. Kept package/monolith behavior aligned and preserved fresh geometry verification before export, including old serialized results.
  - Verification: 56 new package/monolith outcome regressions cover curved boundaries, missing bearings, actual failures, legacy export compatibility, unavailable exception areas, and unchanged export safeguards. `make check` passes 1,493 root tests with 93.49% coverage.

- [x] High — 2. Add a validated dashboard data bundle and reusable renderer. **Effort: Large.** Completed 2026-10-26.
  - Turn the contract in `plugins/metesparser/skills/deed-closure-dashboard/references/playbook.md` into a versioned schema connecting documents, pages, description occurrences, calls, evidence crops, calculations, and scenarios.
  - Validate stable IDs, source references, units, coordinate frames, reading uncertainty, and source-versus-derived fields. Preserve unknown values and separate immutable records from editable scenarios.
  - Package tested HTML/CSS/JS components for the six core dashboard sections, with optional host features detected at runtime. Use the Walnut HTML only as a design example; do not bundle its property data or injected runtime.
  - Save stage outputs and input hashes so layout-only changes reuse completed document review; invalidate dependent results when source readings or assumptions change.
  - Acceptance: the same validated bundle renders reproducibly; dangling source references fail validation; scenario edits leave original record hashes, findings, and engine status unchanged; reset and offline copy/viewer controls work.
  - Implemented immutable versioned source bundles, canonical/relative calculation stages, validated stage reuse, and a self-contained six-section renderer. Added `metes-review dashboard`, plugin launcher support, a `metesparser.dashboard` facade, and schema/example guidance in the skill. Outputs preserve exact input bytes plus source/calculation/presentation hashes and a renderer fingerprint; rendering never writes verified CSV.
  - Verification: 708 deterministic package/plugin tests pass, including 33 bundle tests, 45 renderer tests, and 5 dashboard CLI tests. Fixtures cover source-reference rejection, unknown readings, input validation, scenario isolation, Python/JavaScript numerical agreement, cache tampering, and reproducible cold/warm rendering.
  - Browser/package verification: Chromium checks passed for offline absolute/relative edits, presets, reset, immutable records, invalid bearing rejection, clipboard fallback, occurrence switching, and two-page viewer keyboard/focus behavior. Light/dark mobile layouts fit a 400 px viewport. The rebuilt plugin passed an isolated wheel/runtime smoke test, producing six dashboard artifacts with preserved source bytes and no verified CSV.
  - Delegation: GPT-6.1-sol handled implementation and independent integration reviews; GPT-6-luna handled documentation. Parent integration ran the full checks. Native document-reading accuracy and Claude/Cowork host acceptance remain for item 6. Shared-boundary comparison is item 5; interactive curve editing is unsupported, and relative angular alternatives require explicit sourced scenario presets.

- [x] High — 3. Support deterministic analysis of relative-angle descriptions. **Effort: Large.** Completed 2026-10-26.
  - Move the playbook's reference calculation into a tested module supporting stated interior/exterior angles, perpendicular lines, and parallel-line constraints.
  - Calculate sufficiently determined relative geometry in a declared local frame. Keep numeric recorded bearings unknown when absent; local-angle results must not promote the canonical engine status or authorize verified export.
  - Preserve source wording and references for every constraint. Report ambiguous turns as labeled alternatives or unresolved results, and reject contradictory or insufficient constraints.
  - Acceptance: an angle-defined rectangle has reproducible closure and area while its recorded azimuths remain `None`; tests cover reflex corners, reverse traversal, arbitrary rotation/translation, and unresolved constraints.
  - Implemented source-linked immutable models in `mp_models.relative`, the constraint-graph solver in `mp_verify.relative`, the `metesparser.relative` compatibility facade, and `metes-review analyze-relative`. The dashboard skill now uses the module/command instead of an inline algorithm; see its `references/relative-analysis.md` and synthetic rectangle fixture.
  - Verified with two implementation subagents and an independent review subagent: 56 new model/solver tests, 20 API/CLI tests, and 5 launcher/facade/export/import regressions. `make check` passed 1,436 root tests; the deterministic package/launcher suite passed 624 tests. Built plugin smoke test: 100 × 50 ft rectangle gives 5,000 sq ft and negligible floating-point gap, retains `needs_review`/unknown bearings, and produces no verified CSV.
  - Scope: explicit straight-course JSON constraints; native document reading, automatic prose-to-constraint extraction, circular constraints, and target-host dashboard UI testing are outside this item. Independent review regressions reject unrepresentable translated coordinates and complete angle rings with contradictory winding sums.

- [ ] Medium — 4. Explain which calls deserve source reinspection. **Effort: Medium.**
  - Add course-level displacement and sensitivity diagnostics showing how small distance or angle changes affect the endpoint; link each review candidate to its source excerpt/crop.
  - Evaluate proposed digit readings as explicit scenarios without selecting corrections merely because they improve closure. Report competing explanations.
  - Introduce rounding bounds only when source precision supports them, and keep those bounds distinct from the heuristic score in `packages/mp-verify/src/mp_verify/confidence.py`.
  - Acceptance: a 0.5-ft eastward residual identifies both opposing east/west distances as review candidates; diagnostics neither choose the erroneous source value nor change export eligibility.

- [ ] Medium — 5. Compare descriptions structurally across versions and adjoining parcels. **Effort: Large.**
  - Extend beyond word redlines and positional double-entry comparison to identify changed distances, bearings, monuments, omitted calls, and one course split into several.
  - Start shared-boundary comparison with explicitly selected line pairs, opposite traversal directions, and declared alignment/bearing-basis prerequisites. Keep tentative matches distinct from established relationships.
  - Reuse `packages/mp-verify/src/mp_verify/checks.py:compare_double_entry()` where appropriate; preserve its existing same-traverse behavior while adding a separate comparison capability.
  - Acceptance: reversed descriptions of the same line agree geometrically, length differences are quantified, and an unresolved bearing basis returns `not_comparable` instead of silently aligning parcels.

- [ ] High — 6. Evaluate the full document-to-dashboard workflow. **Effort: Medium to Large.**
  - Add reviewed document fixtures for obscured digits, repeated exhibits, missing pages, angle-only descriptions, exceptions, and conflicting versions; extend `plugins/metesparser/evals/cases.json` with dashboard scenarios.
  - Evaluate source selection/transcription separately from deterministic calculation and browser behavior. Build on `packages/mp-review/src/mp_review/corpus.py` for fixture-backed numerical assertions.
  - For disputed figures, have a second reader inspect the source without seeing the first reading or closure result; record and reconcile disagreements explicitly.
  - Acceptance: every expected page and description occurrence is accounted for; unresolved digits stay conditional; source links open the correct occurrence; Python/JavaScript results agree within 0.001 ft; scenario/reset isolation, strict input validation, and responsive viewer/copy controls pass browser checks.
  - Record actual subagent/model use and stage completion, including any native-reading or target-host checks that remain untested.
