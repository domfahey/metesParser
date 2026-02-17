 # Metes Parser

Parse metes and bounds legal descriptions from deed PDFs into structured, verified CSV format.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

## Features

- **PDF Extraction** - Extract legal descriptions using OpenAI or Gemini APIs
- **Bearing Conversion** - Quadrant bearings to azimuth (degrees from North)
- **Curve Support** - Full radius, delta, arc length, chord calculations; compound/reverse curves
- **8 Verification Checks** - Traverse closure, angles, curves, area, parallelism, double-entry, bearing reversals, distance reasonableness
- **CSV Export** - Standard 21-field schema for GIS plotting
- **Monument Classification** - Automatically identifies survey marker types (iron rod, stone, brass cap, etc.)
- **PLSS Support** - Extracts Section, Township, Range, Principal Meridian metadata
- **Exception Handling** - Parses EXCEPT/LESS AND EXCEPT clauses with proper area calculations
- **POB Closure Detection** - Identifies calls that close back to Point of Beginning
- **POC vs POB Distinction** - Separates Point of Commencement (survey reference) from Point of Beginning (parcel boundary)
- **Never Fabricates Data** - Flags incomplete bearings, never invents numbers
- **Unit Conversion** - Supports feet, poles, rods, chains, varas, arpents, toises, furlongs, meters, miles, engineer chains/links
- **Quality Scoring** - Per-call quality (high/medium/low) and overall confidence score (0.0-1.0)
- **Audit Sidecar** - Optional `.audit.json` + `.audit.html` alongside verified CSV for full transparency
- **LLM Caching** - File-based response caching for deterministic, cost-effective re-extraction
- **Run Registry** - Track prompt versions and extraction results for A/B comparison across runs
- **Composable Packages** - 7 independently installable packages in a uv workspace monorepo

## Recent Updates (v0.4.0)

- **Composable Package Architecture** - Refactored into 7 independently installable packages in a uv workspace monorepo (mp-models, mp-bearing, mp-ocr, mp-parse, mp-verify, mp-export, metesparser). Each package does one thing well; the monolith is preserved for backward compatibility.
- **Pipeline Orchestrator** - `Pipeline` class chains mp-ocr -> mp-parse -> mp-verify -> mp-export in a single call.
- **Audit Sidecar** - Full transparency with `.audit.json` + `.audit.html` alongside verified CSV. Tracks LLM extraction confidence, per-call source excerpts, field-level transformations, and verification results.
- **Quality Scoring** - Per-call quality (high/medium/low) and weighted confidence score (0.0-1.0) on `ClosureResult`.
- **Run Registry** - Track prompt versions (git SHA + content hash) and extraction metrics per run. Compare results with `metesparser compare-runs`.
- **Ground Truth Review Packets** - Self-contained HTML review pages per deed with traverse plots, call tables, and text comparison.
- **38 features** across 6 phases: foundation units, enhanced parsing, verification checks, geometric completeness, production features, and audit transparency.
- **~994 tests, ~93% coverage** with unit, integration, regression, and e2e categories.
- 87 sample deeds with ground truth JSON + LlamaParse markdown conversions.
- Gemini LLM provider support alongside OpenAI (`--llm-provider gemini`).
- File-based LLM response caching via `CachedLLMClient`.

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

# Compare extraction runs across prompt versions
uv run metesparser compare-runs
uv run metesparser compare-runs --pdf pennbrook

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

#### Logging

MetesParser uses `structlog` for structured logs in both CLI and library modules.

```bash
# Human-readable console logs (default)
uv run metesparser --log-level INFO extract deed.pdf

# Debug mode (includes callsite metadata)
uv run metesparser --debug extract deed.pdf

# JSON logs for ingestion/automation
uv run metesparser --log-format json verify calls.csv
```

You can also configure defaults via environment variables:

```bash
export METESPARSER_LOG_LEVEL=DEBUG
export METESPARSER_LOG_FORMAT=json   # console or json
```

### Python API

```python
# Using the Pipeline orchestrator (recommended)
from pathlib import Path
from metesparser import Pipeline

pipe = Pipeline(provider="openai", cache=True, audit=True)
result, audit_ctx = pipe.run(Path("deed.pdf"))

# Or using individual components
from metesparser import PDFProcessor, ClosureChecker

processor = PDFProcessor()
legal_desc = processor.process_deed_pdf("deed.pdf")

result = ClosureChecker.verify_closure(legal_desc.calls)

print(f"Misclosure: {result.misclosure_ft:.4f} ft")
print(f"Area: {result.area_acres:.4f} acres")
print(f"Status: {'VERIFIED' if result.is_fully_verified() else 'NEEDS REVIEW'}")
```

## Architecture

### Composable Packages

The codebase is a **uv workspace monorepo** with 7 independently installable packages following Unix philosophy (each does one thing well):

| Package | Purpose | Dependencies |
|---------|---------|--------------|
| `mp-models` | Pydantic schemas, JSONL envelope, units | None |
| `mp-bearing` | Pure math: azimuth, curves, deltas | mp-models |
| `mp-ocr` | LLM boundary: PDF -> text (OpenAI/Gemini) | mp-models |
| `mp-parse` | Rule-based parsing: text -> calls | mp-models, mp-bearing |
| `mp-verify` | Geometric verification: 8 checks | mp-models, mp-bearing |
| `mp-export` | CSV/JSON/audit HTML output | mp-models, mp-verify |
| `metesparser` | Pipeline orchestrator + CLI | All packages |

Only `mp-ocr` calls LLMs; everything downstream is deterministic.

### Data Flow

```
PDF -> mp-ocr -> mp-parse -> mp-verify -> mp-export
       LLM       Rules       8 checks    _verified.csv
       extract    extract     closure     .audit.json
                  calls       area        .audit.html
```

