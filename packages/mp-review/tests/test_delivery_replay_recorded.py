"""Delivery replay trusts the recorded package, not the replay host's PROJ setup.

Area-of-use omissions (whole-format and per-layer) and the coordinate operation
are environment-dependent choices made at publish. Replay accepts them as
recorded in the snapshot/manifest and verifies integrity by stored artifact
hashes and snapshot identity; it never re-runs the area-of-use check. New
publishes keep the fail-closed check.
"""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from mp_models.delivery import DeliveryRequest
from mp_review.delivery import load_delivery, publish_delivery

pytest.importorskip("pyproj")

_TESTS = Path(__file__).parent


def _module(name):
    spec = importlib.util.spec_from_file_location(f"_replay_{name}", _TESTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _optional(request):
    data = request.model_dump(mode="json")
    for layer in data["layers"]:
        layer["required"] = False
    return DeliveryRequest.model_validate(data)


def _missing_grid(scene, extent=None):
    import mp_review.webmap_projection as module

    raise module.WebMapUnavailable("missing_grid", "Required grids are unavailable locally.")


def _rehash(directory, name):
    manifest_path = directory / "delivery-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"][name] = hashlib.sha256((directory / name).read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))


def test_published_without_grid_replays_with_grid(tmp_path, monkeypatch):
    import mp_review.webmap_projection as module

    real = module.build_web_map_projection
    monkeypatch.setattr(module, "build_web_map_projection", _missing_grid)
    bundle, revision, request = _module("test_delivery_store")._placed_case(tmp_path)
    request = _optional(request)
    result = publish_delivery(bundle, revision, request, tmp_path / "deliveries")
    assert result["status"] == "needs_review", result
    assert "drawing.geojson" not in result["artifacts"]
    calls = []

    def spy(scene, extent=None):
        calls.append(extent)
        return real(scene, extent=extent)

    monkeypatch.setattr(module, "build_web_map_projection", spy)
    snapshot = load_delivery(bundle, revision, tmp_path / "deliveries" / request.id)
    assert any(o.format == "geojson" and o.layer_id is None for o in snapshot.omissions)
    assert calls == []  # replay never re-runs the area-of-use/operation choice


def test_published_with_grid_replays_without_grid(tmp_path, monkeypatch):
    import mp_review.webmap_projection as module

    bundle, revision, request = _module("test_delivery_store")._placed_case(tmp_path)
    result = publish_delivery(bundle, revision, request, tmp_path / "deliveries")
    assert result["status"] == "needs_review", result
    assert "drawing.geojson" in result["artifacts"]
    monkeypatch.setattr(module, "build_web_map_projection", _missing_grid)
    snapshot = load_delivery(bundle, revision, tmp_path / "deliveries" / request.id)
    assert not any(o.reason.startswith("GeoJSON omitted") for o in snapshot.omissions)


def _far_publish(tmp_path):
    context = _module("test_delivery_context_area")
    bundle, revision, request = context._far_context_module()._placed_case(tmp_path)
    request = context._with_far_layer(request, required=False)
    result = publish_delivery(bundle, revision, request, tmp_path / "deliveries")
    assert result["status"] == "needs_review", result
    return bundle, revision, tmp_path / "deliveries" / request.id


def test_recorded_layer_omission_replays_when_replay_operation_differs(tmp_path, monkeypatch):
    import mp_review.webmap as webmap

    bundle, revision, directory = _far_publish(tmp_path)
    # A replay host whose operation would cover everything (or nothing).
    monkeypatch.setattr(webmap, "require_area", lambda projection, extent: None)
    snapshot = load_delivery(bundle, revision, directory)
    assert any(o.layer_id == "far-context" and o.format == "geojson" for o in snapshot.omissions)

    def outside(projection, extent):
        raise ValueError("must not be called on replay")

    monkeypatch.setattr(webmap, "require_area", outside)
    load_delivery(bundle, revision, directory)


