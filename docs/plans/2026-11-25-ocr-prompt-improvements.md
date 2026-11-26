# OCR Prompt Error Analysis and Improvement Plan

- **Date:** 2026-11-25
- **Status:** Experiments 1–3 implemented and validated (`normalize_text.yaml`, `locate_legal_pages.yaml`, `mp-ocr` preprocessing + image clients + Stage 3 guard + escalation policy, `Pipeline` blind escalation, `scripts/eval_model_vs_gt.py` CLI)
- **Scope:** Full 87-deed / 648-course ground-truth corpus (`sample_deeds/`) evaluated through `scripts/eval_model_vs_gt.py` using `mp-ocr` (`OpenRouterClient`, `reasoning_effort="low"`, single-model / no fallback, 8 workers).

## 1. Baseline Benchmark Results (`main` @ `34c807c`)

| Metric | `anthropic/claude-haiku-5.5` | `anthropic/claude-sonnet-5.5` |
|---|---|---|
| Deeds exact (normalized) | **82/87 (94.3%)** (`82/86 = 95.3%` excl. missing-page `7535-933`) | **81/87 (93.1%)** (`81/86 = 94.2%` excl. `7535-933`) |
| Deeds exact (legal stage) | **82/87 (94.3%)** | **82/87 (94.3%)** |
| Metes-and-bounds deeds exact | 75/80 | 74/80 |
| Zero-call deeds exact | 7/7 | 7/7 |
| Courses exact (normalized) | **638/648 (98.5%)** (`638/644 = 99.1%` excl. `7535-933`) | **636/648 (98.1%)** (`636/644 = 98.8%` excl. `7535-933`) |
| Courses exact (legal stage) | 638/648 (98.5%) | 638/648 (98.5%) |
| Stage 3 normalization regressions | **0** | **1** (`219 Berlin Rd 12941-00156`) |
| API errors / Markdown leaks | 0 / 0 | 0 / 0 |
| Tokens (prompt / completion) | 2,024,528 / 692,141 | 2,023,279 / 614,921 |
| Reported cost | **$0.5485** | **$10.1958** (18.6x Haiku) |
| Wall time | 300.37s | 389.81s |

### Stage-Level Takeaways

1. **Stage 2 (`extract_legal_description.yaml`) introduced 0 errors across all 174 runs** (87 deeds x 2 models). Leave it unchanged unless stage boundaries are intentionally refactored.
2. **Stage 3 (`normalize_text.yaml`) added 0 wins and 1 regression across all 174 runs:** `norm` beat `legal` on **0 deeds / 0 courses** for either model, while `legal` beat `norm` on `219 Berlin Rd (12941 - 00156)` (16/16 vs 14/16 on Sonnet).
3. **Haiku 5.5 and Sonnet 5.5 fail in opposite modes:**
   - **Haiku 5.5** had **0 clean-text / attention slips**; every recoverable miss was a visually degraded or watermark-occluded glyph.
   - **Sonnet 5.5** outperformed Haiku on **4 of 6 degraded/watermarked glyphs**, but suffered **4 clean-text attention or ordering slips** on sharp print where Haiku passed 100%.
   - Excluding the unrecoverable missing-page PDF (`7535-933`), **5 of the 7 remaining recoverable failing deeds were 100% exact on the other model**; on the 6th (`89 Haddon Ave`), Haiku got the distance right while Sonnet got the bearing right. Only 2 single-digit stroke dropouts (`2 Walnut St` c12 `130.48` and c17 `248.31`) failed both models.

---

## 2. Error Categorization (All 11 Model-Deed Misses Across 8 Unique Deeds)

Every failing page was rendered at 300 DPI and visually inspected against Stage 1 (`S1`), Stage 2 (`S2`), and Stage 3 (`S3`) transcripts.

