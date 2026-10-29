"""Reopened revisions become manifest-bound offline review views."""

import hashlib
import json
from pathlib import Path

from mp_models.dashboard import DashboardBundle
from mp_models.revisions import revision_template
from mp_review.revision_view import render_revision_file
from mp_review.revisions import publish_revision

ROOT = Path(__file__).resolve().parents[3]


def test_view_replays_published_revision_and_preserves_original_bytes(tmp_path):
    raw = (ROOT / "packages/mp-review/tests/fixtures/dashboard-absolute.json").read_bytes()
    source = tmp_path / "bundle.json"
    source.write_bytes(raw)
    bundle = DashboardBundle.model_validate_json(raw)
    revision = revision_template(bundle, revision_id="selected")
    assert publish_revision(bundle, revision, tmp_path / "store")["save_state"] == "published"
    output = tmp_path / "view"
    result = render_revision_file(source, tmp_path / "store" / "selected", output)
    assert result["status"] == "needs_review"
    assert result["revision_id"] == "selected"
    assert source.read_bytes() == raw
    assert (output / "revision.json").read_bytes() == (
        tmp_path / "store" / "selected" / "revision.json"
    ).read_bytes()
    manifest = json.loads((output / "revision-view-manifest.json").read_text())
    for name, digest in manifest["sha256"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
    assert manifest["bundle_sha256"] == hashlib.sha256(raw).hexdigest()
    assert (
        render_revision_file(source, tmp_path / "store" / "selected", output)["status"] == "error"
    )


def test_incomplete_or_tampered_revision_cannot_render(tmp_path):
    source = tmp_path / "bundle.json"
    source.write_bytes(
        (ROOT / "packages/mp-review/tests/fixtures/dashboard-absolute.json").read_bytes()
    )
    directory = tmp_path / "incomplete"
    directory.mkdir()
    result = render_revision_file(source, directory, tmp_path / "view")
    assert result["status"] == "error"
    assert not (tmp_path / "view").exists()


def test_failed_component_has_no_completed_view_manifest(tmp_path, monkeypatch):
    import mp_review.revision_view as api

    raw = (ROOT / "packages/mp-review/tests/fixtures/dashboard-absolute.json").read_bytes()
    source = tmp_path / "bundle.json"
    source.write_bytes(raw)
    bundle = DashboardBundle.model_validate_json(raw)
    revision = revision_template(bundle, revision_id="selected")
    assert publish_revision(bundle, revision, tmp_path / "store")["save_state"] == "published"
    write = api._atomic

    def interrupted(path, content):
        if path.name == "prepared-revision.json":
            raise OSError("interrupted view generation")
        write(path, content)

    monkeypatch.setattr(api, "_atomic", interrupted)
    result = render_revision_file(source, tmp_path / "store" / "selected", tmp_path / "partial")
    assert result["status"] == "error"
    assert not (tmp_path / "partial" / "revision-view-manifest.json").exists()
    assert source.read_bytes() == raw
