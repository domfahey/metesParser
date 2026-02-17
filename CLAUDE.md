# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project: Metes & Bounds Deed Parser

Extracts, parses, and verifies metes and bounds legal descriptions from deed PDFs into structured CSV format. Core function: convert unstructured surveying notation into validated geometric data for GIS plotting.

**Version**: 0.4.0 | **Tests**: ~961 | **Coverage**: ~93%

## Critical Architecture Principles

### 1. Never Fabricate Data
**Most Important Rule**: If a bearing is incomplete (e.g., "southwesterly" without degrees), leave `bearing_azimuth_deg_from_north` as `None` and set `notes="incomplete bearing - cardinal only"`. Never invent numerical bearings.

### 2. Verification Before Export
Traverse must close to < 0.01 ft misclosure before exporting `_verified.csv`. Use `ClosureChecker.verify_closure()` to run all 8 verification checks before calling `CSVBuilder.export_verified_csv()`.

### 3. Preserve Verbatim Deed Language
Keep original wording in `along` and `to` fields. Example: Keep "Southerly line of Pennbrook Drive" exactly as written in the deed.

### 4. GenAI Transparency & Auditability
Build for transparency by design. All LLM-generated outputs must be traceable and auditable — log prompts, responses, and extraction decisions so users can verify what the AI produced vs. what the parser derived deterministically.

## Essential Commands

### Makefile (Primary Interface)
```bash
make help          # Show all commands
make dev-setup     # Initial setup (creates .env from .env.example)
make lint          # Run ruff (excludes text_parser.py)
make format        # Run ruff formatter
make lint-fix      # Auto-fix linting issues
make test          # Run pytest
make test-fast     # Run pytest with fail-fast (stop on first failure)
make test-cov      # Tests with HTML coverage report
make pre-commit    # Full check before git commit
make check         # Run all checks (lint + format-check + type + test)
make clean         # Remove generated artifacts and caches
make doctor        # Verify project dependencies and environment
```

### Direct CLI Usage
```bash
# Extract and verify
uv run metesparser extract deed.pdf
uv run metesparser verify calls.csv --area 7500

# Compare prompt versions across runs
uv run metesparser compare-runs
uv run metesparser compare-runs --pdf pennbrook

# Development
uv run pytest tests/unit/test_bearing_converter.py -v
uv run pytest -k "test_closure" --pdb
```

### UV (REQUIRED - Never use pip/conda/poetry)
```bash
uv venv                    # Create virtual environment
uv sync --all-extras --dev # Install all dependencies
uv add package-name        # Add new dependency
uv run pytest              # Run commands in venv
```

## Data Flow Architecture

### Processing Pipeline
```
PDF → PDFProcessor.process_deed_pdf() → LegalDescription
  ├─ Configured LLM extraction (`OpenAIClient` / `GeminiClient`)
  ├─ Text normalization (TextParser.normalize_legal_description)
  ├─ PLSS metadata (TextParser.extract_plss_metadata)
  ├─ POC/POB extraction (TextParser.extract_poc_and_pob)
  ├─ Area statement (TextParser.extract_area_statement)
  ├─ Call extraction (CallExtractor.extract_calls) [rule-based, not AI]
  ├─ Azimuth enrichment (BearingConverter.enrich_calls_with_azimuths)
  ├─ Tie-in marking (CallExtractor.mark_tie_in_calls)
  ├─ Basis of bearing (TextParser.extract_basis_of_bearing)
  ├─ Surveyor certification (TextParser.extract_surveyor_certification)
  ├─ Prior conveyance (TextParser.extract_prior_conveyance)
  ├─ Deed clauses (TextParser.extract_deed_clauses)
  ├─ Subdivision reference (TextParser.extract_subdivision_reference)
  ├─ Witness trees (TextParser.extract_witness_trees)
  └─ Coordinate system + FIPS (TextParser.extract_coordinate_system)

LegalDescription → ClosureChecker.verify_closure() → ClosureResult
  ├─ Traverse closure (sum dx, dy)
  ├─ 8 verification checks
  └─ Area calculation (shoelace formula)

ClosureResult → CSVBuilder.export_verified_csv() → CSV + Audit
  ├─ Only exports _verified.csv if all checks pass
  ├─ .audit.json sidecar (if audit_context provided)
  └─ .audit.html report (if audit_context provided)
```

