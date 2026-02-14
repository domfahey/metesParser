# LLM Prompts for Deed Processing

This directory contains all prompts used by the metesParser system. Prompts are provider-agnostic by design and configured through `PDFProcessor`.

## Prompt Files

### 1. extract_text_from_pdf.yaml
**Purpose**: Extract all text from a PDF document (LLM prompt input for downstream parsing)

**Model**: OpenAI `gpt-4.1` (default)
**API/Client**: Provider-dependent (`OpenAIClient` or `GeminiClient`)
**Input**: PDF file (base64 encoded)
**Output**: Complete document text

**Use Case**: First step in PDF processing - extracts raw text from deed PDFs while preserving formatting.

---

### 2. extract_legal_description.yaml
**Purpose**: Locate and extract the legal description section from deed text

**Model**: OpenAI `gpt-4.1` (default)
**API/Client**: Provider-dependent (`OpenAIClient` or `GeminiClient`)
**Input**: Full document text
**Output**: Legal description text only

**Use Case**: Isolates the metes and bounds description from the full deed document, filtering out cover pages, title info, etc.

**What it looks for**:
- Exhibit A sections
- Text beginning with "BEGINNING at..." or "COMMENCING at..."
- Sections labeled "Legal Description" or "Metes and Bounds"

---

### 3. normalize_text.yaml
**Purpose**: Normalize and clean up legal description text

**Model**: OpenAI `gpt-4.1` (default)
**API/Client**: Provider-dependent (`OpenAIClient` or `GeminiClient`)
**Input**: Raw legal description text
**Output**: Normalized, standardized text

**Use Case**: Standardizes formatting before rule-based extraction. Fixes OCR errors and ensures consistent format.

**Transformations**:
- Standardizes DMS symbols (°, ', ")
- Fixes OCR errors (0 vs O, 5 vs S)
- Merges line-wrapped calls
- Standardizes cardinal directions (e.g., "South 56 degrees 40 minutes West" → "S 56°40' W")
- **Preserves** all numbers, bearings, and distances exactly

---

### 4. extract_calls.yaml
**Purpose**: Extract individual calls/courses from normalized legal description (AI-assisted experimental method)

**Model**: OpenAI `gpt-4.1` (default)
**API/Client**: Provider-dependent (`OpenAIClient` or `GeminiClient`)
**Input**: Normalized legal description text
**Output**: JSON array of structured call data

**Use Case**: Experimental AI-based call extraction. **Note**: Production code uses rule-based `CallExtractor` for reliability.

**Output Structure**:
```json
{
  "calls": [
    {
      "course": 1,
      "direction_text": "S 56°40' W",
      "distance": 50.0,
      "distance_unit": "feet",
      "curve_dir": null,
      "radius": null,
      "delta_deg": null,
      "arc_length": null,
      "along": "southerly line of Pennbrook Drive",
      "to": "iron pin",
      "notes": null
    }
  ]
}
```

---

## Prompt Structure

All prompt files follow this YAML structure:

```yaml
name: prompt_name
description: Brief description of what this prompt does

system_prompt: |
  Instructions for the AI model about its role and behavior.

user_prompt_template: |
  Template for the user message. Can include placeholders like {document_text}.

output_format: text|json
```

## How Prompts Are Used

Prompts are loaded by `PDFProcessor` in `src/metesparser/pdf_processor.py`:

```python
def _load_prompt(self, prompt_name: str) -> dict:
    """Load a prompt from YAML file."""
    prompt_path = self.prompts_dir / f"{prompt_name}.yaml"
    with open(prompt_path) as f:
        return yaml.safe_load(f)
```

Then used with appropriate formatting:

```python
prompt_config = self._load_prompt("extract_legal_description")
user_prompt = prompt_config["user_prompt_template"].format(document_text=doc_text)

# Combine system and user prompts for the configured LLM client
combined_prompt = f"{prompt_config['system_prompt']}\n\n{user_prompt}"

response = client.generate_text(combined_prompt)
```

## Processing Pipeline

The complete PDF processing pipeline uses prompts in this order:

```
1. extract_text_from_pdf.yaml
   └─> Raw PDF text

2. extract_legal_description.yaml
   └─> Legal description only

3. normalize_text.yaml
   └─> Normalized text

4. (Rule-based CallExtractor - no AI)
   └─> Structured DeedCall objects

5. (Optional) extract_calls.yaml
   └─> AI-extracted calls (experimental)
```

## Best Practices

### ✓ DO:
- Modify prompts to improve extraction accuracy
- Add specific examples for edge cases
- Test changes with multiple sample deeds
- Keep temperature at 0 for deterministic output
- Preserve exact measurements and bearings

### ✗ DON'T:
- Ask AI to fabricate missing bearings
- Change numbers or measurements
- Remove preservation instructions
- Use high temperature settings
- Modify the rule-based extraction logic via prompts

## Model Configuration

Defaults are:

- OpenAI: **gpt-4.1**
- Gemini: **gemini-2.5-pro** (with optional fallback model in `GeminiClient`)

Prompts are provider-agnostic, so model changes are provider-specific and should be made in the client configuration.

## Testing Prompts

Test prompt changes using:

```bash
# Test full pipeline
uv run python scripts/extract_sample_deeds.py

# Test specific deed
uv run metesparser extract sample_deeds/deed.pdf

# Run integration tests
uv run pytest tests/integration/test_pdf_processing.py -v
```

## GPT-4.1 Optimizations

All prompts have been optimized according to [OpenAI's GPT-4.1 prompting guide](https://cookbook.openai.com/examples/gpt-4.1/gpt-4.1_prompting_guide):

### ✓ Applied Best Practices

1. **XML-Style Delimiters**: All prompts use structured XML tags to segment instructions
   ```xml
   <task>...</task>
   <critical_rules>...</critical_rules>
   <instruction>...</instruction>
   ```

2. **Self-Reflection Prompting**: Phrases like "Think carefully" and "Think step-by-step" encourage deeper reasoning

3. **Structured Sections**: Clear separation of:
   - Task definition
   - Rules and requirements
   - Examples
   - Output specifications

4. **Explicit Constraints**: Critical warnings and preservation requirements clearly stated

5. **Concrete Examples**: Demonstrations of desired transformations (especially in normalize_text.yaml)

6. **Precise Output Format**: Explicit requirements for what should and shouldn't be included

### Optimization Benefits

- **Improved Accuracy**: More precise extraction and fewer hallucinations
- **Better Consistency**: Structured prompts lead to more predictable outputs
- **Reduced Errors**: Explicit warnings prevent common mistakes (e.g., fabricating bearings)
- **Easier Debugging**: Clear sections make it easy to identify and fix prompt issues

## Version History

- **v0.3**: Optimized all prompts for GPT-4.1 using XML delimiters, self-reflection, and structured sections
- **v0.2**: Added `extract_text_from_pdf.yaml`, updated all models to gpt-4.1
- **v0.1**: Initial prompts (extract_legal_description, normalize_text, extract_calls)

---

For questions or improvements, see the main project documentation in `/docs`.
