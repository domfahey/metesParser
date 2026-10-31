# Developer Reference

Lookup material for contributors and coding agents. Rules and guardrails live in [AGENTS.md](../AGENTS.md); architecture, data flow and package details live in [ARCHITECTURE.md](ARCHITECTURE.md).

## CLI Commands

### `metesparser` (provider-backed pipeline)
```bash
uv run metesparser extract deed.pdf [--llm-provider gemini]
uv run metesparser verify calls.csv --area 7500
uv run metesparser compare-runs [--pdf pennbrook] [--runs-dir PATH]
```

### `metes-review` (deterministic; no OCR/provider dependency)
Run `uv run metes-review <command> --help` for arguments.

| Group | Commands |
|-------|----------|
| Advisory analysis (completed results exit 1 `needs_review`) | `validate-source`, `inspect-artifacts`, `diagnose-closure`, `compare-descriptions`, `analyze-corridor`, `derive-plss`, `analyze-relative` |
| Revisions (no verification) | `revision-template`, `save-revision`, `inspect-revision` |
| Revision views and delivery | `render-revision`, `export-review`, `inspect-delivery` |
| Review and verification | `review`, `verify` |
| Plotting and composition | `plot`, `compose-map`, `compose-dashboard`, `dashboard` |
| Online maps | `render-map`, `serve-map`, `mapbox-mcp` |
| Overlays and rasters | `import-overlay`, `register-raster`, `pick-raster`, `fetch-parcel` |
| Corpus | `corpus` |

Common invocations:
```bash
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
```

## Makefile Targets
```bash
make help          # Show all commands
make dev-setup     # Initial setup (creates .env from .env.example)
make install       # Install full dependency set (all extras + dev)
make lint          # Run ruff
make lint-fix      # Auto-fix linting issues
make format        # Run ruff formatter
make format-check  # Check formatter compliance (no changes)
make type          # Run mypy type checks
make test          # Run pytest
make test-fast     # Run pytest with fail-fast
make test-cov      # Tests with HTML coverage report (htmlcov/index.html)
make quality       # Lint + format checks only (nonmutating)
make pre-commit    # lint-fix, format, tests (no type checks; mutating)
make check         # Root lint + mutating format + root typing/tests
make ci            # clean/reinstall, quality checks, root coverage tests (no type)
make clean         # Remove .venv, build/dist artifacts and caches
make test-dashboard-browser # Opt-in offline dashboard Chromium/Node checks
make test-mapbox-browser    # Local map adapter/pinned SDK checks; no provider credentials
make test-mapbox-live       # Separate explicit live-provider acceptance gate
make plugin-build           # Build the Claude plugin ZIP and SHA-256 sidecar
make chat-skill-build       # Build the standalone Claude chat Skill ZIP and SHA-256 sidecar
make doctor        # Verify project dependencies and environment
make run-extract PDF_FILE=deed.pdf   # End-to-end pipeline
make run-verify CSV_FILE=calls.csv   # Closure and curve guardrails on produced calls
```

## Test File Locations
```bash
tests/unit/test_<module>.py               # Unit tests mirror src/ modules
tests/unit/test_phase*.py                 # Phase-specific feature tests
tests/unit/test_bugs_*_tdd.py             # Bug fix regression tests
tests/unit/test_cross_package_imports.py  # Cross-package import verification
tests/unit/test_pipeline.py               # Pipeline orchestrator tests
tests/integration/test_integration.py     # Full pipeline (known parcels)
tests/e2e/test_cli_end_to_end.py          # CLI end-to-end
tests/conftest.py                         # Custom markers, logging isolation, deed_call_factory
tests/fixtures/sample_deeds.py            # Shared DeedCall fixtures
packages/mp-*/tests/                      # Per-package unit tests
plugins/metesparser/tests/                # Plugin runtime/packaging tests
```

See [TESTING.md](TESTING.md) for suites, markers and acceptance gates.

## CSV Schema

22 fields; order matters. Defined in `mp_export.csv_writer` (`FIELDNAMES`) and monolith `csv_builder.py`. `curve_type` was appended last, so the first 21 columns keep their historical order; import also accepts a legacy 21-field CSV (`curve_type` then reads as null) via `LEGACY_FIELDNAMES`.

```csv
course,direction_text,bearing_quadrant,bearing_azimuth_deg_from_north,distance_ft,
curve_dir,radius_ft,delta_deg,arc_length_ft,chord_bearing,chord_length_ft,
along,to,monument_type,monument_status,is_exception,is_meander,is_tie_in,
non_tangent,radial_bearing,notes,curve_type
```

- `distance_ft`: blank only for a spiral stated without an arc, chord or course length (`DeedCall.distance_ft=None`, length not determined; verification treats the course as unpositioned). CSV import reads a blank distance back only when `curve_type` is `spiral` and no arc or chord length is stated; any other blank distance is rejected
- `monument_type`: auto-classified from the `to` field (20 types)
- `monument_status`: `"found"`, `"set"`, or null
- `is_exception` / `is_meander` / `is_tie_in` / `non_tangent`: booleans (CSV `"true"`/`"false"`)
- `radial_bearing`: string for non-tangent curves, empty string if N/A
- `curve_type`: `simple`, `compound`, `reverse`, `spiral`, or empty; exported so a spiral is never read back as a circular arc
- `is_indefinite`, `quality`: model-only fields, not exported
- Import: strict (default) raises on any invalid row; non-strict import records each rejected row as `(row_number, error)` in a caller-supplied `rejected_rows` list and raises when none is supplied, so a course is never dropped silently
- `precision_ratio`, `confidence_score`: on `ClosureResult`, not `DeedCall`; not exported
- `AuditContext`: separate `.audit.json` sidecar, not part of the CSV

## Unit Conversions

`ConversionFactors` in `mp_models.units` (monolith `models.py`):

| Unit | Feet |
|------|------|
| pole = rod = perch | 16.5 |
| chain / link | 66 / 0.66 |
| engineer chain / link | 100 / 1.0 |
| vara (Texas) | 2.778 |
| arpent (French colonial) | 191.8 |
| toise | 6.395 |
| furlong | 660 |
| meter | 3.28084 |
| mile | 5,280 |
| acre | 43,560 sq ft |

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
| 15 | CSV schema (22 fields) | `mp-export` | `FIELDNAMES`, `export_verified_csv()` | See CSV Schema above |
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

## Debugging Closure Issues
```python
# Add inside verify_closure() in mp-verify, after the traversal loop
import structlog; log = structlog.get_logger()
for i, call in enumerate(calls):
    log.debug("traverse_step", course=i+1, bearing=call.bearing_quadrant, distance=call.distance_ft)
log.debug("misclosure", dx=f"{misclosure_x:.4f}", dy=f"{misclosure_y:.4f}", total=f"{misclosure:.4f}")
```
