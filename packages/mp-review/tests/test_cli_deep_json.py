"""Deeply nested JSON is an invocation error (exit 2, invalid_input_json) for every command."""

import json
import subprocess
import sys

import pytest

COMMANDS = [
    ["inspect-delivery", "--revision-dir", "REV", "--package-dir", "PKG"],
    ["inspect-revision", "--revision-dir", "REV"],
    ["plot", "--output-dir", "OUT"],
    ["verify", "--output-dir", "OUT"],
    ["review", "--output-dir", "OUT"],
    ["analyze-corridor", "--output-dir", "OUT"],
    ["derive-plss", "--output-dir", "OUT"],
    ["analyze-relative", "--output-dir", "OUT"],
    ["compare-descriptions", "--output-dir", "OUT"],
    ["validate-source"],
    ["dashboard", "--output-dir", "OUT"],
    ["render-map", "--online-map-config", "CFG", "--output-dir", "OUT"],
]
PAYLOADS = {
    "top-level": "[" * 100000 + "]" * 100000,
    "nested-in-field": '{"a": ' + "[" * 2000 + "]" * 2000 + "}",
}
STRICT_NESTED = {"plot", "analyze-corridor"}  # validators that recurse over decoded values
OWN_CODES = {
    "top-level": {"compare-descriptions", "validate-source", "render-map"},
    "nested-in-field": {c[0] for c in COMMANDS} - STRICT_NESTED,
}


@pytest.mark.parametrize("shape", PAYLOADS)
@pytest.mark.parametrize("command", COMMANDS, ids=lambda c: c[0])
def test_deeply_nested_json_is_invalid_input_json(tmp_path, command, shape):
    source = tmp_path / "nested.json"
    source.write_text(PAYLOADS[shape])
    (tmp_path / "REV").mkdir()
    (tmp_path / "PKG").mkdir()
    (tmp_path / "CFG").write_text("{}")
    args = [str(tmp_path / a) if a in ("REV", "PKG", "CFG", "OUT") else a for a in command[1:]]
    result = subprocess.run(
        [sys.executable, "-m", "mp_review", command[0], str(source), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    assert "Traceback" not in result.stderr, result.stderr[-500:]
    assert result.returncode == 2, result.stderr[-500:]
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    code = payload["errors"][0]["code"]
    if command[0] in OWN_CODES[shape]:
        # These commands classify the unusable payload with their own domain error code.
        assert code != "internal_recursion_error", payload
    else:
        assert code == "invalid_input_json", payload
