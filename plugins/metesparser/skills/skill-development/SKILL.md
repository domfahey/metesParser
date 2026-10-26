---
name: skill-development
description: This skill should be used when the user asks to "create a skill", "add a skill to a plugin", "write a new skill", "improve skill description", or "organize skill content" within an individual Claude Code skill. Covers trigger descriptions, progressive disclosure, supporting resources, and validation; route plugin-wide manifest and component layout changes to plugin-structure.
metadata:
  version: "0.1.0"
---

# Skill development

Create focused instructions for another Claude instance. Inspect the existing plugin and search for overlapping skills before adding files. Preserve project conventions and existing user work.

## Define concrete use cases

Identify representative user requests, required inputs, expected outcomes, and nearby requests that should not trigger the skill. Use supplied examples where available; ask only for missing information that changes the design. Keep the requested workflow within its authorized scope.

Choose a precise kebab-case name. Write a third-person frontmatter description with concrete trigger phrases, such as `This skill should be used when the user asks to "verify a traverse"...`. Describe capability and selection boundaries; keep workflow steps in the body rather than metadata.

## Choose resources

Create `skills/<name>/SKILL.md` directly inside the plugin. Use [Plugin Structure](../plugin-structure/SKILL.md) for manifest or discovery changes. Create optional directories only when needed:

- Put repeatable, deterministic operations in `scripts/`; reuse existing implementations instead of reproducing calculations in prompts.
- Put detailed schemas, policies, and troubleshooting in `references/`. Link each resource from the entrypoint with a reason to read it.
- Put complete runnable demonstrations in `examples/` when they clarify an otherwise ambiguous workflow.
- Put files copied into deliverables in `assets/`; avoid loading them as instructions.

Write reusable resources first, then the entrypoint. Keep information in one maintained location. Avoid empty scaffolding, invented tool dependencies, copied manuals, and redundant scripts.

Maintain a human-facing `README.md` inside each skill directory with its purpose, a realistic request, inputs/outputs, and links to shared documentation. Keep execution rules in `SKILL.md`; avoid copying the same procedures into both. Record user-visible changes under Unreleased in the plugin's shared `CHANGELOG.md` rather than duplicating history per skill.

## Write the entrypoint

Use YAML frontmatter containing `name` and `description`, followed by actionable Markdown. Store optional version information under `metadata.version` for compatibility with this repository's validators. Use verb-first instructions: `Inspect the source`, `Run the verifier`, and `Report unresolved calls`, rather than second-person phrasing.

Keep the body as short as the task permits. Retain essential routing, procedures, failure handling, and decision rules. Move substantial optional detail to references; do not pad a simple skill to meet a word-count target. Use metadata for discovery, the body for execution, and linked resources for specialized steps.

Define inputs, outputs, actual prerequisites, and failure handling. Reference plugin helpers through quoted `${CLAUDE_PLUGIN_ROOT}` paths; provide a script-relative fallback when the target environment lacks that variable. Keep user-local configuration separate from shipped resources; consult [Plugin Settings](../plugin-settings/SKILL.md) when adding configurable behavior.

## Validate and exercise

Follow the [review checklist](references/review-checklist.md). Validate frontmatter, relative links, examples, and new scripts. Run `claude plugin validate PLUGIN_PATH --strict --json`; distinguish manifest success from runtime correctness.

Report the exact failed check and prerequisite when a tool, dependency, or validation step fails. Continue independent checks where useful; do not describe the skill as runnable or fully validated while execution remains unverified.

Ask a reviewer agent for a read-only review of trigger specificity, clarity, resource organization, and missing failure handling. If no reviewer agent is available, perform the checklist directly and report that limitation.

Exercise representative raw requests against the skill in a fresh workspace without exposing expected answers to the reviewer. Include a success, a failure, and a nearby non-trigger request. For actual Claude client acceptance, load the local plugin with `claude --plugin-dir PLUGIN_PATH` and check discovery and behavior. Do not claim this occurred based only on static validation or another agent's review. Keep paid or authenticated client trials within existing authorization.

Revise instructions when a trial exposes a gap. Re-run affected validation and rebuild the plugin distribution after edits. Distribute skills as part of the plugin rather than creating separate skill ZIPs. Report which checks ran and which client or model evaluations remain unverified.

Use the target plugin's documented packaging workflow. For a MetesParser source checkout, run `make plugin-build` and inspect `dist/metesparser-plugin.zip`; do not assume the source builder exists inside an installed plugin.
