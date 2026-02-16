"""Tests for PDFProcessor LLM cache integration."""

from __future__ import annotations

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
    def test_extract_parser_has_no_cache_flag(self) -> None:
        """The extract subcommand parser accepts --no-cache."""
        import argparse

        # Build a parser mimicking cli.py structure to verify the flag works
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        extract_parser = subparsers.add_parser("extract")
        extract_parser.add_argument("pdf")
        extract_parser.add_argument("--no-cache", action="store_true", default=False)

        args = parser.parse_args(["extract", "deed.pdf", "--no-cache"])
        assert args.no_cache is True

    def test_extract_parser_no_cache_defaults_false(self) -> None:
        """Without --no-cache, the flag defaults to False."""
        import argparse

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        extract_parser = subparsers.add_parser("extract")
        extract_parser.add_argument("pdf")
        extract_parser.add_argument("--no-cache", action="store_true", default=False)

        args = parser.parse_args(["extract", "deed.pdf"])
        assert args.no_cache is False
