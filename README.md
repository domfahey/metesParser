# Metes Parser

**Disclaimer:** Metes Parser is an experimental prototype developed with substantial AI-assisted coding to evaluate LLM-assisted extraction and parsing of metes-and-bounds legal descriptions from deed PDFs. It has not undergone peer review, security review, or formal audit. Outputs may contain errors and must be independently verified by qualified professionals before use in any legal, surveying, title, lending, or business decision. This repository must contain only publicly available data - no NPI, PII, or other non-public sensitive information.

> **Note:** This is a work-in-progress prototype exploring AI's ability to extract, parse, and verify metes and bounds legal descriptions from deed PDFs.

Parse metes and bounds legal descriptions into structured calls, inspect source evidence, and run deterministic checks before exporting verified CSV.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

## Why This Exists

Legal descriptions define the property being transferred in a deed. Today, title company employees (e.g., at FNF) manually retype these descriptions from deed documents, then use GIS software like ArcGIS to plot the boundary and confirm the traverse closes. Legal descriptions frequently contain typos — a wrong degree, a flipped quadrant, a transposed distance — and catching these errors is critical to ensuring the correct parcel is identified.

This repository is a **prototype** exploring whether AI can assist with that workflow. The provider-backed Python pipeline extracts legal descriptions from scanned deed PDFs, parses surveying notation into structured data, and runs geometric checks. The sample corpus uses publicly recorded sources. The extraction pipeline accepts deed PDFs containing metes-and-bounds descriptions; source-reading accuracy and selection of the intended description remain separate review tasks.

### Design Pillars

- **Composable architecture** — Independent components let source reading, parsing, verification, and export be evaluated separately and composed as needed.
- **Transparency by design** — Optional audit sidecars (`.audit.json` + `.audit.html`) retain provider extraction and deterministic processing details. The plugin's acquisition and selection records separately preserve source pages, exact text spans, identities, and unresolved readings.
- **AI only where necessary** — Model reading and description selection are source-preparation stages. Within the composable `mp-*` packages, provider calls stay in `mp-ocr`; the compatibility monolith retains its own provider clients. Numerical parsing, bearing math, verification, and export use deterministic code. The Claude plugin performs its native source reading separately.
- **AI as assistant, not replacement** — The tool is designed to augment human judgment, not replace it. Final decisions on property boundaries remain with the professional reviewing the output.

## Features

- **PDF Extraction** - Extract legal descriptions using OpenAI or Gemini APIs
- **Bearing Conversion** - Quadrant bearings to azimuth (degrees from North)
- **Curve Support** - Full radius, delta, arc length, chord calculations; compound/reverse curves
- **Geometric Verification** - Closure, angles, curves, boundary topology, area, parallelism, double-entry, bearing reversals, and distance reasonableness
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
- **LLM Caching** - Retains a previous provider response to avoid repeating extraction calls
- **Run Registry** - Track prompt versions and extraction results for A/B comparison across runs
- **Composable Packages** - 8 independently installable packages in a uv workspace monorepo
- **Source Evidence and Resume Guidance** - Read-only validation of acquisition/selection records and inspection of saved artifacts, dependencies, and restart points
- **Closure Diagnostics** - Source-linked straight-course and supported circular-arc sensitivities, with separate hypothetical scenarios; no automatic correction
- **Description Comparison** - Explicit straight/arc pairs and groups, tentative structural differences, declared units and bearing bases, and optional placement evidence
- **Review Views** - Independent plots, explicit dashboards, and optional online maps with per-scan opacity/order and separate fit/checkpoint evidence
- **Durable Revisions** - Save exact drafts and source-correction evidence under stable identities; publish immutable generations and regenerate shared views from the selected revision
- **Structured Editing** - Edit line and circular-arc calls through the shared revision path; the immediate browser preview is straight-course only
- **Review-Package Delivery** - Freeze published revisions as SVG, PDF, DXF, and GeoJSON with independent inspection and explicit coordinate/layer choices
- **Corridor Geometry** - Preserve centerline width intervals, tapers, joins, caps, and approximation budgets through schema 1.2 revisions and delivery
- **Supplied PLSS References** - Derive geometry only from an identified supplied reference dataset under the supported rectangular rule; PLSS text alone does not establish section geometry
- **Raster Control-Point Picker** - Record pixel controls for raster registration; controls do not place deed geometry

## Claude Plugin Skills

