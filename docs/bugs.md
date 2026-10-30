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

## Code Review (2026-10-29)

Bug review of changes merged 2026-10-22 to 2026-10-29 (PRs #43–#58 and `feat/claude-chat-skill`), split by PR group across read-only reviewers. Each `always` ticket was reproduced by the reviewer with a throwaway test against existing fixtures; `unconfirmed` tickets come from code trace only. Reproductions for #49, #50, #52, #67, #69 and #70 were re-run independently on `main`. No ticket fabricates bearings, grants verified-export eligibility, or promotes advisory status.

**Fix status (2026-10-29):** #49–#73 were fixed test-first (red regression test, then fix) on `fix/code-review-2026-10-29`; #56 and #70 are `partial` with the remaining scope noted. #74 is a new gap found during the #62 fix. Combined-branch gates: packages + plugin 1804 passed / 27 skipped; root 1648 passed / 23 skipped (94.30% coverage); `ruff check` and `mypy src/metesparser` clean.

**PR #60 review fixes (2026-10-29):** regressions found in review were fixed test-first on the same branch: compound-distance joining limited to known sub-unit pairs (#70); derived-tangent note kept alongside meander/approximate notes (#62); tract headings after `:`/`;` and reference-word rejection (#69); bad chord bearings tracked per call, not course number (#72); failed tracts listed in a "Not verified" section of `verification.txt` (#71); symlinks below the bundle root rejected for absolute overrides (#57); EXIF rejection moved to raster import so saved bundles still load (#64); delivery exporter bumped to `delivery-2` with `delivery-1` replay against a committed golden package (#51/#53); area-of-use checked for delivery GeoJSON and out-of-area map layers omitted instead of failing the scene (#68).

### 49) Parallelism check blocks verification when course 1 "continues" a line
- **Status:** `fixed` (2026-10-29, `685a7fd`)
- **Severity:** `high`
- **Reproducibility:** `always`
- **Location:** `packages/mp-verify/src/mp_verify/checks.py` (`parallel_blocked` in `build_verification_checks`); monolith `closure_checker.py` uses the same builder. Introduced in PR #46.
- **Minimal input:** Closed 100 ft square (misclosure ~2e-14 ft, no warnings) with course 1 `along="continuing along Pennbrook Drive"`.
- **Expected behavior:** `is_fully_verified()` is `True`, as it is with `along="Pennbrook Drive"`.
- **Actual behavior:** `is_fully_verified()` is `False` with `[('parallelism', 'blocked')]`; verified CSV export is refused.
- **Impact:** Common deeds whose first main course continues the tie-in line ("thence continuing along…") can never be geometry-verified. Regression: the legacy `check_parallelism` skipped `i == 0`.
- **Suggested fix:** Skip (or mark `not_applicable`) the first course when there is no previous main course to compare.

### 50) `export-review` crashes when an optional derived layer fails and GeoJSON is requested
- **Status:** `fixed` (2026-10-29, `ca3cad4`)
- **Severity:** `high`
- **Reproducibility:** `always`
- **Location:** `packages/mp-review/src/mp_review/delivery.py:500` (`_geojson`), with `prepare_delivery` (lines 414–418) and `publish_delivery` (line 673). Introduced in PR #55.
- **Minimal input:** PLSS delivery request with `formats=["svg","geojson"]` plus a second, non-required PLSS layer with an invalid id.
- **Expected behavior:** The failed optional layer is recorded as an omission and the package publishes.
- **Actual behavior:** A bare `next(...)` over `snapshot.derived_sources` raises `StopIteration`, which neither `publish_delivery` nor the CLI catches. `pending.json` is left behind, so a corrected retry under the same `id` fails with an immutable-artifact conflict.
- **Suggested fix:** Use `next(..., None)` and skip omitted layers; clean up or reuse `pending.json` on failure.

### 51) DXF and GeoJSON silently drop presentation rotation
- **Status:** `fixed` (2026-10-29, `10c993e`)
- **Severity:** `high`
- **Reproducibility:** `always`
- **Location:** `packages/mp-review/src/mp_review/delivery.py:180-187`, `packages/mp-export/src/mp_export/delivery.py:342-435`. Introduced in PR #55.
- **Minimal input:** Delivery request with `presentation_rotation_deg=90`, no labels, `formats=["svg","dxf"]`.
- **Expected behavior:** All formats share the orientation, or the omission is disclosed.
- **Actual behavior:** SVG/PDF are rotated via `_presentation`; DXF/GeoJSON are not. The rotation omission is only recorded when `request.labels` is non-empty, so `snapshot.omissions == ()` and `inspect-delivery` reports the package as consistent.
- **Suggested fix:** Always record the omission when rotation is non-zero and a format ignores it (or apply rotation consistently where meaningful).

### 52) Schema 1.2 revisions reject added calls and tombstones
- **Status:** `fixed` (2026-10-29, `3a1c0d3`)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `packages/mp-review/src/mp_review/revisions.py:503`. Introduced in PR #53/#54.
- **Minimal input:** The existing `added()` fixture in `test_revision_store.py` with only `schema_version` changed to `"1.2"`.
- **Expected behavior:** Parses like schema 1.1 (line 467 already accepts 1.2 for structured edits).
- **Actual behavior:** `ValueError: Added call/tombstone requires schema 1.1 and a distinct stable identity`.
- **Impact:** Corridor revisions must be 1.2 and revisions are full-state, so inserted calls and corridors can never coexist; after a corridor revision no later revision can keep or add an inserted call.
- **Suggested fix:** `revision.schema_version not in ("1.1", "1.2")`.

### 53) Corridor GeoJSON exterior rings are wound clockwise
- **Status:** `fixed` (2026-10-29, `7e10155`)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `packages/mp-review/src/mp_review/delivery_sources.py:370-376`; PLSS `_vector_feature` uses the same unchecked path (not measured). Introduced in PR #55.
- **Minimal input:** Existing rotated-placement corridor fixture.
- **Expected behavior:** Exterior rings counterclockwise per RFC 7946 §3.1.6.
- **Actual behavior:** `drawing.geojson` ring has signed area −3.7e-08 (clockwise; closed, 405 vertices).
- **Impact:** Strict GeoJSON consumers may treat the polygon as a hole or reject it.
- **Suggested fix:** Normalize ring orientation (exterior CCW, holes CW) before serialization.

### 54) `inspect-artifacts` crashes on a tampered plot CSV
- **Status:** `fixed` (2026-10-29, `5432338`)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `packages/mp-review/src/mp_review/artifact_inspect.py:585` (via `plot.py:107-111`); handler at lines 186–191. Introduced in PR #51.
- **Minimal input:** Plot bundle with `1,"a"b,` appended to `plot/source.csv` (hash not updated); `inspect_artifacts(root, requested_stage="plot")`.
- **Expected behavior:** Plot node reported stale/invalid; CLI exits 1 or 2.
- **Actual behavior:** `_csv.Error: ',' expected after '"'` escapes (`csv.Error` is not a `ValueError`); CLI prints a traceback.
- **Suggested fix:** Catch `csv.Error` in replay and map it to an invalid node.

### 55) `inspect-artifacts` crashes on a non-object dashboard render manifest
- **Status:** `fixed` (2026-10-29, `eb83e62`)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `packages/mp-review/src/mp_review/artifact_inspect.py:929-931`. Introduced in PR #51.
- **Minimal input:** Valid dashboard bundle with `dashboard/render-manifest.json` replaced by `[]`.
- **Expected behavior:** Dashboard node `invalid`.
- **Actual behavior:** `AttributeError: 'list' object has no attribute 'get'` at line 931.
- **Suggested fix:** Type-check the loaded manifest before `.get(...)`.

### 56) Review and plot displays are not invalidated by their producers
- **Status:** `partial` (2026-10-29, `e3cb15b`) — Producer dependencies added (display is blocked when its review/plot is invalid). Renderer-fingerprint check not added: review and plot manifests record no renderer fingerprint.
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `packages/mp-review/src/mp_review/artifact_inspect.py:408` (`review_display`) and `:518` (`plot_display`). Introduced in PR #51.
- **Minimal input:** Edit `review-a/calls.json` (distance +1) and rewrite its manifest hash.
- **Expected behavior:** `review.html` is blocked/stale once the review node is invalid, as the dashboard display is (line 653).
- **Actual behavior:** Review node is `invalid (replay_mismatch)` but `review.html` stays `present_valid` with no `dependency_ids`. Stage-level status is still invalid, so per-artifact output is what misleads. These displays also lack the renderer-fingerprint check used for dashboard (line 932) and online map (line 1048).
- **Suggested fix:** Add the producing node to `dependency_ids` and a renderer-fingerprint check.

### 57) `validate-source` rejects in-bundle overrides when the root path is a symlink
- **Status:** `fixed` (2026-10-29, `b067f8d`)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `packages/mp-review/src/mp_review/source_handoff.py:104-116` (with `:536-542`). Introduced in PR #49.
- **Minimal input:** Fixture bundle reached through a symlinked root (any `/tmp/...` path on macOS) with `acquisition=root/"source-acquisition.json"`.
- **Expected behavior:** Same result as the default paths (`needs_review`).
- **Actual behavior:** `error` (exit 2) with `unsafe_path: Reference is outside the explicit bundle root.` The root is resolved; the override is not.
- **Suggested fix:** Resolve the override before the containment check.

### 58) Unreadable source records are reported as `missing`
- **Status:** `fixed` (2026-10-29, `283cab5`)
- **Severity:** `low`
- **Reproducibility:** `always`
- **Location:** `packages/mp-review/src/mp_review/source_handoff.py:242-262` (`_Validator.record`). Introduced in PR #49.
- **Minimal input:** `validate_source_bundle(root, acquisition=Path("bad.json"))` where the file contains `{not json` (or invalid UTF-8).
- **Expected behavior:** Section `invalid` with `path`/`sha256`.
- **Actual behavior:** Overall `error`, but `acquisition == {"status": "missing"}`.
- **Suggested fix:** Set `self.result[kind]` to `invalid` on decode/parse failure, like the other branches.

### 59) Deeply nested JSON crashes `inspect-artifacts`
- **Status:** `fixed` (2026-10-29, `8f408ae`)
- **Severity:** `low`
- **Reproducibility:** `always` (hostile input only)
- **Location:** `packages/mp-review/src/mp_review/artifact_inspect.py:127` and `_finite_json` (line 132). Introduced in PR #51.
- **Minimal input:** `plot-manifest.json` containing `"[" * 100000 + "]" * 100000`.
- **Expected behavior:** `invalid_json`.
- **Actual behavior:** Uncaught `RecursionError`.
- **Suggested fix:** Catch `RecursionError` in `load` and report `invalid_json`.

### 60) Non-UTF-8 transcript yields a misleading selection identity entry
- **Status:** `fixed` (2026-10-29, `68d6777`)
- **Severity:** `low`
- **Reproducibility:** `unconfirmed` (code trace)
- **Location:** `packages/mp-review/src/mp_review/source_handoff.py:375-389` and `:608-614`. Introduced in PR #49.
- **Issue:** `acquisition()` returns `None` for non-UTF-8 transcript bytes, so the selection `transcript_sha256` check records `identity_unavailable`/`unverifiable` with `actual_sha256: null` although the bytes were already hashed. Overall status is still error/needs_review.
- **Suggested fix:** Pass the computed hash through independently of decoding.

### 61) `run-chat.py --setup` cannot repair a corrupted cached uv
- **Status:** `fixed` (2026-10-29, `2b22288`)
- **Severity:** `low`
- **Reproducibility:** `unconfirmed` (code trace; needs a built chat archive)
- **Location:** `plugins/metesparser-chat/scripts/run-chat.py:176-182` and `:100-108`. Introduced on `feat/claude-chat-skill`.
- **Issue:** `verified_cached_uv()` raises on a hash mismatch before the `setup and not --offline` reinstall branch, so with no uv on PATH and a modified `~/.cache/metesparser/chat-tools/uv-0.9.6/<platform>/bin/uv`, `--setup` returns `chat_runtime_error` instead of reinstalling.
- **Suggested fix:** On `--setup`, treat a hash mismatch as a cache miss and reinstall.

### 62) "chord bearing" phrasing is stored as the tangent bearing
- **Status:** `fixed` (2026-10-29, `b626023`)
- **Severity:** `high`
- **Reproducibility:** `always`
- **Location:** `packages/mp-parse/src/mp_parse/calls.py` (curve call parsing). Predates the 2026-10-22 window; surfaced while reviewing PR #47.
- **Minimal input:** `a curve to the right … radius 50 … central angle 90° … chord bearing North 45° East 70.71 feet` in an otherwise closing 4-call parcel.
- **Expected behavior:** `chord_bearing="N 45° E"`, tangent bearing derived; parcel closes.
- **Actual behavior:** N 45° E is stored as `bearing_quadrant`/`bearing_azimuth_deg_from_north` and `chord_bearing` is `None`; both the plot and `verify_closure` report a 54.12 ft misclosure.
- **Impact:** Valid curved parcels fail closure. Feature #8 handles "chord of which bears…" but not "chord bearing …".
- **Suggested fix:** Recognize `chord bearing` / `chord bears` phrasings in `extract_curve_info` and keep the monolith `call_extractor.py` in sync.

### 63) Plot rejects curves whose tangent and chord bearings differ by rounding
- **Status:** `fixed` (2026-10-29, `2dfc51f`)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `packages/mp-verify/src/mp_verify/plot.py:77-80` (`_arc`); shared by plot and dashboard via `_build_geometry`. Introduced in PR #47.
- **Minimal input:** N 0° E 50 ft, then a right curve R=100, Δ=45°15'15", tangent 0°, chord stated N 22°37'38" E (true Δ/2 = 22°37'37.5"), then a closing line.
- **Expected behavior:** Complete plot; `verify_closure` closes the same calls at 0.00019 ft.
- **Actual behavior:** Plot is `partial` with `inconsistent tangent and chord angular evidence`; every later call is `unpositioned`, with no area or closure gap.
- **Impact:** The 1e-6° (~0.004") agreement tolerance is far tighter than whole-second deed precision, so ordinary curves render as truncated prefixes.
- **Suggested fix:** Use a tolerance matched to stated precision (e.g. 1–2 arcseconds) or a linear endpoint tolerance.

### 64) Raster overlays ignore EXIF orientation
- **Status:** `fixed` (2026-10-29, `c491ccb`)
- **Severity:** `medium`
- **Reproducibility:** `unconfirmed` (code trace; no browser repro)
- **Location:** `packages/mp-review/src/mp_review/raster_registration.py:116-128`, `packages/mp-export/src/mp_export/dashboard_html.py` (`_raster_svg`). Introduced in PR #47.
- **Issue:** Width/height come from raw `image.size`/header parsing, but browsers apply EXIF orientation when drawing the SVG `<image preserveAspectRatio="none">`. A JPEG with Orientation=6 is drawn rotated into the raw W×H box, stretched, and no longer matches the affine-registered controls; nothing rejects or normalizes orientation.
- **Suggested fix:** Reject non-default EXIF orientation, or normalize with `ImageOps.exif_transpose` before registration and embedding.

### 65) Corridor arc pieces fail on a floating-point end fraction
- **Status:** `fixed` (2026-10-29, `cf5017d`)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `packages/mp-verify/src/mp_verify/corridor.py:156` (`_pieces`, `f1 = (b - stations[i]) / lengths[i]`); raised by `arc_point` in `plot.py:396`. Introduced in PR #52.
- **Minimal input:** Centerline of a 100 ft line at azimuth 0 followed by a tangent right arc (R=100, Δ=90°), one step width row (left 20, right 10).
- **Expected behavior:** Corridor polygon computed (the arc alone, or a 50 ft line + the same arc, works).
- **Actual behavior:** `f1 == 1.0000000000000002`; result `availability=unsupported` with `fraction must be in [0,1]`. On line pieces the same overshoot silently extrapolates.
- **Suggested fix:** Clamp the fraction to `[0, 1]`, or set `f1 = 1.0` when `b == stations[i + 1]`.

### 66) `diagnose-closure` exits 1 on deeply nested request JSON
- **Status:** `fixed` (2026-10-29, `3a9a6e3`)
- **Severity:** `low`
- **Reproducibility:** `always` (malformed input only)
- **Location:** `packages/mp-review/src/mp_review/diagnostics.py:49` and `:81`. Introduced in PR #50.
- **Minimal input:** Request file of 100000 `[` followed by 100000 `]`.
- **Expected behavior:** Status `error`, exit 2 (as `compare-descriptions` does for the same file).
- **Actual behavior:** Uncaught `RecursionError` traceback with exit 1, indistinguishable from `needs_review`.
- **Suggested fix:** Add `RecursionError` to the caught exceptions (see also #59).

### 67) Web-map validator accepts artifacts with features removed and reports them `ready`
- **Status:** `fixed` (2026-10-29, `438804a`) — Follow-up: the validator checks completeness, counts and internal coordinate consistency but does not re-derive geographic coordinates (mp-verify has no pyproj), so a uniformly shifted but self-consistent artifact still passes.
- **Severity:** `high`
- **Reproducibility:** `always`
- **Location:** `packages/mp-verify/src/mp_verify/webmap.py:123-215` (`_validate_bindings`, `validate_web_map_artifact`). Introduced in PR #48.
- **Minimal input:** Prepared dashboard whose first call is 101 ft (non-zero misclosure; artifact holds 4 courses, 1 POB, 1 `closure_gap`), with the `closure_gap` and the `call-two` course deleted from `web-map.json`.
- **Expected behavior:** Validation fails: one course per placed primitive, one POB per placement, and a closure gap whenever misclosure > 0 are required.
- **Actual behavior:** Returns the artifact with `availability="ready"`; `build_mapbox_mcp_handoff` sends `availability: ready` with no partial-evidence warning. Feature coordinates and `availability`/`unavailable` claims are also never checked.
- **Impact:** A misclosure and a recorded course can be silently hidden from a map that `mapbox-mcp` presents as complete; manifest hashes detect edits but not authenticity.
- **Suggested fix:** Validate feature completeness and coordinates against the freshly derived geometry, not just identities of present features.

### 68) Web-map CRS transform ignores the operation's area of use
- **Status:** `fixed` (2026-10-29, `cc1a45e`) — Delivery GeoJSON now passes its delivered extent too (PR #60 review); `delivery-1` packages replay without the check, as published. Out-of-area context layers/rasters are omitted (`outside_area_of_use`) instead of failing the whole scene; the operation is chosen from the deed geometry.
- **Severity:** `high`
- **Reproducibility:** `always`
- **Location:** `packages/mp-review/src/mp_review/webmap_projection.py:110-125`; the raster path reuses it via `COORDINATE_OPERATION`. Introduced in PR #48.
- **Minimal input:** EPSG:24376 (Kalianpur 1962 / India zone I) parcel at 74°E, 34°N; or EPSG:21419 (Beijing 1954 zone 19) at 111.5°E, 40°N.
- **Expected behavior:** Select an operation whose area of use contains the geometry, or fail closed.
- **Actual behavior:** `TransformerGroup(source, "EPSG:3857")` is built without `area_of_interest` and `transformers[0]` is used. For EPSG:24376 it picks an operation covering 68.27–71.14°E, 24.16–28.61°N recorded at `accuracy_m=3.0`; the only covering operation places the parcel 26.9 m away. For EPSG:21419 no operation covers the point, yet the map renders at a recorded 15 m.
- **Impact:** Parcels placed tens of metres off with a false accuracy figure.
- **Suggested fix:** Pass an `AreaOfInterest` from the placed geometry or raster extent and fail closed when the selected operation's `area_of_use` does not contain it.

### 69) Neighbour references in calls split one parcel into bogus tracts
- **Status:** `fixed` (2026-10-29, `9c1274b`) — PR #60 review: headings are also recognised after `:`/`;` or before BEGINNING/COMMENCING/ALL THAT, and markers right after a reference word (of, to, said, adjoining, adjacent, along, from, with) are rejected even across a line break. A marker with its own colon or dash is always a heading.
- **Severity:** `high`
- **Reproducibility:** `always`
- **Location:** `packages/mp-parse/src/mp_parse/tracts.py:30-41` and `calls.py` (~line 319). Introduced in PR #43/#44.
- **Minimal input:** `BEGINNING at the northeast corner of Parcel 2; THENCE S 0° W 100 ft along the line of Parcel 3; THENCE W 100; THENCE N 100; THENCE E 100 to the POINT OF BEGINNING`.
- **Expected behavior:** One tract of 4 calls that closes (flat verification closes at 0).
- **Actual behavior:** Tracts `[("Parcel 2", 1), ("Parcel 3", 3)]`, both failing with 100 ft misclosure. Two or more `Lot x of Tract 4567` references raise `Tract has no computable calls` in strict mode.
- **Impact:** Fails safe, but valid deeds that cite adjoining parcels are rejected.
- **Suggested fix:** Only treat TRACT/PARCEL as a marker at a heading position (start of line/sentence, followed by a description), not after `of`/`corner of`/`line of`.

### 70) Compound distances not joined by "and" silently keep only the first part
- **Status:** `partial` (2026-10-29, `1634475`) — Space/comma-joined compounds with distinct units now sum (`2 chains 20 links` → 145.2 ft). PR #60 review narrowed this: without "and", only chain/pole/rod/perch followed by links are summed, so unrelated adjacent distances (`150 feet, 3 rods north of the oak`) and equivalent units (`40 poles 2 rods`) are no longer summed, and `40 poles 5 feet` now needs "and". Still open: an unconsumed trailing measurement (`100 feet, 50 feet`; `40 poles 5 feet`) keeps only the first value without a flag.
- **Severity:** `high`
- **Reproducibility:** `always`
- **Location:** `packages/mp-parse/src/mp_parse/metadata.py` (`extract_distance` compound block, ~lines 388–500); same logic in monolith `text_parser.py`. Introduced in PR #43/#44.
- **Minimal input:** `N 10° E 2 chains 20 links`; `40 poles 5 feet`.
- **Expected behavior:** 145.2 ft and 665 ft (as `2 chains and 20 links` correctly gives 145.2).
- **Actual behavior:** `(2.0, "chains")` = 132 ft and `(40.0, "poles")` = 660 ft, with no note or flag. The trailing-component guard only checks `\s+and\s+`.
- **Impact:** Silently wrong distances on colonial/rural deeds; violates the never-fabricate principle by recording a measured value the deed does not state.
- **Suggested fix:** Accept space/comma-joined compound units, and flag any unconsumed trailing measurement instead of dropping it.

### 71) Multi-tract verified export writes `_verified` sidecars when nothing verified
- **Status:** `fixed` (2026-10-29, `180b7b2`)
- **Severity:** `high`
- **Reproducibility:** `always`
- **Location:** `packages/mp-export/src/mp_export/csv_writer.py` (~lines 337–412, `export_verified_csv` with `tract_results`). Introduced in PR #43/#44.
- **Minimal input:** One open 2-call tract passed as `tract_results`.
- **Expected behavior:** Raise (as the single-tract gate does) and write no `_verified` artifacts.
- **Actual behavior:** Returns `[]` and writes `deed_verified.verification.txt` containing `Misclosure: 141.4214 ft (POOR)`; with `audit_context` also `deed_verified.audit.json`/`.audit.html`. In mixed results the `_verified` summary includes failed tracts.
- **Impact:** Files named `_verified` exist for geometry that failed the gate.
- **Suggested fix:** Apply the global gate in multi-tract mode: raise when no tract verifies and restrict `_verified` sidecars to verified tracts.

### 72) Unparseable `chord_bearing` crashes `verify_closure`
- **Status:** `fixed` (2026-10-29, `5d5d782`)
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `packages/mp-verify/src/mp_verify/closure.py` (~lines 83–85, `compute_traverse`); monolith `closure_checker.py` (~line 385). Introduced in PR #43/#44.
- **Minimal input:** CSV/JSON call with `chord_bearing` of `S 0 E`, `S34-57E` or `South`.
- **Expected behavior:** Warning or blocked check.
- **Actual behavior:** `ValueError: Course 1: invalid chord bearing` escapes `verify_closure`; the pipeline and `metesparser verify` do not catch it (the `mp_review` API maps it to `invalid_input`). Parser-generated chord bearings parse fine, so exposure is mainly imported data.
- **Suggested fix:** Convert the parse failure into a blocked curve check with a warning.

### 73) Monolith multi-tract verification keeps only the last tract's audit
- **Status:** `fixed` (2026-10-29, `9b0dfe3`)
- **Severity:** `medium`
- **Reproducibility:** `unconfirmed` (code trace)
- **Location:** `src/metesparser/closure_checker.py` (~line 110; single write at line 333) vs `packages/mp-verify/src/mp_verify/closure.py` (~line 424). Introduced in PR #43/#44.
- **Issue:** With tracts, the monolith passes one `audit_context` to every `verify_tract`, and each call overwrites `audit_context.verification_audit`, so earlier tracts' checks are lost. The package skips audit for tracts and logs a warning — monolith/package drift.
- **Suggested fix:** Record per-tract verification audits (or match the package behavior) and keep both in sync.

### 74) Curve elements written as "radius 50" / "central angle 90°" are not parsed
- **Status:** `open`
- **Severity:** `medium`
- **Reproducibility:** `always`
- **Location:** `packages/mp-parse/src/mp_parse/calls.py` (`CURVE_PATTERN` and the delta fallback in `extract_curve_info`); monolith `call_extractor.py`. Found while fixing #62.
- **Minimal input:** `a curve to the right having a radius 50 feet and a central angle 90°, chord bearing North 45° East 70.71 feet`.
- **Expected behavior:** `radius_ft=50`, `delta_deg=90`.
- **Actual behavior:** Radius and delta are not extracted; the existing patterns expect forms like `radius of 50 feet` and `delta angle of 90°`.
- **Suggested fix:** Accept `radius <n>` without `of` and `central angle` as a delta synonym in package and monolith, with regression tests.

### PR #60 second review (2026-10-29)
Ten findings from a second review of PR #60, fixed red-green on `fix/code-review-2026-10-29`:
- **Distance regression (#70):** `10 chains and 50 links, 3 rods` again parses as 693 ft; the comma/space joiner no longer swallows a trailing measurement after a valid "and" compound (`84e2ddb`, package and monolith).
- **Tract headings (#69):** a hyphenated ID (`Parcel A-1`) after a reference word is no longer a dash heading, and `in`/`within`/`being` are reference words, including across a line break (`7dd0ed8`).
- **Source paths (#57):** an absolute reference with a `..` component is rejected before normalization, so `root/link/../b.txt` through a symlink is `unsafe_path` again (`8f01106`).
- **Chord-only curve bearing:** when the chord bearing is the only bearing in a curve call, it is no longer used as the tangent azimuth in any spelling; the tangent is derived (`5448a51`, package and monolith). Limitation: a chord-only `due North` style bearing is still taken as the tangent.
- **Delivery area of use (#68):** delivery and the web map share one extent helper in `mp_review.webmap`; the GeoJSON operation is chosen from deed geometry; optional out-of-area context, corridor and PLSS layers are omitted from GeoJSON and recorded as `DeliveryOmission(reason=outside_area_of_use)`; required ones block the publish (`4aff764`). SVG/PDF/DXF keep the layer.
- **Concurrent publish:** `publish_delivery` holds a per-delivery-id `flock` across write and discard, and re-writes every artifact through the write-once path after the manifest, so a manifest never references a missing file (`5b9dd54`). Without `fcntl` (Windows) only the re-write check applies.
- **Cleanup:** one geographic Transformer per projection; `mp_review` reuses `mp_verify.webmap.feature_vertices` (`f57864f`).

### PR #60 third review (2026-10-29)
Ten findings from a third review of PR #60, fixed red-green on `fix/code-review-2026-10-29`:
- **Fabricated tangent (critical):** curve delta is never read from a bearing's degrees; only a stated delta/central angle sets `delta_deg`. Without one, the tangent is derived from arc/radius (noted as such, `delta_deg` stays None) or left None (`7dbd98a`, package and monolith).
- **Chord-only test:** only a numeric quadrant/DMS or "due" bearing counts as a separately stated tangent, so "along the Northerly line of …" no longer keeps the chord as the tangent (`7dbd98a`).
- **Standalone tract headings (#69):** a marker on its own line after of/in/being/with is a heading unless an earlier BEGINNING is still open (`0a0470a`). Limitation: relies on a "point of beginning" closure phrase; a prior tract without one keeps the next standalone marker as a reference.
- **GeoJSON-only failure:** if no coordinate operation serves the deed extent (or a grid is missing), only GeoJSON is omitted, recorded as a format-level `DeliveryOmission`; required layers, `required_appearance` or a GeoJSON-only request still fail (`7e0b10c`).
- **Rotated rasters:** one shared `mp_export.raster_guard.require_upright_raster` runs in the dashboard, delivery SVG/PDF and map evidence renderers; a rotated raster fails the render, including optional ones (`62c8533`). Follow-up: omit optional rotated rasters with a recorded omission instead.
- **Mixed compounds (#70):** `10 chains 50 links and 3 perches` sums to 742.5 ft instead of dropping the chains (`207bc74`).
- **Blocked chord check:** an unparseable chord bearing blocks `curve_consistency` but no longer marks `traverse_closure` failed (`e58c9bb`).
- **Corridor area of use:** checked against every boundary point the export samples, not 5 samples per primitive (`7e0b10c`).
- **Per-tract audits (#73):** `AuditContext.tract_verification_audits` records one labelled `VerificationAudit` per tract in package and monolith (`e58c9bb`).
- **Cleanup:** one projection build per publish and per replay; `prepare_web_map` uses `bounds_of` (`7e0b10c`, `523bf0b`).

### PR #60 fourth review (2026-10-29)
Ten findings from a fourth review of PR #60, fixed red-green on `fix/code-review-2026-10-29`:
- **POB opener (#69):** an opener written `POINT OF BEGINNING at` / `place of BEGINNING at` no longer counts as its own closure (`e3694ef`).
- **Replay portability (decision):** `load_delivery` trusts the omissions recorded in the hash-checked snapshot instead of re-running the environment-dependent area-of-use check, and checks `drawing.geojson` against the snapshot (identity, recorded projection pipeline, exact layer set) instead of regenerating it. Publishing stays fail-closed (`6948102`). Residual gap: without a signature, a fully consistent rewrite that adds a whole-format omission and drops `drawing.geojson` is indistinguishable from a publish on a host without the grid.
- **Scene guard:** the `assert scene is not None` is now a `ValueError` (exit 2) (`6948102`).
- **Corridor sampling:** each corridor is sampled once per publish and the ring reused for the area check and export (`6948102`).
- **Per-tract audits (#73):** audit HTML (monolith and package) renders one labelled verification section per tract; the review API payload includes them; the list is reset on each multi-tract run (`d0d7cc4`). Unused monolith logger removed.
- **Chord-only curves:** a chord-only curve whose tangent cannot be derived is `is_indefinite`; radius-point/radial/centre-point bearings no longer count as a stated tangent; one packed-DMS regex in the monolith (`9ac4fd6`).

### PR #60 fifth review (2026-10-29)
Ten findings plus one found while fixing, fixed red-green on `fix/code-review-2026-10-29`:
- **Curve tangent at the root:** `_course_direction` normalizes every accepted bearing form, then removes witness, chord and radial/radius-point/center-point clauses before `extract_direction` runs, so a chord or radial bearing can only reach `chord_bearing`. The after-the-fact patches are gone. A stated tangent in any accepted form (word, dashed, d/m) is kept (`0089f43`, package and monolith).
- **Radius + chord only:** delta = 2·asin(c/2R); `delta_deg` stays None, the computed arc is stored in `arc_length_ft`/`distance_ft` and noted; c > 2R is a malformed course (`0089f43`). Note: `arc_length_ft` then holds a derived value, distinguished only by the note.
- **Normalizer fabrication:** the "bare cardinal + number → due Cardinal" rewrite no longer turns `N 45-30-00 E`, `N 45d30m E` or `S 90 E` into due North/South (`0089f43`, package and monolith). Two test fixtures that only closed because of this bug were corrected.
- **Tract headings (#69):** one structural rule — what follows the ID decides (strong terminators anywhere, weak ones only at text/sentence start, prose means reference); one 62-case table run on raw and normalized text (`2672447`). Round-3 standalone headings never worked after normalization; they do now. Sample deeds: 6 of 89 changed, all toward ground truth.
- **Text before the first marker:** kept as an `Unlabelled tract` when it has a real THENCE course, instead of being discarded; markdown `#` now marks heading position (`b4b166a`).
- **Replay coordinates:** replay re-renders GeoJSON with the recorded pipeline (`Transformer.from_pipeline`) and the recorded omissions and compares bytes; if the pipeline cannot be built it reports `geojson_coordinates: not_verified` (`07df335`). New `replay_delivery`, exported from the monolith facade (`4177b54`). Dead delivery-1 branch removed; post-manifest check is a cheap size check under flock.
- **Web map extent:** omitted (unplaced) calculations no longer choose the operation; `bounds_of` lives in `mp_verify.webmap` (`ece52ec`, explicit re-export fix).
- **Raster guard:** orientation cached per raster content (`13d9951`).

### PR #60 sixth review follow-up (2026-10-30)
Fixed red-green on `fix/pr60-r6-curve` (package and monolith):
- **Radius + chord only (supersedes the `0089f43` derivation):** without a stated delta or arc the arc is ambiguous (minor vs major), so no delta, arc or tangent is derived. The course is kept with `bearing_azimuth_deg_from_north=None`, `is_indefinite=True` and the note `curve delta/arc not stated - positioned by chord only`; `DeedCall` accepts radius + `chord_bearing` + `chord_length_ft`. The traverse and plot place the next course at the chord endpoint, the plot draws no arc for it (unresolved, split chain), and `curve_consistency` is `blocked` (`curve_delta_not_stated`), so geometry is never eligible. A chord longer than the diameter is kept and flagged (`chord length exceeds twice the radius`) in strict and non-strict mode, like other inconsistent stated curve elements, and fails `curve_consistency`.
- **Two-part dashed bearings:** `N 45-30 E` is 45°30' (was 45°00'30"); three parts remain degrees-minutes-seconds and an explicit seconds marker stays seconds.
- **Verbatim `direction_text`:** the parsed bearing is mapped back to the deed's own wording (`North 45 degrees 30 minutes East`, `N 45-30 E`), skipping chord/radial clause bearings; normalization is for parsing only. Due/compass words and unparsed bearings keep their prior text.
- **Audit:** a tangent derived from the chord bearing and delta records a `derive_tangent_azimuth` step (chord bearing, delta and its source, result, rule).

### PR #60 sixth review (2026-10-30)
Ten findings, fixed red-green on `fix/code-review-2026-10-29`:
- **Dashed bearings:** two-part `N 45-30 E` is degrees-minutes (45.5), not degrees-seconds; three-part stays DMS (`a6e5568`, package and monolith).
- **Verbatim `direction_text`:** keeps the deed's own wording; normalization is used only for parsing (`a6e5568`).
- **Radius + chord only (supersedes `0089f43`):** no delta, arc or tangent is derived (minor/major arc is ambiguous). The call is kept, positioned by its chord, `is_indefinite`, `curve_consistency` blocked, geometry never eligible; plots show it unresolved. Chord > 2R is kept and flagged, not dropped (`a6e5568`).
- **Audit:** a derived tangent records a `derive_tangent_azimuth` step (`a6e5568`).
- **Tract headings:** a parenthetical or comma after the ID is transparent (`PARCEL 2 (Tax ID 12-34)`, `TRACT 2, BEGINNING`); pre-marker `THENCE along/with/by …` courses are kept; dropped THENCE text is logged again (`ece4e74`).
- **Cleanup:** raster orientation cache keyed by SHA-256 digest (`9e7cd11`); one projection factory for publish and replay; one closure-gap threshold/helper (`5ca770f`).

### PR #60 seventh review (2026-10-30)
Ten findings plus one found while fixing, fixed red-green on `fix/code-review-2026-10-29`:
- **Mixed-marker bearings:** any mix of degree (°, degrees, deg, d), minute and second markers parses; each number must carry a marker. 100 Haddon (4317-236) now parses four previously cardinal-only calls, all matching ground truth (`03ef290`).
- **Chord-only distance and perimeter:** `distance_ft` is the stated chord length, not the radius; `ClosureResult.perimeter_available` is False when any chord-only or unpositioned course exists, and summaries show "not determined" (`1fd2f0d`). Note: `perimeter_ft` is then 0.0 to avoid a schema break; consumers must read the flag.
- **Unparseable chord on a chord-only curve:** the course is unpositioned (no tangent-line fabrication), closure blocked and area/perimeter unavailable (`1fd2f0d`).
- **Plot:** chord > 2R is unresolved and breaks the chain; non-finite arithmetic is caught (`1fd2f0d`).
- **Revisions:** chord-only calls pass through revision preparation unchanged (`1fd2f0d`).
- **Dashed bearings:** rewritten only in bearing context, never after identifiers (Lot, Block, Route, No., # …) (`1fd2f0d`). Trade-off: a bare dashed bearing after other prose (`Pennbrook Drive N 45-30 E`) is left as an incomplete bearing.
- **Rasters:** the online-map path omits rotated rasters (`raster_orientation`); orientation cache keyed on the validated `layer.sha256` (`b1bc02d`).
- **Replay:** `load_delivery` raises `DeliveryReplayIncomplete` when GeoJSON coordinates could not be re-verified, unless `allow_unverified_geojson=True`; an empty bound geometry is a `ValueError` (`615cdcb`).
- **Tract headings:** same-line BEING is a heading terminator only in uppercase headings, never before "the same" / "part of" (`9d87380`).

### PR #60 eighth review (2026-10-30)
Ten findings; eight fixed red-green, one rejected, one not reproducible:
- **Radial phrasings:** one `_RADIAL_PREFIX_PATTERN` covers radius point / radial / center-centre / "whose radius" / "the radius of which" bears; the clause is stripped from the course text and recorded in `radial_bearing` with `non_tangent=True` (`fc69e95`). Open: a straight course that mentions the next curve's radius point also gets `radial_bearing`/`non_tangent`, which the in-browser preview refuses.
- **Normalize once:** course bearings are normalized once per call and reused for verbatim text and audit (`4bc6811`); the word-symbol pass is folded into marked-DMS expansion, which now also accepts glued cardinals (`North 45°East`) (`c6bba2f`).
- **Tract headings:** an uppercase marker in heading position is a heading whatever prose follows, unless a reference phrase follows (of, as, on, per, in said, being the same/part of …); `NO` must stand alone (`TRACT NOW.` is not `Tract W`) (`ad07f98`). Risk: an uppercase sentence like `PARCEL 2 IS SUBJECT TO …` starts a tract without calls.
- **Closure:** each run clears the other mode's audit; an infeasible chord-only curve is unpositioned in closure as in plot; one `block_curve_consistency` helper (failed stays failed, reasons combine) (`f788210`).
- **Rejected:** "course-0 continuation should block parallelism" reverses #49; `f5b0c31` restores the #49 behaviour and its test.
- **Not reproducible:** "a required raster blocks the GeoJSON-only omission" — a required raster is already rejected for GeoJSON earlier; `_required_geojson` makes the rule explicit (`64d0c8f`).

### PR #60 ninth review (2026-10-30)
Ten findings plus one follow-up, fixed red-green on `fix/code-review-2026-10-29`:
- **Radial data on straight courses:** `non_tangent`/`radial_bearing` are set only on curve calls (`7b68d1a`).
- **Radial lines:** a straight course run "along a/the/said radial line" keeps that bearing as its course bearing; radial clauses end at their bearing (`7571fb5`).
- **Tangent + chord + radius:** delta = 2 × deflection; consistent within 0.1 ft → arc derived and positioned normally; inconsistent or wrong-sided → kept chord-only, noted "stated tangent, chord and radius are inconsistent" (`7571fb5`). Open: mp_verify does not itself re-check tangent/chord/radius; parser 0.1 ft vs plot 0.01 ft tolerance mismatch.
- **Uppercase recital sentences:** CONTAINING/IS/HEREIN/DESCRIBED/EXCEPTED … after an uppercase ID are references; a repeated label whose segment has no calls folds into the earlier tract (`39c909a`). Open: a `TRACT #1: BEING the same …` recital containing a course word still forms its own tract (15 E Euclid).
- **Area:** `ClosureResult.area_available`; summaries, audit and review packet show "not determined" (`cbd7bbd`). Numeric fields are kept with flags; consumers must read the flags.
- **Compound distances (#70):** a fallback "and" compound must start at the first measurement; `1 chain, 2 rods and 3 links` is flagged unsupported instead of silently becoming 34.98 ft (`a9f83e1`). Limitation: that form is not summed (100.98 ft).
- **Delivery:** a crashed publish without a manifest no longer wedges the id; leftovers are cleared under the lock (`889a82d`). Raster extents use `outer_corners`; one `displayed_calculation_points` helper for web map and delivery (`9db01e4`).
- **Cleanup:** dead API per-tract branch and dead strip helpers removed.

### PR #60 tenth review (2026-10-30)
Nine findings plus the three open items from the ninth review, fixed red-green on `fix/code-review-2026-10-29`:
- **Tangent/chord/radius in verification:** `tangent_chord_issue` in `check_curve_consistency` (package; monolith delegates) fails inconsistent stated tangent/chord/radius/delta; chord-only blocks distinguish `curve_tangent_chord_inconsistent` from `curve_delta_not_stated` (`a38849a`).
- **One curve tolerance:** `CURVE_ELEMENT_TOLERANCE_FT = 0.01` and `TANGENT_CHORD_TOLERANCE_DEG = 1.5″` in `mp_bearing.curves`, used by verify and plot (`a38849a`).
- **No derived values in stated fields:** a tangent+chord+radius curve keeps only stated values (`arc_length_ft`/`delta_deg` None), is chord-positioned and judged by verification only; consistent ones are blocked `curve_delta_not_stated`, no longer export-eligible (`a057959`). Fixed in round 11 (`be1367c`): with a stated tangent the block text now says the delta/arc is "not stated and not derived". Curve info is extracted once per call; BEGINNING clauses skip bearing work.
- **Positioning:** `traverse_positions` drives `unpositioned_indices`; any unpositioned course blocks `traverse_closure` and sets `ClosureResult.misclosure_available=False` ("not determined"), including partial traverses past bearingless lines (`2ddd386`).
- **Sentinels:** confidence scoring, verified-CSV messages, dashboard, run registry (`misclosure_available`), review packet, corpus and scripts honour the availability flags; an unavailable misclosure scores 0 (`eb91dd3`).
- **POB:** `PlotGeometry.point_of_beginning` (only when it differs from the first drawn start) and `plot_point_of_beginning` used by web map, plot HTML, dashboard and validation (`16b3bf3`).
- **Tracts:** title recitals ("BEING the same … conveyed/vested") fold into or are dropped beside the described tract; 15 E Euclid 7433-466 now matches ground truth (2 tracts) (`5153df0`); labels fold case-insensitively (`52d5d54`).
- **Distance:** compounds must start at the course's first measurement; witness distances no longer replace it (`3d75c7e`).
- **Delivery:** without `fcntl`, an exclusive `<id>.publishing` claim replaces clearing; one `_present` helper (`2dd58c0`).

### PR #60 eleventh review (2026-10-30)
Seven findings plus one follow-up; six fixed red-green, one not reproducible:
- **Tangent statement wins:** a radial clause sets `non_tangent` only when the deed does not say the curve is tangent ("tangent to the last course", "tangent curve", "being tangent"); explicit "non-tangent"/"not tangent" always wins (`4395370`).
- **Cardinal-only marker on every note branch:** notes are a joined list, so meander/approximate, chord-only and derived-tangent calls keep "incomplete bearing - cardinal only" (`4395370`, `4fe34d6`). Sample deeds 100 Haddon, 116 Kings Hwy E and 2 Walnut St meander calls now carry the marker.
- **Closure reasons follow positioning:** stated bearings are no longer erased; `traverse_closure` reports `unpositioned_courses` vs `missing_bearings` from the traverse outcome; a chord-only curve positioned by its chord no longer reads as a missing bearing (`be1367c`).
- **No area from partial points; dashboard alignment:** area is skipped when unavailable; the dashboard returns `unresolved` instead of zipping misaligned records and points (`be1367c`).
- **Not reproducible:** "revisions drop radial_bearing_value" — the editor already rejects radial-bearing input with an explicit error before the chord-only branch.

### PR #60 twelfth review (2026-10-30)
Eight findings plus one found while fixing, fixed red-green on `fix/code-review-2026-10-29`:
- **Rounding-aware curve tolerances:** stated lengths ±0.005 ft and angles ±0.5″ are propagated through arc, chord and deflection checks (floors 0.01 ft / 1.5″, caps 0.5 ft / 0.1°); one set of helpers in `mp_bearing.curves` used by verify and plot, which now accept exactly the same curves. Fixes large-radius (R=5000) and cul-de-sac (R=25) false failures from the round-10 fixed tolerance (`844b7e4`).
- **No stored derived arc/chord for radius + delta curves (pre-existing on main):** `arc_length_ft`/`chord_length_ft` stay None; `distance_ft` (required) is the arc computed from the stated radius and delta and is noted "arc length not stated - course distance computed from radius and delta"; `curve_consistency` becomes `not_applicable` instead of passing on self-derived values (`4e4e83d`). Behaviour change: CSV arc/chord columns are blank for these curves.
- **"curving to the right":** curve detection accepts curve/curved/curving and arc phrasings ("arc distance", "arc of", "distance along the arc of"). 89 Haddon (4455-174, 4732-544) course 2 and One Centennial Square (9528-156) course 9 no longer take the radius as the distance (`78e1c8e`). Ground truth for these deeds has no calls to compare.
- **Closure:** computable traverse comes from positioning, so an all-chord-only boundary is computable; `tangent_chord_issue` runs once per curve (`90f4344`).
- **Raster import:** orientation comes only from the shared `image_orientation` reader, matching render (`fe7b222`).
- **Cleanup:** dead `misclosure_known` removed; tolerance comment corrected.

### PR #60 thirteenth review (2026-10-30)
Five findings plus one follow-up, fixed red-green on `fix/code-review-2026-10-29`:
- **One chord/radial clause grammar:** SUBJECT (chord | radius point | radius | radial [line|bearing] | center/centre [point] [of the/said curve]) + optional LINK (of which/to which/which/that/whose) + VERB (bears/bearing [of|is]; lies/is only before a quadrant) + a full course-form bearing captured up to the next comma/semicolon. Fixes "chord which/that bears", decimal-second chord bearings and "center of said curve bears"/"radius point lies" being taken as the course bearing (`8f43351`, package and monolith).
- **Linear tail-context scans:** bounded `_ends_with` replaces quadratic prefix searches (2000 tokens: 7.27 s → 0.016 s) (`8f43351`).
- **Radius + delta/arc + chord bearing without a tangent:** verification positions it by its chord exactly as the plot does; perimeter uses R·δ; area includes the segment (`06e62cf`).
- **Strict-mode curve gate:** "Malformed course" detection uses the shared curve/curved/curving keyword (`d1dcad2`).

### PR #60 fourteenth review (2026-10-30)
Four findings, fixed red-green on `fix/code-review-2026-10-29`:
- **Minute-stated deltas:** angle precision is inferred (whole-minute values ±30″, otherwise ±0.5″) for deltas and bearings; the 0.5 ft linear cap is removed so a correctly rounded minute delta passes at large radii; gross errors still fail (`2940b7a`).
- **Cardinal word vs chord-derived tangent:** a consistent cardinal word keeps the derived tangent with a "stated direction is cardinal only" note and `cardinal_only_direction` audit flag; a conflicting word (outside ±45° intercardinal / ±67.5° cardinal sector of the chord) derives no tangent and is flagged `cardinal_chord_conflict` (`3abde3c`, `e15964b`).
- **Headings with prose:** a heading-position marker whose segment opens a description (BEGINNING/COMMENCING/ALL THAT) before any THENCE course, after a closed description, is a heading in any case (`258fa7d`).
- **Topology for chord-fixed curves:** `mp_verify.tangents` computes tangent-in/out internally for curves fixed by radius, delta/arc, direction and chord; interior angles, boundary topology and the incomplete-bearings warning use them; chord-only curves stay blocked (`6ff0ece`). Interior angles stay `not_applicable` for curved boundaries, as with stated tangents.

### PR #60 fifteenth review (2026-10-30)
Five findings, fixed red-green on `fix/code-review-2026-10-29`:
- **Exception loops:** `_calculate_exception_area` positions exception courses with the shared traverse and `has_determined_direction`, so a tangentless chord+delta exception curve no longer makes net area unavailable (`817be67`).
- **Check fallback:** `build_verification_checks` without `positioned` derives positioning from the shared traverse (`position_courses`), not from bearings (`5e9ceab`).
- **Audit sources:** the `extract_distance` audit step records where the stored distance came from (chord length, radius+delta, stated arc), not the first distance in the text (`eb2d8a7`).
- **One verification implementation:** the monolith `ClosureChecker` is a facade over `mp_verify.verify_closure` (1304 → 329 lines); behaviour change: the monolith now also adds curve-consistency issues to `warnings`, as the package does (`e6772db`).
- **Per-call analysis:** a frozen `CourseAnalysis` record per course replaces parallel index lists; each chord bearing is parsed once (`aa1d0cb`).

## Known Limitations

### E4) OCR bearing misread in scanned PDF (31 Pennbrook Book 11191, Call 3)
- **Status:** `known limitation`
- **Severity:** `low` (< 0.02 ft misclosure impact)
- **Reproducibility:** `always` (specific to 31 Pennbrook Book 11191 PDF)
- **Location:** LLM text extraction (`src/metesparser/pdf_processor.py`, `PDFProcessor.extract_legal_description_text`)
- **Minimal input:** 31 Pennbrook Dr, Book 11191 — old scanned PDF, Call 3 bearing
- **Issue:** LLM OCR misread "N 56°40'00" E" as "N 56°40'50" E" (confused "00" minutes as "50" minutes)
- **Expected behavior:** Correct bearing `N 56°40'00" E` with expected misclosure ~0.0116 ft
- **Actual behavior:** Extracted bearing `N 56°40'50" E` yields misclosure ~0.0167 ft, area off by ~1.25 sq ft
- **Root cause:** Inherent OCR limitation on aged scanned deed PDFs; LLM model artifacts (vision confusion between similar digit pairs)
- **Impact:** Marginal — misclosure still within acceptable range (<0.02 ft), area discrepancy minor relative to parcel size
- **No code fix required** — this is a document quality/LLM limitation, not a parser bug
- **Mitigation ideas for future work:** Try alternative LLM provider (Gemini, Claude), image preprocessing (binarization, contrast enhancement), cross-validate bearings against chain-of-title deeds

### E5) LLM extraction failure on oldest scanned deed (31 Pennbrook Book 4618)
- **Status:** `known limitation`
- **Severity:** `low` (single sample deed affected)
- **Reproducibility:** `always` (specific to 31 Pennbrook Book 4618 PDF)
- **Location:** LLM text extraction (`src/metesparser/pdf_processor.py`, `PDFProcessor.extract_legal_description_text`)
- **Minimal input:** 31 Pennbrook Dr, Book 4618 — oldest deed (1993), poor scan quality
- **Issue:** 0 calls extracted; ground truth expects 5 calls with bearings/distances. LLM returned extracted text but no parseable metes & bounds structure (possibly fragmented bearing/distance pairs or unrecognized abbreviations).
- **Expected behavior:** Extract 5 calls from `LegalDescription.calls`
- **Actual behavior:** Returns empty call list
- **Root cause:** Combination of scan age/quality and OCR limitations; LLM struggled to reconstruct coherent metes & bounds text from degraded source image
- **Impact:** Single sample deed unprocessable; other 31 Pennbrook variants (Books 11191, 11985) process normally
- **No code fix required** — this is a document quality/LLM limitation, not a parser bug
- **Mitigation ideas for future work:** Apply Tesseract preprocessing before LLM extraction (binarization, rotation detection), retry with alternative LLM provider, explore character-level OCR recovery on damaged text regions
