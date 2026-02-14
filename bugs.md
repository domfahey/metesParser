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

### 13) `extract_along_to_fields` matches `along` as a substring, not a keyword
- **Location:** `src/metesparser/text_parser.py` (`TextParser.extract_along_to_fields`)
- **Issue:** Detection uses `lower_text.find("along")` instead of a token-level match.
- **Impact:** Words like `"alongside"` are parsed as if they were `along` clauses. For example, `"N 45°E 100 feet alongside the north fence"` yields `along="side the north fence"` and an empty `to`, corrupting extracted metadata.
- **Why it is a bug:** The parser should only treat the standalone keyword `along` as a field delimiter; substring matches create phantom `along` descriptors.
- **Suggested fix:** Use a word-boundary pattern (e.g., `re.search(r"\\balong\\b")`) on normalized spacing to avoid substring matching.

### 14) Curve direction phrase (`to the right/left`) is misread as endpoint
- **Location:** `src/metesparser/text_parser.py` (`TextParser.extract_along_to_fields`) and downstream `src/metesparser/call_extractor.py` (`CallExtractor.extract_single_call`)
- **Issue:** For curve calls, the phrase `"to the right"` / `"to the left"` (which describes curve direction) is interpreted by the `to` parser as an endpoint.
- **Impact:** `to` field is set to junk text like `"the right having a radius ..."` when a curve call has no explicit endpoint, while the actual endpoint may be absent or different.
- **Why it is a bug:** This drops usable curve intent and injects incorrect endpoint data, because the parser does not distinguish directional `to` from endpoint `to`.
- **Suggested fix:** In `extract_along_to_fields`, when scanning the `along` segment, ignore structural direction phrase tokens (e.g., `to the (left|right)` for curve text) from endpoint detection.

### 15) Double-entry validation misses several curve mismatches
- **Location:** `src/metesparser/closure_checker.py` (`ClosureChecker.compare_double_entry`)
- **Issue:** When either call has curve data, comparison only checks `curve_dir` and radius if both `radius_ft` values are present.
- **Impact:** Discrepancies such as differing `delta_deg` values, or one call missing `radius_ft` while the other has it, are not flagged. This can report false positives as matching entries.
- **Why it is a bug:** Double-entry validation is intended to detect all meaningful geometry differences; omitting these curve fields reduces audit reliability.
- **Suggested fix:** Compare curve geometry consistently whenever either call is a curve (including `delta_deg`, radius presence/values, arc/chord if present) and treat asymmetric curve fields as discrepancies.

### 16) OpenAI client drops response format hints
- **Location:** `src/metesparser/llm_clients.py` (`OpenAIClient.generate_text`, `OpenAIClient.generate_text_with_pdf`)
- **Issue:** Both methods remove `response_mime_type` via `del` and call `self._client.responses.create(...)` without passing the requested format.
- **Impact:** `PDFProcessor.extract_calls_ai` always requests JSON (`response_mime_type="application/json"`), but OpenAI calls ignore this. If the model returns non-JSON text, `extract_calls_ai` JSON parsing fails and AI extraction cannot be used reliably.
- **Why it is a bug:** The API contract for `extract_calls_ai` depends on `response_mime_type`, but the OpenAI backend silently discards that control path.
- **Suggested fix:** Forward `response_mime_type` into OpenAI requests (or map to the provider’s supported response-format mechanism).

### 17) Prompt loading path is hard-coded to source checkout layout
- **Location:** `src/metesparser/pdf_processor.py` (`PDFProcessor.__init__`)
- **Issue:** `prompts_dir` is computed as `Path(__file__).parent.parent.parent / "prompts"`, which assumes prompts live at repo root.
- **Impact:** Installed package layouts do not guarantee prompts are present at that path, so `_load_prompt` can raise `FileNotFoundError` in non-source environments.
- **Why it is a bug:** This breaks prompt loading for packaged deployments, despite being a required runtime dependency for PDF extraction.
- **Suggested fix:** Resolve prompts with package resources/importlib.resources and ensure prompts are declared as package data in `pyproject.toml`.

### 18) `extract_sample_deeds.py` points to a non-existent `sample_deeds` directory
- **Location:** `scripts/extract_sample_deeds.py` (`SAMPLE_DEEDS_DIR`)
- **Issue:** `SAMPLE_DEEDS_DIR` is set to `Path(__file__).parent / "sample_deeds"`, which resolves to `scripts/sample_deeds`.
- **Impact:** The directory does not exist in this repo (the actual folder is `sample_deeds/` at repository root), so the full batch script silently skips every PDF listed in `SAMPLE_PDFS`.
- **Why it is a bug:** Running the documented workflow `uv run python scripts/extract_sample_deeds.py` does not process any deeds, producing an empty report and false sense of success.
- **Suggested fix:** Resolve the path from the project root (`Path(__file__).parent.parent / "sample_deeds"`), or derive it from cwd with a clear relative fallback.

### 19) Ground-truth `notes` field records script mtime instead of generation time
- **Location:** `scripts/generate_ground_truth.py` (`generate_ground_truth`, `notes` field)
- **Issue:** `notes` stores `Path(__file__).stat().st_mtime` from `generate_ground_truth.py`.
- **Impact:** Generated ground-truth metadata reflects the script file modification time, not when each run occurred, and is misleading for audit/reproducibility.
- **Why it is a bug:** In provenance-sensitive workflows, this timestamp is meant to indicate generation context; using source file mtime can regress or lie after edits.
- **Suggested fix:** Use runtime generation timestamp (e.g., `datetime.now(timezone.utc).isoformat()`), ideally with model/provider metadata as well.

### 20) Zero-degree curve distances are dropped as non-calls
- **Location:** `src/metesparser/call_extractor.py` (`CallExtractor.extract_single_call`, lines 197-240)
- **Issue:** When parsed curve data includes a zero-degree deflection, `extract_curve_info` returns `arc_length_ft=0.0`, which the extractor treats as a valid float and overrides `distance_ft` to `0.0` in `extract_single_call`.
- **Impact:** Calls like `"curve to the right radius of 50 feet delta of 0° ..."` are silently skipped (`distance_ft <= 0.0` triggers `None`), so a valid call with a straight-line equivalent segment is lost from output.
- **Why it is a bug:** Zero-degree curves are handled as valid in curve utilities and should either be treated as straight segments (original distance) or as explicit zero-curved geometry, not dropped.
- **Suggested fix:** Only override `distance_ft` from arc length when computed arc length is positive, and/or fall back to the parsed line distance when `delta_deg == 0.0`.

### 21) `metesparser` root package does not expose documented public classes
- **Location:** `src/metesparser/__init__.py` and usage in `README.md:99`, `docs/API.md:8,214`
- **Issue:** `metesparser` root exports only `__version__`, so examples like `from metesparser import PDFProcessor` or `ClosureChecker` fail with `ImportError`.
- **Impact:** The public API advertised in docs and examples is currently non-functional for users importing from package root, creating false negatives in onboarding and user scripts.
- **Why it is a bug:** The docs intentionally use root-level imports, but package `__init__.py` never re-exports those symbols.
- **Suggested fix:** Re-export core public classes in `__init__.py` or update docs to require module-specific imports everywhere.
