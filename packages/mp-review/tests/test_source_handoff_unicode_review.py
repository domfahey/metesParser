"""Independent review regressions: JSON escapes must not crash byte/path operations."""

import json
import shutil
from pathlib import Path

import pytest
from mp_review.source_handoff import validate_source_bundle

FIXTURE = Path(__file__).parent / "fixtures/source_handoff"


@pytest.fixture
def source_bundle(tmp_path):
    shutil.copytree(FIXTURE, tmp_path, dirs_exist_ok=True)
    return tmp_path


@pytest.mark.parametrize(
    "field", ["original_path", "transcript_path", "selected_path", "separator", "request_text"]
)
def test_json_escaped_unpaired_surrogates_are_structured_schema_errors(source_bundle, field):
    name = (
        "description-selection.json"
        if field in {"selected_path", "separator"}
        else "source-acquisition.json"
    )
    value = json.loads((source_bundle / name).read_bytes())
    if field == "original_path":
        value["sources"][0]["path"] = "\ud800.bin"
    elif field == "transcript_path":
        value["transcript"]["path"] = "\ud800.txt"
    elif field == "selected_path":
        value["candidates"][0]["selected_text"]["path"] = "\udfff.txt"
    elif field == "separator":
        value["candidates"][0]["separators"] = ["\ud800"]
    else:
        value["request"] = "invalid Unicode scalar \ud800"
    (source_bundle / name).write_text(json.dumps(value, ensure_ascii=True))
    response = validate_source_bundle(source_bundle)
    assert response["status"] == "error"
    assert response["structure"]["status"] == "invalid"
    assert any(item["code"] == "schema_invalid" for item in response["findings"])


@pytest.mark.parametrize("override", ["\ud800.json", "invalid\x00.json"])
def test_unrepresentable_invocation_path_returns_structured_error(source_bundle, override):
    response = validate_source_bundle(source_bundle, acquisition=Path(override))
    assert response["status"] == "error"
    assert response["errors"]


def test_valid_nonascii_scalar_text_remains_exact(source_bundle):
    path = source_bundle / "source-acquisition.json"
    raw = json.loads(path.read_bytes())
    raw["request"] = "  Read café, 漢字, and \U0001f600 without normalizing.\r\n"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    before = {p.name: p.read_bytes() for p in source_bundle.iterdir()}
    response = validate_source_bundle(source_bundle)
    assert response["structure"]["status"] == "valid"
    assert response["status"] == "needs_review"
    assert {p.name: p.read_bytes() for p in source_bundle.iterdir()} == before
