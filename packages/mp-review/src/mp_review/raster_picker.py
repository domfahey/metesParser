"""Prepare an optional offline pixel picker while retaining source evidence."""

from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path
from typing import Any

from mp_models.plot import PlotScene
from mp_models.raster import RasterControl

from .dashboard import _atomic
from .plot import _finite_json
from .raster_registration import image_layer, supplied_affine
from .relative import _invalid_number, _unique_object


def _json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode()


def _read(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Picker inputs must be existing regular files")
    return path.read_bytes()


def prepare_raster_picker_file(
    image_path: Path | str, controls_path: Path | str, output_dir: Path | str
) -> dict[str, Any]:
    """Publish a standalone picker; downloading controls does not calibrate a scan.

    Supported images retain decoded native orientation. EXIF-rotated and animated
    images are refused rather than silently transformed before pixel collection.
    """
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "needs_review",
        "engine_verified": False,
        "verified_export_eligible": False,
        "registration_performed": False,
        "artifacts": {},
        "errors": [],
    }
    try:
        output = Path(output_dir)
        if output.is_symlink() or output.exists():
            raise ValueError("Picker output must be a new directory")
        image_bytes, controls_bytes = _read(Path(image_path)), _read(Path(controls_path))
        config = json.loads(
            controls_bytes, object_pairs_hook=_unique_object, parse_constant=_invalid_number
        )
        _finite_json(config)
        if not isinstance(config, dict):
            raise ValueError("Picker controls require a scene/config object")
        if config.get("pixel_convention", "integer_pixel_centers") != "integer_pixel_centers":
            raise ValueError("Only integer pixel centers are supported")
        scene = PlotScene.model_validate(config["scene"])
        controls = tuple(RasterControl.model_validate(c) for c in config.get("controls", []))
        if len({c.id for c in controls}) != len(controls):
            raise ValueError("Picker control names must be unique")
        if "matrix" in config:
            supplied_affine(config["matrix"], controls)
        # Reuse strict image decode/content limits. Identity is validation-only and is not exported as registration.
        layer, _ = image_layer(
            image_bytes,
            scene=scene,
            registration=supplied_affine((1, 0, 0, 0, 1, 0)),
            filename=Path(image_path).name,
        )
        from PIL import Image

        with Image.open(BytesIO(image_bytes)) as image:
            if image.getexif().get(274, 1) != 1:
                raise ValueError(
                    "EXIF-oriented images are unsupported; supply an already oriented scan with documented provenance"
                )
        config = dict(config)
        config.update(
            scene=scene.model_dump(mode="json"),
            controls=[c.model_dump(mode="json") for c in controls],
            pixel_convention="integer_pixel_centers",
        )
        image_sha, controls_sha = (
            hashlib.sha256(image_bytes).hexdigest(),
            hashlib.sha256(controls_bytes).hexdigest(),
        )
        from mp_export.raster_picker import (
            render_raster_picker,
        )

        html = render_raster_picker(image_bytes, config, controls_sha256=controls_sha)
        suffix = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[layer.mime_type]
        files = {
            "image" + suffix: image_bytes,
            "controls-source.json": controls_bytes,
            "controls-initial.json": _json(config),
            "picker.html": html.encode(),
        }
        manifest = {
            "schema_version": "1.0",
            "artifact_kind": "raster_control_picker",
            "builder_version": "raster-picker-1",
            "image_sha256": image_sha,
            "controls_source_sha256": controls_sha,
            "width": layer.width,
            "height": layer.height,
            "mime_type": layer.mime_type,
            "pixel_convention": "integer_pixel_centers",
            "registration_performed": False,
            "engine_verified": False,
            "verified_export_eligible": False,
            "sha256": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
        }
        output.mkdir(parents=True, exist_ok=False)
        for name, data in files.items():
            _atomic(output / name, data)
            result["artifacts"][name] = str(output / name)
        _atomic(output / "picker-manifest.json", _json(manifest))
        result["artifacts"]["picker-manifest.json"] = str(output / "picker-manifest.json")
        result.update(
            image_sha256=image_sha,
            pixel_convention="integer_pixel_centers",
            width=layer.width,
            height=layer.height,
        )
    except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        result["status"] = "error"
        result["errors"] = [{"code": "invalid_raster_picker_input", "message": str(exc)}]
    return result
