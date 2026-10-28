# Optional Mapbox MCP preview

Use this mode only when an in-chat Mapbox preview is requested. It is a mode of `render-online-map`; it does not perform document reading or prepare new geographic evidence. The local GL JS companion supports registered raster overlays and source/course review; this MCP preview carries prepared vectors only.

## Prepare the handoff

Start with an intact existing standalone `render-map ... --online-map-config CONFIG.json` directory or legacy online-prepared dashboard directory. Both retain source input, request, and provenance hashes; the configuration identifies the explicit scene through `scene_id`. If geographic evidence is missing, follow the [online companion procedure](local-viewer.md) and report the gap; never geocode an address to invent an anchor, infer coordinates from direction words, or reconstruct coordinates with an LLM.

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" mapbox-mcp EXISTING_MAP_DIR --output-dir NEW_DIR --style standard-satellite
```

`--style` accepts `standard` or `standard-satellite`; omitting it inherits the retained request's `view.style`. Use a fresh output directory and a geo-capable plugin/runtime: fresh projected-scene validation requires pyproj for CRS/unit checks. The adapter reuses retained geographic geometry without reprojection or warping; exporting this existing stage does not require rasterio. It validates input/source/provenance hashes and writes `mapbox-mcp-handoff.json` with status, omissions, and digests. It writes `mapbox-mcp-arguments.json` only when the prepared vectors are renderable. Valid processing remains `needs_review` (exit 1), including unavailable previews; malformed or inconsistent inputs return error (exit 2). Neither outcome grants verification.

The handoff is a complete fresh-render payload: `summary`, `baseStyle`, `layers`, and `legend`. Coordinates come only from the validated prepared geographic artifact. Opaque feature IDs and provenance support traceability without including verbatim deed quotes, source pages/scans, or credentials. Registered rasters are explicitly omitted because this upstream tool has no image/raster-source input. Keep the GL JS/offline links for raster and source-page review.

The local adapter refuses arguments over 48 KiB rather than simplifying geometry, splitting calls, or silently dropping vectors. Upstream's resolved output has a 51,200-byte inline threshold; its larger reference-only result requires host resource support. The local limit is conservative portability policy, not an upstream input limit. Keep the full local view when the handoff is oversized.

## Call the configured tool

The preview sends geometry, opaque IDs, and provenance to the configured Mapbox MCP server. This is a separate data path from the local GL JS page's runtime Connect action. Use it within the user's requested external preview scope; do not automatically transmit a handoff created only for local review.

1. Discover the actual connected tools and identify the upstream `render_map_tool` capability. Inspect its live `tools/list` input schema and retain the exact fully qualified tool identifier exposed by the host. Do not call the bare upstream capability name or guess a server prefix. Confirm the schema accepts the generated inline `layers`, `legend`, `summary`, and `baseStyle` fields and their values. The pinned source below is a compatibility reference, not proof of the hosted server's deployed version.
2. When the discovered tool is available and compatible, load `mapbox-mcp-arguments.json` and pass its exact object unchanged as the arguments to that fully qualified host-exposed identifier. Keep it the terminal visualization call and include all layers in that call; successive calls replace the map rather than accumulate content.
3. If discovery, schema compatibility, authentication, or the call fails, retain the handoff and local views and report the actual failure. Do not fabricate a tool result or substitute guessed coordinates. If the client lacks MCP Apps, report text/JSON availability separately from an interactive map.
4. Confirm the panel visibly renders the expected vectors before reporting interactive acceptance. Tool success alone does not establish loaded tiles, correct visual content, or source review. Preserve canonical engine, source-review, placement, registration, and display statuses.

Report local handoff validation, connected-tool compatibility/call, OAuth/provider access, and visible native-client acceptance as separate gates: passed, failed, or not run.

## Optional connection setup and upstream contract

For user-requested Claude Code connection setup, follow Mapbox's current [hosted guide](https://github.com/mapbox/mcp-server/blob/main/docs/hosted-mcp-guide.md#21-claude-code): it documents `claude mcp add --transport http mapbox-mcp-production https://mcp.mapbox.com/mcp`, then `/mcp` and the authentication flow. Setup is optional; do not edit global configuration or install a server just to prepare a local handoff. Hosted OAuth is distinct from entering a public token in the local GL JS page. Never put either credential in artifacts or tool arguments.

Compatibility was checked against upstream commit `6ee4589df5433234969bc525d9342bb7210a529f` (October 26, 2026; package metadata `0.16.1-dev`): [input schema](https://github.com/mapbox/mcp-server/blob/6ee4589df5433234969bc525d9342bb7210a529f/src/tools/render-map-tool/RenderMapTool.input.schema.ts), [render guide](https://github.com/mapbox/mcp-server/blob/6ee4589df5433234969bc525d9342bb7210a529f/docs/render-map-tool.md), and [inline threshold/host behavior](https://github.com/mapbox/mcp-server/blob/6ee4589df5433234969bc525d9342bb7210a529f/src/utils/storeMapPayload.ts). Supported layer types are `fill`, `line`, `circle`, and `symbol`; supported geometry is GeoJSON Feature/FeatureCollection with Point, LineString, Polygon, or MultiPolygon in `[longitude, latitude]` order. Layer `id`, `type`, and `data` are required; `paint`, `layout`, and `slot` are optional. Legend rows require `label`/`color`, with optional opacity in `[0,1]`. Base style is `standard` or `standard-satellite`. The upstream input schema leaves geometry internally loose, so the adapter's geographic validation remains necessary.

Upstream documents MCP Apps support for Claude Desktop, Claude Code, VS Code/GitHub Copilot, and Goose. Other clients require their own acceptance evidence; the source's ChatGPT bridge handling does not establish live ChatGPT acceptance. These contract checks do not authorize verified CSV or attest source completeness.
