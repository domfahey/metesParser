"""Prepare one immutable review snapshot; publish package manifest last."""

from __future__ import annotations

import hashlib
import importlib.metadata
import os
import re
import secrets
import shutil
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NamedTuple

from mp_models.dashboard import DashboardBundle
from mp_models.delivery import (
    DeliveryItem,
    DeliveryManifest,
    DeliveryMetric,
    DeliveryOmission,
    DeliveryPrimitive,
    DeliveryRequest,
    DeliverySnapshot,
)
from mp_models.plot import XY, LinearUnit, PlotPlacement, PlotScene
from mp_models.plot_request import PlotCall, PlotRequest, PreparedPlot
from mp_verify.dashboard import _hash, _json
from mp_verify.plot import prepare_plot, transform_point, unit_factor, validate_plot_placement
from mp_verify.scene import validate_scene

from .dashboard import _load
from .json_input import InvalidInputJson, parse_json
from .revisions import _write_once, load_revision

if TYPE_CHECKING:
    from .webmap_projection import WebMapProjection


def _recorded_plots(bundle: DashboardBundle) -> dict[str, Any]:
    return {
        spec.id: prepare_plot(
            PlotRequest(
                title=bundle.title,
                calculation_id=spec.id,
                foot_definition=spec.frame.foot_definition,
                relative=spec.relative,
                calls=tuple(
                    PlotCall(
                        id=c.id,
                        call=c.call,
                        occurrence_id=c.occurrence_id,
                        page_id=c.page_id,
                        quote=c.quote,
                    )
                    for c in bundle.calls
                    if c.occurrence_id == spec.occurrence_id
                ),
            )
        )
        for spec in bundle.calculations
    }


def _scale(native: LinearUnit, target: LinearUnit) -> float:
    if native == target:
        return 1.0
    return float(unit_factor(native, target))


def prepare_delivery(
    bundle: DashboardBundle,
    revision_dir: Path | str,
    request: DeliveryRequest | dict[str, Any],
    *,
    exporter_version: str = "delivery-2",
) -> DeliverySnapshot:
    """Replay published input and freeze selected membership, transforms and omissions.

    Visible=false explicitly excludes geometry from every output while retaining
    its request membership. Opacity=0 retains all CAD/GIS geometry and tables.

    ``exporter_version="delivery-1"`` exists only to replay packages published by
    the earlier exporter; new packages always use the current version.
    """
    return _prepare(bundle, revision_dir, request, exporter_version=exporter_version)[0]


