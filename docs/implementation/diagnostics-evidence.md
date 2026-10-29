# B1 closure diagnostics implementation evidence

This is a chronological implementation record. The initial outstanding gates below predate B2 and the later independent review. See the [integrated ledger](2026-10-28-evidence-review-ledger.md) and [independent numerical review](diagnostics-independent-review.md) for current local acceptance; native/provider gates remain separate.

Task: workstream B1 and standalone file adapter from the 2026-10-28 implementation plan.
Worker: diagnostics subagent (inherited Codex model; exact model identifier unavailable).
Ownership: new diagnostics modules in mp-models, mp-verify, mp-review; corresponding tests.
No commits or provider calls.

## RED

Command:

```sh
uv run pytest packages/mp-models/tests/test_diagnostics.py packages/mp-verify/tests/test_diagnostics.py packages/mp-review/tests/test_diagnostics.py --no-cov --import-mode=importlib -q
```

Result: exit 2, collection errors: `ModuleNotFoundError: No module named 'mp_models.diagnostics'`.
Initial uv cache sandbox denial resolved by approved escalation; no package changes.
Behavioral RED and GREEN evidence follow below as implementation proceeds.

## Numerical scope

Only complete canonical straight boundaries; marked tie-ins are excluded and retained in the request.
Curves, meanders, exception boundaries and indefinite/missing bearings do not yield partial residuals.
Distance and bearing sensitivity use different units and separate ranks. Absolute projection on residual
direction keeps opposing candidates tied. Unit sensitivity is neither an error probability nor a correction.
This operation never invokes canonical verification or verified export.

## Outstanding gates

Independent numerical review, affected package suite, public exports/CLI/facade (parent), dashboard
integration B2, extracted runtime and provider/native-client acceptance remain pending.

## Behavioral RED and GREEN

After initial implementation, uniquely named test modules avoid a pytest `tests.test_diagnostics`
module collision between the two packages that have `tests/__init__.py`.

```sh
uv run pytest packages/mp-models/tests/test_diagnostics_models.py packages/mp-verify/tests/test_diagnostics_math.py packages/mp-review/tests/test_diagnostics_file.py --no-cov --import-mode=importlib -q
```

Behavioral RED: 2 failed, 29 passed. Tampered result input/request identity was not rejected, and
finite huge distances raised `OverflowError` instead of returning explicit unsupported results.
GREEN after repairs: 31 passed in 0.14 seconds. Additional finite-difference and rounding-box cases
were then added; affected-suite result is recorded below when finished.

## Request authoring and hash contract

```python
from mp_models.deed_call import DeedCall
from mp_models.diagnostics import (
    ClosureDiagnosticRequest, DiagnosticCall, DiagnosticFrame, diagnostic_input_hash,
)
calls = tuple(
    DiagnosticCall(call_id=f"c{i}", call=DeedCall(
        course=i, direction_text="synthetic source text",
        bearing_azimuth_deg_from_north=angle, distance_ft=distance,
    ))
    for i, (angle, distance) in enumerate(
        ((90, 100.5), (180, 100), (270, 100), (0, 100)), 1
    )
)
request = ClosureDiagnosticRequest(
    request_id="r1", input_id="parcel", calls=calls,
    input_sha256=diagnostic_input_hash(calls),
    frame=DiagnosticFrame(name="Recorded local"),
)
```

`diagnostic_input_hash` hashes the ordered full canonical call and source-reference payload as
UTF-8 JSON, sorted keys, compact separators, Unicode preserved, finite numbers only. Model defaults
are included. `request_sha256` applies the same serialization to the full validated request; it
therefore includes the frame, explicit foot definition, source precision and scenario evidence.
The file adapter's manifest `source_sha256` instead hashes **exact original request bytes**.
`diagnostics_sha256` hashes the exact emitted diagnostics JSON file. None of these hashes authenticate
source truth. Source hashes and occurrence identifiers remain null when unavailable.

Source-reference quotes retain whitespace. Call IDs are unique and stable. Scenarios require all
three of `scenario_id`, `baseline_request_sha256`, `scenario_evidence`; closure cannot choose a reading.

Distance derivatives are feet per foot. Angular derivatives are feet per radian and per arcsecond
(`pi / 648000` radians per arcsecond). Absolute projection onto the residual unit vector produces
separate dense ranks; floating ties use relative tolerance `1e-10`, absolute `1e-12` within each
category. Ranking is unavailable below `32 * ulp(perimeter_ft)`, solely a numeric resolution rule;
canonical closure tolerance is never changed. No residual course is added and input calls stay intact.

Quantization requires explicit positive distance/bearing increments and source evidence with
`rounding="nearest"`. For half-increments `h_d` and `h_a` radians, the conservative endpoint bound is
the sum over courses of `h_d + 2*(d+h_d)*sin(h_a/2)`. The bearing increment is at most one full turn.
This triangle-inequality bound is deterministic, not statistical; it is not a confidence score.
Tests independently sample all 256 corners of a four-course rounding box.

B1 affected-suite GREEN before B2: `uv run pytest packages/mp-models/tests/ packages/mp-verify/tests/ packages/mp-review/tests/ --no-cov --import-mode=importlib -q` → **693 passed in 15.49 seconds**. This includes 35 uniquely named diagnostics regressions after additional independent finite differences and all rounding-box corners.

## B2 dashboard integration

