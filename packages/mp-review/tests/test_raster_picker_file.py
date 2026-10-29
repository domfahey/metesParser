"""Offline point collection preserves sources and delegates calibration to Python."""

import base64
import hashlib
import json
import re

import pytest
from mp_models.raster import RasterControl
from mp_review.raster_picker import prepare_raster_picker_file
from mp_review.raster_registration import fit_affine
from PIL import Image


def inputs(tmp_path):
    image = tmp_path / "scan.png"
    Image.new("RGB", (20, 20), "white").save(image)
    config = {
        "scene": {
            "id": "local-grid",
            "name": "Supplied local metric grid",
            "kind": "local",
            "units": "m",
        },
        "controls": [
            {"id": "fit-a", "pixel": [0, 0], "scene": [100, 200], "role": "fit"},
            {"id": "fit-b", "pixel": [10, 0], "scene": [120, 200], "role": "fit"},
            {"id": "fit-c", "pixel": [0, 10], "scene": [100, 180], "role": "fit"},
            {"id": "check-d", "pixel": [10, 10], "scene": [125, 180], "role": "checkpoint"},
        ],
    }
    controls = tmp_path / "controls.json"
    controls.write_text(json.dumps(config, indent=3) + "\n\n")
    return image, controls, config


def seed(path):
    match = re.search(
        r'<script id="picker-data" type="application/json">(.*?)</script>', path.read_text(), re.S
    )
    assert match
    return json.loads(match.group(1))


def test_picker_preserves_exact_image_and_control_bytes_with_named_roles(tmp_path):
    image, controls, config = inputs(tmp_path)
    output = tmp_path / "picker"
    result = prepare_raster_picker_file(image, controls, output)
    assert result["status"] == "needs_review"
    assert (output / "image.png").read_bytes() == image.read_bytes()
    assert (output / "controls-source.json").read_bytes() == controls.read_bytes()
    payload = seed(output / "picker.html")
    assert base64.b64decode(payload["image_url"].split(",", 1)[1]) == image.read_bytes()
    assert payload["width"] == payload["height"] == 20
    assert payload["pixel_convention"] == "integer_pixel_centers"
    assert [c["role"] for c in payload["config"]["controls"]] == ["fit", "fit", "fit", "checkpoint"]
    registration = fit_affine(
        tuple(RasterControl.model_validate(c) for c in payload["config"]["controls"])
    )
    assert registration.fit_rms == pytest.approx(0, abs=1e-12)
    assert registration.checkpoint_rms == pytest.approx(5)
    assert not result["engine_verified"] and not result["verified_export_eligible"]
    manifest = json.loads((output / "picker-manifest.json").read_text())
    for name, digest in manifest["sha256"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest


def test_initial_empty_controls_are_allowed_without_fabricating_fit_points(tmp_path):
    image, controls, config = inputs(tmp_path)
    config["controls"] = []
    controls.write_text(json.dumps(config))
    assert (
        prepare_raster_picker_file(image, controls, tmp_path / "empty")["status"] == "needs_review"
    )
    assert seed(tmp_path / "empty/picker.html")["config"]["controls"] == []


@pytest.mark.parametrize(
    "change",
    [
        {"pixel_convention": "outer_edges"},
        {"controls": [{"id": "bad", "pixel": [float("nan"), 0], "scene": [0, 0], "role": "fit"}]},
        {"scene": {"id": "local", "name": "Unknown feet", "kind": "local", "units": "unknown_ft"}},
    ],
)
def test_unsupported_config_does_not_publish_picker(tmp_path, change):
    image, controls, config = inputs(tmp_path)
    config.update(change)
    controls.write_text(json.dumps(config))
    output = tmp_path / "bad"
    assert prepare_raster_picker_file(image, controls, output)["status"] == "error"
    assert not output.exists()


def test_existing_output_is_preserved_and_exif_rotation_is_not_silently_applied(tmp_path):
    image, controls, _ = inputs(tmp_path)
    output = tmp_path / "exists"
    output.mkdir()
    (output / "keep").write_bytes(b"original")
    assert prepare_raster_picker_file(image, controls, output)["status"] == "error"
    assert (output / "keep").read_bytes() == b"original"
    rotated = tmp_path / "rotated.jpg"
    value = Image.new("RGB", (20, 30), "white")
    exif = Image.Exif()
    exif[274] = 6
    value.save(rotated, exif=exif)
    assert prepare_raster_picker_file(rotated, controls, tmp_path / "rotated")["status"] == "error"


def test_picker_script_payload_cannot_be_closed_by_source_names(tmp_path):
    image, controls, config = inputs(tmp_path)
    config["scene"]["name"] = '</script><script>alert("x")</script>'
    controls.write_text(json.dumps(config))
    output = tmp_path / "safe"
    assert prepare_raster_picker_file(image, controls, output)["status"] == "needs_review"
    payload = seed(output / "picker.html")
    assert payload["config"]["scene"]["name"] == config["scene"]["name"]
    assert "</script><script>alert" not in (output / "picker.html").read_text()