def _prepare(
    bundle: DashboardBundle,
    revision_dir: Path | str,
    request: DeliveryRequest | dict[str, Any],
    *,
    exporter_version: str = "delivery-2",
    recorded_omissions: Sequence[DeliveryOmission] | None = None,
) -> tuple[DeliverySnapshot, _GeoJSONArea | None]:
    """``prepare_delivery`` plus the GeoJSON projection/classification it computed.

    Returned so one publish builds the projection group once. Replay passes the
    package's ``recorded_omissions``: its GeoJSON area-of-use omissions are then
    accepted as recorded (validated against the request) instead of re-running the
    installation-dependent operation/area choice, and no projection is built.
    """
    if exporter_version not in ("delivery-1", "delivery-2"):
        raise ValueError("Unsupported delivery exporter version")
    legacy = exporter_version == "delivery-1"
    if isinstance(request, DeliveryRequest):
        request = request.model_dump(mode="json")
    request = DeliveryRequest.model_validate(request)
    revision_path = Path(revision_dir)
    revision = load_revision(bundle, revision_path)
    if revision.state != "parsed":
        raise ValueError("Unresolved published draft cannot export last-valid geometry")
    if (
        revision.revision.id != request.revision_id
        or revision.revision.generation != request.revision_generation
        or revision.revision.baseline != request.baseline
    ):
        raise ValueError("Delivery revision/baseline identity mismatch")
    revision_corridor_bindings = {
        binding.id: binding
        for binding in request.source_bindings
        if binding.revision_corridor_id is not None
    }
    revision_corridor_inputs: dict[str, tuple[Any, bytes]] = {}
    if revision_corridor_bindings:
        manifest_path = revision_path / "manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ValueError("Revision corridor source requires its published manifest")
        manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        declarations = {item.id: item for item in revision.revision.corridors}
        prepared_corridors = {item.id: item for item in revision.corridor_results}
        for binding_id, binding in revision_corridor_bindings.items():
            if binding.manifest_sha256 != manifest_sha256:
                raise ValueError("Revision corridor manifest differs from explicit binding")
            corridor_id = binding.revision_corridor_id
            assert corridor_id is not None
            declaration = declarations.get(corridor_id)
            prepared_corridor = prepared_corridors.get(corridor_id)
            if declaration is None or declaration.action != "retain":
                raise ValueError("Selected revision corridor is missing or removed")
            if (
                prepared_corridor is None
                or prepared_corridor.state != "computed"
                or prepared_corridor.request is None
                or prepared_corridor.result is None
            ):
                raise ValueError("Selected revision corridor is unresolved or unsupported")
            result = prepared_corridor.result
            if (
                prepared_corridor.request.id != corridor_id
                or result.request.id != corridor_id
                or result.availability != "supported"
                or result.boundary is None
                or result.centerline is None
            ):
                raise ValueError("Selected revision corridor identity or geometry is unsupported")
            if (
                binding.input_sha256 != result.input_sha256
                or binding.geometry_sha256 != result.boundary.geometry.geometry_hash
            ):
                raise ValueError(
                    "Revision corridor input/geometry hash differs from explicit binding"
                )
            if binding.layer_id != result.boundary.request.calculation_id:
                raise ValueError("Revision corridor layer identity differs from selected boundary")
            declaration = declarations[corridor_id]
            revision_corridor_inputs[binding_id] = (
                result,
                declaration.raw_request_json.encode("utf-8"),
            )
    plots = {g.calculation_id: g.plot for g in revision.current_geometry}
    if request.geometry == "recorded" and revision.revision.kind == "scenario":
        plots = _recorded_plots(bundle)
    prepared_call_status = {record.id: record.source_status for record in revision.prepared_calls}
    drawing_recorded_inputs = (
        request.geometry == "recorded" and revision.revision.kind == "scenario"
    )
    original_calls = {c.id: c.call for c in bundle.calls}
    calculations = {c.id: c for c in bundle.calculations}
    vectors = {layer.id: layer for layer in bundle.vector_layers}
    rasters = {layer.id: layer for layer in bundle.raster_layers}
    placements = {p.id: p for p in bundle.placements}
    if len({p.id for p in request.placements}) != len(request.placements):
        raise ValueError("Duplicate supplied placement identity")
    placements.update({p.id: p for p in request.placements})
    scenes = {s.id: s for s in bundle.scenes}
    for supplied_scene in request.scenes:
        if supplied_scene.id in scenes and supplied_scene != scenes[supplied_scene.id]:
            raise ValueError("Supplied scene identity conflicts with baseline scene")
        scenes[supplied_scene.id] = supplied_scene
    scene = scenes.get(request.scene_id) if request.scene_id else None
    if request.coordinate_mode == "placed":
        if scene is None:
            raise ValueError("Unknown requested placement scene")
        # Validate the selected coordinate frame even for SVG/CAD and context-only
        # delivery; geographic export is not the first CRS/unit validation gate.
        validate_scene(scene)
    if "geojson" in request.formats and (
        scene is None or scene.kind != "projected" or request.coordinate_mode != "placed"
    ):
        raise ValueError(
            "Geographic GeoJSON requires an explicitly projected scene and placed coordinates"
        )
    items = []
    metrics = []
    omissions = []
    derived_sources = []
    if (
        request.required_appearance
        and request.labels
        and any(f in request.formats for f in ("dxf", "geojson"))
    ):
        raise ValueError(
            "Required drawn labels/appearance are unsupported in requested CAD/GIS format"
        )
    for fmt in request.formats:
        if fmt not in ("dxf", "geojson"):
            continue
        if legacy:
            # delivery-1 replay: labels-only omission with the original wording.
            if request.labels:
                omissions.append(
                    DeliveryOmission(
                        format=fmt,
                        reason="Drawn labels and presentation rotation are omitted; source values and identity remain in properties/sidecars",
                    )
                )
            continue
        # CAD/GIS carry real coordinates: never rotate them, but always disclose it.
        omitted = []
        if request.labels:
            omitted.append("Drawn labels")
        if request.presentation_rotation_deg != 0:
            omitted.append("Presentation rotation")
        if omitted:
            omissions.append(
                DeliveryOmission(
                    format=fmt,
                    reason=f"{' and '.join(omitted)} omitted (coordinates are not rotated); "
                    "source values and identity remain in properties/sidecars",
                )
            )
    for selection in request.layers:
        if not selection.visible:
            omissions.append(
                DeliveryOmission(
                    format="all",
                    layer_id=selection.id,
                    reason="Excluded by explicit frozen visible=false; membership remains recorded",
                )
            )
            items.append(DeliveryItem(selection=selection))
            continue
        try:
            if selection.kind in {"corridor", "plss_reference"}:
                from .delivery_sources import prepare_delivery_source

                binding = next(b for b in request.source_bindings if b.layer_id == selection.id)
                corridor_input = revision_corridor_inputs.get(binding.id)
                item, source_record, metric = prepare_delivery_source(
                    binding,
                    selection,
                    request,
                    bundle,
                    corridor_result=corridor_input[0] if corridor_input else None,
                    corridor_raw_request=corridor_input[1] if corridor_input else None,
                )
                items.append(item)
                derived_sources.append(source_record)
                if metric is not None:
                    metrics.append(metric)
            elif selection.kind == "calculation":
                if selection.id not in plots:
                    raise ValueError("Selected calculation has no current geometry")
                plot = plots[selection.id]
                if plot.geometry.completeness != "complete":
                    raise ValueError("Selected plot contains unresolved geometry")
                placement = None
                original_geometry_hash = None
                if request.coordinate_mode == "placed":
                    if selection.placement_id not in placements:
                        raise ValueError("Explicit fresh placement identity is required")
                    placement = placements[selection.placement_id]
                    if _hash(placement.model_dump(mode="json")) != selection.placement_sha256:
                        raise ValueError("Placement hash mismatch")
                    if (
                        placement.calculation_id != selection.id
                        or placement.scene_id != request.scene_id
                        or placement.status == "unplaced"
                    ):
                        raise ValueError("Placement calculation/scene/status mismatch")
                    assert scene is not None
                    if placement.geometry_hash != plot.geometry.geometry_hash:
                        from mp_verify.plot import _geometry

                        spec = calculations[selection.id]
                        original = _geometry(bundle, spec, None)
                        native_original = _recorded_plots(bundle)[selection.id]
                        if (
                            spec.method != "canonical"
                            or (request.geometry == "scenario" and bool(revision.revision.edits))
                            or revision.revision.kind == "source_correction"
                            or placement.geometry_hash != original.geometry_hash
                            or plot.geometry.geometry_hash != native_original.geometry.geometry_hash
                            or (original.primitives, original.chains, original.unresolved)
                            != (
                                plot.geometry.primitives,
                                plot.geometry.chains,
                                plot.geometry.unresolved,
                            )
                        ):
                            raise ValueError(
                                "Stale placement: changed revision requires fresh placement"
                            )
                        validate_plot_placement(
                            original,
                            placement,
                            scene,
                            native_units=plot.request.foot_definition,
                            orientation_supported=True,
                        )
                        original_geometry_hash = placement.geometry_hash
                        placement = placement.model_copy(
                            update={"geometry_hash": plot.geometry.geometry_hash}
                        )
                    validate_plot_placement(
                        plot.geometry,
                        placement,
                        scene,
                        native_units=plot.request.foot_definition,
                        orientation_supported=calculations[selection.id].frame.basis
                        == "recorded_bearings",
                    )
                native = (
                    scene.units if placement is not None and scene else plot.request.foot_definition
                )
                factor = _scale(native, request.units)

                def point(
                    p: XY,
                    placement: PlotPlacement | None = placement,
                    plot: PreparedPlot = plot,
                    scene: PlotScene | None = scene,
                    factor: float = factor,
                ) -> XY:
                    value = (
                        transform_point(
                            p,
                            placement,
                            native_units=plot.request.foot_definition,
                            scene_units=scene.units,
                        )
                        if placement is not None and scene
                        else p
                    )
                    return value[0] * factor, value[1] * factor

                source = {c.id: c.call for c in plot.request.calls}
                primitives = []
                for primitive in plot.geometry.primitives:
                    call = source[primitive.call_id]
                    original_call = original_calls.get(primitive.call_id)
                    a, b = point(primitive.start), point(primitive.end)
                    center = point(primitive.center) if primitive.center else None
                    radius = (
                        ((a[0] - center[0]) ** 2 + (a[1] - center[1]) ** 2) ** 0.5
                        if center
                        else None
                    )
                    full_factor = _scale(plot.request.foot_definition, request.units)
                    primitives.append(
                        DeliveryPrimitive(
                            kind=primitive.kind,
                            call_id=primitive.call_id,
                            layer_id=selection.id,
                            start=a,
                            end=b,
                            center=center,
                            radius=radius,
                            sweep_deg=primitive.sweep_deg,
                            curve_dir=primitive.curve_dir,
                            length=primitive.length_ft * full_factor,
                            recorded_bearing_deg=original_call.bearing_azimuth_deg_from_north
                            if original_call
                            else None,
                            recorded_distance_ft=original_call.distance_ft
                            if original_call
                            else None,
                            selected_bearing_deg=call.bearing_azimuth_deg_from_north
                            if call
                            else None,
                            selected_distance_ft=call.distance_ft if call else None,
                            input_status=(
                                "recorded"
                                if drawing_recorded_inputs
                                else prepared_call_status.get(primitive.call_id, "recorded")
                            ),
                        )
                    )
                items.append(
                    DeliveryItem(
                        selection=selection,
                        plot=plot,
                        placement=placement,
                        placement_original_geometry_hash=original_geometry_hash,
                        placement_binding_baseline_sha256=request.baseline.bundle_sha256
                        if original_geometry_hash
                        else None,
                        primitives=tuple(primitives),
                    )
                )
                geometry = plot.geometry
                area = (
                    geometry.area_sq_ft
                    if geometry.misclosure_ft is not None
                    and geometry.misclosure_ft < 0.01
                    and geometry.area_sq_ft is not None
                    and geometry.area_sq_ft > 0
                    else None
                )
                missing = [
                    name
                    for name in ("misclosure_ft", "area_sq_ft", "perimeter_ft")
                    if (area is None if name == "area_sq_ft" else getattr(geometry, name) is None)
                ]
                metrics.append(
                    DeliveryMetric(
                        calculation_id=selection.id,
                        misclosure_ft=geometry.misclosure_ft,
                        area_sq_ft=area,
                        perimeter_ft=geometry.perimeter_ft,
                        unavailable_reason="Unavailable from selected geometry: "
                        + ", ".join(missing)
                        if missing
                        else None,
                    )
                )
            else:
                if request.coordinate_mode != "placed" or scene is None:
                    raise ValueError("Context layers require explicit placed scene coordinates")
                if selection.placement_id:
                    raise ValueError(
                        "Context layers use their own registration, not deed placement"
                    )
                if selection.kind == "vector":
                    layer = vectors.get(selection.id)
                    if layer is None or layer.scene_id != scene.id:
                        raise ValueError("Unknown or cross-scene vector layer")
                    items.append(DeliveryItem(selection=selection, vector=layer))
                else:
                    raster = rasters.get(selection.id)
                    if raster is None or raster.scene_id != scene.id:
                        raise ValueError("Unknown or cross-scene raster layer")
                    from .raster_registration import validate_raster_layer

                    validate_raster_layer(raster, scene)
                    for fmt in request.formats:
                        if fmt in ("dxf", "geojson"):
                            if selection.required or request.required_appearance:
                                raise ValueError(f"Required raster cannot be represented in {fmt}")
                            omissions.append(
                                DeliveryOmission(
                                    format=fmt,
                                    layer_id=selection.id,
                                    reason="Raster embedding is outside CAD/GIS adapter; supplied raster is retained in snapshot",
                                )
                            )
                    items.append(DeliveryItem(selection=selection, raster=raster))
        except ValueError as exc:
            if selection.required or request.required_appearance:
                raise ValueError(f"{selection.id}: {exc}") from exc
            omissions.append(DeliveryOmission(format="all", layer_id=selection.id, reason=str(exc)))
            items.append(DeliveryItem(selection=selection))
    if not any(item.primitives or item.vector or item.raster for item in items):
        raise ValueError("Delivery has no selected representable content")
    geojson_area: _GeoJSONArea | None = None
    if "geojson" in request.formats and not legacy:
        geojson_area, area_omissions = _geojson_omissions(
            items, scene, request, recorded=recorded_omissions
        )
        omissions.extend(area_omissions)
    references = []
    for item in items:
        if item.plot:
            for record in item.plot.request.calls:
                references.append(
                    {
                        "call_id": record.id,
                        "occurrence_id": record.occurrence_id,
                        "page_id": record.page_id,
                        "quote": record.quote,
                        "source_reference": record.source_reference,
                    }
                )
    snapshot = DeliverySnapshot(
        exporter_version=exporter_version,  # type: ignore[arg-type]
        request=request,
        request_sha256=_hash(request.model_dump(mode="json")),
        revision_sha256=_hash(revision.revision.model_dump(mode="json")),
        items=tuple(items),
        metrics=tuple(metrics),
        omissions=tuple(omissions),
        source_references=tuple(references),
        derived_sources=tuple(derived_sources),
        selected_revision_calls=tuple(
            record.model_dump(mode="json")
            for record in getattr(revision, "prepared_calls", ())
            if any(
                item.plot
                and any(c.occurrence_id == record.occurrence_id for c in item.plot.request.calls)
                for item in items
            )
        ),
        unresolved_findings=tuple(e.message for e in revision.errors)
        + tuple(
            f"{record.id}: {record.reading_note or record.reading_status}"
            for record in bundle.calls
            if record.reading_status != "certain"
            and any(
                item.plot and any(c.id == record.id for c in item.plot.request.calls)
                for item in items
            )
        )
        + (
            ("Supplied transcription corrections remain unreviewed source excerpts",)
            if revision.revision.kind == "source_correction"
            else ()
        ),
        software_versions=tuple(
            (name, importlib.metadata.version(name))
            for name in ("mp-export",)
            + (("reportlab",) if "pdf" in request.formats else ())
            + (("ezdxf",) if "dxf" in request.formats else ())
            + (("pyproj",) if "geojson" in request.formats else ())
        ),
        crs=scene.crs if scene else None,
        scene_units=scene.units if scene else None,
    )
    return snapshot, geojson_area


