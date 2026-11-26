"""Integration tests for Pipeline blind escalation and monolith image client parity."""

from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from mp_export import export_verified_csv
from pypdf import PdfWriter

from metesparser import Pipeline
from metesparser.llm_cache import CachedLLMClient as MonolithCachedLLMClient
from metesparser.llm_clients import (
    GeminiClient as MonolithGeminiClient,
)
from metesparser.llm_clients import (
    OpenAIClient as MonolithOpenAIClient,
)
from metesparser.llm_clients import (
    OpenRouterClient as MonolithOpenRouterClient,
)
from metesparser.pdf_processor import PDFProcessor as MonolithPDFProcessor

# Minimal valid 1x1 white PNG — keeps root tests independent of optional [vision] extras
_TINY_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC"
)

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

_ZERO_CALL_LOT_BLOCK = (
    "ALL THAT CERTAIN lot or parcel of land known and designated as Lot 14, Block 202, "
    "as shown on a certain map entitled Map of Pennbrook Estates filed in the Camden County "
    "Clerk's Office."
)

_TWO_TRACT_BROKEN_T2 = "TRACT 1:\n" + _CLOSED_SQUARE + "\n\nTRACT 2:\n" + _BROKEN_SQUARE

_TWO_TRACT_CLOSED = "TRACT 1:\n" + _CLOSED_SQUARE + "\n\nTRACT 2:\n" + _CLOSED_SQUARE

_SINGLE_TRACT_ONLY = "TRACT 1:\n" + _CLOSED_SQUARE


def _make_pdf_and_png(tmp_path: Path, n_pages: int = 3) -> tuple[Path, Path]:
    pdf = tmp_path / "deed.pdf"
    writer = PdfWriter()
    for _ in range(n_pages):
        writer.add_blank_page(width=612, height=792)
    with pdf.open("wb") as handle:
        writer.write(handle)
    png = tmp_path / "page.png"
    png.write_bytes(_TINY_PNG_BYTES)
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


def test_pipeline_validates_escalation_policy_and_dpi_eagerly() -> None:
    with pytest.raises(ValueError, match="Invalid escalation_policy"):
        Pipeline(escalation_policy="always")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="escalation_dpi"):
        Pipeline(escalation_dpi=0)
    with pytest.raises(ValueError, match="escalation_dpi"):
        Pipeline(escalation_dpi=601)
    with pytest.raises(ValueError, match="escalation_dpi"):
        Pipeline(escalation_dpi=True)


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
    assert ctx.run_metadata.config["escalation_policy"] == "closure_failed"
    assert ctx.run_metadata.config["escalation_triggered"] is False


def test_pipeline_zero_call_deed_skips_escalation_under_unverified(tmp_path: Path) -> None:
    pdf, _ = _make_pdf_and_png(tmp_path)
    primary = _StubClient(
        model="haiku-primary",
        pdf_text=_ZERO_CALL_LOT_BLOCK,
        legal_text=_ZERO_CALL_LOT_BLOCK,
        norm_text=_ZERO_CALL_LOT_BLOCK,
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
        audit=False,
        client=primary,
        escalation_policy="unverified",
        escalation_client=escalated,
    )
    res = pipe.run(pdf)
    assert not isinstance(res, list)
    assert pipe.last_escalation_report is not None
    assert pipe.last_escalation_report.triggered is False
    assert escalated.image_calls == 0


def test_pipeline_escalation_fixes_closure_and_syncs_audit_and_export_gate(
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
    # Disagreement MUST fail verification eligibility and add an explicit failed check
    assert res.geometry_verified is False
    assert any("OCR escalation disagreement on course 4" in w for w in res.warnings)
    disagreement_checks = [c for c in res.checks if c.name == "ocr_escalation_agreement"]
    assert len(disagreement_checks) == 1
    assert disagreement_checks[0].status == "failed"
    assert res.confidence_score is not None and res.confidence_score < 1.0

    # VerificationAudit & RunMetadata.config must stay synchronized with ClosureResult (H1)
    assert ctx.verification_audit is not None
    assert any(
        c.name == "ocr_escalation_agreement" and c.status == "failed"
        for c in ctx.verification_audit.checks
    )
    assert ctx.verification_audit.closure_summary["geometry_verified"] is False
    assert ctx.verification_audit.closure_summary["confidence_score"] == res.confidence_score
    assert ctx.run_metadata.config["escalation_triggered"] is True
    assert ctx.run_metadata.config["escalation_agrees"] is False
    assert ctx.run_metadata.config["escalation_selected"] == "escalated"
    assert ctx.run_metadata.config["escalation_disagreement_count"] == 1
    assert ctx.run_metadata.config["escalation_legal_pages"] == "2"

    # Verified-export gate must reject a closed parcel with an unresolved OCR disagreement
    from mp_parse import extract_calls

    closed_calls, _ = extract_calls(_CLOSED_SQUARE)
    with pytest.raises(ValueError):
        export_verified_csv(closed_calls, res, tmp_path / "blocked.csv")

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


def test_pipeline_escalation_confirms_real_deed_typo_and_keeps_primary_with_audit(
    tmp_path: Path,
) -> None:
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
        audit=True,
        client=primary,
        escalation_policy="closure_failed",
    )
    with patch("mp_ocr.preprocessing.preprocess_pdf_pages_for_ocr", return_value=[png]):
        res, ctx = pipe.run(pdf)

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
    assert ctx.extraction_record is not None
    stages = [s.stage for s in ctx.extraction_record.llm_stages]
    assert stages[:3] == [
        "extract_text_from_pdf",
        "extract_legal_description",
        "normalize_text",
    ]
    assert "escalation_extract_text_from_images" in stages
    assert ctx.run_metadata.config["escalation_selected"] == "primary"
    assert ctx.run_metadata.config["escalation_agrees"] is True


