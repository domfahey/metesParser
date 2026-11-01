"""Legacy EXIF-rotated rasters are omitted consistently by every offline renderer."""

import base64
import hashlib
import html
import json
import sys
from io import BytesIO
from pathlib import Path

from mp_models.dashboard import DashboardBundle
from mp_models.raster import RASTER_ORIENTATION_MESSAGE
from mp_models.webmap import StandaloneWebMapInput, WebMapRequest
from mp_review.dashboard import dashboard_file
from mp_review.online_map import render_map_file
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))


def _orientation_6_jpeg() -> bytes:
    exif = Image.Exif()
    exif[274] = 6
    stream = BytesIO()
    Image.new("RGB", (2, 2), "white").save(stream, format="JPEG", exif=exif.tobytes())
    return stream.getvalue()


def _rotate(layer: dict, source: dict) -> None:
    data = _orientation_6_jpeg()
    digest = hashlib.sha256(data).hexdigest()
    layer.update(mime_type="image/jpeg", sha256=digest, data_base64=base64.b64encode(data).decode())
    source.update(sha256=digest, filename="scan.jpg")
    if source.get("data_base64") is not None:
        source["data_base64"] = layer["data_base64"]


def test_dashboard_omits_legacy_oriented_raster(tmp_path):
    from test_dashboard_plot_stages import raster_bundle

    value, _ = raster_bundle()
    _rotate(value["raster_layers"][0], value["map_sources"][-1])
    DashboardBundle.model_validate(value)
    path = tmp_path / "input.json"
    path.write_text(json.dumps(value))
    result = dashboard_file(path, tmp_path / "delivery")
    assert result["status"] == "needs_review", result
    page = (tmp_path / "delivery/dashboard.html").read_text()
    assert "raster_orientation" in page
    assert html.escape(RASTER_ORIENTATION_MESSAGE) in page
    assert "data:image/jpeg;base64," not in page


def test_render_map_omits_legacy_oriented_raster(tmp_path):
    from mp_models.plot import MapSource, PlotScene
    from mp_review.raster_registration import image_layer, supplied_affine
    from test_render_map_file import source_input

    base = source_input()
    scene = PlotScene(id="grid", name="Supplied grid", kind="projected", crs="EPSG:3857", units="m")
    layer, source = image_layer(
        _png(),
        scene=scene,
        registration=supplied_affine((1, 0, 0, 0, -1, 0)),
        filename="scan.png",
    )
    layer_data, source_data = layer.model_dump(mode="json"), source.model_dump(mode="json")
    _rotate(layer_data, source_data)
    data = base.model_dump(mode="json")
    data["map_sources"] = [source_data]
    data["raster_layers"] = [layer_data]
    StandaloneWebMapInput.model_validate(data)
    assert MapSource.model_validate(source_data)
    source_file = tmp_path / "input.json"
    source_file.write_text(json.dumps(data))
    output = tmp_path / "map"
    result = render_map_file(source_file, output, online_map=WebMapRequest(scene_id="grid"))
    assert result["status"] == "needs_review", result
    assert all(e.get("code") != "invalid_online_map_input" for e in result["errors"])
    assert "raster_orientation" in (output / "web-map.json").read_text()
    evidence = (output / "map-evidence.html").read_text()
    assert "raster_orientation" in evidence
    assert html.escape(RASTER_ORIENTATION_MESSAGE) in evidence
    assert "data:image/jpeg;base64," not in evidence


def _png() -> bytes:
    stream = BytesIO()
    Image.new("RGB", (2, 2), "white").save(stream, format="PNG")
    return stream.getvalue()