def _ring_area(ring: list[Any]) -> float:
    return float(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:], strict=False)) / 2)


def _orient_rfc7946(geometry: dict[str, Any]) -> None:
    """RFC 7946: exterior rings counterclockwise, holes clockwise (done before hashing)."""
    if geometry.get("type") == "Polygon":
        polygons = [geometry["coordinates"]]
    elif geometry.get("type") == "MultiPolygon":
        polygons = geometry["coordinates"]
    else:
        return
    for rings in polygons:
        for index, ring in enumerate(rings):
            area = _ring_area(ring)
            if (index == 0 and area < 0) or (index > 0 and area > 0):
                rings[index] = ring[::-1]


# Fixed reason text: the frozen snapshot records it and GeoJSON rendering re-derives it.
_OUTSIDE_AREA = (
    "Outside the deed-selected coordinate operation's area of use; omitted from GeoJSON "
    "and retained in scene-coordinate formats and the snapshot"
)


# Prefix of the whole-format GeoJSON omission (layer_id=None). It distinguishes that
# omission from the labels/rotation disclosure, which is also layer-less.
_GEOJSON_UNAVAILABLE = "GeoJSON omitted: "
# Projection failures that depend on installed operations/grids or the deed extent
# rather than an invalid request; they omit GeoJSON alone unless it is required.
_UNAVAILABLE_CODES = frozenset({"operation_unavailable", "missing_grid", "projection_domain"})


