"""Packages published by exporter delivery-1 must keep replaying as intact (PR #60 review)."""

import json
from pathlib import Path

import pytest
from mp_models.dashboard import DashboardBundle
from mp_review.delivery import load_delivery

GOLDEN = Path(__file__).parent / "fixtures/delivery-1-golden"


def _golden():
    bundle = DashboardBundle.model_validate_json((GOLDEN / "bundle.json").read_text())
    return bundle, GOLDEN / "revisions/placed-revision", GOLDEN / "deliveries/placed-delivery"


def test_delivery_1_golden_package_replays_intact():
    bundle, revision, directory = _golden()
    manifest = json.loads((directory / "delivery-manifest.json").read_text())
    assert manifest["exporter_version"] == "delivery-1"
    snapshot = load_delivery(bundle, revision, directory)
    assert snapshot.exporter_version == "delivery-1"
    assert snapshot.verified_export_eligible is False


def test_delivery_1_golden_geojson_keeps_legacy_ring_order():
    ring = json.loads((GOLDEN / "deliveries/placed-delivery/drawing.geojson").read_text())[
        "features"
    ]
    polygon = next(f for f in ring if f["geometry"]["type"] == "Polygon")["geometry"]
    pts = polygon["coordinates"][0]
    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:], strict=False))
    assert area < 0  # fixture really is the legacy clockwise exterior ring


def test_new_packages_record_current_exporter_version(tmp_path):
    from mp_models.delivery import DeliveryRequest
    from mp_review.delivery import prepare_delivery

    bundle, revision, directory = _golden()
    request = DeliveryRequest.model_validate_json((directory / "request.json").read_text())
    snapshot = prepare_delivery(bundle, revision, request)
    assert snapshot.exporter_version == "delivery-2"
    assert "Presentation rotation" in snapshot.omissions[0].reason
    with pytest.raises(ValueError):
        load_delivery(bundle, revision, directory.parent / "missing")


def test_replay_keeps_the_publishing_hosts_software_versions(monkeypatch):
    from mp_review import delivery

    monkeypatch.setattr(delivery.importlib.metadata, "version", lambda name: "9.9.9")
    bundle, revision, directory = _golden()
    snapshot = load_delivery(bundle, revision, directory)
    recorded = json.loads((directory / "snapshot.json").read_text())["software_versions"]
    assert [list(pair) for pair in snapshot.software_versions] == recorded
    assert ("mp-export", "9.9.9") not in snapshot.software_versions


def test_recorded_software_versions_must_name_the_requested_renderers():
    from mp_models.delivery import DeliveryRequest
    from mp_review.delivery import _software_versions

    _bundle, _revision, directory = _golden()
    request = DeliveryRequest.model_validate_json((directory / "request.json").read_text())
    recorded = json.loads((directory / "snapshot.json").read_text())["software_versions"]
    assert _software_versions(request, recorded) == tuple(tuple(pair) for pair in recorded)
    with pytest.raises(ValueError, match="software versions"):
        _software_versions(request, [["mp-verify", "1.0.0"], *recorded[1:]])
    with pytest.raises(ValueError, match="software versions"):
        _software_versions(request, recorded[:-1])
