# Repository Guidelines

## Project Structure & Commands
- `src/metesparser/` holds the pipeline (PDF extraction, call parsing, bearing math, closure, CSV); mirrors live in `tests/`, prompts in `prompts/`, docs in `docs/`, fixtures in `tests/data/`, and secrets in `.env` cloned from `.env.example`.
- Run `make dev-setup` to provision UV, `make run-extract PDF_FILE=deed.pdf` to drive the pipeline, `make run-verify CSV_FILE=calls.csv` to validate output, and rely on `make lint`, `make format`, `make check`, `make test`, and `make test-cov` (HTML in `htmlcov/`) as gates.

## Style, Testing & Commits
- Target Python 3.11+, four-space indentation, Ruff + Black (Black skips `text_parser.py`), sorted imports, and typed public APIs; keep snake_case modules/functions/tests, CapWords classes, and docstrings only where geometry or guardrails need context.
- Mock OpenAI in pytest, store sanitized PDFs in `tests/data/`, run `make test` often, and skim `htmlcov/index.html` after `make test-cov`.
- Use imperative commits, run `make pre-commit` before pushing, and have PRs note workflow stages touched plus prompt/env changes, linked issues, and manual verification.

## Metes & Bounds Workflow
- **Prep & triage:** Use the clearest scan, transcribe Exhibit A, underline each call, circle corners, flag meanders, log units (feet vs poles = 16.5 ft, note US survey feet), and capture provenance (book/page, survey date, plat references). Keep plotting tools nearby.
- **Normalize & extract:** Standardize ° ' " symbols, merge wrapped lines, normalize cardinal phrases, and watch OCR swaps (1↔4, 2↔7, 5↔S, 0↔°). Populate `course,direction_text,bearing_quadrant,bearing_azimuth_deg_from_north,distance_ft,curve_dir,radius_ft,delta_deg,arc_length_ft,chord_bearing,chord_length_ft,along,to,notes`; keep direction_text verbatim, leave numeric bearings blank for cardinal-only text, default missing minutes/seconds to zero, and capture curve fields when present.
- **Convert & verify:** Translate quadrant bearings to azimuths from north, compute `dx = distance * sin(azimuth)` and `dy = distance * cos(azimuth)` in radians, and validate curves with Δrad = Δdeg·π/180, L ≈ R·Δrad, and chord_length = 2R·sin(Δrad/2). Arc length is treated as the course distance (computed from R/Δ when missing) so closure uses the travelled line. Apply guardrails—traverse closure, interior angles, parallelism, curve consistency, area sanity, and double-entry comparison—before naming a file `_verified.csv`.
- **Plot & export:** For 1:24,000 graphing, poles convert to ≈distance/4.8 mm or distance/121 in; follow the protractor workflow (pick POB, mark bearing, scale distance, draw, label, wavy meanders). Preserve deed wording in direction/along/to fields, never fabricate bearings, flag unresolved calls, fit parcels to USGS quads or GIS basemaps, and follow the CHECK → CALC → SAVE cadence when exporting CSV/KML/GeoJSON. Record metadata (basis of bearing, datum, sources) alongside deliverables.