class _GeoJSONArea(NamedTuple):
    """Publish-time GeoJSON operation, out-of-area layers and sampled corridor rings."""

    projection: WebMapProjection
    outside: dict[str, str]
    # Geographic ring per corridor layer, sampled once for both area check and export.
    corridor_rings: dict[str, list[XY]]


class _GeoJSONUnavailable(ValueError):
    """No installed coordinate operation serves the deed extent (safe reason text)."""


def _geojson_context(item: DeliveryItem) -> bool:
    """Whether an item is area-checked context (not operation-selecting deed geometry)."""
    return (
        item.selection.visible
        and item.selection.kind != "calculation"
        and bool((item.plot and item.placement) or item.vector)
    )


def _required_geojson(items: Sequence[DeliveryItem]) -> list[str]:
    """Visible required selections GeoJSON would carry; rasters are never emitted."""
    return [
        i.selection.id
        for i in items
        if i.selection.kind != "raster" and i.selection.visible and i.selection.required
    ]


def _geojson_omissions(
    items: Sequence[DeliveryItem],
    scene: PlotScene | None,
    request: DeliveryRequest,
    *,
    recorded: Sequence[DeliveryOmission] | None = None,
) -> tuple[_GeoJSONArea | None, list[DeliveryOmission]]:
    """GeoJSON area-of-use omissions: computed at publish, accepted as recorded on replay.

    Publish (``recorded is None``) runs the fail-closed operation/area check. Replay
    never re-runs it: the choice depends on installed PROJ grids/operations, so the
    package's recorded omissions are validated against the request and items, and
    integrity rests on the stored artifact hashes and snapshot identity.
    """
    if scene is None:
        raise ValueError("Geographic GeoJSON area check requires an explicitly projected scene")
    if recorded is not None:
        return None, _recorded_geojson_omissions(items, request, recorded)
    # Like the web map: deed geometry selects the operation; each context or
    # derived layer it does not cover is omitted, or blocks when required.
    try:
        area = _geojson_area(items, scene, tolerance_m=request.geo_tolerance_m)
    except _GeoJSONUnavailable as exc:
        # No installed operation serves the deed extent. Scene-coordinate formats
        # need no projection, so GeoJSON alone is omitted -- unless a visible
        # required layer, required appearance or a GeoJSON-only request needs it.
        required = _required_geojson(items)
        if required or request.required_appearance or set(request.formats) == {"geojson"}:
            raise ValueError(f"{', '.join(required)}: {exc}" if required else str(exc)) from exc
        return None, [DeliveryOmission(format="geojson", reason=str(exc))]
    omissions = []
    for layer_id, reason in area.outside.items():
        selection = next(i.selection for i in items if i.selection.id == layer_id)
        if selection.required or request.required_appearance:
            raise ValueError(f"{layer_id}: {reason}")
        omissions.append(DeliveryOmission(format="geojson", layer_id=layer_id, reason=reason))
    return area, omissions


def _recorded_geojson_omissions(
    items: Sequence[DeliveryItem],
    request: DeliveryRequest,
    recorded: Sequence[DeliveryOmission],
) -> list[DeliveryOmission]:
    """Accept recorded area-of-use omissions only where a publish could have made them."""
    whole = [
        o
        for o in recorded
        if o.format == "geojson"
        and o.layer_id is None
        and o.reason.startswith(_GEOJSON_UNAVAILABLE)
    ]
    layers = [o for o in recorded if o.format == "geojson" and o.reason == _OUTSIDE_AREA]
    if whole:
        if len(whole) > 1 or layers:
            raise ValueError("Recorded GeoJSON omissions are inconsistent")
        if (
            _required_geojson(items)
            or request.required_appearance
            or set(request.formats) == {"geojson"}
        ):
            raise ValueError("Recorded GeoJSON omission contradicts required layers or appearance")
        return whole
    by_id = {i.selection.id: i for i in items}
    seen: set[str] = set()
    for omission in layers:
        item = by_id.get(omission.layer_id) if omission.layer_id else None
        if (
            item is None
            or item.selection.id in seen
            or not _geojson_context(item)
            or item.selection.required
            or request.required_appearance
        ):
            raise ValueError("Recorded GeoJSON area-of-use omission contradicts the request")
        seen.add(item.selection.id)
    return layers


def _geojson_area(
    items: Iterable[DeliveryItem], scene: PlotScene, *, tolerance_m: float | None = None
) -> _GeoJSONArea:
    """Select the GeoJSON operation like the web map and classify context by area of use.

    Deed calculations choose the operation (shared ``operation_extent``). Context
    vectors and derived corridor/PLSS sources are checked individually against it
    (a corridor by the constructed polygon vertices GeoJSON exports at
    ``tolerance_m``); returns the projection and ``{layer_id: reason}`` for layers
    it does not cover. Raises ``_GeoJSONUnavailable`` when no operation serves it.
    """
    from mp_models.webmap import WebMapOptions
    from mp_verify.webmap import bounds_of

    from . import webmap
    from . import webmap_projection as projections
    from .delivery_sources import corridor_export_ring

    primary: list[XY] = []
    context: list[tuple[DeliveryItem, tuple[float, float, float, float] | None]] = []
    for item in items:
        if not item.selection.visible:
            continue
        if item.plot and item.placement:
            points = webmap.displayed_calculation_points(
                item.plot.geometry.primitives,
                [item.placement],
                item.plot.request.foot_definition,
                scene.units,
            )
            if item.selection.kind == "calculation":
                primary.extend(points)
            else:
                context.append((item, bounds_of(points)))
        elif item.vector:
            context.append((item, webmap.vector_extent(item.vector)))
    try:
        projection = projections.build_web_map_projection(
            scene, extent=webmap.operation_extent(primary, (extent for _, extent in context))
        )
    except projections.WebMapUnavailable as exc:
        if exc.code not in _UNAVAILABLE_CODES:
            raise
        raise _GeoJSONUnavailable(
            f"{_GEOJSON_UNAVAILABLE}{exc} Scene-coordinate formats and the snapshot "
            "retain the selected geometry"
        ) from exc
    options = WebMapOptions() if tolerance_m is None else WebMapOptions(tolerance_m=tolerance_m)
    outside: dict[str, str] = {}
    rings: dict[str, list[XY]] = {}
    for item, extent in context:
        try:
            if item.selection.kind == "corridor":
                # The exported polygon, not coarse primitive samples, must be covered;
                # keep the sampled ring so export does not sample it again.
                ring, extent = corridor_export_ring(item, scene, options, projection)
                rings[item.selection.id] = ring
            webmap.require_area(projection, extent)
        except projections.WebMapUnavailable as exc:
            if exc.code not in {"outside_area_of_use", "projection_domain"}:
                raise
            outside[item.selection.id] = _OUTSIDE_AREA
    return _GeoJSONArea(projection, outside, rings)


