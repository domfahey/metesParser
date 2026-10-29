"""Independent projection controls and fail-closed geographic display policy."""

import builtins
import math
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest
from mp_models.plot import PlotScene
from mp_review.webmap_projection import WebMapUnavailable, build_web_map_projection

RADIUS = 6378137.0
LIMIT = math.pi * RADIUS


def scene(crs="EPSG:3857", units="m"):
    return PlotScene(id="grid", name="Grid", kind="projected", crs=crs, units=units, basis="grid")


@pytest.mark.parametrize(
    "unit,factor,proj_unit",
    [("m", 1.0, "m"), ("international_ft", 0.3048, "ft"), ("us_survey_ft", 1200 / 3937, "us-ft")],
)
def test_independent_ellipsoidal_mercator_controls(unit, factor, proj_unit):
    # Independent WGS84 ellipsoidal Mercator formula, then spherical web Mercator.
    projection = build_web_map_projection(
        scene(f"+proj=merc +datum=WGS84 +units={proj_unit} +type=crs", unit)
    )
    longitude, latitude = -73.25, 40.5
    phi = math.radians(latitude)
    eccentricity = math.sqrt((1 / 298.257223563) * (2 - 1 / 298.257223563))
    correction = (eccentricity / 2) * math.log(
        (1 + eccentricity * math.sin(phi)) / (1 - eccentricity * math.sin(phi))
    )
    native = (
        RADIUS * math.radians(longitude) / factor,
        RADIUS * (math.log(math.tan(math.pi / 4 + phi / 2)) - correction) / factor,
    )
    expected = (
        RADIUS * math.radians(longitude),
        RADIUS * math.log(math.tan(math.pi / 4 + math.radians(latitude) / 2)),
    )
    mercator = projection.to_mercator(native)
    assert mercator == pytest.approx(expected, abs=1e-7)
    assert projection.from_mercator(mercator) == pytest.approx((longitude, latitude), abs=1e-11)


def test_authority_axis_pipeline_and_public_xy_are_both_explicit():
    from pyproj import Transformer

    projection = build_web_map_projection(scene("EPSG:2193"))
    # NZTM false origin: easting 1,600,000; northing 10,000,000 at 173 E, 0 N.
    expected = (RADIUS * math.radians(173), 0.0)
    assert projection.to_mercator((1600000.0, 10000000.0)) == pytest.approx(expected, abs=1e-7)
    assert Transformer.from_pipeline(projection.pipeline).transform(
        10000000, 1600000
    ) == pytest.approx(expected, abs=1e-7)
    assert "axisswap" in projection.pipeline


def test_metadata_is_immutable_and_records_database_identity():
    import pyproj

    projection = build_web_map_projection(scene())
    assert projection.source_crs_wkt.startswith("PROJCRS[")
    assert dict(projection.versions)["pyproj"] == pyproj.__version__
    assert len(dict(projection.versions)["proj_database_sha256"]) == 64
    assert not pyproj.network.is_network_enabled()
    with pytest.raises(FrozenInstanceError):
        projection.pipeline = "changed"


@pytest.mark.parametrize(
    "point", [(float("nan"), 0), (0, float("inf")), (LIMIT + 1, 0), (0, LIMIT + 1), (True, 0)]
)
def test_rejects_nonfinite_and_outside_mercator_domain(point):
    projection = build_web_map_projection(scene())
    for method in (projection.to_mercator, projection.from_mercator):
        with pytest.raises(WebMapUnavailable) as error:
            method(point)
        assert error.value.code == "projection_domain"


def test_no_silent_longitude_wrapping():
    projection = build_web_map_projection(scene("+proj=eqc +datum=WGS84 +units=m +type=crs"))
    with pytest.raises(WebMapUnavailable, match="domain"):
        projection.to_mercator((2 * LIMIT, 0))


def test_rejects_latitudes_beyond_web_mercator_limit():
    projection = build_web_map_projection(scene("+proj=eqc +datum=WGS84 +units=m +type=crs"))
    with pytest.raises(WebMapUnavailable) as error:
        projection.to_mercator((0, RADIUS * math.radians(86)))
    assert error.value.code == "projection_domain"


def test_local_scene_is_explicitly_unavailable():
    local = PlotScene(id="local", name="Local", kind="local", units="unknown_ft")
    with pytest.raises(WebMapUnavailable) as error:
        build_web_map_projection(local)
    assert error.value.code == "missing_georeference"


@pytest.mark.parametrize(
    "invalid", [scene(units="international_ft"), scene("EPSG:4326"), scene("invalid-secret-value")]
)
def test_invalid_scene_does_not_leak_source_values(invalid):
    with pytest.raises(WebMapUnavailable) as error:
        build_web_map_projection(invalid)
    assert error.value.code == "invalid_scene"
    assert "invalid-secret-value" not in str(error.value)


