# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project: Metes & Bounds Deed Parser

Extracts, parses, and verifies metes and bounds legal descriptions from deed PDFs into structured CSV format. Core function: convert unstructured surveying notation into validated geometric data for GIS plotting.

**Version**: 0.2 (Enhanced with monument classification, PLSS support, exception handling)

## Critical Architecture Principles

### 1. Never Fabricate Data
**Most Important Rule**: If a bearing is incomplete (e.g., "southwesterly" without degrees), leave `bearing_azimuth_deg_from_north` as `None` and set `notes="incomplete bearing - cardinal only"`. Never invent numerical bearings.

### 2. Verification Before Export
Traverse must close to < 0.01 ft misclosure before exporting `_verified.csv`. Use `ClosureChecker.verify_closure()` to run all 6 guardrails before calling `CSVBuilder.export_verified_csv()`.

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
uv run pytest tests/test_bearing_converter.py -v
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
  ├─ OpenAI extraction (prompts/extract_legal_description.yaml)
  ├─ Text normalization (TextParser.normalize_legal_description)
  ├─ Call extraction (CallExtractor.extract_calls) [rule-based, not AI]
  └─ Azimuth enrichment (BearingConverter.enrich_calls_with_azimuths)

LegalDescription → ClosureChecker.verify_closure() → ClosureResult
  ├─ Traverse closure (sum dx, dy)
  ├─ 6 verification guardrails
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
- Delta calculations: `calculate_deltas(azimuth, distance) → (dx, dy)`
- Curve math: `calculate_curve_properties(radius, delta) → {arc, chord, ...}`

**call_extractor.py** - Rule-based parsing (NOT AI)
- Regex patterns for bearings: `(N|S) \d{1,3}°\d{1,2}' (E|W)`
- Never fabricates - returns `None` for incomplete data
- Preserves verbatim `direction_text`, `along`, `to` fields

**closure_checker.py** - 6 Verification Guardrails
1. Traverse closure (< 0.01 ft)
2. Interior angles sum ((n-2)*180°)
3. Parallelism checks
4. Curve consistency (L ≈ R*Δ)
5. Area reasonableness (vs stated)
6. Double-entry validation

## Bearing Convention (Critical for Calculations)

Azimuth = degrees clockwise from North (0-360):
- N 45° E → 45°
- S 45° E → 135° (180 - 45)
- S 45° W → 225° (180 + 45)
- N 45° W → 315° (360 - 45)

DMS parsing: "S 56°40'30\" W" → (S, 56.675, W) → 236.675° azimuth

## Unit Conversions (survey_parser.py)
- 1 pole = 1 rod = 1 perch = 16.5 ft
- 1 chain = 66 ft
- 1 link = 0.66 ft
- 1 acre = 43,560 sq ft

## Testing Strategy

### Writing Tests (TDD Approach)
1. Test bearing conversions first (most critical)
2. Test with known parcels (18 Pennbrook rectangle, 31 Pennbrook 5-sided)
3. Test closure on rectangles (should close to 0.00 ft)
4. Test incomplete bearing handling (should flag, not fabricate)

### Test File Locations
```bash
tests/test_bearing_converter.py  # Quadrant ↔ azimuth
tests/test_call_extractor.py     # Regex parsing
tests/test_closure_checker.py    # 6 guardrails
tests/test_integration.py        # Full pipeline
```

### Running Specific Tests
```bash
uv run pytest tests/test_bearing_converter.py::test_quadrant_to_azimuth -v
uv run pytest -k "closure" --cov=src/metesparser/closure_checker.py
```

## Known Issues & Workarounds

### text_parser.py Linting
**Issue**: Contains Unicode DMS symbols (°, ', ") that break ruff/black parsers
**Workaround**: Excluded in `pyproject.toml` under `[tool.ruff] exclude`
**Action**: Don't try to lint this file - it's functionally correct

### OpenAI API Configuration
**Location**: `prompts/*.yaml` files
**Temperature**: Always 0 for deterministic output
**Model**: gpt-4o for PDF OCR, gpt-4o-mini for text normalization

### CSV Schema (16 fields - order matters)
```csv
course,direction_text,bearing_quadrant,bearing_azimuth_deg_from_north,distance_ft,
curve_dir,radius_ft,delta_deg,arc_length_ft,chord_bearing,chord_length_ft,
along,to,monument_type,is_exception,notes
```

**New in v0.2:**
- `monument_type`: Auto-classified from "to" field (iron_rod, iron_pin, iron_pipe, stone, concrete, wooden_post, brass_cap, rebar, railroad_spike, nail, other)
- `is_exception`: Boolean flag for EXCEPT/LESS AND EXCEPT clause calls

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

## Environment Setup

Required in `.env`:
```bash
OPENAI_API_KEY=sk-...  # Required for PDF processing
LOG_LEVEL=INFO          # Optional, defaults to INFO
```

## Git Workflow
- Never push to `main` - use branches and PRs
- Run `make pre-commit` before committing
- Never commit `.env` or API keys
- Only commit `_verified.csv` files (passed all checks)

## Common Development Patterns

### Adding a New Verification Check
1. Add method to `ClosureChecker` (e.g., `check_bearing_reversal()`)
2. Call from `verify_closure()` and add to warnings list
3. Update `ClosureResult` model if needed
4. Write test in `tests/test_closure_checker.py`

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
- 6 verification guardrails (Section 6)
- Standard 14-field CSV schema (Section 5)
- Preserve verbatim wording (Section 7)
- Flag meanders/approximations (Section 8A)