def _geojson_omitted(snapshot: DeliverySnapshot) -> bool:
    return any(
        o.format == "geojson" and o.layer_id is None and o.reason.startswith(_GEOJSON_UNAVAILABLE)
        for o in snapshot.omissions
    )


def _geojson(
    bundle: DashboardBundle, snapshot: DeliverySnapshot, area: _GeoJSONArea | None = None
) -> dict[str, Any]:
    """Reuse the shared geographic sampler/projection, with original placement evidence.

    ``area`` is the projection/classification computed while preparing this
    snapshot in the same publish, or on replay the operation recorded in the
    package's GeoJSON with the recorded omissions (``_recorded_area``).
    """
    from mp_models.webmap import WebMapOptions

    from .webmap import _Budget, _deed_features, _vector_feature

    scene = next(
        s for s in (*bundle.scenes, *snapshot.request.scenes) if s.id == snapshot.request.scene_id
    )
    if area is None:
        raise ValueError("GeoJSON rendering requires a coordinate operation")
    projection, outside, rings = area
    # delivery-1 packages were published without an area-of-use check, so they
    # record no layer omissions and replay with ``outside == {}``.
    recorded = {
        o.layer_id: o.reason
        for o in snapshot.omissions
        if o.format == "geojson" and o.reason == _OUTSIDE_AREA
    }
    if recorded != outside:
        raise ValueError("GeoJSON area-of-use omissions differ from the frozen snapshot")
    options = WebMapOptions(tolerance_m=snapshot.request.geo_tolerance_m)
    budget = _Budget(options.max_vertices)
    features = []
    for item in snapshot.items:
        if not item.selection.visible or item.selection.id in outside:
            continue
        values: list[Any] = []
        if item.selection.kind in {"corridor", "plss_reference"}:
            from .delivery_sources import delivery_source_features

            source_record = next(
                (
                    record
                    for record in snapshot.derived_sources
                    if record.get("layer_id") == item.selection.id
                ),
                None,
            )
            if source_record is None:
                # Non-required layer whose preparation failed: an omission is already
                # recorded and the item carries no geometry.
                continue
            values = delivery_source_features(
                item,
                source_record,
                snapshot.request,
                scene,
                options,
                budget,
                projection,
                ring=rings.get(item.selection.id),
            )
        elif item.plot and item.placement:
            values = _deed_features(
                item.plot.geometry,
                item.placement,
                item.plot.request.foot_definition,
                scene.units,
                projection,
                options,
                budget,
            )
        elif item.vector:
            values = [_vector_feature(item.vector, projection, options, budget)]
        for value in values:
            feature = value if isinstance(value, dict) else value.model_dump(mode="json")
            feature["properties"].update(
                revision_id=snapshot.request.revision_id,
                revision_sha256=snapshot.revision_sha256,
                geometry_kind=snapshot.request.geometry,
                delivery_layer_id=item.selection.id,
                opacity=item.selection.opacity,
                canonical_verification="not_requested",
                curve_linearization_tolerance_m=options.tolerance_m,
            )
            primitive = next(
                (p for p in item.primitives if p.call_id == feature["properties"].get("call_id")),
                None,
            )
            if primitive:
                feature["properties"].update(
                    input_status=primitive.input_status,
                    original_recorded_bearing_deg=primitive.recorded_bearing_deg,
                    original_recorded_distance_ft=primitive.recorded_distance_ft,
                    selected_bearing_deg=primitive.selected_bearing_deg,
                    selected_distance_ft=primitive.selected_distance_ft,
                )
                if primitive.input_status == "hypothetical":
                    feature["properties"]["kind"] = "scenario_course"
            if snapshot.exporter_version != "delivery-1":  # delivery-1 replay keeps raw order
                _orient_rfc7946(feature["geometry"])
            features.append(feature)
    return {
        "type": "FeatureCollection",
        "features": features,
        "metesparser": {
            "request_sha256": snapshot.request_sha256,
            "revision_id": snapshot.request.revision_id,
            "curve_linearization_tolerance_m": options.tolerance_m,
            "projection": {
                "source_crs_wkt": projection.source_crs_wkt,
                "pipeline": projection.pipeline,
                "accuracy_m": projection.accuracy,
                "versions": projection.versions,
            },
        },
    }


def _components(
    bundle: DashboardBundle,
    snapshot: DeliverySnapshot,
    area: _GeoJSONArea | None = None,
    *,
    render_geojson: bool = True,
) -> dict[str, bytes]:
    from mp_export.delivery import render_delivery_dxf, render_delivery_pdf, render_delivery_svg

    artifacts = {
        "pending.json": _json(
            {
                "request": snapshot.request.model_dump(mode="json"),
                "snapshot_sha256": _hash(snapshot.model_dump(mode="json")),
            }
        ).encode("utf-8"),
        "snapshot.json": _json(snapshot.model_dump(mode="json")).encode("utf-8"),
        "request.json": _json(snapshot.request.model_dump(mode="json")).encode("utf-8"),
        "revision-calls.json": _json(
            {
                "schema_version": "1.0",
                "purpose": "selected_revision_evidence",
                "drawing_geometry": snapshot.request.geometry,
                "revision_id": snapshot.request.revision_id,
                "generation": snapshot.request.revision_generation,
                "calls": list(snapshot.selected_revision_calls),
            }
        ).encode("utf-8"),
        "metrics.json": _json([m.model_dump(mode="json") for m in snapshot.metrics]).encode(
            "utf-8"
        ),
        "calls.json": _json(
            [
                {
                    "calculation_id": i.selection.id,
                    "calls": [c.model_dump(mode="json") for c in i.plot.request.calls],
                }
                for i in snapshot.items
                if i.plot
            ]
        ).encode("utf-8"),
    }
    for fmt in snapshot.request.formats:
        if fmt == "svg":
            artifacts["drawing.svg"] = render_delivery_svg(snapshot).encode("utf-8")
        elif fmt == "pdf":
            artifacts["drawing.pdf"] = render_delivery_pdf(snapshot)
        elif fmt == "dxf":
            artifacts["drawing.dxf"] = render_delivery_dxf(snapshot)
        elif render_geojson and not _geojson_omitted(snapshot):
            artifacts["drawing.geojson"] = _json(_geojson(bundle, snapshot, area)).encode("utf-8")
    if snapshot.request.include_full_source:
        artifacts["full-source.json"] = _json(bundle.model_dump(mode="json")).encode("utf-8")
    return artifacts


