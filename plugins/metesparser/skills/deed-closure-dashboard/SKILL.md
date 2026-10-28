---
name: deed-closure-dashboard
description: This skill should be used when the user explicitly asks for a deed or boundary review dashboard, interactive closure workbench, source comparison dashboard, or optional Mapbox companion to such a dashboard. A standalone plot uses plot-metes-and-bounds; a closure check uses review-metes-and-bounds.
---

# Deed closure dashboard

Build only the dashboard and stages needed for the user's requested view. Read the [dashboard playbook](references/playbook.md) for source evidence, records, calculations, workbench, and delivery guidance; read the [bundle contract](references/dashboard-bundle.md) for accepted bundle versions and outputs.

Reuse valid acquisition, selection, and calculation artifacts when source identity is unchanged. If the user supplies a prepared deed plot or map layer, retain its provenance and status; do not reread the PDF or repeat preparation. For a requested standalone deed plot or map-layer preparation, use [plot-metes-and-bounds](../plot-metes-and-bounds/SKILL.md) or [prepare-parcel-overlay](../prepare-parcel-overlay/SKILL.md) and stop at that capability's deliverable unless a dashboard is also requested.

Compose existing artifacts using the [explicit handoff mapping](references/dashboard-bundle.md#compose-existing-plot-and-map-artifacts). Reuse plot inputs and source records, not serialized prepared geometry or engine flags. Map-preparation arrays map to their named version 1.1 bundle fields; retain the complete preparation artifact separately. The command does not import either artifact automatically. Recompute dashboard geometry before binding any requested placement to its fresh hash; standalone plot hashes are not dashboard placement hashes. Do not invent source pages, quotes, or review attestations to fill required bundle records.

After source review and bundle preparation, run the offline renderer from the project root:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" dashboard BUNDLE.json --output-dir NEW_DIR --cache-dir CACHE_DIR
```

Keep source-review, canonical engine, scenario, placement, and map-comparison status separate. Unknown bearings and source uncertainty remain visible; do not adjust record values or map placement to force closure or fit. The renderer does not perform native document reading. Stop after delivering the requested local dashboard and its source/calculation/render artifacts; do not publish or share unless separately requested. See [artifact handoffs](../../references/artifact-handoffs.md).

For an explicitly requested Mapbox companion, follow the [optional renderer procedure](references/dashboard-bundle.md#optional-mapbox-companion) after the same source/plot/overlay composition. Reuse existing source-reading and registration evidence; freshly validate dashboard geometry and placements. Preserve the offline view and report online availability separately. Provider activation requires the page's explicit Connect action with a runtime public token; never persist a token or promote verification because a map displays.

For an explicitly requested in-chat Mapbox MCP preview, read the [MCP handoff procedure](references/mapbox-mcp.md). Reuse an existing online-prepared dashboard directory; the deterministic adapter validates its retained artifacts and prepares vector-only arguments. Inspect the connected `render_map_tool` schema before passing the generated JSON unchanged as the terminal visualization call. Report raster omissions and client/provider acceptance separately; an absent or incompatible tool leaves the local artifacts usable.
