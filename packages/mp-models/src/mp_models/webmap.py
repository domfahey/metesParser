"""Provider-independent geographic display contracts; never verification inputs."""

from typing import Annotated, Literal, Self

from pydantic import Field, FiniteFloat, model_validator

from .base import _Model
from .plot import Digest, Identifier

MAX_LATITUDE = 85.0511287798066
Longitude = Annotated[FiniteFloat, Field(ge=-180, le=180)]
Latitude = Annotated[FiniteFloat, Field(ge=-MAX_LATITUDE, le=MAX_LATITUDE)]
LngLat = tuple[Longitude, Latitude]
Opacity = Annotated[FiniteFloat, Field(ge=0, le=1)]


class WebMapOptions(_Model):
    tolerance_m: Annotated[FiniteFloat, Field(gt=0)] = 0.05
    max_depth: Annotated[int, Field(strict=True, ge=1, le=20)] = 20
    max_vertices: Annotated[int, Field(strict=True, ge=2, le=100000)] = 100000
    raster_pixel_size_m: Annotated[FiniteFloat, Field(gt=0)] = 0.25
    max_raster_dimension: Annotated[int, Field(strict=True, ge=1, le=4096)] = 4096
    max_raster_pixels: Annotated[int, Field(strict=True, ge=1, le=16777216)] = 16777216


class MapboxViewOptions(_Model):
    provider: Literal["mapbox"] = "mapbox"
    style: Literal["standard", "standard-satellite"] = "standard"
    raster_opacity: Opacity = 0.55


class WebMapRequest(_Model):
    schema_version: Literal["1.0"] = "1.0"
    scene_id: Identifier
    display: WebMapOptions = Field(default_factory=WebMapOptions)
    view: MapboxViewOptions = Field(default_factory=MapboxViewOptions)


class WebMapPoint(_Model):
    type: Literal["Point"] = "Point"
    coordinates: LngLat


class WebMapLine(_Model):
    type: Literal["LineString"] = "LineString"
    coordinates: tuple[LngLat, ...] = Field(min_length=2)


def _check_rings(polygons: tuple[tuple[tuple[LngLat, ...], ...], ...]) -> None:
    for polygon in polygons:
        if not polygon:
            raise ValueError("polygon requires an exterior ring")
        for ring in polygon:
            if len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError("context polygon rings must be closed")


