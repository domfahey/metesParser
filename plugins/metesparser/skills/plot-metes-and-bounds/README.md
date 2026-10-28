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

The plot remains offline. A later explicitly requested online map routes to [render-online-map](../render-online-map/README.md), reusing valid inputs and source records with explicit geographic placement evidence. A dashboard is an additional requested deliverable.
