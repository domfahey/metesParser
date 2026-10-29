"""Prepare one immutable review snapshot; publish package manifest last."""

from __future__ import annotations

import hashlib
import importlib.metadata
import re
from pathlib import Path
from typing import Any

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
from .revisions import _write_once, load_revision


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
    bundle: DashboardBundle, revision_dir: Path | str, request: DeliveryRequest | dict[str, Any]
) -> DeliverySnapshot:
    """Replay published input and freeze selected membership, transforms and omissions.

    Visible=false explicitly excludes geometry from every output while retaining
    its request membership. Opacity=0 retains all CAD/GIS geometry and tables.
    """
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
        if fmt in ("dxf", "geojson") and request.labels:
            omissions.append(
                DeliveryOmission(
                    format=fmt,
                    reason="Drawn labels and presentation rotation are omitted; source values and identity remain in properties/sidecars",
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
    return DeliverySnapshot(
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


def _geojson(bundle: DashboardBundle, snapshot: DeliverySnapshot) -> dict[str, Any]:
    """Reuse the shared geographic sampler/projection, with original placement evidence."""
    from mp_models.webmap import WebMapOptions

    from .webmap import _Budget, _deed_features, _vector_feature
    from .webmap_projection import build_web_map_projection

    scene = next(
        s for s in (*bundle.scenes, *snapshot.request.scenes) if s.id == snapshot.request.scene_id
    )
    projection = build_web_map_projection(scene)
    options = WebMapOptions(tolerance_m=snapshot.request.geo_tolerance_m)
    budget = _Budget(options.max_vertices)
    features = []
    for item in snapshot.items:
        if not item.selection.visible:
            continue
        values: list[Any] = []
        if item.selection.kind in {"corridor", "plss_reference"}:
            from .delivery_sources import delivery_source_features

            source_record = next(
                record
                for record in snapshot.derived_sources
                if record.get("layer_id") == item.selection.id
            )
            values = delivery_source_features(
                item, source_record, snapshot.request, scene, options, budget, projection
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


def _components(bundle: DashboardBundle, snapshot: DeliverySnapshot) -> dict[str, bytes]:
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
        else:
            artifacts["drawing.geojson"] = _json(_geojson(bundle, snapshot)).encode("utf-8")
    if snapshot.request.include_full_source:
        artifacts["full-source.json"] = _json(bundle.model_dump(mode="json")).encode("utf-8")
    return artifacts


def publish_delivery(
    bundle: DashboardBundle,
    revision_dir: Path | str,
    request: DeliveryRequest | dict[str, Any],
    output_dir: Path | str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "operation": "deliver-review",
        "status": "error",
        "save_state": "failed",
        "errors": [],
        "artifacts": {},
    }
    try:
        snapshot = prepare_delivery(bundle, revision_dir, request)
        directory = Path(output_dir)
        if directory.is_symlink():
            raise ValueError("Unsafe delivery store symlink")
        directory.mkdir(parents=True, exist_ok=True)
        directory = directory / snapshot.request.id
        if directory.is_symlink():
            raise ValueError("Unsafe delivery directory symlink")
        directory.mkdir(exist_ok=True)
        _write_once(
            directory / "pending.json",
            _json(
                {
                    "request": snapshot.request.model_dump(mode="json"),
                    "snapshot_sha256": _hash(snapshot.model_dump(mode="json")),
                }
            ).encode("utf-8"),
        )
        artifacts = _components(bundle, snapshot)
        hashes = {}
        for name, content in artifacts.items():
            _write_once(directory / name, content)
            hashes[name] = hashlib.sha256(content).hexdigest()
        manifest = {
            "schema_version": "1.0",
            "save_state": "published",
            "exporter_version": snapshot.exporter_version,
            "request_sha256": snapshot.request_sha256,
            "snapshot_sha256": _hash(snapshot.model_dump(mode="json")),
            "revision_sha256": snapshot.revision_sha256,
            "artifacts": hashes,
            "omissions": [o.model_dump(mode="json") for o in snapshot.omissions],
        }
        _write_once(directory / "delivery-manifest.json", _json(manifest).encode("utf-8"))
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


def load_delivery(
    bundle: DashboardBundle, revision_dir: Path | str, directory: Path | str
) -> DeliverySnapshot:
    path = Path(directory)
    if path.is_symlink():
        raise ValueError("Unsafe delivery directory")
    manifest_path = path / "delivery-manifest.json"
    if not manifest_path.is_file():
        raise ValueError("Delivery publication incomplete")
    if manifest_path.is_symlink():
        raise ValueError("Unsafe delivery manifest")
    manifest = _load(manifest_path)
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
    request = DeliveryRequest.model_validate(_load(path / "request.json"))
    fresh = prepare_delivery(bundle, revision_dir, request)
    if _hash(fresh.model_dump(mode="json")) != manifest.get("snapshot_sha256"):
        raise ValueError("Delivery snapshot identity mismatch")
    if (
        manifest["request_sha256"] != fresh.request_sha256
        or manifest["revision_sha256"] != fresh.revision_sha256
        or manifest["exporter_version"] != fresh.exporter_version
        or manifest["omissions"] != [o.model_dump(mode="json") for o in fresh.omissions]
    ):
        raise ValueError("Delivery manifest identity or omission policy mismatch")
    expected = _components(bundle, fresh)
    if set(expected) != set(manifest["artifacts"]):
        raise ValueError("Delivery artifact inventory mismatch")
    for name, content in expected.items():
        if (path / name).read_bytes() != content:
            raise ValueError("Delivery artifact differs from fresh replay")
    return fresh
