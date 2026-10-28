# Plot and overlay reference (compatibility path)

Map source import and raster registration instructions now live in [Prepare Parcel Overlay](../../prepare-parcel-overlay/references/overlay-preparation.md). Keep this path for existing links; consult it when adding map evidence to a dashboard.

## Dashboard placement and comparison

The renderer supports explicit placements and named-point residual comparisons. It does not automatically identify matching corners or infer parcel alignment. Finalize the dashboard source/call/calculation/frame inputs and prepare the bundle without placements first, then bind a placement to that dashboard calculation's freshly computed `geometry_hash`. A standalone `plot-geometry.json` hash is not interchangeable, even for the same XY coordinates. Use the [explicit artifact composition sequence](dashboard-bundle.md#compose-existing-plot-and-map-artifacts); do not submit serialized geometry as a source bundle. A changed call set or calculation invalidates the old placement. Placement permits translation and clockwise rotation only: no scaling, shear, reflection, snapping, endpoint replacement, closure adjustment, or automatic fit. Mark alignment `approximate` unless supported position/orientation, compatible units, and a documented basis justify `referenced`; one position tie is insufficient.

A `placements` entry identifies `id`, `calculation_id`, fresh `geometry_hash`, imported `scene_id`, `rotation_deg`, `translation` (scene XY), `status`, and a nonempty `rationale`. A `referenced` entry additionally requires actual `position_evidence` and `orientation_evidence`; preserve their supporting records. The scene's units and deed foot definition must be compatible. Without sufficient transform evidence, keep the layer independent rather than assuming an alignment.

Compare only explicitly named point correspondences in the same supported linear scene. Present residual vectors, RMS, maximum norm, and point names. If prerequisites are missing, report `not_comparable`. Residuals are not survey accuracy or deed closure. Keep any scenario placement tied to scenario geometry while retaining baseline geometry hash, placement ID, and scenario ID; do not refit it.

`plot_view` is presentation only. Visibility, opacity, labels, pan, zoom, and viewport cannot alter geometry, placement, or verification. An empty `visible_layer_ids` uses the default of showing all supplied layers; nonempty IDs choose the initially visible layers. See [dashboard bundle](dashboard-bundle.md) for the authoritative bundle contract.

## Optional geographic display

The [online handoff](../../../references/artifact-handoffs.md#optional-online-map-handoff) defines the Mapbox companion's evidence and invalidation boundary. Reuse the existing projected scene, registered scan, and supported explicit deed placement; a basemap cannot supply missing position/orientation evidence. The [render-online-map configuration/preview procedure](../../render-online-map/references/local-viewer.md) covers optional dependencies, localhost serving, runtime tokens, and offline fallback.
