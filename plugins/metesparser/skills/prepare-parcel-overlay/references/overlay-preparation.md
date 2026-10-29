# Prepare map evidence

Contents: [Vector layers](#vector-layers) · [Scanned map registration](#scanned-map-registration) · [Optional control picker](#optional-native-pixel-control-picker) · [Handoff boundary](#handoff-boundary) · [Later online display](#later-online-display) · [Guided registration and separate deed placement](#guided-registration-and-separate-deed-placement)

This guide covers the existing `import-overlay`, `register-raster`, and `fetch-parcel` commands. Run only the operation requested and preserve its full output/provenance. A prepared layer is not yet placed against deed geometry.

Run from the intended project root through the packaged locked-runtime launcher, as shown below. If `CLAUDE_PLUGIN_ROOT` is unavailable, locate the archive root relative to this procedure file. Honor disabled or invalid [project settings](../../../references/plugin-settings.md).

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

The rendered map evidence reports registration status, fit-control count and fit RMS, independent checkpoint count and checkpoint RMS, units, scene/CRS, source identity/date, deed bearing basis, foot definition, and placement status. With zero checkpoints, independent checkpoint accuracy is unknown; a small fitting residual is not an accuracy estimate. Numerical placement uncertainty remains unknown unless a supported measurement supplies it. Preserve `unplaced`, `approximate`, or `referenced` as recorded; do not upgrade placement based on appearance.

Projected scene validation, vector reprojection, and decoded raster validation require the `geo` extra. Local scenes omit `crs`; projected scenes declare an actual projected CRS and matching linear units. If the runtime reports the optional dependency is unavailable, report that result and stop.

## Optional native-pixel control picker

When the user wants help choosing scan pixels, prepare the optional offline picker with the same scene/controls configuration:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" pick-raster IMAGE --controls CONTROLS.json --output-dir NEW_PICKER_DIR
```

`mp_review.raster_picker.prepare_raster_picker_file` retains exact `image.png`/`image.jpg`/`image.webp` and `controls-source.json`, normalized `controls-initial.json`, `picker.html`, and a final hash manifest. Supported inputs are decoded single-frame PNG/JPEG/WebP with an explicit known-unit scene. EXIF-rotated images are refused; supply an already oriented source with its transformation provenance rather than silently changing pixel meaning. Existing controls may be empty, but the scene is required. The picker does not calibrate a scan or use deed geometry.

Open `picker.html` locally. Select a named row, or add a control and supply its name, fit/checkpoint role and independently supported scene X/Y. Click its image point; zoom and scrolling affect display only. Integer pixels denote centers, with u right/v down and outer edges at −0.5. The visible snap option records the nearest native pixel center; unchecking it allows subpixel coordinates. Scene values remain unchanged by clicks. Retain source controls and evidence; do not treat click precision as survey accuracy. Blank/incomplete rows remain visible and block the controls download rather than becoming zero coordinates.

Download `controls-picked.json`, then run the existing `register-raster` command with that file. The shared runtime fits and validates; three noncollinear fit controls are required for affine fitting, and independent checkpoints stay out of the fit. If the source supplied an affine matrix, the picker explicitly offers retaining it: checked means the runtime uses that supplied matrix and controls provide residual evidence; unchecking requests an affine fit. The original matrix/configuration stays in the retained source file in either case.

Keep the picked file and picker folder with the resulting registration artifact. Their image/control hashes, pixel convention and exact originals preserve the collection provenance. A downloaded file is not a registration result, and registration remains `approximate`. Continue with the existing composition/placement procedure only when requested; raster controls alone never place the deed.

## Handoff boundary

Return the exact command result and its output artifact paths, then stop. Existing deed plot geometry is not an input to import or registration; retain its identity for later composition without changing it. This stage prepares the supplied map evidence independently and does not align it to the deed.

If a dashboard is also requested, explicitly copy the preparation artifact's `scenes`, `map_sources`, `vector_layers`, and/or `raster_layers` arrays into the corresponding version 1.1 `DashboardBundle` fields, resolving IDs against the bundle. Preserve the complete preparation artifact alongside the dashboard: vector import's `operation` and `original_base64` are not accepted bundle fields, while the map source retains source bytes and processing history. Do not merge the entire preparation object into the bundle. The [composition example](../../deed-closure-dashboard/references/dashboard-bundle.md#compose-existing-plot-and-map-artifacts) validates this mapping without repeating import/registration.

For a map-only request, use the [standalone map composition recipe](../../render-online-map/references/local-viewer.md#compose-existing-artifacts) to reuse these arrays with valid prepared plots and separately supplied placements. No DashboardBundle or source-review records need to be invented.

Imported layers may remain unplaced context. For an explicitly requested deed placement, use the [placement sequence](../../deed-closure-dashboard/references/plot-and-overlays.md): recompute geometry from the final dashboard source/call/calculation inputs and bind the supplied transform to its fresh hash. Never transplant a standalone plot's geometry hash into a dashboard placement. Keep placement, deed verification, map residuals, and source accuracy separate; overlays or scenarios cannot improve verification status.

## Later online display

The [render-online-map capability](../../render-online-map/SKILL.md) reuses these preparation artifacts and derives warped display pixels without changing original scan bytes, controls, or registration. Its local viewer provides per-scan visibility, opacity, and accessible raise/lower controls; vectors and deed courses remain above scans. These are in-session display controls and do not change the source, registration, geometry, placement, or verification records. Retain fit residuals and independent checkpoints separately from projection/display tolerances. Local-only coordinates cannot establish a Mapbox location. Follow the [online handoff](../../../references/artifact-handoffs.md#optional-online-map-handoff); provider connection belongs to the explicitly requested online renderer, not this capability.

## Guided registration and separate deed placement

For “put this scan behind my plot using these controls”, collect only missing facts and preserve supplied evidence. Do not require a dashboard for a map-only request.

1. Identify the supplied image, source/date or unknowns, exact bytes/hash, dimensions, and any crop/resize history. Identify the target scene: local with no CRS, or an explicit projected CRS, XY axis order and matching `m`, `international_ft` or `us_survey_ft` units. Unknown feet cannot support registration/conversion. A local scene does not establish geographic location.
2. Confirm integer pixel centers, with pixel `u` right and `v` down in the supplied image, and scene XY coordinates in the declared units. Obtain uniquely named fit controls and independently measured checkpoints, each with its source/rationale retained alongside the controls file. Do not reuse fitting points as independent checkpoints. At least three noncollinear fit controls are required for affine fitting; supplied affine matrices follow the same six-number order above.
3. Author `CONTROLS.json` using the current `PlotScene` and `RasterControl` contracts, then run the documented `register-raster` command in a fresh path. The [synthetic controls example](#synthetic-controls-example) illustrates the accepted shape, not real location evidence. Keep unsupported extra evidence in companion notes rather than guessing model fields. Preserve registration output and original bytes; inspect fit and checkpoint residuals separately. A low fit RMS with poor checkpoints remains problematic; no checkpoints means independent accuracy unknown. Registration status remains `approximate`.
4. Separately establish deed placement: selected fresh plot/calculation ID and geometry hash, target scene, deed foot definition, sourced position tie and orientation/bearing-basis evidence, and the user-supported transform/rationale. Raster pixel-to-scene controls do not locate the deed's POB or establish its orientation. Without this evidence, show the scan and deed independently and name the missing tie/orientation; do not choose an address, imagery corner or direction word as an anchor.
5. Author only the permitted placement: clockwise rotation about the deed frame origin, explicit supported unit conversion, then scene-XY translation. The contract does not support scale fitting, shear, reflection, snapping or closure repair. Use `id`, `calculation_id`, fresh `geometry_hash`, `scene_id`, `rotation_deg`, `translation`, `status` and `rationale`; retain position/orientation evidence. In dashboard bundles, `referenced` additionally requires actual `position_evidence` and `orientation_evidence` plus compatible basis/units. Standalone map placements support only `approximate`/`unplaced`: evidence cannot upgrade that contract to `referenced`.
6. Compose with `compose-map` for a requested standalone map, or `compose-dashboard` for a requested dashboard. Use the fresh hashes from composition before binding placements, then the existing render command. Rebuilding revalidates both geometry/placement and independent raster registration. Report deed misclosure, fit RMS, checkpoint RMS, and map comparison/placement separately; reuse visibility, opacity and order controls only where available. The optional picker above collects pixels into this same input-file workflow; affine fitting remains in the shared runtime.

Changing controls, image bytes, scene CRS or units invalidates the raster and dependent display. Changing deed calls invalidates its geometry-bound placement and dependent display, while an unchanged independent registration remains reusable. Neither a good registration nor a visually aligned display changes source review, canonical verification or verified-export eligibility.

## Synthetic controls example

This local metric example includes three fit controls and a separate checkpoint with a visible residual. Replace it with supplied image/scene measurements; it is not real location evidence.

```json
{
  "scene": {"id": "scan-local", "name": "Synthetic local metric scene", "kind": "local", "units": "m", "axis_order": "xy", "basis": "local"},
  "controls": [
    {"id": "fit-a", "pixel": [0, 0], "scene": [100, 200], "role": "fit"},
    {"id": "fit-b", "pixel": [10, 0], "scene": [120, 200], "role": "fit"},
    {"id": "fit-c", "pixel": [0, 10], "scene": [100, 180], "role": "fit"},
    {"id": "check-d", "pixel": [10, 10], "scene": [125, 180], "role": "checkpoint"}
  ]
}
```
