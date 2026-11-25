"""Tests for metesparser.pipeline — Pipeline orchestrator."""

from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch

from metesparser.pipeline import Pipeline


class TestPipelineImport:
    """Pipeline class should be importable."""

    def test_importable_from_module(self) -> None:
        from metesparser.pipeline import Pipeline

        assert Pipeline is not None

    def test_importable_from_package(self) -> None:
        from metesparser import Pipeline

        assert Pipeline is not None


class TestPipelineConstruction:
    """Pipeline should accept configuration params."""

    def test_default_construction(self) -> None:
        pipe = Pipeline()
        assert pipe.provider == "openai"
        assert pipe.cache is True
        assert pipe.audit is False

    def test_custom_provider(self) -> None:
        pipe = Pipeline(provider="gemini")
        assert pipe.provider == "gemini"

    def test_cache_disabled(self) -> None:
        pipe = Pipeline(cache=False)
        assert pipe.cache is False

    def test_audit_enabled(self) -> None:
        pipe = Pipeline(audit=True)
        assert pipe.audit is True

    def test_all_params(self) -> None:
        pipe = Pipeline(provider="gemini", cache=False, audit=True)
        assert pipe.provider == "gemini"
        assert pipe.cache is False
        assert pipe.audit is True


class TestPipelineRun:
    """Pipeline.run() should chain stages in order."""

    def test_run_is_callable(self) -> None:
        pipe = Pipeline()
        assert callable(pipe.run)

    def test_run_accepts_path(self) -> None:
        """run() should accept a Path argument (signature check)."""
        sig = inspect.signature(Pipeline.run)
        params = list(sig.parameters.keys())
        assert "pdf_path" in params

    @patch("metesparser.pipeline.verify_closure")
    @patch("metesparser.pipeline.PDFProcessor")
    def test_run_chains_stages(
        self,
        mock_processor_cls: MagicMock,
        mock_verify: MagicMock,
    ) -> None:
        """run() should call PDFProcessor then verify_closure."""
        from mp_models import ClosureResult, DeedCall, LegalDescription

        mock_processor = MagicMock()
        mock_processor_cls.return_value = mock_processor

        mock_legal_desc = MagicMock(spec=LegalDescription)
        mock_legal_desc.calls = [MagicMock(spec=DeedCall)]
        mock_legal_desc.stated_area_sq_ft = None
        mock_legal_desc.tracts = []

        mock_processor.process_deed_pdf.return_value = mock_legal_desc

        mock_closure = MagicMock(spec=ClosureResult)
        mock_verify.return_value = mock_closure

        pipe = Pipeline(provider="openai", cache=False)
        result = pipe.run(Path("test.pdf"))

        mock_processor_cls.assert_called_once_with(provider="openai", cache=False)
        mock_processor.process_deed_pdf.assert_called_once_with("test.pdf", audit=False)
        mock_verify.assert_called_once_with(
            mock_legal_desc.calls, stated_area_sq_ft=0.0, audit_context=None
        )
        assert result is mock_closure

    @patch("metesparser.pipeline.verify_closure")
    @patch("metesparser.pipeline.PDFProcessor")
    def test_run_with_audit(
        self,
        mock_processor_cls: MagicMock,
        mock_verify: MagicMock,
    ) -> None:
        """run() with audit=True should pass AuditContext through and return it."""
        from mp_models import AuditContext, ClosureResult, DeedCall, LegalDescription

        mock_processor = MagicMock()
        mock_processor_cls.return_value = mock_processor

        mock_legal_desc = MagicMock(spec=LegalDescription)
        mock_legal_desc.calls = [MagicMock(spec=DeedCall)]
        mock_legal_desc.stated_area_sq_ft = None
        mock_legal_desc.tracts = []

        mock_audit_ctx = MagicMock(spec=AuditContext)
        mock_processor.process_deed_pdf.return_value = (mock_legal_desc, mock_audit_ctx)

        mock_closure = MagicMock(spec=ClosureResult)
        mock_verify.return_value = mock_closure

        pipe = Pipeline(provider="openai", cache=False, audit=True)
        result = pipe.run(Path("test.pdf"))

        mock_processor.process_deed_pdf.assert_called_once_with("test.pdf", audit=True)
        mock_verify.assert_called_once_with(
            mock_legal_desc.calls,
            stated_area_sq_ft=0.0,
            audit_context=mock_audit_ctx,
        )
        assert isinstance(result, tuple)
        assert result[0] is mock_closure
        assert result[1] is mock_audit_ctx


