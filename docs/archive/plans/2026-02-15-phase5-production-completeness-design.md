# Phase 5: Production Completeness — Design

## Goal

Close all remaining gaps between the METES_AND_BOUNDS_REFERENCE.md and parser capabilities. Adds curve completeness, deed language richness, historical deed support, and lightweight COGO metadata — bringing the parser to production-grade coverage.

## Current State

- Version 0.2.0 (Phases 1-4 complete)
- 619 tests, 94% coverage, 21-field CSV schema
- 25 features implemented (see CLAUDE.md feature table)

## Features

### 1. Degree of Curvature Parsing

**Reference**: Section 5.1, 5.2

Deeds sometimes express curves via D° (central angle subtended by a 100-ft arc) instead of Δ. The arc definition formula: `R = 5729.578 / D°`.

**Module**: `bearing_converter.py` — add `degree_of_curvature_to_radius(degree_of_curve)`
**Module**: `call_extractor.py` — parse "degree of curve" / "degree of curvature" in `extract_curve_info()`

Example deed language:
> "along a curve to the right having a degree of curve of 5°00'00""

### 2. Extended Curve Properties (T, E, M)

**Reference**: Section 5.2

Add tangent length (T), external distance (E), and middle ordinate (M) to curve calculations:
- `T = R × tan(Δ/2)` — already computed in `calculate_missing_curve_elements()`
- `E = R × (1/cos(Δ/2) - 1)` — new
- `M = R × (1 - cos(Δ/2))` — new

**Module**: `bearing_converter.py` — add `external_distance_ft` and `middle_ordinate_ft` to the return dict of `calculate_curve_properties()` and `calculate_missing_curve_elements()`

### 3. Natural Monument Classification

**Reference**: Section 6.1

Extend `MonumentClassifier` with patterns for natural monuments:
- Trees: oak, hickory, elm, pine, walnut, sycamore, etc. (see reference Section 15.4)
- Rock outcrops: "standing rock", "rock outcrop", "large rock"
- Natural features: streams, ridges, shorelines (catch-all)

**Model**: Add `MonumentType` literals: `"tree"`, `"rock"`, `"natural_feature"`
**Module**: `call_extractor.py` — add patterns to `MonumentClassifier.MONUMENT_PATTERNS`

### 4. 32-Point Compass System

**Reference**: Section 3.6

Colonial-era deeds use mariner's compass notation instead of degrees:
- "North by East" → N 11.25° E → azimuth 11.25°
- "North-Northeast" → N 22.5° E → azimuth 22.5°
- "Northeast" → N 45° E → azimuth 45°

**Module**: `bearing_converter.py` — add `compass_point_to_azimuth()` with lookup table for all 32 points
**Module**: `call_extractor.py` — add compass point detection as fallback in `extract_direction()`

### 5. Clause Taxonomy

**Reference**: Section 10.3, 10.4

Currently only EXCEPT/LESS AND EXCEPT handled. Add detection for:
- **Reservation**: "RESERVING unto the Grantor..." — retains a right
- **Subject to**: "SUBJECT TO..." — existing encumbrances
- **Together with**: "TOGETHER WITH..." — additional rights conveyed

These are metadata (not boundary-changing). Store as structured clauses on LegalDescription.

**Model**: Add `DeedClause` model with `clause_type` (Literal) and `text` (str)
**Model**: Add `clauses: list[DeedClause]` field on `LegalDescription`
**Module**: `text_parser.py` — add `extract_deed_clauses()`

### 6. Subdivision Lot/Block Reference Extraction

**Reference**: Section 12

Very common in real deeds:
> "Lot 15, Block 3, PENNBROOK ESTATES, as recorded in Plat Book 14, Page 22"

**Model**: Add `SubdivisionReference` model with `lot`, `block`, `subdivision_name`, `plat_book`, `plat_page`
**Model**: Add `subdivision_ref: SubdivisionReference | None` field on `LegalDescription`
**Module**: `text_parser.py` — add `extract_subdivision_reference()`

### 7. TPOB/RPOB Recognition

**Reference**: Section 7.4

Extend `extract_poc_and_pob()` to recognize:
- "TRUE POINT OF BEGINNING" / "TPOB" / "T.P.O.B." → synonym for POB
- "REMOTE POINT OF BEGINNING" / "RPOB" / "R.P.O.B." → synonym for POB

**Module**: `text_parser.py` — extend POB regex patterns

### 8. Witness Trees / Reference Marks

**Reference**: Section 6.6

Historical surveyors recorded trees near corners:
> "a white oak, 14 inches diameter, bears N 35° W, 12 links distant"

Store verbatim text (preserving deed language per architecture principle #3).

**Model**: Add `witness_trees: list[str]` field on `LegalDescription`
**Module**: `text_parser.py` — add `extract_witness_trees()`

### 9. Spiral Curve Detection

**Reference**: Section 5.6

Spiral (transition) curves are uncommon in property deeds but may appear in highway ROW deeds. Detect and flag — no geometry calculation.

**Model**: Add `"spiral"` to `CurveType` literal
**Module**: `call_extractor.py` — detect "spiral" keyword in `extract_curve_info()`

### 10. State Plane Metadata

**Reference**: Section 13.3

Extract coordinate system references from deed text:
> "State Plane Coordinate System, Texas South Central Zone, FIPS 4204, NAD 83"

Store as metadata. Advisory only — no grid correction computation.

**Model**: Add `coordinate_system: str | None` and `fips_code: str | None` to `LegalDescription`
**Module**: `text_parser.py` — add `extract_coordinate_system()`

## Model Changes Summary

```python
# models.py additions
MonumentType += "tree", "rock", "natural_feature"
CurveType += "spiral"

class DeedClause(_Model):
    clause_type: Literal["reservation", "subject_to", "together_with"]
    text: str

class SubdivisionReference(_Model):
    lot: str | None = None
    block: str | None = None
    subdivision_name: str | None = None
    plat_book: str | None = None
    plat_page: str | None = None

# LegalDescription new fields
clauses: list[DeedClause] = Field(default_factory=list)
subdivision_ref: SubdivisionReference | None = None
witness_trees: list[str] = Field(default_factory=list)
coordinate_system: str | None = None
fips_code: str | None = None
```

## What Does NOT Change

- **CSV schema**: stays at 21 fields (new data is metadata on LegalDescription, not per-call)
- **Core traverse logic**: untouched
- **Verification checks**: unchanged (8 checks)
- **No new DeedCall fields**: degree of curvature converts to existing radius_ft

## Implementation Steps

1. Models — all new types and fields
2. Degree of Curvature — bearing_converter + call_extractor
3. Extended Curve Properties — bearing_converter
4. Natural Monuments — call_extractor MonumentClassifier
5. 32-Point Compass — bearing_converter + call_extractor
6. Clause Taxonomy — text_parser
7. Subdivision Lot/Block + TPOB/RPOB — text_parser
8. Witness Trees — text_parser
9. Spiral Curves + State Plane Metadata — call_extractor + text_parser
10. Pipeline Wiring + Final Verification — pdf_processor + csv_builder
