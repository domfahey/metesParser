"""Offline, fail-closed operation selection for geographic display preparation."""

from __future__ import annotations

import hashlib
import math
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mp_models.plot import XY, PlotScene
from mp_verify.scene import validate_scene

_MERCATOR_LIMIT = math.pi * 6378137.0
_DOMAIN_MESSAGE = "Coordinates are outside the supported Web Mercator domain."


class WebMapUnavailable(ValueError):
    """A safe display-only omission reason, without raw CRS or provider content."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _point(point: XY) -> XY:
    try:
        if len(point) != 2 or any(isinstance(v, bool) or not math.isfinite(v) for v in point):
            raise ValueError
        return float(point[0]), float(point[1])
    except (TypeError, ValueError, OverflowError) as exc:
        raise WebMapUnavailable("projection_domain", _DOMAIN_MESSAGE) from exc


def _mercator(point: XY) -> XY:
    x, y = _point(point)
    if abs(x) > _MERCATOR_LIMIT or abs(y) > _MERCATOR_LIMIT:
        raise WebMapUnavailable("projection_domain", _DOMAIN_MESSAGE)
    return x, y


@dataclass(frozen=True)
class WebMapProjection:
    """One exact source→3857 operation and a normalized XY public interface.

    ``pipeline`` uses the source CRS's authority axis order, as required by
    GDAL's COORDINATE_OPERATION. Callers of ``to_mercator`` always supply XY;
    the private adapter handles north/east authority axes. Global ``over``
    prevents PROJ from wrapping an invalid longitude into a plausible parcel.
    """

    source_crs_wkt: str
    pipeline: str
    accuracy: float | None
    versions: tuple[tuple[str, str], ...]
    _forward: Callable[[float, float], XY] = field(repr=False, compare=False)
    _geographic: Callable[[float, float], XY] = field(repr=False, compare=False)
    extent: tuple[float, float, float, float] | None = None

    def to_mercator(self, point: XY) -> XY:
        """Transform normalized scene XY to EPSG:3857 meters, without wrapping."""
        x, y = _point(point)
        try:
            result = self._forward(x, y)
        except Exception as exc:
            raise WebMapUnavailable("projection_domain", _DOMAIN_MESSAGE) from exc
        return _mercator(result)

    def from_mercator(self, point: XY) -> XY:
        """Convert EPSG:3857 meters to WGS84 longitude/latitude, in that order."""
        x, y = _mercator(point)
        try:
            result = _point(self._geographic(x, y))
        except Exception as exc:
            raise WebMapUnavailable("projection_domain", _DOMAIN_MESSAGE) from exc
        if abs(result[0]) > 180 or abs(result[1]) > 85.0511287798066:
            raise WebMapUnavailable("projection_domain", _DOMAIN_MESSAGE)
        return result


def _projection_dependencies() -> Any:
    try:
        import pyproj
        from pyproj.transformer import TransformerGroup
    except ImportError as exc:
        raise WebMapUnavailable(
            "dependency_unavailable", "Install mp-review[web-map] for geographic display."
        ) from exc
    return pyproj, TransformerGroup


def _geographic_bounds(
    pyproj: Any, source: Any, extent: tuple[float, float, float, float]
) -> tuple[float, float, float, float]:
    """Geographic (west, south, east, north) bounds of a source-CRS XY extent.

    Ballpark transforms are acceptable here: the bounds only select and check an
    operation's area of use; they are never used for displayed coordinates.
    """
    if len(extent) != 4 or not all(
        isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) for v in extent
    ):
        raise ValueError("Extent is not finite")
    minx, miny, maxx, maxy = extent
    to_geographic = pyproj.Transformer.from_crs(source, "EPSG:4326", always_xy=True)
    points = [
        to_geographic.transform(
            minx + (maxx - minx) * i / 8, miny + (maxy - miny) * j / 8, errcheck=True
        )
        for i in range(9)
        for j in range(9)
    ]
    west, east = min(p[0] for p in points), max(p[0] for p in points)
    south, north = min(p[1] for p in points), max(p[1] for p in points)
    if east - west > 180 or not all(math.isfinite(v) for v in (west, south, east, north)):
        raise ValueError("Extent spans an unsupported longitude range")
    return west, south, east, north


def _covers(area: Any, bounds: tuple[float, float, float, float]) -> bool:
    if area is None:
        return False
    west, south, east, north = bounds
    if not (area.south <= south and north <= area.north):
        return False
    if area.west <= area.east:
        return bool(area.west <= west and east <= area.east)
    # Areas of use crossing the antimeridian list west > east.
    return bool(west >= area.west or east <= area.east)


def build_web_map_projection(
    scene: PlotScene, extent: tuple[float, float, float, float] | None = None
) -> WebMapProjection:
    """Validate scene units and select the best locally available non-ballpark operation.

    ``extent`` is the placed display extent as scene XY ``(minx, miny, maxx, maxy)``.
    When supplied, operation selection is area-aware and fails closed unless the
    chosen operation's area of use contains the whole extent. Without it, the
    operation's area of use is not checked.
    """
    if scene.kind == "local":
        try:
            validate_scene(scene)
        except ValueError as exc:
            raise WebMapUnavailable(
                "invalid_scene", "Scene CRS, axes, or units are invalid."
            ) from exc
        raise WebMapUnavailable("missing_georeference", "Local scene has no geographic reference.")
    pyproj, group_type = _projection_dependencies()
    pyproj.network.set_network_enabled(False)
    try:
        validate_scene(scene)
        source = pyproj.CRS.from_user_input(scene.crs)
        axes = tuple(axis.direction for axis in source.axis_info)
        if axes not in (("east", "north"), ("north", "east")):
            raise ValueError("Unsupported projected axis directions")
    except Exception as exc:
        raise WebMapUnavailable("invalid_scene", "Scene CRS, axes, or units are invalid.") from exc
    try:
        # Missing-grid warnings contain raw URLs/paths. The typed failure below
        # reports the same condition without exposing external diagnostic text.
        aoi = None
        if extent is not None:
            try:
                bounds = _geographic_bounds(pyproj, source, extent)
            except Exception as exc:
                raise WebMapUnavailable("projection_domain", _DOMAIN_MESSAGE) from exc
            from pyproj.aoi import AreaOfInterest

            aoi = AreaOfInterest(*bounds)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            group = group_type(
                source,
                "EPSG:3857",
                always_xy=False,
                allow_ballpark=False,
                area_of_interest=aoi,
            )
        if not group.best_available:
            raise WebMapUnavailable(
                "missing_grid", "Required coordinate-operation grids are unavailable locally."
            )
        if not group.transformers:
            raise WebMapUnavailable(
                "operation_unavailable", "No supported coordinate operation is available."
            )
        if extent is None:
            selected = group.transformers[0]
        else:
            covering = [t for t in group.transformers if _covers(t.area_of_use, bounds)]
            if not covering:
                raise WebMapUnavailable(
                    "operation_unavailable",
                    "No coordinate operation covers the placed display extent.",
                )
            selected = covering[0]
        definition = selected.definition
        if not definition or "unavailable" in definition.lower():
            raise ValueError("Operation cannot be serialized")
        pipeline = (
            definition.replace("proj=pipeline", "proj=pipeline over", 1)
            if definition.startswith("proj=pipeline")
            else definition + " over"
        )
        transformer = pyproj.Transformer.from_pipeline(pipeline)
        geographic = pyproj.Transformer.from_crs(
            "EPSG:3857", "EPSG:4326", always_xy=True, allow_ballpark=False, only_best=True
        )
        database = Path(pyproj.datadir.get_data_dir()) / "proj.db"
        versions = (
            ("pyproj", pyproj.__version__),
            ("proj", pyproj.proj_version_str),
            ("proj_database_sha256", hashlib.sha256(database.read_bytes()).hexdigest()),
            ("epsg", pyproj.database.get_database_metadata("EPSG.VERSION") or "unknown"),
        )
        accuracy = selected.accuracy

        def forward(x: float, y: float) -> XY:
            ordered = (y, x) if axes == ("north", "east") else (x, y)
            return _point(transformer.transform(*ordered, errcheck=True))

        def longitude_latitude(x: float, y: float) -> XY:
            return _point(geographic.transform(x, y, errcheck=True))

        return WebMapProjection(
            source_crs_wkt=source.to_wkt(),
            pipeline=pipeline,
            accuracy=None if accuracy < 0 or not math.isfinite(accuracy) else accuracy,
            versions=versions,
            _forward=forward,
            _geographic=longitude_latitude,
            extent=None if extent is None else (extent[0], extent[1], extent[2], extent[3]),
        )
    except WebMapUnavailable:
        raise
    except Exception as exc:
        raise WebMapUnavailable(
            "operation_unavailable", "The required coordinate operation cannot be enforced."
        ) from exc