The [MetesParser plugin catalog](plugins/metesparser/README.md) documents thirteen skill entrypoints: ten capabilities (document conversion, description extraction, traverse verification, plotting, overlay preparation, online maps, description comparison, corridors, supplied PLSS references, and review-package export), two workflows (boundary review and the explicitly requested dashboard), and the `review-deed` compatibility alias. Source validation, closure diagnosis, artifact inspection, revision management, and delivery inspection are shared utilities used by these skills. Skills route work through existing Python packages; they are not separate parsing or verification engines. See the [Cowork implementation ledger](docs/implementation/2026-10-28-cowork-workflow-ledger.md) for local evidence and remaining acceptance gates.

The plugin is designed to use Claude's native document/image reading and description selection, followed by deterministic `mp-review` operations. Native Claude/Cowork sessions have not passed acceptance; local tests and extracted-plugin checks do not establish native reading quality or skill discovery. The separate Python PDF pipeline uses OpenAI/Gemini through `mp-ocr`. Use the [shared artifact handoff contract](plugins/metesparser/references/artifact-handoffs.md) for inputs, stopping points, reuse, and status boundaries. Verification, plotting, and overlay preparation can be requested independently; a dashboard requires explicit `DashboardBundle` assembly. See the [composition architecture](docs/ARCHITECTURE.md#skill-composition) for how these paths fit together.

## v0.5.0 Foundation (Historical)

These foundation notes describe the original release. The current package layout and review capabilities are documented below and in the plugin catalog.

- **Composable Package Architecture** - Initially split into six `mp-*` packages plus the root package; `mp-review` was added later. The monolith is preserved for backward compatibility.
- **Pipeline Orchestrator** - `Pipeline.run()` processes a PDF and returns verification results, with an audit context when requested. The CLI and export APIs write output files separately.
- **Audit Sidecar** - Full transparency with `.audit.json` + `.audit.html` alongside verified CSV. Tracks LLM extraction confidence, per-call source excerpts, field-level transformations, and verification results.
- **Quality Scoring** - Per-call quality (high/medium/low) and weighted confidence score (0.0-1.0) on `ClosureResult`.
- **Run Registry** - Track prompt versions (git SHA + content hash) and extraction metrics per run. Compare results with `metesparser compare-runs`.
- **Ground Truth Review Packets** - Self-contained HTML review pages per deed with traverse plots, call tables, and text comparison.
- **38 features** across 6 phases: foundation units, enhanced parsing, verification checks, geometric completeness, production features, and audit transparency.
- Unit, integration, regression, and e2e coverage; see the [testing guide](docs/TESTING.md) and dated implementation evidence for observed results.
- Sample deeds with ground truth JSON and LlamaParse markdown conversions.
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
- Use `make check` for root lint, formatting, typing, and tests, and `make test-cov` for root coverage. Package, plugin, and opt-in browser checks are separate lanes; see [docs/TESTING.md](docs/TESTING.md).

## Quick Start

### Installation

```bash
# Clone and setup
git clone <repo-url>
cd metesParser
make dev-setup    # installs dependencies and creates .env from .env.example

# Edit .env with your API key and preferred provider
# METESPARSER_LLM_PROVIDER=openai   (or gemini)
# OPENAI_API_KEY=sk-...             (required for openai)
# GEMINI_API_KEY=...                (required for gemini)
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

### Deterministic Review and Advisory Tools

These commands accept prepared text, structured calls, or explicit request files; they do not read PDFs or call an LLM:

```bash
uv run metes-review review description.txt --output-dir review-new
uv run metes-review verify calls.json --output-dir verification-new
uv run metes-review plot calls.json --output-dir plot-new

# Read-only utilities: BUNDLE_DIR is an explicit existing directory
uv run metes-review validate-source BUNDLE_DIR
uv run metes-review inspect-artifacts BUNDLE_DIR --requested-stage review

# Typed requests identify immutable calls, source references, and analysis criteria
uv run metes-review diagnose-closure diagnosis-request.json --output-dir diagnostics-new
uv run metes-review compare-descriptions comparison-request.json --output-dir comparison-new
```

Use a new output directory for each producing command. See the [source-record](plugins/metesparser/references/source-preparation.md), [diagnosis](plugins/metesparser/references/closure-diagnostics.md), and [comparison](plugins/metesparser/references/comparison-limits.md) references for complete request examples and limits. The plugin launcher exposes the same commands through `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py"`.

