# AGENTS.md

This file provides guidance to AI coding agents (Claude Code, Codex, etc.) working in this repository.

## Project: Metes & Bounds Deed Parser

MetesParser is a Claude plugin and shared Python engine for source-traceable metes-and-bounds review, plotting and exports. The CLI and composable packages also support automation without a Claude session.

Use deterministic code wherever possible, AI only where needed, and deterministic validation of AI-prepared inputs wherever applicable. Keep source review distinct from computational checks. Follow these guardrails so every contribution stays reliable, auditable, and easy to review.

Versions are declared in each package's `pyproject.toml` (root `metesparser`: 0.6.0; `mp-*`: 1.0.0). Test counts and coverage depend on the selected suite; use the latest [implementation evidence](docs/implementation/2026-10-28-cowork-workflow-ledger.md), not a fixed count in this guide.

## Critical Architecture Principles

### 1. Never Fabricate Data
**Most Important Rule**: If a bearing is incomplete (e.g., "southwesterly" without degrees), leave `bearing_azimuth_deg_from_north` as `None` and set `notes="incomplete bearing - cardinal only"`. Never invent numerical bearings.

### 2. Verification Before Export
Use `verify_closure()` before `export_verified_csv()`. Geometry eligibility requires closure below 0.01 ft, applicable checks passing (explicit `not_applicable` is distinct from `passed`), and no warnings; failed or blocked checks prevent eligibility. The exporter freshly verifies the selected calls and validates the supplied result against them. `source_review_status` remains an explicit, separate assessment; geometry eligibility does not establish source completeness or legal validity.

### 3. Preserve Verbatim Deed Language
Keep original wording in `along` and `to` fields. Example: Keep "Southerly line of Pennbrook Drive" exactly as written in the deed.

### 4. GenAI Transparency & Auditability
Build for transparency by design. All LLM-generated outputs must be traceable and auditable — log prompts, responses, and extraction decisions so users can verify what the AI produced vs. what the parser derived deterministically. Within the composable packages, only `mp-ocr` calls LLMs; downstream packages are deterministic. The compatibility monolith also retains provider clients in `src/metesparser/llm_clients.py`.

## Composable Package Architecture

The codebase is a **uv workspace monorepo** with 8 independently installable packages (the 7 `mp-*` packages under `packages/` plus the root `metesparser` package) following Unix philosophy (each does one thing well). The original monolith in `src/metesparser/` is preserved for backward compatibility.

```
packages/
  mp-models/    → Pydantic schemas, JSONL envelope, units (no workspace deps)
  mp-bearing/   → Pure math: azimuth, curves, deltas (depends: mp-models)
  mp-ocr/       → LLM boundary: PDF → text (depends: mp-models)
  mp-parse/     → Rule-based parsing: text → calls (depends: mp-models, mp-bearing)
  mp-verify/    → Canonical geometry checks (depends: mp-models, mp-bearing)
  mp-export/    → CSV/JSON/audit HTML output (depends: mp-models, mp-verify)
  mp-review/    → Deterministic CLI/adapters (depends: mp-models, mp-parse, mp-verify, mp-export)
src/metesparser/ → Orchestrator + backward-compat monolith
```

These dependency notes list workspace edges; third-party dependencies and optional geographic/browser extras are declared in the package `pyproject.toml` files. In particular, `mp-models` depends on Pydantic and Structlog. `mp-review` provides `metes-review` without an OCR/provider dependency.

### Package → Monolith Module Mapping
| Package | Module(s) | Monolith Equivalent |
|---------|-----------|---------------------|
| `mp-models` | `mp_models.deed_call`, `mp_models.legal_description`, `mp_models.closure`, `mp_models.audit`, `mp_models.envelope`, `mp_models.units`, `mp_models.constants`, `mp_models.base`, `mp_models.logging`, `mp_models.revisions`, `mp_models.corridor`, `mp_models.delivery`, `mp_models.plss` | `models.py` for legacy deed/audit schemas; review contracts stay in `mp_models` |
| `mp-bearing` | `mp_bearing.azimuth`, `mp_bearing.curves`, `mp_bearing.deltas` | `bearing_converter.py` |
| `mp-ocr` | `mp_ocr.extract`, `mp_ocr.clients`, `mp_ocr.cache` | `pdf_processor.py`, `llm_clients.py` |
| `mp-parse` | `mp_parse.calls`, `mp_parse.metadata`, `mp_parse.monuments`, `mp_parse.normalizer`, `mp_parse.numbers` | `call_extractor.py`, `text_parser.py` |
| `mp-verify` | `mp_verify.closure`, `mp_verify.checks`, `mp_verify.confidence` | `closure_checker.py` |
| `mp-export` | `mp_export.csv_writer`, `mp_export.audit_html`, `mp_export.revision_html`, `mp_export.delivery`, `mp_export.raster_picker` | `csv_builder.py`, `audit_reporter.py` for legacy CSV/audit output; new renderers stay in `mp_export` |
| `mp-review` | `mp_review.api`, `mp_review.plot`, `mp_review.dashboard`, `mp_review.source_handoff`, `mp_review.artifact_inspect`, `mp_review.diagnostics`, `mp_review.comparison`, `mp_review.revisions`, `mp_review.revision_view`, `mp_review.delivery`, `mp_review.corridor`, `mp_review.plss`, `mp_review.raster_picker`, `mp_review.cli` | Review API/CLI and corresponding `metesparser` compatibility facades |
| `metesparser` | `metesparser.pipeline` | Orchestrator (new) |

