"""Replay re-renders GeoJSON from the recorded coordinate operation (PR #60 review 5).

Replay keeps trusting the recorded area-of-use omissions, but rebuilds the
projection from ``metesparser.projection.pipeline`` and compares the re-rendered
GeoJSON byte-for-byte. A host that cannot instantiate the recorded operation
falls back to the metadata check and reports reduced verification.
"""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from mp_review.delivery import (
    DeliveryReplayIncomplete,
    load_delivery,
    publish_delivery,
    replay_delivery,
)

pyproj = pytest.importorskip("pyproj")

_TESTS = Path(__file__).parent
GOLDEN = _TESTS / "fixtures/delivery-1-golden"


def _module(name):
    spec = importlib.util.spec_from_file_location(f"_coords_{name}", _TESTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _publish(tmp_path):
    bundle, revision, request = _module("test_delivery_store")._placed_case(tmp_path)
    result = publish_delivery(bundle, revision, request, tmp_path / "deliveries")
    assert result["status"] == "needs_review", result
    assert "drawing.geojson" in result["artifacts"]
    return bundle, revision, tmp_path / "deliveries" / request.id


def _rehash(directory, name):
    manifest_path = directory / "delivery-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"][name] = hashlib.sha256((directory / name).read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))


def _shift(value):
    if isinstance(value, list) and value and all(isinstance(v, float) for v in value):
        return [value[0] + 0.001, value[1] + 0.001]
    if isinstance(value, list):
        return [_shift(v) for v in value]
    return value


def test_replay_rejects_rehashed_moved_geojson_coordinates(tmp_path):
    bundle, revision, directory = _publish(tmp_path)
    path = directory / "drawing.geojson"
    data = json.loads(path.read_text())
    for feature in data["features"]:
        feature["geometry"]["coordinates"] = _shift(feature["geometry"]["coordinates"])
    path.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")))
    _rehash(directory, "drawing.geojson")
    with pytest.raises(ValueError, match="differs from fresh replay"):
        load_delivery(bundle, revision, directory)


def test_intact_replay_reports_reproduced_coordinates(tmp_path, monkeypatch):
    import mp_review.webmap_projection as module

    bundle, revision, directory = _publish(tmp_path)

    def selection(*args, **kwargs):
        raise AssertionError("replay must not re-run operation selection")

    monkeypatch.setattr(module, "build_web_map_projection", selection)
    replay = replay_delivery(bundle, revision, directory)
    assert replay.geojson_coordinates == "reproduced"
    assert replay.findings == ()


def test_host_without_recorded_operation_reports_reduced_verification(tmp_path, monkeypatch):
    bundle, revision, directory = _publish(tmp_path)

    def unavailable(*args, **kwargs):
        raise pyproj.exceptions.ProjError("File not found or invalid")

    monkeypatch.setattr(pyproj.Transformer, "from_pipeline", unavailable)
    replay = replay_delivery(bundle, revision, directory)
    assert replay.geojson_coordinates == "not_verified"
    assert replay.findings and "not re-verified" in replay.findings[0]
    # Metadata/layer binding still applies when coordinates cannot be re-rendered.
    path = directory / "drawing.geojson"
    data = json.loads(path.read_text())
    data["features"] = data["features"][1:]
    path.write_text(json.dumps(data))
    _rehash(directory, "drawing.geojson")
    with pytest.raises(ValueError, match="GeoJSON"):
        replay_delivery(bundle, revision, directory)


def test_load_delivery_refuses_reduced_verification_unless_allowed(tmp_path, monkeypatch):
    bundle, revision, directory = _publish(tmp_path)

    def unavailable(*args, **kwargs):
        raise pyproj.exceptions.ProjError("File not found or invalid")

    monkeypatch.setattr(pyproj.Transformer, "from_pipeline", unavailable)
    with pytest.raises(DeliveryReplayIncomplete, match="not re-verified"):
        load_delivery(bundle, revision, directory)
    assert issubclass(DeliveryReplayIncomplete, ValueError)
    snapshot = load_delivery(bundle, revision, directory, allow_unverified_geojson=True)
    assert snapshot == replay_delivery(bundle, revision, directory).snapshot


def test_cli_replay_reports_reduced_verification(tmp_path, monkeypatch):
    import argparse

    from mp_review.cli import _execute_delivery

    bundle, revision, directory = _publish(tmp_path)
    (tmp_path / "bundle.json").write_text(bundle.model_dump_json())

    def unavailable(*args, **kwargs):
        raise pyproj.exceptions.ProjError("File not found or invalid")

    monkeypatch.setattr(pyproj.Transformer, "from_pipeline", unavailable)
    args = argparse.Namespace(
        command="inspect-delivery",
        input=tmp_path / "bundle.json",
        revision_dir=revision,
        package_dir=directory,
    )
    payload = _execute_delivery(args, {})
    assert payload["status"] == "needs_review"
    assert payload["replay_verification"]["geojson_coordinates"] == "not_verified"


def test_delivery_1_golden_geojson_is_re_rendered_in_legacy_ring_order():
    from mp_models.dashboard import DashboardBundle

    bundle = DashboardBundle.model_validate_json((GOLDEN / "bundle.json").read_text())
    directory = GOLDEN / "deliveries/placed-delivery"
    replay = replay_delivery(bundle, GOLDEN / "revisions/placed-revision", directory)
    assert replay.snapshot.exporter_version == "delivery-1"
    assert replay.geojson_coordinates == "reproduced"
