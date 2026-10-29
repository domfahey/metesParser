# Evidence and review implementation ledger

Plan: [source evidence, diagnostics, maps, and composable skills](../plans/2026-10-28-skill-evidence-and-review-improvements.md).

Implementation started 2026-10-28 on `feat/deed-closure-dashboard-skill`, baseline `c0d6074`. Existing uncommitted research, README, todo and ignore changes are retained. No commit or push is authorized by this implementation task.

This is a chronological ledger. The [completion-audit follow-up](#completion-audit-follow-up) contains the latest validation and archive identities, superseding the earlier acceptance snapshot below.

## Execution and gates

The parent owns integration. GPT-6.1-sol workers own source validation and diagnostic mathematics; GPT-6-luna owns evaluation preparation. Subsequent assignments and independent reviews are recorded as they occur. Local tests, model behavior, native document reading and live provider acceptance are separate gates.

| Slice | RED evidence | GREEN evidence | Review / remaining |
| --- | --- | --- | --- |
| Baseline imports/distribution | Not a new behavior | `uv run pytest tests/unit/test_cross_package_imports.py tests/unit/test_plugin_build.py --no-cov -q`: 32 passed | Baseline only |
| Shared advisory CLI settings | `uv run pytest packages/mp-review/tests/test_advisory_cli.py --no-cov -q`: four failures, unregistered commands had no JSON result | Same command: 4 passed | Valid command integration follows workers |
| In-memory review replay / manifest | `uv run pytest packages/mp-review/tests/test_review_replay.py --no-cov -q`: 4 failures, missing manifest/replay API (after correcting required fixture direction_text) | Replay + existing review + CSV writer suites: 29 passed | Inspector integration and independent review pending |

Source records, diagnostic requests, comparisons and model evaluations have their own worker evidence files in this directory. A passing test count does not substitute for the remaining plan gates.

## Review replay contract

`review-manifest.json` schema `1.0`, `kind=review`, `replay_version=review-replay-1` retains the original input kind/name/hash, retained `source.txt` path, explicit stated-area option (including null), recorded canonical status, and byte hashes for produced artifacts. `mp_review.api.replay_review(source, input_kind=..., source_name=..., stated_area_sq_ft=...)` dispatches retained bytes without writing artifacts or invoking verified export. CSV is decoded from the same retained bytes as text/JSON; filenames do not determine replay kind.

## External acceptance

Native Claude Haiku/Sonnet/Opus sessions, native document reading, and live Mapbox are **not run** at implementation start. Record observations or concrete availability constraints before final reporting; do not infer acceptance from mocks or Codex sessions.

## Integrated implementation and independent review

All four available execution slots were used for parallel work (parent plus three workers), then reused for independent reviews. Assigned implementation/review models were GPT-6.1-sol for source validation, diagnosis, inspection and comparison, and GPT-6-luna for fixture/evaluation tooling, documentation, navigation checks and distribution preparation. These assignments describe development workers, not native Claude evaluation coverage.

| Workstream | Delivered behavior | Evidence |
| --- | --- | --- |
| A | Schema 1.1 acquisition/selection records, exact UTF-8 range reconstruction, hashes, coverage/uncertainty and confined paths; legacy identity remains unverifiable | [Source handoffs](source-handoffs-evidence.md) |
| B | Source-linked straight-boundary sensitivities and explicit precision bounds; standalone diagnosis and separate baseline/scenario dashboard views | [Implementation](diagnostics-evidence.md), [independent numerical review](diagnostics-independent-review.md) |
| C | Read-only inventory, semantic replay and conditional dependency invalidation; recommendations never execute a workflow | [Inspection](artifact-inspection-evidence.md) |
| D | Independent raster opacity/order/visibility; fit/checkpoint, source/frame/basis and placement evidence | [Independent map review](map-independent-review.md) |
| E | Thirteen materialized synthetic cases, hidden rubrics, exact input/skill/transcript evidence validation and pair-equivalence reporting | [Fixture and helper evidence](evaluations-evidence.md), [independent review](evaluation-navigation-independent-review.md) |
| F | Explicit straight segment/group comparisons, tentative structural differences, source-version links and immutable dashboard results | [Comparison](comparison-evidence.md) |
| G | Ten entrypoints (seven capabilities, two workflows and one alias), maintained routing guidance, bundled schemas/examples and evaluator exclusion | [Skills](skills-evidence.md), [packaged navigation](evaluation-navigation-independent-review.md) |

Independent reviews produced fixes before final acceptance: source strings and path overrides with invalid Unicode now return structured errors; diagnostic JavaScript avoids intermediate overflow and matches Python's ULP threshold; comparison tolerances cannot relax group collinearity, partial curve hints cannot become straight boundaries, and nonboundary calls cannot seed split suggestions. Partial preceding curve evidence also blocks positional claims while leaving an independently known selected vector comparable. Inspector calculation replay excludes optional comparison specifications when replaying without map/placement inputs. Evaluation records cannot score authentication-only/startup-only transcripts or count unrun sessions as an observed pair.

Parent integration RED/GREEN evidence:

- Public comparison/inspection facades: **1 failed, 27 passed** for missing public imports → **28 passed** after thin aliases; diagnostics/source facade identity is covered by the same suite.
- Advisory CLI: **8 passed**, including real commands, settings, exact request retention, read-only operations and new-output refusal.
- Review/plot replay: **41 passed** after adding retained original source name/input format and full deterministic audit replay; the new audit assertion first failed because replay omitted the audit payload.
- Independent comparison regressions: **9 failed, 25 passed** → **34 passed** for group eligibility, singleton flags and partial curves (one test initially expected schema rejection of a chord-bearing-only call; its correct contract is explicit unsupported comparison). A subsequent preceding-curve positional regression failed once → **43 passed** across comparison math, dashboard adapter and file output.
- Map evidence assertion first failed without frame/bearing-basis text → **40 HTML tests passed**. Final browser tests cover independent sliders/order/toggles/style reload and good fit with poor independent checkpoint evidence.

## Final local acceptance

| Gate | Observed result |
| --- | --- |
| `make check` | **1,562 passed, 15 skipped**, coverage **93.55%**; root Ruff, formatter and mypy passed. Skips are browser tests run separately below. |
| Combined models/verify/review/export/plugin suite | **1,004 passed, 23 skipped**. Browser/provider cases are opt-in; the later positional-prefix comparison change passed its separate 43-test affected suite. |
| `make test-dashboard-browser` | **15 passed**, zero skipped; Chromium, offline source selection, comparison and diagnostic scenarios/reset. |
| `make test-mapbox-browser` | **22 passed**, zero skipped; includes pinned SDK with a local style, raster controls and checkpoint evidence. No live provider credential was used. |
| Package Ruff | All checked package source/test files passed lint. Changed files formatted; two untouched baseline files (`mp_models/tract.py`, `test_standalone_map_handoff.py`) remain outside formatting cleanup scope. |
| New/integrated package typing | **15 source files passed**. Combined invocation disables only unused-ignore diagnostics because separately checked imported modules make existing import-untyped suppressions redundant. |
| Native behavior evaluation | **Not run**: both actual Claude attempts stopped before inference with expired OAuth. No paired scores or native skill-discovery success is claimed. |
| Live Mapbox / native client display | **Not run**; offline SDK/browser checks do not establish these gates. |

Root/full-package logs are retained under `/private/tmp/metesparser-final-{check,packages}.log`; browser log hashes are in the map-review evidence. The initial `make check` encountered four intentionally failing evaluator-review regressions still being implemented; the final result above supersedes that interim run. Sandbox-denied uv cache access and macOS runtime failures were retried through explicit escalation, not bypassed by moving caches.

Native attempt details, exact client/model initialization metadata, zero cost and transcript hashes are in [native evaluation availability](native-evaluation-availability.md). Todo 6 remains open. Local implementation, distribution acceptance and model/provider acceptance must be reported separately.

## Extracted distribution acceptance

Both built archives passed the final smoke run from working directories outside the checkout, using their extracted locked runtimes. Each ran 16 commands covering source validation, inspection, diagnosis, comparison, existing-output refusal, review, verification, plotting, relative analysis, composition, dashboard rendering, map rendering and Mapbox MCP preparation. Exit 1 for completed advisory results and exit 2 for existing-output errors were expected and verified.

Assertions verified read-only operations, exact diagnosis/comparison request retention, no verified exports from advisory commands, and positive vector rendering. The web-map archive additionally warped a synthetic raster. Mapbox MCP prepared a vector handoff and reported the raster omission; no external provider calls were made. Earlier attempts exposed smoke-driver fixture/setup errors; the fresh final run below supersedes them.

| Artifact | SHA-256 |
| --- | --- |
| `dist/metesparser-evidence-plugin.zip` | `98ce9dcd7d5df60d5eefb592faf7d281740f8b928b8a18fc8607d8cadd62992e` |
| `dist/metesparser-evidence-web-map-plugin.zip` | `3a6fb9d650335cce187a8ca953c33487dbc90a5ed5b5915342c891672931ab9f` |
| Final smoke report | `81c963ed3c3243c11bf9d9e169ec02759d23e21a0f634daabe8e85aca59a7632` |

Local report: `/private/tmp/metesparser-release-smoke-20261028/runs/final/results/run.json`. Driver: `/private/tmp/metesparser-release-smoke-20261028/scripts/run_smokes.py`. The report records **passed** for both archives, with 8 standard and 9 web-map assertions. These temporary files are local evidence, not bundled release assets. Both archives also contain all 11 new reference resources and 19 confined local links per the independent navigation review.

## Completion-audit follow-up

Three agents audited the original requirements in parallel: A/C source and inspection; B/D/F diagnostics, map controls and comparisons; E/G evaluations, skills and distribution. The audit found an omitted dashboard comparison adapter in inspection, empty stage-level reasons/dependencies, and restart guidance that chose a blocked dashboard before its failed comparison prerequisite. These were corrected through behavioral RED/GREEN regressions, with independent review of the final model, inspector and test hashes. Integrated comparison recovery now identifies the retained `dashboard/source.json` and regeneration through the dashboard producer into a new directory. It does not invent a standalone comparison request. See [inspection evidence](artifact-inspection-evidence.md).

The audit also added explicit tests for active malicious/long raster labels, disabled ordering endpoints, and forward/reversed many-to-one comparisons. These were GREEN coverage additions to existing behavior, not claimed production regressions. See [coverage evidence](coverage-audit-follow-up.md).

| Final gate after inspector changes | Observed result |
| --- | --- |
| `make check` | **1,562 passed, 15 skipped**, coverage **93.55%**; root lint, formatting and typing passed. |
| Combined package/plugin suite | **1,020 passed, 25 skipped**; full command unchanged from the plan. |
| `make test-mapbox-browser` | **24 passed**, zero skipped; includes new label and ordering coverage. |
| Dashboard browser | Earlier **15 passed** remains applicable: no dashboard renderer/browser changes followed that run. |
| Inspector focused suite and typing | **64 passed**; two changed modules passed mypy; final patch independently reviewed. |
| Both rebuilt extracted archives | **20/20 commands each**; **11/11 standard** and **12/12 web-map assertions**. |
| Worktree whitespace | `git diff --check` passed. No commit/push. |

The extended distribution smoke adds real integrated comparison production, intact comparison inspection, self-hash-consistent output tampering, and causal restart checks for both comparison and dashboard destinations. The final report is `/private/tmp/metesparser-release-smoke-20261028/runs/post-inspector-freeze-escalated/results/run.json`. A sandbox-denied preliminary run could not consume missing plot artifacts; the fresh escalated run is authoritative. No provider calls were made.

| Final artifact | SHA-256 |
| --- | --- |
| `dist/metesparser-evidence-plugin.zip` | `6f11b86f9da48d4a32643db32f10a90083f0a0460ba5eb7f8ecf206263f2bbbb` |
| `dist/metesparser-evidence-web-map-plugin.zip` | `36604c779b250137ed123cfcee20c118a4f218e00628c4bcd6384544613e3aec` |
| Extended smoke report | `65fd619374b41746bcfae83590d4356d270c06624f825ad6d41d4006295e0a3d` |
| `/private/tmp/metesparser-completion-audit-check.log` | `551190f4b3cbdddb07b002a403e89b647e27d08a01542f3b619bf9a4f9ebddad` |
| `/private/tmp/metesparser-completion-audit-packages.log` | `d740ac0be4e51b142b2151e2bd341f40500d89fedd871adcbb926e671e6989df` |
| `/private/tmp/metesparser-completion-audit-mapbox-browser.log` | `30662bb68b145dd75e28c5652cb09b6436e3a45253f9546dc6241ec4e33e2123` |

Completion remains unproven for observed paired model behavior, native document/client acceptance and live Mapbox. Fresh Claude availability checks again failed before inference with expired OAuth. Mapbox live preflight found no runtime public token. A separate no-model Codex investigation could not establish enforceable baseline isolation; it was not scored as a paired evaluation. These limits are recorded in [native/provider availability](native-evaluation-availability.md) and [Codex isolation availability](codex-evaluation-availability.md). Todo 6 stays open; no substitute acceptance or improvement score is claimed.

## Commit preparation

The user subsequently authorized a Git commit. `make pre-commit` passed with **1,562 tests passed, 15 skipped**, and **93.55%** coverage; log: `/private/tmp/metesparser-git-commit-precheck-escalated.log`. The initial sandbox run encountered uv's macOS system-configuration failure before linting; the explicitly escalated retry passed. Three bounded read-only reviews confirmed unchanged canonical verification/export gates, synthetic fixture scope, and matching packaged sources. Both archives byte-match all 53 packaged plugin files and all source files in their six runtime wheels; no rebuild is needed for this commit. Generated `.playwright-cli/` snapshots remain excluded. Publishing, pushing, and external acceptance are not part of this commit authorization.
