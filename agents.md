# Repository Guidelines

# Repository Guidelines

MetesParser transforms scanned deeds into structured metes-and-bounds data. Follow these guardrails so every contribution stays reliable, auditable, and easy to review.

## Project Structure & Module Organization
- Core pipeline lives in `src/metesparser/` (PDF extraction, parsing, geometry, closure). Mirror tests reside in `tests/`; fixtures in `tests/fixtures/`; prompts in `prompts/`; docs in `docs/`.
- Keep sanitized deed PDFs and expected CSVs in `tests/fixtures/`. Record provenance (book/page, survey date, plats) in doc notes so downstream analysts can verify sources.

## Build, Test, and Development Commands
- `make dev-setup` bootstraps UV and installs dependencies for a new machine or virtualenv.
- `make run-extract PDF_FILE=deed.pdf` executes the pipeline end-to-end; `make run-verify CSV_FILE=calls.csv` applies closure and curve guardrails to produced calls.
- Quality gates: `make lint`, `make format`, `make check`, `make test`, and `make test-cov` (coverage HTML in `htmlcov/index.html`).

## Coding Style & Naming Conventions
- Target Python 3.11+, four-space indentation, snake_case modules/functions/tests, CapWords classes, and typed public APIs.
- Use Ruff + Black for formatting (`text_parser.py` excluded from Black). Keep imports sorted and add concise comments only when geometry rules or guardrails need justification.

## Testing Guidelines
- Run Pytest via `make test`; mock LLM calls to keep suites deterministic. Store sanitized inputs and expected outputs under `tests/fixtures/`.
- Name tests after behaviors (`test_parse_curve_segments`) and review `htmlcov/index.html` after `make test-cov` to confirm coverage.

## Commit & Pull Request Guidelines
- Write imperative commit messages (`Adjust closure tolerance`) and run `make pre-commit` before pushing.
- PRs should list workflow stages affected (Prep, Normalize, Convert, Plot), cite prompt or env updates, link issues, and summarize manual verification (e.g., closure deltas, curve residuals).

## Security & Configuration Tips
- Copy `.env.example` to `.env`; never commit secrets. Guard API keys when scripting against the pipeline.
- Document basis of bearing, datum, and source metadata alongside exported CSV/KML/GeoJSON so deliverables remain audit-ready.