def test_pipeline_multi_tract_retries_all_pages_when_subset_drops_tract_and_syncs_tract_audits(
    tmp_path: Path,
) -> None:
    pdf, png = _make_pdf_and_png(tmp_path, n_pages=4)
    primary = _StubClient(
        model="haiku-primary",
        pdf_text=_TWO_TRACT_BROKEN_T2,
        legal_text=_TWO_TRACT_BROKEN_T2,
        norm_text=_TWO_TRACT_BROKEN_T2,
        locate_json='{"pages": [2]}',
    )

    class _TruncatedThenFullEscClient:
        model = "sonnet-esc"

        def __init__(self) -> None:
            self._text_replies = [
                # First located subset [2] misses Tract 2!
                _SINGLE_TRACT_ONLY,
                _SINGLE_TRACT_ONLY,
                # Automatic all-page fallback [1, 2, 3, 4] recovers both closed tracts!
                _TWO_TRACT_CLOSED,
                _TWO_TRACT_CLOSED,
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
            return "RAW"

    pipe = Pipeline(
        provider="openrouter",
        cache=False,
        audit=True,
        client=primary,
        escalation_policy="closure_failed",
        escalation_client=_TruncatedThenFullEscClient(),
    )
    with patch("mp_ocr.preprocessing.preprocess_pdf_pages_for_ocr", return_value=[png]):
        res_list, ctx = pipe.run(pdf)

    assert isinstance(res_list, list)
    assert len(res_list) == 2
    assert all(r.closure_passed for r in res_list)
    assert all(r.geometry_verified is False for r in res_list)
    report = pipe.last_escalation_report
    assert report is not None
    assert report.legal_pages == (1, 2, 3, 4)
    assert report.selected == "escalated"
    assert any("(Tract 2)" in w for w in report.review_warnings)
    assert len(ctx.tract_verification_audits) == 2
    for t_audit in ctx.tract_verification_audits:
        assert any(
            c.name == "ocr_escalation_agreement" and c.status == "failed" for c in t_audit.checks
        )
        assert t_audit.closure_summary["geometry_verified"] is False
    assert ctx.extraction_record is not None
    assert "escalation_fallback_extract_text_from_images" in [
        s.stage for s in ctx.extraction_record.llm_stages
    ]


def test_pipeline_multi_tract_preserves_primary_if_all_page_escalation_still_drops_tract(
    tmp_path: Path,
) -> None:
    pdf, png = _make_pdf_and_png(tmp_path, n_pages=2)
    primary = _StubClient(
        model="haiku-primary",
        pdf_text=_TWO_TRACT_BROKEN_T2,
        legal_text=_TWO_TRACT_BROKEN_T2,
        norm_text=_TWO_TRACT_BROKEN_T2,
    )
    dropped_esc = _StubClient(
        model="sonnet-esc",
        pdf_text=_SINGLE_TRACT_ONLY,
        legal_text=_SINGLE_TRACT_ONLY,
        norm_text=_SINGLE_TRACT_ONLY,
    )
    pipe = Pipeline(
        provider="openrouter",
        cache=False,
        audit=False,
        client=primary,
        escalation_policy="closure_failed",
        escalation_client=dropped_esc,
    )
    with patch("mp_ocr.preprocessing.preprocess_pdf_pages_for_ocr", return_value=[png]):
        res_list = pipe.run(pdf)

    assert isinstance(res_list, list)
    assert len(res_list) == 2
    report = pipe.last_escalation_report
    assert report is not None
    assert report.selected == "primary"
    assert report.selection_reason == "escalated_dropped_tracts_fallback_to_primary"
    assert any("tract count" in w for w in res_list[0].warnings)


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


def test_monolith_processor_image_extraction_stage3_guard_and_retry(tmp_path: Path) -> None:
    pdf, png = _make_pdf_and_png(tmp_path, n_pages=2)
    client = _StubClient(
        model="monolith-stub",
        pdf_text=_CLOSED_SQUARE,
        legal_text=_CLOSED_SQUARE,
        norm_text=_BROKEN_SQUARE,
    )
    proc = MonolithPDFProcessor(client=client, cache=False)
    with patch("mp_ocr.preprocessing.preprocess_pdf_pages_for_ocr", return_value=[png]):
        legal, norm, pages = proc.extract_legal_description_from_images(str(pdf), audit=True)
    stages = proc.pop_audit_stage_records()
    assert pages == [1, 2]
    assert legal == _CLOSED_SQUARE
    assert norm == _CLOSED_SQUARE
    assert len(stages) == 3

    pdf5, _ = _make_pdf_and_png(tmp_path / "sub" if False else tmp_path, n_pages=5)

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

    proc2 = MonolithPDFProcessor(client=_SubsetRetryClient(), cache=False)
    with patch("mp_ocr.preprocessing.preprocess_pdf_pages_for_ocr", return_value=[png]):
        legal2, norm2, pages2 = proc2.extract_legal_description_from_images(str(pdf5), audit=True)
    stages2 = proc2.pop_audit_stage_records()
    assert pages2 == [1, 2, 3, 4, 5]
    assert legal2 == _CLOSED_SQUARE
    assert norm2 == _CLOSED_SQUARE
    assert any(s.stage == "escalation_fallback_extract_text_from_images" for s in stages2)


def test_monolith_clients_and_cache_generate_text_with_images_parity(tmp_path: Path) -> None:
    png = tmp_path / "p.png"
    png.write_bytes(_TINY_PNG_BYTES)
    empty_png = tmp_path / "empty.png"
    empty_png.write_bytes(b"")

    # OpenAI
    mock_openai = MagicMock()
    mock_openai.responses.create.return_value = SimpleNamespace(output_text="OA_IMG")
    with patch("openai.OpenAI", return_value=mock_openai):
        oa = MonolithOpenAIClient(api_key="k", model="gpt-5.2")
    assert oa.generate_text_with_images("Read", [png]) == "OA_IMG"
    with pytest.raises(TypeError, match="sequence of image paths"):
        oa.generate_text_with_images("Read", str(png))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="empty"):
        oa.generate_text_with_images("Read", [empty_png])

    # OpenRouter
    mock_or = MagicMock()
    mock_or.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="OR_IMG"), finish_reason="stop")]
    )
    with patch("openai.OpenAI", return_value=mock_or):
        or_client = MonolithOpenRouterClient(
            api_key="k", model="anthropic/claude-haiku-5.5", fallback_model=None
        )
    assert or_client.generate_text_with_images("Read", [png]) == "OR_IMG"

    # Gemini
    gem = object.__new__(MonolithGeminiClient)
    fake_types = SimpleNamespace(
        Content=lambda role, parts: {"role": role, "parts": parts},
        Part=SimpleNamespace(
            from_bytes=lambda data, mime_type: ("bytes", mime_type, len(data)),
            from_text=lambda text: ("text", text),
        ),
    )
    object.__setattr__(gem, "_types", fake_types)
    with patch.object(MonolithGeminiClient, "_generate", return_value="GEM_IMG"):
        assert gem.generate_text_with_images("Read", [png]) == "GEM_IMG"

    # CachedLLMClient
    stub = _StubClient(
        model="cache-stub",
        pdf_text="",
        legal_text="",
        norm_text="",
        img_text="CACHED_IMG",
    )
    cached = MonolithCachedLLMClient(stub, tmp_path / "cache")
    assert cached.generate_text_with_images("Read", [png]) == "CACHED_IMG"
    assert cached.generate_text_with_images("Read", [png]) == "CACHED_IMG"
    assert stub.image_calls == 1
    with pytest.raises(TypeError, match="sequence of image paths"):
        cached.generate_text_with_images("Read", png)  # type: ignore[arg-type]

    class _NoImg:
        model = "cache-stub"

        def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
            return ""

        def generate_text_with_pdf(
            self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
        ) -> str:
            return ""

    cached_no_img = MonolithCachedLLMClient(_NoImg(), tmp_path / "cache")
    with pytest.raises(NotImplementedError, match="generate_text_with_images"):
        cached_no_img.generate_text_with_images("Read", [png])
