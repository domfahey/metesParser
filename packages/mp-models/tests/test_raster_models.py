import base64
import hashlib
import io
import json
from pathlib import Path

import pytest
from mp_models.dashboard import DashboardBundle
from mp_models.plot import MapSource
from mp_models.raster import (
    RasterControl,
    RasterLayer,
    RasterRegistration,
    image_orientation,
)
from pydantic import ValidationError

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def layer():
    return {
        "id": "scan",
        "label": "scan",
        "source_id": "map",
        "scene_id": "scene",
        "mime_type": "image/png",
        "width": 1,
        "height": 1,
        "sha256": hashlib.sha256(PNG).hexdigest(),
        "data_base64": base64.b64encode(PNG).decode(),
        "registration": {"matrix": [1, 0, 0, 0, 1, 0], "method": "supplied_affine"},
    }


def test_map_original_bytes_and_angular_pixel_units():
    for unit in ("degree", "pixel"):
        source = MapSource(
            id="map",
            label="x",
            sha256=hashlib.sha256(PNG).hexdigest(),
            data_base64=base64.b64encode(PNG).decode(),
            native_units=unit,
        )
        assert source.data_base64
    with pytest.raises(ValidationError, match="hash"):
        MapSource(id="map", label="x", sha256="0" * 64, data_base64=base64.b64encode(PNG).decode())


def raster_bundle():
    path = Path(__file__).parents[2] / "mp-review/tests/fixtures/dashboard-absolute.json"
    data = json.loads(path.read_text())
    data.update(
        schema_version="1.1",
        scenes=[
            {"id": "scene", "name": "map", "kind": "projected", "crs": "EPSG:3857", "units": "m"}
        ],
        map_sources=[{"id": "map", "label": "scan", "sha256": hashlib.sha256(PNG).hexdigest()}],
        raster_layers=[layer()],
        plot_view={"visible_layer_ids": ["scan"]},
    )
    return data


def test_raster_bundle_references_view_and_v1_guard():
    data = raster_bundle()
    bundle = DashboardBundle.model_validate(data)
    assert len(bundle.raster_layers) == 1
    data["raster_layers"][0]["scene_id"] = "missing"
    with pytest.raises(ValidationError, match="scene"):
        DashboardBundle.model_validate(data)


@pytest.mark.parametrize("retain_source_bytes", [False, True])
def test_raster_bundle_rejects_a_source_for_different_asset_bytes(retain_source_bytes):
    data = raster_bundle()
    other_asset = b"OTHER ASSET"
    data["map_sources"][0]["sha256"] = hashlib.sha256(other_asset).hexdigest()
    if retain_source_bytes:
        data["map_sources"][0]["data_base64"] = base64.b64encode(other_asset).decode()
    with pytest.raises(ValidationError, match="Raster.*source"):
        DashboardBundle.model_validate(data)


@pytest.mark.parametrize("retain_source_bytes", [False, True])
def test_raster_bundle_accepts_its_matching_source_with_optional_bytes(retain_source_bytes):
    data = raster_bundle()
    if retain_source_bytes:
        data["map_sources"][0]["data_base64"] = base64.b64encode(PNG).decode()
    bundle = DashboardBundle.model_validate(data)
    assert bundle.map_sources[0].sha256 == bundle.raster_layers[0].sha256


def test_forged_dimensions_mime_and_residuals_fail_at_model_boundary():
    for update in ({"width": 2}, {"mime_type": "image/jpeg"}):
        with pytest.raises(ValidationError, match="dimensions|MIME"):
            RasterLayer.model_validate(layer() | update)
    with pytest.raises(ValidationError, match="residual"):
        RasterRegistration(
            matrix=(1, 0, 0, 0, 1, 0),
            method="supplied_affine",
            controls=(RasterControl(id="a", pixel=(0, 0), scene=(2, 0)),),
            residuals=(),
            fit_rms=0,
        )


def _jpeg_bytes(orientation: int | None) -> bytes:
    """Build a real JPEG with PIL, optionally carrying an EXIF Orientation tag."""
    Image = pytest.importorskip("PIL.Image")
    buffer = io.BytesIO()
    image = Image.new("RGB", (4, 3), (200, 10, 10))
    if orientation is None:
        image.save(buffer, "JPEG")
    else:
        exif = Image.Exif()
        exif[0x0112] = orientation
        image.save(buffer, "JPEG", exif=exif.tobytes())
    return buffer.getvalue()


def _insert_after_soi(jpeg: bytes, filler: bytes) -> bytes:
    assert jpeg.startswith(b"\xff\xd8")
    return jpeg[:2] + filler + jpeg[2:]


def test_image_orientation_reads_exif_orientation_from_jpeg():
    assert image_orientation(_jpeg_bytes(6)) == 6


@pytest.mark.parametrize("fill_count", [1, 3])
def test_image_orientation_skips_jpeg_fill_bytes_before_exif(fill_count):
    data = _insert_after_soi(_jpeg_bytes(6), b"\xff" * fill_count)
    assert image_orientation(data) == 6


def test_image_orientation_skips_fill_bytes_for_upright_jpeg():
    data = _insert_after_soi(_jpeg_bytes(1), b"\xff\xff")
    assert image_orientation(data) == 1


def test_image_orientation_skips_standalone_markers_before_exif():
    # TEM (0x01) and RST0 (0xD0) carry no length field and must not be read as one.
    data = _insert_after_soi(_jpeg_bytes(8), b"\xff\x01\xff\xd0")
    assert image_orientation(data) == 8


def test_image_orientation_returns_none_for_jpeg_without_exif():
    assert image_orientation(_jpeg_bytes(None)) is None
    assert image_orientation(_insert_after_soi(_jpeg_bytes(None), b"\xff\xff")) is None


@pytest.mark.parametrize("truncate_at", [2, 3, 5, 9, 11])
def test_image_orientation_never_reads_past_truncated_jpeg(truncate_at):
    data = _insert_after_soi(_jpeg_bytes(6), b"\xff\xff")
    assert image_orientation(data[:truncate_at]) in (None, 6)