| Cat | Root Cause | Stage | Deeds / Courses | Models Affected | Visual State on 300 DPI Scan | Prompt Fixability |
|---|---|---|---|---|---|---|
| **A** | Unrecoverable missing PDF page | Source PDF | `8 Kings Highway W (7535 - 933)` (4 courses, `0/4`) | Both | Literal Camden County "Missing Page Certificate" (Schedule C mis-recorded as p. 932A inside `7535-929.pdf`) | **None** (true corpus ceiling: **86/87 deeds, 644/648 courses**) |
| **B** | Normalization course-order swap | Stage 3 (`normalize_text`) | `219 Berlin Rd (12941 - 00156)` c9–c10 (`10)` emitted before `(9)`) | Sonnet only | N/A — `S1` and `S2` were **16/16 exact** | **High** via prompt; **100%** eliminable deterministically |
| **C1** | Clean-text lookahead distance copy | Stage 1 (`extract_text_from_pdf`) | `2 Walnut St (5030 - 535)` c4 (`172` -> `81.52`, copied from c5 two lines below) | Sonnet only | **Crystal clear**, zero watermark | **High** |
| **C2** | Repetitive-bearing `30 -> 00` minutes collapse | Stage 1 (`extract_text_from_pdf`) | `36 Kresson Rd (9476 - 462)` c9 (`N 73°30'00" W` -> `N 73°00'00" W`)<br>`36 Kresson Rd (9888 - 954)` c8 (`S 16°30'00" W` -> `S 16°00'00" W`) | Sonnet only (both deeds) | **Razor-sharp bold laser print**, watermark misses all bearing digits; Exhibit A is on the **final page** (p. 6/6 and p. 5/5) after 14.8k–16.1k chars of NJ tax forms (`GIT/REP-3`, `RTF-1`) | **High** |
| **D** | Green watermark occlusion over faint glyph | Stage 1 (`extract_text_from_pdf`) | `89 Haddon Ave (4732 - 544)` c3 bearing (`S 19°58'30" W` -> `S 19°08'30" W`) | Haiku only | Diagonal green `"This is not an official document"` (`"of"`) crosses directly over faint `58` | **Moderate** (stronger with green-channel strip / crop) |
| **E** | Degraded typewriter / photocopy thin-stroke digit confusion | Stage 1 (`extract_text_from_pdf`) | `3 -> 1`: `2 Walnut St (5030)` c12 `130.48 -> 110.48` (**both**), c14 `35.37 -> 15.37` (Haiku)<br>`8 -> 0`: `2 Walnut St (5030)` c17 `248.31 -> 240.31` (**both**), `26 Chews Landing (5056)` c1 `299.89 -> 299.09` (Haiku)<br>`6 -> 0`: `101-111 KH (11353)` c31 `21.64 -> 21.04` (Haiku)<br>`6 -> 5`: `89 Haddon Ave (4732)` c3 dist `146.44 -> 145.44` (Sonnet) | 5 Haiku, 3 Sonnet (2 shared) | Broken horizontal strokes on typewriter `3`, faint crossbar on `8` (or hand-overstruck `8` over `0`), open/faint top or bottom curve on `6` | **Low-to-moderate** on the 4 single-model misses; **hard floor** via prompt alone on the 2 shared drops (`130.48`, `248.31`) |

### Forensic Detail by Category

- **Cat B (`219 Berlin Rd 12941-00156`):** In the original deed, course `10)` is missing its opening parenthesis between `(9)` and `(11)`, surrounded by alternating identical-bearing lines (`(8) N 32°36'00" W`, `(9) S 56°44'06" W`, `10) N 32°36'00" W`, `(11) S 56°44'05" W`). During Stage 3 regeneration of a 40.4k-char source deed, Sonnet emitted `10)` before `(9)`.
- **Cat C1 (`2 Walnut St 5030-535` c4):** Unnumbered prose repeats `"... a distance of 172 feet to a point; thence ... a distance of 81.52 feet; thence ..."`. Sonnet copied `81.52` into c4 while keeping `"to a point"` intact, then emitted `81.52` again on c5. The `172` pixels are completely crisp.
- **Cat C2 (`36 Kresson Rd 9476-462` c9 & `9888-954` c8):** In Exception 1's 4-course rectangle, all four courses have `30 minutes 00 seconds`. On both PDFs, Exhibit A sits at the very end after 4–5 dense pages of NJ tax/recording boilerplate, and Sonnet collapsed one course's `30 minutes 00 seconds` to `00 minutes 00 seconds` despite sharp laser print.
- **Cat D & E:** Every visual misread in the entire 648-course corpus is a single-digit stroke-dropout confusion from `{3↔1, 8↔0, 6↔0, 6↔5, 5↔0}`. No errors occurred in DMS format handling, curves, tract splitting, or unit parsing.

---

## 3. Targeted Prompt Improvements

