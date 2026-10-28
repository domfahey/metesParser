---
name: render-online-map
description: Renders supplied, geographically placed metes-and-bounds and map artifacts with Mapbox as a local online viewer or a requested in-chat MCP preview. Use for an online map from prepared evidence; source acquisition, parsing, verification, and registration belong to their existing capabilities.
---

# Render online map

Render the requested provider view from valid prepared artifacts. Reuse unchanged source-reading, selection, plot, import, and registration evidence; validate retained identities and placement bindings. Do not reread documents, rerun verification, or create an offline dashboard solely to render a map. If source composition or explicit placement is missing, report the missing evidence and route only the needed preparation to its owner. See [artifact handoffs](../../references/artifact-handoffs.md#optional-online-map-handoff).

Check the [runtime prerequisites](../../references/usage.md#runtime-prerequisites), then choose the requested delivery mode:

- **Local viewer:** compose a `StandaloneWebMapInput` from valid `PreparedPlot` and map artifacts, then use `render-map INPUT.json --online-map-config CONFIG.json --output-dir NEW_DIR`. Read [Mapbox local viewer](references/local-viewer.md) for token-free configuration, dependencies, rendering, and loopback preview. Provider requests begin only after the page's explicit Connect action with a runtime public token; never persist or request credentials in chat.
- **In-chat MCP preview:** read [Mapbox MCP mode](references/mapbox-mcp.md). Reuse retained geographic stages, inspect the connected tool's live schema, and submit generated arguments unchanged only within the user's external-preview request. A local handoff alone does not authorize transmission. This mode carries vectors; retain local raster/source review and report omissions.

Use shared Python contracts and adapters; introduce no parsing, bearing, geometry, projection, or verification logic in instructions. Preserve verbatim source values, unknown bearings, explicit CRS/units and position/orientation evidence. Never geocode an address to invent placement, infer a location from direction words, or align a deed to imagery.

Keep source-review, canonical verification, plot, placement, registration, and geographic availability statuses separate. Display readiness (`ready`, `partial`, `unavailable`) and map fit cannot promote verification or authorize verified CSV. Deed misclosure, scan residuals, projection accuracy, and display tolerance are distinct measures.

Stop at the requested local artifacts or MCP preview. Report local preparation, connected-tool compatibility/call, authentication/provider access, and visible client acceptance as separate passed, failed, blocked, or not-run gates. Do not publish, set up a connection, fetch unrelated data, or switch delivery modes unless requested.
