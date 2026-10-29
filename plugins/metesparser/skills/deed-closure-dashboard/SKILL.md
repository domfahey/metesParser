---
name: deed-closure-dashboard
description: This skill should be used when the user explicitly asks for a deed or boundary review dashboard, interactive closure workbench, source comparison dashboard. A standalone plot uses plot-metes-and-bounds; an online map uses render-online-map; a closure check uses review-metes-and-bounds.
---

# Deed closure dashboard

Build only the dashboard and stages needed for the user's requested view. Read the [dashboard playbook](references/playbook.md) for source evidence, records, calculations, workbench, and delivery guidance; read the [bundle contract](references/dashboard-bundle.md) for accepted bundle versions and outputs.

Deliver with the short [current controls guide](references/playbook.md#current-controls-and-delivery) and the [resume summary](../../references/artifact-handoffs.md#artifact-inspection-and-resume); do not promise controls or persistence the delivered runtime does not support.

Read additional procedures only for the requested features:

- Source reading or selection: [source preparation](../../references/source-preparation.md).
- Relative-angle calculations: [contract and example](references/relative-analysis.md).
- Map placement or comparison: [plot and overlays](references/plot-and-overlays.md).
- Presentation choices: [example patterns](references/example-patterns.md).
- Saved alternatives, recovery and supported source corrections: [revision workflow](../../references/revisions.md).

Reuse valid acquisition, selection, and calculation artifacts when source identity is unchanged. If the user supplies a prepared deed plot or map layer, retain its provenance and status; do not reread the PDF or repeat preparation. For a requested standalone deed plot or map-layer preparation, use [plot-metes-and-bounds](../plot-metes-and-bounds/SKILL.md) or [prepare-parcel-overlay](../prepare-parcel-overlay/SKILL.md) and stop at that capability's deliverable unless a dashboard is also requested.

Compose existing artifacts using the [explicit handoff mapping](references/dashboard-bundle.md#compose-existing-plot-and-map-artifacts). Reuse plot inputs and source records, not serialized prepared geometry or engine flags. Map-preparation arrays map to their named version 1.1 bundle fields; retain the complete preparation artifact separately. The command does not import either artifact automatically. Recompute dashboard geometry before binding any requested placement to its fresh hash; standalone plot hashes are not dashboard placement hashes. Do not invent source pages, quotes, or review attestations to fill required bundle records.

Check the [runtime prerequisites](../../references/usage.md#runtime-prerequisites). After source review and bundle preparation, run the offline renderer from the project root:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" dashboard BUNDLE.json --output-dir NEW_DIR --cache-dir CACHE_DIR
```

Keep source-review, canonical engine, scenario, placement, and map-comparison status separate. Unknown bearings and source uncertainty remain visible; do not adjust record values or map placement to force closure or fit. The renderer does not perform native document reading. Stop after delivering the requested local dashboard and its source/calculation/render artifacts; do not publish or share unless separately requested. See [artifact handoffs](../../references/artifact-handoffs.md).

When the dashboard includes supported lines or circular arcs, its recorded diagnosis panel reports residual sensitivities separately from the immutable canonical calculation. Browser scenario diagnosis retains its own supported-input limits. Neither changes record calls or export eligibility; unsupported geometry stays explicitly unavailable. For a standalone diagnostic request, use the [closure diagnosis command and contract](../../references/closure-diagnostics.md). If the requested dashboard bundle's freshness is unclear, run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" inspect-artifacts BUNDLE_DIR --requested-stage dashboard` before deciding which upstream stages to reuse; inspection is read-only and advisory (exit 1 on completion).

For a requested online map alongside the dashboard, finish source/bundle assembly and explicit placement evidence, then delegate to [render-online-map](../render-online-map/SKILL.md). That capability owns local Mapbox configuration/preview and in-chat MCP delivery; this workflow owns the source-grounded dashboard composition. Reuse unchanged artifacts and retain the offline dashboard. A request for only an online map goes directly to that renderer and does not require building a dashboard.
