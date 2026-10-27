---
name: prepare-parcel-overlay
description: Prepare a supplied vector parcel layer or scanned map for later use when the user asks to import, register, or validate map evidence. Returns layer and provenance artifacts without aligning a deed or building a dashboard.
---

# Prepare parcel overlay data

Use only map evidence and preparation operations requested by the user. This capability prepares a layer; it does not locate or plot deed calls, place a deed on a map, fetch an unrequested parcel, or render a dashboard.

Read [overlay preparation](references/overlay-preparation.md) for the relevant vector import, raster registration, or supplied source operation. Preserve original bytes and source identity, record actual retrieval/source dates and unknowns, and retain CRS, units, axis order, controls, transformation, and residual details where applicable. Do not infer source status, coordinates, deed alignment, or accuracy. Assessment parcels and old scans are contextual evidence, not surveyed or legal boundaries.

Return the prepared layer and provenance artifacts, then stop. The user can request a later deed placement or dashboard as a separate stage. See [artifact handoffs](../../references/artifact-handoffs.md) for input identity, invalidation, and status boundaries.
