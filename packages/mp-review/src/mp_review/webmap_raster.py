"""Derive bounded north-up geographic imagery from validated raster registration."""

from __future__ import annotations

import base64
import hashlib
import math
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from mp_models.plot import XY, PlotScene
from mp_models.raster import RasterLayer
from mp_models.webmap import WebMapOptions, WebMapProjectionRecord, WebMapRaster
from mp_verify.dashboard import _hash

from .raster_registration import transform_pixel, validate_raster_layer
from .webmap_projection import WebMapProjection, WebMapUnavailable, build_web_map_projection


@dataclass(frozen=True)
class PreparedRaster:
    record: WebMapRaster
    data: bytes


def _dependencies() -> tuple[Any, Any, Any, Any, Any, Any]:
    try:
        import numpy as np
        import rasterio  # type: ignore[import-untyped]
        from PIL import Image
        from rasterio.transform import Affine  # type: ignore[import-untyped]
        from rasterio.warp import Resampling, reproject  # type: ignore[import-untyped]
    except ImportError as exc:
        raise WebMapUnavailable(
            "dependency_unavailable", "Install mp-review[web-map] for geographic raster display."
        ) from exc
    return np, rasterio, Image, Affine, Resampling, reproject


def _bounds(
    layer: RasterLayer, projection: WebMapProjection, options: WebMapOptions
) -> tuple[float, float, float, float]:
    """Densify all four outer edges before grid allocation, with bounded refinement."""
    points: list[XY] = []
    count = 0
    nonlinear = False
    tolerance = min(options.tolerance_m, options.raster_pixel_size_m / 8)

    def projected(pixel: XY) -> XY:
        nonlocal count
        count += 1
        if count > 100000:
            raise WebMapUnavailable("raster_limit", "Raster extent sampling exceeds its budget.")
        return projection.to_mercator(transform_pixel(layer.registration, pixel))

    def edge(p: XY, q: XY, start: XY, end: XY, depth: int) -> None:
        nonlocal nonlinear
        sampled = []
        deviations = []
        dx, dy = end[0] - start[0], end[1] - start[1]
        squared = dx * dx + dy * dy
        for fraction in (0.25, 0.5, 0.75):
            pixel = (p[0] + fraction * (q[0] - p[0]), p[1] + fraction * (q[1] - p[1]))
            point = projected(pixel)
            sampled.append((pixel, point))
            t = (
                max(
                    0.0,
                    min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / squared),
                )
                if squared
                else 0.0
            )
            deviations.append(
                math.hypot(point[0] - start[0] - t * dx, point[1] - start[1] - t * dy)
            )
        deviation = max(deviations)
        nonlinear = nonlinear or deviation > 1e-7
        if deviation > tolerance:
            if depth >= options.max_depth:
                raise WebMapUnavailable(
                    "raster_limit", "Raster extent sampling exceeds its depth limit."
                )
            mid, mid_projected = sampled[1]
            edge(p, mid, start, mid_projected, depth + 1)
            edge(mid, q, mid_projected, end, depth + 1)
        else:
            points.extend((start, *(point for _, point in sampled), end))

    corners = (
        (-0.5, -0.5),
        (layer.width - 0.5, -0.5),
        (layer.width - 0.5, layer.height - 0.5),
        (-0.5, layer.height - 0.5),
    )
    for index, p in enumerate(corners):
        q = corners[(index + 1) % 4]
        # Seed each edge independently so quarter-point tests cannot miss a
        # broad curve whose endpoints happen to lie on a projected chord.
        for section in range(64):
            a = (p[0] + (q[0] - p[0]) * section / 64, p[1] + (q[1] - p[1]) * section / 64)
            b = (
                p[0] + (q[0] - p[0]) * (section + 1) / 64,
                p[1] + (q[1] - p[1]) * (section + 1) / 64,
            )
            edge(a, b, projected(a), projected(b), 0)
    # Probe the image interior for projection-domain failures too.
    for row in range(9):
        for column in range(9):
            projected((-0.5 + layer.width * column / 8, -0.5 + layer.height * row / 8))
    margin = tolerance if nonlinear else 0.0
    return (
        min(p[0] for p in points) - margin,
        min(p[1] for p in points) - margin,
        max(p[0] for p in points) + margin,
        max(p[1] for p in points) + margin,
    )


