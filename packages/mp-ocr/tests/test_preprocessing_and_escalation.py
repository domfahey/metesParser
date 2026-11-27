"""Unit tests for OCR image preprocessing, image-capable clients, page location, and escalation."""

from __future__ import annotations

import base64
import builtins
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from mp_models import CheckResult, ClosureResult, DeedCall, LLMStageRecord, Tract, TractType
from mp_ocr import (
    CachedLLMClient,
    CourseDisagreement,
    EscalationReport,
    GeminiClient,
    OpenAIClient,
    OpenRouterClient,
    PDFProcessor,
    compare_call_readings,
    count_pdf_pages,
    parse_located_pages,
    preprocess_pdf_pages_for_ocr,
    render_pdf_pages_to_pngs,
    select_escalation_outcome,
    should_escalate_closure,
    strip_green_watermark_and_crop,
    validate_escalation_policy,
)
from pypdf import PdfWriter

# Minimal valid 1x1 PNG payloads (keep non-vision tests independent of Pillow/NumPy).
_TINY_PNG_A = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg=="
)
_TINY_PNG_B = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABAABJzQnCgAAAABJRU5ErkJggg=="
)


def _write_tiny_png(path: Path, *, alt: bool = False) -> Path:
    path.write_bytes(_TINY_PNG_B if alt else _TINY_PNG_A)
    return path


def _write_blank_pdf(path: Path, n_pages: int, *, width: float = 612, height: float = 792) -> Path:
    writer = PdfWriter()
    for _ in range(n_pages):
        writer.add_blank_page(width=width, height=height)
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def _make_synthetic_watermarked_png(path: Path) -> Path:
    """Create a white canvas with dark black ink and a green diagonal watermark."""
    np = pytest.importorskip("numpy")
    Image = pytest.importorskip("PIL.Image")
    arr = np.full((300, 300, 3), 255, dtype=np.uint8)
    arr[110:160, 100:200] = [15, 15, 15]
    arr[90:130, 80:220] = [155, 205, 155]
    arr[115:125, 110:190] = [30, 55, 30]
    Image.fromarray(arr, mode="RGB").save(path)
    return path


def _closure(
    *,
    passed: bool,
    status: str = "passed",
    reason: str = "within_tolerance",
    misclosure_ft: float = 0.0,
    with_check: bool = True,
    extra_checks: list[CheckResult] | None = None,
) -> ClosureResult:
    checks = (
        [
            CheckResult(
                name="traverse_closure",
                status=status,  # type: ignore[arg-type]
                reason=reason,
                detail="test",
            )
        ]
        if with_check
        else []
    )
    if extra_checks:
        checks.extend(extra_checks)
    return ClosureResult(
        misclosure_x_ft=misclosure_ft,
        misclosure_y_ft=0.0,
        misclosure_ft=misclosure_ft,
        area_sq_ft=10000.0,
        area_acres=10000.0 / 43560.0,
        perimeter_ft=400.0,
        closure_passed=passed,
        angle_check_passed=passed,
        curve_consistency_passed=True,
        checks=checks,
    )


def _call(
    course: int,
    *,
    direction: str = "N 0°00'00\" E",
    az: float | None = 0.0,
    dist: float | None = 100.0,
    curve_dir: str | None = None,
    curve_type: str | None = None,
    radius_ft: float | None = None,
    arc_length_ft: float | None = None,
    delta_deg: float | None = None,
    chord_length_ft: float | None = None,
    chord_bearing: str | None = None,
    radial_bearing: str | None = None,
    non_tangent: bool = False,
    is_exception: bool = False,
    is_tie_in: bool = False,
    is_meander: bool = False,
    is_indefinite: bool = False,
) -> DeedCall:
    return DeedCall(
        course=course,
        direction_text=direction,
        bearing_azimuth_deg_from_north=az,
        distance_ft=dist,
        curve_dir=curve_dir,  # type: ignore[arg-type]
        curve_type=curve_type,  # type: ignore[arg-type]
        radius_ft=radius_ft,
        arc_length_ft=arc_length_ft,
        delta_deg=delta_deg,
        chord_length_ft=chord_length_ft,
        chord_bearing=chord_bearing,
        radial_bearing=radial_bearing,
        non_tangent=non_tangent,
        is_exception=is_exception,
        is_tie_in=is_tie_in,
        is_meander=is_meander,
        is_indefinite=is_indefinite,
    )


# ---------------------------------------------------------------------------
# Preprocessing tests
# ---------------------------------------------------------------------------


