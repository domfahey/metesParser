"""Root wheel packaging regressions: no duplicate archive entries, prompts and license shipped."""

import shutil
import subprocess
import tomllib
import zipfile
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROMPTS = (
    "extract_calls.yaml",
    "extract_legal_description.yaml",
    "extract_text_from_pdf.yaml",
    "normalize_text.yaml",
)


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is required to build the wheel")
def test_root_wheel_has_no_duplicate_entries_and_ships_prompts_and_license(tmp_path):
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = list(tmp_path.glob("metesparser-*.whl"))
    assert len(wheels) == 1, f"expected one root wheel, found {wheels}"
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]

    with zipfile.ZipFile(wheels[0]) as archive:
        names = archive.namelist()

    duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
    assert not duplicates, f"wheel archive has duplicate entries: {duplicates}"
    for prompt in PROMPTS:
        assert names.count(f"metesparser/prompts/{prompt}") == 1
    assert f"metesparser-{version}.dist-info/licenses/LICENSE" in names
