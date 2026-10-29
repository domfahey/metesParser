"""Immutable map-image registration; integer pixels denote centers, not edges."""

import base64
import hashlib
import math
from typing import Annotated, Literal, Self

from pydantic import Field, FiniteFloat, model_validator

from .base import _Model
from .plot import XY, Digest, Identifier


class RasterControl(_Model):
    id: str = Field(min_length=1)
    pixel: XY
    scene: XY
    role: Literal["fit", "checkpoint"] = "fit"


class RasterResidual(_Model):
    control_id: str
    role: Literal["fit", "checkpoint"]
    dx: FiniteFloat
    dy: FiniteFloat
    norm: Annotated[FiniteFloat, Field(ge=0)]


class RasterRegistration(_Model):
    pixel_convention: Literal["integer_pixel_centers"] = "integer_pixel_centers"
    matrix: tuple[FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat]
    method: Literal["affine_least_squares", "supplied_affine"]
    controls: tuple[RasterControl, ...] = ()
    residuals: tuple[RasterResidual, ...] = ()
    fit_rms: Annotated[FiniteFloat, Field(ge=0)] | None = None
    checkpoint_rms: Annotated[FiniteFloat, Field(ge=0)] | None = None
    status: Literal["approximate"] = "approximate"

    @model_validator(mode="after")
    def _invertible(self) -> Self:
        a, b, _, d, e, _ = self.matrix
        scale = max(abs(a), abs(b), abs(d), abs(e))
        determinant = a * e - b * d
        if (
            scale == 0
            or not math.isfinite(determinant)
            or abs(determinant) <= 1e-12 * scale * scale
        ):
            raise ValueError("Raster affine matrix is singular or ill-conditioned")
        if len({c.id for c in self.controls}) != len(self.controls):
            raise ValueError("Raster control IDs must be unique")
        a, b, c, d, e, f = self.matrix
        residuals = tuple(
            RasterResidual(
                control_id=p.id,
                role=p.role,
                dx=a * p.pixel[0] + b * p.pixel[1] + c - p.scene[0],
                dy=d * p.pixel[0] + e * p.pixel[1] + f - p.scene[1],
                norm=math.hypot(
                    a * p.pixel[0] + b * p.pixel[1] + c - p.scene[0],
                    d * p.pixel[0] + e * p.pixel[1] + f - p.scene[1],
                ),
            )
            for p in self.controls
        )
        fit = [p for p in self.controls if p.role == "fit"]
        if self.method == "affine_least_squares":
            if len(fit) < 3 or len({p.pixel for p in fit}) != len(fit):
                raise ValueError("At least three distinct affine fit controls required")
            u = sum(p.pixel[0] for p in fit) / len(fit)
            v = sum(p.pixel[1] for p in fit) / len(fit)
            uu = sum((p.pixel[0] - u) * (p.pixel[0] - u) for p in fit)
            vv = sum((p.pixel[1] - v) * (p.pixel[1] - v) for p in fit)
            uv = sum((p.pixel[0] - u) * (p.pixel[1] - v) for p in fit)
            if not all(math.isfinite(k) for k in (u, v, uu, vv, uv)):
                raise ValueError("Nonfinite raster control arithmetic")
            rank_scale = max(uu, vv)
            if (
                rank_scale == 0
                or (uu / rank_scale) * (vv / rank_scale) - (uv / rank_scale) ** 2 <= 1e-12
            ):
                raise ValueError("Affine controls are collinear or ill-conditioned")
            fit_res = [r for r in residuals if r.role == "fit"]
            for axis in ("dx", "dy"):
                values = [getattr(r, axis) for r in fit_res]
                tolerance = max(
                    1e-9, 128 * math.ulp(max(1.0, max(abs(k) for p in fit for k in p.scene)))
                )
                if abs(sum(values)) > tolerance * len(fit) or any(
                    abs(
                        sum(
                            value * (p.pixel[i] - (u, v)[i])
                            for value, p in zip(values, fit, strict=True)
                        )
                    )
                    > tolerance * sum(abs(p.pixel[i] - (u, v)[i]) for p in fit)
                    for i in (0, 1)
                ):
                    raise ValueError(
                        "Affine matrix is not the least squares solution of its controls"
                    )
        for name, expected in (("residuals", residuals),):
            if name in self.model_fields_set and getattr(self, name) != expected:
                raise ValueError("Raster residuals do not match controls")
            object.__setattr__(self, name, expected)
        for role, name in (("fit", "fit_rms"), ("checkpoint", "checkpoint_rms")):
            norms = [r.norm for r in residuals if r.role == role]
            expected_rms = math.sqrt(sum(n * n for n in norms) / len(norms)) if norms else None
            if name in self.model_fields_set and getattr(self, name) != expected_rms:
                raise ValueError("Raster residual RMS does not match controls")
            object.__setattr__(self, name, expected_rms)
        return self


