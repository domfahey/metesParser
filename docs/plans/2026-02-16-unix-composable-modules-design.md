# Unix Composable Modules Design

**Date**: 2026-02-16
**Status**: Approved
**Version**: 1.0.0 (clean break from v0.4.0)

## Motivation

Refactor metesParser into composable modules following Unix philosophy:

- **CLI composability**: Pipe commands together (`mp-ocr deed.pdf | mp-parse | mp-verify | mp-export`)
- **Library reuse**: Import individual packages without pulling in the whole system
- **Architectural clarity**: Each module has one job with clean boundaries

## Architecture Overview

7 independently installable packages in a uv workspace monorepo. JSONL flows between pipeline stages via stdin/stdout. Logs and human summaries go to stderr only.

```
mp-models     Zero internal deps. Pydantic schemas + JSONL envelope shared by all packages.
mp-bearing    Pure math. Quadrant/azimuth conversion, curves, deltas.
mp-ocr        The AI boundary. PDF -> raw legal text via LLM.
mp-parse      Rule-based parsing. Text -> structured calls + metadata.
mp-verify     Geometric verification. 8 checks, closure, confidence scoring.
mp-export     Format conversion. JSONL -> CSV / JSON / audit HTML.
metesparser   Orchestrator. Chains all stages, provides `mp` convenience command.
```

### Dependency Tree

```
mp-models (zero internal deps -- just pydantic + structlog)
  |-- mp-bearing (pure math, depends only on mp-models)
  |-- mp-ocr (+ openai, google-genai -- the ONLY package with LLM SDKs)
  |-- mp-parse (+ mp-bearing for azimuth enrichment)
  |-- mp-verify (+ mp-bearing for delta calculations)
  |-- mp-export (depends only on mp-models)
  +-- metesparser (depends on all above + mp-ocr)
```

Key win: 5 of 7 packages have zero LLM dependencies.

## JSONL Interchange Format

Every pipeline tool reads JSONL from stdin and writes JSONL to stdout. Each line is a self-describing JSON object with a `type` discriminator field.

### Message Types (Discriminated Union)

Each `type` value maps to a concrete Pydantic model in `mp-models`. The JSONL line is the model's `.model_dump_json()` output.

| Type | Emitted By | Consumed By | Description |
|------|-----------|-------------|-------------|
| `raw_text` | mp-ocr | mp-parse | Raw legal text extracted from PDF via LLM |
| `legal_description` | mp-parse | mp-verify | Structured calls + metadata |
| `closure_result` | mp-verify | mp-export | Verification results with closure data |

```python
# mp_models/envelope.py
from typing import Union
from pydantic import Discriminator, Tag
from typing import Annotated

MessageType = Annotated[
    Union[
        Annotated[RawTextMessage, Tag("raw_text")],
        Annotated[LegalDescriptionMessage, Tag("legal_description")],
        Annotated[ClosureResultMessage, Tag("closure_result")],
    ],
    Discriminator("type"),
]
```

### Example JSONL Stream

```jsonl
{"type": "raw_text", "source": "deed.pdf", "text": "BEGINNING at...", "llm_provider": "openai", "llm_model": "gpt-5.2", "extracted_at": "2026-02-16T14:30:00Z"}
{"type": "legal_description", "source": "deed.pdf", "calls": [...], "plss": {...}, "pob": "...", "area_statement": "..."}
{"type": "closure_result", "source": "deed.pdf", "is_verified": true, "misclosure_ft": 0.003, "confidence": 0.94, "checks": [...], "calls": [...]}
```

### Conventions

- `type` field is always first -- enables `jq 'select(.type == "closure_result")'` filtering
- `source` field traces lineage back to the original PDF
- Each stage **passes through** fields it doesn't understand (envelope pattern)
- Errors/logs go to stderr as structured log lines (structlog JSON), never stdout
- Exit codes: 0 = success, 1 = domain failure, 2 = usage error, 3 = infrastructure error

## Monorepo Structure

