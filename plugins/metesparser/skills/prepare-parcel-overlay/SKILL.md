---
name: prepare-parcel-overlay
description: Prepares a supplied vector parcel layer or scanned map as an overlay layer with provenance, including control-point raster registration. Use when the user asks to georeference a scan, "put this map behind my plot", register a raster, import GeoJSON, or overlay a parcel or assessment layer. Not for plotting deed calls (plot-metes-and-bounds), placing a deed on a map, a Mapbox view (render-online-map), or building a dashboard (deed-closure-dashboard).
metadata:
  version: "0.1.0"
---

# Prepare parcel overlay data

Plugin root: `${CLAUDE_PLUGIN_ROOT}`. Use only map evidence and preparation operations requested by the user. This capability prepares a layer; it does not locate or plot deed calls, place a deed on a map, fetch an unrequested parcel, or render a dashboard.

Check the [runtime prerequisites](../../references/usage.md#runtime-prerequisites), then read [overlay preparation](references/overlay-preparation.md) for the relevant vector import, raster registration, or supplied source operation. For “put this scan behind my plot”, follow its [guided registration and placement procedure](references/overlay-preparation.md#guided-registration-and-separate-deed-placement): collect raster controls and deed position/orientation evidence independently, then compose/render only the requested view. Preserve original bytes and source identity, record actual retrieval/source dates and unknowns, and retain CRS, units, axis order, controls, transformation, and residual details where applicable. Do not infer source status, coordinates, deed alignment, or accuracy. Assessment parcels and old scans are contextual evidence, not surveyed or legal boundaries.

Return the prepared layer and provenance artifacts, then stop. The user can request a later deed placement or dashboard as a separate stage. See [artifact handoffs](../../references/artifact-handoffs.md) for input identity, invalidation, and status boundaries.

For later requested Mapbox display, route to [render-online-map](../render-online-map/SKILL.md) and reuse this registration/import output through the [online handoff](../../references/artifact-handoffs.md#optional-online-map-handoff). Do not activate a provider, infer geographic controls, or promote registration/verification status during preparation.