def test_replay_detects_recorded_omission_tampering_in_snapshot(tmp_path):
    bundle, revision, directory = _far_publish(tmp_path)
    path = directory / "snapshot.json"
    data = json.loads(path.read_text())
    data["omissions"] = [o for o in data["omissions"] if o.get("layer_id") != "far-context"]
    path.write_text(json.dumps(data))
    _rehash(directory, "snapshot.json")
    with pytest.raises(ValueError, match="mismatch"):
        load_delivery(bundle, revision, directory)


def test_replay_detects_fully_rewritten_omission_against_geojson(tmp_path):
    """Snapshot, pending and manifest rewritten consistently still disagree with GeoJSON."""
    from mp_verify.dashboard import _hash

    bundle, revision, directory = _far_publish(tmp_path)
    snapshot_path = directory / "snapshot.json"
    data = json.loads(snapshot_path.read_text())
    data["omissions"] = [o for o in data["omissions"] if o.get("layer_id") != "far-context"]
    snapshot_path.write_text(json.dumps(data))
    pending = json.loads((directory / "pending.json").read_text())
    pending["snapshot_sha256"] = _hash(data)
    (directory / "pending.json").write_text(json.dumps(pending))
    manifest_path = directory / "delivery-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["snapshot_sha256"] = _hash(data)
    manifest["omissions"] = data["omissions"]
    manifest_path.write_text(json.dumps(manifest))
    for name in ("snapshot.json", "pending.json"):
        _rehash(directory, name)
    with pytest.raises(ValueError):
        load_delivery(bundle, revision, directory)


def test_replay_detects_rehashed_geojson_tampering(tmp_path):
    bundle, revision, directory = _far_publish(tmp_path)
    path = directory / "drawing.geojson"
    data = json.loads(path.read_text())
    data["features"] = [
        f for f in data["features"] if f["properties"]["delivery_layer_id"] != "context"
    ]
    path.write_text(json.dumps(data))
    _rehash(directory, "drawing.geojson")
    with pytest.raises(ValueError, match="GeoJSON"):
        load_delivery(bundle, revision, directory)


def test_replay_detects_changed_artifact_and_manifest(tmp_path):
    bundle, revision, directory = _far_publish(tmp_path)
    (directory / "drawing.geojson").write_bytes(b"{}")
    with pytest.raises(ValueError, match="hash"):
        load_delivery(bundle, revision, directory)


def test_replay_detects_changed_manifest_omissions(tmp_path):
    bundle, revision, directory = _far_publish(tmp_path)
    manifest_path = directory / "delivery-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["omissions"] = [o for o in manifest["omissions"] if o.get("layer_id") != "far-context"]
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="policy"):
        load_delivery(bundle, revision, directory)


def test_publish_still_fails_closed_on_required_out_of_area_layer(tmp_path):
    context = _module("test_delivery_context_area")
    bundle, revision, request = context._far_context_module()._placed_case(tmp_path)
    request = context._with_far_layer(request, required=True)
    result = publish_delivery(bundle, revision, request, tmp_path / "deliveries")
    assert result["status"] == "error", result


def test_geojson_area_without_scene_raises_value_error(tmp_path):
    from mp_review.delivery import _geojson_omissions

    bundle, revision, request = _module("test_delivery_store")._placed_case(tmp_path)
    with pytest.raises(ValueError, match="projected scene"):
        _geojson_omissions((), None, request)


def test_corridor_ring_is_sampled_once_per_corridor_per_publish(tmp_path, monkeypatch):
    import mp_review.delivery_sources as sources

    derived = _module("test_delivery_derived_sources")
    bundle, revision, data = derived._placed_corridor_request(tmp_path)
    request = DeliveryRequest.model_validate(data)
    calls = []
    real = sources._corridor_ring

    def spy(item, *args, **kwargs):
        calls.append(item.selection.id)
        return real(item, *args, **kwargs)

    monkeypatch.setattr(sources, "_corridor_ring", spy)
    result = publish_delivery(bundle, revision, request, tmp_path / "exports")
    assert result["status"] == "needs_review", result
    corridors = [layer.id for layer in request.layers if layer.kind == "corridor"]
    assert corridors and sorted(calls) == sorted(corridors)