```
metesParser/
|-- packages/
|   |-- mp-models/
|   |   |-- pyproject.toml
|   |   |-- src/mp_models/
|   |   |   |-- __init__.py          # Re-exports all public models
|   |   |   |-- base.py              # _Model base class, ConfigDict conventions
|   |   |   |-- deed_call.py         # DeedCall, MonumentType, MonumentStatus, CurveType, CurveDirection
|   |   |   |-- legal_description.py # LegalDescription, DeedClause, SubdivisionReference
|   |   |   |-- closure.py           # ClosureResult, CheckResult, Point
|   |   |   |-- audit.py             # AuditContext, CallAudit, Transformation, Decision, ExtractionRecord, etc.
|   |   |   |-- constants.py         # PERMANENT_MONUMENTS, PRIOR_CONVEYANCE_SIGNALS, ConversionFactors
|   |   |   |-- envelope.py          # JSONL message types, read_jsonl/write_jsonl, discriminated union
|   |   |   |-- logging.py           # configure_logging(), get_log_format() -- shared log config
|   |   |   +-- units.py             # DistanceUnit TypeAlias, unit conversion helpers
|   |   +-- tests/
|   |
|   |-- mp-bearing/
|   |   |-- pyproject.toml
|   |   |-- src/mp_bearing/
|   |   |   |-- __init__.py
|   |   |   |-- azimuth.py           # quadrant<->azimuth, packed DMS
|   |   |   |-- curves.py            # curve properties, missing element calc
|   |   |   |-- deltas.py            # dx/dy calculation
|   |   |   +-- cli.py               # mp-bearing azimuth/unpack-dms/curve/deltas
|   |   +-- tests/
|   |
|   |-- mp-ocr/
|   |   |-- pyproject.toml
|   |   |-- src/mp_ocr/
|   |   |   |-- __init__.py
|   |   |   |-- extract.py           # PDF -> raw legal text via LLM
|   |   |   |-- clients.py           # OpenAIClient, GeminiClient, BaseLLMClient protocol
|   |   |   |-- cache.py             # file-based LLM response cache (CachedLLMClient)
|   |   |   +-- prompts/             # 4 YAML prompt templates (moved from src/metesparser/prompts/)
|   |   +-- tests/
|   |
|   |-- mp-parse/
|   |   |-- pyproject.toml
|   |   |-- src/mp_parse/
|   |   |   |-- __init__.py
|   |   |   |-- calls.py             # CallExtractor: regex-based call splitting + field extraction
|   |   |   |-- metadata.py          # PLSS, POC/POB, area, basis of bearing, surveyor cert, etc.
|   |   |   |-- monuments.py         # MonumentClassifier, classify_monument_status()
|   |   |   |-- normalizer.py        # text normalization, abbreviation expansion, OCR cleanup
|   |   |   |-- numbers.py           # parse_comma_number(), _COMMA_NUMBER regex (shared utility)
|   |   |   +-- cli.py               # mp-parse: reads raw_text JSONL, writes legal_description JSONL
|   |   +-- tests/
|   |
|   |-- mp-verify/
|   |   |-- pyproject.toml
|   |   |-- src/mp_verify/
|   |   |   |-- __init__.py
|   |   |   |-- closure.py           # traverse closure, misclosure calc (shoelace area)
|   |   |   |-- checks.py            # 8 verification checks (angles, curves, reversals, etc.)
|   |   |   |-- confidence.py        # confidence scoring, call quality scoring
|   |   |   +-- cli.py               # mp-verify: reads legal_description JSONL, writes closure_result JSONL
|   |   +-- tests/
|   |
|   |-- mp-export/
|   |   |-- pyproject.toml
|   |   |-- src/mp_export/
|   |   |   |-- __init__.py
|   |   |   |-- csv_writer.py        # 21-field CSV schema (preserves existing schema exactly)
|   |   |   |-- json_writer.py       # structured JSON output
|   |   |   |-- audit_html.py        # self-contained HTML audit report (from audit_reporter.py)
|   |   |   +-- cli.py               # mp-export: reads closure_result JSONL, writes CSV/JSON/HTML
|   |   +-- tests/
|   |
|   +-- metesparser/
|       |-- pyproject.toml
|       |-- src/metesparser/
|       |   |-- __init__.py
|       |   |-- pipeline.py          # chains all stages programmatically
|       |   |-- run_registry.py      # RunManifest, PromptVersion, compare-runs (moved from current)
|       |   |-- review_packet.py     # ReviewPacket generator (moved from current)
|       |   +-- cli.py               # mp deed.pdf -o deed.csv (orchestrator + compare-runs + review)
|       +-- tests/
|
|-- pyproject.toml                   # workspace root (uv workspace config)
|-- Makefile
|-- CLAUDE.md
+-- docs/plans/
```

