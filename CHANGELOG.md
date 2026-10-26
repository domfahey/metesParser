# Changelog

All notable changes to the metesParser project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Claude plugin workflow for any source document: native text conversion, explicit metes-and-bounds description selection before closure, and deterministic review of the selected boundary.
- Plugin usage/source-preparation references, per-skill READMEs, and a plugin-specific changelog.
- Project motivation, design pillars, and WIP notice to README (PR #35)

### Removed
- Plugin/skill-development guides accidentally shipped as product skills; retain metes-and-bounds workflows and project settings support.

### Fixed
- Backfill registry handles 0-call deeds, removed stale 7535-933 manifest (PR #34)
- Fixed stale test counts, coverage metrics, and outdated references in docs (PR #36)
- Doctor target now correctly reads `.env` values for API key validation (PR #38)

## [0.5.0] - 2026-02-16

### Added
- **Composable Package Architecture** — Refactored monolith into 7 independently installable packages in a uv workspace monorepo (PR #23)
  - `mp-models`: Pydantic schemas, JSONL envelope, units (zero deps)
  - `mp-bearing`: Pure math — azimuth, curves, deltas
  - `mp-ocr`: LLM boundary — PDF → text (OpenAI/Gemini)
  - `mp-parse`: Rule-based parsing — text → calls
  - `mp-verify`: Geometric verification — 8 checks
  - `mp-export`: CSV/JSON/audit HTML output
  - `metesparser`: Pipeline orchestrator + CLI
- `Pipeline` orchestrator class chains mp-ocr → mp-parse → mp-verify → mp-export in a single call
- Cross-package import verification tests (`test_cross_package_imports.py`)
- 24 new sample deeds for 9 properties with ground truth JSON + LlamaParse markdown (PR #30): 1 Walnut St, 101-111 Kings Hwy E, 104 Kings Hwy E, 116 Kings Hwy E, 1350 Brace Rd, 2 Walnut St, 219 Berlin Rd, 36 Kresson Rd, 56 Haddon Ave
- 34 additional sample deeds with ground truth for 4 properties (8 Kings Hwy W, 17 Kings Hwy W, 32/38 Birchall Dr, 26 Chews Landing Rd)
- Total sample deeds: 87 (up from 63) with ground truth JSON + LlamaParse markdown conversions
- Run registry for prompt A/B testing (`run_registry.py`) (PR #14)
- `RunManifest`, `PromptVersion`, `RunResults` Pydantic models for run tracking
- `get_prompt_versions()` — resolves git SHA + content hash per prompt file
- `write_run_manifest()` / `load_run_manifests()` — per-run JSON I/O in `runs/` directory
- `metesparser compare-runs` CLI command — grouped table comparing extraction results across prompt versions
- `--pdf` filter and `--runs-dir` options for compare-runs command
- Run registry backfill script (`scripts/backfill_run_registry.py`) to populate registry from existing ground truth (PR #15)
- Ground truth review packet generator (`review_packet.py`) for professional surveyor audit (PR #16)
- `generate_review_html()` — self-contained HTML with metadata, call table, closure summary, text comparison, and SVG traverse plot
- `generate_all_packets()` — batch generation across a sample_deeds directory
- `scripts/generate_review_packet.py` and `scripts/audit_gt_vs_md.py` utility scripts
- LlamaParse markdown conversions for all sample deeds (GPT-5, max quality settings)
- Unix composable modules design document (`docs/plans/`)

### Changed
- Monolith modules in `src/metesparser/` preserved for backward compatibility alongside new packages
- Updated README, ARCHITECTURE, and CLAUDE.md for composable package architecture (PRs #25, #26, #27, #28)

### Fixed
- Resolve remaining 3 audit failures — 63/63 pass (PR #24)
- Correct ground truth for missing Schedule C and garbled OCR deeds (PR #22)
- Audit script improvements and abbreviated cardinal matching (PR #21)
- Reparsed 4 problem deeds with GPT-5, fixed audit extraction bugs (PR #17)
- Closure semantics for cardinal-only and empty traverses
- Code review findings from composable modules PR (PR #23)

## [0.4.0] - 2026-02-16

### Added

#### Phase 1: Foundation (PR #1)
- 8 new distance units: varas, arpents, toises, furlongs, meters, miles, engineer chains/links
- 6 new monument types: pk_nail, hub_and_tack, monitoring_well, capped_pin, capped_rod, txdot_monument
- `precision_ratio` field on `ClosureResult`; `non_tangent`/`radial_bearing` on `DeedCall`
- Precise US survey foot conversion factor (3937/1200)

#### Phase 2: Enhanced Parsing (PR #2)
- POC vs POB distinction (`extract_poc_and_pob()`)
- Packed DMS parsing (`parse_packed_dms()` — e.g., 46.1631 → 46°16'31")
- Chord bearing extraction from curve descriptions
- Non-tangent curve detection (keywords: "non-tangent", "radial line bears")
- Basis of bearing, surveyor certification, and prior conveyance extraction
- Unit-inference heuristics (advisory: TX → varas, LA → arpents)
- CSV schema expanded from 16 → 18 fields

#### Phase 3: Enhanced Verification (PR #3)
- Area statement extraction ("CONTAINING X sq ft", "X acres more or less")
- Abbreviation expansion (IPF, IPS, IRF, IRS, CIP, R/W, N/F, PK)
- Monument status classification (found/set from deed text)
- Bearing reversal detection (adjacent courses ~180° apart, 5° threshold)
- Distance reasonableness checks (<0.5 ft, >10x median, >90% perimeter)
- CSV schema expanded to 19 fields (`monument_status`)

#### Phase 4: Geometric Completeness (PR #4)
- Missing curve element calculation (any 2 of 5 → all 5: R, Δ, L, C, T)
- Compound/reverse curve detection (PCC/PRC keywords → `curve_type` field)
- Tie-in call separation (POC-to-POB calls filtered from closure)
- Indefinite call flagging (cardinal-only + physical references)
- Meander/water boundary detection (warning-only, not excluded from closure)
- CSV schema expanded to 21 fields (`is_meander`, `is_tie_in`)

#### Phase 5a: Production Completeness (PR #5)
- Natural monument classification (tree, rock, natural_feature)
- Extended curve properties: tangent (T), external distance (E), middle ordinate (M)
- Degree of curvature parsing (D° → R = 5729.578/D°)
- Clause taxonomy: reservation, subject_to, together_with extraction
- 32-point compass system (mariner's notation → azimuth conversion)
- Subdivision lot/block extraction and TPOB/RPOB recognition
- Witness tree extraction
- Spiral curve detection
- State Plane Coordinate System (SPCS) metadata extraction
- File-based LLM response caching (`CachedLLMClient`, enabled by default)

#### Phase 5b: Quality Scoring (PR #6)
- Call quality scoring (`score_call_quality()` — high/medium/low)
- Confidence scoring (`calculate_confidence_score()` — 0.0–1.0 weighted composite)
- Enhanced closure summary with confidence, precision ratio (1:N), per-call quality

#### Phase 6: Audit Sidecar — Transparency by Design (PR #13)
- Audit data models: `AuditContext`, `RunMetadata`, `ExtractionRecord`, `CallAudit`, `Transformation`, `Decision`, `CheckResult`, `VerificationAudit`
- `PDFProcessor.process_deed_pdf(audit=True)` returns `(LegalDescription, AuditContext)` tuple
- LLM extraction confidence scoring with 7 weighted heuristic signals (POB, bearings, closure language, distances, text length, PLSS, garbled chars)
- Source excerpt capture: verbatim call text preserved per course in `CallAudit.source_excerpt`
- Transformation recording: step-by-step extraction log (bearing, azimuth, distance, monument)
- Per-field parse confidence: 0.95 (exact regex), 0.90 (specific monument), 0.60 (generic), 0.40 (cardinal-only)
- Verification audit recording: `CheckResult` per verification check + closure summary
- `.audit.json` sidecar written alongside `_verified.csv` (via `CSVBuilder.export_verified_csv(audit_context=)`)
- `.audit.html` report: self-contained HTML with embedded CSS, collapsible sections, confidence color coding (green/yellow/red), XSS prevention
- `AuditReporter` module for HTML report generation (no external dependencies)

#### Infrastructure
- Gemini LLM provider support with auto-fallback (`GeminiClient`)
- Ground truth JSON files for 24/31 Pennbrook deed validation
- Comprehensive metes and bounds reference document (BLM Manual, Prosser)
- Bug tracking system (`docs/bugs.md`) — all 48 bugs resolved

### Changed
- Version bumped to 0.4.0 (pyproject.toml + __init__.py now in sync)
- Default OpenAI model upgraded from `gpt-4.1` to `gpt-5.2`
- Default Gemini model upgraded to `gemini-3-flash-preview`
- OpenAI calls use `temperature=0` for deterministic extraction
- Removed black formatter — ruff handles all formatting and linting
- Swapped pytest-watch for pytest-watcher (actively maintained)
- Coverage reporting separated from default `make test`
- `make doctor` checks both OpenAI and Gemini providers (active = required, inactive = optional)
- CLI uses `structlog.contextvars` for log context propagation with `run_id` correlation
- Pydantic v2 best practices: `model_copy()`, explicit `default=None`, bool coercion validators (PRs #8, #9, #11)
- Makefile streamlined — removed all black references, improved provider checks
- CLAUDE.md scored 100/100 on quality audit (feature table, approximate stats, debug snippets)

### Fixed
- 48 bugs resolved (#20–#48) across Phases 1–5 with TDD regression tests
- 5 extraction errors found by ground truth comparison (PR #12)
- Reference doc audit fixes (PR #7)
- CLI logging: `_emit_closure_summary` now logs to structlog in all modes, prints only in console mode
- Arc distance curve parsing — match "arc distance", not just "arc length" (Bug #42)
- Curve math edge cases: 180° delta returns infinity, arc/chord validation guards
- CSV guardrails and bearing test stability
- structlog mode transitions and JSON CLI output hardening
- mypy strict mode: explicit `default=None` in Pydantic `Field()` declarations
- Call extractor distance regex repair
- `check_parallelism` input parameter fix

## [0.3.1] - 2025-10-14

### Added
- JSON ground truth artifacts alongside source PDFs for PDF extraction comparison and reproducibility
- Ground truth folder documentation to describe folder-based extraction validation artifacts
- Prompt/ground-truth-oriented workflow updates for PDF validation around extraction and normalization

### Fixed
- Prompt-driven normalization behavior to better preserve numbered-call formatting and line breaks
- Call-splitting so numbered call notation is prioritized over generic `THENCE` splitting, resolving exception-style split regressions
- Numbering-related extraction ordering issues in curve/exception parsing edge cases (Bug #19)

## [0.3.0] - 2025-10-14

### Added
- GPT-4.1 support for all OpenAI API operations
- `extract_text_from_pdf.yaml` prompt file for PDF text extraction
- Comprehensive prompt optimization using GPT-4.1 best practices
- XML-style delimiters in all prompts for better structure
- Self-reflection prompting techniques ("Think carefully", "Think step-by-step")
- Concrete examples in normalization prompts
- `prompts/README.md` documenting all 4 prompts, pipeline, and usage

### Changed
- **BREAKING**: Migrated all OpenAI API calls to Responses API with GPT-4.1 (previously used Chat Completions for text processing)
- All API calls now exclusively use GPT-4.1 with Responses API (PDF extraction, legal description extraction, normalization, AI call extraction)
- System and user prompts are now combined for Responses API compatibility
- Optimized `extract_text_from_pdf.yaml` with structured sections and precision requirements
- Optimized `extract_legal_description.yaml` with identification markers and extraction rules
- Optimized `normalize_text.yaml` with before/after examples and preservation warnings
- Optimized `extract_calls.yaml` with call anatomy breakdown and JSON schema examples
- Enhanced all prompts with explicit constraints and critical warnings
- Moved inline PDF extraction prompt to YAML file for consistency

### Fixed
- **Bug #18**: GPT-4.1 Responses API compatibility - migrated all API calls from Chat Completions to Responses API
- **Bug #17**: DMS seconds notation now properly supported (e.g., "87 degrees 7 minutes 30 seconds")
  - Fixed normalization pattern that created escaped quotes (`\'`) instead of literal quotes
  - Removed redundant spacing normalization pattern that broke bearing extraction
  - Added lambda pattern to handle seconds in bearing text (`text_parser.py:168`)
- Call #2 extraction for 24 Pennbrook CANJ-115553 now correctly extracts "S 87°08' W" (267.12°)
- Text parser now correctly processes bearings with seconds notation

## [0.2.0] - 2024-10-13

### Added
- Monument type classification system with 11 monument types
- PLSS (Public Land Survey System) metadata extraction
- Exception/inclusion clause handling (EXCEPT, LESS AND EXCEPT, ALSO, INCLUDING)
- Area calculation with exception tract subtraction
- Comprehensive test suite with fixtures and parametrization (147→170 tests)
- Session-scoped pytest fixtures for PDF processing to cache expensive API calls
- Extraction output directory with human-readable reports for all sample deeds
- `extraction_output/README.md` summarizing extraction results
- `test_31_pennbrook_text.py` debug script for testing extraction
- Raw text extraction files for 24 Pennbrook

### Changed
- Reorganized test suite with test infrastructure
- Enhanced test coverage from 147 to 170 tests
- Improved closure checker to handle exception tracts separately
- Updated CSV schema to 16 fields (added `monument_type`, `is_exception`)

### Fixed
- Low priority bugs #11, #14, #16 - improved validation and code quality
- Bug #8: Corrected interior angle check algorithm
- Zero-distance validation in call extractor
- Double normalization bug in `CallExtractor.extract_calls()`
- Call splitting to handle THENCE, numbered, and semicolon-separated formats

## [0.1.0] - 2024-10-12

### Added
- Initial project structure following Python best practices
- Core modules: `bearing_converter.py`, `call_extractor.py`, `closure_checker.py`, `csv_builder.py`
- Pydantic models for `DeedCall`, `LegalDescription`, `ClosureResult`
- PDF processing with OpenAI API integration
- Text normalization with DMS symbol handling
- 6 verification guardrails for closure checking
- CLI interface with `metesparser` command
- Sample deed PDFs for testing (18 Pennbrook, 24 Pennbrook, 31 Pennbrook chain of title)
- Comprehensive documentation in `CLAUDE.md`
- Initial prompt files: `extract_legal_description.yaml`, `normalize_text.yaml`, `extract_calls.yaml`
- Test suite with pytest

## [0.0.1] - 2024-10-05

### Added
- Project initialization
- Repository structure
- Basic configuration files

## Migration Guides

### Migrating from 0.3.1 to 0.4.0

**CSV Schema**:
CSV output now has 21 fields instead of 16. New fields added across Phases 1–4:
- `is_meander`, `is_tie_in`, `monument_status`, `non_tangent`, `radial_bearing`

**Verification Checks**:
Now 8 checks (up from 6). Added: bearing reversal detection, distance reasonableness.

**Audit Sidecar**:
`PDFProcessor.process_deed_pdf(audit=True)` returns `(LegalDescription, AuditContext)` tuple.
`.audit.json` and `.audit.html` files are written alongside `_verified.csv` when `audit_context` is provided to `CSVBuilder.export_verified_csv()`.

**Quality Scoring**:
New fields on `ClosureResult`: `confidence_score` (0.0–1.0) and per-call `quality` (high/medium/low).

**LLM Provider**:
Gemini is now supported as an alternative provider. Set `METESPARSER_LLM_PROVIDER=gemini` and `GEMINI_API_KEY` in `.env`.

**LLM Caching**:
File-based LLM response caching is enabled by default via `CachedLLMClient`.

**Tooling**:
Black has been removed. Ruff handles all formatting and linting. Update any CI scripts that reference `black`.

### Migrating from 0.2.0 to 0.3.0

**OpenAI API Model Changes**:
All API calls now use GPT-4.1 with Responses API instead of GPT-4o/GPT-4o-mini with Chat Completions. No code changes required unless you have custom API calls.

**Prompt Format Changes**:
If you have customized prompts, update them to use XML-style delimiters for better results:
```yaml
system_prompt: |
  <task>
  Your task description here
  </task>

  <critical_rules>
  - Rule 1
  - Rule 2
  </critical_rules>
```

**DMS Seconds Support**:
Bearings with seconds notation (e.g., "87°7'30\"") are now fully supported. Existing extractions may show improved accuracy.

### Migrating from 0.1.0 to 0.2.0

**CSV Schema**:
CSV output now has 16 fields instead of 14. Added:
- `monument_type`: Classified monument type (iron_rod, stone, concrete, etc.)
- `is_exception`: Boolean flag for exception tract calls

**Code Changes**:
Update any code that reads CSV files to handle the new fields.

**Testing**:
Session-scoped fixtures may affect test timing. Use `pytest --cache-clear` if you encounter caching issues.

[Unreleased]: https://github.com/domfahey/metesParser/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/domfahey/metesParser/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/domfahey/metesParser/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/domfahey/metesParser/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/domfahey/metesParser/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/domfahey/metesParser/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/domfahey/metesParser/compare/v0.0.1...v0.1.0
[0.0.1]: https://github.com/domfahey/metesParser/releases/tag/v0.0.1