Completed advisory operations intentionally return `needs_review` and exit **1**, including valid source records, usable artifacts, supported diagnosis, and matching comparison results. Invalid input returns `error` and exit **2**. Canonical review/verification can return `checks_passed` and exit **0**; this reports engine checks, not source accuracy or legal correctness. Plotting, diagnosis, comparison, and map/dashboard rendering do not grant verified-export eligibility.

Local engine, browser, and extracted-plugin checks are recorded in the [implementation ledger](docs/implementation/2026-10-28-evidence-review-ledger.md) and the [Cowork workflow ledger](docs/implementation/2026-10-28-cowork-workflow-ledger.md). Native Claude/Cowork reading and workflow acceptance remains unrun; optional live Mapbox provider acceptance is also separate. Local checks do not establish either gate.

### Durable Revisions and Derived Geometry

The deterministic CLI also supports immutable revision publication, fresh revision views, corridor analysis, supplied-reference PLSS derivation, review-package export, delivery inspection, and the optional raster control-point picker:

```bash
uv run metes-review revision-template BUNDLE.json --output REVISION.json --revision-id ID
uv run metes-review save-revision BUNDLE.json --revision REVISION.json --output-dir REVISIONS_DIR
uv run metes-review inspect-revision BUNDLE.json --revision-dir REVISIONS_DIR/ID
uv run metes-review render-revision BUNDLE.json --revision-dir REVISIONS_DIR/ID --output-dir NEW_DIR
uv run metes-review analyze-corridor REQUEST.json --output-dir NEW_DIR
uv run metes-review derive-plss REQUEST.json --output-dir NEW_DIR
uv run metes-review export-review BUNDLE.json --revision-dir REVISIONS_DIR/ID --request REQUEST.json --output-dir NEW_DIR
uv run metes-review inspect-delivery BUNDLE.json --revision-dir REVISIONS_DIR/ID --package-dir PACKAGE_DIR
uv run metes-review pick-raster IMAGE --controls CONTROLS.json --output-dir NEW_DIR
```

Revision schema 1.2 preserves exact raw corridor definitions and replays their geometry from the saved revision. Structured line/arc publication and shared revision rendering support arcs; the immediate browser preview is straight-course only. SVG/PDF/DXF/GeoJSON delivery freezes a named published revision. Corridor output does not imply parcel closure; PLSS geometry requires an identified supplied reference and uses only the supported rectangular derivation. Pixel control points support raster registration, not deed placement. See the [plugin usage guide](plugins/metesparser/README.md) and [revision contract](plugins/metesparser/references/revisions.md) for request shapes and status boundaries.

### Choosing an LLM Provider

By default MetesParser uses OpenAI. To switch providers either set the environment variable
`METESPARSER_LLM_PROVIDER` (`openai` or `gemini`) or pass the CLI flag:

```bash
uv run metesparser extract deed.pdf --llm-provider gemini
```

### Logging

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
# Provider-backed extraction and verification; this does not write CSV files
from pathlib import Path
from metesparser import Pipeline

pipe = Pipeline(provider="openai", cache=True, audit=True)
result, audit_ctx = pipe.run(Path("deed.pdf"))
# Multi-tract PDFs return a list of verification results instead of one result.

# Or using individual components
from metesparser import PDFProcessor, ClosureChecker

processor = PDFProcessor()
legal_desc = processor.process_deed_pdf("deed.pdf")

result = ClosureChecker.verify_closure(legal_desc.calls)

print(f"Misclosure: {result.misclosure_ft:.4f} ft")
print(f"Area: {result.area_acres:.4f} acres")
print(f"Engine status: {'CHECKS PASSED' if result.is_fully_verified() else 'NEEDS REVIEW'}")
```

## Architecture

### Composable Packages

The codebase is a **uv workspace monorepo** with 8 independently installable packages: seven `mp-*` packages plus the root `metesparser` package. Each has a focused responsibility:

| Package | Purpose | Workspace Dependencies |
|---------|---------|--------------|
| `mp-models` | Shared schemas, source/analysis contracts, JSONL envelope, units, logging | None |
| `mp-bearing` | Pure math: azimuth, curves, deltas | mp-models |
| `mp-ocr` | LLM boundary: PDF -> text (OpenAI/Gemini) | mp-models |
| `mp-parse` | Rule-based parsing: text -> calls | mp-models, mp-bearing |
| `mp-verify` | Canonical checks, relative/plot geometry, advisory diagnosis and comparison | mp-models, mp-bearing |
| `mp-export` | CSV/audit output and plot/dashboard/online-map rendering | mp-models, mp-verify |
| `mp-review` | File/CLI adapters, source validation, artifact inspection/replay, review, diagnosis/comparison, overlays and views | mp-models, mp-parse, mp-verify, mp-export |
| `metesparser` | Pipeline orchestrator + CLI | All packages |

Within the composable `mp-*` packages, only `mp-ocr` makes LLM provider calls. The root package also retains compatibility provider clients in `src/metesparser/llm_clients.py`. Parsing, geometry, review, and rendering are deterministic. The Claude plugin performs native source reading outside that provider pipeline.

### Data Flow

The separate provider-backed PDF pipeline remains available:

```
PDF -> mp-ocr -> mp-parse -> mp-verify -> mp-export
       LLM       Rules       Checks      _verified.csv
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
| `plot.py`, `dashboard.py`, `source_handoff.py`, `artifact_inspect.py`, `diagnostics.py`, `comparison.py` | Thin facades to shared package APIs |
| `pipeline.py`, `cli.py`, `run_registry.py` | `metesparser` |