### Where Current Modules Land

| Current Module (src/metesparser/) | Target Package | Notes |
|----------------------------------|----------------|-------|
| `models.py` (687 lines) | **mp-models** | Split across 7 files (see mp-models section) |
| `bearing_converter.py` (521 lines) | **mp-bearing** | Split into azimuth.py, curves.py, deltas.py |
| `text_parser.py` (959 lines) | **mp-parse** | Split into normalizer.py, metadata.py, numbers.py |
| `call_extractor.py` (907 lines) | **mp-parse** | Split into calls.py, monuments.py |
| `pdf_processor.py` (461 lines) | **mp-ocr** | Becomes extract.py |
| `llm_clients.py` (223 lines) | **mp-ocr** | Becomes clients.py |
| `llm_cache.py` (102 lines) | **mp-ocr** | Becomes cache.py |
| `closure_checker.py` (804 lines) | **mp-verify** | Split into closure.py, checks.py, confidence.py |
| `csv_builder.py` (317 lines) | **mp-export** | Becomes csv_writer.py |
| `audit_reporter.py` (298 lines) | **mp-export** | Becomes audit_html.py |
| `run_registry.py` (202 lines) | **metesparser** | Orchestrator-level concern (prompt A/B testing) |
| `review_packet.py` (507 lines) | **metesparser** | Orchestrator-level concern (professional audit) |
| `logging_config.py` (169 lines) | **mp-models** | Shared across all packages as mp_models.logging |
| `cli.py` (286 lines) | **metesparser** | Rebuilt as orchestrator CLI |

### Shared Utilities Migration

Two utilities in `text_parser.py` are imported by `call_extractor.py`:

| Utility | Current Location | Target | Used By |
|---------|-----------------|--------|---------|
| `_COMMA_NUMBER` regex | text_parser.py:18 | `mp_parse.numbers` | call_extractor (11 regex patterns) |
| `parse_comma_number()` | text_parser.py:42 | `mp_parse.numbers` | call_extractor (9 call sites) |

Both move into `mp_parse.numbers` since both consumers land in mp-parse. No cross-package dependency introduced.

## Package Designs

### mp-models (Foundation)

Zero domain logic -- just schemas, constants, serialization, and shared logging config.

```python
# Public API
from mp_models import DeedCall, LegalDescription, ClosureResult, AuditContext, Point
from mp_models import CheckResult, CallAudit, RunMetadata, ConversionFactors
from mp_models import DeedClause, SubdivisionReference
from mp_models import PERMANENT_MONUMENTS, PRIOR_CONVEYANCE_SIGNALS
from mp_models.envelope import read_jsonl, write_jsonl, RawTextMessage, LegalDescriptionMessage, ClosureResultMessage
from mp_models.logging import configure_logging, get_log_format

def read_jsonl(stream: TextIO) -> Iterator[MessageType]:
    """Read JSONL from stdin, yield typed message objects."""

def write_jsonl(stream: TextIO, message: MessageType) -> None:
    """Write one JSONL line to stdout."""
```

No CLI entry point. Pure library.

Dependencies: `pydantic>=2.10.0`, `structlog>=24.4.0`

### mp-bearing (Math Utilities)

Stateless math. No I/O beyond stdin/stdout.

```python
# Public API
from mp_bearing import quadrant_to_azimuth, azimuth_to_quadrant
from mp_bearing import parse_packed_dms, parse_quadrant_bearing
from mp_bearing import calculate_deltas, calculate_curve_properties
from mp_bearing import calculate_missing_curve_elements
```

CLI subcommands: `azimuth`, `unpack-dms`, `curve`, `deltas`. Each reads JSONL, enriches with computed fields, writes JSONL.

```bash
echo '{"type":"bearing","quadrant":"N 45d30m15s E"}' | mp-bearing azimuth
# -> {"type":"bearing","quadrant":"N 45d30m15s E","azimuth_deg":45.504167}

echo '{"type":"curve","radius":100,"delta_deg":30}' | mp-bearing curve
# -> {"type":"curve","radius":100,"delta_deg":30,"arc_length":52.36,"chord_length":51.76,...}
```

Dependencies: `mp-models>=1.0.0`

### mp-ocr (AI Boundary)

The only package with LLM SDK dependencies. Contains LLM clients, response caching, and prompt templates.

