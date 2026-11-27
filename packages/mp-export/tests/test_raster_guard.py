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
        with pytest.raises(ValueError, match=re.escape(RASTER_ORIENTATION_MESSAGE)):
            require_upright_raster(layer)


def test_dashboard_raster_svg_omits_oriented_raster_with_reason():
    import json
    from pathlib import Path

    from mp_export.dashboard_html import render_dashboard
    from mp_models.dashboard import DashboardBundle
    from mp_verify.dashboard import calculate_dashboard

    fixture_path = (
        Path(__file__).resolve().parents[3]
        / "packages/mp-review/tests/fixtures/dashboard-absolute.json"
    )

    def render_with_orientation(orientation: int) -> str:
        layer = _layer(orientation)
        data = json.loads(fixture_path.read_text())
        data["schema_version"] = "1.1"
        data["calculations"][0]["frame"]["foot_definition"] = "international_ft"
        data["scenes"] = [
            {"id": "scene", "name": "Synthetic scene", "kind": "local", "units": "international_ft"}
        ]
        data["map_sources"] = [
            {
                "id": "src",
                "label": "Guard scan",
                "sha256": layer.sha256,
                "filename": "guard.jpg",
                "native_units": "international_ft",
            }
        ]
        data["raster_layers"] = [layer.model_dump(mode="json")]
        return render_dashboard(calculate_dashboard(DashboardBundle.model_validate(data)))

    oriented_html = render_with_orientation(6)
    assert 'data-omitted-raster="guard-raster"' in oriented_html
    assert "raster_orientation" in oriented_html
    assert RASTER_ORIENTATION_MESSAGE in oriented_html
    assert 'data-raster-layer="guard-raster"' not in oriented_html

    upright_html = render_with_orientation(1)
    assert '<image data-raster-layer="guard-raster"' in upright_html
    assert 'data-omitted-raster="guard-raster"' not in upright_html


def test_orientation_cache_evicts_oldest_digest_past_limit(monkeypatch):
    raster_guard._ORIENTATION_BY_DIGEST.clear()
    layers = []
    for idx in range(raster_guard._CACHE_LIMIT + 2):
        image = Image.new("RGB", (10, 20), color=(idx, 0, 0))
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        data = stream.getvalue()
        layers.append(
            RasterLayer(
                id=f"raster-{idx}",
                label=f"r{idx}.png",
                source_id="src",
                scene_id="scene",
                mime_type="image/png",
                width=10,
                height=20,
                sha256=hashlib.sha256(data).hexdigest(),
                data_base64=base64.b64encode(data).decode(),
                registration=RasterRegistration(
                    method="supplied_affine", matrix=(1, 0, 0, 0, 1, 0)
                ),
            )
        )
    for layer in layers:
        require_upright_raster(layer)

    decodes: list[int] = []
    real_b64decode = base64.b64decode

    def spy(data, *args, **kwargs):
        decodes.append(len(data))
        return real_b64decode(data, *args, **kwargs)

    monkeypatch.setattr(raster_guard.base64, "b64decode", spy)
    # Most recent layer is still cached -> no decode; oldest layer was evicted -> decodes again.
    require_upright_raster(layers[-1])
    assert decodes == []
    require_upright_raster(layers[0])
    assert len(decodes) == 1


def test_render_raster_picker_embeds_image_metadata_and_escapes_script_payload():
    import json

    from mp_export.raster_picker import render_raster_picker

    image = Image.new("RGB", (12, 8), color=(10, 20, 30))
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    data = stream.getvalue()
    payload_note = "</script><img src=x>&\u2028\u2029"
    config = {
        "scene": {"id": "scene-1", "name": payload_note},
        "controls": [{"id": "c1", "role": "fit", "pixel": [1, 2], "scene": [10, 20]}],
    }
    html_out = render_raster_picker(data, config, controls_sha256="c" * 64)
    assert "Raster control picker" in html_out
    assert "does not fit a transform" in html_out
    assert payload_note not in html_out
    assert "\\u003c/script\\u003e\\u003cimg src=x\\u003e\\u0026\\u2028\\u2029" in html_out
    assert html_out.count("</script>") == 2

    match = re.search(
        r'<script id="picker-data" type="application/json">(.*?)</script>', html_out, re.S
    )
    assert match is not None
    seed = json.loads(match.group(1))
    assert seed["width"] == 12
    assert seed["height"] == 8
    assert seed["image_sha256"] == hashlib.sha256(data).hexdigest()
    assert seed["controls_sha256"] == "c" * 64
    assert seed["image_url"].startswith("data:image/png;base64,")
    assert seed["config"]["scene"]["name"] == payload_note
