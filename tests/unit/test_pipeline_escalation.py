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


def _fake_preprocess(png: Path, default_pages: int = 1) -> Any:
    """Return a page-count-accurate mock for ``preprocess_pdf_pages_for_ocr``."""

    def _side_effect(_pdf: Any, _out: Path, *, pages: Any = None, **kwargs: Any) -> list[Path]:
        count = len(pages) if pages is not None else default_pages
        return [png] * count

    return _side_effect


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
    with patch(
        "mp_ocr.preprocess_pdf_pages_for_ocr", side_effect=_fake_preprocess(png, 4)
    ) as mock_pre:
        res, ctx = pipe.run(pdf)
    assert mock_pre.call_count == 2
    assert mock_pre.call_args_list[-1].kwargs["pages"] == [2]
    assert mock_pre.call_args_list[-1].kwargs["dpi"] == 300

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
    assert bool(ctx.verification_audit.closure_summary["geometry_verified"]) is False
    assert ctx.verification_audit.closure_summary["confidence_score"] == res.confidence_score
    import warnings

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        dumped = ctx.model_dump_json()
    assert '"ocr_escalation_agreement"' in dumped
    assert not [w for w in caught if "PydanticSerializationUnexpectedValue" in str(w.message)]
    assert ctx.run_metadata.config["primary_model"] == "haiku-primary"
    assert ctx.run_metadata.config["escalation_model"] == "sonnet-esc"
    assert ctx.run_metadata.config["escalation_triggered"] is True
    assert ctx.run_metadata.config["escalation_agrees"] is False
    assert ctx.run_metadata.config["escalation_selected"] == "escalated"
    assert ctx.run_metadata.config["escalation_disagreement_count"] == 1
    assert ctx.run_metadata.config["escalation_legal_pages"] == "2"

    # Verified-export gate must reject a closed parcel with an unresolved OCR disagreement
    from mp_parse import extract_calls

    closed_calls, _ = extract_calls(_CLOSED_SQUARE)
    with pytest.raises(ValueError, match="verification checks failed"):
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
    with patch(
        "mp_ocr.preprocess_pdf_pages_for_ocr", side_effect=_fake_preprocess(png, 4)
    ) as mock_pre:
        res, ctx = pipe.run(pdf)
    assert mock_pre.called

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
    with patch(
        "mp_ocr.preprocess_pdf_pages_for_ocr", side_effect=_fake_preprocess(png, 4)
    ) as mock_pre:
        res_list, ctx = pipe.run(pdf)
    assert mock_pre.called

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
        assert bool(t_audit.closure_summary["geometry_verified"]) is False
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
    with patch(
        "mp_ocr.preprocess_pdf_pages_for_ocr", side_effect=_fake_preprocess(png, 2)
    ) as mock_pre:
        res_list = pipe.run(pdf)
    assert mock_pre.called

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
    with patch(
        "mp_ocr.preprocess_pdf_pages_for_ocr", side_effect=_fake_preprocess(png, 2)
    ) as mock_pre:
        res = pipe.run(pdf)
    assert mock_pre.called

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
    with patch(
        "mp_ocr.preprocess_pdf_pages_for_ocr", side_effect=_fake_preprocess(png, 2)
    ) as mock_pre:
        legal, norm, pages = proc.extract_legal_description_from_images(str(pdf), audit=True)
    assert mock_pre.called
    stages = proc.pop_audit_stage_records()
    assert pages == [1, 2]
    assert legal == _CLOSED_SQUARE
    assert norm == _CLOSED_SQUARE
    assert len(stages) == 3

    sub = tmp_path / "sub"
    sub.mkdir()
    pdf5, _ = _make_pdf_and_png(sub, n_pages=5)

    class _SubsetRetryClient:
        model = "monolith-retry"

        def __init__(self) -> None:
            self._text_replies = [
                # Stage 2 on subset [1, 5] has no legal signals -> Stage 3 skipped, retries all pages
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
    with patch(
        "mp_ocr.preprocess_pdf_pages_for_ocr", side_effect=_fake_preprocess(png, 5)
    ) as mock_pre2:
        legal2, norm2, pages2 = proc2.extract_legal_description_from_images(str(pdf5), audit=True)
    assert mock_pre2.called
    stages2 = proc2.pop_audit_stage_records()
    assert pages2 == [1, 2, 3, 4, 5]
    assert legal2 == _CLOSED_SQUARE
    assert norm2 == _CLOSED_SQUARE
    assert any(s.stage == "escalation_fallback_extract_text_from_images" for s in stages2)


def test_pipeline_pdf_only_primary_client_uses_escalation_locator_and_thread_isolation(
    tmp_path: Path,
) -> None:
    import threading

    pdf3, png = _make_pdf_and_png(tmp_path, n_pages=3)

    class _PdfOnlyPrimary:
        model = "pdf-only-primary"

        def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
            return _BROKEN_SQUARE

        def generate_text_with_pdf(
            self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
        ) -> str:
            return _BROKEN_SQUARE

    escalated = _StubClient(
        model="vision-sonnet",
        pdf_text=_CLOSED_SQUARE,
        legal_text=_CLOSED_SQUARE,
        norm_text=_CLOSED_SQUARE,
        locate_json='{"pages": [2]}',
    )
    pipe = Pipeline(
        provider="openrouter",
        cache=False,
        audit=False,
        client=_PdfOnlyPrimary(),
        escalation_policy="closure_failed",
        escalation_client=escalated,
    )
    with patch("mp_ocr.preprocess_pdf_pages_for_ocr", side_effect=_fake_preprocess(png, 3)):
        res = pipe.run(pdf3)
    assert not isinstance(res, list)
    assert res.closure_passed is True
    main_report = pipe.last_escalation_report
    assert main_report is not None and main_report.selected == "escalated"

    # A second thread reading pipe.last_escalation_report does not see main thread's state.
    other_thread_reports: list[Any] = []

    def _worker() -> None:
        other_thread_reports.append(pipe.last_escalation_report)

    t = threading.Thread(target=_worker)
    t.start()
    t.join()
    assert other_thread_reports == [None]
    assert pipe.last_escalation_report == main_report


def test_pipeline_subset_parse_error_retries_all_pages_and_falls_back_to_primary_on_failure(
    tmp_path: Path,
) -> None:
    pdf3, png = _make_pdf_and_png(tmp_path, n_pages=3)
    primary = _StubClient(
        model="haiku-primary",
        pdf_text=_BROKEN_SQUARE,
        legal_text=_BROKEN_SQUARE,
        norm_text=_BROKEN_SQUARE,
        locate_json='{"pages": [2]}',
    )

    bad_text = "BEGINNING; THENCE N 10°00'00\" E, 100.00 feet BAD_SUBSET_MARKER"

    class _BadSubsetThenGoodAll:
        model = "sonnet-esc"

        def __init__(self) -> None:
            self._replies = [
                bad_text,
                bad_text,
                _CLOSED_SQUARE,
                _CLOSED_SQUARE,
            ]

        def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
            return self._replies.pop(0)

        def generate_text_with_pdf(
            self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
        ) -> str:
            return ""

        def generate_text_with_images(
            self, prompt: str, image_paths: Any, *, response_mime_type: str | None = None
        ) -> str:
            return "RAW"

    real_process_legal = MonolithPDFProcessor.process_legal_text

    def _strict_fail_on_marker(self, *args: Any, **kwargs: Any) -> Any:
        if "BAD_SUBSET_MARKER" in str(kwargs.get("normalized_text", "")):
            raise ValueError("strict parse failure on truncated subset")
        return real_process_legal(self, *args, **kwargs)

    pipe = Pipeline(
        provider="openrouter",
        cache=False,
        audit=True,
        client=primary,
        escalation_policy="closure_failed",
        escalation_client=_BadSubsetThenGoodAll(),
    )
    with (
        patch("mp_ocr.preprocess_pdf_pages_for_ocr", side_effect=_fake_preprocess(png, 3)),
        patch.object(MonolithPDFProcessor, "process_legal_text", _strict_fail_on_marker),
    ):
        res, _ctx = pipe.run(pdf3)
    assert not isinstance(res, list)
    assert res.closure_passed is True
    assert pipe.last_escalation_report is not None
    assert pipe.last_escalation_report.legal_pages == (1, 2, 3)

    # If escalated text fails strict parsing even on all pages, fail closed to primary without crashing.
    bad_all = _StubClient(
        model="sonnet-broken",
        pdf_text=bad_text,
        legal_text=bad_text,
        norm_text=bad_text,
    )
    pipe_bad = Pipeline(
        provider="openrouter",
        cache=False,
        audit=True,
        client=primary,
        escalation_policy="closure_failed",
        escalation_client=bad_all,
    )
    with (
        patch("mp_ocr.preprocess_pdf_pages_for_ocr", side_effect=_fake_preprocess(png, 3)),
        patch.object(MonolithPDFProcessor, "process_legal_text", _strict_fail_on_marker),
    ):
        res_bad, ctx_bad = pipe_bad.run(pdf3)
    assert not isinstance(res_bad, list)
    assert res_bad.closure_passed is False
    assert pipe_bad.last_escalation_report is not None
    assert pipe_bad.last_escalation_report.selected == "primary"
    assert (
        pipe_bad.last_escalation_report.selection_reason
        == "escalated_parse_failed_fallback_to_primary"
    )
    # Escalated parse failure MUST block verified export, attach failed check, and keep mp_models types
    from mp_models import ExtractionRecord, LLMStageRecord

    assert res_bad.geometry_verified is False
    assert any(
        c.name == "ocr_escalation_agreement" and c.status == "failed" for c in res_bad.checks
    )
    assert ctx_bad.verification_audit is not None
    assert any(
        c.name == "ocr_escalation_agreement" and c.status == "failed"
        for c in ctx_bad.verification_audit.checks
    )
    assert ctx_bad.extraction_record is not None
    assert any(s.stage.startswith("escalation_") for s in ctx_bad.extraction_record.llm_stages)
    assert all(isinstance(s, LLMStageRecord) for s in ctx_bad.extraction_record.llm_stages)
    ExtractionRecord.model_validate(ctx_bad.extraction_record.model_dump())


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


def test_is_escalated_truncated_distinguishes_resolved_bearing_notes_from_tail_blocking_notes() -> (
    None
):
    from mp_models import DESCRIPTION_ROLES_NOTE, DeedCall, LegalDescription

    from metesparser.pipeline import _is_escalated_truncated

    pri_cardinal_call = DeedCall(
        course=1,
        direction_text="Northerly",
        bearing_azimuth_deg_from_north=None,
        distance_ft=100.0,
        notes="incomplete bearing - cardinal only",
    )
    esc_fixed_call = DeedCall(
        course=1,
        direction_text="N 12°34'56\" E",
        bearing_azimuth_deg_from_north=12.5822,
        distance_ft=100.0,
        notes=None,
    )
    pri_desc = LegalDescription(calls=[pri_cardinal_call])
    esc_desc = LegalDescription(calls=[esc_fixed_call])
    # Resolving an incomplete bearing note on located pages must NOT trigger an all-page retry
    assert _is_escalated_truncated(pri_desc, pri_desc.calls, esc_desc, esc_desc.calls) is False

    # Dropping a tail exception or description-role blocking note MUST trigger an all-page retry
    for blocking_note in (
        "exception not applied: easterly 10 feet thereof",
        DESCRIPTION_ROLES_NOTE,
    ):
        pri_blocked = LegalDescription(
            calls=[esc_fixed_call.model_copy(update={"notes": blocking_note})],
        )
        assert (
            _is_escalated_truncated(pri_blocked, pri_blocked.calls, esc_desc, esc_desc.calls)
            is True
        )


def test_pipeline_validates_escalation_provider_degrades_runtime_errors_and_reuses_render_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ValueError, match="Invalid escalation_provider"):
        Pipeline(escalation_provider="bogus")

    # Case-insensitive provider match reuses primary client without constructing a second provider
    pdf3, png = _make_pdf_and_png(tmp_path, n_pages=3)
    primary = _StubClient(
        model="haiku-primary",
        pdf_text=_BROKEN_SQUARE,
        legal_text=_BROKEN_SQUARE,
        norm_text=_BROKEN_SQUARE,
        locate_json='{"pages": [2]}',
    )
    pipe_ci = Pipeline(
        provider="openrouter",
        cache=False,
        audit=True,
        client=primary,
        escalation_policy="closure_failed",
        escalation_provider="OPENROUTER",
    )
    with patch("mp_ocr.preprocess_pdf_pages_for_ocr", side_effect=_fake_preprocess(png, 3)):
        res_ci, _ = pipe_ci.run(pdf3)
    assert not isinstance(res_ci, list)
    assert pipe_ci.last_escalation_report is not None
    assert pipe_ci.last_escalation_report.agrees is True

    # Runtime escalation error (e.g., missing pdftoppm) preserves primary result fail-closed
    pipe_err = Pipeline(
        provider="openrouter",
        cache=False,
        audit=True,
        client=primary,
        escalation_policy="closure_failed",
        escalation_client=primary,
    )
    with patch(
        "mp_ocr.preprocess_pdf_pages_for_ocr", side_effect=RuntimeError("pdftoppm not installed")
    ):
        res_err, ctx_err = pipe_err.run(pdf3)
    assert not isinstance(res_err, list)
    assert res_err.geometry_verified is False
    assert any(
        c.name == "ocr_escalation_agreement" and c.status == "failed" for c in res_err.checks
    )
    assert any("escalated_runtime_error_fallback_to_primary" in w for w in res_err.warnings)
    assert pipe_err.last_escalation_report is not None
    assert pipe_err.last_escalation_report.selected == "primary"
    assert (
        pipe_err.last_escalation_report.selection_reason
        == "escalated_runtime_error_fallback_to_primary"
    )
    assert ctx_err.verification_audit is not None
    assert any(
        c.name == "ocr_escalation_agreement" and c.status == "failed"
        for c in ctx_err.verification_audit.checks
    )
    assert "pdftoppm not installed" in str(ctx_err.run_metadata.config.get("escalation_error", ""))

    # PDF-only primary with cache=True unwraps CachedLLMClient + selected='primary' with disagreements
    monkeypatch.setenv("METESPARSER_CACHE_DIR", str(tmp_path / "llm_cache"))

    class _PdfOnlyPrimary:
        model = "pdf-only-primary"

        def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
            return _BROKEN_SQUARE

        def generate_text_with_pdf(
            self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
        ) -> str:
            return _BROKEN_SQUARE

    worse_square = _BROKEN_SQUARE.replace("99.00 feet", "90.00 feet")
    escalated_worse = _StubClient(
        model="vision-sonnet",
        pdf_text=worse_square,
        legal_text=worse_square,
        norm_text=worse_square,
        locate_json='{"pages": [2]}',
    )
    pipe_cached = Pipeline(
        provider="openrouter",
        cache=True,
        audit=True,
        client=_PdfOnlyPrimary(),
        escalation_policy="closure_failed",
        escalation_client=escalated_worse,
    )
    with patch("mp_ocr.preprocess_pdf_pages_for_ocr", side_effect=_fake_preprocess(png, 3)):
        res_c, ctx_c = pipe_cached.run(pdf3)
    assert not isinstance(res_c, list)
    assert pipe_cached.last_escalation_report is not None
    assert pipe_cached.last_escalation_report.selected == "primary"
    assert (
        pipe_cached.last_escalation_report.selection_reason
        == "primary_preserved_escalated_regressed_verification"
    )
    assert ctx_c.verification_audit is not None
    assert any(
        c.name == "ocr_escalation_agreement" and c.status == "failed"
        for c in ctx_c.verification_audit.checks
    )
    assert ctx_c.extraction_record is not None
    assert ctx_c.extraction_record.llm_stages[0].stage == "extract_text_from_pdf"

    # Truncation retry reuses already-rendered page 2 and only renders missing pages [1, 3]
    seen_render_pages: list[list[int] | None] = []

    def _track_pre(_pdf: Any, _out: Path, *, pages: Any = None, **kw: Any) -> list[Path]:
        seen_render_pages.append(list(pages) if pages is not None else None)
        return [png] * len(pages or [1])

    trunc_replies = [
        _SINGLE_TRACT_ONLY,
        _SINGLE_TRACT_ONLY,
        _TWO_TRACT_CLOSED,
        _TWO_TRACT_CLOSED,
    ]
    trunc_esc = SimpleNamespace(
        model="sonnet-trunc",
        generate_text=lambda *a, **k: trunc_replies.pop(0),
        generate_text_with_pdf=lambda *a, **k: "",
        generate_text_with_images=lambda *a, **k: "RAW",
    )
    pri_two = _StubClient(
        model="haiku-two",
        pdf_text=_TWO_TRACT_BROKEN_T2,
        legal_text=_TWO_TRACT_BROKEN_T2,
        norm_text=_TWO_TRACT_BROKEN_T2,
        locate_json='{"pages": [2]}',
    )
    pipe_reuse = Pipeline(
        provider="openrouter",
        cache=False,
        audit=False,
        client=pri_two,
        escalation_policy="closure_failed",
        escalation_client=trunc_esc,
    )
    with patch("mp_ocr.preprocess_pdf_pages_for_ocr", side_effect=_track_pre):
        pipe_reuse.run(pdf3)
    # 1st call: thumbnails [1,2,3], 2nd call: high-DPI [2], 3rd call: missing [1, 3] only!
    assert seen_render_pages == [[1, 2, 3], [2], [1, 3]]


