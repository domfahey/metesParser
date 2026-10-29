---
name: plot-corridor
description: Constructs an advisory easement or right-of-way corridor when supplied centerline calls and explicit left/right widths, tapers, joins and caps define the requested ribbon. Retains source-linked construction inputs and reports approximation and topology limits without parcel verification or inferred map placement.
metadata:
  version: "0.1.0"
---

# Plot a centerline corridor

Use this capability for a requested corridor from an identified centerline and width instructions. A document classified as an easement alone does not supply its construction. If the intended centerline or width passage is unresolved, use [description selection](../extract-metes-and-bounds/SKILL.md) and retain uncertainty before constructing anything. Stop at corridor artifacts; a dashboard, provider map or parcel verification needs its own request.

Check [runtime prerequisites](../../references/usage.md#runtime-prerequisites), then read the generated [`CorridorRequest` schema](references/request.schema.json) and [complete synthetic example](references/example.json). Author the request from actual supplied evidence:

- Keep the original source-linked line/circular-arc `PlotRequest`, stable call IDs, verbatim quotes and known foot definition. Relative-only, indefinite, tie-in, exception and meander geometry needs separate selection or an explicit unavailable outcome.
- Address width ranges by exact call ID and fractional station. Preserve ordered intervals, both left/right start/end widths, their declared units and source references. Sides follow stored forward centerline traversal. `step` is constant within its interval; adjacent rows can define an explicit jump. `linear_taper` varies with centerline arc length. Never average endpoint widths or choose precedence among overlapping rows.
- Use the requested join, cap and construction evidence. Supported straight joins are bevel, bounded miter and round; arc junctions must be tangent. Square caps extend by half the total endpoint width. Round caps use the diameter between the endpoint offsets; their centers can lie off an asymmetric centerline. Do not describe an example choice as surveyed intent.
- Preserve the declared linear error budget and work limit. Shared geometry chooses curve samples from a second-derivative chord bound. Missing coverage, inner-radius collapse, non-tangent arc joins, full/multirevolution or spiral curves, closed centerlines needing holes, self-intersections, and topology clearance within approximation error remain explicit unavailable outcomes.

Run into a new directory:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" analyze-corridor REQUEST.json --output-dir NEW_DIR
```

The source-checkout command is `uv run metes-review analyze-corridor REQUEST.json --output-dir NEW_DIR`; the adapter is `mp_review.corridor.analyze_corridor_file`. A completed analysis returns `needs_review`/exit 1, including unsupported constructions. Invocation/schema errors return `error`/exit 2.

Return actual availability, reasons, construction choices, error units/bounds, topology limits and artifact paths. The result retains raw `request.json`, canonical `corridor-request.json`, complete `corridor.json` and a final manifest. Supported results also retain centerline/boundary prepared plots and `boundary.html`. No polygon or apparently normal area is issued for an unavailable result.

When the user asks to retain a corridor with a review alternative, use the [saved corridor revision contract](../../references/revisions.md#saved-corridor-definitions). Schema `1.2` saves the exact construction input with stable identity and explicit removal; inspection and rendering recompute it from the immutable revision. Subsequent delivery can bind that revision directly. Do not create a dashboard or revision for a standalone corridor-only request.

The boundary prepared plot begins at its own origin. `boundary_origin_in_centerline_frame` is an explicit translation; `polygon` is already in the original centerline frame. Preserve this metadata and the original analytic centerline and all width definitions through later revision/export. Never overlay the normalized boundary as if it shared the centerline origin. Map use still requires independent sourced placement/CRS evidence; route a later requested provider view to [render-online-map](../render-online-map/SKILL.md). Keep corridor construction, source review, map registration and canonical verification separate. See [artifact handoffs](../../references/artifact-handoffs.md).
