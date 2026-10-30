"""Render-time EXIF orientation guard decodes each embedded raster once."""

import base64
import hashlib
import io
import re

import pytest
from mp_export import raster_guard
from mp_export.raster_guard import require_upright_raster
from mp_models.raster import RASTER_ORIENTATION_MESSAGE, RasterLayer, RasterRegistration
from PIL import Image


def _layer(orientation):
    image = Image.new("RGB", (10, 20))
    exif = Image.Exif()
    exif[274] = orientation
    stream = io.BytesIO()
    image.save(stream, format="JPEG", exif=exif.tobytes())
    data = stream.getvalue()
    return RasterLayer(
        id="guard-raster",
        label="guard.jpg",
        source_id="src",
        scene_id="scene",
        mime_type="image/jpeg",
        width=10,
        height=20,
        sha256=hashlib.sha256(data).hexdigest(),
        data_base64=base64.b64encode(data).decode(),
        registration=RasterRegistration(method="supplied_affine", matrix=(1, 0, 0, 0, 1, 0)),
    )


def test_require_upright_raster_decodes_once_for_repeated_renders(monkeypatch):
    layer = _layer(1)
    raster_guard._ORIENTATION_BY_DIGEST.clear()
    decodes = []
    real_b64decode = base64.b64decode

    def spy(data, *args, **kwargs):
        decodes.append(len(data))
        return real_b64decode(data, *args, **kwargs)

    monkeypatch.setattr(raster_guard.base64, "b64decode", spy)
    require_upright_raster(layer)
    require_upright_raster(layer)
    assert len(decodes) == 1


def test_orientation_cache_is_keyed_on_layer_sha256_without_hashing_payload(monkeypatch):
    layer = _layer(1)
    raster_guard._ORIENTATION_BY_DIGEST.clear()
    hashed = []
    real_sha256 = hashlib.sha256

    def spy(*args, **kwargs):
        hashed.append(args)
        return real_sha256(*args, **kwargs)

    monkeypatch.setattr(hashlib, "sha256", spy)
    require_upright_raster(layer)
    assert list(raster_guard._ORIENTATION_BY_DIGEST) == [layer.sha256]
    assert re.fullmatch(r"[0-9a-f]{64}", layer.sha256)
    assert hashed == []


def test_rotated_raster_is_refused_on_every_repeated_render():
    layer = _layer(6)
    for _ in range(2):
        with pytest.raises(ValueError) as excinfo:
            require_upright_raster(layer)
        assert str(excinfo.value) == RASTER_ORIENTATION_MESSAGE


def test_dashboard_raster_svg_omits_oriented_raster_with_reason():
    from mp_export.dashboard_html import _raster_svg

    svg = _raster_svg(_layer(6))
    assert "raster_orientation" in svg
    assert RASTER_ORIENTATION_MESSAGE in svg
    assert "<image" not in svg
    assert "<image" in _raster_svg(_layer(1))
