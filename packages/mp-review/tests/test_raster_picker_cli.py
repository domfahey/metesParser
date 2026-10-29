"""Optional picker command preserves inputs without registering the scan."""

import json
import subprocess
import sys

from PIL import Image


def test_picker_command_retains_raw_inputs_and_never_registers(tmp_path):
    image = tmp_path / "scan.png"
    Image.new("RGB", (20, 10), "white").save(image)
    controls = tmp_path / "controls.json"
    controls.write_text(
        json.dumps(
            {
                "scene": {
                    "id": "grid",
                    "name": "Supplied local map",
                    "kind": "local",
                    "units": "m",
                    "basis": "local",
                },
                "controls": [],
            },
            indent=3,
        )
    )
    output = tmp_path / "picker"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mp_review",
            "pick-raster",
            str(image),
            "--controls",
            str(controls),
            "--output-dir",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["registration_performed"] is False
    assert payload["verified_export_eligible"] is False
    assert (output / "controls-source.json").read_bytes() == controls.read_bytes()
    assert (output / "image.png").read_bytes() == image.read_bytes()
    assert (output / "picker.html").is_file()
    assert (output / "picker-manifest.json").is_file()
