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


def test_raster_registration_matrix_controls_least_squares_and_rms_invariants():
    # Singular matrix rejected.
    with pytest.raises(ValidationError, match="singular or ill-conditioned"):
        RasterRegistration(matrix=(1, 2, 0, 2, 4, 0), method="supplied_affine")

    # Duplicate control IDs rejected.
    dup = RasterControl(id="c1", pixel=(0, 0), scene=(0, 0))
    with pytest.raises(ValidationError, match="must be unique"):
        RasterRegistration(matrix=(1, 0, 0, 0, 1, 0), method="supplied_affine", controls=(dup, dup))

    # Least squares requires >= 3 distinct non-collinear fit controls.
    with pytest.raises(ValidationError, match="three distinct affine fit controls"):
        RasterRegistration(
            matrix=(1, 0, 0, 0, 1, 0),
            method="affine_least_squares",
            controls=(
                RasterControl(id="c1", pixel=(0, 0), scene=(0, 0)),
                RasterControl(id="c2", pixel=(1, 0), scene=(1, 0)),
            ),
        )
    with pytest.raises(ValidationError, match="collinear or ill-conditioned"):
        RasterRegistration(
            matrix=(1, 0, 0, 0, 1, 0),
            method="affine_least_squares",
            controls=(
                RasterControl(id="c1", pixel=(0, 0), scene=(0, 0)),
                RasterControl(id="c2", pixel=(1, 1), scene=(1, 1)),
                RasterControl(id="c3", pixel=(2, 2), scene=(2, 2)),
            ),
        )
    # Overflowing pixel coordinates trigger nonfinite raster control arithmetic.
    with pytest.raises(ValidationError, match="Nonfinite raster control arithmetic"):
        RasterRegistration(
            matrix=(1, 0, 0, 0, 1, 0),
            method="affine_least_squares",
            controls=(
                RasterControl(id="c1", pixel=(0, 0), scene=(0, 0)),
                RasterControl(id="c2", pixel=(1e200, 0), scene=(1e200, 0)),
                RasterControl(id="c3", pixel=(0, 1e200), scene=(0, 1e200)),
            ),
        )

    # Exact least squares fit with checkpoint computes fit_rms & checkpoint_rms.
    fit_controls = (
        RasterControl(id="f1", pixel=(0, 0), scene=(10, 20), role="fit"),
        RasterControl(id="f2", pixel=(10, 0), scene=(30, 20), role="fit"),
        RasterControl(id="f3", pixel=(0, 10), scene=(10, 50), role="fit"),
        RasterControl(id="chk", pixel=(10, 10), scene=(33, 54), role="checkpoint"),
    )
    reg = RasterRegistration(
        matrix=(2, 0, 10, 0, 3, 20),
        method="affine_least_squares",
        controls=fit_controls,
    )
    assert reg.fit_rms == pytest.approx(0.0)
    assert reg.checkpoint_rms == pytest.approx(5.0)

    # Non-least-squares matrix rejected.
    with pytest.raises(ValidationError, match="not the least squares solution"):
        RasterRegistration(
            matrix=(2.5, 0, 10, 0, 3, 20),
            method="affine_least_squares",
            controls=fit_controls,
        )

    # Explicit mismatched fit_rms rejected even when residuals match.
    with pytest.raises(ValidationError, match="RMS does not match"):
        RasterRegistration(
            matrix=(2, 0, 10, 0, 3, 20),
            method="affine_least_squares",
            controls=fit_controls,
            fit_rms=1.0,
        )


def test_raster_layer_content_guards_and_image_header_formats():
    from mp_models.raster import image_header

    with pytest.raises(ValidationError, match="valid base64"):
        RasterLayer.model_validate(layer() | {"data_base64": "not base64!!!"})
    with pytest.raises(ValidationError, match="hash/size mismatch"):
        RasterLayer.model_validate(layer() | {"sha256": "0" * 64})
    with pytest.raises(ValidationError, match="40 million pixels"):
        RasterLayer.model_validate(layer() | {"width": 10000, "height": 5000})

    # JPEG header parsing: valid SOF0 preceded by fill bytes, standalone marker, and APP0 segment.
    sof0 = (
        b"\xff\xc0"
        + (11).to_bytes(2, "big")
        + b"\x08"
        + (120).to_bytes(2, "big")
        + (240).to_bytes(2, "big")
        + b"\x01\x01\x11\x00"
    )
    app0 = b"\xff\xe0" + (4).to_bytes(2, "big") + b"\x00\x00"
    jpeg = b"\xff\xd8\xff\xff\x01\xff\xd0" + app0 + sof0 + b"\xff\xd9"
    assert image_header(jpeg) == ("image/jpeg", 240, 120)

    # Malformed JPEG break conditions (non-0xFF, trailing 0xFF, short length, truncated segment).
    for bad_jpeg in (
        b"\xff\xd8\x00\x00\x00\x00",
        b"\xff\xd8\xff\xff\xff\xff",
        b"\xff\xd8\xff\xe0\x00",
        b"\xff\xd8\xff\xe0\x00\x01\x00\x00",
        b"\xff\xd8\xff\xe0\x00\x20\x00\x00",
    ):
        with pytest.raises(ValueError, match="Unsupported or malformed"):
            image_header(bad_jpeg)

    # WebP VP8X, VP8 (lossy), and VP8L (lossless) headers.
    vp8x = (
        b"RIFF"
        + b"\x00" * 4
        + b"WEBPVP8X"
        + b"\x00" * 8
        + (319).to_bytes(3, "little")
        + (239).to_bytes(3, "little")
    )
    assert image_header(vp8x) == ("image/webp", 320, 240)

    vp8 = (
        b"RIFF"
        + b"\x00" * 4
        + b"WEBPVP8 "
        + b"\x00" * 7
        + b"\x9d\x01\x2a"
        + (640).to_bytes(2, "little")
        + (480).to_bytes(2, "little")
    )
    assert image_header(vp8) == ("image/webp", 640, 480)

    bits = (199 & 0x3FFF) | ((99 & 0x3FFF) << 14)
    vp8l = (
        b"RIFF"
        + b"\x00" * 4
        + b"WEBPVP8L"
        + b"\x00" * 4
        + b"\x2f"
        + bits.to_bytes(4, "little")
        + b"\x00" * 5
    )
    assert image_header(vp8l) == ("image/webp", 200, 100)


