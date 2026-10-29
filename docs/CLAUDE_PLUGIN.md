# Claude plugin and deterministic review

Shipped user documentation lives in the [plugin README](../plugins/metesparser/README.md), [usage guide](../plugins/metesparser/references/usage.md), and [plugin changelog](../plugins/metesparser/CHANGELOG.md). This document covers source-checkout development and packaging.

## Skills and engine commands

The plugin has seven capability skills, two composing workflows, and one compatibility alias. The [skill catalog](../plugins/metesparser/README.md#skills) is the inventory; the [artifact handoff contract](../plugins/metesparser/references/artifact-handoffs.md) defines accepted inputs, outputs, stopping points, status boundaries, and invalidation. Skills guide the agent's task selection and evidence handling. Python packages own schemas, parsing, geometry, and rendering; a skill is not a separate numerical implementation or a one-to-one wrapper for a CLI command.

`review-metes-and-bounds` coordinates conversion and description selection only when those stages are needed, then runs deterministic review. `review-deed` delegates to it. Existing calls can go directly to verification or plotting. Overlay preparation is independent of deed geometry. Dashboard composition reuses source and map evidence, maps it into a validated bundle, and recomputes geometry under the dashboard's identities. Assembly is explicit, and any requested placement requires a supplied transform; there is no automatic plot-to-dashboard adapter or deed-to-map alignment.

Supplementary runtime commands cover schema 1.1 source validation, read-only artifact freshness inspection, and requested straight-course closure diagnosis; they are helpers used by the skills, not additional skill entrypoints. The `compare-descriptions` capability accepts an explicit comparison request and returns advisory component/grouping results plus tentative structural differences. None replaces source review or promotes verification status; use the [plugin catalog and command guide](../plugins/metesparser/README.md) for exact invocations and limits. Evaluation case files define scenarios; they are not model-run evidence. Native Claude and live-provider acceptance remain separate gates.

## Dashboard development

For the source-grounded, editable closure review dashboard workflow, see the [Deed Closure Dashboard skill](../plugins/metesparser/skills/deed-closure-dashboard/README.md).

The dashboard accepts a validated version 1.0 deed-only bundle or a version 1.1 bundle with plot/map fields and renders a local offline HTML page:

```sh
uv run metes-review dashboard bundle.json --output-dir output/dashboard-new --cache-dir output/dashboard-cache
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" dashboard bundle.json --output-dir output/dashboard-new --cache-dir output/dashboard-cache
```

Use one command at a time and a fresh output directory. Valid bundles return top-level `needs_review` (exit 1); inspect the generated dashboard and JSON artifacts. `geometry_status` (`analyzed`, `unresolved`, `inconsistent`, `blocked`), canonical engine status, and source-review completeness are separate. Native reading, description selection, and the correctness of supplied review attestations remain outside the renderer. Relative calculations and all interactive scenario edits are advisory; no dashboard command writes verified CSV. The [bundle reference](../plugins/metesparser/skills/deed-closure-dashboard/references/dashboard-bundle.md) documents the schema, output files, legacy check-boolean compatibility, and cache invalidation. Explicit rigid placements and named-point residual comparisons are supported. Automatic boundary matching and browser edits to curves remain unsupported; the canonical baseline can calculate supported curves.

Follow the [composition example](../plugins/metesparser/skills/deed-closure-dashboard/references/dashboard-bundle.md#compose-existing-plot-and-map-artifacts) to populate a source bundle and append prepared layers using `compose-dashboard`. The command is available through the packaged launcher as well as `uv run metes-review`, retains exact input sidecars, and prints fresh geometry hashes. Required page and review records must come from actual evidence. A placement uses the freshly computed dashboard geometry hash, not a standalone plot's hash.

## Review and standalone plot development

The `mp-review` workspace package reviews the selected UTF-8 TXT/Markdown, CSV, or JSON without OCR, provider keys, or LLM calls. No new OCR service or conversion dependency is added. All parsing, numeric checks, and verified export decisions run in Python. Acquisition and section selection records remain separate from deterministic engine audits; see [source preparation](../plugins/metesparser/references/source-preparation.md).

```sh
uv sync --extra dev --extra gemini
uv run python -m mp_review review description.txt --output-dir output/review-new
uv run python -m mp_review verify calls.csv --output-dir output/verify-new
uv run python -m mp_review plot calls.csv --output-dir output/plot-new --input-format calls
uv run python -m mp_review plot description.txt --output-dir output/text-plot-new --input-format text
```

Choose the command for the requested deliverable; these are independent examples, not a mandatory sequence. Output directories must not exist. For review/verification, `--area SQFT` supplies a stated area for comparison; never substitute an inferred area. Verification JSON accepts a list of `DeedCall` objects or a `LegalDescription` object with `calls`. CSV input requires the complete ordered 21-column schema. Multiple named parcels are rejected for separate review.

The standalone plot command accepts structured inputs, or an already selected UTF-8 prose description with explicit `--input-format text`. The shared preparation used by review and plotting identifies commencement-to-POB tie-ins before boundary construction. Automatic detection does not parse prose. Plotting can display unresolved geometry and returns `needs_review`, with no canonical verification or verified CSV export. See the [handoff contract](../plugins/metesparser/references/artifact-handoffs.md) for its source copy, normalized input, geometry, HTML, and manifest artifacts. For optional vector import, raster registration, and explicitly requested parcel retrieval, use the [overlay preparation guide](../plugins/metesparser/skills/prepare-parcel-overlay/references/overlay-preparation.md).

The plugin launcher reads optional `.claude/metesparser.local.md` settings from the caller's project directory on each run. Supported fields are `enabled` (default true) and `output_dir` (a project-relative base for fresh review folders). Explicit CLI output takes precedence. Plain engine CLI calls opt in with `--settings PATH`. See [settings reference](../plugins/metesparser/references/plugin-settings.md) for validation and lifecycle details.

The CLI writes one JSON result to stdout and diagnostic logs to stderr. Review exits are 0 (`checks_passed`), 1 (`needs_review`), and 2 (`error`). Corpus exits are 0 (`passed`), 1 (`failed`), and 2 for invalid configuration. A review folder contains the original source, parsed calls, verification results, field-level audit, and escaped HTML report. Verified CSV is issued only when the existing verification and export gates pass. Source SHA-256 and deterministic execution metadata are recorded; no LLM extraction is implied.

## Maintain the skill composition

Keep each fact with its owning layer and link to it from other documents:

| Concern | Maintained location |
| --- | --- |
| Skill discovery and essential agent instructions | `plugins/metesparser/skills/<name>/SKILL.md` |
| Human-facing skill choice and examples | [Plugin catalog](../plugins/metesparser/README.md#skills), [usage guide](../plugins/metesparser/references/usage.md), and existing per-skill READMEs |
| Cross-skill inputs, outputs, status, reuse, and invalidation | [Artifact handoffs](../plugins/metesparser/references/artifact-handoffs.md) |
| Native reading and description-selection evidence | [Source preparation](../plugins/metesparser/references/source-preparation.md) |
| Authoritative schemas and command adapters | `packages/mp-models/src/mp_models/` and `packages/mp-review/src/mp_review/` |
| Shared parsing, numerical geometry, and rendering | `mp_parse`, `mp_bearing` / `mp_verify`, and `mp_export` |
| Dashboard assembly and placement | [Bundle contract and example](../plugins/metesparser/skills/deed-closure-dashboard/references/dashboard-bundle.md) and [plot/overlay reference](../plugins/metesparser/skills/deed-closure-dashboard/references/plot-and-overlays.md) |
| Mapbox local viewer and MCP delivery | [render-online-map references](../plugins/metesparser/skills/render-online-map/README.md#documentation) |
| Behavioral scenarios, model evaluation, and release notes | [Case catalog](../plugins/metesparser/evals/cases.json), [evaluation protocol](../plugins/metesparser/evals/README.md), and [plugin changelog](../plugins/metesparser/CHANGELOG.md) |

When changing or adding a skill:

1. Check whether an existing capability already owns the task. A reusable capability should have an independently useful output and a clear stopping point; a workflow chooses and composes capabilities. Keep compatibility aliases as delegates.
2. Keep discovery and essential constraints in `SKILL.md`; use a specific third-person description stating both the capability and when it applies. Keep the body under 500 lines, link required procedures directly, and add a contents list to references over 100 lines. Link runtime prerequisites rather than assuming tools are installed. Update the owning contract when a handoff changes, and update affected consumers and examples in the same change.
3. Reuse the Python APIs instead of copying parsing, closure, geometry, or rendering logic into skill prose. Keep the source-reading evidence, deterministic result, plot status, and map-registration result separate.
4. Define a realistic routing/composition evaluation before expanding instructions; reuse existing scenarios when they cover the change. Follow the [paired evaluation protocol](../plugins/metesparser/evals/README.md) to compare fresh baseline and with-skill sessions on each intended model. Validate changed links and command examples, and add an appropriate engine regression for runtime changes. Do not assert documentation wording as a substitute for behavior. Record what actually ran separately from scenario specifications and native-host acceptance.
5. Update the user-facing catalog or usage guide when routing changes, record user-visible changes in the plugin changelog, and rebuild the distribution before delivering it. Keep implementation plans as dated evidence rather than the primary usage guide.

These conventions follow [Anthropic's skill authoring guidance](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices). Keep precise commands and validation rules for fragile geometry/evidence operations; leave presentation choices flexible. For MCP calls, discover the exact fully qualified host tool identifier and inspect its live schema instead of guessing a server prefix.

## Validation

For documentation-only changes, check local links, schema/command claims, and examples that changed. Runtime changes also need the affected package and integration checks; `make pre-commit` remains required before committing. Useful focused checks from the repository root are:

```sh
uv run pytest plugins/metesparser/tests/ tests/unit/test_plugin_build.py --no-cov
uv run pytest packages/mp-review/tests/ --no-cov
make review-corpus
# When plot/dashboard browser behavior changes:
make test-dashboard-browser
```

The reviewed corpus lives in `packages/mp-review/tests/fixtures/corpus.json`. Expectations are explicit analytic values and behaviors; the runner compares them with tolerances and reports individual failures. Existing generated sample-deed ground truth is not treated as authoritative. Add reviewed cases with source provenance rather than copying actual output into expected values.

Native Claude/Cowork document reading and host acceptance need their own recorded runs. Local schema, engine, browser, and packaging checks do not establish them; use the [model evaluation protocol](../plugins/metesparser/evals/README.md) and see [pending evaluation work](todos.md#dashboard-skill-and-metes--bounds-checking-improvements-2026-10-26). Claude Haiku, Sonnet, and Opus coverage remains unrun until recorded separately for the actual model versions and client surfaces.

## Packaging and local installation

Run `make plugin-build` for the default distribution. To omit the optional geo dependencies, use `uv run python scripts/build_claude_plugin.py --without-geo --output dist/metesparser-plugin-minimal.zip`. The minimal runtime supports review and standalone plotting; operations requiring the geo extra report its absence. `--offline` uses cached build/runtime dependencies and fails if required dependencies are unavailable.

These are dependency profiles of the same plugin, with the same ten skills:

| Profile | Build option | Bundled geographic dependencies |
| --- | --- | --- |
| Standard | Default (`make plugin-build`) | `pyproj` and Pillow for geographic imports and scan preparation |
| Web-map | `--with-web-map` | Standard dependencies plus Rasterio and NumPy for online maps and raster reprojection |
| Minimal | `--without-geo` | No optional geographic dependencies; review and standalone plots remain available |

Choose the web-map profile for a deed plot over a registered tax scan and online
basemap. ZIP filenames can be changed with `--output`; multiple ZIPs in `dist/`
can therefore represent different profiles or previous builds. Use the archive
identified by its build/smoke-test evidence and SHA-256 sidecar. Building another
profile does not replace an installed Claude plugin or remove other archives.

`scripts/build_claude_plugin.py` builds six engine wheels from the current working tree, pins external runtime dependencies to root `uv.lock` versions, and creates `dist/metesparser-plugin.zip` plus a SHA-256 sidecar. The ZIP contains the manifest at its root, skills, references, a launcher, wheel hashes, and a separate runtime lock. Build artifacts include current uncommitted engine changes. Rebuild after changing engine or plugin files.

Extract the ZIP to a fresh directory. In Claude Code, use `claude --plugin-dir /absolute/path/to/extracted-plugin` for a local session. For Cowork, use its plugin upload interface with the built ZIP. No account installation or publication is performed by the build. The launcher requires Python 3.11+ and `uv`; first use downloads the pinned third-party runtime dependencies and creates a fingerprint-specific environment in the user's cache. The source plugin directory has no built runtime: use the extracted distribution for execution. The release is portable Python packaging, but OS-specific client acceptance must still be tested on each target.

Closure does not establish source completeness or legal correctness. Topology checks cover straight segments, line–arc contacts, and arc–arc contacts using finite circular sweeps rather than endpoint chords. Crossings, overlaps, and nonadjacent touches block verified export; legitimate neighboring endpoints are allowed. Unsupported curves such as spirals and incomplete circular geometry produce review warnings. Missing bearings remain unknown. The skills report these limitations and do not repair source data.

## Optional Mapbox renderer and distribution

The `render-online-map` capability owns an explicitly requested local Mapbox view or in-chat MCP preview; all ten skill entrypoints retain their independent scope. The dashboard workflow owns source/bundle assembly and delegates provider rendering. A map-only request does not require an offline dashboard. Follow the [online handoff](../plugins/metesparser/references/artifact-handoffs.md#optional-online-map-handoff) and [runtime/configuration procedure](../plugins/metesparser/skills/render-online-map/references/local-viewer.md). The default dashboard makes no external requests; the companion also makes none before explicit Connect.

An optional [Mapbox MCP handoff](../plugins/metesparser/skills/render-online-map/references/mapbox-mcp.md) adapts existing standalone online-map or legacy dashboard stages into vector-only `render_map_tool` arguments with provenance checks and a conservative 48 KiB limit. Use `mapbox-mcp EXISTING_MAP_DIR --output-dir NEW_DIR` through the launcher or `metes-review`. It does not repeat GIS preparation or carry raster/source pages. Before a requested external call, inspect the configured tool's live schema and send the exact generated arguments as the terminal visualization call. Hosted OAuth, schema compatibility, provider access, and visible native-client acceptance remain separate gates; local generation does not prove them. Connection setup and the pinned upstream contract are linked in the procedure.

Standalone rendering uses `render-map INPUT.json --online-map-config CONFIG.json --output-dir NEW_DIR`, followed by `serve-map NEW_DIR --port 8765`. `StandaloneWebMapInput` retains prepared plots and map arrays/placements; the adapter validates fresh shared geometry and placement identities. The [local viewer composition recipe](../plugins/metesparser/skills/render-online-map/references/local-viewer.md#compose-existing-artifacts) reuses existing plot and overlay outputs without building a dashboard. Output includes retained source/request, geographic artifact/manifest, `online-map.html`, `map-evidence.html` offline fallback, and optional warped rasters. It returns `needs_review`; no source-review or verification status is granted.

For a reproducible source-checkout test, use the [manual Mapbox smoke test](CONTRIBUTING.md#manual-mapbox-smoke-test). It prepares synthetic deed, parcel, and scan layers, then walks through Claude MCP authentication and the local three-layer viewer. The adjacent automated checks cover offline SDK behavior and a separate live-provider gate.

Build the optional runtime with `uv run python scripts/build_claude_plugin.py --with-web-map --output dist/metesparser-plugin-web-map.zip`. This implies geo support and rejects `--without-geo`; normal and no-geo distributions keep their offline behavior. Rebuild after renderer/assets/runtime changes. Preview is foreground loopback `serve-map`, with an advertised localhost URL and explicit port. Never package a provider token. Local contracts, adapter checks, SDK checks, live provider visual checks, extracted distribution checks, and native Claude/Cowork reachability are separate acceptance lanes; report unrun gates explicitly.
