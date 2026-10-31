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
- **Check fallback:** `build_verification_checks` without `positioned` derives positioning from the shared traverse (`analyze_courses` (formerly `position_courses`)), not from bearings (`5e9ceab`).
- **Audit sources:** the `extract_distance` audit step records where the stored distance came from (chord length, radius+delta, stated arc), not the first distance in the text (`eb2d8a7`).
- **One verification implementation:** the monolith `ClosureChecker` is a facade over `mp_verify.verify_closure` (1304 → 329 lines); behaviour change: the monolith now also adds curve-consistency issues to `warnings`, as the package does (`e6772db`).
- **Per-call analysis:** a frozen `CourseAnalysis` record per course replaces parallel index lists; each chord bearing is parsed once (`aa1d0cb`).

### PR #60 sixteenth review (2026-10-30)
Four findings, fixed red-green on `fix/code-review-2026-10-29`:
- **Chord orders:** the chord grammar accepts a length before the bearing ("a chord of 51.76 feet bearing …"), no verb before a quadrant ("chord N 45° E 51.76 feet"), "on a bearing of", "long chord", "subtended by a chord of …" (`5beb2bb`). Limitation: "chord of X feet and a chord bearing of …" keeps the bearing but not the leading length.
- **"non tangent":** tangent statements and `non_tangent` accept non-tangent with space, hyphen, dashes or no separator (`5beb2bb`).
- **Spirals:** `is_circular_curve` keeps spirals out of circular chord positioning, circular area segments, tangents and topology; a spiral is positioned only by a stated chord bearing and length, with area/perimeter not determined (`ed65dc3`).
- **Chord feasibility:** one `chord_is_feasible` helper (2·|R|) for checks, traverse and plot (`ed65dc3`).

### PR #60 seventeenth review (2026-10-30)
Five findings plus one found while fixing, fixed red-green on `fix/code-review-2026-10-29`:
- **Spirals in the parser:** no circular derivation (tangent from chord − δ/2, delta from arc/R, arc from R·δ) for `curve_type='spiral'`; a spiral without a stated tangent gets azimuth None and "spiral tangent not stated - not derived" (`ea07235`).
- **Comma-grouped chord lengths:** all chord-length groups use `COMMA_NUMBER` (`1,097.78 feet`) (`ea07235`).
- **Spirals in verification and plot:** one `is_spiral` predicate (curve_type alone) — a spiral is never a circular arc or a straight line; positioned only by a stated chord bearing + length (nothing drawn, area/perimeter not determined); curve consistency reports `spiral_geometry_unverified`; plot treats chord-stated spirals like chord-only curves so verify and plot position the same spirals; the circular 2R chord bound is not applied to spirals (`d2a1e0f`).
- **No radius as course distance:** `_course_distance_text` strips radius, radial, tangent-length and stated-chord distances before generic distance extraction on curve calls. A spiral with no stated length keeps `distance_ft=None` (allowed only in that case) with "spiral length not stated - course distance not determined"; verification treats it as unpositioned; CSV leaves the value blank and CSV import rejects it (`5d3711f`). Previously such a course got the radius (1000 ft) as its length.

### PR #60 eighteenth review (2026-10-30)
Five findings plus three found while fixing, fixed red-green on `fix/code-review-2026-10-29`:
- **CSV `curve_type`:** appended as the 22nd (last) CSV column so spirals survive export/import; the first 21 columns keep their order and legacy 21-column CSVs still import (`8d3e825`). Schema change — documented in DEVELOPER_REFERENCE, ARCHITECTURE, API, CLAUDE_PLUGIN and README.
- **Blank distance on import:** a spiral with no stated length round-trips its blank distance; non-strict CSV import records rejected rows (`rejected_rows`) or raises — never drops a row silently (`8d3e825`).
- **Stated curve length:** a radius+delta curve that states its length keeps it as the stated arc (verification cross-checks it) instead of the computed R·δ (`fc75587`).
- **"center line" is not a curve element:** only center/centre [point] or center of the/said curve/circle clauses strip a distance (`fc75587`).
- **Scripts:** extraction and Pennbrook scripts print "not determined" for an undetermined distance (`40e3bd6`); the run-registry backfill no longer invents a 0.0 distance and reports the deed as not backfillable (`8b23526`).
- **Radius from a radius-point clause:** the length after a radial bearing is the radius; a conflicting stated radius is kept and flagged (`de08631`).
- **Skipped courses fail closed:** non-strict extraction records each unparseable course (`SkippedCourse` on `AuditContext`/`Tract`, course number reserved) or raises if there is nowhere to record it; verification blocks `traverse_closure` (`skipped_courses`), makes misclosure/area/perimeter unavailable and names the course; audit HTML lists skips (`5cd1cf4`). No production caller uses non-strict extraction.
- **Standalone "thence:" marker:** punctuated THENCE markers are markers, not malformed courses; 1350 Brace Rd and 38 Birchall Dr now parse in strict mode and match ground truth (`9f1db1d`).

### PR #60 nineteenth review (2026-10-30)
Four findings (three regressions from round 18), fixed red-green on `fix/code-review-2026-10-29`:
- **Curve length roles:** every length in a curve call is classified by its own label — radius, chord, tangent, arc, radial element or course length — before anything is stored. A chord length is never saved as the arc, a bare "tangent N" is never a length, "a distance of N" after a radial bearing is not the radius. One unlabelled course length is the stated arc; two or more are noted "curve length ambiguous" and none is chosen (`26a96d0`). Behaviour change: a single course length is the stated arc whenever a radius is stated.
- **Course-list headers:** "THENCE (by/along) the following N courses (and distances)" and lone/punctuated THENCE markers are removed before numbering, so courses follow the deed's (1)…(n) with no skip; 89 Haddon Ave (4732-544) now parses its six courses (`26a96d0`). Open: numbered courses run inline after the header on one line are not split.

### PR #60 twentieth review (2026-10-30)
Four findings plus one found while fixing, fixed red-green on `fix/code-review-2026-10-29`:
- **No stored derived tangent (supersedes the derived-tangent behaviour recorded in earlier rounds, including the `derive_tangent_azimuth` audit step):** the parser no longer computes chord ± δ/2 into `bearing_azimuth_deg_from_north`. A curve without a stated tangent keeps azimuth None with "tangent bearing not stated - curve positioned by chord and delta in verification"; verification positions it by chord and delta. Closure, area, perimeter, check statuses and eligibility are numerically identical; the tautological tangent/chord check no longer runs on such curves (`f13caa5`).
- **Confidence scoring:** call quality and bearing completeness use `has_determined_direction`, so chord-and-delta curves are not scored as missing a bearing (`6dfce18`).
- **Curved boundaries first:** interior angles are `not_applicable` for curves positioned by their chord (spirals, chord-only), and the incomplete-bearings warning counts only courses that are neither direction-determined nor positioned (`96e6e03`).
- **One sweep rule:** the traverse uses `curve_sweep` (0 < sweep ≤ 360); `stated_sweep`/`chord_delta` helpers replace four inline copies (`96e6e03`).
- **Inline numbered courses:** "(1) … (2) …", "1)", "1." and ordinal enumerators after a course-list header or THENCE are split even on one line; a header count mismatch raises (strict) or is recorded as a skipped course (non-strict). 104 Kings Highway E (8964-1299) now yields all 12 ground-truth courses instead of 2 (`0cc5202`).

### PR #60 twenty-first review (2026-10-30)
Seven findings, fixed red-green on `fix/code-review-2026-10-29`:
- **One course-list header grammar:** `COURSE_LIST_MARKER` (metadata.py, shared with calls.py; monolith mirrored) drives both marker removal and enumeration detection. It accepts leading qualifiers ("along said road"), trailing qualifiers, "to wit", "viz", "namely"; a counted header with no matching enumeration is a mismatch (strict raises, non-strict records `CourseCountMismatch`) — never a silent drop (`280d36a`).
- **Ordinals:** ordinal words are enumerators only as a sequence of two or more starting at First after a header; "THENCE first North …" keeps its wording (`280d36a`).
- **Enumeration once per tract:** `analyze_course_lists` runs once and is passed to `split_into_calls`; bounded header search (1000 courses: 328 ms → 12.9 ms) (`280d36a`).
- **Scoped THENCE re-split:** only list headers and inline-enumerated list courses are re-split; other courses keep "thence running with said line" whole (`280d36a`).
- **Parallelism across curves:** continuing-line checks compare the previous course's exit tangent with the next course's entry tangent (`curve_tangents`), so chord-and-delta curves no longer block and a correct continuation after a curve passes; chord-only curves still block; #49 unchanged (`965c9c7`).

