# Phase 3: Enhanced Verification & Parsing — Design

> Historical snapshot: This plan/design document captures implementation context on its date. It may not reflect current code, defaults, test counts, or workflow state.


## Context

Phase 1 added foundation models (units, monuments, precision ratio, non-tangent fields). Phase 2 added extraction logic (packed DMS, chord bearings, non-tangent detection, basis of bearing, surveyor certification, prior conveyance, extended distance units, unit inference, CSV 18-field schema). Phase 3 fills remaining parsing and verification gaps identified from the metes and bounds reference document.

**Current state**: 457 tests passing, 94% coverage, on `main` branch.

## Features

### 1. Area Statement Extraction

**Module**: `text_parser.py` — `extract_area_statement()`

Parses deed area statements like:
- "CONTAINING 7,500 square feet, or 0.1722 acres, more or less"
- "containing approximately 5 acres"
- "0.1722 acres more or less"

Returns: `{"value_sq_ft": float, "unit": "sq_ft" | "acres", "approximate": bool}`

**Model**: Add `stated_area_sq_ft: float | None` and `stated_area_approximate: bool` to `LegalDescription`.

**Integration**: Wired into `process_deed_pdf()` and passed to `verify_closure()` — eliminates manual `--area` CLI flag.

### 2. Found/Set Monument Distinction

**Module**: `call_extractor.py` — extend `MonumentClassifier`

New `DeedCall` field: `monument_status: Literal["found", "set"] | None`

Patterns:
- Found: "found", "FD", "FND"
- Set: "set", "placed"

**CSV**: FIELDNAMES 18 → 19 (add `monument_status` after `monument_type`).

### 3. Abbreviation Expansion

**Module**: `text_parser.py` — `expand_abbreviations()`

Expands survey abbreviations: IPF, IPS, IRF, IRS, CIP, CMP, Con Mon F, R/W, ROW, N/F, PK.

Called during `normalize_legal_description()`.

### 4. Bearing Reversal Check

**Module**: `closure_checker.py` — `check_bearing_reversals()`

Flags adjacent courses ~180° apart (within 5°). Returns warnings integrated into `verify_closure()`.

### 5. Distance Reasonableness Check

**Module**: `closure_checker.py` — `check_distance_reasonableness()`

Flags: < 0.5 ft, > 10x median, single course > 90% of perimeter. Returns warnings integrated into `verify_closure()`.

## Files to Modify

| File | Changes |
|------|---------|
| `text_parser.py` | `extract_area_statement()`, `expand_abbreviations()`, wire into normalize pipeline |
| `call_extractor.py` | Monument status classification |
| `models.py` | `monument_status` on DeedCall, `stated_area_sq_ft` + `stated_area_approximate` on LegalDescription |
| `closure_checker.py` | `check_bearing_reversals()`, `check_distance_reasonableness()`, wire into `verify_closure()` |
| `csv_builder.py` | FIELDNAMES 18→19, `monument_status` column |
| `pdf_processor.py` | Wire area extraction into pipeline |
| `tests/unit/test_phase3_verification.py` | New test file (~80 tests) |
