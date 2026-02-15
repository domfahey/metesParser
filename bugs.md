# Bugs

## Audit Notes (2026-02-14)
- Corrected the non-reproducible fallback-distance claim into a reproducible parser bug.
- Merged duplicate `along` substring reports (old #9 and #13).
- Added a triage metadata checklist to make each bug easier to verify and close.

## Triage Metadata Checklist
Use this for each bug ticket in issue tracker/PR discussion:
- **Status:** `open` | `in_progress` | `fixed`
- **Severity:** `high` | `medium` | `low`
- **Reproducibility:** `always` | `intermittent`
- **Minimal input:** single string/PDF snippet that triggers the issue
- **Expected behavior:** precise output/state
- **Actual behavior:** precise output/state
- **Suggested test:** unit/integration assertion to prevent regression

## High

### 1) Missing singular distance unit `"foot"` is ignored
- **Location:** `src/metesparser/text_parser.py` (`TextParser.extract_distance`)
- **Issue:** The distance regex accepts `feet`, `ft`, and pluralized units, but not singular `foot`.
- **Impact:** Calls written as `1 foot` (or `2 foot`) parse as distance `0`, so valid lines can be dropped.
- **Suggested fix:** Add `foot` to the regex unit pattern and normalize to `feet`.

### 2) PLSS range direction can be misdetected as East for West ranges
- **Location:** `src/metesparser/text_parser.py` (`TextParser.extract_plss_metadata`)
- **Issue:** West range is inferred with `"E" in range_match.group(0)`, which is true for `WEST`.
- **Impact:** `W` ranges can be silently flipped to `E`, corrupting legal metadata.
- **Suggested fix:** Parse explicit east/west tokens via capture groups or token-level regex checks.

### 3) OpenAI client drops requested response format hints
- **Location:** `src/metesparser/llm_clients.py` (`OpenAIClient.generate_text`, `OpenAIClient.generate_text_with_pdf`)
- **Issue:** `response_mime_type` is deleted and never forwarded to OpenAI requests.
- **Impact:** JSON-required extraction paths can receive non-JSON text and fail downstream parsing.
- **Suggested fix:** Map `response_mime_type` to OpenAI response-format controls and enforce JSON when requested.

## Medium

### 4) Alternate distance parser misses normal apostrophe forms but matches malformed concatenations
- **Location:** `src/metesparser/call_extractor.py` (`CallExtractor.extract_distance_alternate`)
- **Issue:** Pattern `(?:'|feet|ft)\b` does not match common prose like `125.26' along ...`, but does match malformed strings like `30'to`.
- **Impact:** Produces false negatives on legitimate apostrophe-foot notation and false positives on malformed/OCR-collapsed tokens.
- **Suggested fix:** Handle apostrophe-foot with explicit trailing delimiter rules and guard against angle-token artifacts.

### 5) Polygon area formula assumes closed points list and omits wrap-around segment
- **Location:** `src/metesparser/closure_checker.py` (`ClosureChecker.calculate_area`)
- **Issue:** Shoelace loop uses `for i in range(n - 1)`, skipping the final wrap edge unless input already repeats start point.
- **Impact:** Non-repeated point lists produce inaccurate area values and warnings.
- **Suggested fix:** Include wrap-around with modulo indexing (`j = (i + 1) % n`) or explicitly enforce repeated first point.

### 6) `metadata` argument in `calls_to_csv` is silently ignored
- **Location:** `src/metesparser/csv_builder.py` (`CSVBuilder.calls_to_csv`)
- **Issue:** Method accepts `metadata` but intentionally does nothing with it.
- **Impact:** Callers may assume metadata persistence that never occurs.
- **Suggested fix:** Persist metadata deterministically (CSV preamble/sidecar) or remove the argument.

### 7) Curve model inconsistently rejects zero-degree curve data
- **Location:** `src/metesparser/models.py` (`DeedCall.delta_deg`, `DeedCall.arc_length_ft`) and curve logic using truthiness checks
- **Issue:** `DeedCall` requires `delta_deg > 0` / `arc_length_ft > 0`, while curve math utilities support `delta_deg == 0`.
- **Impact:** Zero-angle curve representations are rejected or skipped inconsistently.
- **Suggested fix:** Harmonize constraints around mathematically valid zero values and replace truthy checks with `is not None` where needed.

### 8) Parallelism check ignores azimuth wrap-around at North
- **Location:** `src/metesparser/closure_checker.py` (`ClosureChecker.check_parallelism`)
- **Issue:** Uses raw `abs(curr_az - prev_az)` without circular normalization.
- **Impact:** Bearings near `0°/360°` can trigger false parallelism warnings.
- **Suggested fix:** Compare with circular delta: `min(diff, 360 - diff)`.

### 9) `extract_along_to_fields` matches substrings like `"alongside"`
- **Location:** `src/metesparser/text_parser.py` (`TextParser.extract_along_to_fields`)
- **Issue:** Detection uses `find("along")` instead of standalone keyword matching.
- **Impact:** Non-clause words can be parsed as `along` clauses and corrupt metadata.
- **Suggested fix:** Use word-boundary token matching (`\balong\b`) and parse clause boundaries explicitly.

### 10) Parenthesized or bare-numbered calls are not split into separate calls
- **Location:** `src/metesparser/text_parser.py` (`TextParser.split_into_calls`)
- **Issue:** Splitter recognizes `1.` but not `(1)` or `1)` call numbering styles.
- **Impact:** Multi-call descriptions can collapse into one parsed call.
- **Suggested fix:** Extend numbering regexes to include `(n)` and `n)` forms.

### 11) Exception splitting triggers on incidental `ALSO`/`INCLUDING`
- **Location:** `src/metesparser/text_parser.py` (`TextParser.split_exception_clauses`)
- **Issue:** Any standalone `ALSO`/`INCLUDING` is treated as a tract boundary.
- **Impact:** Main tract text can be split incorrectly in normal prose.
- **Suggested fix:** Restrict split triggers to stronger clause-start patterns.

### 12) Decimal-degree curve deltas are ignored
- **Location:** `src/metesparser/call_extractor.py` (`CallExtractor.extract_curve_info`)
- **Issue:** Delta fallback parser captures integer degrees only (`(\d+)`).
- **Impact:** Inputs like `delta of 90.5 degrees` lose delta data; fallback distances can become wrong.
- **Suggested fix:** Accept decimal degree/minute formats and compute arc length when radius+delta are available.

### 13) Curve direction phrase (`to the right/left`) is misread as endpoint text
- **Location:** `src/metesparser/text_parser.py` (`TextParser.extract_along_to_fields`)
- **Issue:** `to` parsing does not distinguish endpoint `to` from curve-direction phrase `to the right/left`.
- **Impact:** Endpoint metadata can be replaced with directional junk text.
- **Suggested fix:** Exclude structural direction phrase tokens from endpoint extraction.

### 14) Double-entry validation misses several curve mismatches
- **Location:** `src/metesparser/closure_checker.py` (`ClosureChecker.compare_double_entry`)
- **Issue:** Curve comparison checks direction and sometimes radius, but omits delta/arc/chord mismatches and asymmetric presence.
- **Impact:** Non-equivalent curve entries can be reported as matching.
- **Suggested fix:** Compare all meaningful curve fields and treat asymmetric curve data as discrepancy.

### 15) Prompt loading path is hard-coded to source-checkout layout
- **Location:** `src/metesparser/pdf_processor.py` (`PDFProcessor.__init__`)
- **Issue:** Prompts path assumes repository-relative `prompts/` location.
- **Impact:** Installed-package layouts can fail at runtime with missing prompt files.
- **Suggested fix:** Load prompts via package resources and include them as package data.

### 16) `extract_sample_deeds.py` points to non-existent `scripts/sample_deeds`
- **Location:** `scripts/extract_sample_deeds.py` (`SAMPLE_DEEDS_DIR`)
- **Issue:** Uses `Path(__file__).parent / "sample_deeds"` instead of repo-root `sample_deeds/`.
- **Impact:** Script skips every configured sample PDF.
- **Suggested fix:** Resolve from project root (`Path(__file__).parent.parent / "sample_deeds"`).

### 17) Ground-truth `notes` field records script mtime, not generation time
- **Location:** `scripts/generate_ground_truth.py` (`generate_ground_truth`, `notes` field)
- **Issue:** Notes timestamp uses `Path(__file__).stat().st_mtime`.
- **Impact:** Provenance timestamp reflects script file edit time, not when output was generated.
- **Suggested fix:** Use runtime UTC timestamp (`datetime.now(timezone.utc).isoformat()`).

### 18) Zero-degree curve distances are dropped as non-calls
- **Location:** `src/metesparser/call_extractor.py` (`CallExtractor.extract_single_call`)
- **Issue:** Arc length `0.0` overrides parsed distance, then `distance_ft <= 0.0` causes call drop.
- **Impact:** Zero-deflection curve cases can be silently lost.
- **Suggested fix:** Do not override with non-positive arc length; preserve original line distance for `delta_deg == 0`.

### 19) Root package does not expose documented public classes
- **Location:** `src/metesparser/__init__.py` and docs in `README.md`, `docs/API.md`
- **Issue:** Package root exports only `__version__`, but docs show root-level imports.
- **Impact:** Documented import examples fail with `ImportError`.
- **Suggested fix:** Re-export documented public classes in `__init__.py` or update docs to module-level imports.

### 20) Incomplete curve specs crash call extraction
- **Location:** `src/metesparser/call_extractor.py` (`CallExtractor.extract_single_call`, `CallExtractor.extract_calls`)
- **Issue:** Curve parsing can produce incomplete curve metadata (e.g., radius only or delta only), which fails `DeedCall` validation.
- **Impact:** `ValidationError` is raised and bubbles out of `extract_calls`, aborting extraction of the whole description instead of skipping the bad segment.
- **Suggested fix:** Catch validation/parse errors per-call, emit a warning, and continue parsing remaining calls (or preserve malformed text for audit).

### 21) Curves with `radius` + `arc_length` but no `delta` are not traversed
- **Location:** `src/metesparser/call_extractor.py` (`extract_single_call`), `src/metesparser/closure_checker.py` (`ClosureChecker.compute_traverse`)
- **Issue:** `distance_ft` is set from `arc_length_ft`, but traversal only moves for curves when `call.delta_deg` is present.
- **Impact:** The segment is included in call output (and perimeter may include `arc_length`), but compute-traverse area/closure ignores it, producing inconsistent geometry.
- **Suggested fix:** Derive missing `delta_deg` when possible (`arc_length` + `radius`) or at minimum include an approximation branch for radius+arc-length curves in traversal.

### 22) Zero-deflection (`Δ = 0`) curves are treated as zero-move in traverse
- **Location:** `src/metesparser/closure_checker.py` (`ClosureChecker.compute_traverse`), `src/metesparser/call_extractor.py` (`CallExtractor.extract_single_call`), `src/metesparser/bearing_converter.py` (`BearingConverter.compute_curve_endpoint`)
- **Issue:** `compute_traverse` routes any curve call with `curve_dir/radius/delta` to `compute_curve_endpoint`, which computes an endpoint by chord length. For `delta_deg = 0`, chord length is `0`, so the curve advances no distance even if the call carried a positive `distance_ft` fallback for arc/line handling.
- **Impact:** Valid zero-deflection curve records are over-traversed (understated geometry) while perimeter logic can still add the call distance, producing inconsistent closure and area outcomes.
- **Suggested fix:** In curve traversal, treat `delta_deg = 0` as straight-line movement (distance from `distance_ft`) or explicitly document and validate that such records are unsupported.

## Low

### 23) Zero-valued azimuths are hidden as missing in script outputs
- **Location:** `scripts/test_31_pennbrook_text.py` (`main`), `scripts/extract_sample_deeds.py` (`create_extraction_report`)
- **Issue:** Truthiness checks (`if call.bearing_azimuth_deg_from_north`) suppress valid `0.0°` values and render them as `"(none)"`.
- **Impact:** Bearings at true north are misreported during manual review, obscuring data quality and leading to false assumptions in downstream inspection.
- **Suggested fix:** Compare against `is not None` when rendering azimuth fields.

### 24) Extraction report writes `Date Extracted` from file mtime, not runtime timestamp
- **Location:** `scripts/extract_sample_deeds.py` (`create_extraction_report`)
- **Issue:** `Date Extracted` is populated from `Path(output_file).stat().st_mtime` after report creation.
- **Impact:** The field reflects file metadata timing/mutation rather than a deterministic extraction timestamp.
- **Suggested fix:** Write a runtime `datetime.now(timezone.utc)` stamp at report generation time.
