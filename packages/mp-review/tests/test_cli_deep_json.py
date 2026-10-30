"""Deeply nested JSON is an invocation error (exit 2) for every JSON-reading command."""

import json
import subprocess
import sys

import pytest

COMMANDS = [
    ["inspect-delivery", "--revision-dir", "REV", "--package-dir", "PKG"],
    ["inspect-revision", "--revision-dir", "REV"],
    ["plot"],
    ["verify"],
    ["review"],
    ["analyze-corridor"],
    ["derive-plss"],
    ["analyze-relative"],
    ["compare-descriptions"],
    ["validate-source"],
    ["dashboard"],
    ["render-map", "--online-map-config", "CFG", "--output-dir", "OUT"],
]


@pytest.mark.parametrize("command", COMMANDS, ids=lambda c: c[0])
def test_deeply_nested_json_is_error_exit_2(tmp_path, command):
    source = tmp_path / "nested.json"
    source.write_text("[" * 100000 + "]" * 100000)
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
    assert json.loads(result.stdout)["status"] == "error"
