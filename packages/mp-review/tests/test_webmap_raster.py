"""Independent pixel-center, alpha, and nonlinear raster-warp controls."""

import builtins
import hashlib
import math
from io import BytesIO

import numpy as np
import pytest
from mp_models.plot import PlotScene
from mp_models.raster import RasterControl
from mp_models.webmap import WebMapOptions
from mp_review.raster_registration import image_layer, supplied_affine
from mp_review.webmap_projection import WebMapUnavailable, build_web_map_projection
from mp_review.webmap_raster import prepare_web_map_raster
from PIL import Image


def scene(crs="EPSG:3857"):
    return PlotScene(id="grid", name="Grid", kind="projected", crs=crs, units="m", basis="grid")


def layer_for(pixels, matrix=(1, 0, 1000, 0, -1, 2000), *, native=None, controls=()):
    stream = BytesIO()
    Image.fromarray(np.asarray(pixels, dtype="uint8")).save(stream, format="PNG")
    layer, _ = image_layer(
        stream.getvalue(),
        scene=native or scene(),
        registration=supplied_affine(matrix, controls),
        filename="synthetic.png",
    )
    return layer


def prepare(layer, native=None, **options):
    native = native or scene()
    return prepare_web_map_raster(
        layer, native, projection=build_web_map_projection(native), options=WebMapOptions(**options)
    )


def decoded(result):
    return np.asarray(Image.open(BytesIO(result.data)))


def test_identity_preserves_asymmetric_pixels_half_pixel_edges_and_provenance():
    pixels = np.array(
        [
            [[255, 0, 0, 255], [0, 255, 0, 255], [0, 0, 255, 255]],
            [[255, 255, 0, 255], [0, 0, 0, 255], [255, 0, 255, 255]],
        ],
        dtype="uint8",
    )
    controls = (RasterControl(id="check", pixel=(1, 1), scene=(1001.1, 1998.9), role="checkpoint"),)
    layer = layer_for(pixels, controls=controls).model_copy(update={"id": "raster:colon"})
    before = layer.model_dump(mode="json")
    result = prepare(layer, raster_pixel_size_m=1)
    assert decoded(result).tolist() == pixels.tolist()
    assert result.record.grid_affine == (1, 0, 999.5, 0, -1, 2000.5)
    assert (result.record.width, result.record.height) == (3, 2)
    assert result.record.path.startswith("web-map-assets/") and ":" not in result.record.path
    assert result.record.sha256 == hashlib.sha256(result.data).hexdigest()
    assert result.record.checkpoint_rms == pytest.approx(math.sqrt(0.02))
    assert result.record.registration_status == "approximate"
    assert layer.model_dump(mode="json") == before
    assert prepare(layer, raster_pixel_size_m=1) == result


def test_rotated_skew_grid_retains_corner_colors_and_transparent_exterior():
    pixels = np.zeros((7, 7, 4), dtype="uint8")
    pixels[:3, :3] = [255, 0, 0, 255]
    pixels[:3, 4:] = [0, 255, 0, 255]
    pixels[4:, :3] = [0, 0, 255, 255]
    pixels[4:, 4:] = [255, 255, 0, 255]
    matrix = (2, 0.5, 1000, 0.5, -2, 2000)
    result = prepare(layer_for(pixels, matrix), raster_pixel_size_m=0.5)
    image = decoded(result)
    a, b, c, d, e, f = result.record.grid_affine
    for u, v, color in [
        (1, 1, [255, 0, 0]),
        (5, 1, [0, 255, 0]),
        (1, 5, [0, 0, 255]),
        (5, 5, [255, 255, 0]),
    ]:
        x, y = matrix[0] * u + matrix[1] * v + matrix[2], matrix[3] * u + matrix[4] * v + matrix[5]
        row, col = int((y - f) / e), int((x - c) / a)
        assert image[row, col, :3].tolist() == color
        assert image[row, col, 3] == 255
    assert image[0, 0, 3] == 0
    assert np.all(image[image[:, :, 3] == 0, :3] == 0)


