# Description comparison evidence — 2026-10-28

This is a chronological evidence record. Initial standalone notes are followed by the completed dashboard adapter and independent fixes. Current integrated acceptance is recorded in the [ledger](2026-10-28-evidence-review-ledger.md).

Scope: F1/F2 standalone structured description comparison. Comparison is advisory; it never establishes a physical/legal boundary, changes canonical tolerances or grants verified export. Only explicit straight ordered contiguous same-direction collinear groups are supported. Curves, relative-only geometry, incomplete orientations and unsupported boundary flags remain explicit. Length units convert from declared foot definitions; unknown units never establish compatibility. Direction requires documented shared basis identity or a sourced right-to-left rigid rotation. Position additionally requires a shared scene and fresh validated placements. A sourced transform is never fitted and does not substitute for positional placement evidence.

## Deterministic structural rules

Content signatures include all canonical call fields except ordinal `course` and derived `quality`; original source quote/reference/occurrence remain separately retained. Unique exact signatures anchor content. Crossing unique-anchor order produces a tentative reorder suggestion. Repeated exact signatures retain every possible tentative correspondence. Unmatched calls retain independent left/right records; unmatched calls at the same ordinal also receive an explicitly tentative changed-fields suggestion. No edit-distance cost, hidden tie-break or forced alignment is used. Split/merge candidates require contiguous recorded identical azimuths, identical declared native foot definitions and an exact summed numeric distance (relative floating comparison at 1e-12); this notation pattern never establishes directional/geographic agreement. Every candidate retains all contributor IDs and source quotes.

Comparison tolerance boundaries are inclusive, allowing only relative 1e-12 arithmetic roundoff at the boundary. Group collinearity requires equal normalized recorded headings independently of the pair-agreement bearing tolerance. Group vector/length sums use `math.fsum`; all derived arithmetic must remain finite. Unknown-bearing-label equality cannot establish a basis. Source changes alter the canonical validated-request hash.

## RED/GREEN commands and outcomes

- `uv run pytest packages/mp-verify/tests/test_description_comparison_behavior.py -q --no-cov`: RED **16 failed, 1 passed** against a callable `NotImplementedError` stub. This exercised real behavioral assertions beyond importability.
- `uv run pytest packages/mp-review/tests/test_description_comparison_files.py -q --no-cov`: RED **3 failed** against the file adapter stub.
- `uv run pytest packages/mp-review/tests/test_description_comparison_files.py packages/mp-verify/tests/test_description_comparison_behavior.py -q --no-cov --import-mode=importlib`: GREEN **25 passed**. Includes explicit reversal, angular wrap, 0.45-ft difference and inclusive boundary, unknown basis preserving verbatim monument changes, distinct foot definitions and unknown-unit rejection, sourced rotation, splits/reversed splits, noncollinear/canceling/noncontiguous/wrong-order groups, unsupported curved/incomplete/relative cases, duplicate/dangling/nonfinite inputs, structural ambiguity/reorders, derived overflow, fresh/stale placements and unknown scene units, source mutation/nonmutation, independently derived 30-degree vectors and distance finite differences, exact-byte request retention, output reuse rejection, symlink rejection and sanitized errors.
- `uv run mypy packages/mp-models/src/mp_models/comparison.py packages/mp-verify/src/mp_verify/comparison.py packages/mp-review/src/mp_review/comparison.py`: GREEN **3 source files**.
- `uv run pytest packages/mp-models/tests packages/mp-verify/tests packages/mp-review/tests tests/unit/test_bugs_audit_geometry_tdd.py tests/unit/test_bugs_closure_tdd.py -q --no-cov --import-mode=importlib`: GREEN **860 passed in 18.47s**. Includes existing positional same-traverse `compare_double_entry` regressions and parent CLI tests.
- `uv run metes-review compare-descriptions packages/mp-review/tests/fixtures/comparison-synthetic.json --output-dir /private/tmp/metesparser-comparison-20261028-worker`: direct subprocess return code **1**, status **needs_review** (the CLI convention for advisory/review-required output), no verification/boundary promotion. The fixture has unknown same-label basis and a changed distance/monument; vector comparison remains unavailable for agreement while structural changes persist.

Commands requiring uv cache access ran through approved sandbox escalation. No provider/network requests or document extraction were required.

## Exact artifact identities

| Artifact | SHA-256 |
| --- | --- |
| Synthetic request / exact retained comparison-request.json | `a7076cf63347877d451e2fc8254b6eee1a4cf7bef1bceb98a14a5ffbde1d6d9d` |
| comparison.json | `f845253a4196f989c5422c1c2cfbc690e0e402117b0d1cea3a512f593fc5bf06` |
| comparison-manifest.json | `6447ef9b9ec7ff4afe5a443791339c8f4a97aff06a5a7b6bc9782e37e2f47a4a` |

The initial combined CLI/hash shell command exited zero because its final `shasum` succeeded; a direct `subprocess.run(["metes-review", "compare-descriptions", fixture, "--output-dir", new_output], capture_output=True, text=True)` verified the actual CLI return code is **1**. Artifact generation completed with no errors.

Canonical request identity: `a6db2920b8ac8deab55bb1ed9a36e871c0a16373705a31fcf2fd1ed047ca52c7`. Manifest schema `1.0`, artifact kind `description_comparison`, algorithm `comparison-1.0.0`. Manifest request/result hashes cover exact bytes. Inspector replay compares the pure recomputed result, rather than trusting a self-consistent hash of derived content.

