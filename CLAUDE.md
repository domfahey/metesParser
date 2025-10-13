# Metes Parser - Claude Code Configuration

## Project Overview

Metes Parser is a Python application that extracts, parses, and verifies metes and bounds legal descriptions from deed PDFs. It converts unstructured legal text into structured, verified CSV format suitable for GIS plotting and analysis.

## Tech Stack

- **Python 3.11+**
- **UV** for dependency management (NO pip/poetry/conda)
- **OpenAI API** for PDF OCR and extraction
- **Pydantic** for data validation
- **Pandas** for CSV operations
- **pytest** for testing
- **ruff + black** for linting/formatting

## Key Features

1. PDF text extraction using OpenAI
2. Legal description parsing with regex
3. Bearing-to-azimuth conversion
4. Traverse closure verification (6 guardrails)
5. CSV export with standard schema
6. Never fabricates missing bearings

## Project Structure

```
metesParser/
├── src/metesparser/
│   ├── models.py              # Pydantic models (DeedCall, LegalDescription, ClosureResult)
│   ├── bearing_converter.py   # Quadrant ↔ azimuth conversion, curve calculations
│   ├── text_parser.py         # Text normalization, OCR error fixes
│   ├── call_extractor.py      # Regex-based call extraction
│   ├── closure_checker.py     # 6 verification guardrails
│   ├── csv_builder.py         # CSV export/import
│   ├── pdf_processor.py       # OpenAI-based PDF processing
│   └── cli.py                 # Command-line interface
├── prompts/                   # OpenAI prompt YAML files
├── tests/                     # Pytest test suite
└── docs/                      # Additional documentation
```

## Development Commands

```bash
# Setup
uv venv
uv sync --all-extras --dev

# Run CLI
uv run metesparser extract deed.pdf
uv run metesparser verify calls.csv
uv run metesparser export calls.csv --format geojson

# Testing
uv run pytest
uv run pytest --cov=src/metesparser --cov-report=html

# Linting
uv run ruff check .
uv run ruff format .
uv run black .

# Type checking
uv run mypy src/metesparser
```

## Environment Variables

Create `.env` file:
```
OPENAI_API_KEY=your_key_here
LOG_LEVEL=INFO
```

## Core Principles

1. **Never fabricate bearings** - If only "southwesterly" is given, leave bearing blank
2. **Close before verifying** - Traverse must close to <0.01 ft for _verified.csv
3. **Preserve verbatim wording** - Keep original deed language in along/to fields
4. **Six verification guardrails**:
   - A) Traverse closure
   - B) Interior angle validation
   - C) Parallelism checks
   - D) Curve consistency
   - E) Area reasonableness
   - F) Double-entry validation

## CSV Schema

Standard output format:
```
course,direction_text,bearing_quadrant,bearing_azimuth_deg_from_north,distance_ft,
curve_dir,radius_ft,delta_deg,arc_length_ft,chord_bearing,chord_length_ft,
along,to,notes
```

## Bearing Convention

- Azimuth: degrees clockwise from North (0-360)
- Quadrant conversion:
  - N θ E → az = θ
  - S θ E → az = 180 - θ
  - S θ W → az = 180 + θ
  - N θ W → az = 360 - θ

## Unit Conversions

- Pole = Rod = Perch = 16.5 ft
- Chain = 66 ft
- Link = 0.66 ft
- Acre = 43,560 sq ft

## Git Workflow

- Never push to main
- Always use branches and PRs
- Never commit secrets/API keys
- Always commit verified CSVs only

## Testing Approach

TDD (Test-Driven Development):
1. Write test first
2. Implement feature
3. Verify test passes
4. Refactor if needed

## Common Issues

1. **OCR errors**: 0↔°, 1↔l/I, 5↔S, 2↔7
2. **Line wrapping**: Merge with merge_line_wrapped_calls()
3. **Missing bearings**: Flag as "incomplete" in notes
4. **Curve approximations**: Use chord for plotting

## Contact

For issues or questions, refer to project README and playbook documentation.
