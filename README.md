 # Metes Parser

Parse metes and bounds legal descriptions from deed PDFs into structured, verified CSV format.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

## Features

- 📄 **PDF Extraction** - Extract legal descriptions using OpenAI or Gemini APIs
- 🧭 **Bearing Conversion** - Quadrant bearings to azimuth (degrees from North)
- 📐 **Curve Support** - Full radius, delta, arc length, chord calculations
- ✅ **6 Verification Guardrails** - Traverse closure, angles, curves, area, parallelism
- 📊 **CSV Export** - Standard 16-field schema for GIS plotting
- 🏛️ **Monument Classification** - Automatically identifies survey marker types (iron rod, stone, brass cap, etc.)
- 🗺️ **PLSS Support** - Extracts Section, Township, Range, Principal Meridian metadata
- ⚠️ **Exception Handling** - Parses EXCEPT/LESS AND EXCEPT clauses with proper area calculations
- 🔁 **POB Closure Detection** - Identifies calls that close back to Point of Beginning
- 📍 **POC vs POB Distinction** - Separates Point of Commencement (survey reference) from Point of Beginning (parcel boundary)
- 🚫 **Never Fabricates Data** - Flags incomplete bearings, never invents numbers
- 🔄 **Unit Conversion** - Supports feet, poles, rods, chains

## Recent Updates

- Reference docs gained prosser/metes-and-bounds content updates and BLM module additions from recent sessions.
- Gemini LLM provider support added alongside OpenAI (`--llm-provider gemini`).
- Pydantic guardrails tightened for curve and numeric inputs with comprehensive TDD coverage.
- End-to-end CLI and pipeline-contract tests validate full extraction/verification workflows.
- CLI and LLM client exception assertions, and report/date parsing edge-case assertions were hardened.
- Ground truth JSON files stored alongside each sample PDF in `sample_deeds/` for replayable extraction checks.
- `make check` runs the full quality gate (`lint`, `format`, `type`, `test`) in one command.

## Ground Truth Workflow

- Generate missing ground-truth JSON outputs:
```bash
uv run python scripts/generate_ground_truth.py
```
- Extract and verify a sample PDF:
```bash
uv run metesparser extract sample_deeds/"18 Pennbrook Dr - Deed Image (11985 - 00829).pdf"
uv run metesparser verify sample_deeds/"18 Pennbrook Dr - Deed Image (11985 - 00829).csv"
```
- Run full sample extraction report generation:
```bash
uv run python scripts/extract_sample_deeds.py
```

## Project Workflow Notes

- Use `make run-extract` and `make run-verify` for quick local checks.
- Use `make check` for the full quality gate (lint + format + type + tests) and `make test-cov` for coverage.

## Quick Start

### Installation

```bash
# Clone and setup
git clone <repo-url>
cd metesParser
make dev-setup

# Copy environment template
cp .env.example .env

# Configure your preferred LLM provider in .env
echo "METESPARSER_LLM_PROVIDER=openai" >> .env
echo "OPENAI_API_KEY=sk-..." >> .env
# or for Gemini:
# echo "METESPARSER_LLM_PROVIDER=gemini" >> .env
# echo "GEMINI_API_KEY=..." >> .env
```

### Usage

```bash
# Extract legal description from PDF
uv run metesparser extract deed.pdf

# Verify calls from CSV
uv run metesparser verify calls.csv

# Or use the Makefile
make run-extract PDF_FILE=deed.pdf
make run-verify CSV_FILE=calls.csv
```

#### Choosing an LLM Provider

By default MetesParser uses OpenAI. To switch providers either set the environment variable
`METESPARSER_LLM_PROVIDER` (`openai` or `gemini`) or pass the CLI flag:

```bash
uv run metesparser extract deed.pdf --llm-provider gemini
```

### Python API

```python
from metesparser import PDFProcessor, ClosureChecker

# Extract and parse
processor = PDFProcessor()
legal_desc = processor.process_deed_pdf("deed.pdf")

# Verify closure
checker = ClosureChecker()
result = checker.verify_closure(legal_desc.calls)

print(f"Misclosure: {result.misclosure_ft:.4f} ft")
print(f"Area: {result.area_acres:.4f} acres")
print(f"Status: {'✓ VERIFIED' if result.is_fully_verified() else '⚠ NEEDS REVIEW'}")
```

## Architecture

### Data Flow

```
PDF → Extract → Normalize → Parse Calls → Verify → CSV
       LLM      TextParser  CallExtractor  Closure  _verified.csv
                                          Checker   (if passed)
```

