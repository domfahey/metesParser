"""Host-dependent GeoJSON replay failures are ``not_verified``, never tampering.

The recorded coordinate operation can build on a replay host yet fail or
silently differ there (a domain error, or an optional ``@grid`` that is not
installed so PROJ passes points through unchanged). That is reduced
verification of an intact package, not "artifact differs".
"""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from mp_review.delivery import DeliveryReplayIncomplete, load_delivery, replay_delivery

pyproj = pytest.importorskip("pyproj")

_TESTS = Path(__file__).parent
_GRID_PIPELINE = (
    "proj=pipeline step inv proj=webmerc ellps=WGS84 "
    "step proj=hgridshift grids=@us_noaa_conus.tif step proj=webmerc ellps=WGS84"
)


def _coords():
    spec = importlib.util.spec_from_file_location(
        "_host_coords", _TESTS / "test_delivery_replay_coordinates.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rewrite(directory, change):
    path = directory / "drawing.geojson"
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")))
    manifest_path = directory / "delivery-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"]["drawing.geojson"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))


def test_projection_failure_during_replay_render_is_not_verified(tmp_path, monkeypatch):
    import mp_review.webmap_projection as projections

    coords = _coords()
    bundle, revision, directory = coords._publish(tmp_path)
    real = projections.projection_from_pipeline

    def failing(*args, **kwargs):
        projection = real(*args, **kwargs)

        def forward(x, y):
            raise pyproj.exceptions.ProjError("grid lookup failed on this host")

        return projection.__class__(
            source_crs_wkt=projection.source_crs_wkt,
            pipeline=projection.pipeline,
            accuracy=projection.accuracy,
            versions=projection.versions,
            _forward=forward,
            _geographic=projection._geographic,
        )

    monkeypatch.setattr(projections, "projection_from_pipeline", failing)
    replay = replay_delivery(bundle, revision, directory)
    assert replay.geojson_coordinates == "not_verified"
    assert replay.findings and "not re-verified" in replay.findings[0]
    with pytest.raises(DeliveryReplayIncomplete):
        load_delivery(bundle, revision, directory)
    assert load_delivery(bundle, revision, directory, allow_unverified_geojson=True)


def _grid_available() -> bool:
    from pyproj.crs import CoordinateOperation

    pyproj.network.set_network_enabled(False)
    return any(g.available for g in CoordinateOperation.from_string(_GRID_PIPELINE).grids)


def test_missing_optional_grid_mismatch_is_not_verified(tmp_path):
    if _grid_available():
        pytest.skip("us_noaa_conus.tif is installed on this host")
    coords = _coords()
    bundle, revision, directory = coords._publish(tmp_path)

    def published_with_grid(data):
        # A publishing host that had the grid recorded this operation and the
        # grid-shifted coordinates; this host passes points through unchanged.
        data["metesparser"]["projection"]["pipeline"] = _GRID_PIPELINE
        for feature in data["features"]:
            feature["geometry"]["coordinates"] = coords._shift(feature["geometry"]["coordinates"])

    _rewrite(directory, published_with_grid)
    replay = replay_delivery(bundle, revision, directory)
    assert replay.geojson_coordinates == "not_verified"
    assert replay.findings


def test_usable_operation_mismatch_is_still_reported_as_differing(tmp_path):
    coords = _coords()
    bundle, revision, directory = coords._publish(tmp_path)

    def moved(data):
        for feature in data["features"]:
            feature["geometry"]["coordinates"] = coords._shift(feature["geometry"]["coordinates"])

    _rewrite(directory, moved)
    with pytest.raises(ValueError, match="differs from fresh replay"):
        replay_delivery(bundle, revision, directory)