def test_premultiplied_alpha_does_not_blend_in_hidden_black_or_color():
    pixels = np.full((3, 3, 4), [0, 0, 0, 0], dtype="uint8")
    pixels[:, 1] = [255, 255, 255, 255]
    pixels[:, 2] = [255, 0, 0, 0]
    image = decoded(prepare(layer_for(pixels), raster_pixel_size_m=0.25))
    partial = (image[:, :, 3] > 0) & (image[:, :, 3] < 255)
    assert np.any(partial)
    assert np.all(image[partial, :3] == 255)
    assert np.all(image[image[:, :, 3] == 0, :3] == 0)


def test_nonlinear_warp_interior_defeats_four_corner_stretch():
    # Color encodes source row; affine spans 40 degrees of latitude in Mercator.
    radius = 6378137.0
    e2 = (1 / 298.257223563) * (2 - 1 / 298.257223563)

    def native_y(latitude):
        # Independent meridian-distance series for ellipsoidal equidistant cylindrical.
        phi = math.radians(latitude)
        return radius * (
            (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256) * phi
            - (3 * e2 / 8 + 3 * e2**2 / 32 + 45 * e2**3 / 1024) * math.sin(2 * phi)
            + (15 * e2**2 / 256 + 45 * e2**3 / 1024) * math.sin(4 * phi)
            - (35 * e2**3 / 3072) * math.sin(6 * phi)
        )

    native = scene("+proj=eqc +datum=WGS84 +units=m +type=crs")
    top, bottom = native_y(65), native_y(25)
    step = (bottom - top) / 99
    pixels = np.zeros((100, 5, 4), dtype="uint8")
    pixels[:, :, 0] = np.arange(100, dtype="uint8")[:, None] * 2
    pixels[:, :, 3] = 255
    result = prepare(
        layer_for(pixels, (10000, 0, 0, 0, step, top), native=native),
        native,
        raster_pixel_size_m=20000,
    )
    image = decoded(result)
    a, _, c, _, e, f = result.record.grid_affine
    for latitude in (33, 47, 59):
        web_y = radius * math.log(math.tan(math.pi / 4 + math.radians(latitude) / 2))
        row = int((web_y - f) / e)
        col = int((20000 - c) / a)
        actual_y = f + (row + 0.5) * e
        actual_lat = math.degrees(2 * math.atan(math.exp(actual_y / radius)) - math.pi / 2)
        expected = (native_y(actual_lat) - top) / step * 2
        assert float(image[row, col, 0]) == pytest.approx(expected, abs=1.1)
        if latitude == 47:
            top_web = radius * math.log(math.tan(math.pi / 4 + math.radians(65) / 2))
            bottom_web = radius * math.log(math.tan(math.pi / 4 + math.radians(25) / 2))
            four_corner_row = (actual_y - top_web) / (bottom_web - top_web) * 99
            assert abs(four_corner_row * 2 - expected) > 5


@pytest.mark.parametrize("options", [{"max_raster_dimension": 2}, {"max_raster_pixels": 3}])
def test_output_budget_is_reported_without_silent_coarsening(options):
    layer = layer_for(np.full((3, 3, 4), 255, dtype="uint8"))
    with pytest.raises(WebMapUnavailable) as error:
        prepare(layer, raster_pixel_size_m=1, **options)
    assert error.value.code == "raster_limit"


def test_domain_and_wrong_projection_are_rejected():
    layer = layer_for(
        np.full((3, 3, 4), 255, dtype="uint8"), (1, 0, 0, 0, -1, math.pi * 6378137 + 100)
    )
    with pytest.raises(WebMapUnavailable) as error:
        prepare(layer, raster_pixel_size_m=1)
    assert error.value.code == "projection_domain"
    valid = layer_for(np.full((3, 3, 4), 255, dtype="uint8"))
    wrong = build_web_map_projection(scene("EPSG:2193"))
    with pytest.raises(ValueError, match="projection"):
        prepare_web_map_raster(valid, scene(), projection=wrong, options=WebMapOptions())


