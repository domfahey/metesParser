import json
import sys

import pytest
from mp_review.cli import main


def test_import_command_creates_new_artifact_and_rejects_overwrite(tmp_path, monkeypatch, capsys):
    path = tmp_path / "input.json"
    raw = json.dumps(
        {
            "type": "Feature",
            "id": "x",
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
            "properties": {},
        }
    ).encode()
    path.write_bytes(raw)
    output = tmp_path / "layer.json"
    arguments = [
        "metes-review",
        "import-overlay",
        str(path),
        "--format",
        "geojson",
        "--target-crs",
        "EPSG:3857",
        "--output",
        str(output),
    ]
    monkeypatch.setattr(sys, "argv", arguments)
    with pytest.raises(SystemExit) as code:
        main()
    assert code.value.code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "passed"
    assert output.exists()
    with pytest.raises(SystemExit) as code:
        main()
    assert code.value.code == 2
    assert json.loads(capsys.readouterr().out)["status"] == "error"
    assert path.read_bytes() == raw


def test_register_raster_command_requires_scene_controls_and_new_output(
    tmp_path, monkeypatch, capsys
):
    from PIL import Image

    path = tmp_path / "image.png"
    Image.new("RGB", (10, 10)).save(path)
    config = tmp_path / "controls.json"
    config.write_text(
        json.dumps(
            {
                "scene": {
                    "id": "map",
                    "name": "map",
                    "kind": "projected",
                    "crs": "EPSG:3857",
                    "units": "m",
                },
                "controls": [
                    {"id": str(i), "pixel": p, "scene": p}
                    for i, p in enumerate([(0, 0), (10, 0), (0, 10)])
                ],
            }
        )
    )
    output = tmp_path / "raster.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "metes-review",
            "register-raster",
            str(path),
            "--controls",
            str(config),
            "--output",
            str(output),
        ],
    )
    with pytest.raises(SystemExit) as code:
        main()
    assert code.value.code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "passed"
    assert (
        json.loads(output.read_text())["raster_layers"][0]["registration"]["pixel_convention"]
        == "integer_pixel_centers"
    )