### Audit Sidecar (Optional)
When `PDFProcessor.process_deed_pdf(audit=True)`, an `AuditContext` threads through the pipeline:
- **PDFProcessor**: Creates context, captures LLM extraction + confidence scoring (7 heuristic signals)
- **CallExtractor**: Records source excerpts, transformations, decisions, and per-field confidence
- **ClosureChecker**: Records verification check results and closure summary
- **CSVBuilder**: Writes `.audit.json` + `.audit.html` alongside verified CSV
- **AuditReporter**: Self-contained HTML with collapsible sections, confidence color coding

### Key Module Responsibilities

**models.py** - Pydantic schemas
- `DeedCall`: Single course (bearing, distance, curve data)
- `LegalDescription`: Complete deed with calls list + metadata
- `ClosureResult`: Verification results with misclosure and area
- `AuditContext`: Mutable accumulator for audit trail (NOT frozen — extends `BaseModel` directly)
- Audit models: `RunMetadata`, `ExtractionRecord`, `CallAudit`, `Transformation`, `Decision`, `CheckResult`, `VerificationAudit`

**bearing_converter.py** - Coordinate math
- Quadrant bearing ↔ azimuth: `parse_quadrant_bearing()`, `quadrant_to_azimuth()`
- Packed DMS conversion: `parse_packed_dms(46.1631)` → 46.2753° decimal
- Delta calculations: `calculate_deltas(azimuth, distance) → (dx, dy)`
- Curve math: `calculate_curve_properties(radius, delta) → {arc, chord, ...}`

**call_extractor.py** - Rule-based parsing (NOT AI)
- Regex patterns for bearings: `(N|S) \d{1,3}°\d{1,2}' (E|W)`
- Chord bearing extraction: `"chord of which bears S 34°57' E"` → `chord_bearing` field
- Non-tangent curve detection: `"non-tangent"`, `"radial line bears"` → `non_tangent=True`
- Never fabricates - returns `None` for incomplete data
- Preserves verbatim `direction_text`, `along`, `to` fields

**audit_reporter.py** - HTML audit report generation
- `AuditReporter.generate_html()`: Self-contained HTML from `AuditContext`
- Embedded CSS, collapsible `<details>` sections, no external dependencies
- Confidence color coding: green (>=0.8), yellow (0.5-0.8), red (<0.5)
- XSS prevention via `html.escape()` on all user content

**closure_checker.py** - 8 Verification Checks
1. Traverse closure (< 0.01 ft)
2. Interior angles sum ((n-2)*180°)
3. Parallelism checks
4. Curve consistency (L ≈ R*Δ)
5. Area reasonableness (vs stated)
6. Double-entry validation
7. Bearing reversal detection (adjacent courses ~180° apart)
8. Distance reasonableness (short/long/dominant)

**run_registry.py** - Prompt A/B testing
- `RunManifest`, `PromptVersion`, `RunResults`: Pydantic models for per-run tracking
- `get_prompt_versions()`: Git SHA + SHA-256 content hash per prompt YAML
- `write_run_manifest()` / `load_run_manifests()`: Per-run JSON I/O in `runs/` directory
- `format_comparison_table()`: Grouped table comparing runs across prompt versions
- CLI: `metesparser compare-runs [--pdf <name>] [--runs-dir <path>]`

**review_packet.py** - Ground truth review packets
- `generate_review_html()`: Self-contained HTML review page per deed
- `generate_all_packets()`: Batch generation across a sample_deeds directory
- Includes metadata, call table, closure summary, text comparison, and traverse plot (SVG)
- Used for professional surveyor audit of ground truth data

## Bearing Convention (Critical for Calculations)

Azimuth = degrees clockwise from North (0-360):
- N 45° E → 45°
- S 45° E → 135° (180 - 45)
- S 45° W → 225° (180 + 45)
- N 45° W → 315° (360 - 45)

DMS parsing: "S 56°40'30\" W" → (S, 56.675, W) → 236.675° azimuth

## Unit Conversions (models.py — `ConversionFactors`)
- 1 pole = 1 rod = 1 perch = 16.5 ft
- 1 chain = 66 ft | 1 link = 0.66 ft
- 1 vara = 2.778 ft (Texas) | 1 arpent = 191.8 ft (French colonial)
- 1 toise = 6.395 ft | 1 furlong = 660 ft
- 1 meter = 3.28084 ft | 1 mile = 5,280 ft
- 1 engineer chain = 100 ft | 1 engineer link = 1.0 ft
- 1 acre = 43,560 sq ft

