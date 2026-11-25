"""Tests for PDFProcessor LLM cache integration."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from metesparser.llm_cache import CachedLLMClient
from metesparser.pdf_processor import PDFProcessor


class FakeLLMClient:
    def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
        return "normalized text"

    def generate_text_with_pdf(
        self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
    ) -> str:
        return "raw text"


class TestPDFProcessorCacheIntegration:
    def test_cache_enabled_by_default(self) -> None:
        processor = PDFProcessor(client=FakeLLMClient())
        assert isinstance(processor.client, CachedLLMClient)

    def test_cache_disabled_via_constructor(self) -> None:
        processor = PDFProcessor(client=FakeLLMClient(), cache=False)
        assert not isinstance(processor.client, CachedLLMClient)

    def test_cache_disabled_via_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("METESPARSER_LLM_CACHE", "false")
        processor = PDFProcessor(client=FakeLLMClient())
        assert not isinstance(processor.client, CachedLLMClient)

    def test_custom_cache_dir(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "my_cache"
        processor = PDFProcessor(client=FakeLLMClient(), cache_dir=cache_dir)
        assert isinstance(processor.client, CachedLLMClient)
        assert processor.client._cache_dir == cache_dir

    def test_cache_dir_from_env_var(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cache_dir = tmp_path / "env_cache"
        monkeypatch.setenv("METESPARSER_CACHE_DIR", str(cache_dir))
        processor = PDFProcessor(client=FakeLLMClient())
        assert isinstance(processor.client, CachedLLMClient)
        assert processor.client._cache_dir == cache_dir

    def test_double_wrapping_prevented(self, tmp_path: Path) -> None:
        """If client is already a CachedLLMClient, don't wrap again."""
        fake = FakeLLMClient()
        already_cached = CachedLLMClient(fake, cache_dir=tmp_path / "cache1")
        processor = PDFProcessor(client=already_cached, cache_dir=tmp_path / "cache2")
        # Should be wrapped but the inner client should be the original fake
        assert isinstance(processor.client, CachedLLMClient)
        assert processor.client._client is fake


class TestCLICacheFlag:
    def test_extract_cli_cache_true_by_default(self, monkeypatch, tmp_path: Path) -> None:
        """Invoking extract command without --no-cache initializes PDFProcessor with cache=True."""
        from metesparser import cli
        from metesparser.models import LegalDescription

        captured_kwargs = {}

        class DummyProcessor:
            def __init__(self, *args, **kwargs):
                captured_kwargs.update(kwargs)

            def process_deed_pdf(self, path):
                return LegalDescription(calls=[])

        import metesparser.pdf_processor as pdf_proc_module

        monkeypatch.setattr(pdf_proc_module, "PDFProcessor", DummyProcessor)

        import metesparser.closure_checker as closure_checker_module

        dummy_result = type(
            "DummyResult",
            (),
            {
                "is_fully_verified": lambda self: True,
                "misclosure_ft": 0.0,
                "get_closure_status": lambda self: "closed",
                "closure_passed": True,
                "area_sq_ft": 1000.0,
                "confidence_score": 1.0,
                "warnings": [],
            },
        )()
        monkeypatch.setattr(
            closure_checker_module.ClosureChecker, "verify_closure", lambda *a, **kw: dummy_result
        )
        monkeypatch.setattr(
            closure_checker_module.ClosureChecker, "get_closure_summary", lambda *a, **kw: "Summary"
        )

        import metesparser.csv_builder as csv_builder_module

        monkeypatch.setattr(
            csv_builder_module.CSVBuilder, "export_verified_csv", lambda *a, **kw: None
        )

        pdf_file = tmp_path / "deed.pdf"
        pdf_file.write_text("dummy")

        monkeypatch.setattr(sys, "argv", ["metesparser", "extract", str(pdf_file)])
        cli.main()

        assert captured_kwargs.get("cache") is True

    def test_extract_cli_cache_false_with_no_cache_flag(self, monkeypatch, tmp_path: Path) -> None:
        """Invoking extract command with --no-cache initializes PDFProcessor with cache=False."""
        from metesparser import cli
        from metesparser.models import LegalDescription

        captured_kwargs = {}

        class DummyProcessor:
            def __init__(self, *args, **kwargs):
                captured_kwargs.update(kwargs)

            def process_deed_pdf(self, path):
                return LegalDescription(calls=[])

        import metesparser.pdf_processor as pdf_proc_module

        monkeypatch.setattr(pdf_proc_module, "PDFProcessor", DummyProcessor)

        import metesparser.closure_checker as closure_checker_module

        dummy_result = type(
            "DummyResult",
            (),
            {
                "is_fully_verified": lambda self: True,
                "misclosure_ft": 0.0,
                "get_closure_status": lambda self: "closed",
                "closure_passed": True,
                "area_sq_ft": 1000.0,
                "confidence_score": 1.0,
                "warnings": [],
            },
        )()
        monkeypatch.setattr(
            closure_checker_module.ClosureChecker, "verify_closure", lambda *a, **kw: dummy_result
        )
        monkeypatch.setattr(
            closure_checker_module.ClosureChecker, "get_closure_summary", lambda *a, **kw: "Summary"
        )

        import metesparser.csv_builder as csv_builder_module

        monkeypatch.setattr(
            csv_builder_module.CSVBuilder, "export_verified_csv", lambda *a, **kw: None
        )

        pdf_file = tmp_path / "deed.pdf"
        pdf_file.write_text("dummy")

        monkeypatch.setattr(sys, "argv", ["metesparser", "extract", str(pdf_file), "--no-cache"])
        cli.main()

        assert captured_kwargs.get("cache") is False
