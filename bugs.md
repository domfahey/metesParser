# Bugs

## Audit Notes (2026-02-14)
- Corrected the non-reproducible fallback-distance claim into a reproducible parser bug.
- Merged duplicate `along` substring reports (old #9 and #13).
- Added a triage metadata checklist to make each bug easier to verify and close.

## Status Update (2026-02-15)
- Baseline audit tickets `#1-24` are marked `fixed`.
- Recent tickets `#25-34` were re-audited on 2026-02-15.
- Open tickets: none.
- Verification gates passed after baseline and recent fixes (latest run: 2026-02-15): `make check` and full test suite.


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
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `high`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/text_parser.py` (`TextParser.extract_distance`)
- **Issue:** The distance regex accepts `feet`, `ft`, and pluralized units, but not singular `foot`.
- **Impact:** Calls written as `1 foot` (or `2 foot`) parse as distance `0`, so valid lines can be dropped.
- **Suggested fix:** Add `foot` to the regex unit pattern and normalize to `feet`.

### 2) PLSS range direction can be misdetected as East for West ranges
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `high`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/text_parser.py` (`TextParser.extract_plss_metadata`)
- **Issue:** West range is inferred with `"E" in range_match.group(0)`, which is true for `WEST`.
- **Impact:** `W` ranges can be silently flipped to `E`, corrupting legal metadata.
- **Suggested fix:** Parse explicit east/west tokens via capture groups or token-level regex checks.

### 3) OpenAI client drops requested response format hints
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `high`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/llm_clients.py` (`OpenAIClient.generate_text`, `OpenAIClient.generate_text_with_pdf`)
- **Issue:** `response_mime_type` is deleted and never forwarded to OpenAI requests.
- **Impact:** JSON-required extraction paths can receive non-JSON text and fail downstream parsing.
- **Suggested fix:** Map `response_mime_type` to OpenAI response-format controls and enforce JSON when requested.

## Medium

### 4) Alternate distance parser misses normal apostrophe forms but matches malformed concatenations
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/call_extractor.py` (`CallExtractor.extract_distance_alternate`)
- **Issue:** Pattern `(?:'|feet|ft)\b` does not match common prose like `125.26' along ...`, but does match malformed strings like `30'to`.
- **Impact:** Produces false negatives on legitimate apostrophe-foot notation and false positives on malformed/OCR-collapsed tokens.
- **Suggested fix:** Handle apostrophe-foot with explicit trailing delimiter rules and guard against angle-token artifacts.

### 5) Polygon area formula assumes closed points list and omits wrap-around segment
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/closure_checker.py` (`ClosureChecker.calculate_area`)
- **Issue:** Shoelace loop uses `for i in range(n - 1)`, skipping the final wrap edge unless input already repeats start point.
- **Impact:** Non-repeated point lists produce inaccurate area values and warnings.
- **Suggested fix:** Include wrap-around with modulo indexing (`j = (i + 1) % n`) or explicitly enforce repeated first point.

### 6) `metadata` argument in `calls_to_csv` is silently ignored
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/csv_builder.py` (`CSVBuilder.calls_to_csv`)
- **Issue:** Method accepts `metadata` but intentionally does nothing with it.
- **Impact:** Callers may assume metadata persistence that never occurs.
- **Suggested fix:** Persist metadata deterministically (CSV preamble/sidecar) or remove the argument.

### 7) Curve model inconsistently rejects zero-degree curve data
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/models.py` (`DeedCall.delta_deg`, `DeedCall.arc_length_ft`) and curve logic using truthiness checks
- **Issue:** `DeedCall` requires `delta_deg > 0` / `arc_length_ft > 0`, while curve math utilities support `delta_deg == 0`.
- **Impact:** Zero-angle curve representations are rejected or skipped inconsistently.
- **Suggested fix:** Harmonize constraints around mathematically valid zero values and replace truthy checks with `is not None` where needed.

### 8) Parallelism check ignores azimuth wrap-around at North
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/closure_checker.py` (`ClosureChecker.check_parallelism`)
- **Issue:** Uses raw `abs(curr_az - prev_az)` without circular normalization.
- **Impact:** Bearings near `0°/360°` can trigger false parallelism warnings.
- **Suggested fix:** Compare with circular delta: `min(diff, 360 - diff)`.

### 9) `extract_along_to_fields` matches substrings like `"alongside"`
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/text_parser.py` (`TextParser.extract_along_to_fields`)
- **Issue:** Detection uses `find("along")` instead of standalone keyword matching.
- **Impact:** Non-clause words can be parsed as `along` clauses and corrupt metadata.
- **Suggested fix:** Use word-boundary token matching (`\balong\b`) and parse clause boundaries explicitly.

### 10) Parenthesized or bare-numbered calls are not split into separate calls
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/text_parser.py` (`TextParser.split_into_calls`)
- **Issue:** Splitter recognizes `1.` but not `(1)` or `1)` call numbering styles.
- **Impact:** Multi-call descriptions can collapse into one parsed call.
- **Suggested fix:** Extend numbering regexes to include `(n)` and `n)` forms.

### 11) Exception splitting triggers on incidental `ALSO`/`INCLUDING`
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/text_parser.py` (`TextParser.split_exception_clauses`)
- **Issue:** Any standalone `ALSO`/`INCLUDING` is treated as a tract boundary.
- **Impact:** Main tract text can be split incorrectly in normal prose.
- **Suggested fix:** Restrict split triggers to stronger clause-start patterns.

### 12) Decimal-degree curve deltas are ignored
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/call_extractor.py` (`CallExtractor.extract_curve_info`)
- **Issue:** Delta fallback parser captures integer degrees only (`(\d+)`).
- **Impact:** Inputs like `delta of 90.5 degrees` lose delta data; fallback distances can become wrong.
- **Suggested fix:** Accept decimal degree/minute formats and compute arc length when radius+delta are available.

### 13) Curve direction phrase (`to the right/left`) is misread as endpoint text
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/text_parser.py` (`TextParser.extract_along_to_fields`)
- **Issue:** `to` parsing does not distinguish endpoint `to` from curve-direction phrase `to the right/left`.
- **Impact:** Endpoint metadata can be replaced with directional junk text.
- **Suggested fix:** Exclude structural direction phrase tokens from endpoint extraction.

### 14) Double-entry validation misses several curve mismatches
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/closure_checker.py` (`ClosureChecker.compare_double_entry`)
- **Issue:** Curve comparison checks direction and sometimes radius, but omits delta/arc/chord mismatches and asymmetric presence.
- **Impact:** Non-equivalent curve entries can be reported as matching.
- **Suggested fix:** Compare all meaningful curve fields and treat asymmetric curve data as discrepancy.

### 15) Prompt loading path is hard-coded to source-checkout layout
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/pdf_processor.py` (`PDFProcessor.__init__`)
- **Issue:** Prompts path assumes repository-relative `prompts/` location.
- **Impact:** Installed-package layouts can fail at runtime with missing prompt files.
- **Suggested fix:** Load prompts via package resources and include them as package data.

### 16) `extract_sample_deeds.py` points to non-existent `scripts/sample_deeds`
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `scripts/extract_sample_deeds.py` (`SAMPLE_DEEDS_DIR`)
- **Issue:** Uses `Path(__file__).parent / "sample_deeds"` instead of repo-root `sample_deeds/`.
- **Impact:** Script skips every configured sample PDF.
- **Suggested fix:** Resolve from project root (`Path(__file__).parent.parent / "sample_deeds"`).

### 17) Ground-truth `notes` field records script mtime, not generation time
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `scripts/generate_ground_truth.py` (`generate_ground_truth`, `notes` field)
- **Issue:** Notes timestamp uses `Path(__file__).stat().st_mtime`.
- **Impact:** Provenance timestamp reflects script file edit time, not when output was generated.
- **Suggested fix:** Use runtime UTC timestamp (`datetime.now(timezone.utc).isoformat()`).

### 18) Zero-degree curve distances are dropped as non-calls
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/call_extractor.py` (`CallExtractor.extract_single_call`)
- **Issue:** Arc length `0.0` overrides parsed distance, then `distance_ft <= 0.0` causes call drop.
- **Impact:** Zero-deflection curve cases can be silently lost.
- **Suggested fix:** Do not override with non-positive arc length; preserve original line distance for `delta_deg == 0`.

### 19) Root package does not expose documented public classes
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/__init__.py` and docs in `README.md`, `docs/API.md`
- **Issue:** Package root exports only `__version__`, but docs show root-level imports.
- **Impact:** Documented import examples fail with `ImportError`.
- **Suggested fix:** Re-export documented public classes in `__init__.py` or update docs to module-level imports.

### 20) Incomplete curve specs crash call extraction
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/call_extractor.py` (`CallExtractor.extract_single_call`, `CallExtractor.extract_calls`)
- **Issue:** Curve parsing can produce incomplete curve metadata (e.g., radius only or delta only), which fails `DeedCall` validation.
- **Impact:** `ValidationError` is raised and bubbles out of `extract_calls`, aborting extraction of the whole description instead of skipping the bad segment.
- **Suggested fix:** Catch validation/parse errors per-call, emit a warning, and continue parsing remaining calls (or preserve malformed text for audit).

### 21) Curves with `radius` + `arc_length` but no `delta` are not traversed
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/call_extractor.py` (`extract_single_call`), `src/metesparser/closure_checker.py` (`ClosureChecker.compute_traverse`)
- **Issue:** `distance_ft` is set from `arc_length_ft`, but traversal only moves for curves when `call.delta_deg` is present.
- **Impact:** The segment is included in call output (and perimeter may include `arc_length`), but compute-traverse area/closure ignores it, producing inconsistent geometry.
- **Suggested fix:** Derive missing `delta_deg` when possible (`arc_length` + `radius`) or at minimum include an approximation branch for radius+arc-length curves in traversal.

### 22) Zero-deflection (`Δ = 0`) curves are treated as zero-move in traverse
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/closure_checker.py` (`ClosureChecker.compute_traverse`), `src/metesparser/call_extractor.py` (`CallExtractor.extract_single_call`), `src/metesparser/bearing_converter.py` (`BearingConverter.compute_curve_endpoint`)
- **Issue:** `compute_traverse` routes any curve call with `curve_dir/radius/delta` to `compute_curve_endpoint`, which computes an endpoint by chord length. For `delta_deg = 0`, chord length is `0`, so the curve advances no distance even if the call carried a positive `distance_ft` fallback for arc/line handling.
- **Impact:** Valid zero-deflection curve records are over-traversed (understated geometry) while perimeter logic can still add the call distance, producing inconsistent closure and area outcomes.
- **Suggested fix:** In curve traversal, treat `delta_deg = 0` as straight-line movement (distance from `distance_ft`) or explicitly document and validate that such records are unsupported.

## Low (Fixed)

### 23) Zero-valued azimuths are hidden as missing in script outputs
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `low`
- **Reproducibility:** `always`
- **Location:** `scripts/test_31_pennbrook_text.py` (`main`), `scripts/extract_sample_deeds.py` (`create_extraction_report`)
- **Issue:** Truthiness checks (`if call.bearing_azimuth_deg_from_north`) suppress valid `0.0°` values and render them as `"(none)"`.
- **Impact:** Bearings at true north are misreported during manual review, obscuring data quality and leading to false assumptions in downstream inspection.
- **Suggested fix:** Compare against `is not None` when rendering azimuth fields.

### 24) Extraction report writes `Date Extracted` from file mtime, not runtime timestamp
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `low`
- **Reproducibility:** `always`
- **Location:** `scripts/extract_sample_deeds.py` (`create_extraction_report`)
- **Issue:** `Date Extracted` is populated from `Path(output_file).stat().st_mtime` after report creation.
- **Impact:** The field reflects file metadata timing/mutation rather than a deterministic extraction timestamp.
- **Suggested fix:** Write a runtime `datetime.now(timezone.utc)` stamp at report generation time.

## Recent Tickets

### 25) Export CLI command was advertised but failed
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/cli.py` (`main`)
- **Issue:** CLI exposed an `export` subcommand that always failed.
- **Impact:** Users hit a guaranteed CLI failure path.
- **Suggested fix:** Remove/disable the command until implemented.

### 26) Perimeter undercounted zero-deflection curve calls
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/closure_checker.py` (`calculate_perimeter`)
- **Issue:** Zero-arc curve entries could contribute `0.0` instead of effective line distance.
- **Impact:** Perimeter could diverge from traverse behavior.
- **Suggested fix:** Use `distance_ft` when arc length is non-positive.

### 27) PLSS township parser treated many SOUTH entries as NORTH
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/text_parser.py` (`extract_plss_metadata`)
- **Issue:** Direction detection relied on broad string containment.
- **Impact:** SOUTH township metadata could be silently flipped.
- **Suggested fix:** Parse direction from an explicit capture token.

### 28) POC extraction missed explicit `POB` abbreviations
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `low`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/text_parser.py` (`extract_poc`)
- **Issue:** `extract_poc` did not recognize `POB` abbreviation in its downstream detector.
- **Impact:** Distinct POC metadata could be dropped.
- **Suggested fix:** Include `POB` in `pob_pattern`.

### 29) Principal meridian parser truncated multi-word names
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `low`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/text_parser.py` (`extract_plss_metadata`)
- **Issue:** Regex captured only one token before meridian marker.
- **Impact:** Multi-word meridian names were truncated.
- **Suggested fix:** Capture full token sequence before meridian marker.

### 30) Closure status ignored warning context
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/models.py` (`ClosureResult.get_closure_status`)
- **Issue:** Status classification ignored non-empty warnings.
- **Impact:** Warned results could still report top-tier status.
- **Suggested fix:** Return warning-aware state when warnings exist.

### 31) Unknown distance units silently defaulted to feet
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/models.py` (`ConversionFactors.convert_to_feet`)
- **Issue:** Unsupported unit strings fell through to factor `1.0`.
- **Impact:** Silent numeric corruption risk.
- **Suggested fix:** Raise `ValueError` for unsupported units.

### 32) Curve parser ignored degree-minute text tokens
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/call_extractor.py` (`CallExtractor.extract_curve_info`)
- **Issue:** Delta parsing did not consistently consume textual minute/second tokens.
- **Impact:** Curve deltas could lose precision.
- **Suggested fix:** Parse minute/second textual tokens as decimal degrees.

### 33) OCR/no-degree DMS apostrophe can be misread as distance feet
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `medium`
- **Reproducibility:** `intermittent`
- **Location:** `src/metesparser/call_extractor.py` (`CallExtractor.extract_distance_alternate`)
- **Minimal input:** `N 45 30' along the north line`
- **Expected behavior:** `30'` should be interpreted as bearing minutes context, not a distance.
- **Actual behavior:** Alternate distance parser returns `30.0` feet for this OCR-style no-degree-symbol pattern.
- **Impact:** Injects false non-zero distance and can skew closure/traverse.
- **Suggested test:** Unit coverage for no-degree-symbol DMS patterns followed by `along`/`to` text.
- **Suggested fix:** Add stronger bearing-context guards before apostrophe-distance fallback.

### 34) Decimal textual curve minutes precision gap
- **Status:** `fixed` (verified 2026-02-15)
- **Severity:** `low`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/call_extractor.py` (`CallExtractor.extract_curve_info`)
- **Issue:** Decimal-minute textual tokens needed explicit float parsing.
- **Impact:** Could understate curve deltas in textual minute notation.
- **Suggested fix:** Accept decimal minute/second tokens and normalize to decimal degrees.

### 35) Prompt formatting crashes when extracted text contains braces
- **Status:** `open`
- **Severity:** `high`
- **Reproducibility:** `always` (for any legal description text containing `{` or `}`)
- **Location:** `src/metesparser/pdf_processor.py` (`extract_legal_description`, `normalize_legal_description`, `extract_calls_ai`)
- **Issue:** These methods build prompts via `str.format(...)` using raw extracted legal description text as a substitution value.
- **Impact:** Braces in source text are interpreted as format fields and trigger `KeyError`/`IndexError`, aborting extraction even when OCR is otherwise usable.
- **Expected behavior:** Any `{...}` characters in extracted text should be treated as plain text and safely embedded in the user prompt.
- **Actual behavior:** Processing fails at prompt render time with a formatting exception before LLM submission.
- **Suggested test:** Unit test that monkeypatches an injected client returning `document_text="... {TEST} ..."` and asserts `extract_legal_description`/`normalize_legal_description` do not raise and call the client once.
- **Suggested fix:** Use escaped template interpolation (`{`/`}` doubling), `str.format_map` with explicit context, or `.replace` placeholder assembly that avoids interpreting user-supplied text as format fields.

### 36) Bearing-minute apostrophes after `°` can be parsed as distances
- **Status:** `open`
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/call_extractor.py` (`extract_distance_alternate`)
- **Issue:** The alternate distance fallback only blocks north/south no-degree DMS forms, but does not block already formatted `"°` bearings like `N 45°30'`.
- **Impact:** Bearing minute components can be misinterpreted as a 30-feet/30-meter distance, creating inflated or phantom calls and corrupting traverse/closure.
- **Expected behavior:** `N 45°30' along the north line` should yield no alternate-distance fallback value.
- **Actual behavior:** `extract_distance_alternate` returns `30.0` for the minutes token, and call extraction continues with a bogus distance.
- **Suggested test:** Add unit test asserting `CallExtractor.extract_single_call("N 45°30' along the north line", course=1)` does not pick up distance from the apostrophe-minutes term (distance remains 0 when no explicit distance units exist).
- **Suggested fix:** Extend the bearing-context guard to treat any minute token adjacent to a quadrant bearing (`N|S ... °...`) as non-distance.

### 37) Distance parser drops many valid units
- **Status:** `open`
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/text_parser.py` (`TextParser.extract_distance`)
- **Issue:** Linear distance parsing supports only feet/ft and a few legacy survey units, but ignores project-recognized units like `varas`, `arpents`, `toises`, `furlongs`, `meters`, `miles`, `engineer_chains`, and `engineer_links`.
- **Impact:** Valid calls using those units are treated as `(0.0, 'feet')`, so geometry lines may be dropped or silently reduced to zero distance.
- **Expected behavior:** Units listed in `DistanceUnit` should be parsed and converted via `ConversionFactors`.
- **Actual behavior:** Non-foot units are silently ignored at extraction time.
- **Suggested test:** Add fixtures for each unsupported unit in `extract_distance` and assert non-zero `distance_ft` is produced after conversion.
- **Suggested fix:** Extend unit regex/normalization in `extract_distance` to include additional supported unit families and aliases.

### 38) Curve parsing ignores unit qualifiers for radius/arc length
- **Status:** `open`
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/call_extractor.py` (`extract_curve_info`)
- **Issue:** Curve `radius` and `arc length` extraction patterns match numbers only and do not capture/convert unit tokens.
- **Impact:** Curved lines expressed with non-foot units (`meters`, `chains`, etc.) are interpreted as feet and materially skew closure, area, and endpoint geometry.
- **Expected behavior:** Curve geometry units should be normalized using the same unit conversion path as straight distances.
- **Actual behavior:** Units are dropped and values are interpreted as feet without warning.
- **Suggested test:** Add non-foot curve fixture (for example, `radius of 50 meters`) and assert normalized converted values flow into traverse checks.
- **Suggested fix:** Parse optional units for radius/arc, validate against `ConversionFactors`, and convert before math.

### 39) Curve consistency skips radius+arc-only curves
- **Status:** `open`
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/closure_checker.py` (`check_curve_consistency`)
- **Issue:** Calls with `radius_ft` and `arc_length_ft` but no `delta_deg` are excluded from consistency checks.
- **Impact:** A malformed radius/arc pair can pass closure verification as consistent even when the values are geometrically incompatible.
- **Expected behavior:** Radius+arc-only curves should be validated by deriving the implied delta and checking arc math.
- **Actual behavior:** `check_curve_consistency` returns `True` for such calls without validating `arc_length_ft` vs `radius_ft`.
- **Suggested test:** Build a `DeedCall` with matching radius+arc but intentionally mismatched geometry and assert curve consistency fails.
- **Suggested fix:** Derive `delta_deg` from `arc_length_ft / radius_ft` when missing and run the same consistency checks used for explicit deltas.

### 40) `to` endpoint parsing drops `to the right/left of` clauses
- **Status:** `open`
- **Severity:** `low`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/text_parser.py` (`TextParser.extract_along_to_fields`)
- **Issue:** The curve-direction exclusion only guards `to the (left|right)` but also suppresses non-curve phrases like `to the right of` / `to the left of`.
- **Impact:** Endpoint text is lost (`to` becomes empty) in common legal wording such as `"to the right of intersection"`.
- **Expected behavior:** Non-curve `to` clauses should still populate the endpoint field.
- **Actual behavior:** Phrases matching the simple left/right guard are treated as directional and excluded from endpoint extraction.
- **Suggested test:** Assert non-empty `to` for `N 45° E 100 feet to the right of intersection`.
- **Suggested fix:** Expand the guard to only filter true curve-direction tokens (e.g., followed by end-of-phrase/comma/period), not general spatial descriptors like `to the right of`.