class WebMapPolygon(_Model):
    type: Literal["Polygon"] = "Polygon"
    coordinates: tuple[tuple[LngLat, ...], ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _rings(self) -> Self:
        _check_rings((self.coordinates,))
        return self


class WebMapMultiPolygon(_Model):
    type: Literal["MultiPolygon"] = "MultiPolygon"
    coordinates: tuple[tuple[tuple[LngLat, ...], ...], ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _rings(self) -> Self:
        _check_rings(self.coordinates)
        return self


class WebMapProperties(_Model):
    kind: Literal["recorded_course", "closure_gap", "pob", "parcel_context"]
    calculation_id: Identifier | None = None
    call_id: Identifier | None = None
    occurrence_id: Identifier | None = None
    page_id: Identifier | None = None
    source_id: Identifier | None = None
    layer_id: Identifier | None = None
    geometry_hash: Digest | None = None
    placement_hash: Digest | None = None
    placement_id: Identifier | None = None
    placement_status: Literal["approximate", "referenced"] | None = None
    completeness: Literal["complete", "partial", "unresolved"] | None = None
    label: str = ""


class WebMapFeature(_Model):
    type: Literal["Feature"] = "Feature"
    id: Identifier
    geometry: Annotated[
        WebMapPoint | WebMapLine | WebMapPolygon | WebMapMultiPolygon,
        Field(discriminator="type"),
    ]
    properties: WebMapProperties

    @model_validator(mode="after")
    def _identity(self) -> Self:
        p = self.properties
        if p.kind == "parcel_context":
            if (
                not p.source_id
                or not p.layer_id
                or self.geometry.type not in {"Polygon", "MultiPolygon"}
            ):
                raise ValueError("parcel context requires source/layer and polygon geometry")
        else:
            if not all(
                (
                    p.calculation_id,
                    p.geometry_hash,
                    p.placement_id,
                    p.placement_hash,
                    p.placement_status,
                )
            ):
                raise ValueError("deed display requires canonical geometry and placement identity")
            if p.kind == "recorded_course" and (
                not p.call_id or self.geometry.type != "LineString"
            ):
                raise ValueError("recorded course requires call identity and line geometry")
            if p.kind != "recorded_course" and p.call_id is not None:
                raise ValueError("display markers must not impersonate recorded calls")
            if p.kind == "closure_gap" and self.geometry.type != "LineString":
                raise ValueError("closure gap requires line geometry")
            if p.kind == "pob" and self.geometry.type != "Point":
                raise ValueError("POB requires point geometry")
        return self


class WebMapProjectionRecord(_Model):
    source_crs_wkt: str
    target_crs: Literal["EPSG:3857"] = "EPSG:3857"
    geographic_crs: Literal["EPSG:4326"] = "EPSG:4326"
    axis_order: Literal["xy"] = "xy"
    pipeline: str
    accuracy_m: Annotated[FiniteFloat, Field(ge=0)] | None = None
    versions: tuple[tuple[str, str], ...] = ()


class WebMapRaster(_Model):
    id: Identifier
    source_id: Identifier
    source_sha256: Digest
    registration_sha256: Digest
    projection_sha256: Digest
    path: str = Field(pattern=r"^web-map-assets/[A-Za-z][A-Za-z0-9_.-]*\.png$")
    sha256: Digest
    width: Annotated[int, Field(strict=True, ge=1, le=4096)]
    height: Annotated[int, Field(strict=True, ge=1, le=4096)]
    pixel_size_m: Annotated[FiniteFloat, Field(gt=0)]
    grid_affine: tuple[FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat]
    corners: tuple[LngLat, LngLat, LngLat, LngLat]
    resampling: Literal["bilinear"] = "bilinear"
    nodata: Literal["transparent"] = "transparent"
    registration_status: Literal["approximate"] = "approximate"
    fit_rms: Annotated[FiniteFloat, Field(ge=0)] | None = None
    checkpoint_rms: Annotated[FiniteFloat, Field(ge=0)] | None = None
    residual_units: Literal["international_ft", "us_survey_ft", "m"]
    versions: tuple[tuple[str, str], ...] = ()


class WebMapUnavailableItem(_Model):
    item_id: Identifier
    kind: Literal["calculation", "raster", "vector", "scene"]
    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    reason: str


class WebMapArtifact(_Model):
    schema_version: Literal["1.0"] = "1.0"
    adapter_version: str = "web-map-1.0.0"
    scene_id: Identifier
    input_hashes: tuple[tuple[str, Digest], ...]
    options: WebMapOptions
    options_sha256: Digest
    projection: WebMapProjectionRecord | None = None
    features: tuple[WebMapFeature, ...] = ()
    rasters: tuple[WebMapRaster, ...] = ()
    unavailable: tuple[WebMapUnavailableItem, ...] = ()
    availability: Literal["ready", "partial", "unavailable"]
    bounds: tuple[Longitude, Latitude, Longitude, Latitude] | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        included = bool(self.features or self.rasters)
        expected = (
            "partial" if included and self.unavailable else "ready" if included else "unavailable"
        )
        if self.availability != expected:
            raise ValueError("availability does not match included and unavailable evidence")
        if included and (self.projection is None or self.bounds is None):
            raise ValueError("geographic display requires projection provenance and bounds")
        if not included and self.bounds is not None:
            raise ValueError("unavailable display cannot invent bounds")
        if self.bounds and (self.bounds[0] > self.bounds[2] or self.bounds[1] > self.bounds[3]):
            raise ValueError("bounds must be ordered and must not span antimeridian")
        for items in (self.features, self.rasters):
            if len({item.id for item in items}) != len(items):
                raise ValueError("display IDs must be unique")
        if len({k for k, _ in self.input_hashes}) != len(self.input_hashes):
            raise ValueError("input hash names must be unique")
        return self
