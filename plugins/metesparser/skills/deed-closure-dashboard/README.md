# Deed Closure Dashboard

Prepare a source-grounded review dashboard for a deed's boundary description. The workflow keeps recorded deed data intact while allowing clearly separated scenario edits for exploring closure.

## Example request

> Build a closure review dashboard from this deed packet. Show the source evidence, extracted courses, closure findings, and any disputed figures without changing the recorded values.

## Inputs and outputs

**Inputs:** The deed or survey packet, any existing extraction or review artifacts, and the parcel or tract to examine. Include known concerns such as a disputed digit, missing page, or competing description.

**Output:** A review dashboard with record-only findings, disputed-figure scan crops, an interactive SVG plot and editable call sheet, live closure calculations for scenario edits, verbatim transcripts and extracted courses, original page copies with a viewer, and method, limits, and source notes. Copyable CSV and scenario values remain distinguishable from recorded source data.

## Documentation

- [Skill instructions](SKILL.md)
- [Detailed playbook](references/playbook.md)
- [Optional patterns from the supplied HTML example](references/example-patterns.md)
- [Shared plugin usage](../../references/usage.md)
- [Plugin changelog](../../CHANGELOG.md)

The workflow uses Claude's native document reading for source review. Numerical findings are limited to the stated method and available evidence; scenario calculations do not establish that a source bearing was present or that the parser engine verified the result. See the skill and playbook for the evidence workflow, review roles, and limitations.
