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
