# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project: Metes & Bounds Deed Parser

Extracts, parses, and verifies metes and bounds legal descriptions from deed PDFs into structured CSV format. Core function: convert unstructured surveying notation into validated geometric data for GIS plotting.

**Version**: 0.1.0

## Critical Architecture Principles

### 1. Never Fabricate Data
**Most Important Rule**: If a bearing is incomplete (e.g., "southwesterly" without degrees), leave `bearing_azimuth_deg_from_north` as `None` and set `notes="incomplete bearing - cardinal only"`. Never invent numerical bearings.

### 2. Verification Before Export
Traverse must close to < 0.01 ft misclosure before exporting `_verified.csv`. Use `ClosureChecker.verify_closure()` to run all 8 verification checks before calling `CSVBuilder.export_verified_csv()`.

### 3. Preserve Verbatim Deed Language
Keep original wording in `along` and `to` fields. Example: Keep "Southerly line of Pennbrook Drive" exactly as written in the deed.

## Essential Commands

### Makefile (Primary Interface)
```bash
make help          # Show all commands
make dev-setup     # Initial setup (creates .env from .env.example)
make lint          # Run ruff (excludes text_parser.py)
make format        # Run ruff + black formatters
make lint-fix      # Auto-fix linting issues
make test          # Run pytest
make test-cov      # Tests with HTML coverage report
make pre-commit    # Full check before git commit
```

### Direct CLI Usage
```bash
# Extract and verify
uv run metesparser extract deed.pdf
uv run metesparser verify calls.csv --area 7500

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
  ├─ Call extraction (CallExtractor.extract_calls) [rule-based, not AI]
  ├─ Azimuth enrichment (BearingConverter.enrich_calls_with_azimuths)
  ├─ Basis of bearing (TextParser.extract_basis_of_bearing)
  ├─ Surveyor certification (TextParser.extract_surveyor_certification)
  └─ Prior conveyance (TextParser.extract_prior_conveyance)

LegalDescription → ClosureChecker.verify_closure() → ClosureResult
  ├─ Traverse closure (sum dx, dy)
  ├─ 8 verification checks
  └─ Area calculation (shoelace formula)

ClosureResult → CSVBuilder.export_verified_csv() → CSV
  └─ Only exports _verified.csv if all checks pass
```

### Key Module Responsibilities

**models.py** - Pydantic schemas
- `DeedCall`: Single course (bearing, distance, curve data)
- `LegalDescription`: Complete deed with calls list + metadata
- `ClosureResult`: Verification results with misclosure and area

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

**closure_checker.py** - 8 Verification Checks
1. Traverse closure (< 0.01 ft)
2. Interior angles sum ((n-2)*180°)
3. Parallelism checks
4. Curve consistency (L ≈ R*Δ)
5. Area reasonableness (vs stated)
6. Double-entry validation
7. Bearing reversal detection (adjacent courses ~180° apart)
8. Distance reasonableness (short/long/dominant)

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
- `scripts/` — standalone utility scripts (extract_sample_deeds.py, generate_ground_truth.py)
- `docs/reference/` — reference PDFs (BLM manual, etc.) — tracked via `!docs/reference/*.pdf`
- `sample_deeds/` — sample PDFs + ground truth JSON files (co-located)

## Testing Strategy

### Writing Tests (TDD Approach)
1. Test bearing conversions first (most critical)
2. Test with known parcels (18 Pennbrook parallelogram, 24 Pennbrook, square fixture)
3. Test closure cases where misclosure should be near zero
4. Test incomplete bearing handling (should flag, not fabricate)

### Test File Locations
```bash
tests/unit/test_bearing_converter.py  # Quadrant ↔ azimuth
tests/unit/test_call_extractor.py     # Regex parsing
tests/unit/test_closure_checker.py    # Core 8 verification checks
tests/unit/test_phase1_foundation.py  # Units, monuments, precision ratio, non-tangent
tests/unit/test_phase2_enhanced_parsing.py # Packed DMS, chord/non-tangent, extractors, CSV 21-field
tests/unit/test_phase3_verification.py  # Area extraction, monument status, abbreviations, bearing reversal, distance checks
tests/unit/test_phase4_geometric.py   # Meander detection, tie-in calls, curve types, indefinite bearings
tests/unit/test_pydantic_guardrails.py # Model validation and normalization
tests/integration/test_integration.py        # Full pipeline
tests/integration/test_pdf_processing.py       # PDF extraction orchestration
tests/unit/test_pdf_processor_llm.py          # Provider behavior
```

