# Skill behavior evaluation protocol

The [case catalog](cases.json) is the scenario source for skill-behavior evaluations. These cases are specifications, not evidence that a model or native Claude client has passed them. This lightweight protocol follows [Anthropic's skill evaluation guidance](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices): evaluate realistic tasks with and without the skill, use fresh sessions, cover multiple model sizes, and record observations. See the [plugin catalog](../README.md) for skill routing.

## Keep evaluation lanes separate

- **Routing specifications:** `cases.json` describes the intended task, inputs, expected behavior, and prohibited behavior. It does not run a model.
- **Engine tests:** pytest, the review corpus, browser tests, and launcher tests check deterministic software contracts. Passing them is not a model evaluation.
- **Fresh Codex check:** a separate, recorded check of a new Codex session using the skill. Do not infer its outcome from repository tests or from Claude results.
- **Claude model evaluation:** run the same cases in fresh native Claude sessions for Haiku, Sonnet, and Opus where available. No recorded Claude family matrix exists yet.
- **Native document acceptance:** actual reading of supplied PDFs/images and Claude/Cowork host behavior require their own observed runs. Synthetic case descriptions and local tests do not establish this.
- **Mapbox acceptance:** local handoff generation, live provider/tool compatibility, and a visibly correct native-client map are separate results. A tool response alone is not visible UI acceptance.

## Minimal comparison procedure

Use at least three discriminating cases; start with these existing IDs:

1. `ambiguous-cardinal-bearing` — checks that unknown bearing information stays unknown.
2. `extract-only-stops-after-selection` — checks stage boundaries, verbatim selection, and artifact reuse.
3. `changed-call-invalidates-dependent-artifacts` — checks invalidation and recomputation after source changes.

For each case and each model/client being evaluated:

1. Start two independent, fresh sessions with the same model version, system context, user request, input artifacts, and available tools. Do not carry conversation history between trials. Randomize which condition runs first when practical.
2. Materialize any scenario input placeholders as actual files or tool fixtures first. In the **baseline** session, provide only the case's user-facing `request` and `input`; keep this plugin's skills, catalog, and evaluation notes out of its context and accessible files. In the **with-skill** session, provide the same request/input and expose all skill metadata for discovery, with bodies and references available on demand. Do not preselect the expected skill for a routing test. Keep other instructions and tool access identical; record which skills/references the agent actually reads.
3. Keep `expected`, `expected_status`, and `must_not` hidden from both responding sessions. The evaluator uses them only after saving each response. Do not show the rubric or score to the agent before its response is complete.
4. Save the complete response/transcript and enough session evidence to identify the model, client, skill files, tool availability, and case input. Score each stated expected behavior and each `must_not` item independently as pass/fail against the response and observed actions. A trial passes only if all applicable requirements pass and no prohibited behavior occurs; missing evidence or an unrun required check prevents a pass. Record a short evidence quote/location for each score. An unavailable tool is a valid fixture for a fallback case, but cannot satisfy a live-rendering case.
5. Record baseline and with-skill outcomes separately. Report per-case results and observations, including regressions or cases where the skill made no difference. Do not combine model/client versions into one score.

For Claude coverage, repeat the same case set separately with Haiku, Sonnet, and Opus, recording the exact model/version returned by the client. If a model or native Claude surface is unavailable, record `not run` and why. Fresh Codex checks should use the same paired protocol but remain a distinct client/model lane.

## Focused artifact scenarios

The four added cases below are specifications until run in paired fresh sessions. Materialize valid files and directories before presenting either trial with the same case inputs. Keep temporary artifacts outside the repository. All plot/map/dashboard examples in this group are explicitly synthetic; they are software fixtures, not property evidence.

1. `plot-isolated-prose-with-commencement-tie-in`: write the exact UTF-8 prose included in the case input to a new `source.txt`. The first 50-foot course runs from the commencement point to the POB; the following four 100-foot courses form the selected boundary ring. Use the explicit text plot path, not a document-selection workflow:

   ```sh
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" plot source.txt --input-format text --output-dir NEW_PLOT_DIR
   ```
2. `compose-standalone-map-from-existing-plot-and-layer`: materialize the text plot output from case 1. For a real prepared layer artifact, copy the synthetic GeoJSON construction in `packages/mp-review/tests/test_overlay_cli.py::test_import_command_creates_new_artifact_and_rejects_overwrite` into a temporary input file and import it through the documented `import-overlay` launcher command. Then compose the resulting plot directory and layer artifact:

   ```sh
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" import-overlay GEOJSON --format geojson --target-crs EPSG:3857 --output PREPARED_LAYER.json
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" compose-map PLOT_DIR --layer PREPARED_LAYER.json --output-dir NEW_MAP_DIR
   ```

   The inputs are in different frames unless explicit placement evidence is added. A successful composition is not evidence of alignment, provider acceptance, or visible client rendering.
3. `compose-dashboard-recomputes-geometry-hash`: copy `plugins/metesparser/skills/deed-closure-dashboard/references/dashboard-example.json` to a new base input, and use the prepared layer above. Materialize a standalone plot as a comparison artifact, but pass only the base bundle and prepared layer to the dashboard composition command. Capture `geometry_hashes` from its result and compare against the standalone plot hash; do not add placement unless a real explicit transform and supporting evidence are supplied:

   ```sh
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" compose-dashboard BASE_BUNDLE.json --layer PREPARED_LAYER.json --output-dir NEW_DASHBOARD_DIR
   ```

   The example's placeholder page image is only schema fixture data and does not establish that a document was read. Keep engine verification and verified-export eligibility false; if separately rendered, the dashboard's `needs_review` status belongs to that rendering stage. Do not infer a placement from different geometry hashes.
4. `relative-only-analysis-routes-without-verification-or-dashboard`: copy `plugins/metesparser/skills/deed-closure-dashboard/references/relative-rectangle.json` to a new input file and supply it as the `RelativeDescription` JSON. This exercises the relative-analysis route directly and does not require any dashboard source bundle:

   ```sh
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" analyze-relative relative-rectangle.json --output-dir NEW_RELATIVE_DIR
   ```

If a command or required artifact cannot be materialized and validated, record that scenario as `not_run` with the missing prerequisite. Do not replace an absent artifact with a hand-written schema guess or claim a materialization succeeded.

For native document-reading cases, attach or otherwise supply the same real source to both sessions and record which pages/files were actually available. For Mapbox cases, record discovered tool names and input-schema evidence; call a connected provider only when that external preview is requested. Record handoff validation, provider/tool result, and visible-client rendering separately. A hypothetical `connected_tool` field in a case is a fixture precondition, not proof that a live tool or rendered map exists.

## Suggested run record

One JSONL record per case, condition, and model run is sufficient. Keep full transcripts as separate artifacts and link them by path and SHA-256. Do not place credentials in records.

```json
{
  "run_id": "trial-001",
  "case_id": "ambiguous-cardinal-bearing",
  "pair_id": "pair-001",
  "condition": "baseline | with_skill | non_equivalent",
  "model_provider": "",
  "model_name_version": "",
  "client_surface": "",
  "started_at_utc": "",
  "case_source_commit": "",
  "case_source_sha256": "",
  "fresh_session": true,
  "isolation_status": "equivalent | non_equivalent",
  "skill_files_and_hashes": [],
  "candidate_bundle_path": "case-input",
  "rubric_path": "case-rubric/rubric.json",
  "input_manifest_path": "case-input/manifest.json",
  "input_manifest_sha256": "",
  "artifact_paths": [],
  "available_tools_and_schema_evidence": [],
  "transcript_path": "",
  "transcript_sha256": "",
  "criteria": [{"criterion_id": "", "result": "pass | fail | not_run", "evidence": ""}],
  "required_actions": [{"action": "", "result": "pass | fail | not_run", "evidence": "", "reason": ""}],
  "overall_result": "pass | fail | not_run",
  "observations": ""
}
```

## Current recorded status

The entries in `cases.json` are authored routing/behavior specifications. The [October 28 Codex smoke record](runs/2026-10-28-codex-smoke.json) records three fresh smaller-model checks: relative-analysis discovery, prose plotting with a commencement call, and packaged map composition. Each completed its requested task using the extracted plugin. These are unpaired forward checks with command/skill reports and artifact hashes, not full transcripts or baseline comparisons; no improvement score is claimed. A separate seven-command smoke checked the bundled runtime from a project outside the checkout.

No paired evaluation, Claude Haiku/Sonnet/Opus matrix, native Claude document/client acceptance, or live Mapbox acceptance has been recorded. Engine and repository tests remain their own verification lane. Keep matter files and full transcripts outside the repository unless sanitized and approved for inclusion; retain their hashes in the run record.

## E1 fixture preparation and evidence validation

`scripts/skill_evals.py`, run from the repository root, materializes synthetic inputs, checks one run record, and prints a descriptive ledger. It never starts a model/provider session or decides whether a transcription is true. Use new, separate candidate and evaluator directories:

```sh
uv sync --all-extras --dev
uv run python scripts/skill_evals.py materialize source-reading-obscured-digits \
  --output-dir /tmp/case-input --evaluator-dir /tmp/case-rubric
uv run python scripts/skill_evals.py validate-run /tmp/run.json
uv run python scripts/skill_evals.py summarize /tmp/runs.jsonl
```

The candidate directory contains `request.json`, `manifest.json`, and synthetic source artifacts with hashes. The evaluator directory contains `rubric.json`; do not provide it to either responding session. A run record points to both directories and records hashes, complete transcript path/hash, exact model and client, condition and pair ID, available tool/schema evidence, exposed skill resource hashes, artifact paths, criterion evidence, and required actions. Set `isolation_status` to `equivalent` only when the client verifies that baseline cannot access plugin/repository/rubric material and both conditions have identical tools. Otherwise record the run as `non_equivalent`; it is not paired evidence.

The validator checks file hashes and criterion/action coverage. Scored observations require a machine-readable transcript: a JSON object with a `turns` array, a JSON array of turns, or JSONL client events. Startup metadata, empty turns, and synthetic authentication-error messages do not establish model behavior; a client/session failure must remain `not_run`. The helper checks these structural facts without judging whether the response is true or the criterion was scored correctly. A `pass` requires every applicable criterion and required action to have observable `pass` evidence; `fail` requires a failed criterion or action. `not_run` is a valid recorded result and never becomes a pass or an observed paired comparison. Summary rows remain separated by case, exact model, and client. No cross-client improvement score is computed.

The matrix materializes synthetic PDF/image reading cases (obscured figures, absent exhibit, repeated occurrences), selection-only, reuse/restart, closure diagnosis, map routing, optional UI interaction, map checkpoint evidence, reversed/incompatible/structural comparison, and end-to-end review. Native-document and optional UI actions must remain `not_run` when the required client or identical browser tools are unavailable.
