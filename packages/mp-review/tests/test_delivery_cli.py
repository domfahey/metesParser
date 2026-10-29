"""Public revision-view and portable export commands use replayed identities."""

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


def test_published_revision_view_export_and_replay(tmp_path):
    draft = tmp_path / "draft.json"
    assert command("revision-template", BASELINE, "--output", draft).returncode == 1
    revision = json.loads(draft.read_text())
    store = tmp_path / "revisions"
    assert (
        command("save-revision", BASELINE, "--revision", draft, "--output-dir", store).returncode
        == 1
    )
    directory = store / revision["id"]
    view = command(
        "render-revision", BASELINE, "--revision-dir", directory, "--output-dir", tmp_path / "view"
    )
    assert view.returncode == 1, view.stderr
    assert (tmp_path / "view/revision.html").is_file()
    assert json.loads(view.stdout)["verified_export_eligible"] is False
    request = tmp_path / "export.json"
    request.write_text(
        json.dumps(
            {
                "id": "delivery",
                "baseline": revision["baseline"],
                "revision_id": revision["id"],
                "revision_generation": revision["generation"],
                "geometry": "scenario",
                "coordinate_mode": "local",
                "units": "unknown_ft",
                "layers": [
                    {
                        "id": "calc-one",
                        "kind": "calculation",
                        "visible": True,
                        "opacity": 1.0,
                        "required": True,
                    }
                ],
                "formats": ["svg"],
            }
        )
    )
    exported = command(
        "export-review",
        BASELINE,
        "--revision-dir",
        directory,
        "--request",
        request,
        "--output-dir",
        tmp_path / "packages",
    )
    assert exported.returncode == 1, exported.stdout + exported.stderr
    assert json.loads(exported.stdout)["save_state"] == "published"
    package = tmp_path / "packages/delivery"
    inspected = command(
        "inspect-delivery", BASELINE, "--revision-dir", directory, "--package-dir", package
    )
    assert inspected.returncode == 1, inspected.stderr
    assert json.loads(inspected.stdout)["snapshot"]["request"]["revision_id"] == revision["id"]
    manifest = package / "delivery-manifest.json"
    corrupted = json.loads(manifest.read_text())
    corrupted["revision_sha256"] = "0" * 64
    manifest.write_text(json.dumps(corrupted))
    assert (
        command(
            "inspect-delivery", BASELINE, "--revision-dir", directory, "--package-dir", package
        ).returncode
        == 2
    )
    assert not list(tmp_path.rglob("*verified.csv"))


@pytest.mark.parametrize(
    "name,extra",
    [
        ("render-revision", []),
        ("export-review", ["--request", "absent.json"]),
        ("inspect-delivery", ["--package-dir", "absent"]),
    ],
)
def test_delivery_commands_honor_disabled_settings(name, extra, tmp_path):
    settings = tmp_path / "disabled.md"
    settings.write_text("---\nenabled: false\n---\n")
    result = command(name, BASELINE, "--revision-dir", "absent", *extra, "--settings", settings)
    assert result.returncode == 2
    assert json.loads(result.stdout)["errors"][0]["code"] == "plugin_disabled"
