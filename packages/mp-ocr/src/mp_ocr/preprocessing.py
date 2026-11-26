"""Deterministic PDF page rendering, green-watermark removal, and margin cropping.

Prepares clean high-resolution grayscale PNGs for blind escalation OCR passes
without modifying or interpreting source deed measurements.
"""

from __future__ import annotations

import math
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pypdf import PdfReader

_MAX_DPI = 600
_DEFAULT_MAX_RENDER_PIXELS = 40_000_000
_DEFAULT_RENDER_TIMEOUT_S = 60.0


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
    """Cap render DPI when oversized plat sheets would exceed *max_render_pixels*."""
    try:
        box = reader.pages[page_num - 1].mediabox
        width_in = max(abs(float(box.width)) / 72.0, 0.1)
        height_in = max(abs(float(box.height)) / 72.0, 0.1)
    except Exception:
        return requested_dpi
    area_sq_in = width_in * height_in
    est_pixels = area_sq_in * (requested_dpi**2)
    if est_pixels <= max_render_pixels:
        return requested_dpi
    capped = int(math.floor(math.sqrt(max_render_pixels / area_sq_in)))
    return max(36, min(requested_dpi, capped))


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
) -> list[Path]:
    """Render selected 1-based pages (or all pages) of *pdf_path* to PNGs via ``pdftoppm``."""
    validated_dpi = _validate_int(dpi, "dpi", min_value=1, max_value=_MAX_DPI)
    validated_max_pixels = _validate_int(max_render_pixels, "max_render_pixels", min_value=100_000)
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
        if isinstance(pages, (str, bytes)):
            raise ValueError("pages must be a sequence of 1-based integer page numbers")
        validated_pages = [_validate_int(p, "page", min_value=1) for p in pages]
        selected = sorted(dict.fromkeys(validated_pages))
        if not selected:
            raise ValueError("pages must not be empty when explicitly provided")
        invalid = [p for p in selected if p > total_pages]
        if invalid:
            raise ValueError(f"Requested page(s) {invalid} out of range 1..{total_pages}")

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
    rendered: list[Path] = []
    for run_start, run_end, run_dpi in runs:
        prefix = resolved_out / f"run_{run_start:04d}_{run_end:04d}"
        for stale in resolved_out.glob(f"run_{run_start:04d}_{run_end:04d}-*.png"):
            stale.unlink()
        run_timeout = float(timeout_s) * max(1, run_end - run_start + 1)
        try:
            subprocess.run(
                [
                    pdftoppm_bin,
                    "-png",
                    "-r",
                    str(run_dpi),
                    "-f",
                    str(run_start),
                    "-l",
                    str(run_end),
                    str(path),
                    str(prefix),
                ],
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

        matches = sorted(resolved_out.glob(f"run_{run_start:04d}_{run_end:04d}-*.png"))
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

    try:
        import numpy as np
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - optional image deps
        raise ImportError(
            "Pillow and numpy are required for OCR image preprocessing. "
            "Install with: uv sync --extra vision (or pip install 'mp-ocr[vision]')."
        ) from exc

    with Image.open(image_path) as raw_img:
        if not strip_watermark and not crop_margins:
            out_img: Any = raw_img.convert("L")
            if max(out_img.size) > validated_max_dim:
                out_img.thumbnail((validated_max_dim, validated_max_dim), Image.Resampling.LANCZOS)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            out_img.save(output_path, optimize=True)
            return output_path
        arr: Any = np.array(raw_img.convert("RGB"), dtype=np.int16)

    r = arr[:, :, 0]
    g = arr[:, :, 1]
    b = arr[:, :, 2]

    clean = np.round(
        0.299 * r.astype(np.float32) + 0.587 * g.astype(np.float32) + 0.114 * b.astype(np.float32)
    ).astype(np.uint8)

    if strip_watermark:
        green_mask = (g - np.maximum(r, b)) > validated_delta
        if green_mask.any():
            g_sel = g[green_mask].astype(np.float32)
            clean[green_mask] = np.clip((g_sel - 20.0) * (255.0 / 165.0), 0.0, 255.0).astype(
                np.uint8
            )

    if crop_margins:
        height, width = clean.shape
        # Ignore narrow outer 3.5% binder/punch-hole edges when locating the text block,
        # while expanding inclusively (+1) so outer text rows/columns are never truncated.
        x0_lim, x1_lim = int(width * 0.035), int(width * 0.965)
        y0_lim, y1_lim = int(height * 0.025), int(height * 0.975)
        if x1_lim > x0_lim and y1_lim > y0_lim:
            inner = clean[y0_lim:y1_lim, x0_lim:x1_lim]
            dark = inner < 180
            row_has = dark.sum(axis=1) >= 8
            col_has = dark.sum(axis=0) >= 8
            if row_has.any() and col_has.any():
                ry = np.where(row_has)[0]
                cx = np.where(col_has)[0]
                top = max(0, y0_lim + int(ry[0]) - validated_pad)
                bot = min(height, y0_lim + int(ry[-1]) + 1 + validated_pad)
                left = max(0, x0_lim + int(cx[0]) - validated_pad)
                right = min(width, x0_lim + int(cx[-1]) + 1 + validated_pad)
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
) -> list[Path]:
    """Render and preprocess selected PDF pages into clean grayscale PNGs."""
    raw_dir = output_dir / "raw"
    clean_dir = output_dir / "clean"
    raw_pngs = render_pdf_pages_to_pngs(
        pdf_path, raw_dir, dpi=dpi, pages=pages, timeout_s=timeout_s
    )
    cleaned: list[Path] = []
    for raw_png in raw_pngs:
        out_png = clean_dir / raw_png.name
        strip_green_watermark_and_crop(
            raw_png,
            out_png,
            strip_watermark=strip_watermark,
            crop_margins=crop_margins,
            max_dim=max_dim,
        )
        cleaned.append(out_png)
    return cleaned