def test_monolith_processor_batching_and_openrouter_omits_pdf_plugin(tmp_path: Path) -> None:
    pdf5, png = _make_pdf_and_png(tmp_path, n_pages=5)
    replies = iter(['{"pages": []}', '{"pages": [1]}', '{"pages": [1]}'])
    batch_client = SimpleNamespace(
        model="m",
        generate_text=lambda *a, **k: "",
        generate_text_with_pdf=lambda *a, **k: "",
        generate_text_with_images=lambda p, imgs, response_mime_type=None: (
            next(replies) if response_mime_type == "application/json" else f"N={len(imgs)}"
        ),
    )
    proc = MonolithPDFProcessor(client=batch_client, cache=False)
    with patch("mp_ocr.preprocess_pdf_pages_for_ocr", side_effect=_fake_preprocess(png, 5)):
        assert proc.locate_legal_description_pages(
            str(pdf5), max_pages_per_batch=2, audit=True
        ) == [
            3,
            5,
        ]
    assert len(proc.pop_audit_stage_records()) == 3
    assert proc.extract_text_from_images([png] * 5, max_images_per_call=2) == "N=2\n\nN=2\n\nN=1"

    mock_or = MagicMock()
    mock_or.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="OR_IMG"), finish_reason="stop")]
    )
    with patch("openai.OpenAI", return_value=mock_or):
        or_client = MonolithOpenRouterClient(
            api_key="k",
            model="anthropic/claude-haiku-5.5",
            fallback_model=None,
            pdf_engine="mistral-ocr",
        )
    or_client.generate_text_with_images("Read", [png])
    assert "plugins" not in mock_or.chat.completions.create.call_args.kwargs.get("extra_body", {})