def _make_tiff_exif(orientation: int | None, *, big_endian: bool = False) -> bytes:
    order = "big" if big_endian else "little"
    header = (b"MM" if big_endian else b"II") + (42).to_bytes(2, order) + (8).to_bytes(4, order)
    if orientation is None:
        return header + (1).to_bytes(2, order) + (0x0100).to_bytes(2, order) + b"\x00" * 10
    entry = (
        (0x0112).to_bytes(2, order)
        + (3).to_bytes(2, order)
        + (1).to_bytes(4, order)
        + orientation.to_bytes(2, order)
        + b"\x00\x00"
    )
    return header + (1).to_bytes(2, order) + entry


def test_tiff_png_and_webp_exif_orientation_parsing():
    ihdr_chunk = (13).to_bytes(4, "big") + b"IHDR" + b"\x00" * 13 + b"\x00\x00\x00\x00"
    idat_chunk = (0).to_bytes(4, "big") + b"IDAT" + b"\x00\x00\x00\x00"

    def _png_with_exif(payload: bytes) -> bytes:
        chunk = len(payload).to_bytes(4, "big") + b"eXIf" + payload + b"\x00\x00\x00\x00"
        return b"\x89PNG\r\n\x1a\n" + ihdr_chunk + chunk + idat_chunk

    # TIFF edge cases via PNG eXIf chunk: too short, bad magic, bad TIFF version,
    # IFD out of bounds, truncated entry, missing orientation tag, big-endian MM.
    assert image_orientation(_png_with_exif(b"short")) is None
    assert image_orientation(_png_with_exif(b"XX\x2a\x00\x08\x00\x00\x00")) is None
    assert image_orientation(_png_with_exif(b"II\x2b\x00\x08\x00\x00\x00")) is None
    assert image_orientation(_png_with_exif(b"II\x2a\x00\x99\x00\x00\x00")) is None
    assert image_orientation(_png_with_exif(b"II\x2a\x00\x08\x00\x00\x00\x01\x00\x12\x01")) is None
    assert image_orientation(_png_with_exif(_make_tiff_exif(None))) is None
    assert image_orientation(_png_with_exif(_make_tiff_exif(3, big_endian=True))) == 3

    # JPEG with malformed segment length < 2 breaks safely.
    assert image_orientation(b"\xff\xd8\xff\xe1\x00\x01\x00\x00") is None

    # PNG with eXIf chunk before IDAT vs IDAT before any eXIf.
    tiff = _make_tiff_exif(6)
    png_no_exif = b"\x89PNG\r\n\x1a\n" + ihdr_chunk + idat_chunk
    assert image_orientation(_png_with_exif(tiff)) == 6
    assert image_orientation(png_no_exif) is None

    # WebP with preceding odd-length chunk and EXIF chunk (with and without Exif\0\0 header).
    odd_chunk = b"JUNK" + (3).to_bytes(4, "little") + b"abc\x00"
    exif_payload = b"Exif\0\0" + _make_tiff_exif(8)
    webp_with_prefix = (
        b"RIFF\x00\x00\x00\x00WEBP"
        + odd_chunk
        + b"EXIF"
        + len(exif_payload).to_bytes(4, "little")
        + exif_payload
    )
    webp_raw_tiff = b"RIFF\x00\x00\x00\x00WEBP" + b"EXIF" + len(tiff).to_bytes(4, "little") + tiff
    webp_no_exif = b"RIFF\x00\x00\x00\x00WEBP" + odd_chunk
    assert image_orientation(webp_with_prefix) == 8
    assert image_orientation(webp_raw_tiff) == 6
    assert image_orientation(webp_no_exif) is None
