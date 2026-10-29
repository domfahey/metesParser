"""Frozen requests and snapshots for explicitly selected review delivery."""

from typing import Any, Literal, Self

from pydantic import ConfigDict, Field, FiniteFloat, model_validator

from .base import _Model
from .plot import XY, Digest, Identifier, LinearUnit, PlotPlacement, PlotScene, VectorLayer
from .plot_request import PreparedPlot
from .raster import RasterLayer
from .revisions import RevisionBaseline


class DeliveryLayer(_Model):
    id: Identifier
    kind: Literal["calculation", "vector", "raster", "corridor", "plss_reference"]
    visible: bool = Field(strict=True)
    opacity: FiniteFloat = Field(ge=0, le=1, strict=True)
    required: bool = Field(strict=True)
    placement_id: Identifier | None = None
    placement_sha256: Digest | None = None

    @model_validator(mode="after")
    def _binding(self) -> Self:
        if (self.placement_id is None) != (self.placement_sha256 is None):
            raise ValueError("Placement requires both identity and hash")
        return self


class DeliverySourceBinding(_Model):
    id: Identifier
    kind: Literal["corridor", "plss_reference"]
    layer_id: Identifier
    artifact_dir: str | None = Field(default=None, min_length=1)
    revision_corridor_id: Identifier | None = None
    manifest_sha256: Digest
    input_sha256: Digest
    geometry_sha256: Digest

    @model_validator(mode="after")
    def _source(self) -> Self:
        if (self.artifact_dir is None) == (self.revision_corridor_id is None):
            raise ValueError("Derived source requires exactly one artifact or revision corridor")
        if self.revision_corridor_id is not None and self.kind != "corridor":
            raise ValueError("Only corridor sources can bind to a revision corridor")
        return self


class DeliveryRequest(_Model):
    model_config = ConfigDict(str_strip_whitespace=False)
    schema_version: Literal["1.0"] = "1.0"
    id: Identifier
    baseline: RevisionBaseline
    revision_id: Identifier
    revision_generation: int = Field(ge=0, strict=True)
    geometry: Literal["recorded", "scenario"]
    coordinate_mode: Literal["local", "placed"]
    scene_id: Identifier | None = None
    units: LinearUnit
    layers: tuple[DeliveryLayer, ...] = Field(min_length=1)
    placements: tuple[PlotPlacement, ...] = ()
    scenes: tuple[PlotScene, ...] = ()
    source_bindings: tuple[DeliverySourceBinding, ...] = ()
    formats: tuple[Literal["svg", "pdf", "dxf", "geojson"], ...] = Field(min_length=1)
    labels: tuple[Literal["course", "bearing", "distance"], ...] = ()
    presentation_rotation_deg: FiniteFloat = Field(default=0.0, strict=True)
    rotation_convention: Literal["clockwise_xy"] = "clockwise_xy"
    placement_pivot: Literal["native_origin"] = "native_origin"
    presentation_pivot: XY = (0.0, 0.0)
    include_full_source: bool = Field(default=False, strict=True)
    geo_tolerance_m: FiniteFloat = Field(default=0.05, gt=0)
    # CAD/GIS omit raster and drawn labels; make this true when appearance is required.
    required_appearance: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def _selection(self) -> Self:
        if len({layer.id for layer in self.layers}) != len(self.layers):
            raise ValueError("Duplicate delivery layer identity")
        if len(set(self.formats)) != len(self.formats):
            raise ValueError("Duplicate delivery format")
        if self.coordinate_mode == "placed" and self.scene_id is None:
            raise ValueError("Placed delivery requires explicit scene identity")
        if self.coordinate_mode == "local" and any(layer.placement_id for layer in self.layers):
            raise ValueError("Local delivery cannot apply placement transforms")
        if len({scene.id for scene in self.scenes}) != len(self.scenes):
            raise ValueError("Duplicate supplied scene identity")
        if len({binding.id for binding in self.source_bindings}) != len(self.source_bindings):
            raise ValueError("Duplicate derived source binding identity")
        for layer in self.layers:
            matches = [binding for binding in self.source_bindings if binding.layer_id == layer.id]
            if layer.kind in {"corridor", "plss_reference"}:
                if len(matches) != 1 or matches[0].kind != layer.kind:
                    raise ValueError("Derived layer requires exactly one matching source binding")
            elif matches:
                raise ValueError("Ordinary layer cannot substitute a derived source binding")
        if any(
            binding.layer_id not in {layer.id for layer in self.layers}
            for binding in self.source_bindings
        ):
            raise ValueError("Source binding references unselected layer")
        return self


class DeliveryPrimitive(_Model):
    kind: Literal["line", "arc"]
    call_id: Identifier
    layer_id: Identifier
    start: XY
    end: XY
    center: XY | None = None
    radius: FiniteFloat | None = Field(default=None, gt=0)
    sweep_deg: FiniteFloat | None = Field(default=None, gt=0, le=360)
    curve_dir: Literal["left", "right"] | None = None
    length: FiniteFloat = Field(gt=0)
    selected_bearing_deg: FiniteFloat | None = None
    selected_distance_ft: FiniteFloat | None = None
    input_status: Literal[
        "recorded", "hypothetical", "source_correction", "corridor_derived", "plss_reference"
    ] = "recorded"
    recorded_bearing_deg: FiniteFloat | None = None
    recorded_distance_ft: FiniteFloat | None = None


class DeliveryItem(_Model):
    selection: DeliveryLayer
    plot: PreparedPlot | None = None
    placement: PlotPlacement | None = None
    placement_original_geometry_hash: Digest | None = None
    placement_binding_baseline_sha256: Digest | None = None
    primitives: tuple[DeliveryPrimitive, ...] = ()
    vector: VectorLayer | None = None
    raster: RasterLayer | None = None


class DeliveryOmission(_Model):
    format: Literal["svg", "pdf", "dxf", "geojson", "all"]
    layer_id: Identifier | None = None
    reason: str


class DeliveryMetric(_Model):
    calculation_id: Identifier
    misclosure_ft: FiniteFloat | None
    area_sq_ft: FiniteFloat | None
    perimeter_ft: FiniteFloat | None
    unavailable_reason: str | None = None


class DeliverySnapshot(_Model):
    schema_version: Literal["1.0"] = "1.0"
    exporter_version: Literal["delivery-1"] = "delivery-1"
    request: DeliveryRequest
    request_sha256: Digest
    revision_sha256: Digest
    items: tuple[DeliveryItem, ...]
    metrics: tuple[DeliveryMetric, ...]
    omissions: tuple[DeliveryOmission, ...] = ()
    derived_sources: tuple[dict[str, Any], ...] = ()
    source_references: tuple[dict[str, Any], ...] = ()
    selected_revision_calls: tuple[dict[str, Any], ...] = ()
    unresolved_findings: tuple[str, ...] = ()
    crs: str | None = None
    scene_units: LinearUnit | None = None
    coordinate_policy: str = "Recorded values remain separate; placement changes coordinates; presentation rotation affects SVG/PDF only."
    software_versions: tuple[tuple[str, str], ...] = ()
    canonical_verification: Literal["not_requested"] = "not_requested"
    verified_export_eligible: Literal[False] = False


class DeliveryManifest(_Model):
    schema_version: Literal["1.0"] = "1.0"
    save_state: Literal["published"] = "published"
    exporter_version: Literal["delivery-1"] = "delivery-1"
    request_sha256: Digest
    snapshot_sha256: Digest
    revision_sha256: Digest
    artifacts: dict[str, Digest]
    omissions: tuple[DeliveryOmission, ...]