def prepare_web_map_raster(
    layer: RasterLayer,
    scene: PlotScene,
    *,
    projection: WebMapProjection,
    options: WebMapOptions,
) -> PreparedRaster:
    """Warp premultiplied RGBA with the exact recorded operation, without networking."""
    np, rasterio, Image, Affine, Resampling, reproject = _dependencies()
    # Revalidation catches model_copy/model_construct tampering before decoding
    # or allocation; invalid supplied data is an error, not an omitted display.
    layer = RasterLayer.model_validate(layer.model_dump(mode="json"))
    options = WebMapOptions.model_validate(options.model_dump(mode="json"))
    fresh = build_web_map_projection(scene, extent=projection.extent)
    if (projection.source_crs_wkt, projection.pipeline, projection.versions) != (
        fresh.source_crs_wkt,
        fresh.pipeline,
        fresh.versions,
    ):
        raise ValueError("Raster projection does not match the freshly validated scene projection")
    units = scene.units
    if units == "unknown_ft":
        raise ValueError("Raster geographic display requires explicit scene units")
    if tuple(int(part) for part in rasterio.__gdal_version__.split(".")[:2]) < (3, 11):
        raise WebMapUnavailable(
            "operation_unavailable",
            "Raster display requires GDAL 3.11 or newer for strict operation selection.",
        )
    validate_raster_layer(layer, scene)
    xmin, ymin, xmax, ymax = _bounds(layer, projection, options)
    resolution = options.raster_pixel_size_m
    if not all(math.isfinite(v) for v in (xmin, ymin, xmax, ymax)) or xmin >= xmax or ymin >= ymax:
        raise WebMapUnavailable(
            "projection_domain", "Raster extent is outside the supported domain."
        )
    width_float, height_float = (xmax - xmin) / resolution, (ymax - ymin) / resolution
    if not math.isfinite(width_float) or not math.isfinite(height_float):
        raise WebMapUnavailable(
            "raster_limit", "Requested raster resolution exceeds the output budget."
        )
    width, height = max(1, math.ceil(width_float)), max(1, math.ceil(height_float))
    if (
        width > options.max_raster_dimension
        or height > options.max_raster_dimension
        or width * height > options.max_raster_pixels
    ):
        raise WebMapUnavailable(
            "raster_limit", "Requested raster resolution exceeds the output budget."
        )
    affine = Affine(resolution, 0, xmin, 0, -resolution, ymax)
    outer = (
        (xmin, ymax),
        (xmin + width * resolution, ymax),
        (xmin + width * resolution, ymax - height * resolution),
        (xmin, ymax - height * resolution),
    )
    corners = (
        projection.from_mercator(outer[0]),
        projection.from_mercator(outer[1]),
        projection.from_mercator(outer[2]),
        projection.from_mercator(outer[3]),
    )
    if any(
        abs(p[0] - q[0]) > 180 for p, q in zip(corners, (*corners[1:], corners[0]), strict=True)
    ):
        raise WebMapUnavailable(
            "projection_domain", "Antimeridian-spanning rasters are unsupported."
        )
    a, b, c, d, e, f = layer.registration.matrix
    source_affine = Affine(a, b, c - 0.5 * a - 0.5 * b, d, e, f - 0.5 * d - 0.5 * e)
    data = base64.b64decode(layer.data_base64, validate=True)
    try:
        with Image.open(BytesIO(data)) as image:
            rgba = np.asarray(image.convert("RGBA"), dtype="float32") / 255.0
        # Interpolate premultiplied colors and opacity independently. Hidden RGB
        # in transparent source pixels cannot create dark or colored fringes.
        rgba[:, :, :3] *= rgba[:, :, 3:4]
        source = np.moveaxis(rgba, 2, 0)
        target = np.zeros((4, height, width), dtype="float32")
        with rasterio.Env(PROJ_NETWORK="OFF", CHECK_WITH_INVERT_PROJ="YES"):
            reproject(
                source,
                target,
                src_transform=source_affine,
                src_crs=projection.source_crs_wkt,
                dst_transform=affine,
                dst_crs="EPSG:3857",
                resampling=Resampling.bilinear,
                tolerance=0,
                num_threads=1,
                init_dest_nodata=True,
                COORDINATE_OPERATION=projection.pipeline,
                ALLOW_BALLPARK="NO",
                ONLY_BEST="YES",
            )
        alpha = np.clip(target[3], 0.0, 1.0)
        rgb = np.zeros_like(target[:3])
        np.divide(target[:3], alpha[None, :, :], out=rgb, where=alpha[None, :, :] > 0)
        output = np.empty((height, width, 4), dtype="uint8")
        output[:, :, :3] = np.moveaxis(np.rint(np.clip(rgb, 0, 1) * 255).astype("uint8"), 0, 2)
        output[:, :, 3] = np.rint(alpha * 255).astype("uint8")
        output[output[:, :, 3] == 0, :3] = 0
        stream = BytesIO()
        Image.fromarray(output).save(stream, format="PNG", compress_level=9)
        encoded = stream.getvalue()
        versions = [
            ("rasterio", rasterio.__version__),
            ("gdal", rasterio.__gdal_version__),
            ("proj", rasterio.__proj_version__),
        ]
        from rasterio._env import get_proj_data_search_paths  # type: ignore[import-untyped]

        for directory in get_proj_data_search_paths():
            database = Path(directory) / "proj.db"
            if database.is_file():
                versions.append(
                    ("proj_database_sha256", hashlib.sha256(database.read_bytes()).hexdigest())
                )
                break
    except Exception as exc:
        raise WebMapUnavailable(
            "operation_unavailable", "The exact raster coordinate operation could not be applied."
        ) from exc
    projection_record = WebMapProjectionRecord(
        source_crs_wkt=projection.source_crs_wkt,
        pipeline=projection.pipeline,
        accuracy_m=projection.accuracy,
        versions=projection.versions,
    )
    safe_name = "raster-" + hashlib.sha256(layer.id.encode()).hexdigest()[:24]
    record = WebMapRaster(
        id=layer.id,
        source_id=layer.source_id,
        source_sha256=layer.sha256,
        registration_sha256=_hash(layer.registration.model_dump(mode="json")),
        projection_sha256=_hash(projection_record.model_dump(mode="json")),
        path=f"web-map-assets/{safe_name}.png",
        sha256=hashlib.sha256(encoded).hexdigest(),
        width=width,
        height=height,
        pixel_size_m=resolution,
        grid_affine=(affine.a, affine.b, affine.c, affine.d, affine.e, affine.f),
        corners=corners,
        registration_status=layer.registration.status,
        fit_rms=layer.registration.fit_rms,
        checkpoint_rms=layer.registration.checkpoint_rms,
        residual_units=units,
        versions=tuple(versions),
    )
    return PreparedRaster(record, encoded)
