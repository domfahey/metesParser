"""Deterministic PDF page rendering, green-watermark removal, and margin cropping.

Prepares clean high-resolution grayscale PNGs for blind escalation OCR passes
without modifying or interpreting source deed measurements.
"""

from __future__ import annotations

import math
import shutil
import subprocess
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pypdf import PdfReader

MAX_RENDER_DPI = 600
_MAX_DPI = MAX_RENDER_DPI
_DEFAULT_MAX_RENDER_PIXELS = 40_000_000
DEFAULT_MAX_RENDER_PAGES = 100
_DEFAULT_RENDER_TIMEOUT_S = 60.0
_MAX_TOTAL_RUN_TIMEOUT_S = 600.0


def _validate_int(
    value: object,
    name: str,
    *,
    min_value: int,
    max_value: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer, got {type(value).__name__}")
    if value < min_value:
        raise ValueError(f"{name} must be >= {min_value}, got {value}")
    if max_value is not None and value > max_value:
        raise ValueError(f"{name} must be <= {max_value}, got {value}")
    return value


def validate_render_dpi(dpi: object, *, name: str = "dpi") -> int:
    """Validate render DPI as a non-bool integer within ``1..MAX_RENDER_DPI``."""
    return _validate_int(dpi, name, min_value=1, max_value=MAX_RENDER_DPI)


def validate_pdf_pages(pages: Sequence[int], total_pages: int) -> list[int]:
    """Validate and normalize explicit 1-based page numbers without coercing bool/str."""
    if isinstance(pages, (str, bytes)):
        raise ValueError("pages must be a sequence of 1-based integer page numbers")
    validated_pages = [_validate_int(p, "page", min_value=1) for p in pages]
    selected = sorted(dict.fromkeys(validated_pages))
    if not selected:
        raise ValueError("pages must not be empty when explicitly provided")
    invalid = [p for p in selected if p > total_pages]
    if invalid:
        raise ValueError(f"Requested page(s) {invalid} out of range 1..{total_pages}")
    return selected


def _validate_pdf_file(pdf_path: str | Path) -> Path:
    path = Path(pdf_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"PDF not found at {pdf_path}")
    if not path.is_file():
        raise ValueError(f"PDF path is not a regular file: {pdf_path}")
    return path


def count_pdf_pages(pdf_path: str | Path) -> int:
    """Return the 1-based page count of *pdf_path* using ``pypdf``."""
    path = _validate_pdf_file(pdf_path)
    reader = PdfReader(str(path))
    return len(reader.pages)


def _effective_dpi_for_page(
    reader: PdfReader,
    page_num: int,
    requested_dpi: int,
    max_render_pixels: int,
) -> int:
    """Cap render DPI when oversized plat sheets would exceed *max_render_pixels*.

    Fails closed on unreadable/non-finite mediabox dimensions or pages that still
    exceed *max_render_pixels* even at 1 DPI.
    """
    try:
        page = reader.pages[page_num - 1]
        box = page.mediabox
        raw_w = float(box.width)
        raw_h = float(box.height)
        raw_user_unit = page.get("/UserUnit", 1.0) if hasattr(page, "get") else 1.0
        if hasattr(raw_user_unit, "get_object"):
            raw_user_unit = raw_user_unit.get_object()
        user_unit = float(raw_user_unit)
    except Exception as exc:
        raise ValueError(f"Unreadable PDF mediabox on page {page_num}") from exc
    if (
        not (math.isfinite(raw_w) and math.isfinite(raw_h) and math.isfinite(user_unit))
        or raw_w == 0.0
        or raw_h == 0.0
        or user_unit <= 0.0
    ):
        raise ValueError(
            f"Invalid PDF mediabox dimensions ({raw_w!r}x{raw_h!r} pt, "
            f"UserUnit={user_unit!r}) on page {page_num}"
        )
    width_in = max((abs(raw_w) * user_unit) / 72.0, 0.1)
    height_in = max((abs(raw_h) * user_unit) / 72.0, 0.1)

    def _ceil_pixels(dpi_val: int) -> int:
        # +1 px safety margin per axis for Poppler rounding on fractional inch sizes.
        return (math.ceil(width_in * dpi_val) + 1) * (math.ceil(height_in * dpi_val) + 1)

    if _ceil_pixels(requested_dpi) <= max_render_pixels:
        return requested_dpi
    area_sq_in = width_in * height_in
    capped = int(math.floor(math.sqrt(max_render_pixels / area_sq_in)))
    effective = min(requested_dpi, max(capped, 1))
    while effective > 1 and _ceil_pixels(effective) > max_render_pixels:
        effective -= 1
    if _ceil_pixels(effective) > max_render_pixels:
        raise ValueError(
            f"PDF page {page_num} ({width_in:.1f}x{height_in:.1f} in) exceeds "
            f"max_render_pixels={max_render_pixels} even at 1 DPI"
        )
    return effective


def _group_contiguous_pages(
    pages_with_dpi: Sequence[tuple[int, int]],
) -> list[tuple[int, int, int]]:
    """Group consecutive page numbers sharing an effective DPI into ``(start, end, dpi)`` runs."""
    if not pages_with_dpi:
        return []
    runs: list[tuple[int, int, int]] = []
    start, run_dpi = pages_with_dpi[0]
    end = start
    for page_num, page_dpi in pages_with_dpi[1:]:
        if page_num == end + 1 and page_dpi == run_dpi:
            end = page_num
        else:
            runs.append((start, end, run_dpi))
            start, end, run_dpi = page_num, page_num, page_dpi
    runs.append((start, end, run_dpi))
    return runs


def render_pdf_pages_to_pngs(
    pdf_path: str | Path,
    output_dir: Path,
    *,
    dpi: int = 300,
    pages: Sequence[int] | None = None,
    timeout_s: float = _DEFAULT_RENDER_TIMEOUT_S,
    max_render_pixels: int = _DEFAULT_MAX_RENDER_PIXELS,
    max_pages: int = DEFAULT_MAX_RENDER_PAGES,
    grayscale: bool = False,
) -> list[Path]:
    """Render selected 1-based pages (or all pages) of *pdf_path* to PNGs via ``pdftoppm``."""
    validated_dpi = validate_render_dpi(dpi, name="dpi")
    validated_max_pixels = _validate_int(max_render_pixels, "max_render_pixels", min_value=100_000)
    validated_max_pages = _validate_int(max_pages, "max_pages", min_value=1)
    if (
        isinstance(timeout_s, bool)
        or not isinstance(timeout_s, (int, float))
        or not math.isfinite(timeout_s)
        or timeout_s <= 0
    ):
        raise ValueError("timeout_s must be a positive finite number")

    path = _validate_pdf_file(pdf_path)
    reader = PdfReader(str(path))
    total_pages = len(reader.pages)
    if total_pages == 0:
        raise ValueError(f"PDF has no pages: {pdf_path}")

    if pages is None:
        selected = list(range(1, total_pages + 1))
    else:
        selected = validate_pdf_pages(pages, total_pages)

    if len(selected) > validated_max_pages:
        raise ValueError(
            f"Requested {len(selected)} PDF pages, exceeding max_pages={validated_max_pages}"
        )

    pdftoppm_bin = shutil.which("pdftoppm")
    if pdftoppm_bin is None:
        raise RuntimeError(
            "pdftoppm is required to render PDF pages to PNG images. "
            "Install Poppler (e.g., `brew install poppler` or `apt-get install poppler-utils`)."
        )

    resolved_out = Path(output_dir).resolve()
    resolved_out.mkdir(parents=True, exist_ok=True)

    pages_with_dpi = [
        (p, _effective_dpi_for_page(reader, p, validated_dpi, validated_max_pixels))
        for p in selected
    ]
    runs = _group_contiguous_pages(pages_with_dpi)
    run_token = uuid.uuid4().hex[:8]
    timeout_ceiling = max(float(timeout_s), _MAX_TOTAL_RUN_TIMEOUT_S)
    rendered: list[Path] = []
    for run_start, run_end, run_dpi in runs:
        prefix_name = f"{run_token}_run_{run_start:04d}_{run_end:04d}"
        prefix = resolved_out / prefix_name
        run_timeout = min(float(timeout_s) * max(1, run_end - run_start + 1), timeout_ceiling)
        cmd = [pdftoppm_bin, "-png"]
        if grayscale:
            cmd.append("-gray")
        cmd.extend(
            [
                "-r",
                str(run_dpi),
                "-f",
                str(run_start),
                "-l",
                str(run_end),
                str(path),
                str(prefix),
            ]
        )
        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                timeout=run_timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"pdftoppm timed out after {run_timeout:.1f}s rendering pages "
                f"{run_start}-{run_end} of {path.name}"
            ) from exc
        except subprocess.CalledProcessError as exc:
            stderr_text = (
                exc.stderr.decode("utf-8", errors="replace").strip()[:400]
                if isinstance(exc.stderr, bytes)
                else str(exc.stderr or "").strip()[:400]
            )
            detail = f": {stderr_text}" if stderr_text else ""
            raise RuntimeError(
                f"pdftoppm failed (exit {exc.returncode}) rendering pages "
                f"{run_start}-{run_end} of {path.name}{detail}"
            ) from exc

        matches = sorted(resolved_out.glob(f"{prefix_name}-*.png"))
        expected_count = run_end - run_start + 1
        if len(matches) != expected_count:
            raise RuntimeError(
                f"pdftoppm produced {len(matches)} PNG(s) (expected {expected_count}) "
                f"for pages {run_start}-{run_end} of {path.name}"
            )
        rendered.extend(matches)
    return rendered


