# Bugs

## High

### 1) Missing singular distance unit `"foot"` is ignored
- **Location:** `src/metesparser/text_parser.py` (`TextParser.extract_distance`)
- **Issue:** The distance regex only accepts `feet`, `ft`, and pluralized units (`poles`, `rods`, etc.). Singular `"foot"` is not recognized.
- **Impact:** Calls written as `"1 foot"` (or `"2 foot"`) are treated as `0`, so valid geometry lines can be dropped as if they had no distance.
- **Why it is a bug:** The code comments and validation paths imply support for common legal-language units, and fallback parsing does not recover this case.
- **Suggested fix:** Include `"foot"` in the unit pattern and normalize to `"feet"` before conversion.

### 2) Alternate distance parser can misread DMS minute marks as distance
- **Location:** `src/metesparser/call_extractor.py` (`extract_distance_alternate`) called from `CallExtractor.extract_single_call`
- **Issue:** The fallback pattern `(\d+(?:\.\d+)?)\s*(?:'|feet|ft)\b` matches bearing minute values such as `45°30' E` as `30`.
- **Impact:** A call missing a real distance but containing a bearing with minutes (e.g. malformed/legalized text variants) can be assigned a bogus distance, injecting false geometry into the traverse.
- **Why it is a bug:** The pattern has no context to distinguish minutes from distances.
- **Suggested fix:** Scope the fallback to explicit distance forms only (e.g., require word boundary before/after and avoid values immediately preceded by DMS/angle constructs).

## Medium

### 3) Polygon area formula assumes closed points list and omits wrap-around segment
- **Location:** `src/metesparser/closure_checker.py` (`ClosureChecker.calculate_area`)
- **Issue:** Shoelace summation uses `for i in range(n - 1)` and intentionally avoids the final wrap edge. This is only correct if the point list already includes a duplicated start point.
- **Impact:** Open traverses (or any non-repeating point list) produce a non-closed-area approximation, which can emit misleading area values and area-based warnings during verification.
- **Suggested fix:** Validate closure or compute the wrap-around term with modulo indexing: `j = (i + 1) % n`.

### 4) `metadata` argument in `calls_to_csv` is silently ignored
- **Location:** `src/metesparser/csv_builder.py` (`CSVBuilder.calls_to_csv`)
- **Issue:** The `metadata` parameter is never persisted to CSV output.
- **Impact:** Callers that pass metadata through this API receive no CSV-side traceability for source document/PLSS fields unless they separately write metadata themselves.
- **Suggested fix:** Write metadata rows/comments in CSV header or consistently route metadata to a sidecar file in the same writer method.

### 5) PLSS range direction can be misdetected as East for West ranges
- **Location:** `src/metesparser/text_parser.py` (`TextParser.extract_plss_metadata`, lines handling `range_match`)
- **Issue:** West range direction is inferred with `"E" in match.group(0)`, which is true for strings like `"WEST"`, so `W` is incorrectly classified as `E`.
- **Impact:** Parsed PLSS metadata can silently swap `W` ranges to `E`, which is a high-impact data integrity issue for legal references.
- **Why it is a bug:** The heuristic checks only character presence rather than tokenized direction, unlike township parsing.
- **Suggested fix:** Check for explicit west/east tokens (e.g., `re.search(r"\bWEST\b")`) or normalize using a capture group from the regex.

### 6) Apostrophe-distance fallback fails for documented `123.45'` input style
- **Location:** `src/metesparser/call_extractor.py` (`CallExtractor.extract_distance_alternate`)
- **Issue:** The fallback regex `(\d+(?:\.\d+)?)\s*(?:'|feet|ft)\b` requires a word boundary after `'`, so common inputs like `"125.26' along the line"` do not match.
- **Impact:** Legitimate calls that use apostrophe-foot shorthand without an explicit `feet` unit are parsed as zero distance and often dropped as non-calls.
- **Why it is a bug:** The function’s own docstring explicitly says these formats are supported (`125.26'`), but the regex does not match them in normal prose context.
- **Suggested fix:** Relax the apostrophe branch (e.g., allow optional trailing whitespace/punctuation) and avoid matching DMS minutes accidentally by requiring context.

