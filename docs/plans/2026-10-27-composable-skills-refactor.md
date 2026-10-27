# Composable skills refactor

Implemented against `0476a91` on `feat/deed-closure-dashboard-skill`. The objective is to make skills reusable at clear artifact boundaries while keeping geometry, source evidence, and verification distinct.

## Responsibility boundaries

| Skill | Responsibility | Output boundary |
| --- | --- | --- |
| `convert-document-to-text` | Native source reading | Transcription, page map, acquisition record |
| `extract-metes-and-bounds` | Select the requested complete description | Verbatim description, selection record |
| `verify-traverse` | Check supplied calls; route explicit relative analysis separately | Deterministic review or relative-analysis artifacts |
| `plot-metes-and-bounds` | Plot an identified call set | Preserved input, plot request, geometry, HTML, manifest |
| `prepare-parcel-overlay` | Import vector evidence or register a supplied scan | Prepared layer and provenance |
| `review-metes-and-bounds` | Compose missing source/selection/check stages | Requested review |
| `deed-closure-dashboard` | Compose reviewed sources and optional map evidence | Offline dashboard and staged artifacts |
| `review-deed` | Compatibility entrypoint | Delegate to shared review workflow |

Each capability stops at its requested deliverable. Workflows reuse unchanged, valid upstream artifacts and resume at the earliest invalid stage. The shared [handoff contract](../../plugins/metesparser/references/artifact-handoffs.md) owns these rules; skill entrypoints link to focused references instead of duplicating schemas or algorithms.

## Implementation

- `mp_models.plot_request`: immutable `PlotCall`, `PlotRequest`, and `PreparedPlot`. Source/page/occurrence references are optional actual evidence; generated row IDs make no document-reading claim. Unknown calls and bearings stay unresolved.
- `mp_verify.plot`: one geometry builder shared with dashboards, plus fresh standalone preparation/validation. Analytic arcs remain arcs; a missing or unsupported displacement stops the anchored prefix. Complete geometry can show provisional area and the endpoint gap without establishing verification.
- `mp_export.plot_svg`: shared SVG path and viewport helpers. `render_plot` provides a separate offline artifact with source selection and view-only controls. The existing dashboard uses the same helpers.
- `mp_review.plot` and `metes-review plot`: strict CSV, calls-list/LegalDescription JSON, explicit relative JSON, and PlotRequest JSON adapters. Only `auto` detects format. Existing output directories are refused. Original bytes and input/geometry/render hashes are retained.
- Root `metesparser.plot` delegates to package implementations. The plugin launcher exposes `plot`; wheel packaging includes the new assets without a new dependency or package.

Standalone outputs are `source.csv` or `source.json`, `plot-input.json`, `plot-geometry.json`, `plot.html`, and `plot-manifest.json`. A valid plot returns `needs_review` (exit 1), with verification/source-review/export flags false. `plot-input.json` can be plotted again directly. Plain selected descriptions need rule-based structuring first; the plot CLI does not accept prose or perform source selection.

Map preparation remains separate from deed placement. Documented composition copies supported layer arrays into a version 1.1 source bundle and retains the full preparation sidecar. It does not merge unsupported operation fields or fabricate page references. Dashboard geometry is recomputed under its own source/calculation identities; standalone hashes cannot authorize dashboard placements. Title-only changes preserve standalone geometry identity.

## Red–green and independent review

- New model, geometry, renderer, CLI, launcher and facade behavior tests failed before the corresponding APIs/commands existed. Parent CLI integration recorded 7 failures before routing was added.
- Review added regressions for explicit-format mismatch rejection, presentation-only geometry identity, and a small displacement lost at extreme coordinate magnitude. These failed before their fixes. The latter now returns partial geometry without a closure claim.
- Renderer regressions distinguish excluded tie-in calls from supported boundary geometry; incomplete traverses get no misleading closure annotation.
- An independent worker evaluated all eight skill entrypoints. Actual temporary executions covered CSV plotting, selected-transcript review, relative plotting, supplied overlay import, and overlay-to-dashboard composition. The exact documented composition snippet was executed successfully.
- The forward check found and fixed missing overlay-field mapping, stale standalone/dashboard hash guidance, installed-plugin command routing, and unclear plain-text plot preparation. Relative plotting retained unknown recorded bearings. Native Claude skill discovery or document reading was not simulated as a successful host evaluation.

## Validation

| Gate | Result |
| --- | --- |
| `make check UV_RUN='uv run --no-sync'` | Passed lint, formatting and root mypy; 1,496 tests passed, 12 browser tests skipped by default; 93.50% coverage. |
| Six deterministic package suites plus plugin tests | 878 passed with `--no-cov --import-mode=importlib`. |
| `make test-dashboard-browser UV_RUN='uv run --no-sync'` | 12 passed in actual Chromium, including standalone desktop/light and mobile/dark source selection and geometry-preserving controls. |
| Offline default and minimal plugin builds | Both built successfully; each ZIP's 34 plugin files and 61 wheel source/assets matched the workspace. |
| Isolated packaged-runtime composition | Both locked offline runtimes and actual plugin launchers passed CSV/JSON rectangles, relative and unresolved calls, the existing dashboard, and review → saved CSV → plot. Plot outputs retained five files, unknowns and exact source bytes; source review artifacts were unchanged. The minimal runtime required neither pyproj nor Pillow. |
| Skill/reference and source checks | All 8 skill validators, 98 local Markdown links, eval JSON, Ruff on 22 changed Python files, scoped strict mypy, and `git diff --check` passed. |
| Native Claude/Cowork source reading and host acceptance | Not run; remains todo item 6. Behavioral eval cases are specifications except for the local executions described above. |

The sandbox blocked Chromium process launch and uv's macOS system-configuration initialization. These gates passed after approved escalation. No provider requests or external publishing are needed for this refactor.

Builds are `dist/metesparser-plugin.zip` and `dist/metesparser-plugin-minimal.zip` (ignored generated artifacts). Diagnostic logs use `/tmp/metesparser-composable-*`; the isolated package report and retained smoke outputs are at `/private/var/folders/ny/sgsj847n58xbb1d4rxgbxzw80000gn/T/metesparser-package-validation-6l7rgcvo/report.json`. These temporary paths are local validation evidence, not tracked fixtures or portable dependencies.

## Delegation

GPT-6.1-sol workers owned the plot engine/adapters and renderer/browser tests. GPT-6-luna owned skill documentation and evaluation cases. The renderer worker independently checked skill composition; the documentation worker reviewed adapter boundaries. The parent integrated CLI/public facades, reviewed source changes and handoffs, and ran the broad checks. No commit or push is part of this refactor turn.