### PR #60 twenty-second review (2026-10-30)
Two findings, fixed red-green on `fix/code-review-2026-10-29`:
- **Verified export honours skipped courses:** the exporter's fresh re-check (package `export_verified_csv` and monolith `CSVBuilder`) receives tract skips, audit-context skips and an explicit `skipped_courses` list, and refuses export when any apply; `metes-review` passes its audit skips. Callers that extract non-strictly must pass them (`c73b7f7`).
- **Chord-only spirals representable:** `DeedCall` accepts a spiral with chord bearing + chord length and no radius (curve direction optional); the parser uses the stated chord as the course distance with "spiral positioned by stated chord; radius not stated" (`45cd3e2`).

### PR #60 twenty-third review (2026-10-30)
Four findings plus one found while fixing, fixed red-green on `fix/code-review-2026-10-29`:
- **Double-entry comparison:** `compare_double_entry` always compares `curve_type` and compares curve fields whenever either entry has them, so chord-only spirals and spiral-vs-circular disagreements are reported (`3a35cb9`).
- **Single-description export:** the verified-export gate also blocks on `legal_desc.tracts[*].skipped_courses` (package and monolith) (`3a35cb9`).
- **One skip-routing rule:** `mp_verify.closure.skips_for_tract` is used by `verify_closure` and both exporters (`3a35cb9`).
- **Unnumbered counted lists:** a counted header without enumeration is satisfied when at least that many courses follow in the tract, and flagged only when fewer remain (`5b07404`).
- **Semicolon-separated header courses:** courses after a header separated only by ";" are split instead of merged, so the second is no longer lost (`5b07404`).

### PR #60 twenty-fourth review (2026-10-30)
Seven findings plus one found while fixing, fixed red-green on `fix/code-review-2026-10-29`:
- **Fail closed on merged courses (root cause of silent course loss):** a call fragment holding two or more complete bearing+distance courses is split safely on ";" (or back-to-back courses) when every piece is one course; otherwise strict raises `MultipleCoursesError` and non-strict records a `SkippedCourse`. Headers "in the following …" and "the next N (N) courses" and (a)/(b) enumerators are recognised (`0330425`). Sample deeds recover silently lost courses: 8 Kings Highway W (9787-1784) 7 → 8 (now matches ground truth, misclosure 117.49 → 0.98 ft), 26 Chews Landing (8566-200) 1 → 5, 75 Haddon (10604-1433) 1 → 5. Three sample texts now fail closed where a fragment truly holds two courses (1 Walnut St tract 3; 101-111 Kings Highway E 7683-1295 normalized, whose 158 ft course was silently lost and is missing from ground truth; 26 Chews Landing 8566-209 md).
- **Dashed bearings:** any context except identifiers (Lot, Block, Route, …) expands "N 45-30 E" (`0330425`).
- **Count-mismatch record:** names the header text with declared/found counts (`0330425`).
- **Source CRS area of use:** an extent must lie inside both the coordinate operation's and the source CRS's own area of use (`d45e4c3`).
- **Monolith parser facade:** `CallExtractor`, `MonumentClassifier` and `TextParser` delegate to `mp_parse` via shared `package_bridge` converters (−3,635 lines); a differential test over 1,389 texts finds 0 differences (`504a2a8`). Found: the public `mp_parse.extract_calls` normalizes twice and can turn a bearing-tied point of beginning into course 1 — pinned by a strict xfail, fix queued.
- **Library-mode logging:** `mp_*` package warnings reach the configured handler (`6da1dc3`).

### PR #60 twenty-fifth review (2026-10-30)
Six findings plus one found while fixing, fixed red-green on `fix/code-review-2026-10-29`:
- **More chord phrasings (fabrication):** "a long chord of", "chord:", "chord =", "chord direction of", "chord brg.", "C.B.", "a chord which runs" now open a chord clause, so the chord bearing is never stored as the tangent (`70d4013`).
- **Ties, record calls and adjoiner lines are not courses:** before counting complete courses, each bearing+distance pair is classified; ties ("said pin being …", "distant …", "which is … from"), parenthetical/labelled record calls ("(… per deed)") and adjoiner lines ("which line bears …") are excluded, so valid deeds no longer fail closed. Genuine two-course fragments still fail closed (`70d4013`). Fixed in round 26 (`d290473`): record calls are kept verbatim in notes.
- **One course-text preparation:** `_prepare_course_text` serves both bearing reading and course counting; the reversed `_DASHED_BEARING_CONTEXT` alias is removed (`70d4013`).
- **Normalize once, idempotently (found by the facade work):** `extract_calls` normalizes exactly once, and normalization is idempotent — "and <bearing>" → "thence" now happens in one pass and never inside a bearing-tied point of beginning, and "PK" no longer gains a "nail" per pass (`705ace7`).

### PR #60 twenty-sixth review (2026-10-30)
Four findings plus one carried over, fixed red-green on `fix/code-review-2026-10-29`:
- **Record calls kept:** a parenthetical or labelled record call is appended verbatim to the call's notes ("record call: …") and recorded as an audit Decision; a "per record" label after a course no longer marks the measured course itself as a record (`d290473`).
- **Spirals stated by length:** a spiral with a stated length (and optional direction/radius) and no chord is representable — `arc_length_ft` holds the stated spiral length, never R·δ — and verification leaves it unpositioned with the curve check blocked (`4572d56`). Packaged plugin schemas were synced with the new field description.
- **Non-tangent curves:** a course bearing never fixes a non-tangent curve's starting tangent; it is positioned by chord + sweep or by a radial bearing (tangent = radial ∓ 90° by direction), otherwise unpositioned — the same rule in traverse, plot, topology, parallelism, closure and confidence, so verify and plot agree (`0d0f7c1`). Follow-ups fixed (`b52aa1a`, `7cda88a`): an unreadable chord leaves the curve unpositioned in verify and plot; radial vs chord and radial vs stated tangent are cross-checked; diagnostics uses the shared orientation rule.
- **JPEG EXIF fill bytes:** 0xFF fill bytes before a marker are skipped, so a rotated JPEG is no longer read as upright (`74c314f`).

### PR #60 twenty-seventh review (2026-10-30)
Six findings plus two follow-ups, fixed red-green on `fix/code-review-2026-10-29`:
- **Curve length units:** one shared `_LENGTH_UNIT` pattern (feet, ft, ft., foot marks, meters/metres/m, chains, rods …, comma-grouped) for every chord, radius and radial length; chord lengths are converted to feet. A chord of `200.00'` no longer turns its bearing into the tangent (half-disc repro misclosure 282.843 → 0.0) (`5242f78`).
- **Unitless labelled curve lengths (regression from round 19):** "an arc length of 87.27" / "chord distance of 87.16" keep their stated value in the deed's unit; unlabelled unitless numbers are still excluded (`5242f78`).
- **Monolith CSVBuilder facade:** delegates to `mp_export.csv_writer` (593 → 161 lines); a differential test compares every written file byte for byte (`1e15623`).
- **Legacy 21-column curve rows:** noted "curve type not recorded (legacy CSV); treated as circular" (`11846f4`).
- **Chord parsed once:** `tangents.parse_chord` caches the chord azimuth, so verification parses each chord string once (8 → 1) (`280401c`).
- **Curve orientation follow-ups:** unreadable chords leave a curve unpositioned in verify and plot; radial vs chord and radial vs stated tangent are cross-checked; diagnostics uses the shared rule (`b52aa1a`, `7cda88a`).