class TestPreprocessing:
    def test_count_pdf_pages_and_missing_file(self, tmp_path: Path) -> None:
        pdf = _write_blank_pdf(tmp_path / "sample.pdf", 3)
        assert count_pdf_pages(pdf) == 3
        with pytest.raises(FileNotFoundError):
            count_pdf_pages(tmp_path / "missing.pdf")
        with pytest.raises(ValueError, match="regular file"):
            count_pdf_pages(tmp_path)

    def test_strip_green_watermark_and_crop_suppresses_green_and_preserves_ink(
        self, tmp_path: Path
    ) -> None:
        np = pytest.importorskip("numpy")
        Image = pytest.importorskip("PIL.Image")
        src = _make_synthetic_watermarked_png(tmp_path / "raw.png")
        dst = tmp_path / "clean.png"
        out = strip_green_watermark_and_crop(src, dst, crop_margins=False)
        assert out == dst
        with Image.open(dst) as img:
            clean = np.array(img)
        assert clean.ndim == 2
        assert int(clean[95, 90]) >= 245
        assert int(clean[120, 150]) < 90
        assert int(clean[145, 150]) < 40

    def test_strip_green_watermark_crops_margins_inclusive_and_fast_path(
        self, tmp_path: Path
    ) -> None:
        np = pytest.importorskip("numpy")
        Image = pytest.importorskip("PIL.Image")
        # Exact 10x10 ink block at [20:30, 20:30] -> margin_pad_px=0 must keep exact 10x10 size
        arr = np.full((100, 100, 3), 255, dtype=np.uint8)
        arr[20:30, 20:30] = [10, 10, 10]
        src = tmp_path / "block.png"
        Image.fromarray(arr, mode="RGB").save(src)

        exact_crop = strip_green_watermark_and_crop(
            src,
            tmp_path / "exact.png",
            strip_watermark=False,
            crop_margins=True,
            margin_pad_px=0,
            max_dim=500,
        )
        with Image.open(exact_crop) as img:
            assert img.size == (10, 10)

        # Narrow-margin ink starting at pixel 4 (inside old 3.5% exclusion band) is never amputated
        narrow = np.full((300, 300, 3), 255, dtype=np.uint8)
        narrow[4:16, 4:24] = [20, 20, 20]
        narrow[280:296, 270:296] = [180, 180, 180]  # faint gray text near bottom-right edge
        narrow_src = tmp_path / "narrow.png"
        Image.fromarray(narrow, mode="RGB").save(narrow_src)
        narrow_out = strip_green_watermark_and_crop(
            narrow_src,
            tmp_path / "narrow_clean.png",
            strip_watermark=True,
            crop_margins=True,
            margin_pad_px=0,
            max_dim=500,
        )
        with Image.open(narrow_out) as img:
            assert img.size == (292, 292)

        # Fast-path grayscale thumbnail without watermark strip or margin crop
        fast = strip_green_watermark_and_crop(
            src,
            tmp_path / "fast.png",
            strip_watermark=False,
            crop_margins=False,
            max_dim=50,
        )
        with Image.open(fast) as img:
            assert img.mode == "L"
            assert img.size == (50, 50)

    def test_strip_green_watermark_validation_errors(self, tmp_path: Path) -> None:
        src = _write_tiny_png(tmp_path / "raw.png")
        with pytest.raises(ValueError, match="max_dim"):
            strip_green_watermark_and_crop(src, tmp_path / "o.png", max_dim=0)
        with pytest.raises(ValueError, match="max_dim"):
            strip_green_watermark_and_crop(src, tmp_path / "o.png", max_dim=True)
        with pytest.raises(ValueError, match="margin_pad_px"):
            strip_green_watermark_and_crop(src, tmp_path / "o.png", margin_pad_px=-1)
        with pytest.raises(ValueError, match="watermark_green_delta"):
            strip_green_watermark_and_crop(src, tmp_path / "o.png", watermark_green_delta=False)

        # Missing optional vision deps raises actionable ImportError
        orig_import = builtins.__import__

        def _block_vision(name: str, *args: Any, **kwargs: Any) -> Any:
            if name in ("PIL", "numpy") or name.startswith("PIL."):
                raise ImportError(name)
            return orig_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_block_vision):
            with pytest.raises(ImportError, match=r"mp-ocr\[vision\]"):
                strip_green_watermark_and_crop(src, tmp_path / "o.png")

    def test_strip_green_watermark_missing_file_and_max_pixels_guard(self, tmp_path: Path) -> None:
        np = pytest.importorskip("numpy")
        Image = pytest.importorskip("PIL.Image")
        with pytest.raises(FileNotFoundError):
            strip_green_watermark_and_crop(tmp_path / "missing.png", tmp_path / "o.png")

        # Decompression-bomb / oversized pixel count rejected before decoding
        big = tmp_path / "big.png"
        Image.fromarray(np.full((400, 400), 255, dtype=np.uint8), mode="L").save(big)
        with pytest.raises(ValueError, match="exceeds max_pixels"):
            strip_green_watermark_and_crop(big, tmp_path / "o.png", max_pixels=100_000)

    def test_render_pdf_pages_validation_and_missing_pdftoppm(self, tmp_path: Path) -> None:
        pdf = _write_blank_pdf(tmp_path / "two.pdf", 2)
        with pytest.raises(ValueError, match="dpi"):
            render_pdf_pages_to_pngs(pdf, tmp_path / "out", dpi=0)
        with pytest.raises(ValueError, match="dpi"):
            render_pdf_pages_to_pngs(pdf, tmp_path / "out", dpi=601)
        with pytest.raises(ValueError, match="dpi"):
            render_pdf_pages_to_pngs(pdf, tmp_path / "out", dpi=True)
        with pytest.raises(ValueError, match="timeout_s"):
            render_pdf_pages_to_pngs(pdf, tmp_path / "out", timeout_s=0)
        with pytest.raises(ValueError, match="timeout_s"):
            render_pdf_pages_to_pngs(pdf, tmp_path / "out", timeout_s=float("nan"))
        with pytest.raises(ValueError, match="empty"):
            render_pdf_pages_to_pngs(pdf, tmp_path / "out", pages=[])
        with pytest.raises(ValueError, match="page"):
            render_pdf_pages_to_pngs(pdf, tmp_path / "out", pages=[True])
        with pytest.raises(ValueError, match="out of range"):
            render_pdf_pages_to_pngs(pdf, tmp_path / "out", pages=[3])
        with patch("mp_ocr.preprocessing.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="pdftoppm"):
                render_pdf_pages_to_pngs(pdf, tmp_path / "out")

    def test_render_pdf_resolves_dash_prefixed_path_batches_and_caps_oversized_dpi(
        self, tmp_path: Path
    ) -> None:
        # 36" x 48" survey plat (2592 x 3456 pt) at 300 DPI would exceed 150M pixels
        plat = _write_blank_pdf(tmp_path / "-plat.pdf", 4, width=2592, height=3456)
        out_dir = tmp_path / "out"
        seen_cmds: list[list[str]] = []

        def _fake_run(cmd: list[str], **kwargs: Any) -> SimpleNamespace:
            seen_cmds.append(cmd)
            f_idx = cmd.index("-f")
            l_idx = cmd.index("-l")
            prefix = Path(cmd[-1])
            for p in range(int(cmd[f_idx + 1]), int(cmd[l_idx + 1]) + 1):
                prefix.with_name(f"{prefix.name}-{p:04d}.png").write_bytes(b"\x89PNG")
            return SimpleNamespace(returncode=0)

        with (
            patch("mp_ocr.preprocessing.shutil.which", return_value="/usr/bin/pdftoppm"),
            patch("mp_ocr.preprocessing.subprocess.run", side_effect=_fake_run),
        ):
            pngs = render_pdf_pages_to_pngs(
                plat, out_dir, pages=[1, 2, 4], dpi=300, max_render_pixels=10_000_000
            )

        assert len(pngs) == 3
        # Pages [1, 2] batched together, [4] separate -> 2 pdftoppm calls
        assert len(seen_cmds) == 2
        assert seen_cmds[0][seen_cmds[0].index("-f") + 1] == "1"
        assert seen_cmds[0][seen_cmds[0].index("-l") + 1] == "2"
        assert seen_cmds[1][seen_cmds[1].index("-f") + 1] == "4"
        assert seen_cmds[1][seen_cmds[1].index("-l") + 1] == "4"
        # Absolute resolved path never starts with '-'
        assert not seen_cmds[0][-2].startswith("-")
        # Effective DPI capped well below 300 for 36"x48" page under 10M pixel budget
        eff_dpi = int(seen_cmds[0][seen_cmds[0].index("-r") + 1])
        assert 1 <= eff_dpi < 100

    def test_render_pdf_wraps_timeout_and_nonzero_exit(self, tmp_path: Path) -> None:
        pdf = _write_blank_pdf(tmp_path / "one.pdf", 1)
        with (
            patch("mp_ocr.preprocessing.shutil.which", return_value="/usr/bin/pdftoppm"),
            patch(
                "mp_ocr.preprocessing.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["pdftoppm"], timeout=5.0),
            ),
        ):
            with pytest.raises(RuntimeError, match="timed out"):
                render_pdf_pages_to_pngs(pdf, tmp_path / "out", timeout_s=5.0)

        with (
            patch("mp_ocr.preprocessing.shutil.which", return_value="/usr/bin/pdftoppm"),
            patch(
                "mp_ocr.preprocessing.subprocess.run",
                side_effect=subprocess.CalledProcessError(
                    returncode=1, cmd=["pdftoppm"], stderr=b"corrupt xref table"
                ),
            ),
        ):
            with pytest.raises(RuntimeError, match="corrupt xref table"):
                render_pdf_pages_to_pngs(pdf, tmp_path / "out")

    def test_render_pdf_zero_pages_and_missing_output(self, tmp_path: Path) -> None:
        empty_pdf = _write_blank_pdf(tmp_path / "empty.pdf", 0)
        with pytest.raises(ValueError, match="no pages"):
            render_pdf_pages_to_pngs(empty_pdf, tmp_path / "out")

        pdf = _write_blank_pdf(tmp_path / "one.pdf", 1)
        with (
            patch("mp_ocr.preprocessing.shutil.which", return_value="/usr/bin/pdftoppm"),
            patch("mp_ocr.preprocessing.subprocess.run"),
        ):
            with pytest.raises(RuntimeError, match="produced 0 PNG"):
                render_pdf_pages_to_pngs(pdf, tmp_path / "out")

    @pytest.mark.skipif(shutil.which("pdftoppm") is None, reason="pdftoppm not installed")
    def test_preprocess_pdf_pages_for_ocr_real_pdftoppm(self, tmp_path: Path) -> None:
        pytest.importorskip("numpy")
        pytest.importorskip("PIL.Image")
        pdf = _write_blank_pdf(tmp_path / "three.pdf", 3)
        pngs = preprocess_pdf_pages_for_ocr(pdf, tmp_path / "work", pages=[2], dpi=72)
        assert len(pngs) == 1
        assert pngs[0].exists()
        # Raw intermediate directory is cleaned up after preprocessing
        assert not (tmp_path / "work" / "raw").exists()
        # Second call into same output_dir uses unique prefix without deleting first call's PNG
        pngs_again = preprocess_pdf_pages_for_ocr(pdf, tmp_path / "work", pages=[2], dpi=72)
        assert len(pngs_again) == 1
        assert pngs[0].exists() and pngs_again[0].exists()
        assert pngs[0] != pngs_again[0]

    def test_render_pdf_rejects_oversized_mediabox_and_excessive_page_count(
        self, tmp_path: Path
    ) -> None:
        # Giant MediaBox (100000 x 100000 pt) exceeds max_render_pixels even at 1 DPI -> fails closed
        giant = _write_blank_pdf(tmp_path / "giant.pdf", 1, width=100_000, height=100_000)
        with patch("mp_ocr.preprocessing.shutil.which", return_value="/usr/bin/pdftoppm"):
            with pytest.raises(ValueError, match="even at 1 DPI"):
                render_pdf_pages_to_pngs(
                    giant, tmp_path / "out", dpi=300, max_render_pixels=1_000_000
                )

        # Page count exceeding max_pages fails closed
        five = _write_blank_pdf(tmp_path / "five.pdf", 5)
        with pytest.raises(ValueError, match="exceeding max_pages"):
            render_pdf_pages_to_pngs(five, tmp_path / "out", max_pages=3)

    def test_render_pdf_respects_user_unit_and_cleans_all_raw_pngs_on_failure(
        self, tmp_path: Path
    ) -> None:
        from pypdf.generic import FloatObject, NameObject

        # 18" x 24" MediaBox with /UserUnit 4.0 -> effective 72" x 96" engineering plat
        writer = PdfWriter()
        page = writer.add_blank_page(width=1296, height=1728)
        page[NameObject("/UserUnit")] = FloatObject(4.0)
        uu_pdf = tmp_path / "user_unit.pdf"
        with uu_pdf.open("wb") as handle:
            writer.write(handle)

        seen_dpis: list[int] = []

        def _fake_run(cmd: list[str], **kwargs: Any) -> SimpleNamespace:
            seen_dpis.append(int(cmd[cmd.index("-r") + 1]))
            prefix = Path(cmd[-1])
            prefix.with_name(f"{prefix.name}-1.png").write_bytes(b"\x89PNG")
            return SimpleNamespace(returncode=0)

        with (
            patch("mp_ocr.preprocessing.shutil.which", return_value="/usr/bin/pdftoppm"),
            patch("mp_ocr.preprocessing.subprocess.run", side_effect=_fake_run),
        ):
            render_pdf_pages_to_pngs(
                uu_pdf, tmp_path / "out_uu", dpi=300, max_render_pixels=10_000_000
            )
        # 72" x 96" = 6912 sq in -> max DPI <= floor(sqrt(10e6 / 6912)) = 38 (strictly < 40)
        assert len(seen_dpis) == 1
        assert 1 <= seen_dpis[0] <= 38

        # Invalid /UserUnit <= 0 fails closed
        bad_writer = PdfWriter()
        bad_page = bad_writer.add_blank_page(width=612, height=792)
        bad_page[NameObject("/UserUnit")] = FloatObject(0.0)
        bad_pdf = tmp_path / "bad_uu.pdf"
        with bad_pdf.open("wb") as handle:
            bad_writer.write(handle)
        with patch("mp_ocr.preprocessing.shutil.which", return_value="/usr/bin/pdftoppm"):
            with pytest.raises(ValueError, match="UserUnit"):
                render_pdf_pages_to_pngs(bad_pdf, tmp_path / "out_bad")

        # Mid-loop failure in preprocess_pdf_pages_for_ocr unlinks ALL raw PNGs and removes raw_dir
        raw_dir = tmp_path / "fail_work" / "raw"
        raw_dir.mkdir(parents=True)
        r1 = _write_tiny_png(raw_dir / "p1.png")
        r2 = _write_tiny_png(raw_dir / "p2.png")
        r3 = _write_tiny_png(raw_dir / "p3.png")
        with (
            patch("mp_ocr.preprocessing.render_pdf_pages_to_pngs", return_value=[r1, r2, r3]),
            patch(
                "mp_ocr.preprocessing.strip_green_watermark_and_crop",
                side_effect=[tmp_path / "c1.png", RuntimeError("boom on page 2")],
            ),
        ):
            with pytest.raises(RuntimeError, match="boom on page 2"):
                preprocess_pdf_pages_for_ocr(uu_pdf, tmp_path / "fail_work")
        assert not r1.exists() and not r2.exists() and not r3.exists()
        assert not raw_dir.exists()


# ---------------------------------------------------------------------------
# Image-capable LLM clients & cache tests
# ---------------------------------------------------------------------------


class TestClientImages:
    def test_openai_client_generate_text_with_images_and_validation(self, tmp_path: Path) -> None:
        img = _write_tiny_png(tmp_path / "page.png")
        mock_sdk = MagicMock()
        mock_sdk.responses.create.return_value = SimpleNamespace(output_text="EXTRACTED")
        with patch("openai.OpenAI", return_value=mock_sdk):
            client = OpenAIClient(api_key="test-key", model="gpt-5.2")
        out = client.generate_text_with_images(
            "Read page", [img], response_mime_type="application/json"
        )
        assert out == "EXTRACTED"
        kwargs = mock_sdk.responses.create.call_args.kwargs
        assert kwargs["input"][0]["content"][0]["type"] == "input_image"
        assert kwargs["input"][0]["content"][1] == {"type": "input_text", "text": "Read page"}
        assert kwargs["text"] == {"format": {"type": "json_object"}}

        with pytest.raises(TypeError, match="sequence of image paths"):
            client.generate_text_with_images("Read", str(img))  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="sequence of image paths"):
            client.generate_text_with_images("Read", img)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="at least one image"):
            client.generate_text_with_images("Read", [])
        bad_img = tmp_path / "bad.tiff"
        bad_img.write_bytes(b"123")
        with pytest.raises(ValueError, match="Unsupported image format"):
            client.generate_text_with_images("Read", [bad_img])
        empty_png = tmp_path / "empty.png"
        empty_png.write_bytes(b"")
        with pytest.raises(ValueError, match="empty"):
            client.generate_text_with_images("Read", [empty_png])
        with pytest.raises(FileNotFoundError):
            client.generate_text_with_images("Read", [tmp_path / "missing.png"])
        with pytest.raises(ValueError, match="regular file"):
            client.generate_text_with_images("Read", [tmp_path])

    def test_openrouter_client_generate_text_with_images(self, tmp_path: Path) -> None:
        img = _write_tiny_png(tmp_path / "page.png")
        mock_sdk = MagicMock()
        mock_sdk.chat.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content="OR_TEXT"), finish_reason="stop")
            ]
        )
        with patch("openai.OpenAI", return_value=mock_sdk):
            client = OpenRouterClient(
                api_key="or-key",
                model="anthropic/claude-haiku-5.5",
                fallback_model=None,
                pdf_engine="mistral-ocr",
            )
        out = client.generate_text_with_images("Read page", [img])
        assert out == "OR_TEXT"
        kwargs = mock_sdk.chat.completions.create.call_args.kwargs
        assert kwargs["messages"][0]["content"][0]["type"] == "image_url"
        assert "plugins" not in kwargs.get("extra_body", {})
        with pytest.raises(ValueError, match="at least one image"):
            client.generate_text_with_images("Read", [])

    def test_gemini_client_generate_text_with_images(self, tmp_path: Path) -> None:
        img = _write_tiny_png(tmp_path / "page.png")
        client = object.__new__(GeminiClient)
        fake_types = SimpleNamespace(
            Content=lambda role, parts: {"role": role, "parts": parts},
            Part=SimpleNamespace(
                from_bytes=lambda data, mime_type: ("bytes", mime_type, len(data)),
                from_text=lambda text: ("text", text),
            ),
        )
        object.__setattr__(client, "_types", fake_types)
        with patch.object(GeminiClient, "_generate", return_value="GEM_TEXT") as gen:
            out = client.generate_text_with_images("Read page", [img])
        assert out == "GEM_TEXT"
        contents = gen.call_args.args[0]
        assert contents[0]["parts"][0][0] == "bytes"
        assert contents[0]["parts"][0][1] == "image/png"
        assert contents[0]["parts"][1] == ("text", "Read page")
        with pytest.raises(ValueError, match="at least one image"):
            client.generate_text_with_images("Read", [])

    def test_cached_client_generate_text_with_images_caches_and_checks_capability_first(
        self, tmp_path: Path
    ) -> None:
        img1 = _write_tiny_png(tmp_path / "p1.png")
        img2 = _write_tiny_png(tmp_path / "p2.png", alt=True)

        calls: list[str] = []

        class _ImgStub:
            model = "stub-img"

            def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
                return "txt"

            def generate_text_with_pdf(
                self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
            ) -> str:
                return "pdf"

            def generate_text_with_images(
                self,
                prompt: str,
                image_paths: list[Path],
                *,
                response_mime_type: str | None = None,
            ) -> str:
                calls.append(",".join(Path(p).name for p in image_paths))
                return f"img-out-{len(calls)}"

        cached = CachedLLMClient(_ImgStub(), tmp_path / "cache")
        assert cached.generate_text_with_images("P", [img1]) == "img-out-1"
        assert cached.generate_text_with_images("P", [img1]) == "img-out-1"
        assert cached.generate_text_with_images("P", [img2]) == "img-out-2"
        assert len(calls) == 2

        with pytest.raises(TypeError, match="sequence of image paths"):
            cached.generate_text_with_images("P", str(img1))  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="at least one image"):
            cached.generate_text_with_images("P", [])

        class _NoImgStub:
            model = "stub-img"

            def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
                return ""

            def generate_text_with_pdf(
                self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
            ) -> str:
                return ""

        # Even if cache already contains a matching key (or path is missing), capability check runs first
        cached_no_img = CachedLLMClient(_NoImgStub(), tmp_path / "cache")
        with pytest.raises(NotImplementedError, match="generate_text_with_images"):
            cached_no_img.generate_text_with_images("P", [img1])
        with pytest.raises(NotImplementedError, match="generate_text_with_images"):
            cached_no_img.generate_text_with_images("P", [tmp_path / "nonexistent.png"])


