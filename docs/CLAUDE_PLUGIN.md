# Claude plugin and deterministic review

Shipped user documentation lives in the [plugin README](../plugins/metesparser/README.md), [usage guide](../plugins/metesparser/references/usage.md), and [plugin changelog](../plugins/metesparser/CHANGELOG.md). This document covers source-checkout development and packaging.

## Skills, chat, Cowork and Claude Code

Skills describe reusable tasks and can include reference files and executable scripts. A plugin distributes related skills and their shared resources. Cowork and Claude Code are environments that can use them. Deterministic parsing, geometry and verification belong in the shared engine in every environment. Anthropic documents both [script-bearing custom skills](https://support.claude.com/en/articles/12512198-how-to-create-custom-skills) and [skills using Claude's code execution environment](https://support.claude.com/en/articles/12512180-use-skills-in-claude).

The following comparison separates platform capabilities from MetesParser integration status. Platform documentation was checked on 2026-10-29; account policies and available tools still determine a session's access.

| Work | Skills in Claude chat with code execution | Cowork | Claude Code |
| --- | --- | --- | --- |
| Read an uploaded deed and select its description | Possible with supported document reading | Same skill, with connected project files as inputs | Same skill when document reading is available |
| Parse, check closure, plot and compare | Possible when the shared engine and dependencies run in the session | Same engine; verify runtime provisioning | Same engine through the packaged launcher |
| Save revisions, construct corridors/PLSS geometry and export files | Possible with required inputs/dependencies; return downloadable artifacts | Convenient for multi-file projects and repeated work | Available through local project files and commands |
| Reopen local project folders and write results beside sources | Upload/download or a configured file integration | Direct local-file access through the connected desktop app | Local filesystem access under the client's permissions |
| Coordinate longer tasks and parallel subtasks | Depends on the chat surface and tools | Built-in task coordination and persistent projects | Agentic command/file workflow |
| Open an interactive dashboard or online map | Can generate files; embedded viewing and server reachability need testing | Browser access helps; runtime-to-browser reachability still needs testing | Local browser/loopback workflow is straightforward to exercise |

Claude chat already supports Python execution, file creation and package installation, subject to network policy. A skill therefore need not delegate numerical work to the language model. See [Claude code execution and file creation](https://support.claude.com/en/articles/12111783-create-and-edit-files-with-claude).

Cowork contributes file access and orchestration rather than new geometry algorithms. Current Anthropic documentation describes cloud execution, with local files and browser access reached through an open, connected Claude Desktop app. Installing Python or `uv` on a laptop does not establish their availability inside that execution environment. See [Cowork execution and requirements](https://support.claude.com/en/articles/13345190-get-started-with-claude-cowork).

Plugin skills are available across chat, Cowork and Claude Code; hooks, subagents and local MCP servers have narrower host support. MetesParser's current manifest declares none of those components. Optional Mapbox MCP preview uses an already configured connection. See [Anthropic's plugin host support](https://support.claude.com/en/articles/13837440-use-plugins-in-claude).

### What this distribution needs

The [plugin builder](../scripts/build_claude_plugin.py) packages thirteen skills, shared references, the [launcher](../plugins/metesparser/scripts/run-review.py), six engine wheels and a locked runtime. Plugin instructions call `${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py`; copying one skill directory leaves those shared resources behind. The [chat builder](../scripts/build_claude_skill.py) adapts those same procedures and runtime into a standalone Skill with its own setup wrapper.

Every target host needs:

- Access to the complete extracted plugin and a working plugin-root path.
- Python 3.11+, `uv`, writable output/cache directories and permission to execute the launcher.
- Network access to pinned dependencies on first use, or an already provisioned runtime/cache. The ZIP contains engine wheels, not every third-party wheel.
- Source documents plus native reading when needed; prepared text/calls can bypass that stage. The plugin does not require a separate LLM API key.
- Optional geographic/delivery dependencies and, for online viewing, the requested provider connection and a usable browser path.

### Functional gaps for Claude chat

This is a comparison of MetesParser's distributions and target environments, not a claim that every host integration has passed testing. The repository builds both a plugin ZIP and a standalone chat Skill ZIP. Native chat and Cowork acceptance are both pending.

| Function | Claude chat gap today | Cowork path | Work needed for chat |
| --- | --- | --- | --- |
| Install and run MetesParser | The standalone Skill packages paths and explicit dependency setup; actual chat installation/runtime acceptance is pending | Upload the existing plugin ZIP; provision its runtime in Cowork's execution environment | Test the built Skill in an actual chat session, including a cold dependency cache |
| Read a deed, retain exact excerpts and select a tract | No intended feature reduction; end-to-end native reading/evidence capture is untested | Same source-reading and selection skills | Test uploaded PDFs/images and source records; retain uncertainty |
| Parse calls, verify closure, compare, plot, construct corridors/PLSS and export | The same mathematical implementation is bundled; execution still depends on host provisioning | Same Python packages and input contracts | Validate native execution with the same checks; do not replace it with model calculations |
| Process a local folder or many deeds | Ordinary uploads/downloads do not provide direct access to the user's project folder | Desktop-mediated access to granted local files and task coordination | Accept uploaded inputs, return an explicit per-tract batch summary and a downloadable result bundle; test practical limits |
| Save and reopen revisions across work sessions | No tested project persistence or automatic artifact round trip in chat | Use retained project files and revision commands; reopen behavior still needs native testing | Return the complete revision and source evidence together, then validate it when reuploaded; never depend on a surviving chat cache |
| Edit a dashboard or pick raster controls | HTML can be generated, but scripts, downloads and embedded interaction are not proven in chat | Open the generated page in an accessible browser; host interaction still needs testing | Support an external-browser download/edit/reupload path and test it; in-chat interactive parity remains an open integration task |
| View Mapbox layers or an MCP preview | A generated localhost URL may be unreachable from the user's browser; a compatible connector is not guaranteed | Cloud-to-browser reachability and an authenticated provider connection are also required | Test an accessible viewer path or supported remote MCP connection; keep offline plot/evidence downloads useful |
| Run long tasks, parallel agents or scheduled work | A Skill alone supplies none of those host services | Cowork supplies task coordination and scheduling; MetesParser currently bundles no subagents, hooks or schedules | Keep chat workflows bounded and resumable through saved artifacts; use Cowork for the richer host workflow |

The file-access and orchestration differences follow [Cowork's documented capabilities](https://support.claude.com/en/articles/13345190-get-started-with-claude-cowork). The distinction between executable chat skills and host-specific plugin components follows [Claude's skill format](https://support.claude.com/en/articles/12512198-how-to-create-custom-skills) and [plugin support](https://support.claude.com/en/articles/13837440-use-plugins-in-claude). The packaging, viewer and persistence gaps above are our integration assessment, based on the current launcher and unrun native tests.

### Two distributions, one engine

For users without Cowork, the chat distribution is one self-contained Skill ZIP with a root dispatcher, the relevant workflow references and the same deterministic engine. It operates on uploaded documents or prepared inputs and instructs Claude to return downloadable reports, plots, revisions and delivery bundles. The build adapter reuses authoritative capability instructions and one runtime. A custom Skill ZIP has a different layout from a plugin ZIP, so renaming the plugin archive is insufficient.

The existing plugin ZIP retains thirteen discoverable entrypoints and shared resources. Anthropic supports plugins in chat, Cowork and Claude Code; MetesParser's launcher/runtime flow has been exercised locally, while native-host tests remain pending. The separate Skill ZIP offers a chat-focused installation option without requiring Cowork. Cowork executes in the cloud, so validate tools, writable storage and dependency access there. Neither distribution should silently use laptop credentials, rely on an inherited `.env`, or claim that a laptop installation provisions Cowork.

These are distribution and host adaptations, not separate numerical implementations. Both retain deterministic-first behavior, exact source evidence, unknown bearings, revision identities and the same verified-export eligibility rules. The chat archive is built from source separately from the plugin release asset.

Acceptance for each distribution must include a clean install in the actual host, skill discovery, dependency provisioning, a sample deed, a deterministic plot/report, revision save/reopen and retrievable deliverables. Test interactive HTML and online maps separately. Local extracted-runtime tests have passed; native-host acceptance is still pending in the [evidence ledger](implementation/2026-10-28-cowork-workflow-ledger.md).

## Skills and engine commands

The plugin has ten capability skills, two composing workflows, and one compatibility alias. The [skill catalog](../plugins/metesparser/README.md#skills) is the inventory; the [artifact handoff contract](../plugins/metesparser/references/artifact-handoffs.md) defines accepted inputs, outputs, stopping points, status boundaries, and invalidation. Skills guide the agent's task selection and evidence handling. Python packages own schemas, parsing, geometry, and rendering; a skill is not a separate numerical implementation or a one-to-one wrapper for a CLI command.

`review-metes-and-bounds` coordinates conversion and description selection only when those stages are needed, then runs deterministic review. `review-deed` delegates to it. Existing calls can go directly to verification or plotting. Overlay preparation is independent of deed geometry. Dashboard composition reuses source and map evidence, maps it into a validated bundle, and recomputes geometry under the dashboard's identities. Assembly is explicit, and any requested placement requires a supplied transform; there is no automatic plot-to-dashboard adapter or deed-to-map alignment.

Supplementary runtime commands support schema 1.1 source validation, read-only artifact freshness inspection, closure diagnosis, saved revision publication/replay, corridor construction, supplied-reference PLSS derivation, raster registration/picking, and revision-bound delivery. They are helpers used by the thirteen skill entrypoints, not additional skills. The `compare-descriptions` capability accepts an explicit comparison request and returns advisory component/grouping results plus tentative structural differences. None replaces source review or promotes verification status; use the [plugin catalog and command guide](../plugins/metesparser/README.md) for routing and limits, and the [revision reference](../plugins/metesparser/references/revisions.md) for publication and delivery contracts. Evaluation case files define scenarios; they are not model-run evidence. Native Claude/Cowork and live-provider acceptance remain separate gates.

## Dashboard development

For the source-grounded, editable closure review dashboard workflow, see the [Deed Closure Dashboard skill](../plugins/metesparser/skills/deed-closure-dashboard/README.md).

The dashboard accepts a validated version 1.0 deed-only bundle or a version 1.1 bundle with plot/map fields and renders a local offline HTML page:

```sh
uv run metes-review dashboard bundle.json --output-dir output/dashboard-new --cache-dir output/dashboard-cache
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" dashboard bundle.json --output-dir output/dashboard-new --cache-dir output/dashboard-cache
```

Use one command at a time and a fresh output directory. Valid bundles return top-level `needs_review` (exit 1); inspect the generated dashboard and JSON artifacts. `geometry_status` (`analyzed`, `unresolved`, `inconsistent`, `blocked`), canonical engine status, and source-review completeness are separate. Native reading, description selection, and the correctness of supplied review attestations remain outside the renderer. Relative calculations and all interactive scenario edits are advisory; no dashboard command writes verified CSV. The [bundle reference](../plugins/metesparser/skills/deed-closure-dashboard/references/dashboard-bundle.md) documents the schema, output files, legacy check-boolean compatibility, and cache invalidation. Explicit rigid placements and named-point residual comparisons are supported. Automatic boundary matching remains unsupported. The browser retains structured line/arc drafts; `save-revision` and `render-revision` use shared geometry for fresh views. The immediate browser calculator remains straight-only.

Follow the [composition example](../plugins/metesparser/skills/deed-closure-dashboard/references/dashboard-bundle.md#compose-existing-plot-and-map-artifacts) to populate a source bundle and append prepared layers using `compose-dashboard`. The command is available through the packaged launcher as well as `uv run metes-review`, retains exact input sidecars, and prints fresh geometry hashes. Required page and review records must come from actual evidence. A placement uses the freshly computed dashboard geometry hash, not a standalone plot's hash.

### Saved revisions and derived sources

Use `revision-template` only when no dashboard draft was downloaded, then publish with `save-revision`; `inspect-revision` replays a published revision, while `render-revision` writes a new view. These commands retain recoverable raw drafts and separate current geometry from any last-valid parent geometry. They do not run canonical verification or grant verified-export eligibility. For the full command sequence and immutable publication rules, see [saved alternatives and source corrections](../plugins/metesparser/references/revisions.md).

Schema 1.2 revisions can retain exact corridor request JSON and explicitly remove prior corridors. Reopening recomputes a retained corridor from its request; delivery binds the revision manifest, corridor input and boundary geometry hashes and uses that fresh result directly. Standalone corridor artifacts remain a separate source path. Source-correction sidecars preserve supplied supporting excerpts and fresh calls, not native acquisition records or proof of complete source selection. When a new full selection is needed, use the actual source-reading workflow.

The [corridor capability](../plugins/metesparser/skills/plot-corridor/SKILL.md), [PLSS capability](../plugins/metesparser/skills/plot-plss-reference/SKILL.md), and [delivery capability](../plugins/metesparser/skills/export-review-package/SKILL.md) document their supported inputs and stopping points. PLSS derivation requires a supplied, identified reference dataset and supported rectangular rule; a recital does not provide missing section geometry. Delivery exports an explicitly selected published revision and remains a presentation artifact, not a verification result.

For a guided pixel-control workflow, `pick-raster IMAGE --controls CONTROLS.json --output-dir NEW_DIR` produces a downloadable control file for `register-raster`. The [overlay preparation reference](../plugins/metesparser/skills/prepare-parcel-overlay/references/overlay-preparation.md#optional-native-pixel-control-picker) explains prerequisites and limits. Picker points aid raster registration; deed placement remains a separate explicit operation.

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

Native Claude/Cowork document reading, paired model evaluations, and host acceptance need their own recorded runs. The current [Cowork workflow ledger](implementation/2026-10-28-cowork-workflow-ledger.md) records local implementation complete and native acceptance not run, including current access evidence. Local schema, engine, browser, and packaging checks do not establish those gates; use the [model evaluation protocol](../plugins/metesparser/evals/README.md) for future recorded paired sessions.

## Packaging and local installation

### Standalone Claude chat Skill

Run `make chat-skill-build` to produce `dist/metesparser-chat-skill.zip` and its SHA-256 sidecar. Verify with `shasum -a 256 -c metesparser-chat-skill.zip.sha256` from `dist/`, then upload the ZIP through Claude's Skills interface. The archive contains a `metesparser-review/` root with exactly one `SKILL.md`; thirteen embedded `WORKFLOW.md` procedures reuse the plugin's contracts and examples. It includes no plugin manifest, evaluator rubrics or repository checkout dependency.

The [chat templates](../plugins/metesparser-chat/README.md) own host-specific instructions. The builder adapts procedure paths to an explicitly located skill root and `scripts/run-chat.py`, retaining the original review launcher and engine bytes. Source templates contain links to resources added during packaging; validate navigation in the extracted archive.

The chat wrapper's `--setup` checks runtime hashes, uses host/cached `uv` when available, or fetches the pinned `uv` 0.9.6 wheel into the host's writable cache. Both wheel and executable hashes are pinned in [bootstrap metadata](../plugins/metesparser-chat/references/uv-bootstrap.json). Bootstrap downloads support Linux and macOS on x86_64/ARM64; other hosts need a compatible `uv` already on `PATH`. Setup then provisions the shared locked runtime. `--setup --offline` requires existing tools and cached dependencies. Ordinary invocations never install the bootstrap tool; the shared launcher can still provision locked engine dependencies on demand. Python 3.11+ is required before setup, and caches can be placed under a writable `XDG_CACHE_HOME`.

Dependency profiles match the plugin: `uv run python scripts/build_claude_skill.py --without-geo --output dist/metesparser-chat-minimal.zip` omits geo dependencies, while `--with-web-map` adds raster reprojection. All profiles retain delivery support and the same procedures. The ZIP contains engine wheels, not all third-party wheels; a complete first-use offline installation is not promised.

Run `uv run pytest tests/unit/test_chat_skill_build.py tests/unit/test_chat_runtime.py --no-cov` for packaging and setup regressions. Test the extracted distribution with an empty cache, no plugin-root variable and no `uv` on `PATH`, then run prepared-input review/plot and revision round trips. These local checks are separate from uploading and exercising the Skill in Claude chat.

The [chat distribution validation record](implementation/2026-10-29-claude-chat-skill.md) records the built archive hash, cold-cache setup, offline operations and remaining native-host checks.

### Claude plugin

Run `make plugin-build` for the default distribution. To omit the optional geo dependencies, use `uv run python scripts/build_claude_plugin.py --without-geo --output dist/metesparser-plugin-minimal.zip`. The minimal runtime supports review and standalone plotting; operations requiring the geo extra report its absence. `--offline` uses cached build/runtime dependencies and fails if required dependencies are unavailable.

These are dependency profiles of the same plugin, with the same thirteen skills:

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
All profiles include the delivery extra; the standard profile also includes the
geo extra, while `--without-geo` omits it. The web-map extra adds Rasterio and
NumPy on top of geo support. Consult each capability's reference for the exact
prerequisite of a requested operation.

`scripts/build_claude_plugin.py` builds six engine wheels from the current working tree, pins external runtime dependencies to root `uv.lock` versions, and creates `dist/metesparser-plugin.zip` plus a SHA-256 sidecar. The ZIP contains the manifest at its root, skills, references, a launcher, wheel hashes, and a separate runtime lock. Build artifacts include current uncommitted engine changes. Rebuild after changing engine or plugin files.

Extract the ZIP to a fresh directory. In Claude Code, use `claude --plugin-dir /absolute/path/to/extracted-plugin` for a local session. For Cowork, use its plugin upload interface with the built ZIP. No account installation or publication is performed by the build. The launcher requires Python 3.11+ and `uv`; first use downloads the pinned third-party runtime dependencies and creates a fingerprint-specific environment in the user's cache. The source plugin directory has no built runtime: use the extracted distribution for execution. The release is portable Python packaging, but OS-specific client acceptance must still be tested on each target.

Closure does not establish source completeness or legal correctness. Topology checks cover straight segments, line–arc contacts, and arc–arc contacts using finite circular sweeps rather than endpoint chords. Crossings, overlaps, and nonadjacent touches block verified export; legitimate neighboring endpoints are allowed. Unsupported curves such as spirals and incomplete circular geometry produce review warnings. Missing bearings remain unknown. The skills report these limitations and do not repair source data.

## Optional Mapbox renderer and distribution

The `render-online-map` capability owns an explicitly requested local Mapbox view or in-chat MCP preview; all thirteen skill entrypoints retain their independent scope. The dashboard workflow owns source/bundle assembly and delegates provider rendering. A map-only request does not require an offline dashboard. Follow the [online handoff](../plugins/metesparser/references/artifact-handoffs.md#optional-online-map-handoff) and [runtime/configuration procedure](../plugins/metesparser/skills/render-online-map/references/local-viewer.md). The default dashboard makes no external requests; the companion also makes none before explicit Connect.

An optional [Mapbox MCP handoff](../plugins/metesparser/skills/render-online-map/references/mapbox-mcp.md) adapts existing standalone online-map or legacy dashboard stages into vector-only `render_map_tool` arguments with provenance checks and a conservative 48 KiB limit. Use `mapbox-mcp EXISTING_MAP_DIR --output-dir NEW_DIR` through the launcher or `metes-review`. It does not repeat GIS preparation or carry raster/source pages. Before a requested external call, inspect the configured tool's live schema and send the exact generated arguments as the terminal visualization call. Hosted OAuth, schema compatibility, provider access, and visible native-client acceptance remain separate gates; local generation does not prove them. Connection setup and the pinned upstream contract are linked in the procedure.

Standalone rendering uses `render-map INPUT.json --online-map-config CONFIG.json --output-dir NEW_DIR`, followed by `serve-map NEW_DIR --port 8765`. `StandaloneWebMapInput` retains prepared plots and map arrays/placements; the adapter validates fresh shared geometry and placement identities. The [local viewer composition recipe](../plugins/metesparser/skills/render-online-map/references/local-viewer.md#compose-existing-artifacts) reuses existing plot and overlay outputs without building a dashboard. Output includes retained source/request, geographic artifact/manifest, `online-map.html`, `map-evidence.html` offline fallback, and optional warped rasters. It returns `needs_review`; no source-review or verification status is granted.

For a reproducible source-checkout test, use the [manual Mapbox smoke test](CONTRIBUTING.md#manual-mapbox-smoke-test). It prepares synthetic deed, parcel, and scan layers, then walks through Claude MCP authentication and the local three-layer viewer. The adjacent automated checks cover offline SDK behavior and a separate live-provider gate.

Build the optional runtime with `uv run python scripts/build_claude_plugin.py --with-web-map --output dist/metesparser-plugin-web-map.zip`. This implies geo support and rejects `--without-geo`; normal and no-geo distributions keep their offline behavior. Rebuild after renderer/assets/runtime changes. Preview is foreground loopback `serve-map`, with an advertised localhost URL and explicit port. Never package a provider token. Local contracts, adapter checks, SDK checks, live provider visual checks, extracted distribution checks, and native Claude/Cowork reachability are separate acceptance lanes; report unrun gates explicitly.