Keep all three prompt directories synchronized when editing:
- Package prompts: `packages/mp-ocr/src/mp_ocr/prompts/`
- Monolith prompts: `prompts/`
- Packaged root prompts: `src/metesparser/prompts/`

### 3.1 Stage 1 — `extract_text_from_pdf.yaml`

Reference: [extract_text_from_pdf.yaml](../../packages/mp-ocr/src/mp_ocr/prompts/extract_text_from_pdf.yaml)

1. **Add `<anti_slip_course_verification>` (targets Cat C1 & C2):**
   - **Line/course isolation:** When transcribing continuous prose with repeated templates (`"a distance of ___ feet; thence ... a distance of ___ feet"`), read each course's bearing and distance strictly from its own line on the page — never copy a number from the preceding or following course.
   - **Independent DMS digit reading:** Read degrees, minutes, and seconds independently for every course. Do not default minutes to `00` (e.g., collapsing `"30 minutes 00 seconds"` to `"00 minutes 00 seconds"`) on repeated parallel bearings.

2. **Add `<degraded_scan_glyph_guide>` (targets Cat D & E):**
   - **Colored watermark separation:** Ignore colored diagonal watermarks (such as green `"This is not an official document"`). Read only the underlying dark-ink printed text, verifying digits carefully where watermark letters cross them.
   - **Same-page font calibration:** On faint typewriter, dot-matrix, or speckled photocopy scans, inspect commonly confused digits closely: `3` vs `1` (broken horizontal loops on `3`), `8` vs `0` (faint middle crossbar or hand-overstruck `8` over `0`), `6` vs `0` / `6` vs `5` (faded top or bottom stroke), and `5` vs `0`. Compare ambiguous digits against clear occurrences of `0, 1, 3, 5, 6, 8` in the **same font on the same page** (checking glyph width, curvature, and baseline).

3. **Address multi-page boilerplate fatigue (targets Cat C2, optional Stage 1 scope decision):**
   - *Conservative option (keeps full-document OCR contract):* Instruct the model to devote maximum character-level precision to Exhibit/Schedule/BEGINNING/THENCE pages while keeping standard cover-sheet/tax-form transcription concise.
   - *Higher-leverage option (requires checking downstream callers/tests of `extract_text_from_pdf()`):* Scope Stage 1 to recording/property identifiers + complete verbatim legal description(s), skipping NJ tax residency forms, affidavits of consideration, and notary jurats. This eliminates 60–85% of output tokens on multi-page deeds like `36 Kresson Rd` and `219 Berlin Rd`.

4. **Non-negotiable guardrail (preserve `<anti_hallucination_warning>`):**
   - Retain [extract_text_from_pdf.yaml](../../packages/mp-ocr/src/mp_ocr/prompts/extract_text_from_pdf.yaml) lines 30–46 unchanged in spirit.
   - **Never** prompt the model to alter digits so opposite courses are reciprocal or so a parcel closes. Doing so violates `AGENTS.md` Rule #1 (*Never Fabricate Data*) and silently corrupts deeds with real recording misprints. All guidance must remain strictly **pixel-faithful**.

### 3.2 Stage 2 — `extract_legal_description.yaml`

Reference: [extract_legal_description.yaml](../../packages/mp-ocr/src/mp_ocr/prompts/extract_legal_description.yaml)

- **No changes planned.** Achieved 0 errors across all 174 runs.

### 3.3 Stage 3 — `normalize_text.yaml`

Reference: [normalize_text.yaml](../../packages/mp-ocr/src/mp_ocr/prompts/normalize_text.yaml)

- Add explicit **course-order and irregular-delimiter preservation** rules to `<normalization_rules>` #5 and `<critical_preservation_requirements>`:
  - Process courses strictly top-to-bottom in exact input order.
  - **Never swap, reorder, omit, or duplicate a course**, even when adjacent courses share identical bearings or have inconsistent course-number punctuation (e.g., `(8)`, `(9)`, `10)`, `(11)` where an opening parenthesis is missing).
  - Verify before finishing that every course label and numeric value from `<original_text>` appears in the exact same order with identical count.

---

## 4. Non-Prompt Complements (Where Prompts Hit a Ceiling)

Aligned with `AGENTS.md` (*"Use deterministic code wherever possible, AI only where needed, and deterministic validation of AI-prepared inputs wherever applicable"*):