def strip_green_watermark_and_crop(
    image_path: Path,
    output_path: Path,
    *,
    strip_watermark: bool = True,
    crop_margins: bool = True,
    max_dim: int = 2200,
    watermark_green_delta: int = 15,
    margin_pad_px: int = 45,
    max_pixels: int = _DEFAULT_MAX_RENDER_PIXELS,
) -> Path:
    """Deterministically strip green diagonal watermarks and crop empty margins.

    Green recording watermarks (e.g., ``"This is not an official document"``)
    have ``G`` significantly brighter than ``R`` and ``B`` over white paper
    while dark printed ink stays dark in ``G``. Replacing strongly green pixels
    with contrast-stretched green-channel luminance suppresses the colored
    overlay while preserving underlying dark text strokes.
    """
    validated_max_dim = _validate_int(max_dim, "max_dim", min_value=1)
    validated_pad = _validate_int(margin_pad_px, "margin_pad_px", min_value=0)
    validated_delta = _validate_int(
        watermark_green_delta, "watermark_green_delta", min_value=0, max_value=255
    )
    validated_max_pixels = _validate_int(max_pixels, "max_pixels", min_value=100_000)

    try:
        import numpy as np
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - optional image deps
        raise ImportError(
            "Pillow and numpy are required for OCR image preprocessing. "
            "Install with: uv sync --extra vision (or pip install 'mp-ocr[vision]')."
        ) from exc

    with Image.open(image_path) as raw_img:
        img_w, img_h = raw_img.size
        if img_w * img_h > validated_max_pixels:
            raise ValueError(
                f"Image {image_path.name} ({img_w}x{img_h} = {img_w * img_h} px) "
                f"exceeds max_pixels={validated_max_pixels}"
            )
        if not strip_watermark and not crop_margins:
            out_img: Any = raw_img.convert("L")
            if max(out_img.size) > validated_max_dim:
                out_img.thumbnail((validated_max_dim, validated_max_dim), Image.Resampling.LANCZOS)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            out_img.save(output_path, optimize=True)
            return output_path
        if not strip_watermark:
            clean: Any = np.array(raw_img.convert("L"), dtype=np.uint8)
        else:
            rgb_img = raw_img if raw_img.mode == "RGB" else raw_img.convert("RGB")
            clean = np.array(rgb_img.convert("L"), dtype=np.uint8)
            arr: Any = np.asarray(rgb_img, dtype=np.uint8)
            r = arr[:, :, 0]
            g = arr[:, :, 1]
            b = arr[:, :, 2]
            max_rb = np.maximum(r, b)
            green_mask = (g > max_rb) & ((g - max_rb) > validated_delta)
            if green_mask.any():
                lut = np.clip(
                    np.arange(256, dtype=np.float32) * (255.0 / 165.0) - (20.0 * 255.0 / 165.0),
                    0.0,
                    255.0,
                ).astype(np.uint8)
                clean[green_mask] = lut[g[green_mask]]
            del arr, r, g, b, max_rb, green_mask

    if crop_margins:
        height, width = clean.shape
        # Inspect the full page (never slice off fixed outer percentage bands) with a
        # generous <215 luminance threshold so narrow margins, shifted text, and faint
        # gray text under stripped watermarks are preserved without truncation.
        dark = clean < 215
        row_has = dark.sum(axis=1) >= 8
        col_has = dark.sum(axis=0) >= 8
        if row_has.any() and col_has.any():
            ry = np.where(row_has)[0]
            cx = np.where(col_has)[0]
            scaled_pad = (
                0
                if validated_pad == 0
                else max(validated_pad, int(round(max(height, width) * 0.015)))
            )
            top = max(0, int(ry[0]) - scaled_pad)
            bot = min(height, int(ry[-1]) + 1 + scaled_pad)
            left = max(0, int(cx[0]) - scaled_pad)
            right = min(width, int(cx[-1]) + 1 + scaled_pad)
            clean = clean[top:bot, left:right]

    out_img = Image.fromarray(clean, mode="L")
    if max(out_img.size) > validated_max_dim:
        out_img.thumbnail((validated_max_dim, validated_max_dim), Image.Resampling.LANCZOS)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_img.save(output_path, optimize=True)
    return output_path