### PR #60 twenty-eighth review (2026-10-30)
Four findings plus one follow-up, fixed red-green on `fix/code-review-2026-10-29`:
- **No silently dropped parcels:** a block's closing point of beginning must follow its first THENCE ("said point of beginning being …" in the preamble is not a closure); unassigned text containing courses is kept as an unlabelled tract or fails closed. 219 Berlin Rd (12799-00118) legal text: 9 → 29 calls matching all 29 ground-truth courses; 07105-00834 and 08256-00635 split into tract + easement (`d8f0daa`).
- **Trailing text after the closing course:** encumbrance lists, "Subject to", "Together with", "Under and subject to", "BEING the same" etc. after the course that returns to the point of beginning are not courses; a trailing complete course still fails closed. Sample skips 432 → 331 (1 Walnut St 37 → 1, 1350 Brace Rd 19 → 0) with no change in parsed calls (`77131bc`).
- **Concavity is not a direction:** "concave to the southeast" and similar clauses are stripped before cardinal detection (`db2e11a`).
- **Same-unit "and" pairs are not summed:** "100.00 feet and 50.00 feet" gives the first measurement; different-unit compounds still sum (`db2e11a`).
- **Metric course lengths:** `extract_distance` reads metres/meters/m, foot marks and "ft." via the shared `mp_parse.units` module (`b4d83c2`).

### PR #60 twenty-ninth review (2026-10-30)
Five findings (two regressions against main), fixed red-green on `fix/code-review-2026-10-29`:
- **Course region per tract:** `_course_region` bounds course material from the first course (or BEGINNING block) to the fragment containing the closing "point/place of beginning" phrase anywhere in it, cut at the closing sentence. Cover-sheet preambles and trailing affidavit/form text are not courses unless they state a complete course. 20 E Redman Ave (8214-294, 12427-01665) and 17 Kings Highway W (10394-9), which verified on main and regressed, verify again (`d1b17eb`).
- **Main-parity guard:** `tests/unit/test_sample_verification_parity.py` with a recorded main baseline fails if any sample deed that verified on main stops verifying (now 37 vs 36 on main; none lost) (`d1b17eb`).
- **Shared units:** the course-distance check and `extract_distance` read `mp_parse.units` (US survey feet, engineer chains/links, arpents, toises, furlongs; singular "perch") instead of hand-written lists; the region is computed once per tract (`d1b17eb`, `f301c50`).

### PR #60 thirtieth review (2026-10-30)
Nine findings plus two follow-ups; fixed red-green on `fix/code-review-2026-10-29` (the straight-course length ambiguity fix lands separately):
- **Plot and diagnosis apply verification's curve checks:** `plot._arc` (and diagnostics through it) call the shared `tangent_chord_issue`, `radial_chord_issue` and `radial_tangent_issue`, so a curve verification rejects is never drawn or diagnosed (`fe85e28`).
- **Traverse cleanup:** unreachable invalid-chord raises, unused `CourseAnalysis` fields and the duplicate positioning loop removed; `traverse_positions` wraps `analyze_courses` (`6a8b1bb`).
- **Multi-tract export skip routing:** skips are routed against every known tract, so a skip on an omitted tract no longer blocks an exported one (`778cef1`).
- **Undetermined misclosure status:** `get_closure_status()` returns "NOT DETERMINED" and `is_fully_verified()` is False when `misclosure_available` is False (`778cef1`).
- **AGENTS.md:** 22 CSV fields; cardinal-only patterns live in mp_parse and the audit script, with monolith aliases (`778cef1`).
- **Bearing minutes are not lengths:** the shared `LENGTH_UNIT` foot-mark branches refuse a mark followed by a compass direction ("N 45 30' E"), for calls, tracts and curve lengths (`f9b31c2`); tracts.py uses the shared units (`56998f7`).

### PR #60 thirty-first review (2026-10-30)
Four findings plus the round-30 length fix and merge follow-ups, fixed red-green on `fix/code-review-2026-10-29`:
- **Straight-course lengths by role (round 30, finding 1):** `read_course_length` classifies every length on a straight course (ties, widths, parentheticals, stations, monument sizes are excluded; "in all"/"total" wins); two or more remaining lengths fail closed with "course length ambiguous" instead of taking the first (`16fff20`).
- **Compound units:** descending runs such as "100 feet 6 inches" (100.5), "2 rods 3 feet" (36), "1 mile 20 feet" (5300) are summed; ascending or equivalent runs fail closed (`16fff20`).
- **Dashboard:** courses with a determined direction (including tangentless curves positioned by chord and delta) reach the dashboard; local azimuths for curves come from `curve_tangents` (`e59b8be`).
- **Dotted P.O.B. and word-form bearings:** "P.O.B.", "T.P.O.B.", "R.P.O.B." close the course region (the normalizer keeps T./R. as "true/remote point of beginning"); a foot-mark length followed by a worded bearing stays a length (`03af339`, `48decc6`).
- **Single calls cut at the closing sentence:** `extract_single_call` drops a recital after the closing sentence, but a complete course there that is not a recital fails closed (`48decc6`, `6a4e577`).
- **Ground-truth discrepancies found (not changed):** 75 Haddon Ave (4924-448, 10604-1433, 4924-452) ground truth records 15.83 ft for the last course, which is the distance to a stone passed on the way; the deed's "total distance of 336.25 feet" closes the parcel (misclosure 320.45 → 0.034 ft). 101-111 Kings Highway E (7683-1295) ground truth records 10 ft (an alley width) for courses 8 and 9, which the deed states as 148.10 and 12 feet.
- **Known limitation:** distance-first courses ("100' N 45° E") are not parsed and fail closed.

### PR #60 thirty-second review (2026-10-30)
Four findings, fixed red-green on `fix/code-review-2026-10-29`:
- **Inch components never dropped:** "in"/"in." count as inches only where a measurement ends and only as the trailing component of a descending compound ("100 feet 6 in." → 100.5, independent of trailing punctuation); "100' 6\"" reads 100.5 in a length context only; prepositions ("in a northerly direction") are never inches; an unread inch component makes the course fail closed. A square with "100 feet 6 in." on one side now reports 0.5 ft misclosure instead of verifying (`1abaa1a`).
- **Chord-positioned courses:** `traverse.is_chord_positioned` marks chord-only curves and chord-stated spirals; the dashboard draws them as their chord with "Arc not determined; positioned by chord only" instead of blocking as incomplete bearings; confidence rates them medium; the parser no longer marks them indefinite, so text and CSV paths give the same warnings (`350893d`).

### PR #60 thirty-third review (2026-10-30)
Five findings plus one follow-up, fixed red-green on `fix/code-review-2026-10-29`:
- **Inches after a comma:** "100 feet, 6 inches", "100', 6\"" and similar forms sum to 100.5; the unread-inch guard looks across a comma (`fd2ac12`).
- **Worded-degree bearings:** minutes and seconds after "degrees", "deg.", "d" or a hyphen are never read as a feet-and-inches length (`fd2ac12`).
- **Conflicting chord-only courses:** a course whose cardinal word conflicts with its chord (is_indefinite) is not chord-positioned, so the dashboard blocks it and confidence scores it low; the chord analysis is computed once per dashboard calculation; one conflict boolean in the parser (`884463e`).
- **Hyphenated DMS with marks:** "N 45-30' 15\" E", "N 45-30'-15\" E", "S 10-15' W" and similar expand to canonical DMS; identifier guards unchanged (`1081076`).

### PR #60 thirty-fourth review (2026-10-30)
Five findings, fixed red-green on `fix/code-review-2026-10-29`:
- **Verification derives direction conflicts:** `mp_bearing.cardinal_conflicts_bearing` (shared sector rule) lets `CourseAnalysis` detect a cardinal/chord conflict and an over-diameter chord itself, so courses read from CSV or built without the parser are not chord-positioned and get the same indefinite warning, confidence and dashboard status as parsed ones (`bd21927`). Follow-up fixed (`64b7d92`): `effective_indefinite` is used by confidence, corridor, plot, diagnostics, comparison and the closure warning.
- **Monument sizes are not lengths; one inch token:** "100.00 feet, 1\" iron pipe", "3/4\" rebar" read 100; foot-inch pairs end at thence/more or less like every inch form; one shared inch token, measurement-end rule and monument vocabulary (`ab419eb`).

