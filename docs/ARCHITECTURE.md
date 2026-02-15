# Architecture

System design and data flow for metesParser.

## Table of Contents

- [System Overview](#system-overview)
- [Core Principles](#core-principles)
- [Data Flow](#data-flow)
- [Module Architecture](#module-architecture)
- [Data Models](#data-models)
- [Verification Pipeline](#verification-pipeline)
- [Error Handling](#error-handling)
- [Performance Considerations](#performance-considerations)

## System Overview

metesParser is a deterministic metes & bounds parser that converts legal descriptions from PDFs into structured, verified CSV format.

### Key Characteristics

- **Rule-based parsing** - No AI/ML in core logic (only PDF extraction)
- **Deterministic output** - Same input always produces same result
- **Verification-first** - Won't output `_verified.csv` unless all checks pass
- **Never fabricates** - Flags incomplete data rather than guessing

### Technology Stack

- **Python 3.11+** - Modern Python with type hints (`|` unions)
- **Pydantic v2** - Data validation and schema enforcement
- **OpenAI + optional Gemini** - Configurable LLM providers for PDF extraction
- **UV** - Dependency management (no pip/conda/poetry)
- **pytest** - Test framework with 368 tests (as of 2026-02-15)

## Core Principles

### 1. Never Fabricate Data

```python
# NEVER do this:
if bearing is None:
    bearing = "estimate based on adjacent calls"  # ❌ WRONG

# ALWAYS do this:
if bearing is None:
    call.notes = "incomplete bearing - manual review required"  # ✅ CORRECT
```

### 2. Verification Before Export

```python
result = ClosureChecker.verify_closure(calls)

if result.is_fully_verified():
    # Pass legal_desc for metadata-rich verified output
    CSVBuilder.export_verified_csv(calls, result, output_path, legal_desc=legal_desc)
else:
    print(f"Cannot export verified CSV: {result.misclosure_ft:.4f} ft misclosure")
```

### 3. Preserve Original Wording

```python
# Keep deed language verbatim in descriptive fields
call = DeedCall(
    bearing_quadrant="S 56°40' W",
    distance_ft=125.0,
    along="the division line between Lots 46 and 47",  # Preserve exact wording
    to="the corner to Lot 50",  # Preserve exact wording
)
```

### 4. Deterministic Processing

```python
# LLM extraction for deterministic behavior
from metesparser.llm_clients import OpenAIClient, GeminiClient

response_client = OpenAIClient()
# or
response_client = GeminiClient()

response = response_client.generate_text(combined_prompt)
```

## Data Flow

### High-Level Pipeline

```
┌──────┐     ┌─────────┐     ┌───────────┐     ┌────────┐     ┌──────────┐     ┌────────┐
│ PDF  │────>│ LLM    │────>│   Text    │────>│  Call  │────>│ Closure  │────>│  CSV   │
│ File │     │ Extract │     │  Parser   │     │Extract │     │ Checker  │     │ Export │
└──────┘     └─────────┘     └───────────┘     └────────┘     └──────────┘     └────────┘
             (API call)      (Normalize)       (Regex)        (Verify)         (if passed)
```

### Detailed Flow

```
1. PDF Extraction (pdf_processor.py)
   ├─> Configured LLM provider (OpenAI or Gemini)
   ├─> Temperature=0 for determinism
   └─> Returns: Raw legal description text

2. Text Normalization (text_parser.py)
   ├─> Fix OCR errors via `clean_ocr_errors` (5outh → South, Ea5t → East, 56 0 40' → 56°40')
   ├─> Merge wrapped lines (div-\nision → division)
   ├─> Standardize cardinal directions (South → S)
   └─> Returns: Normalized text

3. POB Extraction (text_parser.py)
   ├─> Extract BEGINNING clause
   └─> Returns: Point of Beginning description

4. Call Extraction (call_extractor.py)
   ├─> Split calls by numbered markers, THENCE, or semicolons
   ├─> Parse bearing (quadrant format)
   ├─> Parse distance + unit
   ├─> Parse curve parameters (R, Δ, L)
   ├─> Extract along/to descriptive fields
   └─> Returns: List[DeedCall]

5. Bearing Enrichment (bearing_converter.py)
   ├─> Convert quadrant → azimuth
   ├─> Calculate curve properties
   └─> Returns: Enriched DeedCall objects

6. Closure Verification (closure_checker.py)
   ├─> Compute traverse (calculate all points)
   ├─> Check mandatory guardrails plus optional double-entry validation
   ├─> Calculate area, perimeter, misclosure
   └─> Returns: ClosureResult

7. CSV Export (csv_builder.py)
   ├─> If fully verified: export _verified.csv
   ├─> Else: export regular .csv with warnings
   └─> Export metadata; verification summary is written only for verified outputs
```

## Module Architecture

### Dependency Graph

```
┌─────────────┐
│   cli.py    │  (Entry point)
└─────┬───────┘
      │
      v
┌─────────────────┐
│ pdf_processor.py│  (OpenAI/Gemini provider)
└─────┬───────────┘
      │
      v
┌──────────────┐       ┌─────────────────┐
│text_parser.py│<──────│call_extractor.py│
└──────────────┘       └────────┬────────┘
                                │
                                v
                       ┌──────────────────┐
                       │bearing_converter.│
                       │       py         │
                       └────────┬─────────┘
                                │
                                v
                       ┌──────────────────┐
                       │closure_checker.py│
                       └────────┬─────────┘
                                │
                                v
                       ┌─────────────┐
                       │csv_builder.│
                       │     py      │
                       └─────────────┘

         ┌─────────────┐
         │  models.py  │ (Used by all modules)
         └─────────────┘
```

### Module Responsibilities

#### models.py
**Purpose**: Data schemas and validation

```python
class DeedCall(BaseModel):
    """Single deed call with bearing, distance, and metadata."""
    course: int  # Sequential number
    bearing_quadrant: str | None  # "N 45°30' E"
    bearing_azimuth_deg_from_north: float | None  # 45.5
    distance_ft: float = Field(gt=0)  # Must be > 0
    # ... curve fields, descriptive fields, notes
```

**Key Models**:
- `DeedCall` - Individual call
- `Point` - X/Y coordinate
- `LegalDescription` - Full parcel description
- `ClosureResult` - Verification results

#### bearing_converter.py
**Purpose**: Bearing/azimuth conversions and curve math

**Key Methods**:
- `parse_quadrant_bearing()` - Parse "S 56°40' W" → (S, 56.667, W)
- `quadrant_to_azimuth()` - Convert to degrees from North
- `azimuth_to_quadrant()` - Convert back to quadrant format
- `calculate_curve_properties()` - Compute L, chord from R, Δ
- `calculate_deltas()` - Compute dx, dy from azimuth, distance

**Formulas**:
```python
# Quadrant to Azimuth
N θ E → az = θ
S θ E → az = 180 - θ
S θ W → az = 180 + θ
N θ W → az = 360 - θ

# Curve Properties
L = R × Δ (radians)
chord = 2R × sin(Δ/2)

# Deltas
# azimuth is in degrees from North and converted to radians
dx = distance × sin(radians(azimuth))
dy = distance × cos(radians(azimuth))
```

#### text_parser.py
**Purpose**: Text normalization and OCR error correction

**Key Methods**:
- `normalize_legal_description()` - Full normalization pipeline
- `clean_ocr_errors()` - Correct common OCR mistakes
- `merge_line_wrapped_calls()` - Fix line breaks mid-word
- `standardize_cardinal_directions()` - North → N
- `extract_pob()` - Extract point of beginning
- `split_into_calls()` - Split on numbered calls, THENCE, or semicolons

**OCR Corrections**:
```python
"5outh" → "South"
"NOrth" → "North"
"56 0 40'" → "56 degrees 40 minutes"
"div-\nision" → "division"
```

#### call_extractor.py
**Purpose**: Parse normalized text into structured DeedCall objects

**Key Methods**:
- `extract_calls()` - Parse full description → List[DeedCall]
- `extract_single_call()` - Parse one call
- `extract_direction()` - Extract bearing from text
- `extract_curve_info()` - Extract R, Δ, L from curve text
- `enrich_calls_with_azimuths()` - Add missing azimuths

**Parsing Strategy**:
- **Regex-based** (not AI) for reliability
- **Defensive** - handle incomplete data gracefully
- **Flag uncertainties** - never fabricate

#### closure_checker.py
**Purpose**: Verify traverse with mandatory guardrails plus optional double-entry comparison

**Key Methods**:
- `verify_closure()` - Main verification entry point
- `compute_traverse()` - Calculate all (x,y) points
- `calculate_area()` - Shoelace formula
- `check_interior_angles()` - Verify (n-2)×180°
- `check_curve_consistency()` - Verify L ≈ R×Δ
- `compare_double_entry()` - Compare two independently entered call sets

**Verification Guardrails**:
1. **Traverse Closure** - Misclosure < 0.01 ft by default
2. **Interior Angles** - Sum = (n-2)×180° (straight-line polygons only)
3. **Parallelism** - "continuing" lines match
4. **Curve Math** - L ≈ R×Δ, chord ≈ 2R×sin(Δ/2)
5. **Area Check** - When a stated area is provided, flags if computed area differs by more than 5%
6. **Double Entry** - Optional comparison if a second call set is supplied

#### csv_builder.py
**Purpose**: CSV import/export with verification

**Key Methods**:
- `calls_to_csv()` - Export List[DeedCall] → CSV
- `csv_to_calls()` - Import CSV → List[DeedCall]
- `export_verified_csv()` - Export only if verified
- `legal_description_to_csv()` - Export with metadata

**CSV Schema** (16 fields):
```csv
course,direction_text,bearing_quadrant,bearing_azimuth_deg_from_north,distance_ft,
curve_dir,radius_ft,delta_deg,arc_length_ft,chord_bearing,chord_length_ft,
along,to,monument_type,is_exception,notes
```

#### pdf_processor.py
**Purpose**: Extract legal description from PDF using configured LLM provider

**Key Methods**:
- `process_deed_pdf()` - Main extraction
- `extract_text_from_pdf()` - PDF → text
- `generate_text_with_pdf()` - Provider extraction

**Strategy**:
- Zero-shot prompt with examples
- Temperature=0 for determinism
- Structured output format
  - Retry logic for transient failures

#### cli.py
**Purpose**: Command-line interface

**Commands**:
```bash
metesparser extract <pdf_file>  # Extract from PDF
metesparser verify <csv_file>   # Verify closure
```

## Data Models

### DeedCall

Core data structure representing one deed call:

```python
class DeedCall:
    course: int                                    # Sequential number (1, 2, 3...)
    direction_text: str                            # Raw direction text
    bearing_quadrant: str | None                   # "S 56°40' W"
    bearing_azimuth_deg_from_north: float | None   # 236.667 (degrees from N)
    distance_ft: float                             # Distance in feet (must be > 0)

    # Curve fields (all None for straight lines)
    curve_dir: str | None                          # "left" or "right"
    radius_ft: float | None                        # Curve radius
    delta_deg: float | None                        # Central angle
    non_tangent: bool                             # Non-tangent curve flag
    radial_bearing: str | None                    # Radial bearing (if non_tangent)
    arc_length_ft: float | None                    # Arc length
    chord_bearing: str | None                      # Chord bearing
    chord_length_ft: float | None                  # Chord length
    is_exception: bool                             # EXCEPT/LESS AND EXCEPT marker

    # Descriptive fields
    along: str | None                              # "along the division line"
    to: str | None                                 # "to an iron pin"
    monument_type: str | None                      # Survey marker type
    notes: str | None                              # Warnings/flags

    def is_complete_bearing(self) -> bool:
        """Check if bearing is complete (not cardinal-only)."""
        return self.bearing_azimuth_deg_from_north is not None

    def is_curve(self) -> bool:
        """Check if this is a curve call."""
        return self.curve_dir is not None or self.radius_ft is not None
```

### ClosureResult

Verification results:

```python
class ClosureResult:
    misclosure_x_ft: float                     # X component of misclosure
    misclosure_y_ft: float                     # Y component
    misclosure_ft: float                       # Total misclosure
    area_sq_ft: float                          # Computed area
    area_acres: float                          # Area in acres
    perimeter_ft: float                        # Total perimeter
    precision_ratio: float | None              # Misclosure / perimeter ratio

    closure_passed: bool                       # Misclosure < tolerance?
    angle_check_passed: bool                   # Angles sum correctly?
    curve_consistency_passed: bool             # Curve math correct?

    warnings: list[str]                        # List of warnings
    points: list[Point]                        # All traverse points

    def is_fully_verified(self) -> bool:
        """Check if all verification checks passed."""
        return (
            self.closure_passed
            and self.angle_check_passed
            and self.curve_consistency_passed
            and len(self.warnings) == 0
        )
```

## Verification Pipeline

### Traverse Computation

```python
def compute_traverse(calls, start_point=Point(0, 0)):
    """Compute all points from calls."""
    points = [start_point]
    current = start_point

    for call in calls:
        if call.bearing_azimuth_deg_from_north is None:
            continue  # Skip incomplete bearings

        if call.is_curve():
            # Approximate with chord
            next_point = compute_curve_endpoint(...)
        else:
            # Straight line
            dx, dy = calculate_deltas(call.bearing_azimuth_deg_from_north, call.distance_ft)
            next_point = Point(current.x + dx, current.y + dy)

        points.append(next_point)
        current = next_point

    return points
```

### Closure Check

```python
# Misclosure = distance from last point to first point
misclosure_x = points[-1].x - points[0].x
misclosure_y = points[-1].y - points[0].y
misclosure = sqrt(misclosure_x² + misclosure_y²)

# Pass if misclosure < 0.01 ft
closure_passed = misclosure < 0.01
```

### Area Calculation

```python
def calculate_area(points):
    """Shoelace formula (Gauss's area formula)."""
    area = 0.0
    n = len(points)

    for i in range(n - 1):
        area += points[i].x * points[i+1].y
        area -= points[i+1].x * points[i].y

    return abs(area) / 2.0
```

## Error Handling

### Input Validation

Pydantic enforces constraints at construction:

```python
class DeedCall(BaseModel):
    distance_ft: float = Field(gt=0)  # Must be > 0

# This raises ValidationError:
DeedCall(distance_ft=0.0)  # ❌
DeedCall(distance_ft=-10.0)  # ❌
```

### Graceful Degradation

Handle incomplete data without crashing:

```python
# If bearing can't be parsed, flag it
if parsed_bearing is None:
    call.bearing_azimuth_deg_from_north = None
    call.notes = "incomplete bearing - manual review required"
    # Continue processing, don't crash
```

### Verification Warnings

Collect warnings rather than failing:

```python
warnings = []

if misclosure > tolerance:
    warnings.append(f"Misclosure {misclosure:.4f} ft exceeds tolerance")

if len(incomplete_bearings) > 0:
    warnings.append(f"{len(incomplete_bearings)} calls have incomplete bearings")

return ClosureResult(..., warnings=warnings)
```

## Performance Considerations

### Fast Operations

- **Text parsing**: Regex-based, very fast (~ms)
- **Bearing conversion**: Pure math, no I/O
- **Traverse computation**: O(n) where n = number of calls
- **Area calculation**: O(n) shoelace formula

### Slow Operations

- **PDF extraction**: LLM API call (~2-5 seconds)
- **Large parcels**: 100+ calls take longer to verify

### Optimization Strategies

1. **Cache extraction calls** - Avoid re-extracting the same PDF
2. **Batch processing** - Process multiple PDFs in parallel
3. **Skip verification** - For quick viewing, don't run all checks

### Memory Usage

Minimal memory footprint:
- Each DeedCall: ~500 bytes
- 100 calls: ~50 KB
- Traverse points: 16 bytes/point

## Design Decisions

### Why Rule-Based Parsing?

**Decision**: Use regex-based parsing instead of AI/ML for call extraction.

**Rationale**:
- **Deterministic** - Same input always produces same output
- **Debuggable** - Easy to see why parsing succeeded/failed
- **Fast** - No model loading or inference time
- **Reliable** - Well-understood regex patterns
- **Testable** - Easy to write unit tests

**Trade-off**: More brittle to format variations, but acceptable given standardized legal descriptions.

### Why Pydantic v2?

**Decision**: Use Pydantic for data validation.

**Rationale**:
- **Type safety** - Catch errors at construction time
- **Validation** - Enforce constraints (distance > 0)
- **Serialization** - Easy CSV export/import
- **Documentation** - Self-documenting schemas

### Why UV Instead of Pip?

**Decision**: Mandate UV for dependency management.

**Rationale**:
- **Fast** - Orders of magnitude faster than pip
- **Deterministic** - Lock file ensures reproducibility
- **Simple** - Single tool for venv + install + run
- **Modern** - Built with Rust, actively maintained

### Why Separate Verification Step?

**Decision**: Don't export verified CSV unless all checks pass.

**Rationale**:
- **Quality control** - Prevent bad data from entering GIS
- **Audit trail** - Clear distinction between verified/unverified
- **Professional standards** - Surveying requires verification

---

For more information:
- [TESTING.md](TESTING.md) - Test suite architecture
- [API.md](API.md) - Python API reference
- [CONTRIBUTING.md](CONTRIBUTING.md) - Development guidelines