### Verification Checks

The canonical verifier reports structured check outcomes, with explicit `passed`, `failed`, `not_applicable`, or `blocked` outcomes:

1. **Traverse Closure** - Misclosure < 0.01 ft
2. **Interior Angles** - Sum matches (n-2)x180 degrees
3. **Parallelism** - Continuing lines have matching bearings
4. **Curve Consistency** - L ~ R*delta, chord ~ 2R*sin(delta/2)
5. **Area Reasonableness** - Computed vs stated area
6. **Double-Entry Validation** - Compare duplicate entries
7. **Bearing Reversal Detection** - Adjacent courses ~180 degrees apart (5 degree threshold)
8. **Distance Reasonableness** - Flags <0.5 ft, >10x median, >90% perimeter
9. **Boundary Topology** - Detects intersections in supported straight and circular-arc boundaries

Closing within 0.01 ft alone is insufficient. Verified export rechecks the exact calls, requires eligible canonical outcomes and no warnings, and rejects stale or mismatched verification. Source review, relative analysis, diagnostic availability, comparison agreement, and map placement remain separate statuses.

## Development

### Prerequisites

- Python 3.11+
- [UV](https://github.com/astral-sh/uv) (required for dependency management)
- OpenAI or Google Gemini API key only for live provider-backed PDF extraction

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
make check         # Root lint + format + type + tests
make lint          # Run ruff linter
make format        # Format code with ruff
make test          # Run pytest test suite
make test-cov      # Run tests with coverage report
make pre-commit    # Root lint-fix + format + tests; excludes mypy
```

### Running Tests

Tests are organized into separate root, package/plugin, browser, and external-acceptance lanes. See [docs/TESTING.md](docs/TESTING.md) for their exact scope and prerequisites.

```bash
# Run root tests (unit + integration + e2e + regression)
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

# Opt-in local browser checks; separate from live-provider acceptance
make test-dashboard-browser
make test-mapbox-browser

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

# Run the root quality gate
# Package/plugin/browser lanes are documented separately in docs/TESTING.md
make check
```

## CSV Schema

Standard 21-field output format:

```csv
course,direction_text,bearing_quadrant,bearing_azimuth_deg_from_north,distance_ft,curve_dir,radius_ft,delta_deg,arc_length_ft,chord_bearing,chord_length_ft,along,to,monument_type,monument_status,is_exception,is_meander,is_tie_in,non_tangent,radial_bearing,notes
```

**Example:**
```csv
1,S 33 20' E,S 33 20' E,146.666667,60.00,,,,,,,SW line of Concord Dr,a point in the division line,iron_pin,,false,false,false,false,,
2,S 56 40' W,S 56 40' W,236.666667,125.00,,,,,,,Div. line L46/47 to L50,point corner to Lot 50,stone,,false,false,false,false,,
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
2. **Verification First** - Verified export requires fresh canonical checks, including closure <0.01 ft; advisory results cannot authorize it
3. **Preserve Original Wording** - Keep deed language verbatim in `along` and `to` fields
4. **Deterministic Analysis** - Parsing and numerical analysis are deterministic; model extraction remains source evidence that must be retained and reviewed

## Project Structure

```
metesParser/
├── Makefile                     # Development commands
├── pyproject.toml               # UV workspace root + tool settings
├── packages/                    # Composable packages (uv workspace)
│   ├── mp-models/               # Shared data/evidence/analysis contracts
│   ├── mp-bearing/              # Pure math: azimuth, curves, deltas
│   ├── mp-ocr/                  # LLM boundary: PDF -> text
│   ├── mp-parse/                # Rule-based parsing: text -> calls
│   ├── mp-verify/               # Canonical checks + advisory geometry/analysis
│   ├── mp-export/               # CSV, audit, plot/dashboard rendering
│   └── mp-review/               # Deterministic review CLI + artifact orchestration
├── plugins/metesparser/         # Claude skills, shared contracts, bundled launcher
├── src/metesparser/             # Orchestrator + backward-compat monolith
│   ├── pipeline.py              # Pipeline orchestrator
│   ├── cli.py                   # Command-line interface
│   ├── run_registry.py          # Prompt A/B testing
│   ├── review_packet.py         # Ground truth review packets
│   └── ...                      # Monolith modules (kept in sync with packages)
├── prompts/                     # Prompt YAML files
├── tests/                       # Root unit, integration, regression and e2e tests
│   ├── unit/                    # Unit tests
│   ├── integration/             # Integration tests
│   ├── e2e/                     # End-to-end CLI tests
│   └── regression/              # Bug fix tests
├── scripts/                     # Utility scripts
├── sample_deeds/                # Sample PDFs, ground truth and markdown
├── docs/                        # Documentation
├── AGENTS.md                    # Repository agent guidance
└── CLAUDE.md                    # Symlink to AGENTS.md
```

## Requirements

- Python 3.11+
- OpenAI or Gemini API key for the provider-backed PDF pipeline (the Claude plugin uses native source reading)
- UV package manager (no pip/conda/poetry)

## Environment Variables

Create a `.env` file:

```bash
METESPARSER_LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...  # Required when using OpenAI
GEMINI_API_KEY=...      # Required when using Gemini
METESPARSER_LOG_LEVEL=INFO  # Optional (default: INFO)
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
- **[Plugin catalog](plugins/metesparser/README.md)** - Claude skills and runtime usage
- **[Artifact handoffs](plugins/metesparser/references/artifact-handoffs.md)** - Shared composition and reuse contract
- **[Implementation evidence](docs/implementation/2026-10-28-evidence-review-ledger.md)** - Dated local gates and outstanding native/provider acceptance
- **[docs/API.md](docs/API.md)** - Python API reference
- **[docs/CONTRIBUTING.md](docs/CONTRIBUTING.md)** - Development guidelines
- **[CLAUDE.md](CLAUDE.md)** - AI assistant context and guidance
- **[docs/METES_AND_BOUNDS_REFERENCE.md](docs/METES_AND_BOUNDS_REFERENCE.md)** - Surveying reference guide
- **third-party research** - Public UI observations, product claims, and ideas for the review and map skills
- **[Skill improvement plan](docs/plans/2026-10-28-skill-evidence-and-review-improvements.md)** - Subagent workstreams, contracts, and red-green acceptance tests
- **[docs/bugs.md](docs/bugs.md)** - Known issues tracker
- **[docs/todos.md](docs/todos.md)** - Task tracker

## Support

For issues or questions:
- Check relevant documentation above
- Run `make help` for available commands
- Open an issue on GitHub

---

**Note**: This parser follows strict surveying principles. It will never fabricate missing data and requires traverse closure before marking results as verified.

### Optional online map review

The [render-online-map capability](plugins/metesparser/skills/render-online-map/README.md) renders prepared deed plots and registered map layers in a local Mapbox viewer or requested in-chat MCP preview. A dashboard can delegate an online companion to it after source assembly. See the [configuration, optional dependencies, and loopback preview guide](plugins/metesparser/skills/render-online-map/references/local-viewer.md). Connect requires a runtime public token; map display does not establish survey accuracy or verified-export eligibility. Live provider and native-host acceptance are separate from local checks.

For a Mapbox preview inside Claude, the optional [`mapbox-mcp` handoff](plugins/metesparser/skills/render-online-map/references/mapbox-mcp.md) reuses prepared vectors from intact standalone-map or legacy dashboard stages. It generates exact tool arguments and a local provenance/omission report without contacting Mapbox. A compatible connected MCP tool supplies the interactive panel; registered scans and source review remain in the local evidence/dashboard views.

To try both views, follow the [Mapbox testing guide](docs/CONTRIBUTING.md#manual-mapbox-smoke-test), including a reproducible synthetic fixture, Claude MCP setup, local overlay checks, and automated browser/live-provider commands.