def test_close_processor_client_unwraps_cache_and_terminates_on_magicmock(tmp_path: Path) -> None:
    from metesparser.pipeline import _close_processor_client

    # MagicMock creates infinite child mocks on attribute access; must terminate safely.
    mock_proc = MagicMock()
    _close_processor_client(mock_proc)
    assert mock_proc.client.close.call_count == 1

    # Real cache-like wrapper (Path _cache_dir) unwraps to inner SDK client and closes it.
    closed: list[str] = []
    sdk = SimpleNamespace(close=lambda: closed.append("sdk"))
    inner = SimpleNamespace(_client=sdk)
    cached = SimpleNamespace(_cache_dir=tmp_path, _client=inner)
    _close_processor_client(SimpleNamespace(client=cached))
    assert closed == ["sdk"]


def test_pipeline_injected_non_openai_client_respects_explicit_openai_escalation_provider(
    tmp_path: Path,
) -> None:
    from metesparser.llm_clients import GeminiClient as MonolithGeminiClient

    pdf, png = _make_pdf_and_png(tmp_path, n_pages=1)

    # Create a real GeminiClient subclass instance injected with default provider='openai'.
    class _StubGemini(MonolithGeminiClient):
        def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
            return _BROKEN_SQUARE

        def generate_text_with_pdf(
            self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
        ) -> str:
            return _BROKEN_SQUARE

        def generate_text_with_images(
            self,
            prompt: str,
            image_paths: Any,
            *,
            response_mime_type: str | None = None,
        ) -> str:
            return _BROKEN_SQUARE

    gemini_pri = object.__new__(_StubGemini)
    object.__setattr__(gemini_pri, "model", "gemini-primary")

    openai_stub = _StubClient(
        model="gpt-esc",
        pdf_text=_CLOSED_SQUARE,
        legal_text=_CLOSED_SQUARE,
        norm_text=_CLOSED_SQUARE,
    )
    created_providers: list[str] = []
    real_pdf_proc = MonolithPDFProcessor

    def _spy_processor(**kwargs: Any) -> Any:
        if kwargs.get("client") is None:
            created_providers.append(str(kwargs.get("provider")))
            return real_pdf_proc(client=openai_stub, cache=False)
        return real_pdf_proc(**kwargs)

    pipe = Pipeline(
        client=gemini_pri,
        cache=False,
        audit=False,
        escalation_policy="closure_failed",
        escalation_provider="openai",
    )
    with (
        patch("metesparser.pipeline.PDFProcessor", side_effect=_spy_processor),
        patch("mp_ocr.preprocess_pdf_pages_for_ocr", side_effect=_fake_preprocess(png, 1)),
    ):
        res = pipe.run(pdf)
    assert created_providers == ["openai"]
    assert not isinstance(res, list)
    assert res.closure_passed is True
    assert pipe.last_escalation_report is not None
    assert pipe.last_escalation_report.escalation_model == "gpt-esc"

    # Custom BaseLLMClient injected with default provider also respects explicit escalation_provider="openai"
    created_providers.clear()
    custom_pri = _StubClient(
        model="custom-pdf-only",
        pdf_text=_BROKEN_SQUARE,
        legal_text=_BROKEN_SQUARE,
        norm_text=_BROKEN_SQUARE,
    )
    pipe_custom = Pipeline(
        client=custom_pri,
        cache=False,
        audit=False,
        escalation_policy="closure_failed",
        escalation_provider="openai",
    )
    with (
        patch("metesparser.pipeline.PDFProcessor", side_effect=_spy_processor),
        patch("mp_ocr.preprocess_pdf_pages_for_ocr", side_effect=_fake_preprocess(png, 1)),
    ):
        res_custom = pipe_custom.run(pdf)
    assert created_providers == ["openai"]
    assert not isinstance(res_custom, list)
    assert res_custom.closure_passed is True

    # Monolith PDFProcessor enforces work_dir before locator LLM calls and validates image_paths
    pdf3, _ = _make_pdf_and_png(tmp_path, n_pages=3)
    calls_seen: list[Any] = []
    spy_client = SimpleNamespace(
        model="m",
        generate_text=lambda *a, **k: "",
        generate_text_with_pdf=lambda *a, **k: "",
        generate_text_with_images=lambda *a, **k: calls_seen.append(a) or "",
    )
    proc = MonolithPDFProcessor(client=spy_client, cache=False)
    with pytest.raises(ValueError, match="work_dir is required"):
        proc.extract_legal_description_from_images(str(pdf3), rendered_by_page={})
    with pytest.raises(TypeError, match="sequence of image paths"):
        proc.extract_text_from_images("/tmp/page.png")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="at least one"):
        proc.extract_text_from_images([])
    assert calls_seen == []
