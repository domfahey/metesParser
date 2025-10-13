# Agents Configuration

## Purpose

This file tracks agent configurations and workflows for the Metes Parser project.

## Active Agents

### PDF Extraction Agent

**Role**: Extract legal descriptions from deed PDFs
**Tools**: OpenAI API (gpt-4o with vision)
**Input**: PDF file path
**Output**: Raw legal description text

**Configuration**:
- Model: gpt-4o (vision-capable)
- Max tokens: 4096
- Temperature: 0 (deterministic)
- Prompt: `prompts/extract_legal_description.yaml`

### Text Normalization Agent

**Role**: Clean and standardize legal description text
**Tools**: OpenAI API (gpt-4o-mini)
**Input**: Raw legal description text
**Output**: Normalized text with standard DMS symbols

**Configuration**:
- Model: gpt-4o-mini
- Max tokens: 2048
- Temperature: 0
- Prompt: `prompts/normalize_text.yaml`

**Transformations**:
- Standardize ° ' " symbols
- Fix OCR errors (0↔°, 1↔l/I, 5↔S)
- Merge line-wrapped calls
- Standardize cardinal directions

### Call Extraction Agent (Rule-Based)

**Role**: Extract individual calls using regex patterns
**Tools**: Python regex, BearingConverter
**Input**: Normalized legal description
**Output**: List of DeedCall objects

**Key Patterns**:
- Quadrant bearing: `(N|S) \d{1,3}°\d{1,2}' (E|W)`
- Distance: `\d+(?:\.\d+)? (feet|ft|poles|rods)`
- Curve: `curve to the (left|right).*radius of \d+`

**Principles**:
- Never fabricate bearings
- Flag incomplete calls as meanders
- Preserve verbatim along/to text

### Closure Verification Agent

**Role**: Verify traverse closure and perform 6 guardrail checks
**Tools**: ClosureChecker
**Input**: List of DeedCall objects
**Output**: ClosureResult with validation flags

**Checks**:
1. Traverse closure (misclosure < 0.01 ft)
2. Interior angles sum ((n-2)*180°)
3. Parallelism (continuing lines)
4. Curve consistency (L ≈ R*Δ)
5. Area reasonableness (vs stated)
6. Double-entry validation

### CSV Export Agent

**Role**: Export verified calls to CSV
**Tools**: CSVBuilder
**Input**: DeedCall list + ClosureResult
**Output**: CSV file (_verified.csv if all checks pass)

**Schema**: Standard 14-field format from playbook
**Metadata**: Separate .metadata.txt file

## Workflow Pipeline

```
PDF File
  ↓
[PDF Extraction Agent] → Raw legal description text
  ↓
[Text Normalization Agent] → Normalized text
  ↓
[Call Extraction Agent] → List of DeedCall objects
  ↓
[Closure Verification Agent] → ClosureResult
  ↓
[CSV Export Agent] → _verified.csv (if passed)
```

## Agent Coordination

All agents are coordinated through the `PDFProcessor.process_deed_pdf()` method, which:
1. Calls extraction agent
2. Calls normalization agent
3. Uses rule-based extractor (not AI for reliability)
4. Enriches with azimuths
5. Returns LegalDescription object

CLI then handles verification and export independently.

## Future Enhancements

- [ ] GeoJSON/KML export agent
- [ ] Plat reference resolution agent
- [ ] Multi-document batch processing
- [ ] Interactive correction agent for flagged calls

## Notes

- OpenAI agents use temperature=0 for deterministic output
- Rule-based extractor preferred over AI for call extraction (more reliable)
- All agents handle errors gracefully with structured logging
- API keys managed via .env file (never committed)