### Core Modules

| Module | Purpose |
|--------|---------|
| `models.py` | Pydantic schemas (DeedCall, LegalDescription, ClosureResult) |
| `bearing_converter.py` | Quadrant ↔ azimuth, curve calculations |
| `text_parser.py` | Text normalization, OCR error fixes |
| `call_extractor.py` | Regex-based call parsing (rule-based, not AI) |
| `closure_checker.py` | 6 verification guardrails |
| `csv_builder.py` | CSV export/import with standard schema |
| `pdf_processor.py` | LLM integration for PDF extraction (OpenAI/Gemini) |
| `llm_clients.py` | BaseLLMClient ABC, OpenAIClient, GeminiClient providers |
| `cli.py` | Command-line interface |

### Verification Guardrails

The system implements 6 checks before exporting verified CSV:

1. **Traverse Closure** - Misclosure < 0.01 ft
2. **Interior Angles** - Sum matches (n-2)×180°
3. **Parallelism** - Continuing lines have matching bearings
4. **Curve Consistency** - L ≈ R×Δ, chord ≈ 2R×sin(Δ/2)
5. **Area Reasonableness** - Computed vs stated area
6. **Double-Entry Validation** - Compare duplicate entries

## Development

### Prerequisites

- Python 3.11+
- [UV](https://github.com/astral-sh/uv) (required for dependency management)
- OpenAI or Google Gemini API key

### Setup

```bash
# Install dependencies
make install

# Or manually with UV
uv venv
uv sync --all-extras --dev
```

### Common Commands

```bash
make help          # Show all available commands
make check         # Run full quality gate (lint + format + type + tests)
make lint          # Run ruff linter
make format        # Format code with ruff + black
make test          # Run pytest test suite
make test-cov      # Run tests with coverage report
make pre-commit    # Run all checks before committing
```

### Running Tests

The test suite currently runs 297 tests organized by type (as of 2026-02-15):

```bash
# Run all tests (unit + integration + e2e + regression)
make test

# Run only fast unit tests (skip PDF tests)
uv run pytest tests/unit/ -v

# Run integration tests
uv run pytest tests/integration/ -v

# Skip slow tests (excludes PDF processing tests)
uv run pytest -m "not slow"

# Run PDF processing tests
uv run pytest tests/integration/test_pdf_processing.py -v

# Run specific test markers
uv run pytest -m curve           # Curve-related tests
uv run pytest -m validation      # Input validation tests

# Run specific test file
uv run pytest tests/unit/test_bearing_converter.py -v

# Run tests matching pattern
uv run pytest -k "closure" --pdb

# Generate coverage report
make test-cov
open htmlcov/index.html
```

**PDF Processing Tests**: The current integration PDF suite is mocked, so no live LLM calls are required by default.
- Verifies extraction orchestration and geometry pipeline behavior with fixture inputs
- Uses `sample_deeds/` fixture PDFs for realistic input coverage
- Focuses on deterministic behavior and regression protection

See [docs/TESTING.md](docs/TESTING.md) for comprehensive testing documentation including detailed PDF test guide.

### Code Quality

```bash
# Check code quality
make lint

# Auto-fix issues
make lint-fix

# Format code
make format

# Run all checks
# Includes lint, format, type checking, and test suite
make check
```

## CSV Schema

Standard 16-field output format:

```csv
course,direction_text,bearing_quadrant,bearing_azimuth_deg_from_north,distance_ft,
curve_dir,radius_ft,delta_deg,arc_length_ft,chord_bearing,chord_length_ft,
along,to,monument_type,is_exception,notes
```

**Example:**
```csv
1,"S 33°20' E","S 33°20' E",146.666667,60.00,,,,,,,"SW line of Concord Dr","iron pin",iron_pin,false,""
2,"S 56°40' W","S 56°40' W",236.666667,125.00,,,,,,,"Div. line L46/47 to L50","stone monument",stone,false,""
```

**New Fields:**
- `monument_type`: Classified survey marker type (iron_rod, iron_pin, iron_pipe, stone, concrete, wooden_post, brass_cap, rebar, railroad_spike, nail, other)
- `is_exception`: Boolean indicating if this call is part of an EXCEPT clause

## Bearing Convention

Azimuth = degrees clockwise from North (0-360°):

| Quadrant | Example | Azimuth Formula | Result |
|----------|---------|-----------------|--------|
| N θ E | N 45° E | θ | 45° |
| S θ E | S 45° E | 180 - θ | 135° |
| S θ W | S 45° W | 180 + θ | 225° |
| N θ W | N 45° W | 360 - θ | 315° |

## Unit Conversions

| Unit | Feet Equivalent |
|------|-----------------|
| 1 pole/rod/perch | 16.5 ft |
| 1 chain | 66 ft |
| 1 link | 0.66 ft |
| 1 acre | 43,560 sq ft |

## Core Principles

1. **Never Fabricate Data** - If bearing is incomplete (e.g., "southwesterly"), leave azimuth blank and flag in notes
2. **Verification First** - Traverse must close to <0.01 ft before exporting `_verified.csv`
3. **Preserve Original Wording** - Keep deed language verbatim in `along` and `to` fields
4. **Deterministic Processing** - LLM temperature=0 for consistent results

## Project Structure

```
metesParser/
├── Makefile                     # Development commands
├── pyproject.toml               # UV configuration + tool settings
├── src/metesparser/             # Main package (10 modules)
│   ├── models.py
│   ├── bearing_converter.py
│   ├── text_parser.py
│   ├── call_extractor.py
│   ├── closure_checker.py
│   ├── csv_builder.py
│   ├── pdf_processor.py
│   ├── llm_clients.py
│   └── cli.py
├── prompts/                     # Prompt YAML files
├── tests/                       # Pytest test suite (297 tests as of 2026-02-15)
│   ├── conftest.py              # Shared fixtures
│   ├── helpers.py               # Test utilities
│   ├── fixtures/                # Sample legal descriptions
│   ├── unit/                    # Unit tests (14 files)
│   ├── integration/             # Integration tests
│   ├── e2e/                     # End-to-end CLI tests
│   └── regression/              # Bug fix tests
├── scripts/                     # Standalone utility scripts
├── sample_deeds/                # Sample PDFs + ground truth JSON
├── docs/                        # Documentation
│   ├── reference/               # Reference PDFs (BLM manual, etc.)
│   ├── METES_AND_BOUNDS_REFERENCE.md  # Surveying reference
│   ├── TESTING.md               # Test suite guide
│   ├── ARCHITECTURE.md          # System design
│   ├── API.md                   # Python API reference
│   └── CONTRIBUTING.md          # Development guidelines
├── CLAUDE.md                    # AI assistant guidance
├── AGENTS.md                    # Agent workflow documentation
└── bugs.md                      # Known issues tracker
```

## Requirements

- Python 3.11+
- OpenAI or Gemini API key (based on selected provider)
- UV package manager (no pip/conda/poetry)

## Environment Variables

Create a `.env` file:

```bash
METESPARSER_LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...  # Required
GEMINI_API_KEY=...      # Required when using Gemini
LOG_LEVEL=INFO          # Optional (default: INFO)
```

## Troubleshooting

### Common Issues

**"LLM API key not found"**
- Ensure `.env` file exists with `OPENAI_API_KEY` or `GEMINI_API_KEY` for your selected provider
- Run `make dev-setup` to create `.env` from template

**Traverse doesn't close**
- Check for OCR errors in bearings (0 vs °, 1 vs l/I, 5 vs S)
- Verify distance units (feet vs poles)
- Review misclosure report for specific issues

**Linting fails on text_parser.py**
- This is expected - file contains Unicode symbols that break parsers
- File is excluded in `pyproject.toml` and functionally correct

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run quality checks (`make pre-commit`)
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

**Never commit:**
- `.env` files or API keys
- Unverified CSV files (only commit `_verified.csv`)
- Code that fabricates bearings

## License

MIT

## Credits

Based on comprehensive metes & bounds extraction best practices from professional surveying standards.

## Documentation

- **[README.md](README.md)** - This file, overview and quick start
- **[docs/TESTING.md](docs/TESTING.md)** - Test suite guide and best practices
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** - System design and data flow
- **[docs/API.md](docs/API.md)** - Python API reference
- **[docs/CONTRIBUTING.md](docs/CONTRIBUTING.md)** - Development guidelines
- **[CLAUDE.md](CLAUDE.md)** - AI assistant context and guidance
- **[AGENTS.md](AGENTS.md)** - Agent workflow documentation
- **[docs/METES_AND_BOUNDS_REFERENCE.md](docs/METES_AND_BOUNDS_REFERENCE.md)** - Surveying reference guide
- **[bugs.md](bugs.md)** - Known issues tracker

## Support

For issues or questions:
- Check relevant documentation above
- Run `make help` for available commands
- Open an issue on GitHub

---

**Note**: This parser follows strict surveying principles. It will never fabricate missing data and requires traverse closure before marking results as verified.
