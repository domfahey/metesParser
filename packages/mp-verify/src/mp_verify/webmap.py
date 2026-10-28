"""Validate prepared web-map identities without deriving geographic coordinates."""

from __future__ import annotations

import hashlib
import json

from mp_models.dashboard import PreparedDashboard
from mp_models.webmap import WebMapArtifact

from mp_verify.dashboard import validate_prepared_dashboard


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def _validate_bindings(prepared: PreparedDashboard, artifact: WebMapArtifact) -> None:
    """Check upstream identities without recreating geographic coordinates.

    Coordinate derivation and derived PNG byte validation belong to preparation
    and staging; this validator independently rejects forged evidence bindings.
    """
    bundle = prepared.bundle
    scene = next((item for item in bundle.scenes if item.id == artifact.scene_id), None)
    if scene is None:
        raise ValueError("online display scene does not exist")
    geometries = {item.calculation_id: item for item in prepared.plots.geometries}
    placements = {item.id: item for item in prepared.plots.placements}
    specs = {item.id: item for item in bundle.calculations}
    calls = {item.id: item for item in bundle.calls}
    vectors = {item.id: item for item in bundle.vector_layers}
    sources = {item.id for item in bundle.map_sources}
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
        spec = specs.get(props.calculation_id or "")
        if (
            geometry is None
            or placement is None
            or spec is None
            or placement.scene_id != scene.id
            or placement.scenario_id is not None
            or placement.calculation_id != geometry.calculation_id
            or props.geometry_hash != geometry.geometry_hash
            or placement.geometry_hash != geometry.geometry_hash
            or props.placement_hash != _digest(placement.model_dump(mode="json"))
            or props.placement_status != placement.status
            or placement.status == "unplaced"
            or props.completeness != geometry.completeness
            or props.occurrence_id != geometry.occurrence_id
            or spec.occurrence_id != geometry.occurrence_id
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
                or call.occurrence_id != geometry.occurrence_id
            ):
                raise ValueError("stale online recorded call binding")
        elif (
            not geometry.primitives
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
    rasters = {item.id: item for item in bundle.raster_layers}
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


def validate_web_map_artifact(
    prepared: PreparedDashboard, artifact: WebMapArtifact
) -> WebMapArtifact:
    """Revalidate models, canonical calculations, and display evidence bindings.

    This does not verify geographic coordinate derivation or derived PNG bytes;
    those checks belong to geographic preparation and asset staging upstream.
    """
    prepared = PreparedDashboard.model_validate(prepared.model_dump())
    prepared = validate_prepared_dashboard(prepared)
    artifact = WebMapArtifact.model_validate(artifact.model_dump())
    hashes = {
        key: value
        for key, value in prepared.manifest.model_dump().items()
        if key.endswith("_hash") and value is not None
    }
    if dict(artifact.input_hashes) != hashes:
        raise ValueError("stale online display input hashes")
    if artifact.options_sha256 != _digest(artifact.options.model_dump(mode="json")):
        raise ValueError("stale online display options hash")
    _validate_bindings(prepared, artifact)
    return artifact
