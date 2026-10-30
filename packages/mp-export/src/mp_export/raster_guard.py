"""Shared render-time guard for raster layers saved before EXIF orientation was enforced."""

from __future__ import annotations

import base64
from functools import lru_cache

from mp_models.raster import RASTER_ORIENTATION_MESSAGE, RasterLayer, image_orientation


@lru_cache(maxsize=16)
def _orientation_for(data_base64: str) -> int | None:
    # Keyed on the embedded content so repeated renders of one raster decode it once.
    return image_orientation(base64.b64decode(data_base64))


def require_upright_raster(layer: RasterLayer) -> None:
    """Refuse to embed a raster whose EXIF Orientation would make browsers rotate it."""
    if _orientation_for(layer.data_base64) not in (None, 1):
        raise ValueError(RASTER_ORIENTATION_MESSAGE)