class TestPipelineMultiTract:
    """Pipeline passes tracts to verify_closure for multi-tract deeds."""

    @patch("metesparser.pipeline.verify_closure")
    @patch("metesparser.pipeline.PDFProcessor")
    def test_multi_tract_passes_tracts_to_verify(
        self,
        mock_processor_cls: MagicMock,
        mock_verify: MagicMock,
    ) -> None:
        from mp_models import ClosureResult, DeedCall, LegalDescription, Tract, TractType

        fake_calls = [
            DeedCall(
                course=1,
                direction_text="N 45\u00b000' E",
                bearing_quadrant="N 45\u00b000' E",
                bearing_azimuth_deg_from_north=45.0,
                distance_ft=100.0,
            ),
        ]
        fake_tracts = [
            Tract(label="Tract 1", tract_type=TractType.MAIN, calls=fake_calls),
            Tract(label="Tract 2", tract_type=TractType.MAIN, calls=fake_calls),
        ]

        mock_processor = MagicMock()
        mock_processor_cls.return_value = mock_processor

        mock_legal_desc = MagicMock(spec=LegalDescription)
        mock_legal_desc.calls = fake_calls
        mock_legal_desc.tracts = fake_tracts
        mock_legal_desc.all_calls = fake_calls + fake_calls
        mock_processor.process_deed_pdf.return_value = mock_legal_desc

        mock_results = [MagicMock(spec=ClosureResult), MagicMock(spec=ClosureResult)]
        mock_verify.return_value = mock_results

        pipe = Pipeline(provider="openai", cache=False)
        result = pipe.run(Path("test.pdf"))

        mock_verify.assert_called_once_with(
            mock_legal_desc.all_calls,
            tracts=fake_tracts,
            audit_context=None,
        )
        assert isinstance(result, list)
        assert len(result) == 2

    def test_end_to_end_two_tract_pdf_populates_tracts_and_verifies(
        self,
        tmp_path: Path,
    ) -> None:
        """PDFProcessor.process_deed_pdf populates tracts and Pipeline.run verifies both."""
        from metesparser.models import LegalDescription
        from metesparser.pdf_processor import PDFProcessor

        two_tract_text = (
            "TRACT #1: BEGINNING at an iron pin; "
            "THENCE North 45 degrees 00 minutes 00 seconds East 100.00 feet to a corner; "
            "THENCE South 45 degrees 00 minutes 00 seconds East 100.00 feet to a corner; "
            "THENCE South 45 degrees 00 minutes 00 seconds West 100.00 feet to a corner; "
            "THENCE North 45 degrees 00 minutes 00 seconds West 100.00 feet to the POINT OF BEGINNING. "
            "TRACT #2: BEGINNING at a concrete monument; "
            "THENCE North 00 degrees 00 minutes 00 seconds East 50.00 feet to a corner; "
            "THENCE North 90 degrees 00 minutes 00 seconds East 50.00 feet to a corner; "
            "THENCE South 00 degrees 00 minutes 00 seconds East 50.00 feet to a corner; "
            "THENCE South 90 degrees 00 minutes 00 seconds West 50.00 feet to the POINT OF BEGINNING."
        )

        class StubLLMClient:
            def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
                return two_tract_text

            def generate_text_with_pdf(
                self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
            ) -> str:
                return two_tract_text

        pdf_path = tmp_path / "two_tract.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n% stub\n")

        stub_client = StubLLMClient()
        processor = PDFProcessor(client=stub_client, cache=False)
        legal_desc = processor.process_deed_pdf(str(pdf_path))
        assert isinstance(legal_desc, LegalDescription)

        assert len(legal_desc.tracts) == 2
        assert [t.label for t in legal_desc.tracts] == ["Tract 1", "Tract 2"]
        assert all(len(t.calls) == 4 for t in legal_desc.tracts)

        with patch.object(PDFProcessor, "_create_client", return_value=stub_client):
            pipe = Pipeline(provider="openai", cache=False)
            results = pipe.run(pdf_path)

        assert isinstance(results, list)
        assert len(results) == 2
        assert all(r.is_fully_verified() for r in results)

    def test_exception_tract_marks_is_exception_and_extracts_area(
        self,
        tmp_path: Path,
    ) -> None:
        """Exception tract sets TractType.EXCEPTION, is_exception=True, and stated area."""
        from metesparser.models import LegalDescription, TractType
        from metesparser.pdf_processor import PDFProcessor

        deed_text = (
            "TRACT #1: BEGINNING at an iron pin; "
            "THENCE North 00 degrees 00 minutes 00 seconds East 100.00 feet to a corner; "
            "THENCE North 90 degrees 00 minutes 00 seconds East 100.00 feet to a corner; "
            "THENCE South 00 degrees 00 minutes 00 seconds East 100.00 feet to a corner; "
            "THENCE South 90 degrees 00 minutes 00 seconds West 100.00 feet to the POINT OF BEGINNING, "
            "CONTAINING 10000 square feet. "
            "EXCEPTING TRACT #2: COMMENCING at an iron pin; "
            "THENCE North 90 degrees 00 minutes 00 seconds East 10.00 feet to the POINT OF BEGINNING; "
            "THENCE North 00 degrees 00 minutes 00 seconds East 20.00 feet to a corner; "
            "THENCE North 90 degrees 00 minutes 00 seconds East 20.00 feet to a corner; "
            "THENCE South 00 degrees 00 minutes 00 seconds East 20.00 feet to a corner; "
            "THENCE South 90 degrees 00 minutes 00 seconds West 20.00 feet to the POINT OF BEGINNING, "
            "CONTAINING 400 square feet."
        )

        class StubLLMClient:
            def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
                return deed_text

            def generate_text_with_pdf(
                self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
            ) -> str:
                return deed_text

        pdf_path = tmp_path / "exception_tract.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n% stub\n")

        processor = PDFProcessor(client=StubLLMClient(), cache=False)
        legal_desc = processor.process_deed_pdf(str(pdf_path))
        assert isinstance(legal_desc, LegalDescription)

        assert len(legal_desc.tracts) == 2
        main_tract, exc_tract = legal_desc.tracts
        assert main_tract.tract_type == TractType.MAIN
        assert main_tract.stated_area_sq_ft == 10000.0
        assert all(not c.is_exception for c in main_tract.calls)

        assert exc_tract.tract_type == TractType.EXCEPTION
        assert exc_tract.stated_area_sq_ft == 400.0
        assert exc_tract.calls[0].is_tie_in is True
        assert all(c.is_exception is True for c in exc_tract.calls)

    def test_fallback_empty_except_clause_preserves_single_tract(
        self,
        tmp_path: Path,
    ) -> None:
        """Fallback EXCEPTING clause with 0 calls is dropped and keeps tracts=[]."""
        from mp_models import ClosureResult

        from metesparser.models import LegalDescription
        from metesparser.pdf_processor import PDFProcessor

        single_with_reservation = (
            "BEGINNING at an iron pin; "
            "THENCE North 00 degrees 00 minutes 00 seconds East 100.00 feet to a corner; "
            "THENCE North 90 degrees 00 minutes 00 seconds East 100.00 feet to a corner; "
            "THENCE South 00 degrees 00 minutes 00 seconds East 100.00 feet to a corner; "
            "THENCE South 90 degrees 00 minutes 00 seconds West 100.00 feet to the POINT OF BEGINNING. "
            "EXCEPTING all oil, gas, and mineral rights heretofore reserved."
        )

        class StubLLMClient:
            def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
                return single_with_reservation

            def generate_text_with_pdf(
                self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
            ) -> str:
                return single_with_reservation

        pdf_path = tmp_path / "reservation.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n% stub\n")

        stub_client = StubLLMClient()
        processor = PDFProcessor(client=stub_client, cache=False)
        legal_desc = processor.process_deed_pdf(str(pdf_path))
        assert isinstance(legal_desc, LegalDescription)

        assert legal_desc.tracts == []
        assert len(legal_desc.calls) == 4

        with patch.object(PDFProcessor, "_create_client", return_value=stub_client):
            pipe = Pipeline(provider="openai", cache=False)
            result = pipe.run(pdf_path)

        assert isinstance(result, ClosureResult)
        assert result.is_fully_verified()
