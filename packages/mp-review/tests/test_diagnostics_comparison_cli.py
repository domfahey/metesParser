"""Advisory CLI routes preserve input identity and non-verification status."""

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "command,fixture,retained",
    [
        ("diagnose-closure", "diagnostics/request.json", "request.json"),
        ("compare-descriptions", "comparison-synthetic.json", "comparison-request.json"),
    ],
)
def test_advisory_file_command_retains_exact_input_and_uses_exit_one(
    command, fixture, retained, tmp_path
):
    source = Path(__file__).parent / "fixtures" / fixture
    output = tmp_path / "result"
    result = subprocess.run(
        [sys.executable, "-m", "mp_review", command, str(source), "--output-dir", str(output)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1, result.stderr
    response = json.loads(result.stdout)
    assert response["status"] == "needs_review"
    assert (output / retained).read_bytes() == source.read_bytes()
    assert not list(output.glob("*verified*"))
    again = subprocess.run(
        [sys.executable, "-m", "mp_review", command, str(source), "--output-dir", str(output)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert again.returncode == 2
    assert json.loads(again.stdout)["status"] == "error"