def preprocess_pdf_pages_for_ocr(
    pdf_path: str | Path,
    output_dir: Path,
    *,
    pages: Sequence[int] | None = None,
    dpi: int = 300,
    strip_watermark: bool = True,
    crop_margins: bool = True,
    max_dim: int = 2200,
    timeout_s: float = _DEFAULT_RENDER_TIMEOUT_S,
    max_pages: int = DEFAULT_MAX_RENDER_PAGES,
) -> list[Path]:
    """Render and preprocess selected PDF pages into clean grayscale PNGs."""
    raw_dir = output_dir / "raw"
    clean_dir = output_dir / "clean"
    raw_pngs = render_pdf_pages_to_pngs(
        pdf_path,
        raw_dir,
        dpi=dpi,
        pages=pages,
        timeout_s=timeout_s,
        max_pages=max_pages,
        grayscale=not strip_watermark,
    )
    cleaned: list[Path] = []
    try:
        for raw_png in raw_pngs:
            out_png = clean_dir / raw_png.name
            strip_green_watermark_and_crop(
                raw_png,
                out_png,
                strip_watermark=strip_watermark,
                crop_margins=crop_margins,
                max_dim=max_dim,
            )
            raw_png.unlink(missing_ok=True)
            cleaned.append(out_png)
    finally:
        for raw_png in raw_pngs:
            raw_png.unlink(missing_ok=True)
        try:
            raw_dir.rmdir()
        except OSError:
            pass
    return cleaned
