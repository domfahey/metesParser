# Ground Truth Data

This folder contains ground truth reference data for validating PDF extraction accuracy.

## Purpose

Ground truth files document the expected output at each stage of the PDF processing pipeline:
1. **Raw PDF Text** - What GPT-4.1 should extract from the PDF
2. **Legal Description** - The isolated legal description section
3. **Normalized Text** - Standardized formatting (DMS symbols, cardinal directions)
4. **Expected Calls** - How the calls should be parsed

## Files

### 18_pennbrook_ground_truth.txt
- **Parcel**: 18 Pennbrook Drive, Haddonfield, NJ
- **Deed**: Book 11985, Page 00829
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
**Cause**: GPT-4.1 not preserving line breaks between numbered calls
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
