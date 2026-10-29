"""Saved corridor definitions remain exact, revision-bound and replayable."""

import json
from pathlib import Path

import pytest
from mp_models.dashboard import DashboardBundle
from mp_models.revisions import revision_template
from mp_review.revisions import import_revision, load_revision, publish_revision


@pytest.fixture
def bundle():
    return DashboardBundle.model_validate_json(
        (Path(__file__).parent / "fixtures/dashboard-absolute.json").read_text()
    )


@pytest.fixture
def corridor_raw():
    path = (
        Path(__file__).parents[3]
        / "plugins/metesparser/skills/plot-corridor/references/example.json"
    )
    return path.read_text()


def revision_with_corridor(bundle, raw, *, revision_id="corridor-revision"):
    data = revision_template(bundle, revision_id=revision_id).model_dump(mode="json")
    data["schema_version"] = "1.2"
    data["corridors"] = [{"id": "synthetic-corridor", "action": "retain", "raw_request_json": raw}]
    return data


def test_corridor_raw_definition_and_computed_result_survive_manifest_replay(
    bundle, corridor_raw, tmp_path
):
    data = revision_with_corridor(bundle, corridor_raw)
    prepared = import_revision(bundle, data)

    assert prepared.revision.corridors[0].raw_request_json == corridor_raw
    assert prepared.corridor_results[0].id == "synthetic-corridor"
    assert prepared.corridor_results[0].state == "computed"
    assert (
        prepared.corridor_results[0].request.model_dump(mode="json")["widths"][0]["left_start"]
        == 10
    )
    assert prepared.corridor_results[0].result.availability == "supported"

    published = publish_revision(bundle, data, tmp_path)
    assert published["save_state"] == "published"
    assert "corridors.json" in published["artifacts"]
    restored = load_revision(bundle, tmp_path / "corridor-revision")
    assert restored == prepared
    assert restored.revision.corridors[0].raw_request_json == corridor_raw
    assert restored.corridor_results[0].result == prepared.corridor_results[0].result


def test_unsupported_corridor_is_a_recoverable_per_corridor_draft(bundle, corridor_raw):
    request = json.loads(corridor_raw)
    request["centerline"]["calls"][0]["call"]["is_indefinite"] = True
    raw = json.dumps(request, separators=(",", ":"))
    prepared = import_revision(bundle, revision_with_corridor(bundle, raw))

    result = prepared.corridor_results[0]
    assert prepared.state == "parsed"
    assert result.state == "draft"
    assert prepared.revision.corridors[0].raw_request_json == raw
    assert result.result.availability == "incomplete"
    assert result.reasons


def test_parent_corridor_inventory_requires_explicit_removal_and_raw_tombstone(
    bundle, corridor_raw, tmp_path
):
    first = revision_with_corridor(bundle, corridor_raw, revision_id="corridor-parent")
    assert publish_revision(bundle, first, tmp_path)["save_state"] == "published"
    parent = load_revision(bundle, tmp_path / "corridor-parent")

    child = revision_with_corridor(bundle, corridor_raw, revision_id="corridor-child")
    child["generation"] = 1
    child["parent_revision_id"] = "corridor-parent"
    child["corridors"] = []
    with pytest.raises(ValueError, match="corridor inventory"):
        import_revision(bundle, child, last_valid=parent)

    child["corridors"] = [
        {"id": "synthetic-corridor", "action": "remove", "raw_request_json": corridor_raw}
    ]
    removed = import_revision(bundle, child, last_valid=parent)
    assert removed.revision.corridors[0].raw_request_json == corridor_raw
    assert removed.corridor_results == ()
    assert publish_revision(bundle, child, tmp_path)["save_state"] == "published"
    restored = load_revision(bundle, tmp_path / "corridor-child")
    assert restored.revision.corridors[0].action == "remove"
    assert restored.revision.corridors[0].raw_request_json == corridor_raw
    assert restored.corridor_results == ()

    altered = json.loads(json.dumps(child))
    altered["id"] = "altered-tombstone"
    altered["parent_revision_id"] = "corridor-parent"
    altered["corridors"][0]["raw_request_json"] += " "
    with pytest.raises(ValueError, match="tombstone"):
        import_revision(bundle, altered, last_valid=parent)


def test_child_can_edit_widths_but_cannot_rebind_centerline_identity(
    bundle, corridor_raw, tmp_path
):
    first = revision_with_corridor(bundle, corridor_raw, revision_id="corridor-parent")
    assert publish_revision(bundle, first, tmp_path)["save_state"] == "published"
    parent = load_revision(bundle, tmp_path / "corridor-parent")

    child = revision_with_corridor(bundle, corridor_raw, revision_id="corridor-child")
    child["generation"] = 1
    child["parent_revision_id"] = "corridor-parent"
    request = json.loads(child["corridors"][0]["raw_request_json"])
    request["widths"][0]["left_start"] = 12.0
    child["corridors"][0]["raw_request_json"] = json.dumps(request, separators=(",", ":"))
    updated = import_revision(bundle, child, last_valid=parent)
    assert updated.corridor_results[0].state == "computed"
    assert (
        updated.corridor_results[0].result.input_sha256
        != parent.corridor_results[0].result.input_sha256
    )

    rebound = json.loads(json.dumps(child))
    changed_request = json.loads(rebound["corridors"][0]["raw_request_json"])
    changed_request["centerline"]["calls"][0]["id"] = "different-centerline-call"
    changed_request["widths"][0]["start"]["call_id"] = "different-centerline-call"
    changed_request["widths"][0]["end"]["call_id"] = "different-centerline-call"
    rebound["corridors"][0]["raw_request_json"] = json.dumps(changed_request, separators=(",", ":"))
    with pytest.raises(ValueError, match="rebound"):
        import_revision(bundle, rebound, last_valid=parent)


def test_legacy_revision_schemas_remain_supported(bundle):
    for schema in ("1.0", "1.1"):
        data = revision_template(bundle).model_dump(mode="json")
        data["schema_version"] = schema
        prepared = import_revision(bundle, data)
        assert prepared.revision.schema_version == schema
        assert prepared.corridor_results == ()


def test_corridor_manifest_is_written_last_and_identical_retry_recovers_raw(
    bundle, corridor_raw, tmp_path, monkeypatch
):
    import mp_review.revisions as api

    data = revision_with_corridor(bundle, corridor_raw)
    write_once = api._write_once

    def interrupt_manifest(path, content):
        if path.name == "manifest.json":
            raise OSError("interrupted revision publication")
        return write_once(path, content)

    monkeypatch.setattr(api, "_write_once", interrupt_manifest)
    assert publish_revision(bundle, data, tmp_path)["save_state"] == "failed"
    with pytest.raises(ValueError, match="incomplete"):
        load_revision(bundle, tmp_path / "corridor-revision")

    monkeypatch.setattr(api, "_write_once", write_once)
    assert publish_revision(bundle, data, tmp_path)["save_state"] == "published"
    restored = load_revision(bundle, tmp_path / "corridor-revision")
    assert restored.revision.corridors[0].raw_request_json == corridor_raw
    artifact = json.loads((tmp_path / "corridor-revision/corridors.json").read_text())
    assert artifact["corridors"][0]["raw_request_json"] == corridor_raw
