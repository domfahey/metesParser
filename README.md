# MetesParser

A Claude plugin for reviewing metes-and-bounds descriptions, backed by deterministic parsing, geometry, verification and export tools.

Use it to locate a boundary description in a deed, inspect its calls, check closure, create a plot, compare versions and prepare review deliverables. The same Python engine is available through a CLI and independently installable packages.

[Get the plugin](https://github.com/domfahey/metesParser/releases) · [Chat Skill installation](#install-the-standalone-claude-chat-skill) · [Skill catalog](plugins/metesparser/README.md#skills) · [Usage guide](plugins/metesparser/references/usage.md) · [Changelog](CHANGELOG.md)

> **Proof of concept (POC).** MetesParser explores source-traceable boundary review with Claude and deterministic tools. Review source readings and results before relying on them.

## Deterministic code first

Use deterministic code wherever possible, and AI only where needed. Claude assists with reading documents, identifying the requested description and coordinating the requested workflow. Shared Python code parses calls, computes geometry, checks evidence and validates exports.

AI-prepared text and selections retain their source pages, exact spans and unresolved readings. Deterministic checks then validate structure, identities, geometry and artifact consistency. They can expose inconsistencies; they cannot prove that an AI reading faithfully captured the document. Source review remains a separate step.

```text
Document → AI reading/selection when needed → retained text and source evidence
                                                    ↓
Prepared text or calls ────────────────────→ deterministic parsing and checks
                                                    ↓
                                          review, plots and exports
```

Missing bearings stay unknown. Original deed wording is preserved. Hypothetical edits remain separate from recorded calls, and no workflow changes a value simply to make a boundary close.

## What you can ask Claude to do

| Request | Result |
| --- | --- |
| “Review the boundary description in this deed.” | Selected description, source coverage, structured calls, deterministic checks and an audit report |
| “Plot these calls.” | An offline plot with source references and unresolved geometry identified |
| “Compare these two descriptions.” | Explicit line/arc comparisons and tentative structural differences |
| “Show a dashboard for these tracts.” | An explicitly assembled offline review dashboard with independent tract outcomes |
| “Save this alternative and export the selected revision.” | An immutable revision and requested SVG, PDF, DXF or GeoJSON deliverables |
| “Register this scan using these controls.” | Retained image/control evidence and separate fit/checkpoint residuals |
| “Construct this corridor” or “derive this supplied PLSS reference.” | Advisory geometry from explicit construction inputs or an identified reference dataset |

The plugin has ten capabilities, two workflows and the `review-deed` compatibility alias. Skills reuse valid artifacts and stop at the requested deliverable. A plot request does not automatically create a dashboard, verify a traverse or place it on a map. See the [catalog](plugins/metesparser/README.md#skills) for exact scope and examples.

### Skills, Cowork and Claude Code

Skills can contain instructions, references and executable code. Our plugin packages those skills with one shared deterministic engine. Cowork adds convenient project-file access and task coordination; the calculations do not depend on Cowork. Claude Code is another host for the same plugin.

Claude chat supports skill scripts in its code-execution environment. The standalone chat Skill ZIP reuses the same engine and returns downloadable results, without requiring Cowork. Native chat testing is pending. Individual plugin skill folders are not standalone installations. See the [chat functionality gaps](docs/CLAUDE_PLUGIN.md#functional-gaps-for-claude-chat) and [two-distribution design](docs/CLAUDE_PLUGIN.md#two-distributions-one-engine).

## Install the standalone Claude chat Skill

From a source checkout, run `make chat-skill-build`. This creates `dist/metesparser-chat-skill.zip` and its `.sha256` sidecar. Verify the checksum, then upload the ZIP through **Customize → Skills** and enable code execution. The archive contains one discoverable `metesparser-review` skill with thirteen embedded procedures and one shared engine.

The skill's explicit setup command checks the chat runtime and can install a pinned, hash-checked `uv` in its writable cache before provisioning locked dependencies. It requires Python 3.11+ and first-use network access unless tools and dependencies are already cached. It does not rely on laptop installations. See the [chat installation guide](plugins/metesparser-chat/README.md) and [build profiles](docs/CLAUDE_PLUGIN.md#standalone-claude-chat-skill).

## Install the Claude plugin

The launcher requires **Python 3.11+** and **[uv](https://docs.astral.sh/uv/)** in the environment where Claude runs commands. First use provisions pinned dependencies in the local cache and requires network access unless they are already cached.

1. Download `metesparser-plugin.zip` and `metesparser-plugin.zip.sha256` from [GitHub Releases](https://github.com/domfahey/metesParser/releases).
2. Verify the archive from the directory containing both files:

   ```sh
   shasum -a 256 -c metesparser-plugin.zip.sha256
   ```

3. Load it in your client:
   - **Claude Code:** extract the archive, then run `claude --plugin-dir /absolute/path/to/extracted-plugin`.
   - **Claude Cowork:** upload the ZIP through Customize → Plugins. End-to-end host testing is pending.
4. Supply a document or prepared calls and ask for the specific result you need.

Use the built distribution: `plugins/metesparser/` in a source checkout does not contain its bundled runtime. The standard ZIP includes geographic preparation and delivery dependencies. Online raster reprojection uses the optional web-map profile. See [installation and build profiles](docs/CLAUDE_PLUGIN.md#packaging-and-local-installation) and [project settings](plugins/metesparser/references/plugin-settings.md).

For example:

> Plot the requested tract in this deed. Preserve missing or uncertain readings and show any unresolved geometry.

Native document reading must be available in the current Claude session. The plugin reports unavailable or unreadable sources rather than silently substituting a provider.

## Outputs and verification

Depending on the requested task, outputs include:

- Source acquisition and selection records with page coverage, byte identities and uncertainty.
- Structured calls, check outcomes and an escaped HTML review report.
- Standalone plots, dashboards and their retained inputs and manifests.
- Exact draft inputs, published revisions and explicit current/last-valid geometry.
- Review packages with selected layers, transforms, units, provenance and format omissions.

The deterministic `metes-review` commands report these top-level statuses:

| Status | Exit code | Meaning |
| --- | --- | --- |
| `checks_passed` | `0` | Applicable implemented canonical checks passed; source accuracy is a separate assessment |
| `needs_review` | `1` | Review is needed, or an advisory operation completed; successful plots and comparisons also use this status |
| `error` | `2` | Invalid input, configuration or processing failure |

Verified CSV uses the ordered 22-field schema (`curve_type` is the last column; legacy 21-field CSVs still import). Its exporter freshly checks the selected calls, including closure below 0.01 ft, eligible canonical outcomes and no warnings. Closure alone is insufficient. Plots, comparisons, scenarios, corridors, PLSS references and map views cannot grant verified-export eligibility. A deed with more than one description is eligible only when every description's role comes from an explicit heading (such as `PARCEL ONE:` or `TRACT 2:`) with no exception, easement or reservation wording in the heading or the text introducing it; a heading like `PARCEL B (ACCESS EASEMENT)` or `LESS PARCEL B:` still counts as an inferred role. Easement and exception tracts are never eligible, and text review asks for one parcel per review.

Read the [artifact handoff contract](plugins/metesparser/references/artifact-handoffs.md) for file shapes, reuse and invalidation, and the [review limits](plugins/metesparser/references/review-limits.md) for supported checks.

## Maps and derived geometry

Map evidence requires explicit units, coordinate systems and placement evidence. Raster registration does not locate a deed, and a good fit residual does not establish independent accuracy. PLSS geometry requires an identified supplied reference; a recital alone cannot supply missing section corners.

Optional Mapbox viewing supports a local viewer and a requested vector MCP preview. The local viewer accepts a token only in its runtime Connect field; tokens do not belong in configuration or generated artifacts. See the [online-map guide](plugins/metesparser/skills/render-online-map/README.md) for dependencies, geographic prerequisites and separate provider acceptance checks.

## Use the Python engine or CLI

The CLI is useful for automation, prepared inputs and testing without a Claude session. Deterministic review commands need no LLM API key. The separate PDF extraction pipeline can call OpenAI or Gemini.

### Set up a source checkout

Install Python 3.11+, uv, Git and Make, then:

```sh
git clone https://github.com/domfahey/metesParser.git
cd metesParser
make dev-setup
make review-corpus
```

`make dev-setup` installs dependencies and creates `.env` from the sample when absent. `make review-corpus` runs the reviewed deterministic fixtures without OCR or provider calls.

### Review prepared input

Use an already selected UTF-8 description or identified JSON/CSV calls. These are independent examples; supply the named inputs and use a new output directory each time:

```sh
uv run metes-review review description.txt --output-dir output/review-new
uv run metes-review verify calls.json --output-dir output/verification-new
uv run metes-review plot calls.json --output-dir output/plot-new
```

Inspect the JSON status and artifacts. Advisory success uses exit 1, so do not chain these commands with `&&`. Whole-document text needs description selection before parsing. The [usage guide](plugins/metesparser/references/usage.md) covers revision, delivery, comparison and resume commands.

### Extract a PDF with a provider

Set `METESPARSER_LLM_PROVIDER` and the corresponding `OPENAI_API_KEY` or `GEMINI_API_KEY` in your local `.env`, then:

```sh
uv run metesparser extract deed.pdf
# Or select Gemini explicitly, with GEMINI_API_KEY configured:
uv run metesparser extract deed.pdf --llm-provider gemini
```

Provider extraction remains subject to source review and deterministic checks. Never commit credentials. The [architecture guide](docs/ARCHITECTURE.md) documents the Python `Pipeline` API and its compatibility layer.

## Architecture

The plugin supplies instructions and workflow routing. Shared packages own the computations and artifact contracts:

| Location | Responsibility |
| --- | --- |
| `plugins/metesparser/` | Claude skills, shared procedures and the bundled-runtime launcher |
| `plugins/metesparser-chat/` | Standalone chat dispatcher, host setup wrapper and download guidance |
| `packages/mp-models/` | Schemas, source identities, units and artifact contracts |
| `packages/mp-bearing/`, `packages/mp-parse/` | Bearing math and rule-based parsing |
| `packages/mp-verify/` | Canonical checks and advisory geometry/analysis |
| `packages/mp-export/` | CSV, HTML, drawing and GIS/CAD serialization |
| `packages/mp-review/` | File/CLI adapters, replay, revisions and workflow artifacts |
| `packages/mp-ocr/` | Provider-backed PDF extraction; the only `mp-*` package that calls LLMs |
| `src/metesparser/` | Python orchestrator, CLI and compatibility modules |

The seven `mp-*` packages and root package form a uv workspace. The compatibility monolith also retains provider clients; native Claude reading is a separate source-preparation path. See [architecture and data flow](docs/ARCHITECTURE.md) for dependencies and module ownership.

## Develop and contribute

Use uv for dependencies and Ruff for linting/formatting. Keep schema, math and rendering logic in their owning packages; keep compatibility implementations synchronized where they exist.

```sh
make check          # Root lint, formatting, mypy and tests
make pre-commit     # Required before commits; runs lint-fix, formatting and root tests
make plugin-build   # Build dist/metesparser-plugin.zip and its SHA-256 sidecar
make chat-skill-build # Build dist/metesparser-chat-skill.zip and its SHA-256 sidecar
```

Package/plugin tests, browser checks and native/provider acceptance are separate lanes. Use the [testing guide](docs/TESTING.md) for commands and prerequisites, and the [contribution guide](docs/CONTRIBUTING.md) for changes and pull requests. Repository-specific agent instructions live in [AGENTS.md](AGENTS.md); `CLAUDE.md` is its symlink.

Keep only publicly available source data in the repository. Do not commit credentials, non-public sensitive information or newly generated unverified CSVs. Preserve source wording and uncertainty rather than inventing missing data.

## Documentation

- [Plugin catalog and usage](plugins/metesparser/README.md)
- [Plugin development and installation](docs/CLAUDE_PLUGIN.md)
- [Implementation plans](docs/plans/README.md) and [historical extraction outputs](docs/archive/extraction-output/README.md)
- [Architecture](docs/ARCHITECTURE.md) and [testing](docs/TESTING.md)
- [Project changelog](CHANGELOG.md) and [plugin changelog](plugins/metesparser/CHANGELOG.md)
- [Workflow implementation evidence](docs/implementation/2026-10-28-cowork-workflow-ledger.md) and [chat distribution validation](docs/implementation/2026-10-29-claude-chat-skill.md), including outstanding host checks

## License

MIT.
