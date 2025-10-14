# Python API Reference

Complete reference for metesParser Python API.

## Quick Example

```python
from metesparser import CallExtractor, ClosureChecker, CSVBuilder

# Parse legal description
text = """
BEGINNING at a point;
THENCE North 45 degrees East 100 feet;
THENCE South 45 degrees East 100 feet;
THENCE South 45 degrees West 141.42 feet to the POINT OF BEGINNING.
"""

calls = CallExtractor.extract_calls(text)
calls = CallExtractor.enrich_calls_with_azimuths(calls)

# Verify closure
result = ClosureChecker.verify_closure(calls)
print(f"Misclosure: {result.misclosure_ft:.4f} ft")
print(f"Area: {result.area_acres:.4f} acres")

# Export if verified
if result.is_fully_verified():
    CSVBuilder.export_verified_csv(calls, result, "output.csv")
```

## Core Modules

### BearingConverter

Bearing/azimuth conversions and curve calculations.

```python
from metesparser.bearing_converter import BearingConverter

# Parse quadrant bearing
parsed = BearingConverter.parse_quadrant_bearing("S 56°40' W")
# Returns: ("S", 56.667, "W")

# Convert to azimuth
azimuth = BearingConverter.quadrant_to_azimuth("S", 56.667, "W")
# Returns: 236.667

# Calculate deltas
dx, dy = BearingConverter.calculate_deltas(azimuth=45.0, distance_ft=100.0)
# Returns: (70.71, 70.71)

# Curve properties
props = BearingConverter.calculate_curve_properties(
    radius_ft=50.0,
    delta_deg=90.0
)
# Returns: {"radius_ft": 50.0, "delta_deg": 90.0, "arc_length_ft": 78.54, ...}
```

### CallExtractor

Parse legal descriptions into structured DeedCall objects.

```python
from metesparser.call_extractor import CallExtractor

# Extract all calls
calls = CallExtractor.extract_calls(legal_text)

# Extract single call
call = CallExtractor.extract_single_call(
    "N 45°30' E 100.50 feet along the north line",
    course=1
)

# Enrich with azimuths
enriched = CallExtractor.enrich_calls_with_azimuths(calls)
```

### ClosureChecker

Verify traverse closure and perform validation checks.

```python
from metesparser.closure_checker import ClosureChecker

# Verify closure
result = ClosureChecker.verify_closure(
    calls=calls,
    stated_area_sq_ft=10000.0,  # Optional
    closure_tolerance_ft=0.01    # Optional
)

# Check results
print(f"Misclosure: {result.misclosure_ft} ft")
print(f"Area: {result.area_sq_ft} sq ft ({result.area_acres} acres)")
print(f"Perimeter: {result.perimeter_ft} ft")
print(f"Verified: {result.is_fully_verified()}")

# Compute traverse points
points = ClosureChecker.compute_traverse(calls)

# Calculate area from points
area = ClosureChecker.calculate_area(points)

# Get summary
summary = ClosureChecker.get_closure_summary(result)
print(summary)
```

### CSVBuilder

Export/import CSV files.

```python
from metesparser.csv_builder import CSVBuilder

# Export calls to CSV
CSVBuilder.calls_to_csv(calls, "output.csv")

# Export verified CSV (only if all checks pass)
CSVBuilder.export_verified_csv(
    calls=calls,
    closure_result=result,
    output_path="output.csv",
    legal_desc=legal_description  # Optional
)

# Import calls from CSV
imported_calls = CSVBuilder.csv_to_calls("input.csv")
```

### TextParser

Normalize and parse legal description text.

```python
from metesparser.text_parser import TextParser

# Normalize text
normalized = TextParser.normalize_legal_description(raw_text)

# Extract POB
pob = TextParser.extract_pob(normalized)

# Extract distance
distance, unit = TextParser.extract_distance("125.50 feet")
# Returns: (125.5, "feet")

# Split into calls
calls = TextParser.split_into_calls(normalized)
```

## Data Models

### DeedCall

```python
from metesparser.models import DeedCall

call = DeedCall(
    course=1,
    direction_text="S 56°40' W",
    bearing_quadrant="S 56°40' W",
    bearing_azimuth_deg_from_north=236.667,
    distance_ft=125.0,
    along="the division line",
    to="an iron pin",
    notes=None
)

# Methods
call.is_complete_bearing()  # Returns: True
call.is_curve()             # Returns: False
```

### ClosureResult

```python
from metesparser.models import ClosureResult

result = ClosureResult(
    misclosure_x_ft=0.0,
    misclosure_y_ft=0.0,
    misclosure_ft=0.0,
    area_sq_ft=10000.0,
    area_acres=0.2296,
    perimeter_ft=400.0,
    closure_passed=True,
    angle_check_passed=True,
    curve_consistency_passed=True,
    warnings=[],
    points=[...]
)

# Methods
result.is_fully_verified()     # Returns: True
result.get_closure_status()    # Returns: "PASS"
```

### Point

```python
from metesparser.models import Point

p1 = Point(x=0.0, y=0.0)
p2 = Point(x=100.0, y=100.0)
```

## Complete Example

```python
from pathlib import Path
from metesparser import (
    PDFProcessor,
    TextParser,
    CallExtractor,
    ClosureChecker,
    CSVBuilder,
    LegalDescription
)

# 1. Extract from PDF
processor = PDFProcessor()
legal_text = processor.process_deed_pdf("deed.pdf")

# 2. Normalize
normalized = TextParser.normalize_legal_description(legal_text)
pob = TextParser.extract_pob(normalized)

# 3. Extract calls
calls = CallExtractor.extract_calls(normalized)
calls = CallExtractor.enrich_calls_with_azimuths(calls)

# 4. Verify
result = ClosureChecker.verify_closure(calls)

# 5. Create legal description
legal_desc = LegalDescription(
    pob_description=pob,
    calls=calls,
    source_doc="deed.pdf"
)

# 6. Export
if result.is_fully_verified():
    CSVBuilder.export_verified_csv(
        calls,
        result,
        "output.csv",
        legal_desc
    )
    print("✓ Exported verified CSV")
else:
    CSVBuilder.legal_description_to_csv(legal_desc, "output.csv")
    print(f"⚠ Misclosure: {result.misclosure_ft:.4f} ft")
    print("Review required before verification")
```

---

For more information:
- [TESTING.md](TESTING.md) - Test suite guide
- [ARCHITECTURE.md](ARCHITECTURE.md) - System design
- [CONTRIBUTING.md](CONTRIBUTING.md) - Development guidelines