def test_tampered_raster_is_an_error_not_an_omission():
    layer = layer_for(np.full((3, 3, 4), 255, dtype="uint8"))
    with pytest.raises(ValueError):
        prepare(layer.model_copy(update={"width": 4}))


def test_missing_raster_dependency_is_typed(monkeypatch):
    layer = layer_for(np.full((3, 3, 4), 255, dtype="uint8"))
    original = builtins.__import__

    def importing(name, *args, **kwargs):
        if name == "rasterio" or name.startswith("rasterio."):
            raise ImportError("missing")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", importing)
    with pytest.raises(WebMapUnavailable) as error:
        prepare(layer)
    assert error.value.code == "dependency_unavailable"


def test_north_east_source_axes_warp_at_independent_nztm_origin():
    native = scene("EPSG:2193")
    pixels = np.full((5, 5, 4), 255, dtype="uint8")
    # Encode both row and column so an axis swap or vertical flip is visible.
    for row in range(5):
        for column in range(5):
            pixels[row, column, :3] = row * 30 + column * 10
    result = prepare(
        layer_for(pixels, (1, 0, 1599998, 0, -1, 10000002), native=native),
        native,
        raster_pixel_size_m=0.25,
    )
    image = decoded(result)
    a, _, c, _, e, f = result.record.grid_affine
    expected_x = 6378137 * math.radians(173)
    row, column = int(-f / e), int((expected_x - c) / a)
    web_x, web_y = c + (column + 0.5) * a, f + (row + 0.5) * e
    flattening = 1 / 298.257222101
    e2 = flattening * (2 - flattening)
    native_dx = (web_x - expected_x) * 0.9996
    native_dy = web_y * 0.9996 * (1 - e2)
    expected_color = (2 - native_dy) * 30 + (2 + native_dx) * 10
    assert image[row, column, 0] == pytest.approx(expected_color, abs=1)
    assert image[row, column, 3] == 255


def test_densified_bounds_include_curved_edge_beyond_four_corners():
    from mp_review.raster_registration import outer_corners, transform_pixel

    native = scene("EPSG:2193")
    layer = layer_for(
        np.full((11, 51, 4), 255, dtype="uint8"),
        (20000, 0, 1100000, 0, -10000, 5100000),
        native=native,
    )
    result = prepare(layer, native, raster_pixel_size_m=5000)
    projection = build_web_map_projection(native)
    corner_minimum = min(
        projection.to_mercator(point)[1]
        for point in outer_corners(layer.registration, layer.width, layer.height)
    )
    a, _, c, _, e, f = result.record.grid_affine
    minimum = f + result.record.height * e
    assert minimum < corner_minimum - 1000
    # Withheld boundary positions do not coincide with the 64 seed sections.
    for index in range(129):
        pixel = (-0.5 + 51 * (index + 0.371) / 130, 10.5)
        x, y = projection.to_mercator(transform_pixel(layer.registration, pixel))
        assert c <= x <= c + a * result.record.width
        assert minimum <= y <= f


def test_output_limit_is_checked_before_warp_allocation(monkeypatch):
    layer = layer_for(np.full((3, 3, 4), 255, dtype="uint8"))

    def unexpected(*args, **kwargs):
        raise AssertionError("Output allocation occurred before the budget check")

    monkeypatch.setattr(np, "zeros", unexpected)
    with pytest.raises(WebMapUnavailable) as error:
        prepare(layer, raster_pixel_size_m=1, max_raster_pixels=1)
    assert error.value.code == "raster_limit"


def test_unsupported_gdal_fails_explicitly(monkeypatch):
    import rasterio

    layer = layer_for(np.full((3, 3, 4), 255, dtype="uint8"))
    monkeypatch.setattr(rasterio, "__gdal_version__", "3.10.0")
    with pytest.raises(WebMapUnavailable) as error:
        prepare(layer)
    assert error.value.code == "operation_unavailable"
