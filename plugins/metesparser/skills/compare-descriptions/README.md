# compare-descriptions

Compare two identified, source-linked description versions using explicitly supported geometric criteria and deterministic structural differences.

## Example request

> Compare the operative description in the 1988 deed with the revised survey description and report which calls changed.

## Inputs and outputs

**Inputs:** A `ComparisonRequest` JSON containing two `PlotRequest` descriptions, bearing-basis evidence, explicit sourced tolerances, and optional explicit pairs/transform. Read the authoritative model before constructing the request; do not infer missing basis or tolerance facts.

**Outputs:** Advisory `needs_review` status and `comparison-request.json`, `comparison.json`, and `comparison-manifest.json`. Structural pairings remain tentative and comparison never establishes a legal boundary or grants verified-export eligibility.

## Documentation

- [Claude instructions](SKILL.md)
- [Comparison limits](../../references/comparison-limits.md)
- [Packaged request JSON schema](references/comparison-request.schema.json)
- [Synthetic request](references/comparison-example.json)
- [Plugin changelog](../../CHANGELOG.md)
