# Changelog

All notable changes to the metesParser project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

#### Infrastructure
- Gemini LLM provider support with auto-fallback (`GeminiClient`)
- Ground truth JSON files for 24/31 Pennbrook deed validation
- Comprehensive metes and bounds reference document (BLM Manual, Prosser)
- Bug tracking system (`docs/bugs.md`) — all 48 bugs resolved

### Changed
- Version bumped to 0.2.0
- Default Gemini model upgraded to `gemini-3-flash-preview`
- OpenAI calls use `temperature=0` for deterministic extraction
- Removed black formatter — ruff handles all formatting and linting
- Swapped pytest-watch for pytest-watcher (actively maintained)
- Coverage reporting separated from default `make test`
- `make doctor` checks both OpenAI and Gemini providers (active = required, inactive = optional)
- CLI uses `structlog.contextvars` for log context propagation with `run_id` correlation
- Pydantic v2 best practices: `model_copy()`, explicit `default=None`, bool coercion validators
- Makefile streamlined — removed all black references, improved provider checks
- CLAUDE.md scored 100/100 on quality audit (feature table, approximate stats, debug snippets)

### Fixed
- 48 bugs resolved (#20–#48) across Phases 1–5 with TDD regression tests
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
- Added JSON ground truth artifacts alongside source PDFs for PDF extraction comparison and reproducibility.
- Added ground truth folder documentation to describe folder-based extraction validation artifacts.

### Fixed
- Fixed prompt-driven normalization behavior to better preserve numbered-call formatting and line breaks.
- Fixed call-splitting so numbered call notation is prioritized over generic `THENCE` splitting, resolving exception-style split regressions.
- Fixed numbering-related extraction ordering issues in curve/exception parsing edge cases tracked as Bug #19.

### Changed
- Added prompt/ground-truth-oriented workflow updates for PDF validation around extraction and normalization.

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

### Security
- No security vulnerabilities in this release

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

### Changed
- N/A (initial release)

### Fixed
- N/A (initial release)

## [0.0.1] - 2024-10-05

### Added
- Project initialization
- Repository structure
- Basic configuration files

---

## Version Numbering

This project uses [Semantic Versioning](https://semver.org/):

- **MAJOR** version (X.0.0): Incompatible API changes
- **MINOR** version (0.X.0): New functionality in a backward-compatible manner
- **PATCH** version (0.0.X): Backward-compatible bug fixes

## Release Types

- **[Unreleased]**: Changes in development not yet released
- **[X.Y.Z]**: Released versions with dates

## Change Categories

- **Added**: New features
- **Changed**: Changes in existing functionality
- **Deprecated**: Soon-to-be removed features
- **Removed**: Removed features
- **Fixed**: Bug fixes
- **Security**: Security vulnerability fixes

## Links

- [Keep a Changelog](https://keepachangelog.com/)
- [Semantic Versioning](https://semver.org/)

## Migration Guides

### Migrating from 0.3.1 to next release

**CSV Schema**:
CSV output now has 21 fields instead of 16. New fields added across Phases 1–4:
- `is_meander`, `is_tie_in`, `monument_status`, `non_tangent`, `radial_bearing`

**LLM Provider**:
Gemini is now supported as an alternative provider. Set `METESPARSER_LLM_PROVIDER=gemini` and `GEMINI_API_KEY` in `.env`.

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
