"""Shared render-time guard for raster layers saved before EXIF orientation was enforced."""

from __future__ import annotations

import base64

from mp_models.raster import RASTER_ORIENTATION_MESSAGE, RasterLayer, image_orientation

_CACHE_LIMIT = 16
# Holds only RasterLayer.sha256 digests and small orientation ints, never the payload itself.
_ORIENTATION_BY_DIGEST: dict[str, int | None] = {}


def _orientation_for(digest: str, data_base64: str) -> int | None:
    # Repeated renders of one raster decode it once; the payload is released after the miss.
    if digest not in _ORIENTATION_BY_DIGEST:
        if len(_ORIENTATION_BY_DIGEST) >= _CACHE_LIMIT:
            _ORIENTATION_BY_DIGEST.pop(next(iter(_ORIENTATION_BY_DIGEST)))
        _ORIENTATION_BY_DIGEST[digest] = image_orientation(base64.b64decode(data_base64))
    return _ORIENTATION_BY_DIGEST[digest]


def require_upright_raster(layer: RasterLayer) -> None:
    """Refuse to embed a raster whose EXIF Orientation would make browsers rotate it."""
    # RasterLayer validates sha256 against the decoded bytes, so it is a sound cache key.
    if _orientation_for(layer.sha256, layer.data_base64) not in (None, 1):
        raise ValueError(RASTER_ORIENTATION_MESSAGE)


# Same code prepare_web_map reports when it omits such a legacy raster.
RASTER_ORIENTATION_REASON = "raster_orientation"


def raster_orientation_omission(layer: RasterLayer) -> str | None:
    """Return the omission message for a legacy EXIF-rotated raster, else None."""
    try:
        require_upright_raster(layer)
    except ValueError as exc:
        return str(exc)
    return None
