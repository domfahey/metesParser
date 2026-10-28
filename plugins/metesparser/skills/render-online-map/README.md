# render-online-map

Render prepared metes-and-bounds and map evidence with Mapbox, using a local viewer or a requested vector-only in-chat MCP preview.

## Example requests

> Show these placed deed courses, parcel context, and registered tax-map scan over Mapbox in a local viewer.

> Show the vectors from this prepared online map in chat using Mapbox MCP.

## Inputs and outputs

**Inputs:** `StandaloneWebMapInput` containing a nonempty scene set and prepared plots (`request`, `geometry`, `input_hash`), source-linked map layers, or both, plus token-free `WebMapRequest` configuration. Deed geometry needs a supported placement for geographic display; map layers need a compatible declared scene and registration where applicable. A map-layer-only view needs no deed placement. Standalone placements remain approximate/unplaced. Existing valid geographic stages can be reused for MCP preview. Missing geographic evidence stays unavailable; the renderer does not acquire, parse, verify, register, geocode, or align a boundary.

**Outputs:** Local viewer/configuration and display provenance, or vector-only MCP arguments with validation/omission report. Display availability remains separate from canonical verification and source review. Local viewer tokens are runtime-only; a requested external MCP call uses the configured connection.

## Run the local renderer

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" render-map map-input.json --online-map-config online-map-config.json --output-dir online-map-new
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" serve-map online-map-new --port 8765
```

The package command is `uv run metes-review` with the same arguments. Use one command at a time. Valid preparation returns `needs_review` (exit 1); the local procedure below shows how to compose existing plot/layer artifacts without a dashboard. `mapbox-mcp EXISTING_MAP_DIR --output-dir NEW_DIR` accepts these retained stages or legacy online dashboard stages.

## Documentation

- [Skill instructions](SKILL.md)
- [Local Mapbox viewer](references/local-viewer.md)
- [Mapbox MCP mode](references/mapbox-mcp.md)
- [Artifact handoffs](../../references/artifact-handoffs.md#optional-online-map-handoff)
- [Usage and routing](../../references/usage.md)
- [Plugin changelog](../../CHANGELOG.md)