### 7) Inconsistent curve model rejects valid zero-degree curve data
- **Location:** `src/metesparser/models.py` (`DeedCall.delta_deg`, `DeedCall.arc_length_ft`) and call/closure curve logic using truthy checks
- **Issue:** `DeedCall` requires `delta_deg > 0` and `arc_length_ft > 0`, but `BearingConverter` and regression coverage allow `delta_deg=0.0` as valid (straight line with zero central angle), and several curve branches use truthiness checks.
- **Impact:** Straight-line curve cases represented with zero delta/arc cannot be represented via `DeedCall`/CSV import, and zero-angle curves can be skipped in curve computations.
- **Why it is a bug:** The domain model and curve utilities disagree on valid input bounds, causing avoidable validation/normalization failures.
- **Suggested fix:** Permit zero where mathematically valid (`ge=0`) consistently, and check curve fields with `is not None` rather than truthiness where zero may be meaningful.

### 8) Parallelism check ignores azimuth wrap-around at North
- **Location:** `src/metesparser/closure_checker.py` (`ClosureChecker.check_parallelism`)
- **Issue:** The difference is computed as `abs(curr_az - prev_az)` with no circular normalization.
- **Impact:** Calls marked as `"continuing"` can be falsely flagged when bearings cross 0°/360° (e.g., 359.8° then 0.2°), because the raw difference is 359.6° rather than the true 0.4° line-parallel separation.
- **Why it is a bug:** Angular continuation comparisons must use the smallest circular difference, not raw subtraction, to correctly handle compass wrap.
- **Suggested fix:** Normalize using `delta = min(abs(curr_az - prev_az), 360 - abs(curr_az - prev_az))`, then compare against tolerances for same/opposite direction.

### 9) Along-field extraction matches substrings like `"alongside"`
- **Location:** `src/metesparser/text_parser.py` (`TextParser.extract_along_to_fields`)
- **Issue:** Along detection uses `find("along")` and treats any substring match as an `"along"` clause.
- **Impact:** Phrases such as `"alongside the north line"` are incorrectly parsed as `along="side the north line"` even though no explicit `along` clause is present.
- **Why it is a bug:** The method should only detect the standalone keyword `along`, not arbitrary words containing the substring, to preserve line descriptions.
- **Suggested fix:** Use a word-boundary anchored regex for the clause (e.g., `\balong\b`) and ignore suffix/prefix matches.

### 10) Parenthesized or bare-numbered calls are not split into separate calls
- **Location:** `src/metesparser/text_parser.py` (`TextParser.split_into_calls`)
- **Issue:** Call splitting only recognizes numbered formats like `1.`, `2.` or `THENCE`/semicolons; patterns like `1)`/`(1)` are not treated as call delimiters.
- **Impact:** Descriptions such as `"1) N 45°E 100 feet\n2) S 45°W 80 feet"` are parsed as a single call, causing later parsing to retain only the first boundary or merge multiple courses into one call record.
- **Why it is a bug:** The parser explicitly documents numbered-call support in prompt contracts and real deed outputs, but the regex only handles dot-form numbering.
- **Suggested fix:** Extend the numbered-call detection/splitting patterns to accept `(n)` and `n)` styles and strip those prefixes during normalization.

### 11) Exception splitting triggers on incidental `ALSO`/`INCLUDING` words
- **Location:** `src/metesparser/text_parser.py` (`TextParser.split_exception_clauses`)
- **Issue:** The clause splitter treats any standalone `ALSO` or `INCLUDING` as a tract boundary, regardless of semantic context.
- **Impact:** Descriptions like `"along the line including lots"` split the main tract in-place, dropping/reshaping call text before geometry extraction and producing truncated or misplaced calls.
- **Why it is a bug:** Not every occurrence of these words denotes an exception/inclusion tract; the splitter performs literal lexical matching without validating clause intent.
- **Suggested fix:** Restrict split detection to exception clause syntax/position (e.g., beginning-of-clause markers) or require stronger grammatical/contextual patterns before splitting.

### 12) Decimal-degree curve deltas are ignored, so curve distance is wrong
- **Location:** `src/metesparser/call_extractor.py` (`CallExtractor.extract_curve_info` and `CallExtractor.extract_single_call`)
- **Issue:** The fallback delta parser accepts only integer degrees/minutes (`(\d+)`), so inputs like `"delta of 90.5 degrees"` are not captured as `delta_deg`.
- **Impact:** For curve calls without explicit arc length, `distance_ft` falls back to the first parsed feet token (often the radius), yielding an incorrect straight-line-like segment distance instead of curve arc length.
- **Why it is a bug:** Legal descriptions commonly include decimal-degree curve deltas; dropping them silently changes geometry magnitude while preserving only partial curve metadata.
- **Suggested fix:** Allow decimal delta capture in the parser (`\d+(?:\.\d+)?` and decimal minutes parsing), then compute/override distance from computed arc length whenever radius+delta exists.