# ---------------------------------------------------------------------------
# Page locator & image extraction tests
# ---------------------------------------------------------------------------


class TestPageLocatorAndImageExtraction:
    def test_parse_located_pages_variants_and_fallbacks(self) -> None:
        assert parse_located_pages('{"pages": [6, 5, 6, 99, 0, true]}', 6) == [5, 6]
        assert parse_located_pages('```JSON\n{"pages": [2, 3]}\n```', 5) == [2, 3]
        assert parse_located_pages("[2, 4]", 4) == [2, 4]
        assert parse_located_pages("not json", 4) == [1, 2, 3, 4]
        assert parse_located_pages('{"pages": "bad"}', 3) == [1, 2, 3]
        assert parse_located_pages('{"pages": []}', 3) == [1, 2, 3]

    def test_locate_legal_description_pages_shortcuts_small_pdf_and_batches_large_pdf(
        self, tmp_path: Path
    ) -> None:
        two_pdf = _write_blank_pdf(tmp_path / "two.pdf", 2)

        class _NoCallClient:
            def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
                raise AssertionError("should not call LLM")

            def generate_text_with_pdf(
                self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
            ) -> str:
                raise AssertionError("should not call LLM")

        proc = PDFProcessor(client=_NoCallClient(), cache=False)
        assert proc.locate_legal_description_pages(str(two_pdf)) == [1, 2]

        # Batching across 5 pages with max_pages_per_batch=2 -> 3 batches ([1,2], [3,4], [5])
        five_pdf = _write_blank_pdf(tmp_path / "five.pdf", 5)
        fake_thumbs = [tmp_path / f"t{i}.png" for i in range(1, 6)]
        batch_sizes: list[int] = []
        replies = ['{"pages": [2]}', '{"pages": [1]}', '{"pages": [1]}']

        class _BatchLocatorClient:
            def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
                return ""

            def generate_text_with_pdf(
                self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
            ) -> str:
                return ""

            def generate_text_with_images(
                self, prompt: str, image_paths: Any, *, response_mime_type: str | None = None
            ) -> str:
                batch_sizes.append(len(image_paths))
                return replies.pop(0)

        b_proc = PDFProcessor(client=_BatchLocatorClient(), cache=False)
        with patch("mp_ocr.extract.preprocess_pdf_pages_for_ocr", return_value=fake_thumbs):
            pages = b_proc.locate_legal_description_pages(
                str(five_pdf), max_pages_per_batch=2, audit=True
            )
        assert batch_sizes == [2, 2, 1]
        assert pages == [2, 3, 5]
        assert len(b_proc.pop_audit_stage_records()) == 3

    def test_extract_text_from_images_batches_large_inputs(self, tmp_path: Path) -> None:
        imgs = [tmp_path / f"p{i}.png" for i in range(5)]

        class _BatchImgClient:
            def __init__(self) -> None:
                self.batches: list[int] = []

            def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
                return ""

            def generate_text_with_pdf(
                self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
            ) -> str:
                return ""

            def generate_text_with_images(
                self, prompt: str, image_paths: Any, *, response_mime_type: str | None = None
            ) -> str:
                self.batches.append(len(image_paths))
                return f"CHUNK_{len(self.batches)}"

        client = _BatchImgClient()
        proc = PDFProcessor(client=client, cache=False)
        out = proc.extract_text_from_images(imgs, audit=True, max_images_per_call=2)
        assert client.batches == [2, 2, 1]
        assert out == "CHUNK_1\n\nCHUNK_2\n\nCHUNK_3"
        assert len(proc.pop_audit_stage_records()) == 3

    def test_extract_legal_description_from_images_preserves_locator_audit_records(
        self, tmp_path: Path
    ) -> None:
        pdf = _write_blank_pdf(tmp_path / "five.pdf", 5)
        fake_png = _write_tiny_png(tmp_path / "p5.png")

        s2_text = "(1) North 32 degrees 36 minutes 00 seconds West, 143.00 feet."
        s3_swapped = "(1) N 32°36'00\" W, 999.00 feet."

        class _LocatorStub:
            model = "haiku-locator"

            def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
                return ""

            def generate_text_with_pdf(
                self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
            ) -> str:
                return ""

            def generate_text_with_images(
                self, prompt: str, image_paths: Any, *, response_mime_type: str | None = None
            ) -> str:
                return '{"pages": [5]}'

        class _EscStub:
            model = "sonnet-esc"

            def __init__(self, norm_reply: str) -> None:
                self.text_replies = [s2_text, norm_reply]

            def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
                return self.text_replies.pop(0)

            def generate_text_with_pdf(
                self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
            ) -> str:
                return ""

            def generate_text_with_images(
                self, prompt: str, image_paths: Any, *, response_mime_type: str | None = None
            ) -> str:
                return "EXHIBIT A\n" + s2_text

        locator = PDFProcessor(client=_LocatorStub(), cache=False)
        existing_stage = LLMStageRecord(
            stage="primary_stage",
            prompt="p",
            prompt_sha256="a" * 64,
            response="r",
            response_sha256="b" * 64,
            provider="unknown",
            model="haiku-locator",
        )
        locator._audit_stage_records = [existing_stage]
        esc_proc = PDFProcessor(client=_EscStub(s3_swapped), cache=False)

        with patch("mp_ocr.extract.preprocess_pdf_pages_for_ocr", return_value=[fake_png]):
            legal, norm, pages = esc_proc.extract_legal_description_from_images(
                str(pdf), audit=True, locator_processor=locator
            )

        assert pages == [5]
        assert legal == s2_text
        assert norm == s2_text
        # Pre-existing locator audit records must be restored untouched, never stolen!
        assert locator._audit_stage_records == [existing_stage]
        stages = esc_proc.pop_audit_stage_records()
        assert [s.stage for s in stages] == [
            "locate_legal_pages",
            "escalation_extract_text_from_images",
            "escalation_extract_legal_description",
            "escalation_normalize_text",
        ]
        assert esc_proc.pop_audit_stage_records() == []

        # Clean normalization path succeeds and preserves normalized text
        s3_clean = "(1) N 32°36'00\" W, 143.00 feet."
        esc_clean = PDFProcessor(client=_EscStub(s3_clean), cache=False)
        with patch("mp_ocr.extract.preprocess_pdf_pages_for_ocr", return_value=[fake_png]):
            _, norm_ok, explicit_pages = esc_clean.extract_legal_description_from_images(
                str(pdf), pages=[5, 5], audit=False
            )
        assert explicit_pages == [5]
        assert norm_ok == s3_clean

        # Client without generate_text_with_images raises NotImplementedError and clears audit
        class _NoImg:
            def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
                return ""

            def generate_text_with_pdf(
                self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
            ) -> str:
                return ""

        bad_proc = PDFProcessor(client=_NoImg(), cache=False)
        with patch("mp_ocr.extract.preprocess_pdf_pages_for_ocr", return_value=[fake_png]):
            with pytest.raises(NotImplementedError):
                bad_proc.extract_legal_description_from_images(str(pdf), pages=[1], audit=True)
        assert bad_proc.pop_audit_stage_records() == []

    def test_extract_legal_description_from_images_retries_all_pages_on_empty_subset(
        self, tmp_path: Path
    ) -> None:
        pdf = _write_blank_pdf(tmp_path / "seven.pdf", 7)
        fake_png = _write_tiny_png(tmp_path / "p.png")
        good_legal = "(1) North 32 degrees 36 minutes 00 seconds West, 143.00 feet."
        good_norm = "(1) N 32°36'00\" W, 143.00 feet."

        class _RetryStub:
            model = "retry-stub"

            def __init__(self) -> None:
                self.image_calls = 0
                self.text_replies = [
                    # Stage 2 on subset [1, 2, 7] has no legal signals -> Stage 3 skipped!
                    "No legal description found on these pages.",
                    good_legal,
                    good_norm,
                ]

            def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
                return self.text_replies.pop(0)

            def generate_text_with_pdf(
                self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
            ) -> str:
                return ""

            def generate_text_with_images(
                self, prompt: str, image_paths: Any, *, response_mime_type: str | None = None
            ) -> str:
                self.image_calls += 1
                if response_mime_type == "application/json":
                    return '{"pages": [1, 2, 7]}'
                return "RAW"

        seen_page_lists: list[list[int] | None] = []

        def _fake_preprocess(
            pdf_path: Any, out_dir: Path, *, pages: Any = None, **kwargs: Any
        ) -> list[Path]:
            seen_page_lists.append(list(pages) if pages is not None else None)
            if pages is None:
                return [fake_png] * 7
            return [fake_png for _ in pages]

        proc = PDFProcessor(client=_RetryStub(), cache=False)
        with patch("mp_ocr.extract.preprocess_pdf_pages_for_ocr", side_effect=_fake_preprocess):
            legal, norm, resolved_pages = proc.extract_legal_description_from_images(
                str(pdf), audit=True
            )

        assert resolved_pages == [1, 2, 3, 4, 5, 6, 7]
        assert legal == good_legal
        assert norm == good_norm
        # Reuses rendered pages [1, 2, 7] and renders only missing pages [3, 4, 5, 6] on fallback!
        assert seen_page_lists == [None, [1, 2, 7], [3, 4, 5, 6]]
        stages = proc.pop_audit_stage_records()
        assert "escalation_fallback_extract_text_from_images" in [s.stage for s in stages]
        assert "escalation_normalize_text" not in [s.stage for s in stages]

    def test_locate_legal_pages_multi_batch_does_not_expand_empty_batch(
        self, tmp_path: Path
    ) -> None:
        pdf = _write_blank_pdf(tmp_path / "twenty.pdf", 20)
        fake_png = _write_tiny_png(tmp_path / "t.png")
        replies = iter(['{"pages": []}', '{"pages": [2]}'])

        class _MultiBatchStub:
            def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
                return ""

            def generate_text_with_pdf(
                self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
            ) -> str:
                return ""

            def generate_text_with_images(
                self, prompt: str, image_paths: Any, *, response_mime_type: str | None = None
            ) -> str:
                return next(replies)

        proc = PDFProcessor(client=_MultiBatchStub(), cache=False)
        with patch(
            "mp_ocr.extract.preprocess_pdf_pages_for_ocr",
            return_value=[fake_png] * 20,
        ):
            pages = proc.locate_legal_description_pages(str(pdf), max_pages_per_batch=16)
        # First batch returned {"pages": []} -> NOT expanded to 1..16; only page 18 returned!
        assert pages == [18]

        # If ALL batches return empty, fall back to all pages 1..20
        empty_replies = iter(['{"pages": []}', '{"pages": []}'])
        proc_empty = PDFProcessor(
            client=SimpleNamespace(
                generate_text=lambda *a, **k: "",
                generate_text_with_pdf=lambda *a, **k: "",
                generate_text_with_images=lambda *a, **k: next(empty_replies),
            ),
            cache=False,
        )
        with patch(
            "mp_ocr.extract.preprocess_pdf_pages_for_ocr",
            return_value=[fake_png] * 20,
        ):
            assert proc_empty.locate_legal_description_pages(
                str(pdf), max_pages_per_batch=16
            ) == list(range(1, 21))