### PR #60 thirty-fifth review (2026-10-30)
Nine findings plus one follow-up, fixed red-green on `fix/code-review-2026-10-29`:
- **Fractional lengths (also wrong on main):** one shared `mp_parse.units.LENGTH_NUMBER` / `parse_number` grammar (comma-grouped decimals, mixed "100 1/2" and "100-1/2", plain "3/4", vulgar "½"/"6½") feeds every length, curve-element, compound and inch pattern; a number never starts or ends inside a fraction, and unreadable fractions fail closed. "100 1/2 feet" → 100.5 (was 2.0); "3/4 mile" → 3960 ft (was 21120); fractional inches and radii are read; an ascending compound ("6 inches 10 feet") fails closed; "100 feet 6\"" reads 100.5; "North 1/2 of Section 5" and aliquot parts are not courses (`17094c9`). Open: curve calls have no inch unit.
- **CSV header validation:** `csv_text_to_calls` accepts only the exact 22- or legacy 21-column header, so `metesparser verify` rejects partial-column CSVs (exit 1); per-tract skip routing is computed once; `extract_single_call` docstring describes what it raises (`a4598c9`).
- **Derived indefinite everywhere:** `effective_indefinite` (stored flag or verification-detected conflict) drives confidence, corridor, plot, diagnostics, comparison and the closure warning (`64b7d92`).

### PR #60 thirty-sixth review (2026-10-30)
Six findings, fixed red-green on `fix/code-review-2026-10-29`:
- **CSV row width (bug):** a data row with fewer or more cells than the header was padded with None and imported (a truncated spiral became circular, an exception row became boundary). `csv_text_to_calls` reads with `csv.reader(strict=True)`, requires every row to match the header width (strict: raise; non-strict: rejected row), skips blank lines everywhere, and strips a UTF-8 BOM; `csv_to_calls` opens with `utf-8-sig`, so Excel CSVs import. `mp_review` verify and plot use it instead of their own checks (`b8063f4`).
- **`extract_single_call` contract:** returns None only for BEGINNING/COMMENCING/P.O.B. clauses; any other course that yields no call raises `ValueError` (monolith docstring updated). An out-of-range hyphenated bearing ("N 95-30' E") becomes an incomplete-bearing call like "N 95° E" instead of being dropped (`a4c7501`).
- **Strip-exception widths:** use the shared number grammar, so "except the East 20 1/2 feet thereof" and "except the North 1,200 feet" are detected and removed (`a4c7501`).
- **Closure computes indefinite once:** the closure warning and confidence score use the `CourseAnalysis` records instead of re-deriving per call; identical output (`58a8366`).

