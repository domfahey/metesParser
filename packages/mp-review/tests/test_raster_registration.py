import base64
import hashlib
from io import BytesIO

import pytest
from mp_models.plot import PlotScene
from mp_models.raster import RasterControl
from mp_review.raster_registration import fit_affine, image_layer, outer_corners, transform_pixel


def controls():
    return tuple(
        RasterControl(id=str(i), pixel=p, scene=q)
        for i, p, q in [
            ("a", (0, 0), (100, 200)),
            ("b", (10, 0), (100, 220)),
            ("c", (0, 10), (130, 200)),
        ]
    )


def test_rotated_affine_integer_pixel_centers_and_edges():
    registration = fit_affine(controls())
    assert registration.matrix == pytest.approx((0, 3, 100, 2, 0, 200))
    assert transform_pixel(registration, (4, 5)) == pytest.approx((115, 208))
    assert outer_corners(registration, 10, 20)[0] == pytest.approx((98.5, 199))
    assert outer_corners(registration, 10, 20)[2] == pytest.approx((158.5, 219))
    assert registration.checkpoint_rms is None
    assert registration.status == "approximate"


@pytest.mark.parametrize(
    "pairs",
    [
        controls()[:2],
        controls() + (controls()[0],),
        tuple(RasterControl(id=str(i), pixel=(i, i), scene=(i, i)) for i in range(3)),
    ],
)
def test_reject_insufficient_duplicate_collinear_controls(pairs):
    with pytest.raises(ValueError):
        fit_affine(pairs)


def test_residuals_and_independent_checkpoints():
    pairs = controls() + (
        RasterControl(id="d", pixel=(10, 10), scene=(131, 220)),
        RasterControl(id="check", pixel=(5, 5), scene=(116, 210), role="checkpoint"),
    )
    result = fit_affine(pairs)
    assert result.fit_rms == pytest.approx(0.25)
    assert result.checkpoint_rms == pytest.approx(0.75)
    assert [r.role for r in result.residuals] == ["fit"] * 4 + ["checkpoint"]


def test_image_content_hash_dimensions_and_no_deed_scaling():
    from PIL import Image

    stream = BytesIO()
    Image.new("RGB", (10, 20)).save(stream, format="PNG")
    data = stream.getvalue()
    scene = PlotScene(id="map", name="map", kind="projected", crs="EPSG:3857", units="m")
    layer, source = image_layer(
        data, scene=scene, registration=fit_affine(controls()), filename="scan.png"
    )
    assert (layer.width, layer.height) == (10, 20)
    assert layer.sha256 == hashlib.sha256(data).hexdigest()
    assert base64.b64decode(layer.data_base64) == data
    assert source.sha256 == layer.sha256
    with pytest.raises(ValueError):
        image_layer(
            b"not an image", scene=scene, registration=fit_affine(controls()), filename="fake.png"
        )


def test_supplied_singular_nonfinite_and_forged_raster_rejected():
    from mp_review.raster_registration import supplied_affine, validate_raster_layer
    from PIL import Image

    for matrix in [(1, 2, 0, 2, 4, 0), (1, 0, float("inf"), 0, 1, 0)]:
        with pytest.raises(ValueError):
            supplied_affine(matrix)
    stream = BytesIO()
    Image.new("RGB", (10, 20)).save(stream, format="PNG")
    scene = PlotScene(id="map", name="map", kind="projected", crs="EPSG:3857", units="m")
    layer, _ = image_layer(
        stream.getvalue(), scene=scene, registration=fit_affine(controls()), filename="image.png"
    )
    with pytest.raises(ValueError, match="dimensions"):
        validate_raster_layer(layer.model_copy(update={"width": 9}), scene)


def _oriented_image(fmt, orientation):
    from PIL import Image

    image = Image.new("RGB", (10, 20))
    exif = Image.Exif()
    exif[274] = orientation
    stream = BytesIO()
    image.save(stream, format=fmt, exif=exif.tobytes())
    return stream.getvalue()


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
@pytest.mark.parametrize("orientation", [2, 3, 6, 8])
def test_exif_oriented_raster_fails_closed(fmt, orientation):
    scene = PlotScene(id="map", name="map", kind="projected", crs="EPSG:3857", units="m")
    data = _oriented_image(fmt, orientation)
    with pytest.raises(ValueError, match="orientation"):
        image_layer(data, scene=scene, registration=fit_affine(controls()), filename="s.img")


def test_exif_orientation_one_is_accepted():
    scene = PlotScene(id="map", name="map", kind="projected", crs="EPSG:3857", units="m")
    layer, _ = image_layer(
        _oriented_image("JPEG", 1),
        scene=scene,
        registration=fit_affine(controls()),
        filename="s.jpg",
    )
    assert (layer.width, layer.height) == (10, 20)


def test_header_only_guard_rejects_oriented_raster_without_pillow():
    from mp_models.raster import image_orientation

    assert image_orientation(_oriented_image("JPEG", 6)) == 6
    assert image_orientation(_oriented_image("JPEG", 1)) == 1
    assert image_orientation(_oriented_image("PNG", 6)) == 6
    assert image_orientation(_oriented_image("WEBP", 6)) == 6


def _oriented_layer_payload(orientation=6):
    data = _oriented_image("JPEG", orientation)
    return {
        "id": "raster-old",
        "label": "old.jpg",
        "source_id": "map-old",
        "scene_id": "map",
        "mime_type": "image/jpeg",
        "width": 10,
        "height": 20,
        "sha256": hashlib.sha256(data).hexdigest(),
        "data_base64": base64.b64encode(data).decode(),
        "registration": fit_affine(controls()),
    }


def test_oriented_raster_model_still_loads_for_saved_artifacts():
    from mp_models.raster import RasterLayer

    layer = RasterLayer.model_validate(_oriented_layer_payload())
    assert (layer.width, layer.height) == (10, 20)


def test_dashboard_renderer_refuses_to_draw_oriented_raster():
    from mp_export.dashboard_html import _raster_svg
    from mp_models.raster import RasterLayer

    with pytest.raises(ValueError, match="orientation"):
        _raster_svg(RasterLayer.model_validate(_oriented_layer_payload()))


def test_oriented_saved_raster_is_reported_unsupported_when_validated_for_use():
    from mp_models.raster import RasterLayer
    from mp_review.raster_registration import validate_raster_layer

    scene = PlotScene(id="map", name="map", kind="projected", crs="EPSG:3857", units="m")
    layer = RasterLayer.model_validate(_oriented_layer_payload())
    with pytest.raises(ValueError, match="orientation"):
        validate_raster_layer(layer, scene)