## Key Directories
- `scripts/` — standalone utility scripts (extract_sample_deeds.py, generate_ground_truth.py, generate_review_packet.py, backfill_run_registry.py, audit_gt_vs_md.py, parse_pdfs_to_md.sh)
- `docs/reference/` — reference PDFs (BLM manual, etc.) — tracked via `!docs/reference/*.pdf`
- `sample_deeds/` — 63 sample PDFs + ground truth JSON files + LlamaParse markdown conversions (co-located)

## Testing Strategy

### Writing Tests (TDD Approach)
1. Test bearing conversions first (most critical)
2. Test with known parcels (18 Pennbrook parallelogram, 24 Pennbrook, square fixture)
3. Test closure cases where misclosure should be near zero
4. Test incomplete bearing handling (should flag, not fabricate)

### Test File Locations
```bash
tests/unit/test_<module>.py           # Unit tests mirror src/ modules
tests/unit/test_phase*.py             # Phase-specific feature tests
tests/unit/test_bugs_*_tdd.py         # Bug fix regression tests
tests/integration/test_integration.py # Full pipeline (known parcels)
tests/e2e/test_cli_end_to_end.py      # CLI end-to-end
tests/conftest.py                     # Custom markers, logging isolation, deed_call_factory, sample_legal_text
tests/fixtures/sample_deeds.py        # Shared DeedCall fixtures
```

### Running Specific Tests
```bash
uv run pytest tests/unit/test_bearing_converter.py::TestQuadrantToAzimuth::test_ne_quadrant -v
uv run pytest -k "closure" --cov=src/metesparser/closure_checker.py
```

### Expected Test Output
```
~961 passed
```
All tests should pass with no warnings or errors. If you see `FAILED` or `ERROR`, investigate before committing.

## Known Issues & Workarounds

