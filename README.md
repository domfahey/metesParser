# Metes Parser

Parse metes and bounds legal descriptions from deed PDFs into structured, verified CSV format.

## Features

- Extract legal descriptions from PDF deeds using OpenAI Responses API
- Parse bearing/distance calls with proper quadrant-to-azimuth conversion
- Support for curves (radius, delta, arc length, chord)
- Traverse closure verification (6 guardrails)
- Export to CSV, GeoJSON, KML formats
- Flag incomplete/meander lines (never fabricate bearings)
- Comprehensive unit conversion (feet, poles, chains)

## Installation

```bash
# Clone repository
git clone <repo-url>
cd metesParser

# Set up environment with UV
uv venv
uv sync --all-extras --dev

# Configure API keys
cp .env.example .env
# Edit .env with your OpenAI API key
```

## Quick Start

```bash
# Extract legal description from PDF
uv run metesparser extract deed.pdf

# Verify a CSV file
uv run metesparser verify calls.csv

# Export to GeoJSON
uv run metesparser export calls_verified.csv --format geojson
```

## Project Structure

```
metesParser/
├── src/metesparser/         # Main package
│   ├── models.py            # Pydantic models
│   ├── pdf_processor.py     # PDF extraction & OCR
│   ├── text_parser.py       # Legal description parsing
│   ├── call_extractor.py    # Extract individual calls
│   ├── bearing_converter.py # Bearing/azimuth conversions
│   ├── closure_checker.py   # Traverse verification
│   └── csv_builder.py       # CSV output generation
├── prompts/                 # OpenAI prompt YAML files
├── tests/                   # Pytest test suite
└── docs/                    # Documentation
```

## Usage

### Extract from PDF

```python
from metesparser import PDFProcessor

processor = PDFProcessor()
legal_desc = processor.extract_legal_description("deed.pdf")
```

### Parse Calls

```python
from metesparser import CallExtractor

extractor = CallExtractor()
calls = extractor.extract_calls(legal_desc)
```

### Verify Closure

```python
from metesparser import ClosureChecker

checker = ClosureChecker()
result = checker.verify_closure(calls)
print(f"Misclosure: {result.misclosure_ft} ft")
print(f"Area: {result.area_sq_ft} sq ft")
```

## CSV Schema

Standard output format:

```
course,direction_text,bearing_quadrant,bearing_azimuth_deg_from_north,distance_ft,
curve_dir,radius_ft,delta_deg,arc_length_ft,chord_bearing,chord_length_ft,
along,to,notes
```

## Development

### Using Makefile (Recommended)

```bash
# Show all available commands
make help

# Code quality
make lint          # Run ruff linter
make format        # Format code with ruff and black
make lint-fix      # Auto-fix linting issues
make check         # Run all checks (lint + format check)

# Testing
make test          # Run pytest test suite
make test-cov      # Run tests with coverage report

# Utility
make clean         # Remove build artifacts and cache
make dev-setup     # Initial development setup
make pre-commit    # Run all checks before committing
```

### Manual Commands

```bash
# Run tests
uv run pytest

# Run linting
uv run ruff check src/metesparser
uv run ruff format src/metesparser
uv run black src/metesparser --exclude text_parser.py

# Type checking
uv run mypy src/metesparser
```

## Verification Guardrails

The system implements 6 verification checks:
- A) Traverse closure (misclosure < 0.01 ft)
- B) Interior angle validation
- C) Parallelism checks
- D) Curve consistency
- E) Area reasonableness
- F) Double-entry validation

## License

MIT

## Credits

Based on comprehensive metes & bounds extraction best practices.