### Monolith Modules (Backward Compatibility)

The original monolith in `src/metesparser/` is preserved for backward compatibility:

| Module | Package Equivalent |
|--------|-------------------|
| `models.py` | `mp-models` |
| `bearing_converter.py` | `mp-bearing` |
| `text_parser.py`, `call_extractor.py` | `mp-parse` |
| `pdf_processor.py`, `llm_clients.py`, `llm_cache.py` | `mp-ocr` |
| `closure_checker.py` | `mp-verify` |
| `csv_builder.py`, `audit_reporter.py` | `mp-export` |
| `pipeline.py`, `cli.py`, `run_registry.py` | `metesparser` |

### Verification Checks

The system implements 8 checks before exporting verified CSV:

1. **Traverse Closure** - Misclosure < 0.01 ft
2. **Interior Angles** - Sum matches (n-2)x180 degrees
3. **Parallelism** - Continuing lines have matching bearings
4. **Curve Consistency** - L ~ R*delta, chord ~ 2R*sin(delta/2)
5. **Area Reasonableness** - Computed vs stated area
6. **Double-Entry Validation** - Compare duplicate entries
7. **Bearing Reversal Detection** - Adjacent courses ~180 degrees apart (5 degree threshold)
8. **Distance Reasonableness** - Flags <0.5 ft, >10x median, >90% perimeter

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
make format        # Format code with ruff
make test          # Run pytest test suite
make test-cov      # Run tests with coverage report
make pre-commit    # Run all checks before committing
```

### Running Tests

The test suite runs ~994 tests organized by type:

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

# Run per-package tests (requires --no-cov)
uv run pytest packages/mp-models/tests/ -v --no-cov
for pkg in packages/mp-*/tests/; do uv run pytest "$pkg" -v --no-cov; done

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

Standard 21-field output format:

```csv
course,direction_text,bearing_quadrant,bearing_azimuth_deg_from_north,distance_ft,
curve_dir,radius_ft,delta_deg,arc_length_ft,chord_bearing,chord_length_ft,
along,to,monument_type,monument_status,is_exception,is_meander,is_tie_in,
non_tangent,radial_bearing,notes
```

**Example:**
```csv
1,"S 33 20' E","S 33 20' E",146.666667,60.00,,,,,,"SW line of Concord Dr","a point in the division line","iron_pin",,false,false,"",""
2,"S 56 40' W","S 56 40' W",236.666667,125.00,,,,,,"Div. line L46/47 to L50","point corner to Lot 50","stone",,false,false,"",""
```

**Key Fields:**
- `monument_type`: Classified survey marker type (20 types including iron_rod, iron_pin, stone, brass_cap, etc.)
- `monument_status`: Endpoint monument status (`found`, `set`, or empty)
- `is_exception`: Boolean indicating if this call is part of an EXCEPT clause
- `is_meander`: Boolean flag for water boundary / meander line
- `is_tie_in`: Boolean flag for tie-in calls (POC-to-POB, excluded from closure)
- `non_tangent`: Boolean flag for non-tangent curves
- `radial_bearing`: Radial bearing for non-tangent curves

## Bearing Convention

Azimuth = degrees clockwise from North (0-360):

| Quadrant | Example | Azimuth Formula | Result |
|----------|---------|-----------------|--------|
| N x E | N 45 E | x | 45 |
| S x E | S 45 E | 180 - x | 135 |
| S x W | S 45 W | 180 + x | 225 |
| N x W | N 45 W | 360 - x | 315 |

## Unit Conversions

| Unit | Feet Equivalent |
|------|-----------------|
| 1 pole/rod/perch | 16.5 ft |
| 1 chain | 66 ft |
| 1 link | 0.66 ft |
| 1 vara | 2.778 ft (Texas) |
| 1 arpent | 191.8 ft (French colonial) |
| 1 toise | 6.395 ft |
| 1 furlong | 660 ft |
| 1 meter | 3.28084 ft |
| 1 mile | 5,280 ft |
| 1 engineer chain | 100 ft |
| 1 engineer link | 1.0 ft |
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
├── pyproject.toml               # UV workspace root + tool settings
├── packages/                    # Composable packages (uv workspace)
│   ├── mp-models/               # Pydantic schemas, JSONL envelope, units
│   ├── mp-bearing/              # Pure math: azimuth, curves, deltas
│   ├── mp-ocr/                  # LLM boundary: PDF -> text
│   ├── mp-parse/                # Rule-based parsing: text -> calls
│   ├── mp-verify/               # Geometric verification: 8 checks
│   └── mp-export/               # CSV/JSON/audit HTML output
├── src/metesparser/             # Orchestrator + backward-compat monolith
│   ├── pipeline.py              # Pipeline orchestrator
│   ├── cli.py                   # Command-line interface
│   ├── run_registry.py          # Prompt A/B testing
│   ├── review_packet.py         # Ground truth review packets
│   └── ...                      # Monolith modules (kept in sync with packages)
├── prompts/                     # Prompt YAML files
├── tests/                       # Pytest test suite (~994 tests, ~93% coverage)
│   ├── unit/                    # Unit tests
│   ├── integration/             # Integration tests
│   ├── e2e/                     # End-to-end CLI tests
│   └── regression/              # Bug fix tests
├── scripts/                     # Utility scripts
├── sample_deeds/                # 87 sample PDFs + ground truth JSON + LlamaParse markdown
├── docs/                        # Documentation
├── CLAUDE.md                    # AI assistant guidance
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
- Check for OCR errors in bearings (0 vs degree symbol, 1 vs l/I, 5 vs S)
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
