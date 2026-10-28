# plot-metes-and-bounds

Create a standalone display plot from identified calls or an already-isolated description.

## Example request

> Plot the selected calls in this CSV and show the unresolved bearing as a gap.

## Inputs and outputs

**Inputs:** Strict CSV, calls-list or `LegalDescription` JSON, `RelativeDescription` JSON, or `PlotRequest` JSON. For an already-isolated UTF-8 description, run `plot description.txt --input-format text` through the plugin launcher. The shared preparation retains commencement calls as tie-ins and excludes them from boundary geometry; unknown bearings stay unknown. Multiple tracts or an unresolved commencement require clarification. Automatic format detection remains limited to structured files.

**Outputs:** Exact-byte source copy, normalized plot input, geometry, standalone HTML, and manifest. The command reports top-level `needs_review`; this is not canonical verification.

## Documentation

- [Skill instructions](SKILL.md)
- [Artifact handoffs and PlotRequest fields](../../references/artifact-handoffs.md)
- [Usage and routing](../../references/usage.md)
- [Plugin changelog](../../CHANGELOG.md)

The plot remains offline. A later explicitly requested online map routes to [render-online-map](../render-online-map/README.md), reusing valid inputs and source records with explicit geographic placement evidence. A dashboard is an additional requested deliverable.
