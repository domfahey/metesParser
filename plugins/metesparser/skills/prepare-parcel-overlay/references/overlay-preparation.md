# Prepare map evidence

This guide covers the existing `import-overlay`, `register-raster`, and `fetch-parcel` commands. Run only the operation requested and preserve its full output/provenance. A prepared layer is not yet placed against deed geometry.

Run from the intended project root through the plugin's locked-runtime launcher, as shown below. If `CLAUDE_PLUGIN_ROOT` is unavailable, locate the plugin root relative to this skill file. In a development workspace with the package installed, `uv run metes-review` can replace `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py"`. Honor disabled or invalid [project settings](../../../references/plugin-settings.md).

## Vector layers

Map and assessment parcels are contextual evidence, not surveyed or legal boundaries. Preserve source filename or URL/provider, retrieval time, source date (including unknown), response/file hash, native CRS, units, axis order, feature IDs, and processing history. A hash establishes byte identity, not review or accuracy. Preserve supplied source bytes and do not silently repair invalid rings. Never treat source status, tax status, or visual overlap as deed geometry.

Only compare coordinates later in an explicitly compatible scene with a known linear unit and declared deed foot definition (`international_ft` or `us_survey_ft`). A scene display name does not establish compatibility. CRS/unit conversion and ground/grid treatment are separate; never assume a ground-to-grid factor. Geographic longitude/latitude degrees are not feet.

Import supplied vector data with:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" import-overlay INPUT --format geojson|projected-layer --target-crs CRS [--source-crs CRS] --output NEW_LAYER.json
```

RFC 7946 GeoJSON has fixed WGS84 longitude/latitude; do not override it or treat coordinates as feet. Projected-layer JSON must declare `source_crs`, `units`, `axis_order: "xy"`, `basis: "grid"`, and feature geometry. Output contains scenes, map sources, vector layers, conversion operation metadata, and retained original bytes. A live parcel source may be reported as acquired only if the provider command actually ran and its response/provenance were retained. Fetch official NJGIN parcels by exact identifiers only when requested:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" fetch-parcel --municipality 4DIGIT_CODE --block BLOCK --lot LOT [--qualifier QUALIFIER --feature-id OID] --target-crs CRS --output NEW_LAYER.json
```

Municipality code avoids name collisions; ambiguous results require an explicit feature ID. Preserve returned source date or unknown value, retrieval time, feature identifiers, response hash, and processing details. Do not add taxpayer/owner information solely to support plotting. NJGIN assessment parcels are not legal boundary evidence.

## Scanned map registration

For supported supplied PNG/JPEG/WebP scans, preserve original bytes/hash and dimensions, scene/unit, registration method/matrix, named controls, and fit/checkpoint residuals. Register with:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" register-raster IMAGE --controls CONTROLS.json --output NEW_RASTER.json
```

The controls file contains a `scene` plus `controls` (`id`, `pixel`, `scene`, `role`); alternatively provide a six-number affine `matrix` in order `(a,b,c,d,e,f)` for `x=a*u+b*v+c`, `y=d*u+e*v+f`. Integer pixel coordinates are pixel centers; raster outer edges are `(-0.5,-0.5)` and `(width-0.5,height-0.5)`. Fit controls calibrate; independent checkpoints do not. Three noncollinear fit controls determine an affine transform but provide no independent accuracy check. Keep registration approximate and preserve crop/resize provenance. A printed scale or visual corner selection alone does not establish referenced placement. Do not warp a scan until it matches deed geometry.

Projected scene validation, vector reprojection, and decoded raster validation require the `geo` extra. Local scenes omit `crs`; projected scenes declare an actual projected CRS and matching linear units. If the runtime reports the optional dependency is unavailable, report that result and stop.

## Handoff boundary

Return the exact command result and its output artifact paths, then stop. Existing deed plot geometry is not an input to import or registration; retain its identity for later composition without changing it. This stage prepares the supplied map evidence independently and does not align it to the deed.

If a dashboard is also requested, explicitly copy the preparation artifact's `scenes`, `map_sources`, `vector_layers`, and/or `raster_layers` arrays into the corresponding version 1.1 `DashboardBundle` fields, resolving IDs against the bundle. Preserve the complete preparation artifact alongside the dashboard: vector import's `operation` and `original_base64` are not accepted bundle fields, while the map source retains source bytes and processing history. Do not merge the entire preparation object into the bundle. The [composition example](../../deed-closure-dashboard/references/dashboard-bundle.md#compose-existing-plot-and-map-artifacts) validates this mapping without repeating import/registration.

Imported layers may remain unplaced context. For an explicitly requested deed placement, use the [placement sequence](../../deed-closure-dashboard/references/plot-and-overlays.md): recompute geometry from the final dashboard source/call/calculation inputs and bind the supplied transform to its fresh hash. Never transplant a standalone plot's geometry hash into a dashboard placement. Keep placement, deed verification, map residuals, and source accuracy separate; overlays or scenarios cannot improve verification status.

## Later online display

The optional dashboard companion reuses these preparation artifacts and derives warped display pixels without changing original scan bytes, controls, or registration. Retain fit residuals and independent checkpoints separately from projection/display tolerances. Local-only coordinates cannot establish a Mapbox location. Follow the [online handoff](../../../references/artifact-handoffs.md#optional-online-map-handoff); provider connection belongs to the explicitly requested dashboard renderer, not this capability.
