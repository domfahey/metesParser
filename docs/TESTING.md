# Testing guide

This guide describes the current test lanes and the commands that run them. Counts are intentionally omitted because the suite changes as packages and behaviors are added.

## Running tests

```sh
make test       # root tests/ suite, with the configured coverage report
make check      # lint + format + mypy on src/metesparser + root tests
make test-fast  # root tests; stop on the first failure
make test-cov   # root tests and HTML/terminal coverage report
```

`make check` runs lint, `format` (which can modify files), mypy on `src/metesparser/`, and the root test suite. `make quality` uses the non-mutating format check. `make pre-commit` runs `lint-fix`, `format`, and `test`; it does not run mypy. `make ci` starts with `clean` (removing `.venv`, `dist/`, and other generated files), then runs quality and coverage tests; it does not run mypy.

The root pytest configuration discovers `tests/` and measures `src/metesparser/` with a configured 80% coverage floor. The project aims for coverage above 90%; the configured floor is the enforced threshold. Coverage is not configured to measure the workspace packages, so disable it for package-only runs.

### Root suite

Pytest defaults to the root `tests/` directory. Workspace packages and the Claude plugin have separate suites and must be named explicitly. Use importlib mode when running package/plugin suites to avoid test-package import collisions.

```sh
# Root unit, integration, regression, and CLI tests
uv run pytest tests/unit/ --no-cov
uv run pytest tests/integration/test_pdf_processing.py --no-cov
uv run pytest tests/regression/ --no-cov
uv run pytest tests/e2e/ --no-cov
```

The default root run also collects `tests/browser/`, where browser tests skip unless enabled by the explicit browser target. Package and plugin test trees are separate lanes:

### Per-package and plugin tests

```sh
# Workspace package suites (run together or select one package)
uv run pytest packages/mp-*/tests/ --no-cov --import-mode=importlib
uv run pytest packages/mp-review/tests/test_source_handoff.py --no-cov --import-mode=importlib

# Plugin runtime/packaging tests
uv run pytest plugins/metesparser/tests/ tests/unit/test_plugin_build.py \
  --no-cov --import-mode=importlib
```

For example, this focused node ID is present in the root suite:

```sh
uv run pytest tests/unit/test_bearing_converter.py::TestQuadrantToAzimuth --no-cov
```

Run browser checks separately when their prerequisites are available:

```sh
make test-dashboard-browser
make test-mapbox-browser
```

These targets require the optional browser-test dependencies and a usable Chromium; dashboard checks also require Node. Mapbox browser checks additionally require the pinned SDK cache and Chromium WebGL2. `make test-mapbox-live` is a separate provider acceptance check requiring a public Mapbox token and network access. It is not part of `make check`.

## PDF pipeline tests

`tests/integration/test_pdf_processing.py` exercises the pipeline with mocked provider calls. Each test writes a minimal stub PDF under pytest's temporary directory and feeds deterministic text fixtures to the mocked client. It does not read PDFs from `sample_deeds/`, call an LLM provider, or require API keys.

```sh
uv run pytest tests/integration/test_pdf_processing.py::test_process_deed_pdf_closure_metrics --no-cov
```

The parametrized cases include a 100-foot square, 18 Pennbrook (7,500 sq ft), and 24 Pennbrook (17,750 sq ft). These are software fixtures, not external deed validation.

## Fixtures and markers

Root fixtures in `tests/conftest.py` include `deed_call_factory`, `sample_legal_text`, and `isolate_logging_state`. Shared legal-description text lives in `tests/fixtures/sample_deeds.py`; assertion helpers are in `tests/helpers.py`. Other suites define their own focused fixtures alongside package/plugin tests.

Root markers are `slow`, `integration`, `e2e`, `regression`, `curve`, and `validation`. For example, `uv run pytest -m 'integration' --no-cov` runs marked root integration tests. Package-only commands should use `--no-cov`; use `--import-mode=importlib` when collecting multiple package/plugin test trees.

## Test workflow

For a behavior change, add a focused regression for the expected behavior, run it first, then run the affected suite and the broader check when appropriate. Keep fixtures deterministic and synthetic unless a test explicitly documents a real source; ordinary tests should not make provider calls. Root coverage is measured against `src/metesparser/`, as configured in [pyproject.toml](../pyproject.toml); package coverage needs a package-specific configuration before it can be reported meaningfully.

## Skill and provider acceptance

Plugin engine behavior is covered by `plugins/metesparser/tests/` and workspace package tests. Skill-evaluation cases are scenario specifications until run in fresh sessions. Native Claude document/client acceptance, paired baseline-versus-skill evaluations, and live Mapbox rendering are separate gates; repository tests do not establish those results. See the [evaluation protocol](../plugins/metesparser/evals/README.md) for recording model, client, tool availability, transcripts, and outcomes.

For plugin build and distribution checks, use the [plugin maintenance guide](CLAUDE_PLUGIN.md). Do not treat passing engine tests or generated evaluation scenarios as native-host acceptance.
