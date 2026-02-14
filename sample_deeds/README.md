# Sample Deed PDFs

This directory contains sample deed PDFs from the Camden County (NJ) Recorder's Office. These are **public records** with no PII/NPI and are safe to commit to version control.

## Files

### 18 Pennbrook Drive
- **File**: `18 Pennbrook Dr - Deed Image (11985 - 00829).pdf`
- **Book/Page**: 11985-829
- **Description**: Simple rectangular parcel (4 calls)
- **Use Case**: Basic traverse closure testing, ideal for verifying fundamental bearing conversion

### 24 Pennbrook Drive
- **File**: `24 Pennbrook Dr - Deed Image (11793 - 00217).pdf`
- **Book/Page**: 11793-217
- **Description**: Standard residential lot
- **Use Case**: Testing standard metes and bounds parsing

### 31 Pennbrook Drive (Multiple Deeds)
This property has **4 historical deed recordings** showing chain of title:

1. **File**: `31 Pennbrook Dr - Deed Image (4618 - 717).pdf`
   - **Book/Page**: 4618-717
   - **Era**: Oldest deed
   - **Use Case**: Historical deed format testing

2. **File**: `31 Pennbrook Dr - Deed Image (9777 - 1354).pdf`
   - **Book/Page**: 9777-1354
   - **Use Case**: Mid-era deed format

3. **File**: `31 Pennbrook Dr - Deed Image (10989 - 916).pdf`
   - **Book/Page**: 10989-916
   - **Description**: 5-sided parcel with curves
   - **Use Case**: Complex geometry testing, curve calculations

4. **File**: `31 Pennbrook Dr - Deed Image (11191 - 01716).pdf`
   - **Book/Page**: 11191-1716
   - **Era**: Most recent
   - **Use Case**: Modern deed format, updated legal description

## Data Source

All deeds obtained from:
- **Source**: Camden County Recorder's Office
- **Status**: Public records (available via county recorder search)
- **Privacy**: No PII/NPI - property addresses and legal descriptions are public information
- **Date Retrieved**: October 2025

## Purpose

These sample deeds serve as:
- **Test Data**: Integration testing for PDF extraction and parsing pipeline
- **Regression Testing**: Known-good parcels for validating closure calculations
- **Documentation**: Real-world examples of metes and bounds descriptions
- **Benchmarking**: Performance testing with actual deed PDFs

## Usage in Tests

The test suite uses these files for integration testing and ground-truth validation:

```python
# Example usage
from metesparser import PDFProcessor

processor = PDFProcessor()
legal_desc = processor.process_deed_pdf("sample_deeds/18 Pennbrook Dr - Deed Image (11985 - 00829).pdf")
```

Tests will automatically skip if these files are not present (graceful degradation for CI environments).

## Legal Note

These are **public domain records** obtained from the Camden County Recorder's Office. Property deeds are public records under New Jersey Open Public Records Act (OPRA). No confidential information is contained in these files.
