# Ground Truth Data

Ground truth reference files are stored **next to each PDF** in `sample_deeds/` as JSON files.

## File Format

Each PDF has a corresponding `.ground_truth.json` file:
```
sample_deeds/
├── 18 Pennbrook Dr - Deed Image (11985 - 00829).pdf
├── 18 Pennbrook Dr - Deed Image (11985 - 00829).ground_truth.json  ← Ground truth
├── 24 Pennbrook Dr - Deed Image (11793 - 00217).pdf
└── ...
```

## Purpose

Ground truth files document the expected output at each stage of the PDF processing pipeline:
1. **Raw PDF Text** (`raw_ocr_text`) - What the configured prompt flow should extract from the PDF
2. **Legal Description** (`expected_legal_description`) - The isolated legal description section
3. **Normalized Text** (`expected_normalized_text`) - Standardized formatting (DMS symbols, cardinal directions)
4. **Expected Calls** (`expected_calls`) - Structured call data with bearings, distances, along/to fields
5. **Critical Assertions** (`critical_assertions`) - Required test conditions

## JSON Schema

```json
{
  "deed_info": {
    "address": "18 Pennbrook Drive",
    "city": "Haddonfield",
    "book": "11985",
    "page": "00829"
  },
  "raw_ocr_text": "LAND AND PREMISES...",
  "expected_legal_description": "BEGINNING at a point...",
  "expected_normalized_text": "BEGINNING at a point...",
  "expected_pob": "a point at the southwesterly corner...",
  "expected_calls": [
    {
      "course": 1,
      "direction_text": "S 33°20'00\" E",
      "bearing_azimuth_deg_from_north": 146.666667,
      "distance_ft": 60.0,
      "along": "southwesterly line of Concord Drive",
      "to": "a point in the division line..."
    }
  ],
  "expected_closure": {
    "misclosure_ft": 0.0,
    "area_sq_ft": 7500.0,
    "area_acres": 0.172
  },
  "critical_assertions": {
    "num_calls": {"expected": 4, "operator": "=="},
    "area_matches": {"expected_sq_ft": 7500.0, "tolerance_percent": 5.0}
  },
  "common_failure_modes": [...]
}
```

## Reference Files

This folder contains reference documentation:

### 18_pennbrook_ground_truth.txt
- **Legacy format** - Human-readable text version
- **Parcel**: 18 Pennbrook Drive, Haddonfield, NJ
- **Shape**: Rectangle (60' × 125')
- **Calls**: 4 numbered calls
- **Area**: 7,500 sq ft (0.172 acres)
- **Key Test Case**: Validates numbered call format preservation

## Usage

### Comparing API Output

To compare actual extraction against ground truth:

```bash
# Extract from PDF
uv run metesparser extract "sample_deeds/18 Pennbrook Dr - Deed Image (11985 - 00829).pdf" > /tmp/actual_output.txt

# Compare against ground truth
diff ground_truth/18_pennbrook_ground_truth.txt /tmp/actual_output.txt
```

### Adding New Ground Truth

When adding new sample deeds:

1. Extract the raw OCR text from the PDF
2. Document expected output at each pipeline stage
3. Include critical assertions (number of calls, area, misclosure)
4. Name file: `{address}_ground_truth.txt`

## Critical Assertions for 18 Pennbrook

✓ **MUST extract 4 calls** (not 1, not 2)
✓ **MUST preserve numbered format** (1., 2., 3., 4.)
✓ **MUST NOT merge calls** into one "along" field
✓ **Traverse MUST close** to < 0.01 ft
✓ **Area MUST equal** 7,500 sq ft ± 5%

## Common Failure Modes

### Issue: Only 1-2 calls extracted
**Symptom**: All 4 numbered calls merged into call #1 or #2's "along" field
**Cause**: Prompt changes not preserving line breaks between numbered calls
**Fix**: Strengthen prompts with explicit line break examples

### Issue: Calls have incomplete bearings
**Symptom**: `bearing_azimuth_deg_from_north = None`, notes say "incomplete bearing"
**Cause**: Call extractor not recognizing bearing format
**Fix**: Update bearing regex patterns in `call_extractor.py`

### Issue: Wrong area calculation
**Symptom**: Area significantly different from expected 7,500 sq ft
**Cause**: Bearing or distance parsing errors
**Fix**: Check bearing azimuths and distance conversions

## Maintenance

- Update ground truth when prompts change significantly
- Re-validate periodically to detect API model drift
- Add new ground truth files for each new sample deed
- Document any deviations from expected behavior
