"""Revision-bound corridor construction survives reload and delivery replay."""

import base64
import hashlib
import json
from pathlib import Path

import pytest
from mp_models.corridor import CorridorRequest
from mp_models.dashboard import DashboardBundle
from mp_models.delivery import DeliveryRequest
from mp_models.revisions import revision_template
from mp_review.delivery import load_delivery, prepare_delivery, publish_delivery
from mp_review.revisions import load_revision, publish_revision
from mp_verify.corridor import analyze_corridor

PLUGIN = Path(__file__).parents[3] / "plugins/metesparser"


def _saved_revision(tmp_path: Path, *, action: str = "retain", unsupported: bool = False):
    bundle = DashboardBundle.model_validate_json(
        (PLUGIN / "skills/export-review-package/references/bundle-example.json").read_bytes()
    )
    raw = (PLUGIN / "skills/plot-corridor/references/example.json").read_bytes()
    corridor = CorridorRequest.model_validate_json(raw)
    retained_raw = "{ malformed" if unsupported else raw.decode("utf-8")
    revision_root = tmp_path / "revisions"
    if action == "remove":
        parent = revision_template(bundle, revision_id="corridor-parent").model_dump(mode="json")
        parent.update(
            schema_version="1.2",
            corridors=[{"id": corridor.id, "action": "retain", "raw_request_json": retained_raw}],
        )
        assert publish_revision(bundle, parent, revision_root)["save_state"] == "published"
        revision = revision_template(bundle, revision_id="corridor-delivery").model_dump(
            mode="json"
        )
        revision.update(
            schema_version="1.2",
            generation=1,
            parent_revision_id=parent["id"],
            corridors=[{"id": corridor.id, "action": "remove", "raw_request_json": retained_raw}],
        )
    else:
        revision = revision_template(bundle, revision_id="corridor-delivery").model_dump(
            mode="json"
        )
        revision.update(
            schema_version="1.2",
            corridors=[{"id": corridor.id, "action": action, "raw_request_json": retained_raw}],
        )
    saved = publish_revision(bundle, revision, revision_root)
    assert saved["save_state"] == "published"
    revision_dir = revision_root / revision["id"]
    prepared = load_revision(bundle, revision_dir)
    record = prepared.corridor_results[0] if prepared.corridor_results else None
    result = (
        record.result
        if record is not None and record.result is not None and record.result.boundary is not None
        else analyze_corridor(corridor)
    )
    assert result is not None and result.boundary is not None
    manifest_sha256 = hashlib.sha256((revision_dir / "manifest.json").read_bytes()).hexdigest()
    binding = {
        "id": "revision-corridor-binding",
        "kind": "corridor",
        "layer_id": result.boundary.request.calculation_id,
        "revision_corridor_id": corridor.id,
        "manifest_sha256": manifest_sha256,
        "input_sha256": result.input_sha256,
        "geometry_sha256": result.boundary.geometry.geometry_hash,
    }
    request = DeliveryRequest.model_validate(
        {
            "id": "corridor-delivery-package",
            "baseline": prepared.revision.baseline.model_dump(mode="json"),
            "revision_id": prepared.revision.id,
            "revision_generation": prepared.revision.generation,
            "geometry": "scenario",
            "coordinate_mode": "local",
            "units": "international_ft",
            "layers": [
                {
                    "id": binding["layer_id"],
                    "kind": "corridor",
                    "visible": True,
                    "opacity": 1.0,
                    "required": True,
                }
            ],
            "source_bindings": [binding],
            "formats": ["svg", "pdf"],
        }
    )
    return bundle, revision_dir, request, prepared, raw


def test_saved_revision_corridor_reloads_plots_and_exports_exact_construction(tmp_path):
    bundle, revision_dir, request, prepared, raw = _saved_revision(tmp_path)
    corridor = prepared.corridor_results[0]
    assert corridor.state == "computed"
    assert corridor.result is not None and corridor.result.boundary is not None

    snapshot = prepare_delivery(bundle, revision_dir, request)
    record = snapshot.derived_sources[0]
    assert record["binding"]["revision_corridor_id"] == corridor.id
    assert record["binding"]["artifact_dir"] is None
    assert base64.b64decode(record["raw_request_base64"]) == raw
    assert record["canonical_request"] == corridor.request.model_dump(mode="json")
    assert record["boundary_geometry_sha256"] == corridor.result.boundary.geometry.geometry_hash
    assert snapshot.items[0].plot is not None

    published = publish_delivery(bundle, revision_dir, request, tmp_path / "exports")
    assert published["status"] == "needs_review"
    restored = load_delivery(bundle, revision_dir, tmp_path / "exports" / request.id)
    assert restored == snapshot
    saved_snapshot = json.loads((tmp_path / "exports" / request.id / "snapshot.json").read_text())
    assert saved_snapshot["derived_sources"][0]["canonical_request"] == corridor.request.model_dump(
        mode="json"
    )
    assert (tmp_path / "exports" / request.id / "drawing.svg").is_file()
    assert (tmp_path / "exports" / request.id / "drawing.pdf").is_file()


@pytest.mark.parametrize("field", ["manifest_sha256", "input_sha256", "geometry_sha256"])
def test_revision_corridor_delivery_rejects_changed_binding_hash(tmp_path, field):
    bundle, revision_dir, request, _, _ = _saved_revision(tmp_path)
    data = request.model_dump(mode="json")
    data["source_bindings"][0][field] = "0" * 64
    with pytest.raises(ValueError):
        prepare_delivery(bundle, revision_dir, DeliveryRequest.model_validate(data))


def test_revision_corridor_delivery_rejects_removed_corridor(tmp_path):
    bundle, revision_dir, request, _, _ = _saved_revision(tmp_path, action="remove")
    with pytest.raises(ValueError, match="removed"):
        prepare_delivery(bundle, revision_dir, request)


def test_revision_corridor_delivery_rejects_unresolved_corridor(tmp_path):
    bundle, revision_dir, request, _, _ = _saved_revision(tmp_path, unsupported=True)
    with pytest.raises(ValueError, match="unresolved or unsupported"):
        prepare_delivery(bundle, revision_dir, request)


def test_revision_corridor_delivery_rejects_stale_revision_generation(tmp_path):
    bundle, revision_dir, request, _, _ = _saved_revision(tmp_path)
    data = request.model_dump(mode="json")
    data["revision_generation"] += 1
    with pytest.raises(ValueError, match="revision/baseline identity"):
        prepare_delivery(bundle, revision_dir, DeliveryRequest.model_validate(data))


def test_revision_corridor_binding_requires_exactly_one_source_locator(tmp_path):
    _, _, request, _, _ = _saved_revision(tmp_path)
    data = request.model_dump(mode="json")
    binding = data["source_bindings"][0]
    binding["artifact_dir"] = "/tmp/external-corridor"
    with pytest.raises(ValueError, match="exactly one"):
        DeliveryRequest.model_validate(data)