### Composable Skills

`make chat-skill-build` adapts the plugin into one standalone Claude chat Skill with thirteen embedded procedures. Maintain shared capability instructions in `plugins/metesparser/`; keep the chat dispatcher, host setup and download guidance in `plugins/metesparser-chat/`. The builder reuses the same wheels, lock and engine fingerprint, adapts paths at build time, and leaves the plugin unchanged. Validate the extracted archive outside the checkout; distinguish local runtime checks from native Claude chat acceptance.

The Claude plugin is an instruction layer over the shared packages. Its [catalog](plugins/metesparser/README.md#skills) lists thirteen skills: ten capabilities, two workflows, and the `review-deed` compatibility alias. Keep each capability scoped to its own output; workflows select stages and reuse valid artifacts. The plugin is designed to use native Claude document reading, but native Claude/Cowork acceptance remains unrun; `mp-ocr` remains the provider-backed extraction path for the separate Python pipeline.

The review workflow saves exact raw drafts separately from parsed or last-valid geometry, preserves source/document/tract/call identities, and publishes immutable revisions. Structured line and arc edits use shared revision preparation and rendering; only the immediate browser preview is straight-course only. Source-correction records preserve supplied excerpts and fresh calls and must not be described as complete native source acquisition or selection.

Corridor revisions use schema 1.2 to retain the exact centerline and ordered endpoint width/taper/join/cap definitions for replay and delivery. Corridor geometry remains separate from parcel closure and must report unsupported topology or unmet error budgets. PLSS geometry is derived only from an identified supplied reference dataset under the documented supported rectangular rule; metadata extraction or a PLSS recital alone does not establish section corners. The optional raster picker records image pixel controls for raster registration only; it does not establish real-world controls or deed placement. The plugin provides immutable SVG/PDF/DXF/GeoJSON delivery and read-only delivery inspection. See the [revision](plugins/metesparser/references/revisions.md), [corridor](plugins/metesparser/skills/plot-corridor/SKILL.md), [PLSS](plugins/metesparser/skills/plot-plss-reference/SKILL.md), [delivery](plugins/metesparser/skills/export-review-package/SKILL.md), and [raster registration](plugins/metesparser/skills/prepare-parcel-overlay/references/overlay-preparation.md) contracts.

Use the [handoff contract](plugins/metesparser/references/artifact-handoffs.md) for accepted inputs, stopping points, status separation, and invalidation. Keep schemas in `mp_models`, adapters in `mp_review`, numerical logic in the shared parsing/bearing/verification packages, and rendering in `mp_export`. Plotting and overlay preparation must not grant canonical verification status. Dashboard assembly is explicit and placements bind to freshly computed dashboard geometry.

Source acquisition/selection records use schema 1.1 and preserve exact UTF-8 bytes, page/span identities and uncertainties. `validate-source` checks those records; it does not establish source accuracy. `inspect-artifacts` inventories and replays supported artifacts read-only, reporting dependencies and restart guidance without executing a workflow. `diagnose-closure` and `compare-descriptions` retain explicit requests and produce advisory results; diagnoses, scenarios, tentative matches and comparisons must not modify canonical calls, verification or verified-export eligibility. Completed advisory commands return `needs_review` (exit 1), including completed findings; invocation/schema errors return `error` (exit 2). See the shared [source](plugins/metesparser/references/source-preparation.md), [diagnosis](plugins/metesparser/references/closure-diagnostics.md) and [comparison](plugins/metesparser/references/comparison-limits.md) references.

Follow the [skill maintenance guide](docs/CLAUDE_PLUGIN.md#maintain-the-skill-composition) when changing instructions, handoffs, or examples. Link shared references rather than duplicating contracts across skills. Preserve the `CLAUDE.md` symlink to this file.

The `render-online-map` capability owns optional local Mapbox and requested in-chat MCP rendering; the dashboard workflow owns source/bundle assembly and delegates provider rendering. Map-only requests do not require a dashboard. Optional online maps compose these same artifacts: `mp_models.webmap` defines the display contract, `mp_review.webmap` prepares geographic features and warped raster assets, and `mp_export.online_map_html` renders the Mapbox companion. Install the `web-map` extra for raster reprojection. The ordinary offline dashboard stays unchanged. Require explicit CRS, unit, placement and registration evidence; never infer a location from direction words or fit a deed to imagery. Mapbox tokens belong only in the runtime Connect field, never in configuration or generated files. See the [online map reference](plugins/metesparser/skills/render-online-map/references/local-viewer.md) for configuration, local preview and separate live-provider acceptance gates.

The standalone `render-map` command accepts `StandaloneWebMapInput` (prepared plots and map arrays/placements) plus token-free `WebMapRequest`; shared math revalidates plots and stale placements fail. It writes an online viewer and offline evidence fallback without building a dashboard or granting source-review/verification status. The optional `mapbox-mcp` command reuses intact standalone-map or legacy dashboard geographic stages for a vector-only in-chat preview. Keep shared provenance validation in `mp_verify.webmap`, serialization in `mp_export.mapbox_mcp`, and stage I/O in `mp_review.mapbox_mcp`. It must not reproject, simplify, transmit data, or promote verification. The renderer skill handles a requested external preview through an already configured compatible tool; MCP connection credentials stay outside artifacts. See the [MCP reference](plugins/metesparser/skills/render-online-map/references/mapbox-mcp.md).

### Pipeline Orchestrator
`Pipeline.run()` uses the monolith `PDFProcessor` for extraction/parsing, then shared `mp_verify` verification. It returns a `ClosureResult` (or a list for multiple tracts), optionally paired with `AuditContext`; it does not write exports. CSV/audit export is a separate step.

```python
from metesparser import Pipeline
pipe = Pipeline(provider="openai", cache=True, audit=True)
result, audit_ctx = pipe.run(Path("deed.pdf"))
```

### When Modifying Code
1. Modify the package code (e.g., `packages/mp-parse/`)
2. Keep existing duplicated monolith behavior in sync; for shared review features, maintain the corresponding compatibility facade rather than duplicating the implementation
3. Run per-package tests: `uv run pytest packages/mp-parse/tests/ -v --no-cov`
4. Run cross-package import verification: `uv run pytest tests/unit/test_cross_package_imports.py -v`

## Essential Commands

### Makefile (Primary Interface)
```bash
make help          # Show all commands
make dev-setup     # Initial setup (creates .env from .env.example)
make install       # Install full dependency set (all extras + dev)
make lint          # Run ruff (excludes text_parser.py)
make lint-fix      # Auto-fix linting issues
make format        # Run ruff formatter
make format-check  # Check formatter compliance (no changes)
make type          # Run mypy type checks
make test          # Run pytest
make test-fast     # Run pytest with fail-fast (stop on first failure)
make test-cov      # Tests with HTML coverage report
make quality       # Run lint + format checks only
make pre-commit    # Run lint-fix, format, and tests (no type checks)
make check         # Root lint + mutating format + root typing/tests
make ci            # Clean/reinstall, quality checks and root coverage tests
make clean         # Remove .venv, build/dist artifacts and caches
make test-dashboard-browser # Opt-in offline dashboard Chromium/Node checks
make test-mapbox-browser    # Local map adapter/pinned SDK checks; no provider credentials
make test-mapbox-live       # Separate explicit live-provider acceptance gate
make plugin-build           # Build the default Claude plugin ZIP and SHA-256 sidecar
make doctor        # Verify project dependencies and environment
make run-extract   # Quick local PDF extraction
make run-verify    # Quick local CSV verification
```

- `make run-extract PDF_FILE=deed.pdf` executes the pipeline end-to-end; `make run-verify CSV_FILE=calls.csv` applies closure and curve guardrails to produced calls.
- `make test-cov` writes coverage HTML to `htmlcov/index.html`.
- Makefile lint/format target `src/metesparser` and `tests`; typing targets `src/metesparser`. Root Pytest discovery targets `tests`, with coverage for `src/metesparser` and an 80% minimum. Package/plugin tests and changed package/script lint/type checks need explicit commands; `make check` does not cover every workspace file.
- `make check` and `make pre-commit` can change files. Use `make quality` for nonmutating root lint/format checks. `make ci` removes the environment and build outputs through `clean` and does not run the `type` target.
- Local browser/SDK and extracted-archive checks do not establish live Mapbox acceptance, native skill discovery or native document-reading accuracy. Keep these gates separate and report unrun gates explicitly.

### Direct CLI Usage
```bash
# Extract and verify
uv run metesparser extract deed.pdf
uv run metesparser verify calls.csv --area 7500

# Compare prompt versions across runs
uv run metesparser compare-runs
uv run metesparser compare-runs --pdf pennbrook

# Deterministic advisory commands (completed results exit 1)
uv run metes-review validate-source BUNDLE_DIR
uv run metes-review inspect-artifacts BUNDLE_DIR --requested-stage compare-descriptions
uv run metes-review diagnose-closure REQUEST.json --output-dir NEW_DIR
uv run metes-review compare-descriptions REQUEST.json --output-dir NEW_DIR
uv run metes-review revision-template BUNDLE.json --output REVISION.json --revision-id ID
uv run metes-review save-revision BUNDLE.json --revision REVISION.json --output-dir REVISIONS_DIR
uv run metes-review inspect-revision BUNDLE.json --revision-dir REVISIONS_DIR/ID
uv run metes-review render-revision BUNDLE.json --revision-dir REVISIONS_DIR/ID --output-dir NEW_DIR
uv run metes-review analyze-corridor REQUEST.json --output-dir NEW_DIR
uv run metes-review derive-plss REQUEST.json --output-dir NEW_DIR
uv run metes-review export-review BUNDLE.json --revision-dir REVISIONS_DIR/ID --request REQUEST.json --output-dir NEW_DIR
uv run metes-review inspect-delivery BUNDLE.json --revision-dir REVISIONS_DIR/ID --package-dir PACKAGE_DIR
uv run metes-review pick-raster IMAGE --controls CONTROLS.json --output-dir NEW_DIR

# Development
uv run pytest tests/unit/test_bearing_converter.py -v
uv run pytest -k "test_closure" --pdb

# Per-package tests (use --no-cov to avoid root coverage config)
uv run pytest packages/mp-models/tests/ -v --no-cov
uv run pytest packages/mp-bearing/tests/ -v --no-cov

# All per-package tests at once
for pkg in packages/mp-*/tests/; do uv run pytest "$pkg" -v --no-cov; done

# Combined package/plugin checks (avoid duplicate test module names)
uv run pytest packages/mp-*/tests plugins/metesparser/tests --no-cov --import-mode=importlib
```

### UV (REQUIRED - Never use pip/conda/poetry)
```bash
uv venv                    # Create virtual environment
uv sync --all-extras --dev # Install all dependencies
uv add package-name        # Add new dependency
uv run pytest              # Run commands in venv
```

## Data Flow Architecture

### Processing Pipeline
```
PDF → PDFProcessor.process_deed_pdf() → LegalDescription
  ├─ Configured LLM extraction (`OpenAIClient` / `GeminiClient`)  [mp-ocr]
  ├─ Text normalization (normalize_legal_description)              [mp-parse]
  ├─ PLSS metadata (extract_plss_metadata)                        [mp-parse]
  ├─ POC/POB extraction (extract_poc_and_pob)                     [mp-parse]
  ├─ Area statement (extract_area_statement)                      [mp-parse]
  ├─ Call extraction (extract_calls) [rule-based, not AI]         [mp-parse]
  ├─ Azimuth enrichment (enrich_calls_with_azimuths)              [mp-parse]
  ├─ Tie-in marking (mark_tie_in_calls)                           [mp-parse]
  ├─ Basis of bearing (extract_basis_of_bearing)                  [mp-parse]
  ├─ Surveyor certification (extract_surveyor_certification)      [mp-parse]
  ├─ Prior conveyance (extract_prior_conveyance)                  [mp-parse]
  ├─ Deed clauses (extract_deed_clauses)                          [mp-parse]
  ├─ Subdivision reference (extract_subdivision_reference)        [mp-parse]
  ├─ Witness trees (extract_witness_trees)                        [mp-parse]
  └─ Coordinate system + FIPS (extract_coordinate_system)         [mp-parse]

LegalDescription → verify_closure() → ClosureResult               [mp-verify]
  ├─ Traverse closure (sum dx, dy)
  ├─ Canonical checks with explicit applicability and blocked outcomes
  └─ Area calculation (shoelace plus analytic circular-segment corrections)

ClosureResult → export_verified_csv() → CSV + Audit               [mp-export]
  ├─ Freshly validates selected calls/result and geometry eligibility
  ├─ .audit.json sidecar (if audit_context provided)
  └─ .audit.html report (if audit_context provided)
```

### Audit Sidecar (Optional)
When `PDFProcessor.process_deed_pdf(audit=True)`, an `AuditContext` threads through the pipeline:
- **mp-ocr**: Creates context, captures LLM extraction + confidence scoring (7 heuristic signals)
- **mp-parse**: Records source excerpts, transformations, decisions, and per-field confidence
- **mp-verify**: Records verification check results and closure summary
- **mp-export**: Writes `.audit.json` + `.audit.html` alongside verified CSV; self-contained HTML with collapsible sections, confidence color coding

### Key Module Responsibilities

**mp-models** (`packages/mp-models/`) - Pydantic schemas
- `DeedCall`: Single course (bearing, distance, curve data)
- `LegalDescription`: Complete deed with calls list + metadata
- `ClosureResult`: Verification results with misclosure and area
- `AuditContext`: Mutable accumulator for audit trail (NOT frozen — extends `BaseModel` directly)
- `RawTextMessage`, `LegalDescriptionMessage`, `ClosureResultMessage`: JSONL envelope types
- `ConversionFactors`, `DistanceUnit`: Unit conversion constants
- Audit models: `RunMetadata`, `ExtractionRecord`, `CallAudit`, `Transformation`, `Decision`, `CheckResult`, `VerificationAudit`

**mp-bearing** (`packages/mp-bearing/`) - Coordinate math
- Quadrant bearing ↔ azimuth: `parse_quadrant_bearing()`, `quadrant_to_azimuth()`
- Packed DMS conversion: `parse_packed_dms(46.1631)` → 46.2753° decimal
- Delta calculations: `calculate_deltas(azimuth, distance) → (dx, dy)`
- Curve math: `calculate_curve_properties(radius, delta) → {arc, chord, ...}`

**mp-ocr** (`packages/mp-ocr/`) - LLM boundary (the only package that calls AI)
- `PDFProcessor`: Extracts text from deed PDFs via OpenAI/Gemini
- `BaseLLMClient` ABC, `OpenAIClient`, `GeminiClient`: Provider implementations
- `CachedLLMClient`: Disk-cached wrapper for LLM responses

**mp-parse** (`packages/mp-parse/`) - Rule-based parsing (NOT AI)
- `extract_calls()`: Regex-based call extraction from normalized text
- `enrich_calls_with_azimuths()`: Converts quadrant bearings to azimuths
- `classify_monument()`, `classify_monument_status()`: Monument classification
- Metadata extraction: PLSS, POC/POB, area, basis of bearing, surveyor cert, etc.

**mp-verify** (`packages/mp-verify/`) - Canonical checks

- Traverse closure (< 0.01 ft)
- Interior angles sum ((n-2)*180°) where applicable
- Parallelism checks
- Curve consistency (L ≈ R*Δ)
- Boundary topology: straight-segment and circular-arc intersections; incomplete or unsupported geometry blocks a clear outcome
- Area reasonableness (vs stated)
- Double-entry validation when an independent second entry is supplied
- Bearing reversal detection (adjacent straight courses ~180° apart)
- Distance reasonableness (short/long/dominant)

**mp-export** (`packages/mp-export/`) - Output formats
- `export_verified_csv()`, `calls_to_csv()`, `csv_to_calls()`: CSV I/O
- `generate_html()`, `write_report()`: Audit HTML report
- XSS prevention via `html.escape()` on all user content

**run_registry.py** (`src/metesparser/`) - Prompt A/B testing
- `RunManifest`, `PromptVersion`, `RunResults`: Pydantic models for per-run tracking
- `get_prompt_versions()`: Git SHA + SHA-256 content hash per prompt YAML
- CLI: `metesparser compare-runs [--pdf <name>] [--runs-dir <path>]`

**review_packet.py** (`src/metesparser/`) - Ground truth review packets
- `generate_review_html()`: Self-contained HTML review page per deed
- Includes metadata, call table, closure summary, text comparison, and traverse plot (SVG)

## Bearing Convention (Critical for Calculations)

Azimuth = degrees clockwise from North (0-360):
- N 45° E → 45°
- S 45° E → 135° (180 - 45)
- S 45° W → 225° (180 + 45)
- N 45° W → 315° (360 - 45)

DMS parsing: "S 56°40'30\" W" → (S, 56.675, W) → 236.675° azimuth

## Unit Conversions (`mp_models.units` / `models.py` — `ConversionFactors`)
- 1 pole = 1 rod = 1 perch = 16.5 ft
- 1 chain = 66 ft | 1 link = 0.66 ft
- 1 vara = 2.778 ft (Texas) | 1 arpent = 191.8 ft (French colonial)
- 1 toise = 6.395 ft | 1 furlong = 660 ft
- 1 meter = 3.28084 ft | 1 mile = 5,280 ft
- 1 engineer chain = 100 ft | 1 engineer link = 1.0 ft
- 1 acre = 43,560 sq ft

## Key Directories
- `packages/` — 7 composable packages (mp-models, mp-bearing, mp-ocr, mp-parse, mp-verify, mp-export, mp-review)
- `plugins/metesparser/` — capability/workflow skills, shared handoffs, launcher, and plugin documentation
- `plugins/metesparser-chat/` — standalone chat entrypoint templates, setup adapter and host guidance
- `src/metesparser/` — orchestrator (`pipeline.py`) + backward-compat monolith modules
- `scripts/` — standalone utility scripts (extract_sample_deeds.py, generate_ground_truth.py, generate_review_packet.py, backfill_run_registry.py, audit_gt_vs_md.py, parse_pdfs_to_md.sh, test_31_pennbrook_text.py)
- `docs/reference/` — reference PDFs (BLM manual, etc.) — tracked via `!docs/reference/*.pdf`
- `sample_deeds/` — sample PDFs, ground truth JSON files and LlamaParse markdown conversions (co-located)
- `tests/` — tests; fixtures in `tests/fixtures/`
- `prompts/` — LLM prompt YAMLs
- `docs/` — documentation
- `docs/plans/` — implementation plans and acceptance handoffs
- `docs/archive/extraction-output/` — preserved historical extraction outputs; not current verified results
- `output/` — ignored runtime outputs and local experiments; keep durable evidence under `docs/`

## Coding Style & Naming Conventions
- Target Python 3.11+, four-space indentation, snake_case modules/functions/tests, CapWords classes, and typed public APIs.
- Use Ruff for formatting and linting; respect the exclusions in `pyproject.toml`. Never use Black. Keep imports sorted and add concise comments only when geometry rules or guardrails need justification.

## Testing Strategy

### Writing Tests (TDD Approach)
1. Test bearing conversions first (most critical)
2. Test with known parcels (18 Pennbrook parallelogram, 24 Pennbrook, square fixture)
3. Test closure cases where misclosure should be near zero
4. Test incomplete bearing handling (should flag, not fabricate)

### Test File Locations
```bash
tests/unit/test_<module>.py               # Unit tests mirror src/ modules
tests/unit/test_phase*.py                 # Phase-specific feature tests
tests/unit/test_bugs_*_tdd.py             # Bug fix regression tests
tests/unit/test_cross_package_imports.py  # Cross-package import verification
tests/unit/test_pipeline.py              # Pipeline orchestrator tests
tests/integration/test_integration.py     # Full pipeline (known parcels)
tests/e2e/test_cli_end_to_end.py          # CLI end-to-end
tests/conftest.py                         # Custom markers, logging isolation, deed_call_factory
tests/fixtures/sample_deeds.py            # Shared DeedCall fixtures
packages/mp-*/tests/                      # Per-package unit tests
```

### Running Specific Tests
```bash
uv run pytest tests/unit/test_bearing_converter.py::TestQuadrantToAzimuth::test_ne_quadrant -v
uv run pytest tests/unit/test_closure_checker.py --no-cov
uv run pytest packages/mp-parse/tests/ -v --no-cov  # Per-package (needs --no-cov)
```

### Expected Test Outcomes
Required checks must pass. Investigate failures and unexpected warnings or skips before committing; optional browser/provider suites have explicit prerequisites and are not established by a skipped test. Record the exact command, result and scope rather than relying on a fixed expected test count.

### Testing Guidelines
- Run Pytest via `make test`; mock LLM calls to keep suites deterministic. Store sanitized inputs and expected outputs under `tests/fixtures/`.
- Name tests after behaviors (`test_parse_curve_segments`) and review `htmlcov/index.html` after `make test-cov` to confirm coverage.

## Known Issues & Workarounds

### text_parser.py Linting
`src/metesparser/text_parser.py` is currently excluded under `[tool.ruff] exclude`. Preserve that configured scope unless deliberately changing it. Unicode DMS symbols alone do not establish a Ruff parser defect, and a lint exclusion does not establish functional correctness; verify changes with focused parsing tests.

### Boolean Field Validation
**Rule**: Do NOT use `strict=True` on boolean `Field()` declarations in `DeedCall`
**Reason**: Contradicts the `_coerce_bool_field` validator that coerces strings ("true"/"false") to bools

### Cardinal Direction Patterns
**Rule**: Cardinal-only patterns must include `(?:erly|wardly)?` suffixes AND abbreviated forms (`NE|NW|SE|SW`)
**Locations** (all must stay in sync):
- `packages/mp-parse/src/mp_parse/calls.py` (`_CARDINAL_ONLY_PATTERN`)
- `packages/mp-parse/src/mp_parse/metadata.py` (`CARDINAL_ONLY_PATTERN`)
- `src/metesparser/call_extractor.py` (`_CARDINAL_ONLY_PATTERN`)
- `src/metesparser/text_parser.py` (`CARDINAL_ONLY_PATTERN`)
- `scripts/audit_gt_vs_md.py` (`CARDINAL_ONLY_PATTERN`)
**Bug history**: Missing `wardly` suffix caused false negatives (fixed in `d25fcc9`); missing abbreviated cardinals caused call rejection when LLM normalization abbreviated "NORTHWEST" → "NW" (fixed in PR #21)

### LLM Configuration
**Location**: `prompts/*.yaml` files (monolith) and `packages/mp-ocr/src/mp_ocr/prompts/*.yaml` (package)
**Provider Clients**: `OpenAIClient` and `GeminiClient` behind `METESPARSER_LLM_PROVIDER`
**Model**: OpenAI defaults to `gpt-5.2`; Gemini defaults to `gemini-3-flash-preview` with fallback to `gemini-2.5-flash`.
**Architecture**: `BaseLLMClient` ABC in `mp_ocr.clients`; `PDFProcessor` accepts `provider=` or `client=` for DI
**CLI**: `uv run metesparser extract deed.pdf --llm-provider gemini`

### CSV Schema (21 fields - order matters, defined in `mp_export.csv_writer` / `csv_builder.py`)
```csv
course,direction_text,bearing_quadrant,bearing_azimuth_deg_from_north,distance_ft,
curve_dir,radius_ft,delta_deg,arc_length_ft,chord_bearing,chord_length_ft,
along,to,monument_type,monument_status,is_exception,is_meander,is_tie_in,
non_tangent,radial_bearing,notes
```

**Field notes:**
- `monument_type`: Auto-classified from "to" field (20 types)
- `monument_status`: "found", "set", or null
- `is_exception`/`is_meander`/`is_tie_in`/`non_tangent`: Boolean flags (CSV: "true"/"false")
- `radial_bearing`: String for non-tangent curves, empty string if N/A
- `is_indefinite`, `curve_type`, `quality`: Model-only fields (not exported to CSV)
- `precision_ratio`: On `ClosureResult`, not `DeedCall`
- `confidence_score`: On `ClosureResult`, not exported to CSV
- `AuditContext`: Separate sidecar output (`.audit.json`), not part of CSV schema

### Per-Package Testing
Root coverage defaults target `src/metesparser`, so a package-only run can fail the unrelated 80% root coverage threshold. Use `--no-cov` for per-package tests unless explicitly configuring package coverage. Use `--import-mode=importlib` when collecting multiple package/plugin suites together.

## Feature Reference

| # | Feature | Package | Key Function/Class | Notes |
|---|---------|---------|-------------------|-------|
| 1 | Monument type classification | `mp-parse` | `classify_monument()` | Regex-based, specificity-ordered |
| 2 | PLSS metadata | `mp-parse` | `extract_plss_metadata()` | Section/Township/Range/PM/aliquot |
| 3 | Exception/inclusion clauses | `mp-parse` | `split_exception_clauses()` | EXCEPT, LESS AND EXCEPT, ALSO |
| 4 | Exception area verification | `mp-verify` | `verify_closure()` | Net area = main - exception |
| 5 | POB closure detection | `mp-parse` | `is_closure_to_pob()` | Checks last 60 chars of call text |
| 6 | POC vs POB distinction | `mp-parse` | `extract_poc_and_pob()` | COMMENCING at → POC, POINT OF BEGINNING → POB |
| 7 | Packed DMS parsing | `mp-bearing` | `parse_packed_dms()` | 46.1631 → 46°16'31" → 46.2753° |
| 8 | Chord bearing extraction | `mp-parse` | `extract_curve_info()` | "chord of which bears S 34°57' E" |
| 9 | Non-tangent curve detection | `mp-parse` | `extract_curve_info()` | Keywords: non-tangent, radial line bears |
| 10 | Basis of bearing | `mp-parse` | `extract_basis_of_bearing()` | "bearings based on", "referenced to" |
| 11 | Surveyor certification | `mp-parse` | `extract_surveyor_certification()` | "I hereby certify", "Certified by:" |
| 12 | Prior conveyance | `mp-parse` | `extract_prior_conveyance()` | "BEING the same premises", "Deed Book" |
| 13 | Extended distance units | `mp-parse` | `extract_distance()` | varas, arpents, toises, furlongs, meters, miles |
| 14 | Unit-inference heuristics | `mp-parse` | `infer_distance_unit()` | Advisory only — TX→varas, LA→arpents |
| 15 | CSV schema (21 fields) | `mp-export` | `FIELDNAMES`, `export_verified_csv()` | See CSV Schema section above |
| 16 | Area statement extraction | `mp-parse` | `extract_area_statement()` | "CONTAINING X sq ft", "X acres more or less" |
| 17 | Abbreviation expansion | `mp-parse` | `expand_abbreviations()` | IPF, IPS, IRF, IRS, CIP, R/W, N/F, PK |
| 18 | Monument status (found/set) | `mp-parse` | `classify_monument_status()` | found/FD/FND → "found", set/placed → "set" |
| 19 | Bearing reversal detection | `mp-verify` | `check_bearing_reversals()` | Adjacent courses ~180° apart (5° threshold) |
| 20 | Distance reasonableness | `mp-verify` | `check_distance_reasonableness()` | <0.5ft, >10x median, >90% perimeter |
| 21 | Meander/water boundary | `mp-parse` | `detect_meander()` | Warning-only, NOT auto-excluded from closure |
| 22 | Compound/reverse curves | `mp-parse` | `extract_curve_info()` | PCC/PRC keywords → `curve_type` field |
| 23 | Missing curve elements | `mp-bearing` | `calculate_missing_curve_elements()` | Any 2+ → all 5; rejects chord>diameter, zero delta |
| 24 | Tie-in call separation | `mp-parse` | `mark_tie_in_calls()` | POC-to-POB calls filtered from closure |
| 25 | Indefinite call flagging | `mp-parse` | `is_indefinite_call()` | Cardinal-only + physical references; needs `has_bearing=False` |
| 26 | Call quality scoring | `mp-verify` | `score_call_quality()` | high/medium/low based on bearing + monument + flags |
| 27 | Confidence scoring | `mp-verify` | `calculate_confidence_score()` | 0.0–1.0 weighted: closure 30%, checks 20%, bearings 25%, quality 15%, warnings 10% |
| 28 | Enhanced closure summary | `mp-verify` | `get_closure_summary()` | Confidence score, precision ratio (1:N), per-call quality breakdown |
| 29 | Audit sidecar (JSON) | `mp-export` | `export_verified_csv(audit_context=)` | `.audit.json` alongside verified CSV |
| 30 | Audit HTML report | `mp-export` | `generate_html()` | Self-contained HTML, collapsible sections, confidence colors |
| 31 | LLM confidence scoring | `mp-ocr` | `compute_llm_confidence()` | 7 weighted heuristic signals, 0.0–1.0 |
| 32 | Source excerpt capture | `mp-parse` | `extract_calls(audit_context=)` | Verbatim call text preserved per course |
| 33 | Transformation recording | `mp-parse` | `_audit_single_call()` | Step-by-step extraction log per field |
| 34 | Verification audit | `mp-verify` | `verify_closure(audit_context=)` | CheckResults + closure_summary in audit trail |
| 35 | Run registry | `metesparser` | `RunManifest`, `get_prompt_versions()` | Git SHA prompt versioning, per-run JSON, compare-runs CLI |
| 36 | Ground truth review packets | `metesparser` | `generate_review_html()`, `generate_all_packets()` | Self-contained HTML with traverse plot, call table, closure summary |
| 37 | Pipeline orchestrator | `metesparser` | `Pipeline.run()` | Returns verification results and optional audit; export is separate |
| 38 | Cross-package imports | `metesparser` | `test_cross_package_imports.py` | Verifies all package public APIs |

## Environment Setup

Required in `.env`:
```bash
OPENAI_API_KEY=sk-...  # Required if METESPARSER_LLM_PROVIDER=openai
GEMINI_API_KEY=...      # Required if METESPARSER_LLM_PROVIDER=gemini
METESPARSER_LOG_LEVEL=INFO  # Optional, defaults to INFO
```
- Copy `.env.example` to `.env`; never commit secrets. Guard API keys when scripting against the pipeline.
- Document basis of bearing, datum, and source metadata alongside exported CSV so deliverables remain audit-ready.

## Git Workflow
- Never push to `main` - use branches and PRs
- Run `make pre-commit` before committing
- Never commit `.env` or API keys
- For generated deed CSV outputs, only commit exports accepted by the canonical verified-export gate; synthetic test inputs remain separate fixtures

### Git Gotchas
- `.gitignore` ignores PDFs except allowed sample/reference paths. Use `git check-ignore -v PATH` to inspect a specific untracked path; add a scoped exception only for intended repository evidence. Tracked PDFs can be moved with `git mv`.
- Pre-commit hooks may reformat files — check `git status` after every commit for new unstaged changes
- `uv.lock` is tracked (not gitignored) — commit lockfile changes with dependency updates
- Inspect the configured remote before GitHub operations; creating a repository or pushing requires user authorization.
- Preserve unrelated or concurrent work. Do not automatically stash, reset or clean a dirty checkout to merge; inspect the state and use an isolated worktree or obtain authorization for changes to that work.

### Commit & Pull Request Guidelines
- Write conventional commit messages (`feat: add curve support`); types: `feat:`, `fix:`, `docs:`, `chore:`, `test:`, `refactor:`.
- PRs should list workflow stages affected, cite prompt or env updates, link issues, and summarize manual verification (e.g., closure deltas, curve residuals).

## Common Development Patterns

### Adding a New Verification Check
1. Add function to `packages/mp-verify/src/mp_verify/checks.py`
2. Call from `verify_closure()` in `closure.py` and add to warnings list
3. Update `ClosureResult` model in `mp-models` if needed
4. Write test in `packages/mp-verify/tests/` and `tests/unit/test_phase3_verification.py`
5. Keep monolith `closure_checker.py` in sync

### Adding a New DeedCall Field
1. Add field to `DeedCall` in `packages/mp-models/src/mp_models/deed_call.py` (with `Field()` default, no `strict=True` on bools)
2. Add to `FIELDNAMES` in `packages/mp-export/src/mp_export/csv_writer.py` (order matters)
3. Add to `_CSVDeedCallRow` in `csv_writer.py`
4. Wire extraction into `packages/mp-parse/src/mp_parse/calls.py` or `metadata.py`
5. Keep monolith `models.py`, `csv_builder.py`, `call_extractor.py` in sync
6. Update fieldnames count test in `test_phase2_enhanced_parsing.py`
7. Add feature tests in appropriate phase test file

### Adding New Unit Support
1. Add conversion factor to `ConversionFactors` in `packages/mp-models/src/mp_models/units.py`
2. Update `convert_to_feet()` method
3. Add to `distance_unit` Literal in `LegalDescription`
4. Keep monolith `models.py` in sync
5. Test with sample deed using that unit

### Debugging Closure Issues
```python
# Add inside verify_closure() in mp-verify, after the traversal loop
import structlog; log = structlog.get_logger()
for i, call in enumerate(calls):
    log.debug("traverse_step", course=i+1, bearing=call.bearing_quadrant, distance=call.distance_ft)
log.debug("misclosure", dx=f"{misclosure_x:.4f}", dy=f"{misclosure_y:.4f}", total=f"{misclosure:.4f}")
```