## Separate acceptance gates

Standalone deterministic engine/file/CLI gates above passed. Dashboard adapter/browser gate is being implemented separately; native-client visible display, native document reading, paired model behavior and live Mapbox provider acceptance are not established by these tests. Parent owns final full-repository CI and packaging checks. No commits were made by this worker.

## Dashboard adapter and browser evidence

The optional `description_comparison_specs` field is available in dashboard schema `1.1`. Each spec names two calculations, explicit source-owned call pairs, documented bearing bases and tolerances, and optionally a scene and placement IDs. The adapter builds immutable standalone requests from the bundle's actual calls/quotes/pages/occurrences. It accepts no duplicated caller-supplied call values. `PreparedDashboard.description_comparisons` retains both request and result, calculation identity and a fresh canonical input hash.

Dashboard and standalone plots have different provenance hash domains. To reuse a validated dashboard placement, the adapter compares fresh primitives/chains/unresolved geometry exactly, retains `(placement ID, original dashboard geometry hash, equivalent standalone geometry hash)` bindings, and rebinds only the equivalent geometry. The original bundle placement remains unchanged. Stale original placement hashes are rejected before adaptation.

`description-comparisons.json` is a separate stage. Its input/output hashes include selected requests, specs, explicit placement bindings and algorithm version; unrelated map placement changes do not invalidate an absent comparison. Cache checks replay fresh results and reject changed derived content. Presentation displays per-component explicit-pair results separately from tentative structural correspondences. Version-specific source buttons reuse the existing source selection/page/crop viewer. Browser scenarios and reset never modify comparisons, source records, canonical findings or export status.

- Dashboard RED: `uv run pytest packages/mp-verify/tests/test_dashboard_description_comparison.py -q --no-cov` → **3 failed, 1 passed** before schema/adapter support.
- Renderer RED: `uv run pytest packages/mp-export/tests/test_dashboard_description_comparison_html.py -q --no-cov` → **1 failed, 1 passed** before comparison markup.
- Browser RED: `METESPARSER_BROWSER_TESTS=1 uv run --extra browser-test pytest tests/browser/test_dashboard_comparison_ui.py -q --no-cov` → **1 failed** because the comparison section was absent. A subsequent intermediate run caught an incorrect test selector (`#close-viewer`); corrected to the existing `#viewer-close` control.
- Focused GREEN: `uv run pytest packages/mp-verify/tests/test_dashboard_description_comparison.py packages/mp-review/tests/test_dashboard_comparison_stages.py packages/mp-export/tests/test_dashboard_description_comparison_html.py -q --no-cov --import-mode=importlib` → **9 passed**.
- Full dashboard browser GREEN: `METESPARSER_BROWSER_TESTS=1 uv run --extra browser-test pytest tests/browser --no-cov --import-mode=importlib -q` → **15 passed in 8.87s**, including both occurrence source links, verbatim changed monument selection, scenario edit/reset and immutable source/comparison/findings checks.
- Combined package regression initially reported **963 passed, 23 skipped, 1 failed**: unrelated overlay changes incorrectly invalidated an empty comparison cache. After correcting the dependency, `uv run pytest packages/mp-review/tests/test_dashboard_plot_stages.py packages/mp-review/tests/test_dashboard_comparison_stages.py packages/mp-verify/tests/test_dashboard_description_comparison.py -q --no-cov --import-mode=importlib` → **18 passed**. Parent owns the final combined rerun after independent core review.
- Dashboard model/verifier and HTML renderer targeted mypy checks passed. Optional live Mapbox and native-client/document/model acceptance remain separate gates; the offline comparison UI requires neither provider nor network.

Independent review added partial-curve evidence cases: canonical model validation rejects arc/delta/chord fields without curve direction, but `curve_type`, radial bearing and non-tangent flags initially passed as straight calls. Parent corrected these cases together with independent group-collinearity and split-seed review; see the final core result below.

Final independent core review corrected the partial-curve and grouping findings: group collinearity now requires equal normalized recorded headings, independently from pair agreement tolerance; partial curve hints stay unsupported; nonboundary/uncertain singleton calls cannot seed split/merge suggestions. Parent recorded **34 comparison behavior tests GREEN**. The dashboard fixture's SHA-256 is `f0620e3f2cac9800ea189add63d272f4d56c7bd2f542767e18c82c9ac4cf1add`. Final combined package/CI validation is owned by the parent after these core and independent source-review fixes.


## Final positional-prefix guard review

Independent read review found the new `_position` prefix guard correct for its stated scope. It inspects every non-tie-in call before the earliest selected course and blocks positional comparison when curve evidence exists without a canonical curve. The selected straight-course vector comparison remains independent and available. Complete preceding curves still use the existing validated arc builder; unresolved or unsupported curves cannot pass the subsequent fresh-primitive membership check. The guard does not change canonical calls, placements or selected-vector results.

Parent recorded `test_partial_curve_before_selection_cannot_establish_position` **RED 1 → GREEN**, followed by **43 focused core/dashboard/file tests passed**. The preceding full package run was **1004 passed, 23 skipped** before this final guard; the focused rerun covers the new change. This reviewer inspected the helper, guard, regression and shared plot-builder behavior without repeating the suites. Reviewed comparison module SHA-256: `56b7112be0260d7d6670ceb787ab1cd8a4b54bfceee8ea3c2b07234b1de25282`.