```python
# Public API
from mp_ocr import extract_legal_text, OpenAIClient, GeminiClient
from mp_ocr import BaseLLMClient, CachedLLMClient
```

```bash
mp-ocr deed.pdf > raw.jsonl
mp-ocr deed.pdf --provider gemini > raw.jsonl
mp-ocr deed1.pdf deed2.pdf deed3.pdf > raw.jsonl  # batch mode
mp-ocr deed.pdf --no-cache > raw.jsonl
```

Output:
```jsonl
{"type": "raw_text", "source": "deed.pdf", "text": "BEGINNING at an iron pin...", "llm_provider": "openai", "llm_model": "gpt-5.2", "confidence": 0.87, "extracted_at": "2026-02-16T14:30:00Z", "cache_hit": false}
```

Stdin alternative -- skip OCR entirely if you have pre-extracted text:
```bash
echo '{"type": "raw_text", "source": "manual", "text": "BEGINNING at..."}' | mp-parse
```

Dependencies: `mp-models>=1.0.0`, `openai>=2.3.0`, `pypdf>=6.1.1`, `pyyaml>=6.0.2`
Optional: `google-genai>=0.3.0` (for Gemini provider)

### mp-parse (Rule-Based Parsing)

Text in, structured calls + metadata out. The workhorse. Contains the current text_parser.py (959 lines) and call_extractor.py (907 lines), split into focused modules.

Internal split:
- `calls.py` -- CallExtractor regex patterns, call splitting, field extraction
- `metadata.py` -- PLSS, POC/POB, area statement, basis of bearing, surveyor cert, prior conveyance, deed clauses, subdivision reference, witness trees, coordinate system
- `monuments.py` -- MonumentClassifier (20 types), classify_monument_status()
- `normalizer.py` -- text normalization, abbreviation expansion, OCR cleanup, DMS symbol standardization, line merging
- `numbers.py` -- `parse_comma_number()`, `_COMMA_NUMBER` regex (shared between calls.py and normalizer.py)

```python
# Public API
from mp_parse import extract_calls, extract_metadata
from mp_parse import normalize_text, expand_abbreviations
from mp_parse import MonumentClassifier
```

```bash
mp-ocr deed.pdf | mp-parse > parsed.jsonl
mp-parse --input legal_text.txt > parsed.jsonl  # from file
```

Output:
```jsonl
{"type": "legal_description", "source": "deed.pdf", "calls": [{"course": 1, "direction_text": "North 45 degrees 30 minutes East", ...}], "plss": {"section": 12, "township": "3N", "range": "2W"}, "pob": "an iron pin in the south line of Elm Street", "area_statement": "containing 0.25 acres"}
```

Passes through upstream fields (`llm_provider`, `llm_model`, etc.) it doesn't use.

Dependencies: `mp-models>=1.0.0`, `mp-bearing>=1.0.0`

### mp-verify (Geometric Verification)

8 checks, confidence scoring, closure calculation.

```python
# Public API
from mp_verify import verify_closure, score_confidence, score_call_quality
from mp_verify import ClosureChecker
```

```bash
mp-ocr deed.pdf | mp-parse | mp-verify > verified.jsonl
mp-ocr deed.pdf | mp-parse | mp-verify --stated-area 7500 > verified.jsonl
mp-ocr deed.pdf | mp-parse | mp-verify --strict  # exit 1 if any check fails
```

Output:
```jsonl
{"type": "closure_result", "source": "deed.pdf", "is_verified": true, "misclosure_ft": 0.003, "precision_ratio": "1:50000", "confidence": 0.94, "area_sq_ft": 7503.2, "checks": [{"name": "traverse_closure", "passed": true, "detail": "misclosure 0.003 ft"}, ...], "calls": [...], "warnings": []}
```

Dependencies: `mp-models>=1.0.0`, `mp-bearing>=1.0.0`

### mp-export (Format Conversion)

JSONL in, human-readable formats out.

```python
# Public API
from mp_export import to_csv, to_json, to_audit_html
from mp_export import CSVWriter, AuditHTMLWriter
```

```bash
... | mp-export --format csv > deed.csv
... | mp-export --format csv -o deed.csv     # file output
... | mp-export --format json > deed.json
... | mp-export --format audit-html -o deed.audit.html
... | mp-export --format csv --format audit-html -o deed  # multiple formats
```

CSV output preserves the existing 21-field schema exactly.

Dependencies: `mp-models>=1.0.0`

### metesparser (Orchestrator)

