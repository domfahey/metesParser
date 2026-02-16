# Phase 4: Geometric Completeness — Design

> Historical snapshot: This plan/design document captures implementation context on its date. It may not reflect current code, defaults, test counts, or workflow state.


## Context

Phases 1-3 established foundation models, extraction logic, and enhanced verification. Phase 4 addresses remaining geometric gaps between the parser and the reference document (docs/METES_AND_BOUNDS_REFERENCE.md), focusing on real-world scenarios the parser cannot yet handle correctly.

**Current state**: 528 tests passing, 94% coverage, on `main` branch.

## Features

### 1. Meander / Water Boundary Detection

**Module**: `text_parser.py` — `detect_meander()`

Detects when a call references a water boundary. Returns `True` for patterns like:
- "along the creek", "along the river", "along the stream"
- "with the brook", "up the creek", "down the river"
- "meander line", "meandering", "along the shore"
- Water keywords: creek, stream, river, brook, run, branch, kill, pond, lake, shore, bank, thalweg, thread

**Model**: Add `is_meander: bool = False` to `DeedCall`.

**CSV**: Add `is_meander` field (FIELDNAMES 19 → 20, after `is_exception`).

**Verification**: `ClosureChecker` warns when meander calls are present. Does NOT auto-exclude from closure — user decides.

### 2. Compound / Reverse Curve Detection

**Module**: `call_extractor.py` — extend `extract_curve_info()`

Detects PCC and PRC keywords:
- PCC: "point of compound curvature", "PCC", "compound curve"
- PRC: "point of reverse curvature", "PRC", "reverse curve"

**Model**: Add `curve_type: Literal["simple", "compound", "reverse"] | None` to `DeedCall`. `None` for non-curve calls, `"simple"` for standard curves.

**No CSV column** — informational, stored in `notes`.

### 3. Missing Curve Element Calculation

**Module**: `bearing_converter.py` — `calculate_missing_curve_elements()`

Given 2-3 curve elements (radius, arc length, delta, chord length), compute missing ones:
- `L = R * delta_rad`
- `C = 2R * sin(delta/2)`
- `T = R * tan(delta/2)`

**Integration**: Called during `CallExtractor.enrich_calls_with_azimuths()` to fill in missing curve data.

### 4. Tie-In Call Separation

**Module**: `call_extractor.py` — `mark_tie_in_calls()`

When `poc_description` is set, calls before the POB terminus are tie-in calls.

**Model**: Add `is_tie_in: bool = False` to `DeedCall`.

**CSV**: Add `is_tie_in` field (FIELDNAMES 20 → 21, after `is_meander`).

**Verification**: `ClosureChecker.verify_closure()` filters out `is_tie_in=True` calls alongside `is_exception=True`.

### 5. Indefinite Call Flagging

**Module**: `text_parser.py` — `is_indefinite_call()`

Flags calls with vague direction and no precise bearing:
- Cardinal approximations: "northerly", "southwesterly"
- Physical references: "along the road as it now runs", "to the top of the mountain"

**Model**: Add `is_indefinite: bool = False` to `DeedCall`.

**Integration**: Set during `CallExtractor.extract_single_call()` when no quadrant bearing is parsed.

**Verification**: `ClosureChecker` warns when indefinite calls are present.

## Files to Modify

| File | Changes |
|------|---------|
| `models.py` | `is_meander`, `curve_type`, `is_tie_in`, `is_indefinite` on DeedCall |
| `text_parser.py` | `detect_meander()`, `is_indefinite_call()` |
| `call_extractor.py` | Compound/reverse curve detection, `mark_tie_in_calls()`, wire meander/indefinite |
| `bearing_converter.py` | `calculate_missing_curve_elements()` |
| `closure_checker.py` | Filter tie-in calls, warn on meanders/indefinite calls |
| `csv_builder.py` | FIELDNAMES 19 → 21, `is_meander` + `is_tie_in` columns |
| `pdf_processor.py` | Wire tie-in marking into pipeline |
| `tests/unit/test_phase4_geometric.py` | New test file |