### PR #60 thirty-seventh review (2026-10-30)
Nine findings, fixed red-green on `fix/code-review-2026-10-29` (findings 3-8 also behave this way on `main`):
- **Curve followed by a course (fabrication):** "along a curve ... arc length of 50 feet; THENCE N 20° E 10 feet" stored N 20° E as the curve's tangent and lost the 10 ft course. A curve fragment beside a separate complete course now raises `MultipleCoursesError` in `extract_single_call`, and `extract_calls` splits it into both courses (`4fb7dfb`).
- **Cardinal/chord conflict survives CSV:** verification derives the conflict with the parser's rule (chord bearing stated, no numeric course bearing, cardinal word outside its sector) even when chord and sweep determine the direction, so a re-imported conflicting curve stays indefinite (`c5b68e5`).
- **Out-of-range bearings agree:** with or without "THENCE", degree-sign, hyphen and word forms ("N 91° E", "N 91-30-00 E", "N 91 degrees E") give an incomplete-bearing call from both `extract_single_call` and `extract_calls` (`4fb7dfb`).
- **Comma grouping:** only valid thousands grouping is a number; "100,50 feet" fails closed instead of reading 10050 (`3cb6eae`).
- **Verbatim `along`:** the course's own bearing and length are no longer captured in `along` ("Main Street (50 feet wide)", "Main Street") (`4fb7dfb`).
- **Decimal degrees:** a degree-sign decimal with 1 or 3 decimals ("N 45.5° E") is not read as packed DD.MMSS; azimuth stays empty with "incomplete bearing - ambiguous decimal degrees". Two- and four-plus-decimal forms stay packed (bug #43) (`3cb6eae`).
- **Seconds kept in `bearing_quadrant`:** "S 89°59'59\" W" is stored as stated instead of "S 90°00' W"; 186 sample bearing strings gain their stated seconds, azimuths unchanged (`3cb6eae`).
- **CSV row numbers:** errors and `rejected_rows` give the physical line where the record starts, correct after multi-line quoted cells (`c5b68e5`).
- **Cleanup:** duplicate "due {cardinal}" block removed from `extract_direction` (`4fb7dfb`).
- **Known limitations:** two-decimal degree values ("N 45.50° E") are still read as packed minutes; a comma list "100, 200 feet" reads 200.

### PR #60 thirty-eighth review (2026-10-30)
Seven findings, fixed red-green on `fix/code-review-2026-10-29`:
- **Spelled-out out-of-range bearings:** one shared recogniser makes every quadrant-bearing form with an out-of-range component ("North 91° East", "South 45° 30' 75\" West", "N 45 degrees 61 minutes E") an incomplete-bearing call in both `extract_single_call` and `extract_calls`; identifiers such as "Lot N 12-70 E" stay non-bearings (`470fbea`).
- **Unread chord and radial bearings:** a stated bearing that cannot be read is kept verbatim in notes ("chord bearing not read: 'N 45 E'") instead of disappearing. It does not set `is_indefinite`, which is not a CSV column, so text and CSV verification agree; a tangentless curve with an unread chord stays unpositioned on both paths (`470fbea`, `fe02cfa`).
- **Chord-stated spirals:** the parser treats a spiral with a stated length and chord as chord-positioned, matching verification and the CSV round trip (`ea44a6d`).
- **Curve direction not stated:** a curve stated only by concavity fails closed with "curve direction (left/right) not stated" (never inferred); any `DeedCall` validation error from parser input becomes a clean malformed-course message or skip (`ea44a6d`).
- **Leading-decimal lengths:** ".5 feet" reads 0.5; "1.2.3", "100 .5" and similar fail closed (`40eb6af`).
- **Inch-only courses:** "12 inches", "6 in.", "24\"" right after the bearing read as feet; monument sizes, prepositions and seconds marks are unaffected (`40eb6af`).
- **Tabular curve labels:** R=, L=, Δ=, CB=, CH=/C= are read like the spelled-out wording; A= and D= are not read; a degree-of-curve value is no longer taken as the delta (`40eb6af`).
- **Known limitation:** "along an arc to the right" is not recognised as a curve and fails closed.

### PR #60 thirty-ninth review (2026-10-30)
Nine findings (three regressions against `main`), fixed red-green on `fix/code-review-2026-10-29`:
- **Record-call regressions:** "N 45° E (deed N 44° E) 100 feet", "100 feet per deed / of record / (R)" and "(R) …, … (M)" or "[N 44° E 99 feet deed]" parse as one course again. A bearing inside a parenthetical or bracketed group never takes the length of the bearing outside it; a fragment's only labelled pair is the course; with (R)/(M) labels the measured pair is the course in either order (on `main` "(R) first" took the record pair). Record bearings and record distances ("(deed 99.5 feet)") are kept verbatim in notes; road widths are not record calls (`e850ed3`).
- **Qualifiers in `along`/`to`:** "parallel to/with", "at right angles to", "tangent to", "perpendicular to" and similar are kept verbatim in `along` and never become the destination; the course's own length no longer ends up in `to`. 114 of 1045 sample calls change (96 gain the qualifier in `along`; 18 lose a wrong `to` such as "the last course a distance of 81.52 feet") (`0b01839`).
- **Spiral notes:** a chord-positioned spiral is noted once as "spiral positioned by its stated chord only; radius not stated", matching the verification warning (`0b01839`, `beeb5a4`).
- **`DeedCall.is_curve()` includes spirals:** one curve predicate for verification and every caller; the relative-course plot and dashboard validators reject spirals instead of drawing them as lines; perimeter uses a spiral's stated length (`9658b58`).
- **Dead code:** `csv_writer._row_to_call` (log and drop) removed (`9658b58`).
- **Cardinal vocabulary sync:** `mp_bearing.normalize_cardinal_word` is added to the AGENTS.md sync list, and a test checks every copy accepts and rejects the same words (`9658b58`).
- **Known limitations:** a lone course labelled "per deed" or "(R)" loses the label wording (as on `main`); a qualifier before an explicit "along" is not kept; a qualifier at a sentence end can run on into the next word ("parallel with the first course the").

### PR #60 fortieth review (2026-10-30)
Ten findings (two fabrications, two regressions against `main`), fixed red-green on `fix/code-review-2026-10-29`:
- **Record calls identified once, before any course value is read:** a single scan (`_scan_record_calls`) finds nested-aware bracketed record groups and record-labelled statements, blanks them from the text used to read bearing, tangent, chord, radial, distance and curve elements, and keeps them verbatim in notes. A record bearing can no longer become a curve's tangent ("chord bearing N 45° E 49.9 feet (deed N 44° E 49.8 feet)" was az 44) or a cardinal-only course's bearing ("Northeasterly (deed N 44° E)" was az 44, now "incomplete bearing - cardinal only"); pairs are never mixed; "[deed 99.5 feet]" reads 100 again; (M) beats (R) for lengths and chords; R/M, "formerly" and "(recorded as …)" distances are noted; a course whose only length is a record fails closed; "per deed, … per deed" now raises `MultipleCoursesError` (`e70a791`).
- **Notes kept on enrichment:** `enrich_calls_with_azimuths` removes only the incomplete-bearing note, keeping every other note intact (`e70a791`).
- **Offset distances (regression):** "parallel to and 50 feet distant from", "N feet off", "N feet measured at right angles from" are offsets, not the course length; a length directly after another unjoined length stays ambiguous (`d61636f`, `92f4536`).
- **Known limitations:** a lone labelled course loses its label (or keeps it in `along`); a tie inside parentheses is noted as a record call; an unclosed bracket holding a bearing is treated as a record to the end of the text; "one hundred (100) feet" fails closed.

### PR #60 forty-first review (2026-10-30)
Nine findings (three regressions against `main`, one a silent loss of every course), fixed red-green on `fix/code-review-2026-10-29`:
- **Courses joined by "and" (regression, silent loss):** "BEGINNING at a pin and running N 45° E 100 feet to a pin and S 45° E …" returned no calls and no error in strict mode (`main` returned 3 of 4). "and running <bearing>" opens a course and later "and <bearing>" separates courses, so all 4 parse. Defence in depth: a BEGINNING/COMMENCING clause that states a course is never dropped silently — strict raises, non-strict records `SkippedCourse(error_type="CourseInPreamble")`. 8 Kings Highway W (7489-772), which lost its first two numbered courses this way (2 calls, misclosure 89.87), now fails closed (`2aef883`).
- **COMMENCING tie-ins:** courses from the point of commencement to the point of beginning are marked `is_tie_in` at extraction (skipped when a course gap could hide the real tie). Deed 50058-00465 now verifies (misclosure 81.997 → 0.005); deed 50146-01291 Parcel A's two commencement courses are tie-ins (`2aef883`).
- **Trailing separator in `to`:** "to a pin and thence" gives "a pin" (`2aef883`).
- **Adjective widths and monument depths (regressions):** "a 50 foot road", "a 16.5 foot right of way", "a 20 foot alley" are widths; "found 0.5 feet below grade" is a monument position, not a course length (`79caf75`).
- **Every excluded record value is noted, verbatim:** an (R) bearing after an (M) bearing without a comma, and "Rec.", "plan", "plat", "survey", "P", "D" labels are noted; record notes in `extract_calls` use the deed's own text, including label words ("in prior deed") (`78ad6d7`).
- **"by the line of Smith":** kept in `along` like "along" (`78ad6d7`).
- **Known limitations:** Deed 50231's tie ("to a place of beginning") is not marked; "to a point, thence" keeps the trailing "thence".

### PR #60 forty-second review (2026-10-30)
Eight findings (none regressions against `main`; two fabricated lengths), fixed red-green on `fix/code-review-2026-10-29`:
- **No fallback length (fabrication, also on `main`):** when every length in a course is an offset, tie, width or monument depth, the course fails closed with "Missing boundary course distance" instead of taking the first number ("set 0.5 feet below grade" was a 0.5 ft course). The fallback's two legitimate uses are now role rules ("80 feet in width or breadth"; a leading "at a distance of N feet"). 34 sample rows that had borrowed a tie, record or width length now fail closed; none was geometry-eligible (`1b38bd1`).
- **Monument depth needs a monument:** "back", "deep", "high", "above", "below" make a length a tie only with a monument noun, "found"/"set", or "grade/surface/ground"; "100 feet back to the place of beginning" and "150 feet deep" are course lengths (`1b38bd1`).
- **Preamble courses through the real splitter:** `split_call_fragments` returns every fragment, including the BEGINNING/COMMENCING ones `split_into_calls` drops. A preamble course in its own clause (";", numbered, "running") is extracted as an ordinary course; one comma-joined to the BEGINNING clause fails closed (`CourseInPreamble`); ties are decided with the parser's own pair roles. The regex detector is gone. 8 Kings Highway W (7489-772) now gives all 4 ground-truth courses and verifies (misclosure 89.87 → 0.0053 ft) (`ec38062`).
- **"by" adjoiners only before the destination:** "to a stake in the corner formed by the line of Smith …" no longer invents an `along` (`e3fc6dd`).
- **(R) then (M) bearings:** the measured bearing is the course in every order, with or without commas, including chord bearings (`e3fc6dd`).
- **Verbatim record notes from aligned spans:** source and normalized text are aligned once per description and each record is restored within its own tract, with word boundaries (`e3fc6dd`).
- **Known limitations:** a cardinal-only course (no degrees) inside a preamble clause is ignored; the monolith splitter merges 15 E Euclid's "80 feet in width or breadth; thence …" into one fragment, which now fails closed (the package path matches ground truth).

### PR #60 forty-third review (2026-10-30)
Ten findings (two regressions against `main`), fixed red-green on `fix/code-review-2026-10-29`, plus one found while checking samples:
- **Feature dimensions (regressions):** a length followed by high/tall/thick/square/radius/diameter is a feature dimension, never the course length ("100 feet to a corner of a fence 4 feet high", "along a fence 3 feet high" read 100 again); "long"/"deep" are the course only when no other length is stated; a course whose only length is a feature dimension fails closed (`b578dab`).
- **Parentheticals noted:** a bracketed length that is not a record or measured call is kept verbatim as "parenthetical: (calculated 101 feet)"; "(see plan 12 feet)" is now noted (`b578dab`).
- **Area statements:** shared number grammar (".5 acres" was 5 acres; "1/2 acre" and "2 1/2 acres" were 2 acres); compound areas ("2 acres and 50 perches") are summed; an unreadable component gives no area rather than a partial one (`b578dab`).
- **Strip exceptions:** "EXCEPTING the westerly 10 feet thereof" and "LESS AND EXCEPT …" no longer become an invented 10 ft exception course. They are set aside before tract splitting and noted verbatim as "exception not applied: …"; verification warns that closure, area and perimeter describe the boundary before the exception, so the parcel is never export-eligible. Deed 50233 and -50795 now give 4 closing courses (was 3 plus an ambiguous skip); deed 50512 loses an invented exception tract (`a7171a5`).
- **Appurtenant easements:** "Together with / Subject to / Reserving … easement" or "ALSO an easement" descriptions with their own courses become EASEMENT tracts instead of extra boundary courses (`a7171a5`).
- **36 Kresson Rd (found in samples):** a tie reaching the point of beginning followed by ", thence" closed the block early and silently dropped 4 exception courses; the package path now gives all 9 ground-truth courses (`a7171a5`).
- **`along`/`to` from one set of spans:** the destination is the first destination "to" after the course (so "lands conveyed to Smith" stays whole) and ends at the clause end ("containing … acres", "subject to", "being the same", the next "thence"); `along` comes only from the course part and accepts "by and with", "with the line of", "binding/bounding on", "adjoining", "following"; passing calls go to notes as "passing call: …"; the course's own length and "a distance of" are removed from both. 154 sample along/to values change, almost all toward verbatim adjoiner and destination wording (`17d4798`).
- **Known limitations:** `to` stops at an initial's period ("Samuel N."); in 219 Berlin, OCR "4' a point" (for "to a point") leaves no destination; an easement deed is multi-tract, so `mp_review` plot refuses it; "100 feet (101 feet M)" fails closed as ambiguous (`main` read 100).

### PR #60 forty-fourth review (2026-10-30)
First round beyond the parser: all 129 sample tracts give identical misclosure, area, perimeter, `is_fully_verified` and plot output to `main` wherever a value is available. Ten findings (one regression), fixed red-green on `fix/code-review-2026-10-29`:
- **No placeholder misclosure in audits:** when misclosure is not determined, the `traverse_closure` check records `misclosure_available: False` instead of `misclosure_total_ft: 0.0` (110 placeholder entries across the samples removed) (`1d5d903`).
- **Interior angles (regression):** missing bearings take precedence over a curved boundary, so 89 Haddon Ave (4455-174), 89 Haddon Ave (4732-544) Tract 1 and One Centennial Square (9528-156) report `blocked/missing_bearings` again instead of `not_applicable` (`1d5d903`).
- **One rule per curve question:** `stated_sweep_with_error` (delta uncertainty, was copied five times), `determined_arc_sweep` (area and perimeter), one `_analyze` for indefinite and chord positioning (no per-call traverse), `entry_azimuth`/`exit_azimuth` shared by dashboard, traverse, plot and parallelism; `build_verification_checks` requires `positioned`. Sample output identical apart from the two fixes above (`1d5d903`).
- **Replay host limits are not tampering:** a projection that fails on the replay host (`WebMapUnavailable`, `ProjError`) or a mismatch where a named grid is not installed reports `geojson_coordinates: not_verified`; only a mismatch with every grid available reports "artifact differs" (`6d511ac`).
- **Atomic publish:** artifacts and manifest are written to a `.<id>.publishing-<pid>-<hex>` staging directory and renamed into place; the per-id `flock`, claim file, clear/discard and post-manifest re-assert steps (entries above) are gone. A crashed publish leaves only a staging directory that never blocks a retry (a stray `.DS_Store` used to wedge the id). Artifacts are byte-identical; `delivery-1` still replays. Behaviour change: republishing an already-published id, even with identical content, now fails as "already published" (`6d511ac`).
- **Web map imports:** one `mp_verify.webmap` import block, no redundant re-export aliases (`feb57a0`).
- **Known limitations:** on POSIX, `rename` replaces an empty directory created with the same id in the instant between the existence check and the rename; on Windows stale staging directories are ignored but not cleaned.

### PR #60 forty-fifth review (2026-10-30)
Six findings (no regressions against `main`; three were gaps in this PR's own fixes), fixed red-green on `fix/code-review-2026-10-29`:
- **Revisions with chord-stated spirals:** an unrelated edit to a deed containing a chord-stated spiral was rejected as "incomplete or unsupported". `PlotUnresolved.positioned` (a derived, unserialized property, so `geometry_hash` and stored plot JSON are byte-identical) marks courses placed by their chord, and revision acceptance uses it (`23e47ef`, `07db92c`).
- **Chord-only structured edits cross-checked:** a supplied tangent that contradicts the chord bearing, radius and chord length is rejected with the shared rounding-aware tangent/chord check (`23e47ef`).
- **Skipped courses in the audit:** `audit.json` always records `skipped_courses`; replay treats an older audit without the key as empty (`23e47ef`, `07db92c`).
- **Deeply nested JSON:** every CLI command returns the error envelope with exit 2 instead of a traceback with exit 1 (`ed96227`).
- **Plot notice:** a partial plot caused only by chord-positioned courses names those courses instead of saying only the anchored prefix is plotted (`ed96227`, plus a follow-up using `PlotUnresolved.positioned`).
- **Legacy EXIF-rotated rasters:** the offline map evidence and the dashboard omit them with the `raster_orientation` reason and message, matching `prepare_web_map`; delivery and compose still refuse them (`ed96227`).

### PR #60 forty-sixth review (2026-10-30)
Ten findings (four regressions from recent rounds), fixed red-green on `fix/code-review-2026-10-29`:
- **"ALSO an easement" then "ALSO all that lot" (regression):** strict extraction raised on a stray "Unlabelled tract"; the easement is now its own EASEMENT tract and the lot an Addition (8 boundary calls, as on `main`, which dropped the easement silently). Easement notes use the deed's own wording (`adc6027`).
- **Strip-exception wording:** "SAVE/LESS AND EXCEPT", "EXCEPTING THEREFROM/AND RESERVING", "of said lot/premises", "of the above described premises" and purpose tails ("for road purposes", "conveyed to …") are recognised and noted whole. Any other EXCEPT clause after a closed description with no traverse is noted as not applied instead of becoming an invented course or a calls-less tract. 219 Berlin Rd (12941-00156) Tract 2 now flags its "Excepting thereout … conveyed to the State" exception, which was dropped silently (`adc6027`).
- **Note splitting:** note prefixes live in `mp_models.deed_call`; `split_notes` splits only before a known prefix, so exception wording containing "; " stays whole in the verification warning (`adc6027`).
- **Passing calls in brackets (regression):** "(passing a pin at 50 feet)" no longer truncates `along` to "the line of Smith (" or is noted twice; it is noted once as a passing call (`5539674`).
- **Record calls never in `along`:** `along` is built with the record scan's spans removed, so the result is the same whatever the word order (`5539674`).
- **Legacy crashed publishes (regression):** a manifest-less delivery directory holding only files the old publisher wrote (plus OS litter) is cleared and republished; anything else is refused untouched (`b596f7f`).
- **Long delivery ids (regression):** staging names no longer embed the id, so any id whose directory name is legal publishes (`b596f7f`).
- **CLI recursion:** only recursion while reading the input JSON is `invalid_input_json`; other recursion is `internal_recursion_error` and lists files already written (`b596f7f`).
- **Dashboard calculator version:** `dashboard-1.2.0`, since round 44 changed stored local azimuths; older dashboards inspect as `algorithm_version_mismatch` (`b596f7f`).
- **Known limitations:** a non-boundary reservation after the description ("EXCEPTING AND RESERVING unto the Grantor all oil, gas and minerals") is flagged as an unapplied exception and blocks verified export; "Subject to easements of record, except as noted." still raises in strict mode.

### PR #60 forty-seventh review (2026-10-30)
Ten findings (two regressions from recent rounds), fixed red-green on `fix/code-review-2026-10-29`:
- **Addition parcels that mention a right of way (regression):** an easement opener must grant, reserve or subject an easement or right of way as its object; "ALSO all that tract of land adjoining the railroad right of way, BEGINNING …" stays an Addition with its courses on the boundary (as on `main`). When unsure, a parcel is kept as an addition rather than set aside (`1d5edd7`).
- **Sentence ends skip initials and abbreviations:** one `ends_sentence` rule (initials, acronyms, common abbreviations, decimals; a clause-opening word always ends the sentence) replaces two copies. Exception notes keep "conveyed to John A. Smith by deed dated May 1, 1950", and `to` fields no longer stop at a middle initial ("Samuel N. Rhoads", "Henry E. Uber and wife"; only `to` values change in the samples) (`1d5edd7`).
- **Bearing-only exceptions:** an EXCEPT clause that names a bearing but states no measured course is noted as not applied instead of failing strict extraction (`1d5edd7`).
- **One closure rule and one stop list** for strip, stated-exception and easement spans (`1d5edd7`).
- **Notes read by prefix:** record-call audit values, verbatim restoration and set-aside notes use `split_notes` instead of assuming record calls are last; audited record calls equal the noted wording exactly (`1a54c79`).
- **Record and alternative wording leave `to`:** "to a pin (deed 99 feet)" gives `to='a pin'` with the record only in notes; alternative-length parentheticals and measured groups are removed from `to` as from `along` (`1a54c79`).
- **Offsets (regression):** "parallel to/with and N feet (distant) from X", "N feet from and parallel to X" and "(measured) at right angles from" are offsets; "parallel to and 10 feet from Main Street 100 feet" reads 100 (`main` read 10) (`1a54c79`).
- **Passing calls after ";":** attached to the preceding course in every split path; an unattachable adjoiner/qualifier tail after ";" fails closed (`1a54c79`).
- **CLI input recursion by phase:** each JSON-input command loads and depth-checks its input inside an input boundary first, so recursion there is `invalid_input_json` on every platform; output tracking records only this run's paths, without walking the output directory (`8b209ce`).
- **Known limitations:** three other ". "+capital splitters (`calls._SENTENCE_END`, `metadata._SENTENCE_BREAK`, the RESERVING/SUBJECT TO clause text) do not yet use `ends_sentence`; a measured group after the destination keeps its value in `distance_ft` but the word "measured" is in no field; "Lot B. Next …" can over-capture into an exception note.

### PR #60 forty-eighth review (2026-10-30)
Nine findings (two regressions from recent rounds), fixed red-green on `fix/code-review-2026-10-29`. Tract, exception and easement classification had oscillated across rounds 43-48, so every case asserted since round 43 now lives in one corpus (`test_tract_classification_corpus.py`, 115 deeds) that must pass at once:
- **Strip inside the closing course (regression):** "…, except the North 10 feet thereof, to the point of beginning." keeps `to` = "the point of beginning"; a strip in an open course is never extended, and no extension crosses a point-of-beginning mention (`50ad847`).
- **Easement grants (regression):** "the use of an easement / right of way", "the right to use", "a right of ingress and egress", "the free and uninterrupted use", and grantee wording with or without commas are easements again; land that merely adjoins or lies within a right of way or easement stays a fee addition. A BEGINNING block is an easement when a grant clause runs on to it with no sentence end, ";" or THENCE between (`50ad847`).
- **EXCEPT after acreage:** an EXCEPT after the closure with only course-free wording between ("containing 0.23 acres, more or less") is noted as not applied instead of failing the deed (`50ad847`).
- **Dividing-line exceptions:** an exception is a traverse only with two or more courses or one course closing to the point of beginning; "a line running N 80° E 100 feet from the pin" is noted, not traversed (`50ad847`).
- **Computed once:** clause stops, openings, closures, EXCEPT leads and easement spans are indexed once per text (`50ad847`). In the samples, 100 Haddon Ave (4658-859) `.md` now gives the same 4 courses as its other sources instead of failing; a signature-page warranty "except as otherwise set forth" is noted as an unapplied exception (fails closed).
- **Note registry:** every fixed note the system writes is registered in `mp_models`, so `split_notes` never merges a following fixed note (e.g. the legacy-CSV curve note) into exception or record wording; round-trip tested over all pairs and random combinations (`c2f68e5`).
- **Passing calls before the bearing:** "passing over a stone wall S 45° E 100 feet" notes only "passing over a stone wall" (`c2f68e5`).
- **One passing-piece rule and one bracket scanner** (`c2f68e5`).
- **CLI partial output:** an internal error lists only output directories this run created or changed, as "may contain partial output", never other runs' files (`6559d98`).
- **Known limitations:** a strip exception inside a middle course still fails closed as an ambiguous length; a new fixed note must be added to the registry; partial-output directories are detected by top-level change only.

### PR #60 forty-ninth review (2026-10-30)
Seven findings (four regressions from rounds 47-48, none conflicting with the classification corpus), fixed red-green on `fix/code-review-2026-10-29`; the corpus grew to 133 deeds:
- **Closure means a course's arrival (regressions):** a point-of-beginning mention closes a description only where a course arrives after the opening clause. A mention inside the BEGINNING clause ("BEGINNING at an iron pin marking the point of beginning, together with an easement …") or a COMMENCING tie to "the true point of beginning" followed by courses does not close it, so the parcel courses stay on the boundary instead of being set aside as an easement or raising; an easement clause with no courses of its own inside an open description is noted (`15e15ec`).
- **Described excepted parcels (regression):** "EXCEPTING THEREFROM the following described parcel: PARCEL A: BEGINNING …" and "LESS AND EXCEPT that part described as follows: Tract 2: …" type the parcel EXCEPTION and keep the boundary MAIN (`main` dropped the boundary; the branch made the excepted land a second fee tract) (`15e15ec`).
- **Wording after the closing point of beginning (regression):** ";"-separated wording after the closure stays on the closing course, so a passing call is noted and adjoiner wording fails closed as mid-traverse (`15e15ec`).
- **Exception traverses without degree marks:** exception courses are recognised with the parser's own bearing grammar and counted per ";" clause; dashed DMS exceptions become EXCEPTION tracts, and symbol-less "S 80 E" fails closed as on `main` (`15e15ec`).
- **Offset wording kept:** "10 feet from and parallel to the line of Smith" stays whole in `along`; a qualifier before an adjoiner is kept with it (36 sample `along` values regain qualifier wording such as "at right angles to the last course and along the line of lands now or late of Uber") (`1da3dd0`).
- **Bracket-aware ";" cuts:** a ";" inside brackets no longer cuts `to`, the no-THENCE course split, or the calls segmenter (two of these silently dropped the text after the ";"); a bracketed passing call is noted once (`1da3dd0`).
- **Known limitations:** a plural lead ("the following described parcels: PARCEL A … PARCEL B") types only the first parcel EXCEPTION; two ";"-separated dividing lines with bearings and distances count as a traverse (fail closed or exception tract, not a note).

### PR #60 fiftieth review (2026-10-30)
Ten findings (four regressions from rounds 48-49, one performance regression), fixed red-green on `fix/code-review-2026-10-29`:
- **Performance (regression, worse than reported):** besides per-character bracket and sentence-end rescans (400 courses 0.38 s vs 0.07 s on `main`), `_SourceMap`'s `difflib` alignment was cubic when normalization rewrote every course (a 400-course description did not finish in 120 s). Unchanged tokens now align one to one and changed stretches in 256-token windows; bracket spans are bisected; sentence-end checks read only the adjacent word. Time now grows linearly (400 courses 0.13 s; normalizing variant 0.19 s), guarded by a growth-ratio test (`08caf24`).
- **Course length removed from `along` (regression):** the whole selected course-length span ("1 chain 50 links", "25 feet 6 inches", "the distance of 142 feet", "more or less") is cut, not a re-matched token; 22 sample `along` values lose a dangling "the" (`08caf24`).
- **"along with" (regression):** conveyancing "along with all improvements thereon" is not adjoiner wording, never fails a course closed, and is recorded as a deed clause; "along with the line of Smith" is still an adjoiner (`08caf24`).
- **Adjoiner after the destination and length (regression):** "to a pin 100 feet more or less along the line of Jones" gives `along='the line of Jones'` again (`08caf24`).
- **"Lot B." (regression):** a single letter after Lot/Block/Section/Parcel/Tract/Unit is a label, so `along` stops at "Lot B"; the remaining ". "+capital splitters (closing-sentence cut, strip scan, RESERVING/SUBJECT TO clauses) use the shared rule (`08caf24`).
- **Easement grants:** "the benefit of an easement" and "all right, title and interest in and to the … easement" are easements; land within or adjoining an easement stays an addition (corpus +13 cases) (`c51dd0d`).
- **One JSON reader:** every CLI-reachable JSON input decodes once and is depth-checked inside the input boundary (`mp_review.json_input`), so deep JSON in any input or option is `invalid_input_json` and the double parse is gone; a deep record inside a `validate-source` root stays a per-file `invalid_json` finding (`f3671a3`, `32f8fa2`).
- **Partial output:** an internal error lists every path handed to the run that exists afterwards (`f3671a3`).
- **Legacy temp files:** `NamedTemporaryFile` residue (`tmp` + 8 characters) in a manifest-less legacy delivery directory no longer blocks the id (`f3671a3`).

### PR #60 fifty-first review (2026-10-30)
First round run as a result-level comparison: every sample `.md`, `::legal` and `::normalized` text through `extract_calls` + `verify_closure` on `origin/main`, the round-46 state and the head. No sample deed's course values, misclosure, area or verification status regressed since round 46, and none lost full verification against `main`. Six findings from synthetic probes (two regressions), plus one gap found while fixing them, fixed red-green on `fix/code-review-2026-10-29`:
- **Generic encumbrance recitals (regression):** "SUBJECT to easements of record." before the description made the whole boundary an EASEMENT tract with no boundary calls (`metes-review review` returned `no_calls`; `main` verified it). A recital naming plural easements/rights of way "of record" or "if any" is never an easement opener, and an opener whose sentence ends before a following BEGINNING is not an easement description. Removes the false "easement, not part of the boundary: SUBJECT to zoning ordinances …" note on 219 Berlin Rd (12799-00118) (`aa22b89`).
- **Easement and exception tracts never export as verified (found while fixing the above; introduced with EASEMENT tracts in this PR):** through the Pipeline, an easement-only deed was fully verified and wrote `deed_verified_tract1.csv`, and a boundary plus easement or exception wrote a verified CSV for the non-boundary tract. `verify_closure` now blocks EASEMENT and EXCEPTION tracts (`non_boundary_tract`) while still computing their geometry, and `export_verified_csv` refuses when no MAIN/ADDITION tract is supplied and skips non-boundary tracts even when a supplied result claims eligibility (`66f7ec0`).
- **"along with" (regression):** conveyancing only before a conveyancing object (improvements, hereditaments, appurtenances, rights …) or after the closing course; "along with the Northerly side of Main Street" is adjoiner wording again; a `together_with` deed clause never spans a THENCE (`aa22b89`).
- **Sentence ends at document structure:** a blank line, markdown heading or bullet, table bar or HTML tag ends a sentence and bounds notes, so the 56 Haddon Ave (7426-1333) and 15 E Euclid Ave (7433-466) exception notes no longer run over affidavit forms (`aa22b89`).
- **Error envelopes kept:** `diagnose_closure_file` returns `invalid_diagnostics_input` for deep JSON again; a malformed or too-deep artifact inside a delivery package is an invalid delivery naming the artifact, not `invalid_input_json` (`9292ce7`).
- **Legacy temp files refused, not deleted:** a `tmp` + 8-character name cannot prove it is publisher residue, so such files in a manifest-less legacy directory are refused untouched and listed for manual removal (reverses the round-50 auto-clear) (`9292ce7`).

### PR #60 fifty-second review (2026-10-30)
Result-level comparison of all 227 sample texts (extraction, verification with tracts, verified export) on `origin/main`, the pre-round-51 head and the head: no course value, misclosure, area, verification status or export eligibility regressed. Six findings from synthetic probes, three of them changing classification and therefore verified export, fixed red-green on `fix/code-review-2026-10-29`; the classification corpus grew to 174 cases, and every new case also asserts that verified export writes only the boundary:
- **Generic recital beside a specific easement (regression from `aa22b89`):** a recital is generic only when its clause names no single easement or right of way and introduces no description; "SUBJECT to the easements of record and to an easement for drainage described as follows: BEGINNING …" keeps its easement tract instead of becoming a verified fee tract (`e6dfda8`).
- **Document breaks end an easement opener:** a blank line, heading or line break before BEGINNING ends the opener's sentence before any boundary, so a recital before the parcel never swallows it (`e6dfda8`).
- **Easements by position:** after a closed boundary, a specific grant followed only by its sentence end (period, blank line or line break) and then a new BEGINNING/COMMENCING description is an easement; "The said easement is … described as follows:" gives the description to the easement in either position. Previously such descriptions became second fee tracts and bypassed the non-boundary export block (also on `main`) (`e6dfda8`, `ab67639`).
- **Blocked tracts scored after the block:** the non-boundary check (`checks.evaluate_tract_role`) runs before confidence is computed, so a blocked easement or exception reports a lower confidence than a verified boundary; tests live where AGENTS.md says (`6a2cdcf`).
- **One export-eligibility helper** and one source for the non-boundary reason text (`mp_models.tract_kind`, `non_boundary_detail`) (`6a2cdcf`).
- **Known limitations:** after a closed boundary, "SUBJECT to a right of way over the driveway. BEGINNING …" now types the next description as an easement (conservative: never exported as verified); a heading between such a grant and the description leaves it a fee tract.

### PR #60 fifty-third review (2026-10-31)
Sample texts unchanged from round 52 (byte-identical result-level output). Nine findings from synthetic probes, four of them regressions from `e6dfda8` that changed classification and so verification and verified export. Fixed red-green on `fix/code-review-2026-10-29` by consolidating the classification logic rather than patching each case:
- **One sentence-break rule and one grant decision:** `_sentence_break` replaces three diverging sentence-end helpers, and `_grant_takes` decides for every path whether an opener's grant takes a description (the divergence between `_easement_spans` and the `_easement_lead` fallback caused the regressions and the five-round oscillation) (`f01f50d`).
- **Common "subject to … of record, bounded and described as follows" form (regression):** a generic recital before any boundary never claims the parcel; "lying within" / "being a portion of" a right of way is a location, not a grant (`f01f50d`).
- **"After the boundary" means a closed MAIN/ADDITION description:** an exception description, a COMMENCING or true-point-of-beginning tie, or a recital mention no longer makes a later recital claim the real parcel (`f01f50d`).
- **Numbered courses (regression, unsafe):** "thence (1) North …" is recognised by the parser's own enumerator grammar, so an easement after the boundary is an easement whatever the numbering; the corpus re-runs every case in four numbering forms and requires identical classification, calls, verification and export (186 cases, 1425 tests) (`f01f50d`).
- **`role_check` private:** `verify_closure` no longer accepts a caller-supplied role check (which could strip verification from a closed parcel); export reasons derive from the exported tract, and a result belonging to another tract blocks that tract's export (`91cb313`).
- **Known limitations:** after a closed boundary, an easement grant followed by an explicit tract heading ("PARCEL B: BEGINNING …") is typed as a fee tract; "Said easement is described as follows" before the parcel types the next description as an easement.

### PR #60 fifty-fourth review (2026-10-31)
Sample texts unchanged by round 53. Five result-changing findings from synthetic probes, three of them regressions against `main` on ordinary single-parcel deeds whose preamble recited an easement or exception. Instead of recognising more grant wording, classification now rests on invariants (`1a40419`):
- **INV-1, the first parcel is the parcel:** wording before the first description ("SUBJECT to easements … as shown on the filed plan", "subject to a 10 foot wide utility easement along the rear line", "excepting the portion within Main Street", "EXCEPTING AND RESERVING the oil and gas rights") never types it as an easement or exception; a preamble EXCEPT clause stays on the parcel text. Explicit exceptions: an EXCEPT lead taking land "from the lands hereinafter described", and a document that opens with a specific easement grant running into its description (an easement deed; nothing exported).
- **INV-2:** only a description after a closed MAIN/ADDITION boundary can be an easement, or an exception unless introduced inside an open description.
- **INV-3:** a boundary written as an enumerated list under one THENCE ("thence the following four courses: (1) …, (2) …, (3) … and (4) …") counts its courses, so it closes and an easement after it stays an easement.
- A property test inserts 12 recitals in 2 frames before the first description of every corpus case and requires an identical outcome (classification, calls, verification, export files and rows).
- On the samples, no verification or export result changed: 116 Kings Highway E `.md` is no longer typed EXCEPTION (its four cardinal-only courses are the boundary, matching ground truth) and 36 Kresson Rd `.md` (monolith one-description path) no longer marks all four courses as exceptions because of boilerplate "except as set forth in this Deed".
- **`verify_tract` role binding:** the public `verify_tract` no longer accepts a caller-supplied role check; it takes an optional `tract` and derives the check from its type (`da093bc`).
- **Known limitations:** a "GRANT OF EASEMENT" title alone does not mark an easement deed; preamble recitals are left on the parcel text rather than noted.

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