Ownership explicitly extended to dashboard model, calculator, file adapter, renderer, browser assets
and relevant tests. Existing record findings remain in `calculations`; `PreparedDashboard.diagnostics`
is a separate fresh stage. Each wrapper retains calculation and occurrence IDs and the current
`calculation_input_hash`. `diagnostic_request_from_dashboard(bundle, spec)` exposes exactly the request
that standalone diagnosis accepts. Null source calls and relative constraints produce explicit
incomplete/unsupported wrappers, never fabricated `DeedCall`s.

RED command:

```sh
uv run pytest packages/mp-verify/tests/test_dashboard_diagnostics.py packages/mp-export/tests/test_dashboard_html.py -q --no-cov --import-mode=importlib
```

Initial RED: missing request adapter import. Behavioral RED after stage wiring: **2 failed, 50 passed**;
recorded/scenario diagnostic regions were absent, and independent browser `diagnoseScenario` did not
exist. GREEN after rendering and browser math: **52 passed in 1.82 seconds**.

`make test-dashboard-browser` initially passed **13 tests in 6.43 seconds**, including baseline
immutability, opposing candidate ties, keyboard source/crop selection, edited scenario recalculation,
reset, unchanged embedded records, no network and no browser errors. A second-occurrence source-page
regression and explicit stale/tampered diagnostic cache tests were then added.

Calculator identity is now `dashboard-1.1.0`. Diagnostic input/output hashes are persisted alongside
the existing stages; legacy caches miss, and saved diagnosis is compared against fresh pure results.
Renderer identity already hashes Python, CSS and JS bytes and therefore changes with this UI.
Browser math separately labels its working scenario, applies compensated summation, and uses the same
unit/tie/numerical-zero rules; relative diagnosis remains unsupported. Candidate actions reuse existing
`selectSourceCall`, including existing source page/crop and occurrence bindings. Browser edits and reset
never write artifacts or update original findings, placement, canonical status or export eligibility.

Explicit source module mypy check passes with `--disable-error-code unused-ignore`; explicitly passing
the renderer changes import classification for two pre-existing `import-untyped` suppression comments
in the file adapter. Their original root-check behavior is preserved. Ruff checks/format pass for owned
files. Parent owns root/facade/CLI checks and independent numerical review.

## Final local results and review identity

Affected four-package suite: **868 passed, 22 skipped in 17.54 seconds**. Skips are separately gated Mapbox/provider/browser tests; the dedicated dashboard target then passed **14 tests in 6.89 seconds**. Supplied synthetic fixture validation: **4 passed in 0.12 seconds**. Desktop dashboard screenshot visually inspected at `output/playwright/plot-validation/plot-1200-light.png`; both diagnosis panels are readable and source controls remain accessible.

Standalone file-adapter smoke completed as `needs_review`, `engine_verified=false`, `verified_export_eligible=false` in `output/diagnostics-validation/`; exact retained request and produced artifact hashes:

- `packages/mp-review/tests/fixtures/diagnostics/request.json`: `9064ec9031f0a95f73e4cee0490175edd704022032e2028dfc2d943292d244f3`
- `output/diagnostics-validation/diagnostics-manifest.json`: `d7409dc7115ec86b355d80aaac6bc430fec7a3af68e3dd13e7db5f3cdeff0520`
- `output/diagnostics-validation/diagnostics.json`: `94ded5c1af28f3007276cf2eb77ae2271676ff2c0d4f441d9351d23a689f4916`
- `output/diagnostics-validation/request.json`: `9064ec9031f0a95f73e4cee0490175edd704022032e2028dfc2d943292d244f3`

Worker diff identity (SHA-256 per owned source; no commit):

- `packages/mp-models/src/mp_models/diagnostics.py`: `2f57d66604e8e1db51b547282588c63dbfcc55fdef8eabec8cefc2465efbd47f`
- `packages/mp-models/src/mp_models/dashboard.py`: `9231c5180c2a4fe0c86d78738a88291c6d08f207ec9729c482933b631052c89a`
- `packages/mp-verify/src/mp_verify/diagnostics.py`: `945c6c6edae779a5b1b2f5e2cfd8aa61f62881567c9bdc084f054d0ad13a8067`
- `packages/mp-verify/src/mp_verify/dashboard.py`: `5e81d72034aabf1aaab146dbdda4b674c5dc6a0fe90cf32eff2cc6e5c32ea077`
- `packages/mp-review/src/mp_review/diagnostics.py`: `4f3073fa364c95ee098744e1d512a5155eed8397ef14bff9f5d89d1868c3b4b4`
- `packages/mp-review/src/mp_review/dashboard.py`: `eec77206ab21da4afc97cca54c75b1a6859a5fc2d0ccf38afc064ff16b0ee356`
- `packages/mp-export/src/mp_export/dashboard_html.py`: `3cb3fd27c25ca90bbfe4879ae646c962012d477b1a323b69653742a54cc634a3`
- `packages/mp-export/src/mp_export/dashboard_assets/dashboard.js`: `1cfe75d9d655e576087a507629ce229b007e51a36b8a058ae5c796abb09bb033`
- `packages/mp-export/src/mp_export/dashboard_assets/dashboard.css`: `a48a51d6bf47c8b5681e6ffad4e28b080f9df5aeeaeea0145bcdd8a68ed2ab92`

Independent numerical review is owned by the parent agent and remains pending at this handoff. Live provider/native client acceptance was not run by this worker; no claim is made about those gates.

Final cross-package import verification: `uv run pytest tests/unit/test_cross_package_imports.py --no-cov -q` → **26 passed in 0.03 seconds**. Final Ruff check over all owned Python sources and tests passed. The standalone file-adapter smoke returned `needs_review`, `engine_verified=False`, `verified_export_eligible=False`.
