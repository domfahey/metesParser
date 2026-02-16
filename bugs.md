# Bugs

## Audit Notes (2026-02-14)
- Corrected the non-reproducible fallback-distance claim into a reproducible parser bug.
- Merged duplicate `along` substring reports (old #9 and #13).
- Added a triage metadata checklist to make each bug easier to verify and close.

## Status Update (2026-02-16)
- Baseline audit tickets `#1-24` are marked `fixed`.
- Recent tickets `#25-34` were re-audited on 2026-02-15.
- Open tickets: none remaining.
- Tickets `#35-#48` are fixed as of 2026-02-16. Parser fixes for `#35-#47` landed in commit `902898a`; ticket `#48` was already fixed and then marked in `bugs.md` in commit `743bf33`.
- Verification gates passed after baseline and recent fixes (latest run: 2026-02-16): `make check` and full test suite.

## Error Analysis (2026-02-15)
- Ran full pipeline on 6 sample deeds (18, 24, 31 Pennbrook variants) using GPT-5.2 and Gemini 3 Flash Preview.
- Identified 7 error categories; 3 are new parser bugs (#46-#48), 2 were ground truth corruption (fixed), 2 are working-as-designed.
- Ground truth regenerated for 4618, 10989, and 11191 using GPT-5.2 verified output (commit `3869a81`).


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
- **Status:** `fixed` (verified 2026-02-16)
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
- **Status:** `fixed` (verified 2026-02-16)
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
- **Status:** `fixed` (verified 2026-02-16)
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
- **Status:** `fixed` (verified 2026-02-16)
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
- **Status:** `fixed` (verified 2026-02-16)
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
- **Status:** `fixed` (verified 2026-02-16)
- **Severity:** `low`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/text_parser.py` (`TextParser.extract_along_to_fields`)
- **Issue:** The curve-direction exclusion only guards `to the (left|right)` but also suppresses non-curve phrases like `to the right of` / `to the left of`.
- **Impact:** Endpoint text is lost (`to` becomes empty) in common legal wording such as `"to the right of intersection"`.
- **Expected behavior:** Non-curve `to` clauses should still populate the endpoint field.
- **Actual behavior:** Phrases matching the simple left/right guard are treated as directional and excluded from endpoint extraction.
- **Suggested test:** Assert non-empty `to` for `N 45° E 100 feet to the right of intersection`.
- **Suggested fix:** Expand the guard to only filter true curve-direction tokens (e.g., followed by end-of-phrase/comma/period), not general spatial descriptors like `to the right of`.

### 41) Numeric principal meridian ordinals are not parsed
- **Status:** `fixed` (verified 2026-02-16)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/text_parser.py` (`TextParser.extract_plss_metadata`)
- **Issue:** `pm_pattern` only matches token characters `[A-Z]+`, so ordinals like `6th` or `11TH` are rejected.
- **Impact:** Parcels using ordinal principal meridians (e.g., `"IN 6TH PRINCIPAL MERIDIAN"`) lose PLSS metadata (`principal_meridian=None`), which breaks downstream filtering and reporting.
- **Expected behavior:** Numeric ordinals should be normalized to principal meridian names (`6th Principal Meridian`).
- **Actual behavior:** Such inputs return `None` despite valid format.
- **Suggested test:** Add regression case to assert `TextParser.extract_plss_metadata("IN 6th Principal Meridian")["principal_meridian"] == "6th Principal Meridian"`.
- **Suggested fix:** Extend principal-meridian token pattern to allow ordinal digits/suffixes (e.g., `\d+(?:st|nd|rd|th)?`) alongside alphabetic words before `Principal Meridian`/`P.M.`.

### 42) Curve parser only matches "arc length", not "arc distance"
- **Status:** `fixed` (verified 2026-02-16)
- **Severity:** `high`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/call_extractor.py` (`extract_curve_info`, lines 387 and 431)
- **Minimal input:** `ALONG THE SOUTHEASTERLY LINE OF GREENMOUNT ROAD, ON A CURVE TO THE RIGHT HAVING A RADIUS OF 50.00 FEET, AN ARC DISTANCE OF 36.35 FEET TO A POINT OF TANGENCY`
- **Expected behavior:** Curve call is extracted with `arc_length_ft=36.35`, `radius_ft=50.0`, `curve_dir="right"`.
- **Actual behavior:** Arc length regex only matched `"arc length of"`, not `"arc distance of"`. The curve call failed Pydantic validation (`Curve geometry requires radius_ft and either delta_deg or arc_length_ft`) and was silently dropped.
- **Impact:** Entire curve calls were lost from the traverse, producing incorrect call counts, inflated misclosure, and wrong area calculations. Affected 31 Pennbrook Dr (Book 11191) ground truth extraction.
- **Fix:** Updated both arc length regex patterns to `arc\s+(?:length|distance)\s+(?:of\s+)?(\d+(?:\.\d+)?)`.
- **Commit:** `d99a592`

### 43) Packed-DMS bearings are never parsed from call text
- **Status:** `fixed` (verified 2026-02-16)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/bearing_converter.py` (`BearingConverter.parse_packed_dms`), `src/metesparser/call_extractor.py` (`CallExtractor.extract_direction`, `CallExtractor.extract_single_call`)
- **Issue:** `parse_packed_dms` exists but is not used in the main call parsing pipeline, so bearings written as packed decimal degrees (for example, `N 46.1631° E`) are not recognized as valid bearings.
- **Impact:** These calls are treated as missing/incomplete bearings, then skipped or treated as straight-line approximations, corrupting traversal, closure, and derived area/perimeter when the bearing format appears in source text.
- **Expected behavior:** Packed DMS bearings should be normalized to decimal degrees and parsed into `bearing_quadrant`/`bearing_azimuth_deg_from_north`.
- **Actual behavior:** `extract_direction()` only checks `QUADRANT_PATTERN`; compact values are never converted.
- **Suggested test:** Add regression: `CallExtractor.extract_single_call("N 46.1631° E 100 feet", course=1)` should yield `bearing_azimuth_deg_from_north` equal to `46.275278` and a non-empty `bearing_quadrant`.
- **Suggested fix:** Add packed-DMS pre-parse in `CallExtractor.extract_direction` (or embed it into `BearingConverter.parse_quadrant_bearing`) and route through the same validation/rejection logic as standard quadrant bearings.

### 44) Unit inference helper is never applied in extraction pipeline
- **Status:** `fixed` (verified 2026-02-16)
- **Severity:** `medium`
- **Reproducibility:** `always` (for unitless distances with context hints)
- **Location:** `src/metesparser/text_parser.py` (`TextParser.infer_distance_unit`), `src/metesparser/call_extractor.py` (`CallExtractor.extract_calls`), `src/metesparser/pdf_processor.py` (`PDFProcessor.process_deed_pdf`)
- **Issue:** `infer_distance_unit()` is defined but not used by production code; `process_deed_pdf()` hardcodes `distance_unit="feet"` and `extract_calls()` defaults to feet.
- **Impact:** Deeds that omit explicit units but provide contextual clues (state/year patterns from docs) are interpreted as feet or drop to 0.0, producing incorrect distances and potentially losing calls.
- **Expected behavior:** The extraction path should infer a preferred distance unit once from document context and pass it to call extraction.
- **Actual behavior:** Unit inference is isolated in tests only.
- **Suggested test:** Add regression fixture with unitless distance and strong context (e.g., Texas pre-1900 varas/deed text), assert parsed `distance_ft` matches inferred unit conversion instead of zero.
- **Suggested fix:** Thread document metadata/state/year context into `PDFProcessor.process_deed_pdf` and call `TextParser.infer_distance_unit` before `CallExtractor.extract_calls`.

### 45) Numeric parsing rejects comma-separated distances and curve measurements
- **Status:** `fixed` (verified 2026-02-16)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/text_parser.py` (`TextParser.extract_distance`), `src/metesparser/call_extractor.py` (`CallExtractor.extract_curve_info`, `CallExtractor.extract_distance_alternate`)
- **Issue:** Distance/curve numeric regexes only accept digits and optional decimals (`\d+(?:\.\d+)?`), so valid thousand-formatted values like `1,200 feet`, `3,500.00 ft`, `radius of 10,000 feet`, and `1,000 feet arc length` never match.
- **Expected behavior:** Parser should tolerate thousands separators in metric/length values and normalize them to floats before conversion.
- **Actual behavior:** These calls resolve to `(0.0, "feet")` in `extract_distance` (and miss radius/arc data in curve parsing), so valid geometry is skipped or interpreted as zero-length.
- **Suggested test:** Assert `TextParser.extract_distance("1,200 feet") == (1200.0, "feet")` and that `CallExtractor.extract_single_call("THENCE N 45° E 1,200 feet to a point", course=1)` returns a parsed call with `distance_ft == 1200.0`.
- **Suggested fix:** Introduce a shared numeric normalization helper that strips commas before conversion and reuse it for straight/alternate/cuve distance and radius/arc extraction.

### 46) POB description distances leak into call extraction as phantom courses
- **Status:** `fixed` (verified 2026-02-16)
- **Severity:** `high`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/call_extractor.py` (`CallExtractor.extract_calls`), `src/metesparser/text_parser.py` (`TextParser.split_into_calls`)
- **Minimal input:** `BEGINNING at a point in the Southerly line of Greenmount Road (50 feet wide)...` (18 Pennbrook Dr, Book 11985)
- **Issue:** The POB/preamble text is not stripped before call splitting. Distance values embedded in POB descriptions (road widths like `"50 feet wide"`, offset distances like `"100 feet from the corner"`) are parsed as standalone deed calls.
- **Expected behavior:** POB/preamble text before the first `THENCE` should be excluded from call extraction. Only traverse calls should produce `DeedCall` objects.
- **Actual behavior:** A phantom Course 1 is created from the POB text with `distance_ft=50.0` and no bearing, injecting a zero-azimuth leg into the traverse that inflates call count and corrupts closure/area.
- **Impact:** Observed on 18 Pennbrook (all extraction runs) — pipeline produces 5 calls instead of 4, with Course 1 being a phantom 50-foot call from the road width.
- **Suggested test:** Assert `CallExtractor.extract_calls("BEGINNING at a point in the Southerly line of Greenmount Road (50 feet wide); THENCE S 71°53'10\" E 125.26 feet...")` returns calls starting from the first bearing, not a phantom distance-only call.
- **Suggested fix:** Strip text before the first `THENCE`/`thence` keyword (or first recognized bearing) before passing to `split_into_calls`. Alternatively, reject calls with `distance_ft > 0` but `bearing_azimuth_deg_from_north is None` and no curve data.

### 47) LLM extracts wrong legal description section from multi-section deeds
- **Status:** `fixed` (verified 2026-02-16)
- **Severity:** `high`
- **Reproducibility:** `intermittent` (depends on LLM prompt response)
- **Location:** `src/metesparser/pdf_processor.py` (`PDFProcessor.extract_legal_description`), `prompts/extract_legal_description.yaml`
- **Minimal input:** 24 Pennbrook Dr (Book 11793) — PDF contains both a deed body (short description with bearings) and an Exhibit A (full metes and bounds with 8 calls)
- **Issue:** When a deed PDF contains multiple legal description sections (e.g., deed body + Exhibit A, or main tract + AMENDED description), the LLM extraction prompt does not specify which section to prefer. The LLM may return the deed body (which has fewer calls or abbreviated descriptions) instead of the Exhibit A or survey attachment.
- **Expected behavior:** Extraction should prefer the most complete/detailed legal description, typically the Exhibit A or survey attachment when present.
- **Actual behavior:** For 24 Pennbrook PDF, the LLM extracted the deed body (yielding 2 calls from merged text) instead of Exhibit A (which has 8 distinct calls with full bearings/distances).
- **Impact:** Produces incomplete call sets, wrong call counts, and failed closure. The 24 Pennbrook PDF extraction returned 2 calls instead of 8.
- **Suggested test:** Integration-level test with a multi-section deed confirming the Exhibit A calls are extracted.
- **Suggested fix:** Update `extract_legal_description.yaml` prompt to explicitly instruct the LLM to prefer Exhibit A, survey attachments, or the most detailed metes-and-bounds section when multiple descriptions exist.

### 48) Markdown-based extraction fails to split inline-numbered `thence (N)` calls
- **Status:** `fixed` (verified 2026-02-16)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `src/metesparser/text_parser.py` (`TextParser.split_into_calls`), `src/metesparser/call_extractor.py` (`CallExtractor.extract_calls`)
- **Minimal input:** `thence (1) S 71°53'10" E 125.26 feet; thence (2) S 33°20'00" E 60 feet; thence (3) N 71°53'10" W 125.26 feet...` (24 Pennbrook from markdown extraction)
- **Issue:** When legal description text uses inline parenthesized numbering within a single text block (e.g., `thence (1) ... thence (2) ...`), `split_into_calls` does not split on the `thence` keyword when all calls are concatenated into one line/paragraph. This is distinct from bug #10 (which addressed `(1)` at line start); the issue here is that markdown-parsed text collapses multi-line calls into flowing text where `thence` is the only delimiter.
- **Expected behavior:** Each `thence` keyword should start a new call segment, producing 8 separate calls for 24 Pennbrook.
- **Actual behavior:** All calls are merged into 1-2 segments. Only the first bearing/distance pair is extracted per segment, losing subsequent calls.
- **Impact:** Observed on 24 Pennbrook markdown extraction — produced 2 calls instead of 8, with most bearings/distances lost.
- **Suggested test:** Assert `len(CallExtractor.extract_calls("thence (1) S 71°53'10\" E 125.26 feet; thence (2) S 33°20'00\" E 60 feet; thence (3) N 71°53'10\" W 125.26 feet")) == 3`.
- **Suggested fix:** Add `thence` as a call delimiter in `split_into_calls` (in addition to existing numbered/semicolon patterns). Ensure the split preserves the `thence` keyword in each resulting segment for downstream direction extraction.
