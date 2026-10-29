"""Comparison stage integrity and exact-byte retention."""

import hashlib
import json
from pathlib import Path

from mp_models.comparison import ComparisonRequest
from mp_review.comparison import compare_descriptions_file
from mp_verify.comparison import compare_descriptions

FIXTURE = Path(__file__).parent / "fixtures" / "comparison-synthetic.json"


def test_exact_bytes_hashed_and_replay_matches_new_directory(tmp_path):
    raw = b" \n" + FIXTURE.read_bytes() + b"\n\n"
    source = tmp_path / "request.json"
    source.write_bytes(raw)
    output = tmp_path / "out"
    response = compare_descriptions_file(source, output)
    assert response["status"] == "needs_review"
    assert (output / "comparison-request.json").read_bytes() == raw
    manifest = json.loads((output / "comparison-manifest.json").read_bytes())
    assert manifest["request_sha256"] == hashlib.sha256(raw).hexdigest()
    result_bytes = (output / "comparison.json").read_bytes()
    assert manifest["result_sha256"] == hashlib.sha256(result_bytes).hexdigest()
    result = json.loads(result_bytes)
    expected = compare_descriptions(ComparisonRequest.model_validate_json(raw))
    assert result == expected.model_dump(mode="json")
    assert manifest["input_hash"] == expected.input_hash
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    assert compare_descriptions_file(source, output)["status"] == "error"
    assert before == {p.name: p.read_bytes() for p in output.iterdir()}


def test_bad_input_never_creates_output_or_echoes_source(tmp_path):
    source = tmp_path / "bad.json"
    source.write_text('{"private_text": "do-not-echo"}')
    output = tmp_path / "out"
    response = compare_descriptions_file(source, output)
    assert response["status"] == "error"
    assert "do-not-echo" not in json.dumps(response)
    assert not output.exists()


def test_reject_symlink_input(tmp_path):
    source = tmp_path / "link.json"
    source.symlink_to(FIXTURE.resolve())
    assert compare_descriptions_file(source, tmp_path / "out")["status"] == "error"
