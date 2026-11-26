"""Integration tests for Pipeline closure-triggered blind escalation."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np
from PIL import Image
from pypdf import PdfWriter

from metesparser import Pipeline
from metesparser.pdf_processor import PDFProcessor as MonolithPDFProcessor

_CLOSED_SQUARE = (
    "BEGINNING at a point; "
    "THENCE N 0°00'00\" E 100.00 feet to a point; "
    "THENCE S 90°00'00\" E 100.00 feet to a point; "
    "THENCE S 0°00'00\" W 100.00 feet to a point; "
    "THENCE N 90°00'00\" W 100.00 feet to the point of beginning."
)

_BROKEN_SQUARE = (
    "BEGINNING at a point; "
    "THENCE N 0°00'00\" E 100.00 feet to a point; "
    "THENCE S 90°00'00\" E 100.00 feet to a point; "
    "THENCE S 0°00'00\" W 100.00 feet to a point; "
    "THENCE N 90°00'00\" W 99.00 feet to the point of beginning."
)

_BLOCKED_CARDINAL = (
    "BEGINNING at a point; "
    "THENCE Northerly 100.00 feet to a point; "
    "THENCE Easterly 100.00 feet to the point of beginning."
)


def _make_pdf_and_png(tmp_path: Path, n_pages: int = 3) -> tuple[Path, Path]:
    pdf = tmp_path / "deed.pdf"
    writer = PdfWriter()
    for _ in range(n_pages):
        writer.add_blank_page(width=612, height=792)
    with pdf.open("wb") as handle:
        writer.write(handle)
    png = tmp_path / "page.png"
    Image.fromarray(np.full((100, 100, 3), 255, dtype=np.uint8)).save(png)
    return pdf, png


class _StubClient:
    def __init__(
        self,
        *,
        model: str,
        pdf_text: str,
        legal_text: str,
        norm_text: str,
        locate_json: str = '{"pages": [2]}',
        img_text: str | None = None,
    ) -> None:
        self.model = model
        self._pdf_text = pdf_text
        self._legal_text = legal_text
        self._norm_text = norm_text
        self._locate_json = locate_json
        self._img_text = img_text if img_text is not None else pdf_text
        self.text_calls = 0
        self.image_calls = 0

    def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
        self.text_calls += 1
        if "Normalize the legal description text" in prompt:
            return self._norm_text
        return self._legal_text

    def generate_text_with_pdf(
        self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
    ) -> str:
        return self._pdf_text

    def generate_text_with_images(
        self, prompt: str, image_paths: Any, *, response_mime_type: str | None = None
    ) -> str:
        self.image_calls += 1
        if response_mime_type == "application/json":
            return self._locate_json
        return self._img_text


def test_pipeline_no_escalation_when_primary_closes(tmp_path: Path) -> None:
    pdf, _ = _make_pdf_and_png(tmp_path)
    primary = _StubClient(
        model="haiku-primary",
        pdf_text=_CLOSED_SQUARE,
        legal_text=_CLOSED_SQUARE,
        norm_text=_CLOSED_SQUARE,
    )
    escalated = _StubClient(
        model="sonnet-esc",
        pdf_text=_CLOSED_SQUARE,
        legal_text=_CLOSED_SQUARE,
        norm_text=_CLOSED_SQUARE,
    )
    pipe = Pipeline(
        provider="openrouter",
        cache=False,
        audit=True,
        client=primary,
        escalation_policy="closure_failed",
        escalation_client=escalated,
    )
    res, ctx = pipe.run(pdf)
    assert not isinstance(res, list)
    assert res.closure_passed is True
    assert pipe.last_escalation_report is not None
    assert pipe.last_escalation_report.triggered is False
    assert escalated.image_calls == 0
    assert ctx.extraction_record is not None
    assert len(ctx.extraction_record.llm_stages) == 3


def test_pipeline_escalation_fixes_closure_and_records_disagreement_warning(
    tmp_path: Path,
) -> None:
    pdf, png = _make_pdf_and_png(tmp_path, n_pages=4)
    primary = _StubClient(
        model="haiku-primary",
        pdf_text=_BROKEN_SQUARE,
        legal_text=_BROKEN_SQUARE,
        norm_text=_BROKEN_SQUARE,
        locate_json='{"pages": [2]}',
    )
    escalated = _StubClient(
        model="sonnet-esc",
        pdf_text=_CLOSED_SQUARE,
        legal_text=_CLOSED_SQUARE,
        norm_text=_CLOSED_SQUARE,
    )
    pipe = Pipeline(
        provider="openrouter",
        cache=False,
        audit=True,
        client=primary,
        escalation_policy="closure_failed",
        escalation_client=escalated,
    )
    with patch("mp_ocr.preprocessing.preprocess_pdf_pages_for_ocr", return_value=[png]):
        res, ctx = pipe.run(pdf)

    assert not isinstance(res, list)
    assert res.closure_passed is True
    assert res.misclosure_ft < 0.01
    assert any("OCR escalation disagreement on course 4" in w for w in res.warnings)
    report = pipe.last_escalation_report
    assert report is not None
    assert report.triggered is True
    assert report.legal_pages == (2,)
    assert report.agrees is False
    assert report.selected == "escalated"
    assert report.selection_reason == "escalated_passed_closure_where_primary_failed"
    assert len(report.disagreements) == 1
    assert ctx.extraction_record is not None
    stage_names = [s.stage for s in ctx.extraction_record.llm_stages]
    assert "extract_text_from_pdf" in stage_names
    assert "locate_legal_pages" in stage_names
    assert "escalation_extract_text_from_images" in stage_names
    assert "escalation_normalize_text" in stage_names


def test_pipeline_escalation_confirms_real_deed_typo_when_readings_agree(tmp_path: Path) -> None:
    pdf, png = _make_pdf_and_png(tmp_path, n_pages=2)
    primary = _StubClient(
        model="haiku-primary",
        pdf_text=_BROKEN_SQUARE,
        legal_text=_BROKEN_SQUARE,
        norm_text=_BROKEN_SQUARE,
    )
    pipe = Pipeline(
        provider="openrouter",
        cache=False,
        audit=False,
        client=primary,
        escalation_policy="closure_failed",
    )
    with patch("mp_ocr.preprocessing.preprocess_pdf_pages_for_ocr", return_value=[png]):
        res = pipe.run(pdf)

    assert not isinstance(res, list)
    assert res.closure_passed is False
    report = pipe.last_escalation_report
    assert report is not None
    assert report.triggered is True
    assert report.agrees is True
    assert report.disagreements == ()
    assert report.selected == "primary"
    assert report.selection_reason == "readings_agree_confirmed_by_escalation"
    assert not any("OCR escalation disagreement" in w for w in res.warnings)


def test_pipeline_unverified_policy_escalates_blocked_cardinal_deed(tmp_path: Path) -> None:
    pdf, png = _make_pdf_and_png(tmp_path, n_pages=2)
    primary = _StubClient(
        model="haiku-primary",
        pdf_text=_BLOCKED_CARDINAL,
        legal_text=_BLOCKED_CARDINAL,
        norm_text=_BLOCKED_CARDINAL,
    )
    esc_fixed = _BLOCKED_CARDINAL.replace("100.00 feet", "105.00 feet", 1)
    escalated = _StubClient(
        model="sonnet-esc",
        pdf_text=esc_fixed,
        legal_text=esc_fixed,
        norm_text=esc_fixed,
    )
    pipe = Pipeline(
        provider="openrouter",
        cache=False,
        audit=False,
        client=primary,
        escalation_policy="unverified",
        escalation_client=escalated,
    )
    with patch("mp_ocr.preprocessing.preprocess_pdf_pages_for_ocr", return_value=[png]):
        res = pipe.run(pdf)

    assert not isinstance(res, list)
    assert res.closure_passed is False
    report = pipe.last_escalation_report
    assert report is not None
    assert report.triggered is True
    assert report.selected == "escalated"
    assert report.selection_reason == "escalated_high_dpi_selected_with_disagreement_warning"
    assert any("OCR escalation disagreement on course 1" in w for w in res.warnings)


def test_monolith_processor_image_extraction_and_stage3_guard(tmp_path: Path) -> None:
    pdf, png = _make_pdf_and_png(tmp_path, n_pages=2)
    client = _StubClient(
        model="monolith-stub",
        pdf_text=_CLOSED_SQUARE,
        legal_text=_CLOSED_SQUARE,
        norm_text=_BROKEN_SQUARE,  # drifted distance 99.00 vs 100.00 -> guard must reject
    )
    proc = MonolithPDFProcessor(client=client, cache=False)
    with patch("mp_ocr.preprocessing.preprocess_pdf_pages_for_ocr", return_value=[png]):
        legal, norm, pages, stages = proc.extract_legal_description_from_images(
            str(pdf), audit=True
        )
    assert pages == [1, 2]
    assert legal == _CLOSED_SQUARE
    assert norm == _CLOSED_SQUARE  # preserved Stage 2 text!
    assert len(stages) == 3


def test_monolith_processor_retries_all_pages_when_located_subset_lacks_measurements(
    tmp_path: Path,
) -> None:
    pdf, png = _make_pdf_and_png(tmp_path, n_pages=5)

    class _SubsetRetryClient:
        model = "monolith-retry"

        def __init__(self) -> None:
            self._text_replies = [
                "No legal description on pages 1 or 5.",
                "No legal description on pages 1 or 5.",
                _CLOSED_SQUARE,
                _CLOSED_SQUARE,
            ]

        def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
            return self._text_replies.pop(0)

        def generate_text_with_pdf(
            self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
        ) -> str:
            return ""

        def generate_text_with_images(
            self, prompt: str, image_paths: Any, *, response_mime_type: str | None = None
        ) -> str:
            if response_mime_type == "application/json":
                return '{"pages": [1, 5]}'
            return "RAW"

    proc = MonolithPDFProcessor(client=_SubsetRetryClient(), cache=False)
    with patch("mp_ocr.preprocessing.preprocess_pdf_pages_for_ocr", return_value=[png]):
        legal, norm, pages, stages = proc.extract_legal_description_from_images(
            str(pdf), audit=True
        )
    assert pages == [1, 2, 3, 4, 5]
    assert legal == _CLOSED_SQUARE
    assert norm == _CLOSED_SQUARE
    assert any(s.stage == "escalation_fallback_extract_text_from_images" for s in stages)
