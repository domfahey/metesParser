"""Bind exported derived geometry to freshly replayed corridor/PLSS construction.

Bindings identify actual producer bundles, exact selected geometry and request
hashes. Caller-authored arbitrary JSON is never accepted as construction evidence.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

from mp_models.corridor import CorridorRequest, CorridorResult
from mp_models.dashboard import DashboardBundle
from mp_models.delivery import (
    DeliveryItem,
    DeliveryLayer,
    DeliveryMetric,
    DeliveryPrimitive,
    DeliveryRequest,
    DeliverySourceBinding,
)
from mp_models.plot import XY, PlotPlacement, PlotPrimitive, PlotScene
from mp_models.plss import PLSSDerivationRequest
from mp_models.webmap import WebMapFeature, WebMapOptions, WebMapPolygon, WebMapProperties
from mp_verify.corridor import validate_corridor_result
from mp_verify.dashboard import _hash
from mp_verify.plot import transform_point, unit_factor, validate_plot_placement
from mp_verify.scene import validate_scene

from .corridor import replay_corridor
from .plss import replay_plss
from .webmap import _Budget, _primitive_point, _sample, _vector_feature, bounds_of
from .webmap_projection import WebMapProjection


def _read(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Derived source requires regular, intact artifact files")
    return path.read_bytes()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _scene(request: DeliveryRequest, bundle: DashboardBundle) -> PlotScene:
    scenes = {s.id: s for s in bundle.scenes}
    for supplied in request.scenes:
        if supplied.id in scenes and scenes[supplied.id] != supplied:
            raise ValueError("Supplied derived-source scene conflicts with baseline identity")
        scenes[supplied.id] = supplied
    scene = scenes.get(request.scene_id or "")
    if scene is None:
        raise ValueError("Derived source requires an explicitly selected scene")
    validate_scene(scene)
    return scene


def _binding(binding: DeliverySourceBinding, selection: DeliveryLayer) -> None:
    if binding.kind != selection.kind or binding.layer_id != selection.id:
        raise ValueError("Derived source binding and selected geometry identity differ")


def prepare_delivery_source(
    binding: DeliverySourceBinding,
    selection: DeliveryLayer,
    request: DeliveryRequest,
    bundle: DashboardBundle,
    *,
    corridor_result: CorridorResult | None = None,
    corridor_raw_request: bytes | None = None,
) -> tuple[DeliveryItem, dict[str, Any], DeliveryMetric | None]:
    """Return honest derived primitives plus typed, source-bound construction metadata."""
    _binding(binding, selection)
    name = "corridor-manifest.json" if binding.kind == "corridor" else "plss-manifest.json"
    try:
        if binding.kind == "corridor":
            if binding.revision_corridor_id is not None:
                if (
                    binding.artifact_dir is not None
                    or corridor_result is None
                    or corridor_raw_request is None
                ):
                    raise ValueError(
                        "Revision corridor binding requires its retained request and result"
                    )
                raw = corridor_raw_request
                source_request = CorridorRequest.model_validate_json(raw)
                result = validate_corridor_result(corridor_result)
                if source_request != result.request or result != corridor_result:
                    raise ValueError(
                        "Revision corridor result differs from its retained raw request"
                    )
            else:
                if (
                    binding.artifact_dir is None
                    or corridor_result is not None
                    or corridor_raw_request is not None
                ):
                    raise ValueError("Standalone corridor binding requires its artifact directory")
                directory = Path(binding.artifact_dir)
                manifest_bytes = _read(directory / name)
                if _sha(manifest_bytes) != binding.manifest_sha256:
                    raise ValueError("Derived source manifest hash differs from explicit binding")
                result = replay_corridor(directory)
                raw = _read(directory / "request.json")
            if (
                result.availability != "supported"
                or result.boundary is None
                or result.centerline is None
            ):
                raise ValueError("Only a fully supported corridor can be selected for delivery")
            if selection.id != result.boundary.request.calculation_id:
                raise ValueError(
                    "Selected corridor geometry identity differs from producer boundary"
                )
            if (
                binding.input_sha256 != result.input_sha256
                or binding.geometry_sha256 != result.boundary.geometry.geometry_hash
            ):
                raise ValueError("Corridor input/geometry hash differs from explicit binding")
            if binding.revision_corridor_id is None:
                manifest = json.loads(manifest_bytes)
                if _sha(raw) != manifest["source_sha256"]:
                    raise ValueError("Corridor source request changed during replay")
            elif result.request.id != binding.revision_corridor_id:
                raise ValueError("Revision corridor identity differs from explicit binding")
            plot = result.boundary
            origin = result.boundary_origin_in_centerline_frame
            assert origin is not None
            native = plot.request.foot_definition
            placement = None
            original_placement = None
            scene = None
            if request.coordinate_mode == "placed":
                scene = _scene(request, bundle)
                placements = {p.id: p for p in bundle.placements}
                placements.update({p.id: p for p in request.placements})
                original_placement = placements.get(selection.placement_id or "")
                if original_placement is None or original_placement.status == "unplaced":
                    raise ValueError("Corridor requires an explicit placed centerline transform")
                if _hash(original_placement.model_dump(mode="json")) != selection.placement_sha256:
                    raise ValueError("Corridor supplied placement hash differs")
                if (
                    original_placement.calculation_id != result.centerline.request.calculation_id
                    or original_placement.scene_id != scene.id
                ):
                    raise ValueError(
                        "Corridor placement must identify the original centerline and selected scene"
                    )
                validate_plot_placement(
                    result.centerline.geometry,
                    original_placement,
                    scene,
                    native_units=native,
                    orientation_supported=True,
                )
                # This is an explicit change of native origin, never new geographic evidence.
                translation = transform_point(
                    origin, original_placement, native_units=native, scene_units=scene.units
                )
                data = original_placement.model_dump(mode="json")
                data.update(
                    id=binding.id + ":boundary-origin",
                    calculation_id=plot.request.calculation_id,
                    geometry_hash=plot.geometry.geometry_hash,
                    translation=translation,
                    rationale="Boundary origin composed from supplied centerline placement "
                    + original_placement.id
                    + ": "
                    + original_placement.rationale,
                )
                placement = PlotPlacement.model_validate(data)
                validate_plot_placement(
                    plot.geometry, placement, scene, native_units=native, orientation_supported=True
                )
            factor = unit_factor(scene.units if scene else native, request.units)

            def point(p: XY) -> XY:
                value = (
                    transform_point(p, placement, native_units=native, scene_units=scene.units)
                    if placement is not None and scene
                    else (p[0] + origin[0], p[1] + origin[1])
                )
                return value[0] * factor, value[1] * factor

            calls = {record.id: record.call for record in plot.request.calls}
            primitives = []
            for p in plot.geometry.primitives:
                call = calls[p.call_id]
                primitives.append(
                    DeliveryPrimitive(
                        kind=p.kind,
                        call_id=p.call_id,
                        layer_id=selection.id,
                        start=point(p.start),
                        end=point(p.end),
                        center=point(p.center) if p.center else None,
                        radius=p.radius_ft * unit_factor(native, request.units)
                        if p.radius_ft
                        else None,
                        sweep_deg=p.sweep_deg,
                        curve_dir=p.curve_dir,
                        length=p.length_ft * unit_factor(native, request.units),
                        selected_bearing_deg=call.bearing_azimuth_deg_from_north if call else None,
                        selected_distance_ft=call.distance_ft if call else None,
                        input_status="corridor_derived",
                    )
                )
            record = {
                "layer_id": selection.id,
                "kind": "corridor",
                "binding": binding.model_dump(mode="json"),
                "input_sha256": result.input_sha256,
                "raw_request_sha256": _sha(raw),
                "raw_request_base64": base64.b64encode(raw).decode(),
                "canonical_request": result.request.model_dump(mode="json"),
                "canonical_request_is_complete": True,
                "boundary_origin_in_centerline_frame": list(origin),
                "boundary_geometry_sha256": plot.geometry.geometry_hash,
                "centerline_geometry_sha256": result.centerline.geometry.geometry_hash,
                "error": result.error.model_dump(mode="json") if result.error else None,
                "boundary_edges": [e.model_dump(mode="json") for e in result.boundary_edges],
                "source_bytes_omitted": False,
                "supplied_centerline_placement": original_placement.model_dump(mode="json")
                if original_placement
                else None,
                "effective_boundary_placement": placement.model_dump(mode="json")
                if placement
                else None,
                "limitations": list(result.limitations),
                "canonical_verification": "not_requested",
                "verified_export_eligible": False,
            }
            metric = DeliveryMetric(
                calculation_id=selection.id,
                misclosure_ft=None,
                area_sq_ft=plot.geometry.area_sq_ft,
                perimeter_ft=plot.geometry.perimeter_ft,
                unavailable_reason="Constructed corridor boundary metrics; open centerline is not evaluated as parcel closure",
            )
            item = DeliveryItem(
                selection=selection, plot=plot, placement=placement, primitives=tuple(primitives)
            )
        else:
            if binding.artifact_dir is None:
                raise ValueError("PLSS reference binding requires its artifact directory")
            directory = Path(binding.artifact_dir)
            manifest_bytes = _read(directory / "plss-manifest.json")
            if _sha(manifest_bytes) != binding.manifest_sha256:
                raise ValueError("Derived source manifest hash differs from explicit binding")
            plss = replay_plss(directory)
            if plss.availability != "computed" or len(plss.vector_layers) != 1:
                raise ValueError("Only a computed, supported PLSS reference layer can be delivered")
            layer = plss.vector_layers[0]
            if selection.id != layer.id:
                raise ValueError("Selected PLSS layer identity differs from producer reference")
            if binding.input_sha256 != plss.input_hash or binding.geometry_sha256 != _hash(
                layer.model_dump(mode="json")
            ):
                raise ValueError("PLSS input/geometry hash differs from explicit binding")
            if request.coordinate_mode != "placed" or selection.placement_id is not None:
                raise ValueError(
                    "PLSS reference retains its own supplied scene; no local reinterpretation or deed placement"
                )
            scene = _scene(request, bundle)
            if len(plss.scenes) != 1 or scene != plss.scenes[0]:
                raise ValueError(
                    "PLSS selected scene differs from original supplied reference scene"
                )
            raw = _read(directory / "request.json")
            manifest = json.loads(manifest_bytes)
            if _sha(raw) != manifest["sha256"]["request.json"]:
                raise ValueError("PLSS source request changed during replay")
            original = PLSSDerivationRequest.model_validate_json(raw)
            canonical = original.model_dump(mode="json")
            omitted = (
                original.dataset.source.data_base64 is not None and not request.include_full_source
            )
            if omitted:
                canonical["dataset"]["source"]["data_base64"] = None
            # Keep this a schema-valid typed reference, even when page bytes are explicitly omitted.
            canonical = PLSSDerivationRequest.model_validate(canonical).model_dump(mode="json")
            record = {
                "layer_id": selection.id,
                "kind": "plss_reference",
                "binding": binding.model_dump(mode="json"),
                "input_sha256": plss.input_hash,
                "raw_request_sha256": _sha(raw),
                "raw_request_base64": None if omitted else base64.b64encode(raw).decode(),
                "canonical_request": canonical,
                "canonical_request_is_complete": not omitted,
                "source_hash": plss.source_hash,
                "dataset_hash": plss.dataset_hash,
                "dataset_id": plss.dataset_id,
                "reference_id": plss.reference_id,
                "rule": plss.rule,
                "aliquot_steps": list(plss.aliquot_steps),
                "area_scene_units_squared": plss.area_scene_units_squared,
                "scene": scene.model_dump(mode="json"),
                "source_bytes_omitted": omitted,
                "limitations": list(plss.limitations)
                + (
                    [
                        "Inline reference source bytes omitted by include_full_source=false; retained source/request hashes identify the original bundle."
                    ]
                    if omitted
                    else []
                ),
                "canonical_verification": "not_requested",
                "verified_export_eligible": False,
            }
            item = DeliveryItem(selection=selection, vector=layer)
            metric = DeliveryMetric(
                calculation_id=selection.id,
                misclosure_ft=None,
                area_sq_ft=None,
                perimeter_ft=None,
                unavailable_reason="Computed PLSS reference has no deed closure metric; original scene-unit area remains in derived source metadata",
            )
        if binding.revision_corridor_id is None and _read(directory / name) != manifest_bytes:
            raise ValueError("Derived source manifest changed during replay")
        return item, record, metric
    except OSError as exc:
        raise ValueError("Derived source artifact is unavailable for fresh replay") from exc


def _corridor_ring(
    item: DeliveryItem,
    scene: PlotScene,
    options: WebMapOptions,
    budget: _Budget,
    projection: WebMapProjection,
    scene_points: list[XY] | None = None,
) -> list[XY]:
    """Sample the constructed corridor boundary exactly as GeoJSON exports it.

    Returns geographic ring vertices. ``scene_points`` collects every placed
    scene-XY point the sampler evaluates (a superset of the exported vertices'
    sources, all on the boundary), for area-of-use checks of exported geometry.
    """
    if item.plot is None or item.placement is None:
        raise ValueError("Geographic corridor requires its composed explicit placement")
    native = item.plot.request.foot_definition
    placement = item.placement
    points: list[XY] = []
    for primitive in item.plot.geometry.primitives:

        def placed_point(t: float, p: PlotPrimitive = primitive) -> XY:
            value = transform_point(
                _primitive_point(p, t),
                placement,
                native_units=native,
                scene_units=scene.units,
            )
            if scene_points is not None:
                scene_points.append(value)
            return value

        sampled = _sample(
            placed_point,
            projection,
            options,
            budget,
            count_start=not points,
        )
        points.extend(sampled if not points else sampled[1:])
    return points


def corridor_export_extent(
    item: DeliveryItem, scene: PlotScene, options: WebMapOptions, projection: WebMapProjection
) -> tuple[float, float, float, float] | None:
    """Scene-XY bounds of the corridor polygon vertices GeoJSON would export."""
    collected: list[XY] = []
    _corridor_ring(item, scene, options, _Budget(options.max_vertices), projection, collected)
    return bounds_of(collected)


def delivery_source_features(
    item: DeliveryItem,
    source_record: dict[str, Any],
    request: DeliveryRequest,
    scene: PlotScene,
    options: WebMapOptions,
    budget: _Budget,
    projection: WebMapProjection,
) -> list[dict[str, Any]]:
    """Project explicit constructed polygons without deed-course or POB assertions."""
    if (
        source_record.get("layer_id") != item.selection.id
        or source_record.get("kind") != item.selection.kind
    ):
        raise ValueError("Derived geographic feature differs from source binding")
    if item.selection.kind == "corridor":
        points = _corridor_ring(item, scene, options, budget, projection)
        if len(points) < 4:
            raise ValueError("Geographic corridor requires a closed boundary ring")
        if points[-1] != points[0]:
            # The stored corridor boundary is closed in its native frame; retain an
            # exact geographic ring closure after the projection's round trip.
            points.append(points[0])
        geometry = WebMapPolygon(coordinates=(tuple(points),))
        feature = WebMapFeature(
            id="derived:" + source_record["binding"]["id"],
            geometry=geometry,
            properties=WebMapProperties(
                kind="parcel_context",
                source_id=source_record["binding"]["id"],
                layer_id=item.selection.id,
                label="Constructed corridor boundary",
            ),
        ).model_dump(mode="json")
        kind = "corridor_boundary"
    else:
        if item.vector is None or item.vector.scene_id != scene.id:
            raise ValueError("Geographic PLSS layer must retain its original scene")
        feature = _vector_feature(item.vector, projection, options, budget).model_dump(mode="json")
        kind = "computed_plss_reference"
    feature["properties"].update(
        kind=kind,
        input_status="corridor_derived" if kind == "corridor_boundary" else "plss_reference",
        derived_source_binding=source_record["binding"]["id"],
        source_manifest_sha256=source_record["binding"]["manifest_sha256"],
        source_input_sha256=source_record["input_sha256"],
        source_geometry_sha256=source_record["binding"]["geometry_sha256"],
        boundary_established=False,
        canonical_verification="not_requested",
        verified_export_eligible=False,
    )
    if kind == "corridor_boundary":
        feature["properties"].update(
            corridor_error=source_record["error"],
            curve_linearization_tolerance_m=options.tolerance_m,
            boundary_origin_in_centerline_frame=source_record[
                "boundary_origin_in_centerline_frame"
            ],
        )
    else:
        feature["properties"].update(
            dataset_hash=source_record["dataset_hash"],
            reference_id=source_record["reference_id"],
            rule=source_record["rule"],
        )
    return [feature]