def test_missing_pyproj_is_typed_without_affecting_module_import(monkeypatch):
    original = builtins.__import__

    def importing(name, *args, **kwargs):
        if name == "pyproj" or name.startswith("pyproj."):
            raise ImportError("missing")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", importing)
    with pytest.raises(WebMapUnavailable) as error:
        build_web_map_projection(scene())
    assert error.value.code == "dependency_unavailable"


def test_missing_best_grid_cannot_fall_back(monkeypatch):
    import pyproj.transformer

    def unavailable(*args, **kwargs):
        assert kwargs["allow_ballpark"] is False
        assert kwargs["always_xy"] is False
        return SimpleNamespace(best_available=False, transformers=[object()])

    monkeypatch.setattr(pyproj.transformer, "TransformerGroup", unavailable)
    with pytest.raises(WebMapUnavailable) as error:
        build_web_map_projection(scene())
    assert error.value.code == "missing_grid"


def _gdal_control_sample(projection, source_center, target_center, *, pipeline=None):
    """Optional full-extra probe; ordinary projection tests remain pyproj-only."""
    rasterio = pytest.importorskip("rasterio")
    np = pytest.importorskip("numpy")
    from rasterio.transform import Affine
    from rasterio.warp import Resampling, reproject

    source = np.array([[1, 2, 3], [4, 100, 6], [7, 8, 9]], dtype="float64")
    destination = np.zeros((1, 1), dtype="float64")
    # The supplied center is pixel (1,1); GDAL affine origins are outer edges.
    source_affine = Affine(1, 0, source_center[0] - 1.5, 0, -1, source_center[1] + 1.5)
    target_affine = Affine(0.1, 0, target_center[0] - 0.05, 0, -0.1, target_center[1] + 0.05)
    with rasterio.Env(PROJ_NETWORK="OFF", CHECK_WITH_INVERT_PROJ="YES"):
        reproject(
            source,
            destination,
            src_transform=source_affine,
            src_crs=projection.source_crs_wkt,
            dst_transform=target_affine,
            dst_crs="EPSG:3857",
            resampling=Resampling.bilinear,
            tolerance=0,
            COORDINATE_OPERATION=projection.pipeline if pipeline is None else pipeline,
            ALLOW_BALLPARK="NO",
            ONLY_BEST="YES",
        )
    return destination[0, 0]


@pytest.mark.parametrize("crs", ["EPSG:3857", "EPSG:2193"])
def test_gdal_exact_authority_operation_at_center_and_interior_checkpoint(crs):
    projection = build_web_map_projection(scene(crs))
    if crs == "EPSG:3857":
        source_center = (1000.0, 2000.0)
        target_center = source_center
        checkpoint = (1000.25, 2000.25)
    else:
        source_center = (1600000.0, 10000000.0)
        target_center = (RADIUS * math.radians(173), 0.0)
        # Independent derivative of NZTM at its false origin, using GRS80.
        # The neglected cubic terms are below 1e-8 m for these 0.25 m offsets.
        flattening = 1 / 298.257222101
        eccentricity_squared = flattening * (2 - flattening)
        checkpoint = (
            target_center[0] + 0.25 / 0.9996,
            0.25 / ((1 - eccentricity_squared) * 0.9996),
        )
    assert _gdal_control_sample(projection, source_center, target_center) == pytest.approx(
        100.0, abs=1e-5
    )
    # Source pixel center (u=1.25,v=0.75) interpolates four asymmetric values.
    expected = 2 * 0.1875 + 3 * 0.0625 + 100 * 0.5625 + 6 * 0.1875
    assert _gdal_control_sample(projection, source_center, checkpoint) == pytest.approx(
        expected, abs=1e-5
    )


def test_gdal_coordinate_operation_keyword_is_enforced():
    projection = build_web_map_projection(scene())
    # An enforced 100 m shift puts this target outside the source raster.
    # A silently ignored COORDINATE_OPERATION would instead return 100.
    assert (
        _gdal_control_sample(
            projection,
            (1000.0, 2000.0),
            (1000.0, 2000.0),
            pipeline="proj=pipeline step proj=affine xoff=100",
        )
        == 0.0
    )


@pytest.mark.parametrize(
    "pipeline",
    [
        "proj=not_a_projection",
        "proj=pipeline step proj=hgridshift grids=metesparser_missing_grid.tif "
        "step proj=webmerc ellps=WGS84",
    ],
)
def test_gdal_invalid_or_missing_grid_operation_cannot_fall_back(pipeline):
    projection = build_web_map_projection(scene())
    with pytest.raises(Exception, match="Cannot instantiate pipeline"):
        _gdal_control_sample(projection, (1000.0, 2000.0), (1000.0, 2000.0), pipeline=pipeline)