def publish_delivery(
    bundle: DashboardBundle,
    revision_dir: Path | str,
    request: DeliveryRequest | dict[str, Any],
    output_dir: Path | str,
) -> dict[str, Any]:
    """Publish one immutable package under ``output_dir/<request.id>``.

    Every artifact and the manifest are written and fsynced into a private
    sibling directory, which is then renamed into place: a package is visible
    only complete. An existing package id is never replaced, so of concurrent
    publishers of one id exactly one succeeds.
    """
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "operation": "deliver-review",
        "status": "error",
        "save_state": "failed",
        "errors": [],
        "artifacts": {},
    }
    try:
        snapshot, geojson_area = _prepare(bundle, revision_dir, request)
        store = Path(output_dir)
        if store.is_symlink():
            raise ValueError("Unsafe delivery store symlink")
        store.mkdir(parents=True, exist_ok=True)
        directory = store / snapshot.request.id
        _clear_stale_publishes(store, snapshot.request.id)
        if os.path.lexists(directory):
            _clear_legacy_incomplete(directory, snapshot.request.id)
        artifacts = _components(bundle, snapshot, geojson_area)
        manifest = {
            "schema_version": "1.0",
            "save_state": "published",
            "exporter_version": snapshot.exporter_version,
            "request_sha256": snapshot.request_sha256,
            "snapshot_sha256": _hash(snapshot.model_dump(mode="json")),
            "revision_sha256": snapshot.revision_sha256,
            "artifacts": {n: hashlib.sha256(c).hexdigest() for n, c in artifacts.items()},
            "omissions": [o.model_dump(mode="json") for o in snapshot.omissions],
        }
        staging = _make_staging(store, snapshot.request.id)
        try:
            for name, content in artifacts.items():
                _write_once(staging / name, content)
            # Manifest last, so even the private staging copy never names a missing file.
            _write_once(staging / "delivery-manifest.json", _json(manifest).encode("utf-8"))
            if os.path.lexists(directory):
                raise ValueError(_already_published(snapshot.request.id))
            try:
                # POSIX rename(2) refuses a non-empty target (always the case for a
                # package); Windows refuses any existing target.
                os.rename(staging, directory)
            except OSError as exc:
                if os.path.lexists(directory):
                    raise ValueError(_already_published(snapshot.request.id)) from exc
                raise
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        _fsync_directory(store)
        result.update(
            status="needs_review",
            save_state="published",
            manifest=str(directory / "delivery-manifest.json"),
            revision_id=snapshot.request.revision_id,
            request_sha256=snapshot.request_sha256,
            omissions=manifest["omissions"],
            artifacts={n: str(directory / n) for n in artifacts},
            canonical_verification="not_requested",
            verified_export_eligible=False,
        )
    except (OSError, ValueError, TypeError, KeyError, ImportError) as exc:
        result["errors"].append(str(exc))
    return result


def _already_published(delivery_id: str) -> str:
    return f"Delivery {delivery_id!r} is already published; published deliveries are immutable"


_STAGING_PREFIX = ".publishing-"

# Everything a pre-staging publisher could leave in a crashed, manifest-less directory.
_LEGACY_NAMES = re.compile(
    r"(?:(?:pending|snapshot|request|metrics|calls|revision-calls|full-source)\.json"
    r"|drawing\.(?:svg|pdf|dxf|geojson)|\.DS_Store|Thumbs\.db|desktop\.ini|\._.*)"
)
# tempfile.NamedTemporaryFile default names ("tmp" + 8 of [a-z0-9_]) were used by the legacy
# atomic writer and may be left behind by a killed publisher. The name cannot prove
# provenance ("tmp20261030", "tmpnotes_01" are plausible user files), so such files are never
# deleted: the publish is refused and the files are listed for manual cleanup.
_TEMP_LOOKALIKE = re.compile(r"tmp[a-z0-9_]{8}")


def _id_tag(delivery_id: str) -> str:
    return hashlib.sha256(delivery_id.encode("utf-8")).hexdigest()[:12]


def _staging_pattern(delivery_id: str) -> re.Pattern[str]:
    return re.compile(rf"{re.escape(_STAGING_PREFIX)}(\d+)-[0-9a-f]{{16}}-{_id_tag(delivery_id)}")


def _make_staging(store: Path, delivery_id: str) -> Path:
    """Private sibling ``.publishing-<pid>-<random>-<id hash>``; short whatever the id."""
    # Plain mkdir (not mkdtemp's 0o700) so the published directory keeps umask modes.
    while True:
        name = f"{_STAGING_PREFIX}{os.getpid()}-{secrets.token_hex(8)}-{_id_tag(delivery_id)}"
        staging = store / name
        try:
            staging.mkdir()
        except FileExistsError:
            continue
        return staging


def _clear_legacy_incomplete(directory: Path, delivery_id: str) -> None:
    """Make way for a publish when ``directory`` is not a published delivery.

    A directory with a manifest is published and immutable (never touched). One
    without is a crashed pre-staging publish only if it holds nothing but plain
    files the old publisher could write (plus OS litter); those are removed.
    Anything else is refused untouched.
    """
    refusal = ValueError(
        f"Delivery directory {delivery_id!r} exists but is not a published delivery "
        "(incomplete or unknown contents); refusing to modify it"
    )
    if directory.is_symlink() or not directory.is_dir():
        raise refusal
    if os.path.lexists(directory / "delivery-manifest.json"):
        raise ValueError(_already_published(delivery_id))
    entries = list(directory.iterdir())
    lookalikes = sorted(
        e.name for e in entries if _TEMP_LOOKALIKE.fullmatch(e.name) and not e.is_symlink()
    )
    if lookalikes:
        raise ValueError(
            f"Delivery directory {delivery_id!r} holds temporary-looking files "
            f"({', '.join(lookalikes)}) that cannot be proven to be publisher residue; "
            "refusing to modify it. Inspect and remove them manually, then retry"
        )
    for entry in entries:
        if _LEGACY_NAMES.fullmatch(entry.name) is None or entry.is_symlink() or not entry.is_file():
            raise refusal
    for entry in entries:
        entry.unlink()
    try:
        directory.rmdir()
    except OSError as exc:
        raise refusal from exc


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":  # directories cannot be opened for fsync on Windows
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _clear_stale_publishes(store: Path, delivery_id: str) -> None:
    """Remove staging directories left by crashed publishes of this id.

    Staging directories never block a publish; one is removed only when its
    owning process is gone (POSIX). Elsewhere, or for a live or unknown owner,
    it is left alone and ignored.
    """
    if os.name == "nt":  # no safe liveness probe: os.kill(pid, 0) would signal it
        return
    pattern = _staging_pattern(delivery_id)
    for entry in store.iterdir():
        match = pattern.fullmatch(entry.name)
        if match is None or entry.is_symlink() or not entry.is_dir():
            continue
        pid = int(match.group(1))
        if pid == os.getpid():
            continue
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            shutil.rmtree(entry, ignore_errors=True)
        except OSError:  # alive under another user, or unknown: leave it
            continue


