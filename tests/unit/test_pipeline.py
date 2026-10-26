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
