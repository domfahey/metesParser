# Python API Reference

Core compatibility API exposed by the `metesparser` package and its legacy modules.
For the composable package boundaries, see [Architecture](ARCHITECTURE.md#composable-package-architecture).
For the `metes-review` file/CLI workflows and their handoffs, see the [usage guide](../plugins/metesparser/references/usage.md)
and [artifact contract](../plugins/metesparser/references/artifact-handoffs.md).

## Quick Example

```python
from metesparser import CallExtractor, ClosureChecker, CSVBuilder

# Parse legal description
text = """
BEGINNING at a point;
THENCE North 100 feet;
THENCE East 100 feet;
THENCE South 100 feet;
THENCE West 100 feet to the POINT OF BEGINNING.
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

`extract_calls()` raises `ValueError` when a course cannot be parsed, so an
incomplete parcel cannot silently pass verification. Use `strict=False` only
when deliberately recovering partial data for manual review. The same default
and recovery option apply to `mp_parse.extract_calls()`.

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

The composable package API `mp_parse.extract_calls(text, strict=True)` returns
`(flat_calls, tracts)`. Unpack the calls before passing them to enrichment or
verification. The legacy `CallExtractor.extract_calls()` retains its list return
value. For independent tracts, use `mp_verify.verify_closure(calls, tracts=tracts)`;
each tract runs the same geometric guardrails as a single description.

Boundary topology checks include straight segments and circular arcs. The audit
entry `boundary_intersections` replaces `straight_boundary_intersections` and
reports crossings, overlaps, nonadjacent contacts, and unavailable geometry.
The old straight-only checker remains available for callers requesting that scope.

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
area = ClosureChecker.calculate_area(points, calls=calls)

# Get summary
summary = ClosureChecker.get_closure_summary(result)
print(summary)
```

### CSVBuilder

Export/import CSV files.

`csv_to_calls()` rejects invalid rows by default. Use `strict=False` with a
`rejected_rows` list for explicit partial recovery: each rejected row is recorded
as `(row_number, error)`, and non-strict import without that list raises instead
of dropping a course. The 22-field schema ends with `curve_type`; legacy 21-field
CSVs still import with `curve_type` unset. CSV numeric fields retain the precision used in verification,
including values requiring more than two decimal places. These rules also apply
to `mp_export`.

`export_verified_csv()` verifies the actual calls again before writing and rejects
a stale result or a `LegalDescription` containing different calls. Rewriting a
CSV also clears its old generated sidecars when replacement inputs are omitted.
In multi-tract exports, every tract reported as verified is checked against its
actual calls before any output is written; unsuccessful tracts are skipped, and
easement and exception tracts are never exported.

The exporter also fails closed on description roles: when a deed has more than one
description and any role was inferred from wording rather than an explicit
`PARCEL ONE:` / `TRACT 2:` heading, `export_verified_csv()` raises, whatever the
supplied results claim. See
[Description roles and verified export](ARCHITECTURE.md#description-roles-and-verified-export).
Courses that extraction could not parse also block export, but only if the exporter
can see them: pass `skipped_courses` or the `audit_context` used for extraction.

```python
from metesparser.csv_builder import CSVBuilder

# Export calls to CSV
CSVBuilder.calls_to_csv(calls, "output.csv")

# Export verified CSV (only if all checks pass)
CSVBuilder.export_verified_csv(
    calls=calls,
    closure_result=result,
    output_path="output.csv",
    legal_desc=legal_description,  # Optional
    # skipped_courses=[...],       # Optional: unparsed courses block export
    # audit_context=audit_context, # Optional: supplies its skipped_courses
)

# Multi-tract: one verified CSV per eligible main/addition tract
results = ClosureChecker.verify_closure(calls, tracts=tracts)
CSVBuilder.export_verified_csv(
    calls,
    results[0],
    "output.csv",
    legal_desc=legal_description,
    tract_results=list(zip(tracts, results)),
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
    to="an iron pin found",
    monument_type="iron_pin",
    monument_status="found",
    notes=None
)

# Methods
call.is_complete_bearing()  # Returns: True
call.is_curve()             # Returns: False
```

### ClosureResult

```python
from metesparser import CallExtractor, ClosureChecker

text = """
BEGINNING at a point;
THENCE North 100 feet;
THENCE East 100 feet;
THENCE South 100 feet;
THENCE West 100 feet to the POINT OF BEGINNING.
"""
calls = CallExtractor.enrich_calls_with_azimuths(CallExtractor.extract_calls(text))
result = ClosureChecker.verify_closure(calls)

# Methods
result.is_fully_verified()     # Returns: True
result.get_closure_status()    # Returns: "EXCELLENT" for this zero-misclosure example
```

### Point

```python
from metesparser.models import Point

p1 = Point(x=0.0, y=0.0)
p2 = Point(x=100.0, y=100.0)
```

## Provider-Backed PDF Example

This example covers one `LegalDescription` returned by the provider-backed Python
pipeline. It assumes the intended boundary has been selected and source wording
has been reviewed. It does not demonstrate native Claude acquisition or
multi-tract selection.

```python
from metesparser import (
    ClosureChecker,
    CSVBuilder,
    PDFProcessor,
)

# 1. Extract and parse one boundary through the configured provider
processor = PDFProcessor()
legal_desc = processor.process_deed_pdf("deed.pdf")
calls = legal_desc.calls

# 2. Verify the returned calls, retaining a stated area when present
result = ClosureChecker.verify_closure(
    calls,
    stated_area_sq_ft=legal_desc.stated_area_sq_ft or 0.0,
)

# 3. Export with the original parsed metadata
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

## Audit Sidecar

Generate transparency reports alongside verified CSV output.

Audited extraction records include `llm_stages`: the rendered prompt, response,
SHA-256 fingerprints, and configured provider/model for each OCR, legal-description,
and normalization exchange. JSON sidecars and HTML reports include this evidence;
the existing extraction fields remain available.

```python
from metesparser import PDFProcessor, ClosureChecker, CSVBuilder

# Extract with audit trail enabled
processor = PDFProcessor()
legal_desc, audit_context = processor.process_deed_pdf("deed.pdf", audit=True)

# Verify closure (audit context records check results)
result = ClosureChecker.verify_closure(
    legal_desc.calls,
    stated_area_sq_ft=legal_desc.stated_area_sq_ft or 0.0,
    audit_context=audit_context
)

# Export with audit sidecar (.audit.json + .audit.html alongside CSV)
if result.is_fully_verified():
    CSVBuilder.export_verified_csv(
        legal_desc.calls,
        result,
        "output.csv",
        legal_desc=legal_desc,
        audit_context=audit_context
    )
    # Creates: output_verified.csv, output_verified.metadata.txt,
    # output_verified.verification.txt,
    # output_verified.audit.json, output_verified.audit.html
```

### AuditContext

```python
from metesparser.models import AuditContext

# AuditContext is a mutable accumulator (NOT frozen)
# It threads through the pipeline collecting:
# - LLM extraction metadata and confidence scoring
# - Per-call source excerpts and transformations
# - Verification check results and closure summary
```

### Quality Scoring

```python
from metesparser import ClosureChecker

result = ClosureChecker.verify_closure(calls)

# Overall confidence score (0.0 - 1.0)
print(f"Confidence: {result.confidence_score:.2f}")

# Per-call quality (high / medium / low)
for call in calls:
    print(f"Course {call.course}: quality={call.quality}")

# Enhanced closure summary with precision ratio
summary = ClosureChecker.get_closure_summary(result)
print(summary)
```

---

For more information:
- [TESTING.md](TESTING.md) - Test suite guide
- [ARCHITECTURE.md](ARCHITECTURE.md) - System design
- [CONTRIBUTING.md](CONTRIBUTING.md) - Development guidelines