class DeliveryReplay(NamedTuple):
    """A read-only replay of a published package and how fully it was re-verified.

    ``geojson_coordinates`` is ``"reproduced"`` when GeoJSON was re-rendered with
    the recorded coordinate operation and matched byte-for-byte, ``"not_verified"``
    when this host cannot instantiate or faithfully execute that operation (a
    domain/PROJ error, or a mismatch while a grid it names is not installed;
    only identity, operation presence and layer binding were checked; see
    ``findings``), and
    ``"not_applicable"`` when the package has no GeoJSON.
    """

    snapshot: DeliverySnapshot
    geojson_coordinates: Literal["reproduced", "not_verified", "not_applicable"]
    findings: tuple[str, ...]


_COORDINATES_NOT_VERIFIED = (
    "GeoJSON coordinates not re-verified: the recorded coordinate operation cannot be "
    "instantiated on this host (for example a missing grid); only identity, the "
    "recorded operation's presence and layer binding were checked"
)


_COORDINATES_HOST_LIMITED = (
    "GeoJSON coordinates not re-verified: the recorded coordinate operation cannot be "
    "executed faithfully on this host (for example a domain error or a grid it names is "
    "not installed); only identity, the recorded operation's presence and layer binding "
    "were checked"
)


class DeliveryReplayIncomplete(ValueError):
    """Replay succeeded but GeoJSON coordinates could not be re-verified on this host."""


def _load_package_artifact(path: Path) -> Any:
    """Load a package JSON artifact; too-deep nesting is a malformed package naming it."""
    try:
        return _load(path)
    except InvalidInputJson as exc:
        raise ValueError(
            f"Delivery artifact {path.name} is nested too deeply to load (malformed package)"
        ) from exc


def load_delivery(
    bundle: DashboardBundle,
    revision_dir: Path | str,
    directory: Path | str,
    *,
    allow_unverified_geojson: bool = False,
) -> DeliverySnapshot:
    """Replay a published package read-only and return its snapshot.

    Raises ``DeliveryReplayIncomplete`` when GeoJSON coordinates were not re-verified,
    unless ``allow_unverified_geojson`` is set. ``replay_delivery`` reports the depth.
    """
    replay = replay_delivery(bundle, revision_dir, directory)
    if replay.geojson_coordinates == "not_verified" and not allow_unverified_geojson:
        raise DeliveryReplayIncomplete("; ".join(replay.findings) or _COORDINATES_NOT_VERIFIED)
    return replay.snapshot


def replay_delivery(
    bundle: DashboardBundle, revision_dir: Path | str, directory: Path | str
) -> DeliveryReplay:
    """Replay a published package read-only and report how fully it was re-verified.

    A package artifact too deeply nested to load is a malformed package (ValueError), not
    an invocation input error.
    """
    try:
        return _replay_delivery(bundle, revision_dir, directory)
    except InvalidInputJson as exc:
        raise ValueError(
            "Delivery package artifact is nested too deeply to load (malformed package)"
        ) from exc


def _replay_delivery(
    bundle: DashboardBundle, revision_dir: Path | str, directory: Path | str
) -> DeliveryReplay:
    path = Path(directory)
    if path.is_symlink():
        raise ValueError("Unsafe delivery directory")
    manifest_path = path / "delivery-manifest.json"
    if not manifest_path.is_file():
        raise ValueError("Delivery publication incomplete")
    if manifest_path.is_symlink():
        raise ValueError("Unsafe delivery manifest")
    manifest = _load_package_artifact(manifest_path)
    manifest = DeliveryManifest.model_validate(manifest).model_dump(mode="json")
    for name, digest in manifest["artifacts"].items():
        if (
            not re.fullmatch(
                r"(?:(?:pending|snapshot|request|metrics|calls|revision-calls|full-source)\.json|drawing\.(?:svg|pdf|dxf|geojson))",
                name,
            )
            or (path / name).is_symlink()
        ):
            raise ValueError("Unsafe delivery artifact")
        if not (path / name).is_file():
            raise ValueError("Delivery publication incomplete: missing artifact")
        if hashlib.sha256((path / name).read_bytes()).hexdigest() != digest:
            raise ValueError("Delivery artifact hash mismatch")
    if not {
        "pending.json",
        "snapshot.json",
        "request.json",
        "metrics.json",
        "calls.json",
        "revision-calls.json",
    } <= set(manifest["artifacts"]):
        raise ValueError("Delivery manifest artifact inventory incomplete")
    request = DeliveryRequest.model_validate(_load_package_artifact(path / "request.json"))
    recorded = _load_package_artifact(path / "snapshot.json")
    if not isinstance(recorded, dict) or not isinstance(recorded.get("omissions"), list):
        raise ValueError("Delivery snapshot artifact is malformed")
    # Replay with the exporter that published the package (recorded in the manifest),
    # accepting its recorded GeoJSON area-of-use omissions: they depend on the
    # publishing host's PROJ grids/operations and are never recomputed here.
    fresh, _ = _prepare(
        bundle,
        revision_dir,
        request,
        exporter_version=str(manifest["exporter_version"]),
        recorded_omissions=[DeliveryOmission.model_validate(o) for o in recorded["omissions"]],
    )
    if _hash(fresh.model_dump(mode="json")) != manifest.get("snapshot_sha256"):
        raise ValueError("Delivery snapshot identity mismatch")
    if (
        manifest["request_sha256"] != fresh.request_sha256
        or manifest["revision_sha256"] != fresh.revision_sha256
        or manifest["exporter_version"] != fresh.exporter_version
        or manifest["omissions"] != [o.model_dump(mode="json") for o in fresh.omissions]
    ):
        raise ValueError("Delivery manifest identity or omission policy mismatch")
    expected = _components(bundle, fresh, render_geojson=False)
    geojson = "geojson" in fresh.request.formats and not _geojson_omitted(fresh)
    if set(expected) | ({"drawing.geojson"} if geojson else set()) != set(manifest["artifacts"]):
        raise ValueError("Delivery artifact inventory mismatch")
    for name, content in expected.items():
        if (path / name).read_bytes() != content:
            raise ValueError("Delivery artifact differs from fresh replay")
    if not geojson:
        return DeliveryReplay(fresh, "not_applicable", ())
    recorded_geojson = (path / "drawing.geojson").read_bytes()
    recorded_projection = _check_recorded_geojson(recorded_geojson, fresh)
    # Re-render with the operation recorded at publish. It is never re-selected
    # here, so the replay host's grids/area of use cannot change the omissions.
    area = _recorded_area(bundle, fresh, recorded_projection)
    if area is None:
        return DeliveryReplay(fresh, "not_verified", (_COORDINATES_NOT_VERIFIED,))
    from .webmap_projection import WebMapUnavailable, _projection_dependencies

    pyproj, _ = _projection_dependencies()
    try:
        rendered = _json(_geojson(bundle, fresh, area)).encode("utf-8")
    except (WebMapUnavailable, pyproj.exceptions.ProjError):
        # The operation built but cannot run here (domain error, grid failure):
        # a host capability limit, not evidence that the artifact changed.
        return DeliveryReplay(fresh, "not_verified", (_COORDINATES_HOST_LIMITED,))
    if rendered != recorded_geojson:
        # A grid the recorded operation names but this host lacks can make PROJ
        # pass points through unchanged (optional ``@grid``), so a mismatch is
        # tampering only when the operation is fully usable here.
        if not _grids_installed(pyproj, recorded_projection["pipeline"]):
            return DeliveryReplay(fresh, "not_verified", (_COORDINATES_HOST_LIMITED,))
        raise ValueError("Delivery artifact differs from fresh replay")
    return DeliveryReplay(fresh, "reproduced", ())


