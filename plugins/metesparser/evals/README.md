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

For native document-reading cases, attach or otherwise supply the same real source to both sessions and record which pages/files were actually available. For Mapbox cases, record discovered tool names and input-schema evidence; call a connected provider only when that external preview is requested. Record handoff validation, provider/tool result, and visible-client rendering separately. A hypothetical `connected_tool` field in a case is a fixture precondition, not proof that a live tool or rendered map exists.

## Suggested run record

One JSONL record per case, condition, and model run is sufficient. Keep full transcripts as separate artifacts and link them by path and SHA-256. Do not place credentials in records.

```json
{
  "run_id": "trial-001",
  "case_id": "ambiguous-cardinal-bearing",
  "condition": "baseline | with_skill",
  "model_provider": "",
  "model_name_version": "",
  "client_surface": "",
  "started_at_utc": "",
  "case_source_commit": "",
  "case_source_sha256": "",
  "skill_files_and_hashes": [],
  "fresh_session": true,
  "request_and_input_artifact": "",
  "available_tools_and_schema_evidence": [],
  "transcript_path": "",
  "transcript_sha256": "",
  "criteria": [{"criterion": "", "result": "pass | fail | not_run", "evidence": ""}],
  "overall_result": "pass | fail | not_run",
  "observations": ""
}
```

## Current recorded status

The entries in `cases.json` are authored routing/behavior specifications. This README adds a reproducible procedure only; it records no model runs. No Claude Haiku/Sonnet/Opus evaluation matrix or native Claude document/client acceptance is recorded here. Engine and repository tests remain their own verification lane. Keep matter files and full transcripts outside the repository unless sanitized and approved for inclusion; retain their hashes in the run record.
