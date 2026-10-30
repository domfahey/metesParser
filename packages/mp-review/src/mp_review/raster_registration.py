"""Deterministic affine calibration transforms the supplied scan, never deed calls."""

from __future__ import annotations

import base64
import hashlib
import math
import warnings
from collections.abc import Sequence
from io import BytesIO

from mp_models.plot import XY, MapSource, PlotScene
from mp_models.raster import (
    RASTER_ORIENTATION_MESSAGE,
    RasterControl,
    RasterLayer,
    RasterRegistration,
    image_orientation,
)


def transform_pixel(registration: RasterRegistration, pixel: XY) -> XY:
    a, b, c, d, e, f = registration.matrix
    u, v = pixel
    result = (a * u + b * v + c, d * u + e * v + f)
    if not all(math.isfinite(p) for p in result):
        raise ValueError("Nonfinite transformed raster coordinates")
    return result


def outer_corners(registration: RasterRegistration, width: int, height: int) -> tuple[XY, ...]:
    return tuple(
        transform_pixel(registration, p)
        for p in (
            (-0.5, -0.5),
            (width - 0.5, -0.5),
            (width - 0.5, height - 0.5),
            (-0.5, height - 0.5),
        )
    )


def _solve(matrix: list[list[float]], rhs: list[float]) -> tuple[float, ...]:
    augmented = [list(row) + [value] for row, value in zip(matrix, rhs, strict=False)]
    scale = max(abs(v) for row in matrix for v in row)
    for column in range(3):
        pivot = max(range(column, 3), key=lambda i: abs(augmented[i][column]))
        if abs(augmented[pivot][column]) <= scale * 1e-12:
            raise ValueError("Control points are collinear or ill-conditioned")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        factor = augmented[column][column]
        augmented[column] = [v / factor for v in augmented[column]]
        for row in range(3):
            if row != column:
                factor = augmented[row][column]
                augmented[row] = [
                    v - factor * w for v, w in zip(augmented[row], augmented[column], strict=False)
                ]
    return tuple(row[3] for row in augmented)


def supplied_affine(
    matrix: Sequence[float], controls: tuple[RasterControl, ...] = ()
) -> RasterRegistration:
    return RasterRegistration.model_validate(
        {"matrix": matrix, "method": "supplied_affine", "controls": controls}
    )


def fit_affine(controls: tuple[RasterControl, ...]) -> RasterRegistration:
    """Least squares fit; checkpoints never participate in the fit."""
    fit = [p for p in controls if p.role == "fit"]
    if (
        len(fit) < 3
        or len({p.id for p in controls}) != len(controls)
        or len({p.pixel for p in fit}) != len(fit)
    ):
        raise ValueError("At least three distinct named fit controls are required")
    # Center/normalize both domains to preserve precision at large scene offsets.
    n = len(fit)
    u = sum(p.pixel[0] for p in fit) / n
    v = sum(p.pixel[1] for p in fit) / n
    x = sum(p.scene[0] for p in fit) / n
    y = sum(p.scene[1] for p in fit) / n
    span = max(max(abs(p.pixel[0] - u), abs(p.pixel[1] - v)) for p in fit)
    if not span:
        raise ValueError("Duplicate fit pixels")
    rows = [((p.pixel[0] - u) / span, (p.pixel[1] - v) / span, 1) for p in fit]
    normal = [[sum(row[i] * row[j] for row in rows) for j in range(3)] for i in range(3)]
    sx = _solve(
        normal,
        [
            sum(row[i] * (p.scene[0] - x) for row, p in zip(rows, fit, strict=False))
            for i in range(3)
        ],
    )
    sy = _solve(
        normal,
        [
            sum(row[i] * (p.scene[1] - y) for row, p in zip(rows, fit, strict=False))
            for i in range(3)
        ],
    )
    a, b = sx[0] / span, sx[1] / span
    d, e = sy[0] / span, sy[1] / span
    initial = RasterRegistration(
        matrix=(a, b, x + sx[2] - a * u - b * v, d, e, y + sy[2] - d * u - e * v),
        method="affine_least_squares",
        controls=controls,
    )
    return initial


def image_layer(
    data: bytes, *, scene: PlotScene, registration: RasterRegistration, filename: str
) -> tuple[RasterLayer, MapSource]:
    if len(data) > 20 * 1024 * 1024:
        raise ValueError("Raster exceeds 20 MiB limit")
    if scene.units == "unknown_ft":
        raise ValueError("Raster registration requires explicit scene linear units")
    try:
        from PIL import Image
    except ImportError as exc:
        raise ValueError("Install mp-review[geo] for raster image validation") from exc
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                image.verify()
            with Image.open(BytesIO(data)) as image:
                if image.format not in ("PNG", "JPEG", "WEBP"):
                    raise ValueError("Only PNG/JPEG/WebP images are supported")
                if getattr(image, "n_frames", 1) != 1:
                    raise ValueError("Animated images are unsupported")
                width, height = image.size
                if width > 20000 or height > 20000 or width * height > 40_000_000:
                    raise ValueError("Raster dimensions exceed import limit")
                if image_orientation(data) not in (None, 1):
                    raise ValueError(RASTER_ORIENTATION_MESSAGE)
                image.load()
                mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[
                    image.format
                ]
    except Exception as exc:
        raise ValueError(f"Invalid raster content: {exc}") from exc
    digest = hashlib.sha256(data).hexdigest()
    source_id = f"map-{digest[:16]}"
    layer = RasterLayer.model_validate(
        {
            "id": f"raster-{digest[:16]}",
            "label": filename,
            "source_id": source_id,
            "scene_id": scene.id,
            "mime_type": mime,
            "width": width,
            "height": height,
            "sha256": digest,
            "data_base64": base64.b64encode(data).decode(),
            "registration": registration,
        }
    )
    source = MapSource(
        id=source_id,
        label=filename,
        filename=filename,
        sha256=digest,
        native_units="pixel",
        data_base64=base64.b64encode(data).decode(),
        processing_history=(
            "Supplied scan; integer pixel centers; affine calibration is approximate, not survey accuracy.",
        ),
    )
    return layer, source


def validate_raster_layer(layer: RasterLayer, scene: PlotScene) -> None:
    """Freshly decode a supplied layer and validate its derived registration outputs."""
    if layer.scene_id != scene.id:
        raise ValueError("Raster scene reference mismatch")
    registration = (
        fit_affine(layer.registration.controls)
        if layer.registration.method == "affine_least_squares"
        else supplied_affine(layer.registration.matrix, layer.registration.controls)
    )
    for actual, expected in zip(layer.registration.matrix, registration.matrix, strict=True):
        if not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-9):
            raise ValueError("Raster registration matrix does not match controls")
    if (
        layer.registration.residuals != registration.residuals
        or layer.registration.fit_rms != registration.fit_rms
        or layer.registration.checkpoint_rms != registration.checkpoint_rms
    ):
        raise ValueError("Raster registration residuals do not match controls")
    decoded, _ = image_layer(
        base64.b64decode(layer.data_base64, validate=True),
        scene=scene,
        registration=registration,
        filename=layer.label,
    )
    if (decoded.width, decoded.height, decoded.mime_type, decoded.sha256) != (
        layer.width,
        layer.height,
        layer.mime_type,
        layer.sha256,
    ):
        raise ValueError("Raster declared dimensions/MIME/hash do not match decoded content")
