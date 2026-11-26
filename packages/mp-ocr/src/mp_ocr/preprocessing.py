"""Deterministic PDF page rendering, green-watermark removal, and margin cropping.

Prepares clean high-resolution grayscale PNGs for blind escalation OCR passes
without modifying or interpreting source deed measurements.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pypdf import PdfReader


def count_pdf_pages(pdf_path: str | Path) -> int:
    """Return the 1-based page count of *pdf_path* using ``pypdf``."""
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found at {pdf_path}")
    reader = PdfReader(str(path))
    return len(reader.pages)


def render_pdf_pages_to_pngs(
    pdf_path: str | Path,
    output_dir: Path,
    *,
    dpi: int = 300,
    pages: Sequence[int] | None = None,
) -> list[Path]:
    """Render selected 1-based pages (or all pages) of *pdf_path* to PNGs via ``pdftoppm``."""
    if dpi <= 0:
        raise ValueError("dpi must be a positive integer")
    path = Path(pdf_path)
    total_pages = count_pdf_pages(path)
    if total_pages == 0:
        raise ValueError(f"PDF has no pages: {pdf_path}")

    if pages is None:
        selected = list(range(1, total_pages + 1))
    else:
        selected = sorted(dict.fromkeys(int(p) for p in pages))
        if not selected:
            raise ValueError("pages must not be empty when explicitly provided")
        invalid = [p for p in selected if p < 1 or p > total_pages]
        if invalid:
            raise ValueError(f"Requested page(s) {invalid} out of range 1..{total_pages}")

    pdftoppm_bin = shutil.which("pdftoppm")
    if pdftoppm_bin is None:
        raise RuntimeError(
            "pdftoppm is required to render PDF pages to PNG images. "
            "Install Poppler (e.g., `brew install poppler` or `apt-get install poppler-utils`)."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[Path] = []
    for page_num in selected:
        prefix = output_dir / f"page_{page_num:04d}"
        # Clear any stale files matching this prefix before rendering.
        for stale in output_dir.glob(f"page_{page_num:04d}-*.png"):
            stale.unlink()
        subprocess.run(
            [
                pdftoppm_bin,
                "-png",
                "-r",
                str(dpi),
                "-f",
                str(page_num),
                "-l",
                str(page_num),
                str(path),
                str(prefix),
            ],
            check=True,
            capture_output=True,
        )
        matches = sorted(output_dir.glob(f"page_{page_num:04d}-*.png"))
        if not matches:
            raise RuntimeError(
                f"pdftoppm produced no PNG output for page {page_num} of {path.name}"
            )
        rendered.append(matches[0])
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
    if max_dim <= 0:
        raise ValueError("max_dim must be a positive integer")
    if margin_pad_px < 0:
        raise ValueError("margin_pad_px must be non-negative")

    try:
        import numpy as np
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - optional image deps
        raise ImportError("Pillow and numpy are required for OCR image preprocessing.") from exc

    img: Any = Image.open(image_path).convert("RGB")
    arr: Any = np.array(img, dtype=np.int16)
    r = arr[:, :, 0]
    g = arr[:, :, 1]
    b = arr[:, :, 2]

    gray = np.round(0.299 * r + 0.587 * g + 0.114 * b).astype(np.int16)
    clean = gray.copy()

    if strip_watermark:
        green_mask = (g - np.maximum(r, b)) > watermark_green_delta
        g_boosted = np.clip((g - 20) * (255.0 / 165.0), 0, 255).astype(np.int16)
        clean[green_mask] = g_boosted[green_mask]

    if crop_margins:
        height, width = clean.shape
        x0_lim, x1_lim = int(width * 0.07), int(width * 0.93)
        y0_lim, y1_lim = int(height * 0.04), int(height * 0.95)
        if x1_lim > x0_lim and y1_lim > y0_lim:
            inner = clean[y0_lim:y1_lim, x0_lim:x1_lim]
            dark = inner < 180
            row_has = dark.sum(axis=1) >= 8
            col_has = dark.sum(axis=0) >= 8
            if row_has.any() and col_has.any():
                ry = np.where(row_has)[0]
                cx = np.where(col_has)[0]
                top = max(0, y0_lim + int(ry[0]) - margin_pad_px)
                bot = min(height, y0_lim + int(ry[-1]) + margin_pad_px)
                left = max(0, x0_lim + int(cx[0]) - margin_pad_px)
                right = min(width, x0_lim + int(cx[-1]) + margin_pad_px)
                clean = clean[top:bot, left:right]

    out_img: Any = Image.fromarray(clean.astype(np.uint8), mode="L")
    if max(out_img.size) > max_dim:
        out_img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
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
) -> list[Path]:
    """Render and preprocess selected PDF pages into clean grayscale PNGs."""
    raw_dir = output_dir / "raw"
    clean_dir = output_dir / "clean"
    raw_pngs = render_pdf_pages_to_pngs(pdf_path, raw_dir, dpi=dpi, pages=pages)
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
