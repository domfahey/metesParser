"""Real command round trips preserve drafts without promoting review status."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

BASELINE = Path(__file__).parent / "fixtures/dashboard-absolute.json"


def command(*args):
    return subprocess.run(
        [sys.executable, "-m", "mp_review", *map(str, args)],
        text=True,
        capture_output=True,
        check=False,
    )


def test_template_publish_inspect_and_retry_keep_invalid_draft(tmp_path):
    draft = tmp_path / "draft.json"
    template = command("revision-template", BASELINE, "--output", draft)
    assert template.returncode == 1, template.stderr
    assert json.loads(template.stdout)["status"] == "needs_review"
    value = json.loads(draft.read_text())
    value["edits"] = [
        {
            "call_id": "call-one",
            "occurrence_id": "occ-one",
            "tract_id": "parcel-one",
            "document_id": "doc-one",
            "action": "update",
            "raw_fields": {"bearing_azimuth_deg_from_north": " N ", "notes": "  look at scan\n"},
            "rationale": "",
            "source_refs": [],
            "evidence_ids": [],
        }
    ]
    draft.write_text(json.dumps(value))
    store = tmp_path / "revisions"
    saved = command("save-revision", BASELINE, "--revision", draft, "--output-dir", store)
    assert saved.returncode == 1, saved.stderr
    result = json.loads(saved.stdout)
    assert result["save_state"] == "published"
    assert result["state"] == "draft"
    directory = store / value["id"]
    inspected = command("inspect-revision", BASELINE, "--revision-dir", directory)
    assert inspected.returncode == 1, inspected.stderr
    prepared = json.loads(inspected.stdout)["revision"]
    assert prepared["state"] == "draft"
    assert prepared["current_geometry"] == []
    assert prepared["revision"]["edits"][0]["raw_fields"] == value["edits"][0]["raw_fields"]
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    assert (
        command("save-revision", BASELINE, "--revision", draft, "--output-dir", store).returncode
        == 1
    )
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == before
    assert not list(store.rglob("*verified*"))
    assert command("revision-template", BASELINE, "--output", draft).returncode == 2


@pytest.mark.parametrize(
    "name,extra",
    [
        ("revision-template", ["--output", "never.json"]),
        ("save-revision", ["--revision", "absent.json"]),
        ("inspect-revision", ["--revision-dir", "absent"]),
    ],
)
def test_revision_commands_honor_disabled_settings(name, extra, tmp_path):
    settings = tmp_path / "disabled.md"
    settings.write_text("---\nenabled: false\n---\n")
    result = command(name, BASELINE, *extra, "--settings", settings)
    assert result.returncode == 2
    assert json.loads(result.stdout)["errors"][0]["code"] == "plugin_disabled"
