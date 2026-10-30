"""Shared render-time guard for raster layers saved before EXIF orientation was enforced."""

from __future__ import annotations

import base64

from mp_models.raster import RASTER_ORIENTATION_MESSAGE, RasterLayer, image_orientation


def require_upright_raster(layer: RasterLayer) -> None:
    """Refuse to embed a raster whose EXIF Orientation would make browsers rotate it."""
    if image_orientation(base64.b64decode(layer.data_base64)) not in (None, 1):
        raise ValueError(RASTER_ORIENTATION_MESSAGE)
