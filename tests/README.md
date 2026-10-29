# Tests

Keep tests deterministic and focused on observable behavior. Mock provider calls in ordinary tests; test parsing and geometry against explicit fixtures and known values. Add regressions for corrected bugs without relying on implementation details.

Root tests live under `tests/` (`unit`, `integration`, `regression`, `e2e`, and opt-in browser tests). Workspace-package and Claude-plugin tests live with their respective components and are not included by the default root pytest discovery.

```sh
make test
make check
uv run pytest tests/unit/test_bearing_converter.py::TestQuadrantToAzimuth --no-cov
uv run pytest packages/mp-review/tests/ --no-cov --import-mode=importlib
uv run pytest plugins/metesparser/tests/ --no-cov --import-mode=importlib
uv run pytest packages/mp-review/tests/test_revision_store.py packages/mp-review/tests/test_revision_corridors.py packages/mp-review/tests/test_delivery_revision_corridors.py --no-cov --import-mode=importlib
uv run pytest tests/unit/test_skill_eval_cowork_materialization.py tests/unit/test_packaged_skill_navigation.py --no-cov
```

Root fixtures include `deed_call_factory`, `sample_legal_text`, and `isolate_logging_state`; legal-description text and test helpers are in `tests/fixtures/sample_deeds.py` and `tests/helpers.py`.

See the [testing guide](../docs/TESTING.md) for suite boundaries, coverage settings, focused revision/corridor/delivery/picker/PLSS commands, browser and live-provider gates, mocked PDF tests, and skill-evaluation limits. Browser preview tests validate offline page behavior and local downloads; native Claude/Cowork paired evaluations and live Mapbox remain separate acceptance gates. Current gate status is recorded in the [Cowork workflow ledger](../docs/implementation/2026-10-28-cowork-workflow-ledger.md).