The "porcelain" command. Like `git` wrapping plumbing. Also houses cross-cutting concerns: run registry (prompt A/B testing) and review packet generation.

```python
# Public API
from metesparser import process_deed, Pipeline

class Pipeline:
    def __init__(self, provider: str = "openai", cache: bool = True, audit: bool = False): ...
    def run(self, pdf_path: Path) -> ClosureResult: ...
    def run_from_text(self, text: str) -> ClosureResult: ...
```

```bash
mp deed.pdf -o deed.csv                     # full pipeline
mp deed.pdf -o deed.csv --audit             # with audit sidecar
mp deed1.pdf deed2.pdf -o output_dir/       # batch
mp deed.pdf --provider gemini -o deed.csv
mp compare-runs --pdf pennbrook             # prompt A/B testing
```

Under the hood, `mp deed.pdf -o deed.csv` is equivalent to:
```bash
mp-ocr deed.pdf | mp-parse | mp-verify | mp-export --format csv -o deed.csv
```

Dependencies: all 6 other packages + `python-dotenv>=1.0.0`

## Audit Trail Design

In the composable system, audit data accumulates in the JSONL stream itself -- no mutable accumulator needed.

Each stage optionally adds an `audit` field when invoked with `--audit`:

```jsonl
// mp-ocr output (--audit)
{"type": "raw_text", ..., "audit": {"stage": "ocr", "llm_confidence": 0.87, "prompt_hash": "abc123"}}

// mp-parse output (nests upstream audit)
{"type": "legal_description", ..., "audit": {"stage": "parse", "call_audits": [...], "upstream": {"stage": "ocr", "llm_confidence": 0.87}}}

// mp-verify output (nests full chain)
{"type": "closure_result", ..., "audit": {"stage": "verify", "check_results": [...], "upstream": {"stage": "parse", "upstream": {"stage": "ocr", ...}}}}
```

Each stage nests upstream audit under `audit.upstream`, creating a 3-level chain (ocr -> parse -> verify). `mp-export --format audit-html` unrolls this chain into the full HTML report.

Without `--audit`: no `audit` field emitted, zero overhead.

**Migration from current AuditContext**: The current `AuditContext` is a mutable accumulator threaded through the pipeline via optional parameter. In v1.0, this becomes the nested JSONL pattern above. The `AuditContext` Pydantic model is retained in mp-models for the orchestrator's programmatic API (`Pipeline.run(audit=True)`), which collects the same data without requiring JSONL serialization.

## CLI Conventions

### Universal Flags (all mp-* tools)

```
--audit              Enable audit trail in output
--log-level LEVEL    DEBUG/INFO/WARNING/ERROR (default: WARNING)
--log-format FORMAT  console/json (default: console)
--input FILE         Read from file instead of stdin
--help               Usage info
```

### Exit Codes

```
0  Success
1  Domain failure (verification failed, parsing error)
2  Usage error (bad args, missing input)
3  Infrastructure error (LLM timeout, file not found)
```

### Pipeline Hygiene

- Errors/logs to stderr (structlog JSON), never stdout
- Handle SIGPIPE gracefully (`signal.signal(signal.SIGPIPE, signal.SIG_DFL)`)
- Human summaries to stderr so piping stays clean
- Each CLI wraps its main in a try/except that maps exceptions to exit codes

### jq Interop Examples

```bash
mp-ocr deed.pdf | mp-parse | jq '.calls[]'                              # extract calls
mp-ocr *.pdf | mp-parse | mp-verify | jq 'select(.is_verified == true)'  # filter verified
mp-ocr deed.pdf | mp-parse | mp-verify | jq '{source, confidence}'       # extract fields
mp-ocr deed.pdf | mp-parse | jq '.calls | length'                        # count courses
```

## Installation Matrix

```bash
# Full system (all 7 packages)
uv add metesparser

# Just bearing math (for a GIS project)
uv add mp-bearing
# -> mp-bearing + mp-models (2 packages, no LLM SDKs)

# Parse + verify without LLM (bring your own text)
uv add mp-parse mp-verify
# -> mp-parse + mp-verify + mp-bearing + mp-models (4 packages, no LLM SDKs)

# Just export (consume JSONL from another tool)
uv add mp-export
# -> mp-export + mp-models (2 packages)

# OCR only (extract text, pipe to your own parser)
uv add mp-ocr
# -> mp-ocr + mp-models + openai + pypdf
```

