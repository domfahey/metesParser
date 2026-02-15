# Changelog

All notable changes to the metesParser project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Full History Backfill (all commits in repository)

- 435a638 (2026-02-15): test: harden CLI and LLM client exception assertions
- aaf51f6 (2026-02-15): docs: add Prosser presentation content to metes and bounds reference
- 770b908 (2026-02-15): docs: sync bugs audit status with current fixes
- 6a6ab37 (2026-02-15): test: assert missing-pdf error message for read_pdf
- 1aad945 (2026-02-15): docs: enrich metes and bounds reference with BLM Module 3 content
- e64a09a (2026-02-15): test: harden date extraction assertion in report parsing test
- dec07c0 (2026-02-15): fix: resolve prioritized open bugs with tdd
- 1624137 (2026-02-15): docs: audit and reprioritize open bug tickets
- 78c1a8f (2026-02-15): test: add e2e and integration coverage for CLI and pipeline contracts
- c6a78bf (2026-02-15): test: strengthen guardrail assertions and integration checks
- 51f2ba2 (2026-02-15): test: strengthen guardrail and coverage effectiveness assertions
- 8230dcf (2026-02-15): docs: update bugs audit status
- aa74023 (2026-02-15): test: tighten exception-path assertions
- 07c2ff0 (2026-02-15): fix: stabilize parser guardrails and prompts
- 55f9948 (2026-02-15): fix: close bugs 20-24 with TDD
- 2e6c857 (2026-02-15): docs: update CLAUDE.md with session learnings and bug fixes
- 7ec96e2 (2026-02-14): test: strengthen pydantic guardrail checks
- cc114da (2026-02-14): Audit and deduplicate bugs list
- 717468f (2026-02-14): docs: update changelog and quality-gate documentation
- e65cba6 (2026-02-14): Fix type and quality-gate reliability
- 92e1145 (2026-02-14): fix: tighten pydantic guardrails for deed calls
- 65feac1 (2026-02-14): fix: enforce pydantic guardrails for curve and numeric inputs
- b3a30db (2026-02-14): fix: extend lint/format to tests, tighten assertions, document new bugs
- 61ae4ed (2026-02-14): docs: add bugs.md for tracking known issues
- d1bb11b (2026-02-14): feat: add ground truth JSONs for 24/31 Pennbrook and generate script
- 5a35fb6 (2026-02-14): feat: add Gemini LLM provider support and refactor PDF processor
- c5a2b5b (2026-02-14): chore: organize project root - move scripts, PDFs, and ground truth
- 7c41dde (2026-02-14): chore: apply pydantic best practices audit fixes
- 602557b (2026-02-14): test: expand closure checker branch coverage
- 22d007a (2026-02-14): docs: sync documentation with current suite and provider behavior
- 8eda598 (2026-02-14): docs: Add comprehensive metes and bounds legal description reference
- 6697559 (2026-02-14): Add parsed markdown outputs for project PDFs
- c6970e3 (2026-02-14): test: expand coverage for cli and llm clients
- 1d53270 (2026-02-14): chore: improve Makefile for reliability and workflow targets
- 225fbf6 (2025-10-14): feat: Add JSON ground truth files next to source PDFs
- e8a5a4d (2025-10-14): docs: Add ground truth folder for PDF extraction validation
- 124dae0 (2025-10-14): fix: Strengthen prompts to preserve numbered call line breaks
- de370c3 (2025-10-14): fix: Prioritize numbered call detection over THENCE splitting (Bug #19)
- f00ebf9 (2025-10-14): feat: Migrate to GPT-4.1 with OpenAI Responses API and optimize prompts
- 2d9cfa4 (2025-10-14): fix: Use OpenAI file upload API for PDF processing
- 67f5681 (2025-10-14): fix: Update PDF test paths to use sample_deeds/ directory
- 61f9f39 (2025-10-14): docs: Add sample deed PDFs from Camden County Recorder (public records)
- 24ae692 (2025-10-14): feat: Add comprehensive PDF processing test suite (20+ tests)
- 5cb6c2d (2025-10-14): feat: Add POC/POB distinction and closure detection (Phase 2A+2B)
- 5a09d85 (2025-10-14): feat: Add monument classification, PLSS support, and exception handling (v0.2)
- 3a413fa (2025-10-13): docs: Comprehensive documentation overhaul following best practices
- a2672df (2025-10-13): refactor: Enhance test suite with fixtures and parametrization (147→170 tests)
- 58c4497 (2025-10-13): refactor: Create test infrastructure and reorganize test suite
- 70d464c (2025-10-13): fix: Low priority bugs #11, #14, #16 - improve validation and code quality
- bbb269d (2025-10-13): fix: correct interior angle check algorithm (Bug #8)
- c53227a (2025-10-13): style: apply ruff formatting to closure_checker.py
- 12176c9 (2025-10-13): fix: resolve 9 critical/high/medium bugs + add 26 comprehensive tests
- dadad66 (2025-10-13): style: apply ruff formatting to call_extractor.py
- 0c2d925 (2025-10-13): fix: resolve final 2 test failures - complete Phase 1 (121/121 tests passing)
- cca8391 (2025-10-12): Fix curve extraction regex patterns - now 116/121 tests passing
- 71d95b0 (2025-10-12): Fix 132 test failures - align tests with implementation APIs
- a9addb2 (2025-10-12): Enhance code comments for clarity in closure_checker.py
- 0fc5c5d (2025-10-12): Add comprehensive pytest test suite with 155 tests
- d0735ac (2025-10-12): Initial commit: Metes & Bounds Deed Parser

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
- [OpenAI GPT-5 Prompting Guide](https://cookbook.openai.com/examples/gpt-5/gpt-5_prompting_guide)

## Migration Guides

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