1. **Deterministic Stage 3 Integrity Guard — or Skip LLM Stage 3 (eliminates Cat B 100%):**
   - In [extract.py](../../packages/mp-ocr/src/mp_ocr/extract.py), compare the ordered sequence of numeric/bearing tokens (or parsed course count and values) between Stage 2 (`legal_desc_text`) and Stage 3 (`normalized_text`).
   - On any ordering swap, dropped course, or numeric drift (like Sonnet's `219 Berlin Rd` regression), log an audit warning and fall back to Stage 2 / deterministic regex normalization (or retry once).
   - Longer term, evaluate replacing LLM Stage 3 with deterministic normalization altogether, since Stage 3 produced **0 accuracy gains across 174 runs** while adding ~1/3 of LLM calls.

2. **Closure-Triggered Blind Escalation on Failed Deeds (targets Cat C, D, E):**
   - Keep **Haiku 5.5** as the default primary model (`$0.55` / 87 deeds, 0 clean-text slips).
   - Run deterministic `mp-verify` (`verify_closure()`). Every recoverable value error in the corpus breaks parcel closure.
   - **Only on the ~4–5% of deeds that fail closure**, trigger an independent **blind** re-read (never revealing what closure expects!):
     - Render only the legal description page(s) at 300–400 DPI (optionally stripping the green watermark channel via RGB `(G - max(R, B))` masking before vision input), and/or
     - Run a second opinion with **Sonnet 5.5** (or `OPENROUTER_PDF_ENGINE=mistral-ocr`; see [clients.py](../../packages/mp-ocr/src/mp_ocr/clients.py)).
     - When primary and escalation readings disagree, surface the exact course-level discrepancy for human review rather than fabricating a reconciliation.
   - Estimated corpus cost: `$0.55` (Haiku) + ~5 escalated deeds (~`$0.60`) = **~$1.15 total** vs `$10.20` for all-Sonnet.

---

## 5. Recommended Experiment Order & Acceptance Gates

1. **Experiment 1 — Pure Prompt Edits (Stage 1 + Stage 3):**
   - Apply Sections 3.1 (items 1–2) and 3.3 to all three synced prompt directories (`packages/mp-ocr/src/mp_ocr/prompts/`, `prompts/`, `src/metesparser/prompts/`).
   - Run `scripts/eval_model_vs_gt.py` on a targeted subset first: the **6 recoverable failing deeds** + a **10–15 deed regression sentinel set** (space-separated DMS, dual notation, multi-tract, and known-typo deeds to ensure `<anti_hallucination_warning>` still holds).
   - If net-positive with 0 regressions, run the full 87-deed Haiku 5.5 sweep (~`$0.55`) and record before/after metrics.
2. **Experiment 2 — Deterministic Stage 3 Guard:**
   - Implement ordered course/number integrity check in `packages/mp-ocr/src/mp_ocr/extract.py` (with mirror/facade check per `AGENTS.md`), unit-tested against the `219 Berlin Rd` swap fixture.
   - Re-verify `make quality`, `make test`, `make test-packages-cov`, and `tests/unit/test_cross_package_imports.py`.
3. **Experiment 3 — Boilerplate Trimming & Closure-Triggered Escalation (Optional):**
   - Measure impact of legal-page cropping + green-watermark stripping + Sonnet escalation specifically on the remaining Cat D/E deeds (`2 Walnut St 5030`, `89 Haddon Ave 4732`, `26 Chews Landing 5056`, `101-111 KH 11353`).

---

## 6. Experimental Results (2026-11-25)

### 6.1 Experiment 1 — Pure Prompt Edits (19-Deed Panel: 7 Recoverable Failing + 12 Sentinels, 253 Courses)

Added `<degraded_scan_and_watermark_guidance>` and `<anti_slip_course_verification>` to `extract_text_from_pdf.yaml` and strict course-order / irregular-label rules (`(9)` / `10)` / `(11)`) to `normalize_text.yaml` across all three synced directories (`packages/mp-ocr/src/mp_ocr/prompts/`, `prompts/`, `src/metesparser/prompts/`).

| Model | Panel Baseline (`34c807c`) | Exp 1 (`prompt_v1`) | Delta | Sentinels (12 deeds) | Cost |
|---|---|---|---|---|---|
| **Haiku 5.5** | `15/19` deeds, `247/253` courses | `15/19` deeds, `246/253` courses | `0` deeds, **`-1` course** | 12/12 PASS | `$0.1591` |
| **Sonnet 5.5** | `14/19` deeds, `245/253` courses | `16/19` deeds, `247/253` courses | **`+2` deeds, `+2` courses** | 12/12 PASS | `$2.9130` |

**Key findings & disposition:**
- **Stage 3 (`normalize_text.yaml`) — KEPT:** Fixed Sonnet's `219 Berlin Rd (12941 - 00156)` course-order swap (`14/16 -> 16/16`) with 0 regressions across both models and all 12 sentinels.
- **Stage 1 (`extract_text_from_pdf.yaml`) — REVERTED:** Fixed Sonnet's `89 Haddon Ave` c3 distance (`145.44 -> 146.44`), but produced **0/4 fixes and `-1` regression on Haiku** (`89 Haddon Ave` c4 `53.75 -> 93.75`), failed to fix either `36 Kresson Rd` `00`-minute slip on Sonnet, and worsened Sonnet's `2 Walnut St` lookahead slip (`14/17 -> 13/17`, c5 `81.52 -> 23.46`). Confirmed via `pdftotext` that none of the 6 failing PDFs contain an embedded text layer.

### 6.2 Experiment 2 — Deterministic Stage 3 Measurement Integrity Guard (Implemented)

Implemented `verify_normalization_integrity(source_text, normalized_text)` in [extract.py](../../packages/mp-ocr/src/mp_ocr/extract.py) (exported from `mp_ocr`) and wired it into `PDFProcessor.normalize_legal_description` in both [extract.py](../../packages/mp-ocr/src/mp_ocr/extract.py) and [src/metesparser/pdf_processor.py](../../src/metesparser/pdf_processor.py).

- **Invariant:** Extracts ordered canonical DMS bearing tuples and ordered `(value, unit)` distance tuples from Stage 2 and Stage 3. Any reordering, omission, duplication, numeric drift, or empty output logs a warning and falls back to Stage 2 `legal_desc_text` while still recording the raw Stage 3 LLM response in `LLMStageRecord` for auditability.
- **Retrospective validation across all 212 real model runs** (87x2 baseline + 19x2 Exp 1): **0 false positives**; caught `Sonnet / 219 Berlin Rd (12941 - 00156)` (bearing + distance swap) and `Haiku / 8 Kings Highway W (7505 - 1211)` (Stage 3 silently deleted a duplicate tie-in measurement; Stage 2 fallback preserves 4/4 exact).
- **Tests:** Added [packages/mp-ocr/tests/test_normalization_integrity.py](../../packages/mp-ocr/tests/test_normalization_integrity.py) and [tests/unit/test_normalization_integrity_guard.py](../../tests/unit/test_normalization_integrity_guard.py), and aligned one synthetic mock stub ([tests/unit/test_phase6_audit.py](../../tests/unit/test_phase6_audit.py)) so Stage 2 and Stage 3 stub fixtures carry matching course counts.

### 6.3 Experiment 3 — 300 DPI Legal-Page Crop + RGB Green-Watermark Removal (Prototype Benchmark)

Evaluated all **6 Stage-1 failing deeds** (82 courses) by rendering only the legal-description page(s) at 300 DPI, replacing green diagonal watermark pixels (`(G - max(R, B)) > 15`) with contrast-boosted green-channel luminance, auto-cropping empty outer margins (capped at 2200px long edge), and sending the clean PNG(s) via `image_url` through the reverted Stage 1 prompt + Stage 2 + guarded Stage 3.

| Deed (Legal Page(s)) | Haiku Base | Haiku Exp 3 | Sonnet Base | Sonnet Exp 3 |
|---|---|---|---|---|
| `89 Haddon Ave (4732 - 544)` (p. 2) | `5/6` | **`6/6` EXACT** (`$0.0034`) | `5/6` | **`6/6` EXACT** (`$0.0597`) |
| `26 Chews Landing (5056 - 813)` (p. 2) | `4/5` | **`5/5` EXACT** (`$0.0022`) | `5/5` | **`5/5` EXACT** (`$0.0439`) |
| `36 Kresson Rd (9476 - 462)` (p. 6) | `10/10` | **`10/10` EXACT** (`$0.0028`) | `9/10` | **`10/10` EXACT** (`$0.0557`) |
| `36 Kresson Rd (9888 - 954)` (p. 5) | `10/10` | **`10/10` EXACT** (`$0.0028`) | `9/10` | **`10/10` EXACT** (`$0.0551`) |
| `101-111 KH (11353 - 01989)` (pp. 3–5) | `33/34` | `33/34` (`21.04`, `$0.0094`) | `34/34` | **`34/34` EXACT** (`$0.1672`) |
| `2 Walnut St (5030 - 535)` (p. 2) | `14/17` | `14/17` (fixed c14 `35.37`; missed c12/c13/c17, `$0.0044`) | `14/17` | **`15/17`** (fixed c4 `172`; only broken-stroke c12 `130.48` & c17 `248.31` remain, `$0.0696`) |
| **Total (6 Stage-1 failing deeds)** | **2/6** | **4/6 (`78/82`, `$0.0249`)** | **2/6** | **5/6 (`80/82`, `$0.4512`)** |

**Projected full-corpus impact (87 deeds / 86 recoverable, 644 recoverable courses):**
- **Haiku-first + closure-triggered cropped Haiku re-read:** **`84/86 (97.7%)`** recoverable deeds at **`~$0.57` total**.
- **Haiku-first + closure-triggered cropped Sonnet escalation (4–5 failed-closure deeds):** **`85/86 (98.8%)`** recoverable deeds (**`642/644 = 99.7%`** recoverable courses) at **`~$0.89` total** (11x cheaper than all-Sonnet `$10.20`, and +4 deeds / +6 courses more accurate).
- The only 2 remaining course misses in the entire corpus (`2 Walnut St 5030-535` c12 `130.48` and c17 `248.31`) are physically missing horizontal strokes in the 1999 photocopy and are deterministically caught by `mp-verify` closure failure.


### 6.4 Production Wiring & Live End-to-End Validation (Implemented)

Implemented the full closure-triggered blind escalation pipeline with zero hardcoded page numbers:
- [preprocessing.py](../../packages/mp-ocr/src/mp_ocr/preprocessing.py): `count_pdf_pages`, `render_pdf_pages_to_pngs`, `strip_green_watermark_and_crop`, `preprocess_pdf_pages_for_ocr`.
- [clients.py](../../packages/mp-ocr/src/mp_ocr/clients.py), [cache.py](../../packages/mp-ocr/src/mp_ocr/cache.py) (and monolith mirrors [llm_clients.py](../../src/metesparser/llm_clients.py), [llm_cache.py](../../src/metesparser/llm_cache.py)): `generate_text_with_images` across OpenRouter, OpenAI, Gemini, and disk cache.
- [locate_legal_pages.yaml](../../packages/mp-ocr/src/mp_ocr/prompts/locate_legal_pages.yaml) (synced across all 3 prompt directories) + `PDFProcessor.locate_legal_description_pages` / `extract_legal_description_from_images` in [extract.py](../../packages/mp-ocr/src/mp_ocr/extract.py) and [pdf_processor.py](../../src/metesparser/pdf_processor.py).
- [escalation.py](../../packages/mp-ocr/src/mp_ocr/escalation.py) + opt-in `Pipeline(..., escalation_policy=...)` in [pipeline.py](../../src/metesparser/pipeline.py) + `--escalate-policy` / `--escalate-model` flags in [eval_model_vs_gt.py](../../scripts/eval_model_vs_gt.py).

**Live E2E validation (`Haiku 5.5` -> `--escalate-policy unverified --escalate-model anthropic/claude-sonnet-5.5`, 8-deed panel, `$0.6031` total, 0 hardcoded page numbers):**

| Deed | Primary -> Final | Triggered | Auto-Located Pages | Agrees | Selection Reason | Cost |
|---|---|---|---|---|---|---|
| `18 Pennbrook Dr (11985)` (closed control) | `4/4 -> 4/4` | No | — | — | — | `$0.0058` |
| `31 Pennbrook Dr (9777)` (zero-call control) | `0/0 -> 0/0` | No | — | — | — | `$0.0069` |
| `17 Kings Highway W (8494)` (deed-typo control) | `4/4 -> 4/4` | Yes | `[2, 4, 5]` | **Yes** | `readings_agree_confirmed_by_escalation` | `$0.0732` |
| `36 Kresson Rd (9476)` (6-page typo control) | `10/10 -> 10/10` | Yes | **`[6]`** | **Yes** | `readings_agree_confirmed_by_escalation` | `$0.0634` |
| `26 Chews Landing (5056)` | `4/5 -> 5/5` **EXACT** | Yes | `[1, 2]` | No (c1 `299.09->299.89`) | `escalated_passed_closure_where_primary_failed` | `$0.0705` |
| `89 Haddon Ave (4732)` | `4/6 -> 6/6` **EXACT** | Yes | `[1, 2]` | No (c3 `19°08'->19°58'`, c4 `93.75->53.75`) | `escalated_high_dpi_selected_with_disagreement_warning` | `$0.0833` |
| `101-111 KH (11353)` (9-page PDF) | `33/34 -> 34/34` **EXACT** | Yes | `[2, 3, 4, 5]` | No (c12 `21.04->21.64`) | `escalated_high_dpi_selected_with_disagreement_warning` | `$0.2066` |
| `2 Walnut St (5030)` | `14/17 -> 15/17` | Yes | `[1, 2]` | No (c14 `15.37->35.37`) | `escalated_high_dpi_selected_with_disagreement_warning` | `$0.0934` |

### 6.5 Full 87-Deed Corpus Sweep (`Haiku 5.5` -> `--escalate-policy unverified --escalate-model anthropic/claude-sonnet-5.5`)

Output directory: `output/model_eval/exp3_full87_haiku_to_sonnet_unverified/`

| Metric | Haiku 5.5 Baseline (`34c807c`) | Sonnet 5.5 Baseline (`34c807c`) | **Haiku -> Sonnet Escalation (`unverified`)** |
|---|---|---|---|
| Deeds exact (normalized) | `82/87` (`94.3%`) | `81/87` (`93.1%`) | **`85/87` (`97.7%`)** |
| Deeds exact (excl. missing-page `7535-933`) | `82/86` (`95.3%`) | `81/86` (`94.2%`) | **`85/86` (`98.8%`)** |
| Metes-and-bounds deeds exact | `75/80` | `74/80` | **`78/80`** (`78/79 = 98.7%` recoverable) |
| Zero-call deeds exact | `7/7` | `7/7` | **`7/7`** |
| Courses exact (normalized) | `638/648` (`98.5%`) | `636/648` (`98.1%`) | **`642/648` (`99.1%`)** |
| Courses exact (excl. `7535-933`) | `638/644` (`99.1%`) | `636/644` (`98.8%`) | **`642/644` (`99.7%`)** |
| Stage 3 normalization regressions | `0` | `1` | **`0`** |
| API errors / Markdown leaks | `0 / 0` | `0 / 0` | **`0 / 0`** |
| Reported cost | `$0.5485` | `$10.1958` | **`$5.1006`** (50% cheaper than all-Sonnet) |
| Wall time | `300.37s` | `389.81s` | `496.79s` |

**Escalation telemetry across all 87 deeds:**
- **Skipped (0 extra LLM calls):** `33/87` deeds (25 cleanly closed + 8 zero-call/missing-page).
- **Triggered:** `54/87` deeds.
  - **47/54 agreed 100%** (`agrees=True`, `readings_agree_confirmed_by_escalation`), confirming their non-closure is due to genuine source-deed typos or cardinal-only wording rather than OCR error.
  - **5/54 rescued primary OCR errors:** `26 Chews Landing (5056)` (`4/5 -> 5/5`), `89 Haddon Ave (4732)` (`4/6 -> 6/6`), `101-111 KH (11353)` (`33/34 -> 34/34`), `15 E Redman Ave (04462)` (`7/9 -> 9/9` bonus rescue), and `2 Walnut St (5030)` (`14/17 -> 15/17`).
  - **2/54 safe guard fallbacks (pre-fallback run):** On 7-page deeds `116 Kings Highway E (9166 - 536)` and `17 Kings Highway W (8673 - 1087)`, this 87-deed sweep ran prior to adding the automatic all-page fallback; 100-DPI thumbnail triage missed the exhibit page (`[1, 2, 7]`), returning 0 escalated calls, and `escalated_empty_fallback_to_primary` preserved primary (`4/4` exact on both). After adding automatic all-page fallback on empty or truncated located-page extractions, live re-verification on both deeds passed `4/4` exact with `agrees=True` and 0 disagreements.
- **Only 2 remaining course misses in the entire 644-course recoverable corpus:** `2 Walnut St (5030 - 535)` c12 (`130.48` vs `110.48`) and c17 (`248.31` vs `240.31`), where horizontal ink strokes are physically absent in the 1999 scan and `mp-verify` blocks verified export.
