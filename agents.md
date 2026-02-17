# Repository Guidelines

MetesParser transforms scanned deeds into structured metes-and-bounds data. Follow these guardrails so every contribution stays reliable, auditable, and easy to review.

## Project Structure & Module Organization

The codebase is a **uv workspace monorepo** with 7 composable packages plus a backward-compatible monolith:

```
packages/
  mp-models/    → Pydantic schemas, JSONL envelope, units (zero deps)
  mp-bearing/   → Pure math: azimuth, curves, deltas (depends: mp-models)
  mp-ocr/       → LLM boundary: PDF → text (depends: mp-models)
  mp-parse/     → Rule-based parsing: text → calls (depends: mp-models, mp-bearing)
  mp-verify/    → Geometric verification: 8 checks (depends: mp-models, mp-bearing)
  mp-export/    → CSV/JSON/audit HTML output (depends: mp-models, mp-verify)
src/metesparser/ → Orchestrator + backward-compat monolith
```

When modifying code:
1. Modify the package code (e.g., `packages/mp-parse/`)
2. Keep the monolith in `src/metesparser/` in sync
3. Run per-package tests: `uv run pytest packages/mp-parse/tests/ -v --no-cov`
4. Run cross-package import verification: `uv run pytest tests/unit/test_cross_package_imports.py -v`

Only `mp-ocr` calls LLMs; everything downstream is deterministic.

Tests reside in `tests/`; fixtures in `tests/fixtures/`; prompts in `prompts/`; docs in `docs/`. Sample deeds and ground truth JSON are in `sample_deeds/`.

## Build, Test, and Development Commands
- `make dev-setup` bootstraps UV and installs dependencies for a new machine or virtualenv.
- `make run-extract PDF_FILE=deed.pdf` executes the pipeline end-to-end; `make run-verify CSV_FILE=calls.csv` applies closure and curve guardrails to produced calls.
- Quality gates: `make lint`, `make format`, `make check`, `make test`, and `make test-cov` (coverage HTML in `htmlcov/index.html`).
- Per-package tests: `uv run pytest packages/mp-*/tests/ -v --no-cov` (requires `--no-cov` because root coverage config targets monolith).

## Coding Style & Naming Conventions
- Target Python 3.11+, four-space indentation, snake_case modules/functions/tests, CapWords classes, and typed public APIs.
- Use Ruff for all formatting and linting (`text_parser.py` excluded due to Unicode DMS symbols). Never use Black. Keep imports sorted and add concise comments only when geometry rules or guardrails need justification.

## Testing Guidelines
- Run Pytest via `make test`; mock LLM calls to keep suites deterministic. Store sanitized inputs and expected outputs under `tests/fixtures/`.
- Name tests after behaviors (`test_parse_curve_segments`) and review `htmlcov/index.html` after `make test-cov` to confirm coverage.
- Use conventional commits (`feat:`, `fix:`, `docs:`, `chore:`, `test:`, `refactor:`).

## Commit & Pull Request Guidelines
- Write conventional commit messages (`feat: add curve support`) and run `make pre-commit` before pushing.
- Never push directly to main — use feature branches and PRs.
- PRs should list workflow stages affected, cite prompt or env updates, link issues, and summarize manual verification (e.g., closure deltas, curve residuals).

## Security & Configuration Tips
- Copy `.env.example` to `.env`; never commit secrets. Guard API keys when scripting against the pipeline.
- Document basis of bearing, datum, and source metadata alongside exported CSV so deliverables remain audit-ready.
