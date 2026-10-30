# AGENTS.md

This file provides guidance to AI coding agents (Claude Code, Codex, etc.) working in this repository.

## Project: Metes & Bounds Deed Parser

MetesParser is a Claude plugin and shared Python engine for source-traceable metes-and-bounds review, plotting and exports. The CLI and composable packages also support automation without a Claude session.

Use deterministic code wherever possible, AI only where needed, and deterministic validation of AI-prepared inputs wherever applicable. Keep source review distinct from computational checks.

Versions are declared in each package's `pyproject.toml` (root `metesparser`: 0.6.0; `mp-*`: 1.0.0). Test counts and coverage depend on the selected suite; consult the [workflow evidence](docs/implementation/2026-10-28-cowork-workflow-ledger.md) and [chat distribution validation](docs/implementation/2026-10-29-claude-chat-skill.md), not a fixed count in this guide.

**Further reading:** [ARCHITECTURE.md](docs/ARCHITECTURE.md) (packages, data flow, module mapping) · [DEVELOPER_REFERENCE.md](docs/DEVELOPER_REFERENCE.md) (CLI commands, Makefile targets, CSV schema, units, feature table) · [TESTING.md](docs/TESTING.md) · [CLAUDE_PLUGIN.md](docs/CLAUDE_PLUGIN.md)

## Critical Architecture Principles

### 1. Never Fabricate Data
**Most Important Rule**: If a bearing is incomplete (e.g., "southwesterly" without degrees), leave `bearing_azimuth_deg_from_north` as `None` and set `notes="incomplete bearing - cardinal only"`. Never invent numerical bearings.

### 2. Verification Before Export
Use `verify_closure()` before `export_verified_csv()`. Geometry eligibility requires closure below 0.01 ft, applicable checks passing (explicit `not_applicable` is distinct from `passed`), and no warnings; failed or blocked checks prevent eligibility. The exporter freshly verifies the selected calls and validates the supplied result against them. `source_review_status` remains an explicit, separate assessment; geometry eligibility does not establish source completeness or legal validity.

### 3. Preserve Verbatim Deed Language
Keep original wording in `along` and `to` fields. Example: Keep "Southerly line of Pennbrook Drive" exactly as written in the deed.

### 4. GenAI Transparency & Auditability
All LLM-generated outputs must be traceable and auditable — log prompts, responses, and extraction decisions so users can verify what the AI produced vs. what the parser derived deterministically. Within the composable packages, only `mp-ocr` calls LLMs; downstream packages are deterministic. The compatibility monolith also retains provider clients in `src/metesparser/llm_clients.py`.

## Package Layout

A **uv workspace monorepo**: 7 `mp-*` packages under `packages/` plus the root `metesparser` package. The monolith in `src/metesparser/` is preserved for backward compatibility. Workspace dependency edges:

```
mp-models   → Pydantic schemas, JSONL envelope, units (no workspace deps)
mp-bearing  → Pure math: azimuth, curves, deltas (mp-models)
mp-ocr      → LLM boundary: PDF → text (mp-models)
mp-parse    → Rule-based parsing: text → calls (mp-models, mp-bearing)
mp-verify   → Canonical geometry checks (mp-models, mp-bearing)
mp-export   → CSV/JSON/HTML rendering (mp-models, mp-verify)
mp-review   → Deterministic `metes-review` CLI/adapters; no OCR/provider dependency (mp-models, mp-parse, mp-verify, mp-export)
metesparser → Orchestrator (`Pipeline`) + backward-compat monolith
```