# ---------------------------------------------------------------------------
# Escalation policy & disagreement comparison tests
# ---------------------------------------------------------------------------


class TestEscalationPolicyAndDisagreement:
    def test_validate_policy_and_should_escalate_closure_policies(self) -> None:
        assert validate_escalation_policy("unverified") == "unverified"
        with pytest.raises(ValueError, match="Invalid escalation_policy"):
            validate_escalation_policy("always")
        with pytest.raises(ValueError, match="Invalid escalation_policy"):
            should_escalate_closure(_closure(passed=False, status="failed"), policy="bogus")  # type: ignore[arg-type]

        passed = _closure(passed=True, status="passed")
        failed = _closure(
            passed=False, status="failed", reason="misclosure_exceeds_tolerance", misclosure_ft=0.8
        )
        blocked = _closure(
            passed=False, status="blocked", reason="missing_bearings", misclosure_ft=0.0
        )
        closed_but_bad_curve = _closure(
            passed=True,
            status="passed",
            extra_checks=[
                CheckResult(
                    name="curve_consistency",
                    status="failed",
                    reason="curve_inconsistent",
                    detail="arc != R*delta",
                )
            ],
        )
        closed_but_inferred_roles = _closure(
            passed=True,
            status="passed",
            extra_checks=[
                CheckResult(
                    name="description_roles_inferred",
                    status="blocked",
                    reason="roles_inferred",
                    detail="inferred role",
                )
            ],
        )
        legacy_fail = _closure(passed=False, misclosure_ft=1.2, with_check=False)

        assert should_escalate_closure(failed, policy="never") == (False, [])
        assert should_escalate_closure(failed, policy="unverified", has_calls=False) == (False, [])
        assert should_escalate_closure([], policy="unverified") == (False, [])
        assert should_escalate_closure(passed, policy="closure_failed") == (False, [])
        assert should_escalate_closure(passed, policy="unverified") == (False, [])

        ok_f, reasons_f = should_escalate_closure(failed, policy="closure_failed")
        assert ok_f is True and "traverse_closure failed" in reasons_f[0]

        assert should_escalate_closure(blocked, policy="closure_failed") == (False, [])
        ok_b, reasons_b = should_escalate_closure(blocked, policy="unverified")
        assert ok_b is True and "traverse_closure blocked" in reasons_b[0]

        # Non-closure check failures/blocks trigger under "unverified" even when closure passed
        assert should_escalate_closure(closed_but_bad_curve, policy="closure_failed") == (False, [])
        ok_c, reasons_c = should_escalate_closure(closed_but_bad_curve, policy="unverified")
        assert ok_c is True and any("curve_consistency failed" in r for r in reasons_c)

        ok_r, reasons_r = should_escalate_closure(closed_but_inferred_roles, policy="unverified")
        assert ok_r is True and any("description_roles_inferred blocked" in r for r in reasons_r)

        ok_leg, _ = should_escalate_closure([passed, legacy_fail], policy="closure_failed")
        assert ok_leg is True

    def test_compare_call_readings_tight_tolerances_and_all_semantic_fields(self) -> None:
        # Tight circular wrap within 1e-4 deg and 1e-4 ft agrees
        c1 = _call(1, direction="N 0°00'00\" E", az=0.00004, dist=100.0)
        c1_wrap = _call(1, direction="N 0°00'00\" W", az=359.99996, dist=100.00005)
        assert compare_call_readings([c1], [c1_wrap]) == []

        # Small 0.02 ft or 2' (~0.033 deg) OCR fix MUST be reported as a disagreement (not masked!)
        c_small_dist = _call(1, az=0.0, dist=100.02)
        c_small_az = _call(1, az=2.0 / 60.0, dist=100.0)
        assert len(compare_call_readings([c1], [c_small_dist])) == 1
        assert len(compare_call_readings([c1], [c_small_az])) == 1

        # Cardinal-only direction_text difference when both azimuths are None
        c_card_a = _call(1, direction="Northerly", az=None, dist=100.0)
        c_card_b = _call(1, direction="Southerly", az=None, dist=100.0)
        card_diffs = compare_call_readings([c_card_a], [c_card_b])
        assert len(card_diffs) == 1 and "direction_text" in card_diffs[0].details[0]

        # Full curve + semantic flag differences
        c_full_a = _call(
            2,
            direction="N 45°00'00\" E",
            az=45.0,
            dist=146.44,
            curve_dir="right",
            curve_type="simple",
            radius_ft=565.45,
            arc_length_ft=304.57,
            delta_deg=30.0,
            chord_length_ft=300.0,
            chord_bearing="N 60°00'00\" E",
            radial_bearing="S 45°00'00\" E",
            non_tangent=False,
            is_exception=False,
            is_tie_in=False,
            is_meander=False,
            is_indefinite=False,
        )
        c_full_b = _call(
            3,
            direction="S 19°58'30\" W",
            az=199.975,
            dist=145.44,
            curve_dir="left",
            curve_type="spiral",
            radius_ft=560.0,
            arc_length_ft=300.0,
            delta_deg=31.0,
            chord_length_ft=295.0,
            chord_bearing="S 10°00'00\" W",
            radial_bearing="N 20°00'00\" W",
            non_tangent=True,
            is_exception=True,
            is_tie_in=True,
            is_meander=True,
            is_indefinite=True,
        )
        diffs = compare_call_readings([c1, c_full_a], [c1, c_full_b, _call(4)])
        assert diffs[0].kind == "call_count"
        assert "call count" in diffs[0].format_warning()
        assert diffs[1].kind == "value_mismatch"
        assert diffs[1].course == 2
        joined = "; ".join(diffs[1].details)
        for token in (
            "course_num",
            "distance_ft",
            "bearing",
            "curve_dir",
            "curve_type",
            "radius_ft",
            "arc_length_ft",
            "delta_deg",
            "chord_length_ft",
            "chord_bearing",
            "radial_bearing",
            "non_tangent",
            "is_exception",
            "is_tie_in",
            "is_meander",
            "is_indefinite",
        ):
            assert token in joined

    def test_compare_call_readings_multi_tract_structure_and_metadata(self) -> None:
        t1_pri = Tract(
            label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=[_call(1)]
        )
        t2_pri = Tract(
            label="Tract 2",
            tract_type=TractType.EXCEPTION,
            role_basis="heading",
            calls=[_call(1, dist=50.0)],
        )
        t1_esc = Tract(
            label="Tract 1",
            tract_type=TractType.EASEMENT,
            role_basis="inferred",
            calls=[_call(1, dist=105.0)],
        )
        diffs = compare_call_readings(
            [c for t in (t1_pri, t2_pri) for c in t.calls],
            t1_esc.calls,
            primary_tracts=[t1_pri, t2_pri],
            escalated_tracts=[t1_esc],
        )
        kinds = [d.kind for d in diffs]
        assert kinds == ["tract_count", "tract_metadata", "value_mismatch"]
        assert "tract count" in diffs[0].format_warning()
        assert "(Tract 1)" in diffs[1].format_warning()
        assert "(Tract 1)" in diffs[2].format_warning()

    def test_select_escalation_outcome_all_branches_and_truncation_guards(self) -> None:
        c_pri = [_call(1, dist=299.09), _call(2, dist=100.0)]
        c_esc = [_call(1, dist=299.89), _call(2, dist=100.0)]
        dis = compare_call_readings(c_pri, c_esc)
        passed = _closure(passed=True, status="passed")
        failed = _closure(passed=False, status="failed", misclosure_ft=0.8)

        assert select_escalation_outcome(
            primary_calls=c_pri,
            escalated_calls=[],
            primary_results=failed,
            escalated_results=failed,
            disagreements=dis,
        ) == ("primary", "escalated_empty_fallback_to_primary")

        # Dropped tracts guard (C1)
        t1 = Tract(
            label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=[c_pri[0]]
        )
        t2 = Tract(
            label="Tract 2", tract_type=TractType.MAIN, role_basis="heading", calls=[c_pri[1]]
        )
        assert select_escalation_outcome(
            primary_calls=c_pri,
            escalated_calls=c_esc,
            primary_results=[failed, failed],
            escalated_results=[passed],
            disagreements=dis,
            primary_tracts=[t1, t2],
            escalated_tracts=[t1],
        ) == ("primary", "escalated_dropped_tracts_fallback_to_primary")

        # Truncated calls guard (C1)
        assert select_escalation_outcome(
            primary_calls=c_pri,
            escalated_calls=[c_esc[0]],
            primary_results=failed,
            escalated_results=passed,
            disagreements=dis,
        ) == ("primary", "escalated_truncated_calls_fallback_to_primary")

        # Agreement confirms primary
        assert select_escalation_outcome(
            primary_calls=c_pri,
            escalated_calls=c_pri,
            primary_results=failed,
            escalated_results=failed,
            disagreements=[],
        ) == ("primary", "readings_agree_confirmed_by_escalation")

        # Escalated passes where primary failed
        assert select_escalation_outcome(
            primary_calls=c_pri,
            escalated_calls=c_esc,
            primary_results=failed,
            escalated_results=passed,
            disagreements=dis,
        ) == ("escalated", "escalated_passed_closure_where_primary_failed")

        # Escalated regressed a closed tract -> keep primary
        assert select_escalation_outcome(
            primary_calls=c_pri,
            escalated_calls=c_esc,
            primary_results=[passed, failed],
            escalated_results=[failed, failed],
            disagreements=dis,
        ) == ("primary", "primary_preserved_escalated_regressed_verification")

        # Partial multi-tract improvement without regressing any tract
        assert select_escalation_outcome(
            primary_calls=c_pri,
            escalated_calls=c_esc,
            primary_results=[failed, failed],
            escalated_results=[passed, failed],
            disagreements=dis,
        ) == ("escalated", "escalated_improved_closure_with_disagreement_warning")

        # Both failed closure -> select high-DPI with disagreement warning
        assert select_escalation_outcome(
            primary_calls=c_pri,
            escalated_calls=c_esc,
            primary_results=failed,
            escalated_results=failed,
            disagreements=dis,
        ) == ("escalated", "escalated_high_dpi_selected_with_disagreement_warning")

        report = EscalationReport(
            triggered=True,
            policy="closure_failed",
            disagreements=tuple(dis),
            selected="escalated",
            selection_reason="escalated_passed_closure_where_primary_failed",
        )
        assert len(report.review_warnings) == 1
        assert isinstance(report.disagreements[0], CourseDisagreement)

    def test_red_team_selection_and_comparison_guards(self) -> None:
        c1 = _call(1, az=0.0, dist=100.0)
        c2 = _call(2, az=90.0, dist=100.0)
        c2_alt = _call(2, az=90.0, dist=101.0)
        dis = compare_call_readings([c1, c2], [c1, c2_alt])
        assert len(dis) == 1

        # 1. Unverified policy triggers on unresolved warnings even when closure_passed=True
        warned_closed = _closure(passed=True, status="passed").model_copy(
            update={"warnings": ["exception not applied: easterly 10 feet"]}
        )
        esc_warn, reasons_warn = should_escalate_closure(warned_closed, policy="unverified")
        assert esc_warn is True and any("warnings" in r for r in reasons_warn)

        # 2. Catastrophically regressed unclosed pass (lost misclosure_available / worse misclosure)
        pri_near = _closure(passed=False, status="failed", misclosure_ft=0.02).model_copy(
            update={"confidence_score": 0.79}
        )
        esc_garbled = _closure(passed=False, status="blocked", misclosure_ft=0.0).model_copy(
            update={"misclosure_available": False, "confidence_score": 0.38}
        )
        assert select_escalation_outcome(
            primary_calls=[c1, c2],
            escalated_calls=[c1, c2_alt],
            primary_results=pri_near,
            escalated_results=esc_garbled,
            disagreements=dis,
        ) == ("primary", "primary_preserved_escalated_regressed_verification")

        # 3. Pairwise multi-tract regression: [closed, failed] -> [failed, closed] breaks T1 -> keep primary
        closed_ok = _closure(passed=True, status="passed")
        failed_bad = _closure(passed=False, status="failed", misclosure_ft=0.5)
        assert select_escalation_outcome(
            primary_calls=[c1, c2],
            escalated_calls=[c1, c2_alt],
            primary_results=[closed_ok, failed_bad],
            escalated_results=[failed_bad, closed_ok],
            disagreements=dis,
        ) == ("primary", "primary_preserved_escalated_regressed_verification")

        # 4. Adding a warning to a previously clean tract is treated as a regression
        assert select_escalation_outcome(
            primary_calls=[c1, c2],
            escalated_calls=[c1, c2_alt],
            primary_results=[closed_ok, failed_bad],
            escalated_results=[warned_closed, closed_ok],
            disagreements=dis,
        ) == ("primary", "primary_preserved_escalated_regressed_verification")

        # 5. Per-tract call truncation [4->6, 4->2] caught even when total calls are equal
        t1_pri = Tract(label="T1", tract_type=TractType.MAIN, role_basis="heading", calls=[c1, c2])
        t2_pri = Tract(label="T2", tract_type=TractType.MAIN, role_basis="heading", calls=[c1, c2])
        t1_esc = Tract(
            label="T1", tract_type=TractType.MAIN, role_basis="heading", calls=[c1, c2, c2_alt]
        )
        t2_esc = Tract(label="T2", tract_type=TractType.MAIN, role_basis="heading", calls=[c1])
        assert select_escalation_outcome(
            primary_calls=[c1, c2, c1, c2],
            escalated_calls=[c1, c2, c2_alt, c1],
            primary_results=[failed_bad, failed_bad],
            escalated_results=[closed_ok, closed_ok],
            disagreements=dis,
            primary_tracts=[t1_pri, t2_pri],
            escalated_tracts=[t1_esc, t2_esc],
        ) == ("primary", "escalated_truncated_calls_fallback_to_primary")

        # 6. Equivalent chord_bearing formatting & tangent-less curve direction_text produce zero false disagreements
        curve_pri = _call(
            1,
            direction="curving to the right, chord N 45°00'00\" E",
            az=None,
            dist=50.0,
            curve_dir="right",
            radius_ft=100.0,
            arc_length_ft=50.0,
            chord_bearing="N 45°00'00\" E",
        )
        curve_esc = _call(
            1,
            direction="curve right along chord North 45 degrees East",
            az=None,
            dist=50.0,
            curve_dir="right",
            radius_ft=100.0,
            arc_length_ft=50.0,
            chord_bearing="North 45 degrees East",
        )
        assert compare_call_readings([curve_pri], [curve_esc]) == []

        # 7. Dropped call.notes, stated_area_sq_ft, and skipped_courses surface as disagreements
        noted_pri = c1.model_copy(update={"notes": "exception not applied: easterly 10 ft"})
        dis_meta = compare_call_readings(
            [noted_pri],
            [c1],
            primary_stated_area_sq_ft=10000.0,
            escalated_stated_area_sq_ft=9500.0,
            primary_skipped_courses=["c5"],
            escalated_skipped_courses=[],
        )
        assert any("stated_area_sq_ft" in ";".join(d.details) for d in dis_meta)
        assert any("skipped_courses" in ";".join(d.details) for d in dis_meta)
        assert any("notes:" in ";".join(d.details) for d in dis_meta)

        # 8. Reclassifying a conveyed boundary tract as an easement/exception cannot fake closure
        t_main_1 = Tract(label="T1", tract_type=TractType.MAIN, role_basis="heading", calls=[c1])
        t_main_2 = Tract(label="T2", tract_type=TractType.MAIN, role_basis="heading", calls=[c2])
        t_ease_2 = Tract(
            label="T2", tract_type=TractType.EASEMENT, role_basis="heading", calls=[c2_alt]
        )
        ease_failed = _closure(
            passed=False,
            status="failed",
            misclosure_ft=0.5,
            extra_checks=[
                CheckResult(
                    name="non_boundary_tract",
                    status="blocked",
                    reason="non_boundary",
                    detail="easement",
                )
            ],
        )
        assert select_escalation_outcome(
            primary_calls=[c1, c2],
            escalated_calls=[c1, c2_alt],
            primary_results=[closed_ok, failed_bad],
            escalated_results=[closed_ok, ease_failed],
            disagreements=dis,
            primary_tracts=[t_main_1, t_main_2],
            escalated_tracts=[t_main_1, t_ease_2],
        ) == ("primary", "primary_preserved_escalated_regressed_verification")

        # 9. Sole-easement and mixed MAIN+EASEMENT regressions preserve primary
        ease_closed = _closure(
            passed=True,
            status="passed",
            extra_checks=[
                CheckResult(
                    name="non_boundary_tract",
                    status="blocked",
                    reason="non_boundary",
                    detail="easement",
                )
            ],
        )
        assert select_escalation_outcome(
            primary_calls=[c1, c2],
            escalated_calls=[c1, c2_alt],
            primary_results=[ease_closed],
            escalated_results=[ease_failed],
            disagreements=dis,
            primary_tracts=[t_ease_2],
            escalated_tracts=[t_ease_2],
        ) == ("primary", "primary_preserved_escalated_regressed_verification")

        ease_near = ease_failed.model_copy(update={"misclosure_ft": 0.02, "confidence_score": 0.75})
        ease_garbled = ease_failed.model_copy(
            update={"misclosure_available": False, "confidence_score": 0.30}
        )
        assert select_escalation_outcome(
            primary_calls=[c1, c2],
            escalated_calls=[c1, c2_alt],
            primary_results=[ease_near],
            escalated_results=[ease_garbled],
            disagreements=dis,
            primary_tracts=[t_ease_2],
            escalated_tracts=[t_ease_2],
        ) == ("primary", "primary_preserved_escalated_regressed_verification")

        assert select_escalation_outcome(
            primary_calls=[c1, c2],
            escalated_calls=[c1, c2_alt],
            primary_results=[failed_bad, ease_closed],
            escalated_results=[closed_ok, ease_failed],
            disagreements=dis,
            primary_tracts=[t_main_1, t_ease_2],
            escalated_tracts=[t_main_1, t_ease_2],
        ) == ("primary", "primary_preserved_escalated_regressed_verification")

        # 10. Bare cardinal & invalid DMS bearings are never folded into exact azimuths
        c_bare_card = _call(1, chord_bearing="North")
        c_due_north = _call(1, chord_bearing="Due North")
        c_n0e = _call(1, chord_bearing="N 0°00'00\" E")
        assert len(compare_call_readings([c_bare_card], [c_due_north])) == 1
        assert len(compare_call_readings([c_bare_card], [c_n0e])) == 1
        assert compare_call_readings([c_due_north], [c_n0e]) == []

        c_bad_min = _call(1, chord_bearing="N 45°60'00\" E")
        c_bad_dec_min = _call(1, chord_bearing="N 45.5°30'00\" E")
        c_46e = _call(1, chord_bearing="N 46°00'00\" E")
        assert len(compare_call_readings([c_bad_min], [c_46e])) == 1
        assert len(compare_call_readings([c_bad_dec_min], [c_46e])) == 1
