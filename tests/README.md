# Tests

## Philosophy

Tests are the safety net that lets us trust the system's output. Since metesParser processes legal descriptions that define real property boundaries, correctness is non-negotiable. Our test philosophy:

- **TDD first** — Write tests before implementation. Tests define the expected behavior; code satisfies it.
- **Determinism over cleverness** — Every test produces the same result every time. LLM calls are mocked. No network, no randomness, no flakiness.
- **AI is mocked, math is proven** — Only `mp-ocr` calls LLMs, and those calls are always mocked in tests. Bearing conversions, closure calculations, and verification checks are tested against known geometric truths.
- **Regression protection** — Every bug fix gets a regression test. We never fix the same bug twice.
- **Test what matters** — We test behavior, not implementation details. Public APIs, not private internals.

## Structure

```
tests/
├── conftest.py              # Shared fixtures, custom markers, logging isolation
├── helpers.py               # Assertion helpers and data generators
├── fixtures/
│   └── sample_deeds.py      # Legal description text samples
├── unit/                    # Fast, isolated module tests (~923 tests)
├── integration/             # Full pipeline tests (~31 tests)
├── regression/              # Bug fix validation (~40 tests)
└── e2e/                     # CLI end-to-end tests (~2 tests)
```

Per-package tests live alongside their packages in `packages/mp-*/tests/`.

## Running Tests

```bash
# All tests
make test

# By category
uv run pytest tests/unit/ -v
uv run pytest tests/integration/ -v
uv run pytest tests/regression/ -v
uv run pytest tests/e2e/ -v

# By marker
uv run pytest -m curve -v
uv run pytest -m "not slow" -v

# Per-package (requires --no-cov)
uv run pytest packages/mp-models/tests/ -v --no-cov

# With coverage
make test-cov
```

## Fixtures

Defined in `conftest.py` and available to all tests:

- **`deed_call_factory`** — Creates `DeedCall` objects with sensible defaults
- **`sample_legal_text`** — 18 Pennbrook Dr parallelogram (4 calls, closes perfectly)
- **`isolate_logging_state`** — Resets structlog configuration between tests

Shape fixtures and data generators live in `helpers.py` and `fixtures/sample_deeds.py`.

## Markers

| Marker | Purpose | Skip with |
|--------|---------|-----------|
| `slow` | Tests > 1 second | `-m "not slow"` |
| `integration` | Pipeline tests | `-m "not integration"` |
| `regression` | Bug fix tests | `-m "not regression"` |
| `curve` | Curve calculations | `-m "not curve"` |
| `validation` | Input validation | `-m "not validation"` |

## Coverage

Target: >90% line coverage (current: ~94%). Run `make test-cov` and open `htmlcov/index.html`.

## See Also

- [docs/TESTING.md](../docs/TESTING.md) — Comprehensive testing guide with per-module coverage, PDF test details, and best practices
