# plot-metes-and-bounds

Create a standalone display plot from an identified structured boundary input.

## Example request

> Plot the selected calls in this CSV and show the unresolved bearing as a gap.

## Inputs and outputs

**Inputs:** Strict CSV, calls-list or `LegalDescription` JSON, `RelativeDescription` JSON, or `PlotRequest` JSON. For an already-isolated plain-text description, `mp_parse.extract_calls()` can prepare structured plot input without running canonical verification; ambiguous or unresolved calls remain unresolved.

**Outputs:** Exact-byte source copy, normalized plot input, geometry, standalone HTML, and manifest. The command reports top-level `needs_review`; this is not canonical verification.

## Documentation

- [Skill instructions](SKILL.md)
- [Artifact handoffs and PlotRequest fields](../../references/artifact-handoffs.md)
- [Usage and routing](../../references/usage.md)
- [Plugin changelog](../../CHANGELOG.md)

The plot remains offline. A later explicitly requested [Mapbox dashboard companion](../deed-closure-dashboard/references/dashboard-bundle.md#optional-mapbox-companion) composes these plot inputs with source evidence and prepared map layers; it does not turn this capability into a mapping or verification workflow.
