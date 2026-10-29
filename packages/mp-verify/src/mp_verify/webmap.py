"""Validate prepared web-map identities without deriving geographic coordinates."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from mp_models.dashboard import DashboardCall, PreparedDashboard
from mp_models.plot import (
    LinearUnit,
    MapSource,
    PlotGeometry,
    PlotPlacement,
    PlotScene,
    VectorLayer,
)
from mp_models.plot_request import PlotCall
from mp_models.raster import RasterLayer
from mp_models.webmap import StandaloneWebMapInput, WebMapArtifact

from mp_verify.dashboard import validate_prepared_dashboard
from mp_verify.plot import validate_plot_placement, validate_prepared_plot


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


WebMapInput = PreparedDashboard | StandaloneWebMapInput


@dataclass(frozen=True)
class WebMapContext:
    """Validated shared evidence for display, with no synthetic dashboard entities."""

    title: str
    scenes: tuple[PlotScene, ...]
    map_sources: tuple[MapSource, ...]
    vector_layers: tuple[VectorLayer, ...]
    raster_layers: tuple[RasterLayer, ...]
    geometries: tuple[PlotGeometry, ...]
    placements: tuple[PlotPlacement, ...]
    calls: tuple[PlotCall | DashboardCall, ...]
    foot_definitions: tuple[tuple[str, LinearUnit], ...]
    input_hashes: tuple[tuple[str, str], ...]


def normalize_web_map_context(prepared: WebMapInput) -> WebMapContext:
    """Recompute every input geometry and preserve existing dashboard manifest hashes."""
    if isinstance(prepared, PreparedDashboard):
        prepared = PreparedDashboard.model_validate(prepared.model_dump())
        prepared = validate_prepared_dashboard(prepared)
        bundle = prepared.bundle
        return WebMapContext(
            title=bundle.title,
            scenes=bundle.scenes,
            map_sources=bundle.map_sources,
            vector_layers=bundle.vector_layers,
            raster_layers=bundle.raster_layers,
            geometries=prepared.plots.geometries,
            placements=prepared.plots.placements,
            calls=bundle.calls,
            foot_definitions=tuple((s.id, s.frame.foot_definition) for s in bundle.calculations),
            input_hashes=tuple(
                (key, value)
                for key, value in prepared.manifest.model_dump().items()
                if key.endswith("_hash") and value is not None
            ),
        )
    if not isinstance(prepared, StandaloneWebMapInput):
        raise TypeError("online map requires a prepared dashboard or standalone map input")
    standalone = StandaloneWebMapInput.model_validate(prepared.model_dump())
    plots = tuple(validate_prepared_plot(plot) for plot in standalone.plots)
    geometries = {plot.request.calculation_id: plot.geometry for plot in plots}
    units = {plot.request.calculation_id: plot.request.foot_definition for plot in plots}
    scenes = {scene.id: scene for scene in standalone.scenes}
    for placement in standalone.placements:
        validate_plot_placement(
            geometries[placement.calculation_id],
            placement,
            scenes[placement.scene_id],
            native_units=units[placement.calculation_id],
            orientation_supported=False,
            allow_unknown_units=True,
        )
    data = standalone.model_dump(mode="json")
    return WebMapContext(
        title=standalone.title,
        scenes=standalone.scenes,
        map_sources=standalone.map_sources,
        vector_layers=standalone.vector_layers,
        raster_layers=standalone.raster_layers,
        geometries=tuple(plot.geometry for plot in plots),
        placements=standalone.placements,
        calls=tuple(call for plot in plots for call in plot.request.calls),
        foot_definitions=tuple(units.items()),
        input_hashes=(
            ("standalone_input_hash", _digest(data)),
            ("plot_input_hash", _digest([plot.request.model_dump(mode="json") for plot in plots])),
            (
                "plot_output_hash",
                _digest([plot.geometry.model_dump(mode="json") for plot in plots]),
            ),
            (
                "map_input_hash",
                _digest(
                    {
                        key: data[key]
                        for key in ("scenes", "map_sources", "vector_layers", "raster_layers")
                    }
                ),
            ),
            ("placement_input_hash", _digest(data["placements"])),
        ),
    )


def _validate_bindings(context: WebMapContext, artifact: WebMapArtifact) -> None:
    """Check upstream identities without recreating geographic coordinates.

    Coordinate derivation and derived PNG byte validation belong to preparation
    and staging; this validator independently rejects forged evidence bindings.
    """
    scene = next((item for item in context.scenes if item.id == artifact.scene_id), None)
    if scene is None:
        raise ValueError("online display scene does not exist")
    geometries = {item.calculation_id: item for item in context.geometries}
    placements = {item.id: item for item in context.placements}
    calls = {item.id: item for item in context.calls}
    vectors = {item.id: item for item in context.vector_layers}
    sources = {item.id for item in context.map_sources}
    for feature in artifact.features:
        props = feature.properties
        if props.kind == "parcel_context":
            vector = vectors.get(props.layer_id or "")
            if (
                vector is None
                or vector.scene_id != scene.id
                or props.source_id != vector.source_id
                or vector.source_id not in sources
                or feature.geometry.type != vector.geometry_type
            ):
                raise ValueError("stale online context binding")
            continue
        geometry = geometries.get(props.calculation_id or "")
        placement = placements.get(props.placement_id or "")
        if (
            geometry is None
            or placement is None
            or placement.scene_id != scene.id
            or placement.scenario_id is not None
            or placement.calculation_id != geometry.calculation_id
            or props.geometry_hash != geometry.geometry_hash
            or placement.geometry_hash != geometry.geometry_hash
            or props.placement_hash != _digest(placement.model_dump(mode="json"))
            or props.placement_status != placement.status
            or placement.status == "unplaced"
            or props.completeness != geometry.completeness
            or props.source_id is not None
            or props.layer_id is not None
        ):
            raise ValueError("stale online deed feature binding")
        if props.kind == "recorded_course":
            call = calls.get(props.call_id or "")
            primitive = next(
                (item for item in geometry.primitives if item.call_id == props.call_id), None
            )
            if (
                call is None
                or primitive is None
                or props.page_id != call.page_id
                or primitive.page_id != call.page_id
                or props.occurrence_id != call.occurrence_id
                or primitive.occurrence_id != call.occurrence_id
            ):
                raise ValueError("stale online recorded call binding")
        elif (
            not geometry.primitives
            or props.occurrence_id != geometry.occurrence_id
            or props.page_id is not None
            or (
                props.kind == "closure_gap"
                and (
                    geometry.completeness != "complete"
                    or geometry.misclosure_ft is None
                    or geometry.misclosure_ft <= 1e-8
                )
            )
        ):
            raise ValueError("stale online marker binding")
    rasters = {item.id: item for item in context.raster_layers}
    projection_hash = (
        _digest(artifact.projection.model_dump(mode="json")) if artifact.projection else None
    )
    for raster in artifact.rasters:
        source = rasters.get(raster.id)
        if (
            source is None
            or source.scene_id != scene.id
            or raster.source_id != source.source_id
            or source.source_id not in sources
            or raster.source_sha256 != source.sha256
            or raster.registration_sha256 != _digest(source.registration.model_dump(mode="json"))
            or raster.projection_sha256 != projection_hash
            or raster.registration_status != source.registration.status
            or raster.fit_rms != source.registration.fit_rms
            or raster.checkpoint_rms != source.registration.checkpoint_rms
            or raster.residual_units != scene.units
        ):
            raise ValueError("stale online raster binding")


def validate_web_map_artifact(prepared: WebMapInput, artifact: WebMapArtifact) -> WebMapArtifact:
    """Revalidate models, canonical calculations, and display evidence bindings.

    This does not verify geographic coordinate derivation or derived PNG bytes;
    those checks belong to geographic preparation and asset staging upstream.
    """
    context = normalize_web_map_context(prepared)
    artifact = WebMapArtifact.model_validate(artifact.model_dump())
    if dict(artifact.input_hashes) != dict(context.input_hashes):
        raise ValueError("stale online display input hashes")
    if artifact.options_sha256 != _digest(artifact.options.model_dump(mode="json")):
        raise ValueError("stale online display options hash")
    _validate_bindings(context, artifact)
    return artifact