Placement rules: schemas in `mp_models`, numerical logic in `mp_parse`/`mp_bearing`/`mp_verify`, rendering in `mp_export`, adapters and stage I/O in `mp_review`. `Pipeline.run()` returns verification results (and optional `AuditContext`) but never writes exports; export is a separate step. Module-level mapping: [ARCHITECTURE.md](docs/ARCHITECTURE.md#package-to-monolith-mapping).

Other directories:
- `plugins/metesparser/` — capability/workflow skills, shared handoffs, launcher, plugin docs
- `plugins/metesparser-chat/` — standalone chat dispatcher, host setup and download guidance
- `prompts/` (monolith) and `packages/mp-ocr/src/mp_ocr/prompts/` (package) — LLM prompt YAMLs
- `sample_deeds/` — sample PDFs, ground-truth JSON and LlamaParse markdown (co-located)
- `tests/` (fixtures in `tests/fixtures/`), `packages/mp-*/tests/`, `plugins/metesparser/tests/`
- `docs/reference/` — reference PDFs, tracked via `!docs/reference/*.pdf`
- `docs/plans/` — plans and acceptance handoffs; `docs/archive/extraction-output/` — historical outputs, not current verified results
- `output/` — ignored runtime outputs; keep durable evidence under `docs/`

### When Modifying Code
1. Modify the package code (e.g., `packages/mp-parse/`)
2. Keep duplicated monolith behavior in sync; for shared review features, maintain the compatibility facade rather than duplicating the implementation
3. Run per-package tests: `uv run pytest packages/mp-parse/tests/ -v --no-cov`
4. Run cross-package import verification: `uv run pytest tests/unit/test_cross_package_imports.py -v`

## Plugin and Review Workflow Rules

The Claude plugin is an instruction layer over the shared packages. Its [catalog](plugins/metesparser/README.md#skills) lists thirteen skills: ten capabilities, two workflows, and the `review-deed` compatibility alias.

**Skills and distribution**
- Keep each capability scoped to its own output; workflows select stages and reuse valid artifacts.
- Follow the [skill maintenance guide](docs/CLAUDE_PLUGIN.md#maintain-the-skill-composition) when changing instructions, handoffs or examples. Link shared references rather than duplicating contracts across skills.
- Use the [handoff contract](plugins/metesparser/references/artifact-handoffs.md) for accepted inputs, stopping points, status separation and invalidation.
- Maintain shared capability instructions in `plugins/metesparser/`. `make chat-skill-build` adapts them into one standalone chat Skill (same wheels, lock and engine fingerprint) without changing the plugin. Validate the extracted archive outside the checkout, and distinguish local runtime checks from native Claude chat acceptance.
- The plugin is designed for native Claude document reading, but native Claude/Cowork acceptance remains unrun — do not claim it. `mp-ocr` is the provider-backed path for the Python pipeline only.

**Status separation (never promote verification)**
- Plotting, overlay preparation, dashboards, maps, revisions, diagnoses, scenarios, tentative matches and comparisons must not modify canonical calls, verification or verified-export eligibility.
- Completed advisory commands return `needs_review` (exit 1), including completed findings; invocation/schema errors return `error` (exit 2).
- `validate-source` checks source records (schema 1.1, exact UTF-8 bytes, page/span identities, uncertainties); it does not establish source accuracy. `inspect-artifacts` inventories and replays artifacts read-only, reporting dependencies and restart guidance without executing a workflow. `diagnose-closure` and `compare-descriptions` retain the explicit request alongside their advisory results. See the [source](plugins/metesparser/references/source-preparation.md), [diagnosis](plugins/metesparser/references/closure-diagnostics.md) and [comparison](plugins/metesparser/references/comparison-limits.md) references.

**Revisions** — [contract](plugins/metesparser/references/revisions.md)
- Save exact raw drafts separately from parsed or last-valid geometry; preserve source/document/tract/call identities; publish immutable revisions.
- Line and arc edits use shared revision preparation and rendering; only the immediate browser preview is straight-course only.
- Source-correction records must not be described as complete native source acquisition or selection.

**Derived geometry**
- [Corridor](plugins/metesparser/skills/plot-corridor/SKILL.md): schema 1.2 retains the exact centerline and ordered endpoint width/taper/join/cap definitions. Keep it separate from parcel closure; report unsupported topology or unmet error budgets.
- [PLSS](plugins/metesparser/skills/plot-plss-reference/SKILL.md): derive only from an identified supplied reference dataset under the supported rectangular rule. A PLSS recital or metadata extraction alone does not establish section corners.
- [Raster picker](plugins/metesparser/skills/prepare-parcel-overlay/references/overlay-preparation.md): records image pixel controls only; does not establish real-world controls or deed placement.
- Dashboard assembly is explicit; placements bind to freshly computed dashboard geometry. [Delivery](plugins/metesparser/skills/export-review-package/SKILL.md) (SVG/PDF/DXF/GeoJSON) is immutable; inspection is read-only.

**Online maps** — [local viewer](plugins/metesparser/skills/render-online-map/references/local-viewer.md), [MCP](plugins/metesparser/skills/render-online-map/references/mapbox-mcp.md)
- `render-online-map` owns Mapbox and in-chat MCP rendering; the dashboard workflow owns bundle assembly. Map-only requests do not require a dashboard; the offline dashboard stays unchanged.
- Require explicit CRS, unit, placement and registration evidence. Never infer a location from direction words or fit a deed to imagery. Stale placements fail.
- Mapbox tokens belong only in the runtime Connect field — never in configuration or generated files. MCP connection credentials stay outside artifacts.
- `render-map` accepts `StandaloneWebMapInput` (prepared plots and map arrays/placements) plus a token-free `WebMapRequest`; shared math revalidates plots. It writes an online viewer and an offline evidence fallback without building a dashboard or granting source-review/verification status.
- `mapbox-mcp` reuses intact standalone-map or legacy dashboard geographic stages for a vector-only in-chat preview; it must not reproject, simplify, transmit data or promote verification. Request external previews only through an already configured compatible tool. Code locations: contract `mp_models.webmap`, provenance `mp_verify.webmap`, preparation `mp_review.webmap`/`mp_review.mapbox_mcp`, rendering `mp_export.online_map_html`/`mp_export.mapbox_mcp`. Raster reprojection needs the `web-map` extra.

## Commands

UV is required — never use pip, conda or poetry (`uv sync --all-extras --dev`, `uv add PKG`, `uv run ...`). Full command lists: [DEVELOPER_REFERENCE.md](docs/DEVELOPER_REFERENCE.md#cli-commands).

```bash
make quality       # Nonmutating root lint + format checks
make type          # mypy
make test          # Root pytest (tests/, 80% coverage on src/metesparser)
make pre-commit    # lint-fix, format, tests — MUTATING
uv run pytest packages/mp-*/tests plugins/metesparser/tests --no-cov --import-mode=importlib
```

- **`--no-cov`** for any package/plugin run: root coverage targets `src/metesparser`, so package-only runs fail the unrelated 80% threshold. Add **`--import-mode=importlib`** when collecting multiple package/plugin suites together.
- Makefile lint/format cover `src/metesparser` and `tests`; typing covers `src/metesparser`. Changed package/script files need explicit `uv run ruff`/`uv run mypy` runs.
- `make check` and `make pre-commit` can change files. `make ci` deletes the environment and build outputs via `clean` and skips `type`.
- Local browser/SDK and extracted-archive checks do not establish live Mapbox acceptance, native skill discovery or native document-reading accuracy. Keep these gates separate and report unrun gates explicitly.

## Bearing Convention (Critical for Calculations)

Azimuth = degrees clockwise from North (0-360):
- N 45° E → 45°
- S 45° E → 135° (180 - 45)
- S 45° W → 225° (180 + 45)
- N 45° W → 315° (360 - 45)

DMS parsing: "S 56°40'30\" W" → (S, 56.675, W) → 236.675° azimuth

## Coding Style
- Python 3.11+, four-space indentation, snake_case modules/functions/tests, CapWords classes, typed public APIs.
- Ruff for formatting and linting; respect the exclusions in `pyproject.toml`. Never use Black. Add concise comments only when geometry rules or guardrails need justification.

## Testing
- TDD order: bearing conversions first; known parcels (18 Pennbrook parallelogram, 24 Pennbrook, square fixture); near-zero closure cases; incomplete bearings (flag, don't fabricate).
- Mock LLM calls; store sanitized inputs and expected outputs under `tests/fixtures/`. Name tests after behaviors (`test_parse_curve_segments`).
- Required checks must pass. Investigate failures and unexpected warnings or skips before committing; a skipped optional browser/provider suite establishes nothing. Record the exact command, result and scope rather than a fixed test count.

## Known Issues & Workarounds

### text_parser.py Linting
`src/metesparser/text_parser.py` is excluded under `[tool.ruff] exclude`. Preserve that scope unless deliberately changing it. A lint exclusion does not establish functional correctness; verify changes with focused parsing tests.

### Boolean Field Validation
Do NOT use `strict=True` on boolean `Field()` declarations in `DeedCall` — it contradicts the `_coerce_bool_field` validator that coerces `"true"`/`"false"` strings.

### Cardinal Direction Patterns
Cardinal-only patterns must include `(?:erly|wardly)?` suffixes AND abbreviated forms (`NE|NW|SE|SW`). All three must stay in sync:
- `packages/mp-parse/src/mp_parse/calls.py` (`_CARDINAL_ONLY_PATTERN`)
- `packages/mp-parse/src/mp_parse/metadata.py` (`CARDINAL_ONLY_PATTERN`)
- `scripts/audit_gt_vs_md.py` (`CARDINAL_ONLY_PATTERN`)

The monolith `call_extractor._CARDINAL_ONLY_PATTERN` and `TextParser.CARDINAL_ONLY_PATTERN` re-export the package patterns.

Bug history: missing `wardly` caused false negatives; missing abbreviations caused call rejection when LLM normalization turned "NORTHWEST" into "NW" (PR #21).

### LLM Configuration
- `OpenAIClient` and `GeminiClient` behind `METESPARSER_LLM_PROVIDER`; `BaseLLMClient` ABC in `mp_ocr.clients`; `PDFProcessor` accepts `provider=` or `client=` for DI.
- Defaults: OpenAI `gpt-5.2`; Gemini `gemini-3-flash-preview` with fallback `gemini-2.5-flash`.

### CSV Schema
21 fields in `mp_export.csv_writer.FIELDNAMES` (monolith `csv_builder.py`); **order matters**. Field list and notes: [DEVELOPER_REFERENCE.md](docs/DEVELOPER_REFERENCE.md#csv-schema).

## Environment Setup
`.env` (copy from `.env.example`): `OPENAI_API_KEY` or `GEMINI_API_KEY` per provider; optional `METESPARSER_LOG_LEVEL` (default `INFO`). Never commit secrets; guard API keys when scripting against the pipeline. Document basis of bearing, datum and source metadata alongside exported CSV.

## Git Workflow
- Never push to `main` — use branches and PRs.
- Run `make pre-commit` before committing on a clean tree. On a dirty tree it reformats unrelated files; run `make quality` and `make test` instead and fix only the files you changed.
- Never commit `.env` or API keys.
- For generated deed CSV outputs, only commit exports accepted by the canonical verified-export gate; synthetic test inputs remain separate fixtures.
- Preserve the `CLAUDE.md` symlink to this file.

### Git Gotchas
- `.gitignore` ignores PDFs except allowed sample/reference paths. Use `git check-ignore -v PATH`; add a scoped exception only for intended repository evidence. Move tracked PDFs with `git mv`.
- Pre-commit hooks may reformat files — check `git status` after every commit.
- `uv.lock` is tracked — commit lockfile changes with dependency updates.
- Inspect the configured remote before GitHub operations; creating a repository or pushing requires user authorization.
- Preserve unrelated or concurrent work. Do not automatically stash, reset or clean a dirty checkout; inspect the state and use an isolated worktree or obtain authorization.

### Commits & Pull Requests
- Conventional commits: `feat:`, `fix:`, `docs:`, `chore:`, `test:`, `refactor:`.
- PRs list workflow stages affected, cite prompt or env updates, link issues, and summarize manual verification (e.g., closure deltas, curve residuals).

## Common Development Patterns

### Adding a New Verification Check
1. Add function to `packages/mp-verify/src/mp_verify/checks.py`
2. Call from `verify_closure()` in `closure.py` and add to warnings list
3. Update `ClosureResult` model in `mp-models` if needed
4. Write test in `packages/mp-verify/tests/` and `tests/unit/test_phase3_verification.py`
5. Keep monolith `closure_checker.py` in sync

### Adding a New DeedCall Field
1. Add field to `DeedCall` in `packages/mp-models/src/mp_models/deed_call.py` (with `Field()` default, no `strict=True` on bools)
2. Add to `FIELDNAMES` in `packages/mp-export/src/mp_export/csv_writer.py` (order matters)
3. Add to `_CSVDeedCallRow` in `csv_writer.py`
4. Wire extraction into `packages/mp-parse/src/mp_parse/calls.py` or `metadata.py`
5. Keep monolith `models.py` and `csv_builder.py` in sync (`call_extractor.py` delegates to `mp_parse`)
6. Update fieldnames count test in `test_phase2_enhanced_parsing.py`
7. Add feature tests in appropriate phase test file

### Adding New Unit Support
1. Add conversion factor to `ConversionFactors` in `packages/mp-models/src/mp_models/units.py`
2. Update `convert_to_feet()` method
3. Add to the `DistanceUnit` Literal in `packages/mp-models/src/mp_models/units.py` (used by `LegalDescription.distance_unit`)
4. Keep monolith `models.py` in sync
5. Test with sample deed using that unit
