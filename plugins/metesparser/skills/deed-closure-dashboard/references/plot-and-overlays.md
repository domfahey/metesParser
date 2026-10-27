# Deed plot and map overlays

Read this reference when adding a deed plot, tax parcel layer, or scanned map to a dashboard. The plotting data contract is version 1.1; version 1.0 remains a supported deed-only path. Consult [dashboard-bundle.md](dashboard-bundle.md) for bundle fields and artifacts.

## Deed plot is the primary evidence

The plot is derived from source-linked calls and calculation semantics. It may contain analytic straight lines or circular arcs, unresolved-call records, and partial chains. If displacement becomes unknown, retain the known prefix and stop that chain; do not connect later courses across the gap. Cardinal-only wording remains without a numeric azimuth. A chord can be shown as a chord when a curve is unresolved, but must not be represented as the curved boundary. Do not close a partial path for display or infer a full-parcel area from it. A complete traverse's closure gap is an annotation, not a deed course.

Keep record geometry and any placed display geometry distinct. A local-axis arrow is not geographic north. Show the basis for any grid/true/magnetic orientation and label unresolved basis. Keep canonical verification status, deed misclosure, map fit residuals, and source accuracy separate. Dashboard outputs remain advisory and do not create verified CSVs.

## Optional vector map layers

Map and assessment parcels are contextual evidence, not surveyed or legal boundaries. Preserve the source filename or URL/provider, retrieval time and source date (including explicit unknowns), response/file hash, native CRS, units, axis order, feature IDs, and processing history. A hash establishes byte identity, not review or accuracy. Preserve supplied source bytes and do not silently repair invalid rings. Never treat a source status, tax status, or visual overlap as deed geometry.

Only compare coordinates in an explicitly compatible scene with a known linear unit and declared deed foot definition (`international_ft` or `us_survey_ft`). A scene display name does not establish compatibility. CRS/unit conversion and ground/grid treatment must be recorded separately; never assume a ground-to-grid factor. Geographic longitude/latitude degrees are not feet.

Install optional map dependencies with `uv sync --extra geo` in this repository (or install `mp-review[geo]` in a separate environment). Projected scene validation, vector reprojection, and decoded raster validation require this extra. Deed-only and local supplied-vector dashboards do not. The default plugin build includes these dependencies; `--without-geo` builds a smaller runtime with actionable errors for unsupported map preparation. Local scenes must omit `crs`; projected scenes must declare an actual projected CRS and matching linear units.

Import supplied vector data with `uv run metes-review import-overlay INPUT --format geojson|projected-layer --target-crs CRS [--source-crs CRS] --output NEW_LAYER.json`. RFC 7946 GeoJSON has fixed WGS84 longitude/latitude; do not override it or treat coordinates as feet. Projected-layer JSON must declare `source_crs`, `units`, `axis_order: "xy"`, `basis: "grid"`, and feature geometry. The output contains `scenes`, `map_sources`, `vector_layers`, conversion operation metadata, and retained original bytes. Merge the actual returned objects into the version 1.1 dashboard bundle, resolving IDs and preserving provenance, then render the bundle. Import output alone is not an overlay in the dashboard.

For a rigid placement, first prepare and render the deed-only source bundle. Read the resulting `plot-geometry.json` and use that calculation's exact `geometry_hash` in `placements[].geometry_hash`; then add an explicit scene and placement and rerender. If any source call or calculation changes, reprepare geometry and revalidate the placement. Placement allows translation and clockwise rotation only: no scaling, shear, reflection, snapping, endpoint replacement, closure adjustment, or automatic boundary fit. Mark map alignment `approximate` unless supported position and orientation, compatible units, and a documented basis justify `referenced`. One position tie alone is insufficient. A convincing overlay on an assessment parcel remains approximate.

Compare only explicitly named point correspondences in the same supported linear scene. Present each residual vector, RMS, and maximum norm, with all point names. If alignment prerequisites are missing, report `not_comparable`. Residuals are not survey accuracy or deed closure.

`comparison_specs` holds the named correspondence inputs; the calculated comparison is derived output, not a source reading. `plot_view` is presentation only: layer visibility, opacity, labels, and optional viewport. The viewport tuple is `(min_x, min_y, width, height)` in scene coordinates, with positive width and height. Pan/zoom/view changes cannot alter deed geometry, placement, or verification.

An empty `visible_layer_ids` uses the default of showing all supplied layers; a nonempty list selects which layers start visible. Runtime checkboxes can hide every layer. Delivery retains supplied original assets under `assets/<source-id>.bin`, independent of untrusted original filenames.

## Frozen advisory scenarios

Freeze the baseline geometry hash and placement before scenario work. Each scenario may derive a new placement bound to its scenario geometry hash, with the original baseline geometry hash, baseline placement ID, and scenario ID retained. Apply the same rigid transform without refitting. A changed recorded source call invalidates the old geometry-bound placement and requires explicit re-preparation; this is different from deriving a scenario placement. Neither an overlay nor a scenario can improve engine status or authorize export.

## Scanned map registration

For supported supplied PNG/JPEG/WebP scans, preserve the original bytes/hash and dimensions, scene/unit, registration method/matrix, named controls, and fit/checkpoint residuals. Register using `uv run metes-review register-raster IMAGE --controls CONTROLS.json --output NEW_RASTER.json`. The controls file contains a `scene` plus `controls` (`id`, `pixel`, `scene`, and `role`); alternatively it may supply a six-number affine `matrix` in order `(a,b,c,d,e,f)` for `x=a*u+b*v+c`, `y=d*u+e*v+f`. Integer pixel coordinates denote pixel centers: raster outer edges are at `(-0.5,-0.5)` and `(width-0.5,height-0.5)`. Fit controls participate in calibration; independent checkpoints do not. Three noncollinear fit controls determine an affine transform but provide no independent accuracy check. Keep registration approximate, transform the map rather than the deed, and retain crop/resize provenance. A printed scale or visual corner selection alone does not establish referenced placement. Do not warp a scan until it matches the deed. Merge the command's scene, map source, and raster layer into the version 1.1 bundle and render that bundle.

## Official parcel snapshots

The optional provider adapter is limited to official NJGIN parcel retrieval by exact identifiers. Run `uv run metes-review fetch-parcel --municipality 4DIGIT_CODE --block BLOCK --lot LOT [--qualifier QUALIFIER --feature-id OID] --target-crs CRS --output NEW_LAYER.json`. Municipality code is used to avoid name collisions; ambiguous results require an explicit feature ID. On a unique or explicitly selected result, merge the objects under its `overlay` key into a version 1.1 bundle; retain the full command output with response/provenance records too. Empty or ambiguous results do not contain a selected overlay. A successful local fixture test is not live acquisition; report live provider use only when it actually ran. Preserve the returned source date or unknown value, retrieval time, feature identifiers, response hash, and processing details. Never add taxpayer/owner information solely to support plotting.

## Limits and acceptance status

An offline HTML render or local package smoke does not prove native document reading, actual Claude/Cowork UI acceptance, or live provider acquisition. Report each such gate as passed, failed, not run, or blocked based on its own evidence. Do not claim live parcel acquisition unless a provider command actually ran and retained the response and provenance. NJGIN specifically disclaims assessment parcel data as survey or legal boundary data; carry that caveat with parcel overlays.
