"""Unit tests for OCR image preprocessing, image-capable clients, page location, and escalation."""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from mp_models import CheckResult, ClosureResult, DeedCall
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
    preprocess_pdf_pages_for_ocr,
    render_pdf_pages_to_pngs,
    select_escalation_outcome,
    should_escalate_closure,
    strip_green_watermark_and_crop,
)
from mp_ocr.extract import _parse_located_pages
from PIL import Image
from pypdf import PdfWriter


def _write_blank_pdf(path: Path, n_pages: int) -> Path:
    writer = PdfWriter()
    for _ in range(n_pages):
        writer.add_blank_page(width=612, height=792)
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def _make_synthetic_watermarked_png(path: Path) -> Path:
    """Create a white canvas with dark black ink and a green diagonal watermark."""
    arr = np.full((300, 300, 3), 255, dtype=np.uint8)
    # Dark text block in the center
    arr[110:160, 100:200] = [15, 15, 15]
    # Pure green watermark band overlapping both paper and text
    arr[90:130, 80:220] = [155, 205, 155]
    # Dark ink under green watermark (alpha blended dark green)
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
    radius_ft: float | None = None,
    arc_length_ft: float | None = None,
) -> DeedCall:
    return DeedCall(
        course=course,
        direction_text=direction,
        bearing_azimuth_deg_from_north=az,
        distance_ft=dist,
        curve_dir=curve_dir,  # type: ignore[arg-type]
        radius_ft=radius_ft,
        arc_length_ft=arc_length_ft,
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

    def test_strip_green_watermark_and_crop_suppresses_green_and_preserves_ink(
        self, tmp_path: Path
    ) -> None:
        src = _make_synthetic_watermarked_png(tmp_path / "raw.png")
        dst = tmp_path / "clean.png"
        out = strip_green_watermark_and_crop(src, dst, crop_margins=False)
        assert out == dst
        clean = np.array(Image.open(dst))
        assert clean.ndim == 2
        # Pure green watermark over paper should become bright white (>= 245)
        assert int(clean[95, 90]) >= 245
        # Dark ink under green watermark should stay clearly dark (< 90)
        assert int(clean[120, 150]) < 90
        # Unwatermarked dark ink stays dark
        assert int(clean[145, 150]) < 40

    def test_strip_green_watermark_crops_margins_and_caps_max_dim(self, tmp_path: Path) -> None:
        src = _make_synthetic_watermarked_png(tmp_path / "raw.png")
        cropped = strip_green_watermark_and_crop(
            src, tmp_path / "cropped.png", strip_watermark=True, crop_margins=True, max_dim=120
        )
        w, h = Image.open(cropped).size
        assert max(w, h) <= 120
        assert w < 300 and h < 300

    def test_strip_green_watermark_validation_errors(self, tmp_path: Path) -> None:
        src = _make_synthetic_watermarked_png(tmp_path / "raw.png")
        with pytest.raises(ValueError, match="max_dim"):
            strip_green_watermark_and_crop(src, tmp_path / "o.png", max_dim=0)
        with pytest.raises(ValueError, match="margin_pad_px"):
            strip_green_watermark_and_crop(src, tmp_path / "o.png", margin_pad_px=-1)

    def test_render_pdf_pages_validation_and_missing_pdftoppm(self, tmp_path: Path) -> None:
        pdf = _write_blank_pdf(tmp_path / "two.pdf", 2)
        with pytest.raises(ValueError, match="dpi"):
            render_pdf_pages_to_pngs(pdf, tmp_path / "out", dpi=0)
        with pytest.raises(ValueError, match="empty"):
            render_pdf_pages_to_pngs(pdf, tmp_path / "out", pages=[])
        with pytest.raises(ValueError, match="out of range"):
            render_pdf_pages_to_pngs(pdf, tmp_path / "out", pages=[3])
        with patch("mp_ocr.preprocessing.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="pdftoppm"):
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
            with pytest.raises(RuntimeError, match="no PNG output"):
                render_pdf_pages_to_pngs(pdf, tmp_path / "out")

    @pytest.mark.skipif(shutil.which("pdftoppm") is None, reason="pdftoppm not installed")
    def test_preprocess_pdf_pages_for_ocr_real_pdftoppm(self, tmp_path: Path) -> None:
        pdf = _write_blank_pdf(tmp_path / "three.pdf", 3)
        pngs = preprocess_pdf_pages_for_ocr(pdf, tmp_path / "work", pages=[2], dpi=72)
        assert len(pngs) == 1
        assert pngs[0].exists()
        # Re-running cleans stale files cleanly
        pngs_again = preprocess_pdf_pages_for_ocr(pdf, tmp_path / "work", pages=[2], dpi=72)
        assert len(pngs_again) == 1


# ---------------------------------------------------------------------------
# Image-capable LLM clients & cache tests
# ---------------------------------------------------------------------------


class TestClientImages:
    def test_openai_client_generate_text_with_images(self, tmp_path: Path) -> None:
        img = _make_synthetic_watermarked_png(tmp_path / "page.png")
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
        with pytest.raises(ValueError, match="at least one image"):
            client.generate_text_with_images("Read", [])
        bad_img = tmp_path / "bad.tiff"
        bad_img.write_bytes(b"123")
        with pytest.raises(ValueError, match="Unsupported image format"):
            client.generate_text_with_images("Read", [bad_img])
        with pytest.raises(FileNotFoundError):
            client.generate_text_with_images("Read", [tmp_path / "missing.png"])

    def test_openrouter_client_generate_text_with_images(self, tmp_path: Path) -> None:
        img = _make_synthetic_watermarked_png(tmp_path / "page.png")
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
        # pdf_engine plugin must NOT be attached for image_url calls
        assert "plugins" not in kwargs.get("extra_body", {})
        with pytest.raises(ValueError, match="at least one image"):
            client.generate_text_with_images("Read", [])

    def test_gemini_client_generate_text_with_images(self, tmp_path: Path) -> None:
        img = _make_synthetic_watermarked_png(tmp_path / "page.png")
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

    def test_cached_client_generate_text_with_images_caches_by_content(
        self, tmp_path: Path
    ) -> None:
        img1 = _make_synthetic_watermarked_png(tmp_path / "p1.png")
        img2 = tmp_path / "p2.png"
        Image.fromarray(np.zeros((10, 10, 3), dtype=np.uint8)).save(img2)

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

        with pytest.raises(ValueError, match="at least one image"):
            cached.generate_text_with_images("P", [])

        class _NoImgStub:
            def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
                return ""

            def generate_text_with_pdf(
                self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
            ) -> str:
                return ""

        cached_no_img = CachedLLMClient(_NoImgStub(), tmp_path / "cache2")
        with pytest.raises(NotImplementedError, match="generate_text_with_images"):
            cached_no_img.generate_text_with_images("P", [img1])


# ---------------------------------------------------------------------------
# Page locator & image extraction tests
# ---------------------------------------------------------------------------


class TestPageLocatorAndImageExtraction:
    def test_parse_located_pages_variants_and_fallbacks(self) -> None:
        assert _parse_located_pages('{"pages": [6, 5, 6, 99, 0, true]}', 6) == [5, 6]
        assert _parse_located_pages('```json\n{"pages": [2, 3]}\n```', 5) == [2, 3]
        assert _parse_located_pages("[2, 4]", 4) == [2, 4]
        assert _parse_located_pages("not json", 4) == [1, 2, 3, 4]
        assert _parse_located_pages('{"pages": "bad"}', 3) == [1, 2, 3]
        assert _parse_located_pages('{"pages": []}', 3) == [1, 2, 3]

    def test_locate_legal_description_pages_shortcuts_small_pdf(self, tmp_path: Path) -> None:
        pdf = _write_blank_pdf(tmp_path / "two.pdf", 2)

        class _NoCallClient:
            def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
                raise AssertionError("should not call LLM")

            def generate_text_with_pdf(
                self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
            ) -> str:
                raise AssertionError("should not call LLM")

        proc = PDFProcessor(client=_NoCallClient(), cache=False)
        assert proc.locate_legal_description_pages(str(pdf)) == [1, 2]

    def test_extract_legal_description_from_images_blind_and_audited(self, tmp_path: Path) -> None:
        pdf = _write_blank_pdf(tmp_path / "five.pdf", 5)
        fake_png = _make_synthetic_watermarked_png(tmp_path / "p5.png")

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
        esc_proc = PDFProcessor(client=_EscStub(s3_swapped), cache=False)

        with patch("mp_ocr.extract.preprocess_pdf_pages_for_ocr", return_value=[fake_png]):
            legal, norm, pages = esc_proc.extract_legal_description_from_images(
                str(pdf), audit=True, locator_processor=locator
            )

        assert pages == [5]
        assert legal == s2_text
        # Stage 3 integrity guard must reject the 999.00 ft drift and preserve Stage 2 text!
        assert norm == s2_text
        assert esc_proc._audit_stage_records is not None
        assert [s.stage for s in esc_proc._audit_stage_records] == [
            "locate_legal_pages",
            "escalation_extract_text_from_images",
            "escalation_extract_legal_description",
            "escalation_normalize_text",
        ]
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
        assert bad_proc._audit_stage_records is None

    def test_extract_legal_description_from_images_retries_all_pages_on_empty_subset(
        self, tmp_path: Path
    ) -> None:
        pdf = _write_blank_pdf(tmp_path / "seven.pdf", 7)
        fake_png = _make_synthetic_watermarked_png(tmp_path / "p.png")
        good_legal = "(1) North 32 degrees 36 minutes 00 seconds West, 143.00 feet."
        good_norm = "(1) N 32°36'00\" W, 143.00 feet."

        class _RetryStub:
            model = "retry-stub"

            def __init__(self) -> None:
                self.image_calls = 0
                self.text_replies = [
                    "No legal description found on these pages.",
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
            return [fake_png]

        proc = PDFProcessor(client=_RetryStub(), cache=False)
        with patch("mp_ocr.extract.preprocess_pdf_pages_for_ocr", side_effect=_fake_preprocess):
            legal, norm, resolved_pages = proc.extract_legal_description_from_images(
                str(pdf), audit=True
            )

        assert resolved_pages == [1, 2, 3, 4, 5, 6, 7]
        assert legal == good_legal
        assert norm == good_norm
        # Call 1 = thumbnails (None), call 2 = located subset [1,2,7], call 3 = all pages 1..7
        assert seen_page_lists == [None, [1, 2, 7], [1, 2, 3, 4, 5, 6, 7]]
        assert proc._audit_stage_records is not None
        assert "escalation_fallback_extract_text_from_images" in [
            s.stage for s in proc._audit_stage_records
        ]


# ---------------------------------------------------------------------------
# Escalation policy & disagreement comparison tests
# ---------------------------------------------------------------------------


class TestEscalationPolicyAndDisagreement:
    def test_should_escalate_closure_policies(self) -> None:
        passed = _closure(passed=True, status="passed")
        failed = _closure(
            passed=False, status="failed", reason="misclosure_exceeds_tolerance", misclosure_ft=0.8
        )
        blocked = _closure(
            passed=False, status="blocked", reason="missing_bearings", misclosure_ft=0.0
        )
        legacy_fail = _closure(passed=False, misclosure_ft=1.2, with_check=False)

        assert should_escalate_closure(failed, policy="never") == (False, [])
        assert should_escalate_closure([], policy="unverified") == (False, [])
        assert should_escalate_closure(passed, policy="closure_failed") == (False, [])
        assert should_escalate_closure(passed, policy="unverified") == (False, [])

        ok_f, reasons_f = should_escalate_closure(failed, policy="closure_failed")
        assert ok_f is True and "traverse_closure failed" in reasons_f[0]

        assert should_escalate_closure(blocked, policy="closure_failed") == (False, [])
        ok_b, reasons_b = should_escalate_closure(blocked, policy="unverified")
        assert ok_b is True and "traverse_closure blocked" in reasons_b[0]

        ok_leg, _ = should_escalate_closure([passed, legacy_fail], policy="closure_failed")
        assert ok_leg is True

    def test_compare_call_readings_all_fields_and_circular_azimuth(self) -> None:
        c1 = _call(1, direction="N 0°00'00\" E", az=0.01, dist=100.0)
        c1_wrap = _call(1, direction="N 0°00'00\" W", az=359.99, dist=100.02)
        assert compare_call_readings([c1], [c1_wrap]) == []

        c_curve_a = _call(
            2,
            direction="N 45°00'00\" E",
            az=45.0,
            dist=146.44,
            curve_dir="right",
            radius_ft=565.45,
            arc_length_ft=304.57,
        )
        c_curve_b = _call(
            2,
            direction="S 19°58'30\" W",
            az=199.975,
            dist=145.44,
            curve_dir="left",
            radius_ft=560.0,
            arc_length_ft=300.0,
        )
        diffs = compare_call_readings([c1, c_curve_a], [c1, c_curve_b, _call(3)])
        assert diffs[0].kind == "call_count"
        assert "call count" in diffs[0].format_warning()
        assert diffs[1].kind == "value_mismatch"
        assert diffs[1].course == 2
        assert len(diffs[1].details) == 5
        assert "course 2" in diffs[1].format_warning()

        # None vs float mismatch on optional fields
        none_straight = _call(1, az=None, dist=50.0, radius_ft=None, arc_length_ft=None)
        none_diffs = compare_call_readings(
            [none_straight],
            [_call(1, az=10.0, dist=50.0, curve_dir="right", radius_ft=20.0, arc_length_ft=15.0)],
        )
        assert len(none_diffs) == 1 and len(none_diffs[0].details) == 4

        spiral_no_dist = DeedCall(
            course=1,
            direction_text="N 0°00'00\" E",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=None,
            curve_dir="right",
            curve_type="spiral",
            radius_ft=100.0,
            delta_deg=10.0,
        )
        dist_none_diffs = compare_call_readings(
            [spiral_no_dist],
            [_call(1, az=0.0, dist=50.0, curve_dir="right", radius_ft=100.0, arc_length_ft=17.45)],
        )
        assert len(dist_none_diffs) == 1 and "distance_ft" in dist_none_diffs[0].details[0]

    def test_select_escalation_outcome_all_branches(self) -> None:
        c_pri = [_call(1, dist=299.09)]
        c_esc = [_call(1, dist=299.89)]
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

        assert select_escalation_outcome(
            primary_calls=c_pri,
            escalated_calls=c_pri,
            primary_results=failed,
            escalated_results=failed,
            disagreements=[],
        ) == ("primary", "readings_agree_confirmed_by_escalation")

        assert select_escalation_outcome(
            primary_calls=c_pri,
            escalated_calls=c_esc,
            primary_results=failed,
            escalated_results=passed,
            disagreements=dis,
        ) == ("escalated", "escalated_passed_closure_where_primary_failed")

        assert select_escalation_outcome(
            primary_calls=c_pri,
            escalated_calls=c_esc,
            primary_results=passed,
            escalated_results=failed,
            disagreements=dis,
        ) == ("primary", "primary_passed_closure_where_escalated_failed")

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