### Running Specific Tests
```bash
uv run pytest tests/unit/test_bearing_converter.py::TestQuadrantToAzimuth::test_ne_quadrant -v
uv run pytest -k "closure" --cov=src/metesparser/closure_checker.py
```

## Known Issues & Workarounds

### text_parser.py Linting
**Issue**: Contains Unicode DMS symbols (°, ', ") that break ruff/black parsers
**Workaround**: Excluded in `pyproject.toml` under `[tool.ruff] exclude`
**Action**: Don't try to lint this file - it's functionally correct

### LLM Configuration
**Location**: `prompts/*.yaml` files
**Provider Clients**: `OpenAIClient` and `GeminiClient` behind `METESPARSER_LLM_PROVIDER`
**Model**: OpenAI defaults to `gpt-5.2`; Gemini defaults to `gemini-3-flash-preview` with fallback.
**Architecture**: `llm_clients.py` defines `BaseLLMClient` ABC; `PDFProcessor` accepts `provider=` or `client=` for DI
**CLI**: `uv run metesparser extract deed.pdf --llm-provider gemini`

### CSV Schema (21 fields - order matters)
```csv
course,direction_text,bearing_quadrant,bearing_azimuth_deg_from_north,distance_ft,
curve_dir,radius_ft,delta_deg,arc_length_ft,chord_bearing,chord_length_ft,
along,to,monument_type,monument_status,is_exception,is_meander,is_tie_in,
non_tangent,radial_bearing,notes
```

**New in v0.2:**
- `monument_type`: Auto-classified from "to" field (iron_rod, iron_pin, iron_pipe, stone, concrete, wooden_post, brass_cap, rebar, railroad_spike, nail, pk_nail, hub_and_tack, monitoring_well, capped_pin, capped_rod, txdot_monument, other)
- `monument_status`: Found/set distinction ("found", "set", or null)
- `is_exception`: Boolean flag for EXCEPT/LESS AND EXCEPT clause calls

**New in Phase 1:**
- `non_tangent`: Boolean flag for non-tangent curves
- `radial_bearing`: Radial bearing string for non-tangent curves
- `is_meander`: Boolean flag for water boundary (meander line) calls
- `is_tie_in`: Boolean flag for tie-in calls between POC and POB
- `precision_ratio` on `ClosureResult`: Misclosure/perimeter ratio for survey quality

## Recent Enhancements (v0.2)

### 1. Monument Type Classification
- **Module**: `call_extractor.py` - `MonumentClassifier` class
- **Feature**: Automatically classifies survey markers from the "to" field
- **Supported Types**: iron_rod, iron_pin, iron_pipe, stone, concrete, wooden_post, brass_cap, rebar, railroad_spike, nail, other
- **Pattern Matching**: Regex-based classification with specificity ordering
- **Use Case**: Helps assess survey reliability (e.g., iron monuments are more permanent than wooden posts)

### 2. PLSS (Public Land Survey System) Support
- **Module**: `text_parser.py` - `extract_plss_metadata()` method
- **Fields Added to LegalDescription**: section, township, range, principal_meridian, aliquot
- **Extraction**: Automatically parses Section/Township/Range/PM from deed text
- **Formats Supported**: "Section 12, Township 15 N, Range 3 E, Willamette PM" and abbreviated forms
- **Use Case**: Essential for western US deeds, locates parcel within broader survey system
- **Integration**: `pdf_processor.py` calls this automatically during deed processing

### 3. Exception/Inclusion Clause Handling
- **Module**: `text_parser.py` - `split_exception_clauses()` method
- **Keywords**: EXCEPT, EXCEPTING, LESS AND EXCEPT, ALSO, INCLUDING
- **Functionality**: Splits legal description into main tract and exception/inclusion tracts
- **Marking**: Calls in exception tracts have `is_exception=True`
- **Area Calculation**: `closure_checker.py` subtracts exception areas from main area
- **Use Case**: Handles complex deeds like "All of Lot 5 EXCEPT the North 50 feet thereof"
- **Warnings**: Adds warnings to ClosureResult when exception tracts are found

### 4. Enhanced Area Verification
- **Module**: `closure_checker.py` - `verify_closure()` method
- **Change**: Now handles exception tracts separately
- **Process**:
  1. Separates main tract from exception calls
  2. Computes area for each independently
  3. Net area = main area - exception area
  4. Adds warnings about exception tracts
- **Validation**: Closure checks run on main tract only

### 5. POB Closure Detection (Phase 2A)
- **Module**: `text_parser.py` - `is_closure_to_pob()` method
- **Feature**: Detects when a deed call indicates closure back to Point of Beginning
- **Patterns Detected**: "to [the] [point of] beginning", "to [the] POB", "returning to beginning", "back to POB"
- **Smart Matching**: Only checks last 60 characters of call text to avoid false positives
- **Use Case**: Identifies the final call that closes the parcel traverse (essential for verification)
- **Testing**: 8 test cases covering various closure patterns and edge cases
- **Implementation**: Case-insensitive regex patterns with word boundaries

### 6. POC vs POB Distinction (Phase 2B)
- **Module**: `text_parser.py` - `extract_poc()`, `extract_poc_and_pob()` methods
- **Concept**: Distinguishes Point of Commencement (survey reference) from Point of Beginning (parcel boundary)
- **Pattern Recognition**: Extracts POC only when text contains both "COMMENCING at" AND later "POINT OF BEGINNING"
- **Model Update**: Added `poc_description` field to `LegalDescription` class
- **CSV Export**: POC included in metadata file alongside POB
- **Example**:
  ```
  COMMENCING at NW corner of Section 12;        ← POC (reference point)
  THENCE S 89° E 100 feet to the                ← Tie-in call
  POINT OF BEGINNING;                            ← POB (parcel starts here)
  THENCE N 45° E 200 feet...                     ← Boundary calls begin
  ```
- **Use Case**: Essential for understanding survey methodology and locating parcel from control points
- **Testing**: 6 test cases covering POC extraction, POB-only scenarios, and combined extraction
- **Integration**: `pdf_processor.py` automatically extracts both during processing

## Phase 2 Enhancements (Enhanced Parsing)

### 7. Packed DMS Parsing
- **Module**: `bearing_converter.py` - `parse_packed_dms()` method
- **Feature**: Converts packed DMS values (e.g., 46.1631 → 46°16'31" → 46.2753°)
- **Formula**: `degrees + minutes/60 + seconds/3600` where MM.SS are extracted from fractional part
- **Validation**: Raises `ValueError` for minutes >= 60 or seconds >= 60

### 8. Chord Bearing Extraction
- **Module**: `call_extractor.py` - within `extract_curve_info()`
- **Patterns**: `"chord of which bears S 34°57' E"`, `"chord bears"`, `"the chord bears"`
- **Normalization**: Spelled-out cardinals standardized via `TextParser.standardize_cardinal_directions()`
- **Storage**: Populates `chord_bearing` field as normalized quadrant bearing string

### 9. Non-Tangent Curve Detection
- **Module**: `call_extractor.py` - within `extract_curve_info()`
- **Keywords**: `non-tangent`, `nontangent`, `radial line bears`, `radial bearing of`
- **Fields Populated**: `non_tangent=True`, `radial_bearing="N 15°22' E"`
- **Integration**: `extract_single_call()` reads from `curve_info` dict (no longer hardcoded)

### 10. Basis of Bearing Extraction
- **Module**: `text_parser.py` - `extract_basis_of_bearing()` method
- **Patterns**: "Basis of Bearings:", "bearings based on", "referenced to", "bearings are magnetic/assumed"
- **Integration**: Wired into `process_deed_pdf()` — replaces hardcoded `None`

### 11. Surveyor Certification Extraction
- **Module**: `text_parser.py` - `extract_surveyor_certification()` method
- **Patterns**: "That I, [name]," + "Licensed/Registered", "I hereby certify", "Certified by:", "Surveyed by"
- **Model Field**: `surveyor_certification: str | None` on `LegalDescription`

### 12. Prior Conveyance Extraction
- **Module**: `text_parser.py` - `extract_prior_conveyance()` method
- **Patterns**: "BEING the same premises", "Deed Book \d+", "Instrument Number", "Official Records Book"
- **Model Field**: `prior_conveyance: str | None` on `LegalDescription`

### 13. Extended Distance Unit Parsing
- **Module**: `text_parser.py` - `extract_distance()` method (extended)
- **New Units**: varas, arpents, toises, furlongs, meters, miles (singular + plural)
- **Conversion**: Uses existing `ConversionFactors` from Phase 1

### 14. Unit-Inference Heuristics
- **Module**: `text_parser.py` - `infer_distance_unit()` method
- **Advisory Only**: Returns suggestion string, caller decides whether to apply
- **Rules**: Texas pre-1900 → varas, Louisiana → arpents, New England pre-1850 → rods, "chains and links" → chains
- **Text Keywords**: Detects "varas", "arpents" in deed text

### 15. CSV Schema Expansion (16 → 21 fields)
- **Module**: `csv_builder.py` - `FIELDNAMES`, `_call_to_row()`
- **New Fields**: `monument_status` (Phase 3), `is_meander`, `is_tie_in`, `non_tangent` ("true"/"false"), `radial_bearing` (string or "")
- **Position**: `monument_status` after `monument_type`; `is_meander`/`is_tie_in` after `is_exception`; `non_tangent`/`radial_bearing` before `notes`
- **Metadata Export**: `surveyor_certification` and `prior_conveyance` added to `.metadata.txt`

## Phase 3 Enhancements (Enhanced Verification)

### 16. Area Statement Extraction
- **Module**: `text_parser.py` - `extract_area_statement()` method
- **Patterns**: "CONTAINING X square feet", "X acres more or less", "approximately X acres"
- **Model Fields**: `stated_area_sq_ft`, `stated_area_approximate` on `LegalDescription`

### 17. Survey Abbreviation Expansion
- **Module**: `text_parser.py` - `expand_abbreviations()` method
- **Abbreviations**: IPF, IPS, IRF, IRS, CIP, CMP, R/W, ROW, N/F, PK, Con Mon F
- **Integration**: Wired into `normalize_legal_description()`

### 18. Found/Set Monument Status
- **Module**: `call_extractor.py` - `MonumentClassifier.classify_monument_status()`
- **Keywords**: found/FD/FND → "found", set/placed → "set"
- **Model Field**: `monument_status` on `DeedCall`, CSV field after `monument_type`

### 19. Bearing Reversal Detection
- **Module**: `closure_checker.py` - `check_bearing_reversals()` method
- **Logic**: Adjacent courses ~180° apart (within 5° threshold) suggest quadrant transcription error

### 20. Distance Reasonableness Checks
- **Module**: `closure_checker.py` - `check_distance_reasonableness()` method
- **Flags**: < 0.5 ft (short), > 10x median (long), > 90% perimeter (dominant)

## Environment Setup

Required in `.env`:
```bash
OPENAI_API_KEY=sk-...  # Required if METESPARSER_LLM_PROVIDER=openai
GEMINI_API_KEY=...      # Required if METESPARSER_LLM_PROVIDER=gemini
LOG_LEVEL=INFO          # Optional, defaults to INFO
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
- Default branch is `main` — rename with `gh api repos/OWNER/REPO/branches/master/rename -X POST -f new_name=main`
- Hooks may auto-commit on both `main` and feature branches — if branches diverge, recreate feature branch from main
- `gh pr merge` requires clean working tree — `git stash` before merging if unstaged changes exist

## Common Development Patterns

### Adding a New Verification Check
1. Add method to `ClosureChecker` (e.g., `check_bearing_reversal()`)
2. Call from `verify_closure()` and add to warnings list
3. Update `ClosureResult` model if needed
4. Write test in appropriate phase file (e.g., `tests/unit/test_phase3_verification.py`)

### Adding New Unit Support
1. Add conversion factor to `ConversionFactors` in `models.py`
2. Update `convert_to_feet()` method
3. Add to `distance_unit` Literal in `LegalDescription`
4. Test with sample deed using that unit

### Debugging Closure Issues
```python
# In closure_checker.py, after computing traverse:
for i, (call, point) in enumerate(zip(calls, points)):
    print(f"Course {i+1}: {call.bearing_quadrant} {call.distance_ft}ft → {point}")
print(f"Misclosure: ({misclosure_x:.4f}, {misclosure_y:.4f}) = {misclosure:.4f}ft")
```

## Reference: Playbook Compliance

This implementation follows the comprehensive "Metes & Bounds – Deed Call Extraction Playbook" with:
- Never fabricate bearings (Section 8A)
- Close traverse before export (Section 6A)
- 8 verification checks (Section 6 + supplementary)
- Standard 21-field CSV schema (Section 5)
- Preserve verbatim wording (Section 7)
- Flag meanders/approximations (Section 8A)
