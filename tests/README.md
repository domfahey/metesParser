# Tests

Keep tests deterministic and focused on observable behavior. Mock provider calls in ordinary tests; test parsing and geometry against explicit fixtures and known values. Add regressions for corrected bugs without relying on implementation details.

Root tests live under `tests/` (`unit`, `integration`, `regression`, `e2e`, and opt-in browser tests). Workspace-package and Claude-plugin tests live with their respective components and are not included by the default root pytest discovery.

```sh
make test
make check
uv run pytest tests/unit/test_bearing_converter.py::TestQuadrantToAzimuth --no-cov
uv run pytest packages/mp-review/tests/ --no-cov --import-mode=importlib
uv run pytest plugins/metesparser/tests/ --no-cov --import-mode=importlib
```

Root fixtures include `deed_call_factory`, `sample_legal_text`, and `isolate_logging_state`; legal-description text and test helpers are in `tests/fixtures/sample_deeds.py` and `tests/helpers.py`.

See the [testing guide](../docs/TESTING.md) for suite boundaries, coverage settings, package/plugin commands, browser and live-provider gates, mocked PDF tests, and skill-evaluation limits.
