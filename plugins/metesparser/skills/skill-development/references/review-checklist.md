# Skill review checklist

Use this checklist during authoring and independent review. Record concrete failures rather than a general quality score.

## Discovery

- Confirm `skills/<kebab-case-name>/SKILL.md` exists and its frontmatter parses as a mapping with non-empty `name` and `description` strings.
- Check third-person descriptions for concrete user trigger phrases and relevant boundaries. Avoid terms so broad that unrelated tasks activate the skill.
- Compare nearby skills and resolve overlapping responsibility with a clear routing rule.

## Execution and disclosure

- Start procedures with imperative verbs and specify necessary inputs and outputs.
- Keep essential invariants and failure handling in the entrypoint. Link substantial optional details instead of duplicating them.
- Resolve each relative resource link from the file containing it. Remove references to unavailable tools, agents, or files.
- Include only useful resources; keep examples complete and scripts runnable with documented dependencies.
- Check portable paths from an unrelated working directory and a directory containing spaces. Use a `python3` prefix or preserve executable permissions for Python helpers.
- Identify configuration defaults, CLI precedence, and actual reload behavior when configuration is supported.

## Behavior trials

Prepare at least three representative requests. Maintain expected outcomes separately from raw reviewer inputs:

| Trial | Example request | Assessment |
| --- | --- | --- |
| Success | "Add a skill that reviews supplied traverse CSV." | Reuse existing verifier, define triggers, reference the deterministic launcher, and validate resources. |
| Failure | "Create a skill around this script" with a script that requires an unavailable dependency. | Report the prerequisite or failure; do not claim execution succeeded. |
| Selection boundary | "Verify these existing deed calls." | Select `verify-traverse`; do not begin authoring a new skill. |

Keep reviews read-only unless implementation is explicitly assigned. Record whether assessment was a static review, an agent exercise, or an actual Claude client trial. Treat each as distinct evidence.