## Workspace Configuration

Root `pyproject.toml`:
```toml
[project]
name = "metesparser-workspace"
version = "1.0.0"
requires-python = ">=3.11"

[tool.uv.workspace]
members = ["packages/*"]

[tool.pytest.ini_options]
testpaths = ["packages/*/tests"]
addopts = ["-v", "--strict-markers"]

[tool.ruff]
src = ["packages/*/src"]
line-length = 100
target-version = "py311"

[tool.mypy]
python_version = "3.11"
strict = true
```

Per-package `pyproject.toml` example:
```toml
# packages/mp-bearing/pyproject.toml
[project]
name = "mp-bearing"
version = "1.0.0"
requires-python = ">=3.11"
dependencies = ["mp-models>=1.0.0"]

[project.scripts]
mp-bearing = "mp_bearing.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

## Test Migration Strategy

Current state: 50 test files, ~885 tests, ~93% coverage, phase-organized.

### Approach

Tests migrate with their module. Phase-organized test files split by which package the tested functionality lands in.

| Current Test File | Target Package | Notes |
|-------------------|---------------|-------|
| `test_bearing_converter.py` | mp-bearing/tests/ | Direct move |
| `test_phase1_foundation.py` | Split: mp-models + mp-parse | DeedCall tests -> mp-models; monument tests -> mp-parse |
| `test_phase2_enhanced_parsing.py` | Split: mp-export + mp-parse | CSV schema tests -> mp-export; text parsing -> mp-parse |
| `test_phase3_verification.py` | mp-verify/tests/ | Direct move |
| `test_phase4_geometric.py` | mp-bearing/tests/ + mp-verify/tests/ | Curve math -> mp-bearing; closure -> mp-verify |
| `test_phase5_*.py` | Split by feature | Production features span multiple packages |
| `test_phase6_audit.py` | Split: mp-models + mp-export | Audit models -> mp-models; HTML report -> mp-export |
| `test_bugs_*_tdd.py` | Package where fix lives | Bug fixes follow the module they fixed |
| `tests/integration/` | metesparser/tests/ | Full pipeline tests stay with orchestrator |
| `tests/e2e/` | metesparser/tests/ | CLI e2e tests stay with orchestrator |
| `tests/fixtures/sample_deeds.py` | metesparser/tests/fixtures/ | Shared fixtures stay with orchestrator; packages needing them use `conftest.py` with local copies of relevant fixtures |

### Shared Test Fixtures

`deed_call_factory()` and sample deed texts (PENNBROOK_18, SQUARE_100FT, etc.) are used across multiple test files. Strategy:

1. `mp-models` provides `deed_call_factory()` as a test utility (`mp_models.testing`)
2. Sample legal texts stay in the orchestrator's test fixtures
3. Each package's tests are self-contained with package-specific fixtures
4. Integration/e2e tests that exercise the full pipeline remain in the orchestrator

## Versioning

All 7 packages share the same version number, bumped together (lockstep). Starting at 1.0.0 (clean break from v0.4.0).

## Decision Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Interchange format | JSONL | Streamable, jq-friendly, one object per line |
| Message typing | Pydantic discriminated union | Type-safe deserialization, IDE autocomplete, validation |
| Package count | 7 | One per pipeline stage + shared models + orchestrator |
| Packaging model | uv workspace monorepo | Independently installable, single repo to manage |
| Backward compat | Clean break | v1.0.0 opportunity, redesign CLI from scratch |
| Audit mechanism | Nested in JSONL stream | No mutable accumulator needed for CLI piping; AuditContext retained for programmatic API |
| LLM isolation | mp-ocr only | 5/7 packages have zero LLM dependencies |
| Naming | mp-* CLI, mp_* Python imports | Short CLI names, standard Python underscore convention |
| Versioning | Lockstep across all packages | Simple compatibility, bumped together |
| Logging | mp-models owns configure_logging() | Shared across all packages, avoids duplication |
| run_registry | metesparser orchestrator | Cross-cutting concern (prompt A/B testing), not a pipeline stage |
| review_packet | metesparser orchestrator | Professional audit output, orchestrator-level feature |
| Shared number parsing | mp_parse.numbers | Both consumers (calls.py, normalizer.py) are in mp-parse |
| Test fixtures | mp_models.testing + per-package | deed_call_factory shared; sample texts stay with orchestrator |