def _grids_installed(pyproj: Any, pipeline: str) -> bool:
    """Whether every grid the pipeline names is available offline on this host."""
    try:
        operation = pyproj.crs.CoordinateOperation.from_string(pipeline)
        return all(grid.available for grid in operation.grids)
    except Exception:  # an operation this host cannot inspect is not proven usable
        return False


def _recorded_area(
    bundle: DashboardBundle, snapshot: DeliverySnapshot, recorded: dict[str, Any]
) -> _GeoJSONArea | None:
    """The recorded GeoJSON operation and omissions, or ``None`` if not instantiable here.

    CRS WKT, accuracy and versions are publish-host evidence carried over verbatim
    (the CRS must still equal the scene CRS); coordinates come from executing the
    recorded ``pipeline``. Area of use is not consulted.
    """
    from . import webmap_projection as projections
    from .webmap_projection import WebMapUnavailable, _projection_dependencies

    accuracy = recorded.get("accuracy_m")
    versions = recorded.get("versions")
    wkt = recorded.get("source_crs_wkt")
    if (
        not isinstance(wkt, str)
        or not (accuracy is None or (isinstance(accuracy, float | int) and accuracy is not True))
        or not isinstance(versions, list)
        or not all(
            isinstance(v, list) and len(v) == 2 and all(isinstance(x, str) for x in v)
            for v in versions
        )
    ):
        raise ValueError("Recorded GeoJSON identity or coordinate operation mismatch")
    scene = next(
        s for s in (*bundle.scenes, *snapshot.request.scenes) if s.id == snapshot.request.scene_id
    )
    try:
        pyproj, _ = _projection_dependencies()
    except WebMapUnavailable:  # pyproj not installed on this replay host
        return None
    try:
        source = pyproj.CRS.from_user_input(scene.crs)
        same_crs = pyproj.CRS.from_wkt(wkt).equals(source)
    except Exception as exc:
        raise ValueError("Recorded GeoJSON coordinate operation mismatch") from exc
    if not same_crs:
        raise ValueError("Recorded GeoJSON coordinate operation differs from the scene CRS")
    axes = tuple(axis.direction for axis in source.axis_info)
    pyproj.network.set_network_enabled(False)
    try:
        projection = projections.projection_from_pipeline(
            pyproj,
            source_crs_wkt=wkt,
            axes=axes,
            pipeline=recorded["pipeline"],
            accuracy=accuracy,
            versions=tuple((v[0], v[1]) for v in versions),
        )
    except pyproj.exceptions.ProjError:
        return None
    outside = {
        o.layer_id: o.reason
        for o in snapshot.omissions
        if o.format == "geojson" and o.layer_id is not None and o.reason == _OUTSIDE_AREA
    }
    return _GeoJSONArea(projection, outside, {})


def _check_recorded_geojson(content: bytes, snapshot: DeliverySnapshot) -> dict[str, Any]:
    """Bind a hash-verified recorded GeoJSON artifact to the replayed snapshot.

    Checks identity, that a coordinate operation is recorded, and that exactly the
    snapshot's visible, non-omitted geographic layers are present; returns the
    recorded projection block.
    """
    try:
        data = parse_json(content)
    except (ValueError, InvalidInputJson) as exc:
        raise ValueError("Recorded GeoJSON artifact drawing.geojson is malformed") from exc
    meta = data.get("metesparser") if isinstance(data, dict) else None
    projection = meta.get("projection") if isinstance(meta, dict) else None
    features = data.get("features") if isinstance(data, dict) else None
    if (
        not isinstance(meta, dict)
        or data.get("type") != "FeatureCollection"
        or meta.get("request_sha256") != snapshot.request_sha256
        or meta.get("revision_id") != snapshot.request.revision_id
        or meta.get("curve_linearization_tolerance_m") != snapshot.request.geo_tolerance_m
        or not isinstance(projection, dict)
        or not isinstance(projection.get("pipeline"), str)
        or not projection["pipeline"]
        or not isinstance(features, list)
    ):
        raise ValueError("Recorded GeoJSON identity or coordinate operation mismatch")
    omitted = {
        o.layer_id
        for o in snapshot.omissions
        if o.format == "geojson" and o.reason == _OUTSIDE_AREA
    }
    sourced = {record.get("layer_id") for record in snapshot.derived_sources}
    expected = {
        item.selection.id
        for item in snapshot.items
        if item.selection.visible
        and item.selection.id not in omitted
        and ((item.plot and item.placement) or item.vector)
        and (
            item.selection.kind not in {"corridor", "plss_reference"}
            or item.selection.id in sourced
        )
    }
    present = set()
    for feature in features:
        properties = feature.get("properties") if isinstance(feature, dict) else None
        if (
            not isinstance(properties, dict)
            or properties.get("revision_sha256") != snapshot.revision_sha256
            or properties.get("revision_id") != snapshot.request.revision_id
        ):
            raise ValueError("Recorded GeoJSON feature identity mismatch")
        present.add(properties.get("delivery_layer_id"))
    if present != expected:
        raise ValueError("Recorded GeoJSON layers differ from the replayed snapshot omissions")
    return projection
