"""Saved review artifacts must be replayable without side effects or filename guesses."""

import hashlib
import json

import pytest
from mp_export.csv_writer import calls_to_csv
from mp_models import DeedCall
from mp_review import api


def test_review_manifest_retains_replay_parameters_and_artifact_hashes(tmp_path):
    source = tmp_path / "original.json"
    source.write_text(
        json.dumps([{"course": 1, "direction_text": "southwesterly", "distance_ft": 100}])
    )
    output = tmp_path / "review"
    result = api.review_file(source, output_dir=output, stated_area_sq_ft=123)
    manifest_path = output / "review-manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert manifest["replay_version"] == api.REPLAY_VERSION
    assert manifest["input"]["kind"] == "json"
    assert manifest["input"]["path"] == "source.txt"
    assert manifest["parameters"] == {"stated_area_sq_ft": 123}
    assert manifest["recorded_status"] == result["status"]
    for name, digest in manifest["artifacts"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest


def test_replay_exposes_exact_deterministic_audit_without_changing_review_envelope(tmp_path):
    source = "THENCE N 90°00'00\" E 100 feet to an iron pin;".encode()
    output = tmp_path / "review"
    result = api.review_text(source.decode(), source_name="description.txt", output_dir=output)
    replay = api.replay_review(source, input_kind="text", source_name="description.txt")
    assert "audit" not in result
    assert replay["audit"] == json.loads((output / "audit.json").read_text())
    assert replay["audit"]["call_audits"]
    assert replay["audit"]["original_source"] == source.decode()


@pytest.mark.parametrize("kind", ["json", "csv", "text"])
def test_replay_uses_original_input_kind_without_export_or_disk_writes(tmp_path, monkeypatch, kind):
    call = DeedCall(
        course=1, direction_text="E", bearing_azimuth_deg_from_north=90, distance_ft=100
    )
    source = tmp_path / ("original." + {"text": "txt"}.get(kind, kind))
    if kind == "csv":
        calls_to_csv([call], str(source))
    elif kind == "json":
        source.write_text(json.dumps([call.model_dump(mode="json")]))
    else:
        source.write_text("THENCE N 90 degrees E 100 feet;")
    result = api.review_file(source)
    raw = source.read_bytes()
    source.unlink()
    before = list(tmp_path.rglob("*"))

    def fail_export(*args, **kwargs):
        pytest.fail("Read-only replay may not export")

    monkeypatch.setattr(api, "export_verified_csv", fail_export)
    replay = api.replay_review(raw, source_name="source.txt", input_kind=kind)
    assert replay["calls"] == result["calls"]
    assert replay["verification"] == result["verification"]
    assert replay["status"] == result["status"]
    assert replay["artifacts"] == {}
    assert list(tmp_path.rglob("*")) == before
