# Independent workstream B review

The counts and byte identities below describe this bounded review snapshot.
See the [integrated ledger](2026-10-28-evidence-review-ledger.md) for final
combined local gates and [native availability](native-evaluation-availability.md)
for the separately unrun model/client acceptance.

Date: 2026-10-28. Reviewer: `source_handoffs`; configured model per parent
assignment: GPT-6.1-sol, exact runtime snapshot unavailable. This reviewer did not author B. Reviewed
the plan's B scope, diagnostic schemas/math and tests, dashboard source adapter,
browser diagnosis/selection/scenario logic, and export boundaries. No commits.
Baseline HEAD: `c0d6074941c9a59e68cc1d37e1f89531621f23e0`.

## Confirmed findings and repairs

1. **Finite browser sensitivity overflow.** `diagnoseScenario` multiplied an
   angle derivative by the residual component before dividing by residual
   magnitude. For finite synthetic distances `1e200` and `1e300`, intermediate
   products overflowed; the function still claimed `supported` and JSON encoded
   the projections as null. Python normalizes the residual first and computes
   finite results. Browser code now uses normalized components before both
   distance/angle projections and rejects any remaining nonfinite projections
   as explicitly unsupported. Excluded tie-in IDs survive that outcome.
2. **Browser ULP threshold disagreed at binary boundaries.** `Math.log2` can
   round a value immediately below a power of two to the integer exponent. A
   perimeter immediately below 512 ft produced a browser threshold
   `3.637978807091713e-12` versus Python's `1.8189894035458565e-12`, changing
   ranking availability for the same immutable courses. The browser helper now
   checks the inferred binade against the actual value before deriving its ULP.

Edits are limited to the adjacent browser diagnosis/math functions and the new
`mp-export/tests/test_dashboard_diagnostics_review.py`. The comparison worker
confirmed no conflicting edit to that block; its source-button handler remains
intact. Canonical verification and source values were not changed.

## RED and GREEN

```sh
uv run pytest packages/mp-export/tests/test_dashboard_diagnostics_review.py -q --no-cov --import-mode=importlib
```

Behavioral RED: **3 failed, 1 passed**. Both large finite scales returned null
angle projections while Python returned finite values. The binary-boundary
fixture independently checked its perimeter was below 512 before asserting the
ULP mismatch. The existing `1e155` case passed. After repair: **4 passed**.

```sh
uv run pytest packages/mp-models/tests/test_diagnostics_models.py packages/mp-verify/tests/test_diagnostics_math.py packages/mp-verify/tests/test_dashboard_diagnostics.py packages/mp-export/tests/test_dashboard_html.py packages/mp-export/tests/test_dashboard_diagnostics_review.py packages/mp-review/tests/test_diagnostics_file.py --no-cov --import-mode=importlib -q
```

**92 passed in 2.16 seconds.** Includes independent finite differences and
rounding-box corner bounds, opposing candidate ties, unsupported/incomplete
geometry, zero residual, source identity, canonical non-promotion, and fresh
standalone/dashboard agreement.

```sh
METESPARSER_BROWSER_TESTS=1 uv run pytest tests/browser/test_dashboard_plot_ui.py -k diagnostic --no-cov --import-mode=importlib -q
```

**2 passed, 10 deselected in 0.93 seconds** in offline Chromium, after the
required uv cache escalation. Source buttons selected the correct occurrence,
page and crop; scenario edits/reset preserved the frozen baseline and retained
input data. Browser guards observed no remote requests or page errors.
Ruff lint/format checks passed for the new regression file.

## Independent mathematical assessment

For azimuth clockwise from north, distance derivatives are `(sin θ, cos θ)`;
angle derivatives are `(d cos θ, -d sin θ)` per radian. Multiplication by
`π / 648000` correctly converts to feet per arcsecond. Distance and angle
projections/ranks remain separate and use absolute projection, so opposing
candidate explanations stay tied.

The nearest-rounding endpoint bound follows the triangle inequality:
`half_distance + (d + half_distance) * 2 sin(half_angle / 2)` per course, summed
over the retained boundary. The declared angular-increment cap keeps the sine
term monotone over the permitted half-angle. Assumptions require explicit
evidence; numerical text formatting does not supply them. The bound is not a
probability or confidence estimate. No additional confirmed Python numeric,
source-binding, baseline/scenario, or export-promotion finding remained after
this bounded review.

## Reviewed identity and limits

| File | SHA-256 at review |
| --- | --- |
| `mp_models/diagnostics.py` | `2f57d66604e8e1db51b547282588c63dbfcc55fdef8eabec8cefc2465efbd47f` |
| `mp_verify/diagnostics.py` | `945c6c6edae779a5b1b2f5e2cfd8aa61f62881567c9bdc084f054d0ad13a8067` |
| `dashboard_assets/dashboard.js` | `dc58cc46a2521ef26b0e079ec6ca10d393c0cb552f2b8d2aca9ca37271a5d444` |
| `test_dashboard_diagnostics_review.py` | `96b15a6cb34b4b8ad34d7b2241d4be0e845f2d3b91bac1df70f0bbbc4a9616da` |

The JavaScript file also contains concurrent F2 changes outside the reviewed
diagnosis block. This review does not certify those separate features. Renderer
fingerprints change with the repaired code, so existing presentation caches must
be regenerated. No native document reading, live map/provider call, or paid
model evaluation ran; those gates remain separate.