### text_parser.py Linting
**Issue**: Contains Unicode DMS symbols (°, ', ") that break ruff parser
**Workaround**: Excluded in `pyproject.toml` under `[tool.ruff] exclude`
**Action**: Don't try to lint this file - it's functionally correct

### Boolean Field Validation
**Rule**: Do NOT use `strict=True` on boolean `Field()` declarations in `DeedCall`
**Reason**: Contradicts the `_coerce_bool_field` validator that coerces strings ("true"/"false") to bools

### Cardinal Direction Patterns
**Rule**: Cardinal-only patterns must include `(?:erly|wardly)?` suffixes AND abbreviated forms (`NE|NW|SE|SW`)
**Locations**: `call_extractor.py` (`_CARDINAL_ONLY_PATTERN`), `text_parser.py` (`CARDINAL_ONLY_PATTERN`), `scripts/audit_gt_vs_md.py` (`CARDINAL_ONLY_PATTERN`) — all three must stay in sync
**Bug history**: Missing `wardly` suffix caused false negatives (fixed in `d25fcc9`); missing abbreviated cardinals caused call rejection when LLM normalization abbreviated "NORTHWEST" → "NW" (fixed in PR #21)

### LLM Configuration
**Location**: `prompts/*.yaml` files
**Provider Clients**: `OpenAIClient` and `GeminiClient` behind `METESPARSER_LLM_PROVIDER`
**Model**: OpenAI defaults to `gpt-5.2`; Gemini defaults to `gemini-3-flash-preview` with fallback.
**Architecture**: `llm_clients.py` defines `BaseLLMClient` ABC; `PDFProcessor` accepts `provider=` or `client=` for DI
**CLI**: `uv run metesparser extract deed.pdf --llm-provider gemini`

### CSV Schema (21 fields - order matters, defined in `csv_builder.py:51`)
```csv
course,direction_text,bearing_quadrant,bearing_azimuth_deg_from_north,distance_ft,
curve_dir,radius_ft,delta_deg,arc_length_ft,chord_bearing,chord_length_ft,
along,to,monument_type,monument_status,is_exception,is_meander,is_tie_in,
non_tangent,radial_bearing,notes
```

**Field notes:**
- `monument_type`: Auto-classified from "to" field (20 types)
- `monument_status`: "found", "set", or null
- `is_exception`/`is_meander`/`is_tie_in`/`non_tangent`: Boolean flags (CSV: "true"/"false")
- `radial_bearing`: String for non-tangent curves, empty string if N/A
- `is_indefinite`, `curve_type`, `quality`: Model-only fields (not exported to CSV)
- `precision_ratio`: On `ClosureResult`, not `DeedCall`
- `confidence_score`: On `ClosureResult`, not exported to CSV
- `AuditContext`: Separate sidecar output (`.audit.json`), not part of CSV schema

## Feature Reference

| # | Feature | Module | Key Method/Class | Notes |
|---|---------|--------|-------------------|-------|
| 1 | Monument type classification | `call_extractor.py` | `MonumentClassifier.classify_monument()` | Regex-based, specificity-ordered |
| 2 | PLSS metadata | `text_parser.py` | `extract_plss_metadata()` | Section/Township/Range/PM/aliquot |
| 3 | Exception/inclusion clauses | `text_parser.py` | `split_exception_clauses()` | EXCEPT, LESS AND EXCEPT, ALSO |
| 4 | Exception area verification | `closure_checker.py` | `verify_closure()` | Net area = main - exception |
| 5 | POB closure detection | `text_parser.py` | `is_closure_to_pob()` | Checks last 60 chars of call text |
| 6 | POC vs POB distinction | `text_parser.py` | `extract_poc_and_pob()` | COMMENCING at → POC, POINT OF BEGINNING → POB |
| 7 | Packed DMS parsing | `bearing_converter.py` | `parse_packed_dms()` | 46.1631 → 46°16'31" → 46.2753° |
| 8 | Chord bearing extraction | `call_extractor.py` | `extract_curve_info()` | "chord of which bears S 34°57' E" |
| 9 | Non-tangent curve detection | `call_extractor.py` | `extract_curve_info()` | Keywords: non-tangent, radial line bears |
| 10 | Basis of bearing | `text_parser.py` | `extract_basis_of_bearing()` | "bearings based on", "referenced to" |
| 11 | Surveyor certification | `text_parser.py` | `extract_surveyor_certification()` | "I hereby certify", "Certified by:" |
| 12 | Prior conveyance | `text_parser.py` | `extract_prior_conveyance()` | "BEING the same premises", "Deed Book" |
| 13 | Extended distance units | `text_parser.py` | `extract_distance()` | varas, arpents, toises, furlongs, meters, miles |
| 14 | Unit-inference heuristics | `text_parser.py` | `infer_distance_unit()` | Advisory only — TX→varas, LA→arpents |
| 15 | CSV schema (21 fields) | `csv_builder.py` | `FIELDNAMES`, `_call_to_row()` | See CSV Schema section above |
| 16 | Area statement extraction | `text_parser.py` | `extract_area_statement()` | "CONTAINING X sq ft", "X acres more or less" |
| 17 | Abbreviation expansion | `text_parser.py` | `expand_abbreviations()` | IPF, IPS, IRF, IRS, CIP, R/W, N/F, PK |
| 18 | Monument status (found/set) | `call_extractor.py` | `classify_monument_status()` | found/FD/FND → "found", set/placed → "set" |
| 19 | Bearing reversal detection | `closure_checker.py` | `check_bearing_reversals()` | Adjacent courses ~180° apart (5° threshold) |
| 20 | Distance reasonableness | `closure_checker.py` | `check_distance_reasonableness()` | <0.5ft, >10x median, >90% perimeter |
| 21 | Meander/water boundary | `text_parser.py` | `detect_meander()` | Warning-only, NOT auto-excluded from closure |
| 22 | Compound/reverse curves | `call_extractor.py` | `extract_curve_info()` | PCC/PRC keywords → `curve_type` field |
| 23 | Missing curve elements | `bearing_converter.py` | `calculate_missing_curve_elements()` | Any 2+ → all 5; rejects chord>diameter, zero delta |
| 24 | Tie-in call separation | `call_extractor.py` | `mark_tie_in_calls()` | POC-to-POB calls filtered from closure |
| 25 | Indefinite call flagging | `text_parser.py` | `is_indefinite_call()` | Cardinal-only + physical references; needs `has_bearing=False` |
| 26 | Call quality scoring | `closure_checker.py` | `score_call_quality()` | high/medium/low based on bearing + monument + flags |
| 27 | Confidence scoring | `closure_checker.py` | `calculate_confidence_score()` | 0.0–1.0 weighted: closure 30%, checks 20%, bearings 25%, quality 15%, warnings 10% |
| 28 | Enhanced closure summary | `closure_checker.py` | `get_closure_summary()` | Confidence score, precision ratio (1:N), per-call quality breakdown |
| 29 | Audit sidecar (JSON) | `csv_builder.py` | `export_verified_csv(audit_context=)` | `.audit.json` alongside verified CSV |
| 30 | Audit HTML report | `audit_reporter.py` | `AuditReporter.generate_html()` | Self-contained HTML, collapsible sections, confidence colors |
| 31 | LLM confidence scoring | `pdf_processor.py` | `_compute_llm_confidence()` | 7 weighted heuristic signals, 0.0–1.0 |
| 32 | Source excerpt capture | `call_extractor.py` | `extract_calls(audit_context=)` | Verbatim call text preserved per course |
| 33 | Transformation recording | `call_extractor.py` | `_audit_single_call()` | Step-by-step extraction log per field |
| 34 | Verification audit | `closure_checker.py` | `verify_closure(audit_context=)` | CheckResults + closure_summary in audit trail |
| 35 | Run registry | `run_registry.py` | `RunManifest`, `get_prompt_versions()` | Git SHA prompt versioning, per-run JSON, compare-runs CLI |
| 36 | Ground truth review packets | `review_packet.py` | `generate_review_html()`, `generate_all_packets()` | Self-contained HTML with traverse plot, call table, closure summary |

## Environment Setup

Required in `.env`:
```bash
OPENAI_API_KEY=sk-...  # Required if METESPARSER_LLM_PROVIDER=openai
GEMINI_API_KEY=...      # Required if METESPARSER_LLM_PROVIDER=gemini
METESPARSER_LOG_LEVEL=INFO  # Optional, defaults to INFO
```

## Git Workflow
- Never push to `main` - use branches and PRs
- Run `make pre-commit` before committing
- Never commit `.env` or API keys
- Only commit `_verified.csv` files (passed all checks)

### Git Gotchas
- `*.pdf` is globally gitignored — use `mv` not `git mv` for PDFs, add `!path/*.pdf` exceptions
- Pre-commit hooks may reformat files — check `git status` after every commit for new unstaged changes
- `uv.lock` is tracked (not gitignored) — commit lockfile changes with dependency updates
- GitHub remote: `gh repo create --private --source=. --push` if no remote configured
- `gh pr merge` requires clean working tree — `git stash` before merging if unstaged changes exist

## Common Development Patterns

### Adding a New Verification Check
1. Add method to `ClosureChecker` (e.g., `check_bearing_reversal()`)
2. Call from `verify_closure()` and add to warnings list
3. Update `ClosureResult` model if needed
4. Write test in appropriate phase file (e.g., `tests/unit/test_phase3_verification.py`)

### Adding a New DeedCall Field
1. Add field to `DeedCall` in `models.py` (with `Field()` default, no `strict=True` on bools)
2. Add to `FIELDNAMES` in `csv_builder.py` (order matters) and `_call_to_row()`
3. Add to `_CSVDeedCallRow` in `csv_builder.py`
4. Wire extraction into `call_extractor.py` or `text_parser.py`
5. Update fieldnames count test in `test_phase2_enhanced_parsing.py`
6. Add/update fixtures in `tests/fixtures/sample_deeds.py` if needed
7. Add feature tests in appropriate phase test file

### Adding New Unit Support
1. Add conversion factor to `ConversionFactors` in `models.py`
2. Update `convert_to_feet()` method
3. Add to `distance_unit` Literal in `LegalDescription`
4. Test with sample deed using that unit

### Debugging Closure Issues
```python
# Add inside ClosureChecker._compute_traverse(), after the traversal loop
import structlog; log = structlog.get_logger()
for i, call in enumerate(calls):
    log.debug("traverse_step", course=i+1, bearing=call.bearing_quadrant, distance=call.distance_ft)
log.debug("misclosure", dx=f"{misclosure_x:.4f}", dy=f"{misclosure_y:.4f}", total=f"{misclosure:.4f}")
```