class RasterLayer(_Model):
    id: Identifier
    label: str
    source_id: Identifier
    scene_id: Identifier
    mime_type: Literal["image/png", "image/jpeg", "image/webp"]
    width: Annotated[int, Field(gt=0, le=20000)]
    height: Annotated[int, Field(gt=0, le=20000)]
    sha256: Digest
    data_base64: str
    registration: RasterRegistration

    @model_validator(mode="after")
    def _content(self) -> Self:
        try:
            data = base64.b64decode(self.data_base64, validate=True)
        except ValueError as exc:
            raise ValueError("Raster content must be valid base64") from exc
        if len(data) > 20 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != self.sha256:
            raise ValueError("Raster content hash/size mismatch")
        if self.width * self.height > 40_000_000:
            raise ValueError("Raster dimensions exceed 40 million pixels")
        if image_header(data) != (self.mime_type, self.width, self.height):
            raise ValueError("Raster dimensions/MIME do not match its image header")
        return self


def image_header(data: bytes) -> tuple[str, int, int]:
    """Read supported image dimensions without optional GIS/image dependencies.

    Import preparation additionally decodes complete images with Pillow. This
    zero-dependency guard protects direct rendering of serialized model inputs.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24 and data[12:16] == b"IHDR":
        return "image/png", int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data.startswith(b"\xff\xd8"):
        offset = 2
        while offset + 4 <= len(data):
            if data[offset] != 255:
                break
            while offset < len(data) and data[offset] == 255:
                offset += 1
            if offset >= len(data):
                break
            marker = data[offset]
            offset += 1
            if marker in (0xD8, 0xD9, 1) or 0xD0 <= marker <= 0xD7:
                continue
            if offset + 2 > len(data):
                break
            length = int.from_bytes(data[offset : offset + 2], "big")
            if length < 2 or offset + length > len(data):
                break
            if (
                marker
                in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF)
                and length >= 7
            ):
                return (
                    "image/jpeg",
                    int.from_bytes(data[offset + 5 : offset + 7], "big"),
                    int.from_bytes(data[offset + 3 : offset + 5], "big"),
                )
            offset += length
    if len(data) >= 30 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        kind = data[12:16]
        if kind == b"VP8X":
            return (
                "image/webp",
                1 + int.from_bytes(data[24:27], "little"),
                1 + int.from_bytes(data[27:30], "little"),
            )
        if kind == b"VP8 " and data[23:26] == b"\x9d\x01\x2a":
            return (
                "image/webp",
                int.from_bytes(data[26:28], "little") & 0x3FFF,
                int.from_bytes(data[28:30], "little") & 0x3FFF,
            )
        if kind == b"VP8L" and data[20] == 0x2F:
            bits = int.from_bytes(data[21:25], "little")
            return "image/webp", 1 + (bits & 0x3FFF), 1 + ((bits >> 14) & 0x3FFF)
    raise ValueError("Unsupported or malformed raster image header")
