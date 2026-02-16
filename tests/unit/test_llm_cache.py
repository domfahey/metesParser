"""Tests for LLM response caching."""

from __future__ import annotations

from pathlib import Path

from metesparser.llm_cache import CachedLLMClient


class FakeLLMClient:
    """Test double that counts calls and returns canned responses."""

    def __init__(self, text_response: str = "fake response") -> None:
        self.text_response = text_response
        self.call_count = 0

    def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
        self.call_count += 1
        return self.text_response

    def generate_text_with_pdf(
        self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
    ) -> str:
        self.call_count += 1
        return self.text_response


class TestGenerateTextCaching:
    def test_cache_miss_delegates_to_wrapped_client(self, tmp_path: Path) -> None:
        fake = FakeLLMClient(text_response="hello world")
        cached = CachedLLMClient(fake, cache_dir=tmp_path / "cache")

        result = cached.generate_text("my prompt")

        assert result == "hello world"
        assert fake.call_count == 1

    def test_cache_hit_returns_stored_result(self, tmp_path: Path) -> None:
        fake = FakeLLMClient(text_response="hello world")
        cached = CachedLLMClient(fake, cache_dir=tmp_path / "cache")

        cached.generate_text("my prompt")
        result = cached.generate_text("my prompt")

        assert result == "hello world"
        assert fake.call_count == 1

    def test_different_prompts_get_different_cache_entries(self, tmp_path: Path) -> None:
        fake = FakeLLMClient(text_response="response")
        cached = CachedLLMClient(fake, cache_dir=tmp_path / "cache")

        cached.generate_text("prompt A")
        cached.generate_text("prompt B")

        assert fake.call_count == 2

    def test_response_mime_type_affects_cache_key(self, tmp_path: Path) -> None:
        fake = FakeLLMClient(text_response="response")
        cached = CachedLLMClient(fake, cache_dir=tmp_path / "cache")

        cached.generate_text("prompt", response_mime_type=None)
        cached.generate_text("prompt", response_mime_type="application/json")

        assert fake.call_count == 2

    def test_cache_persists_across_instances(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        fake1 = FakeLLMClient(text_response="first")
        CachedLLMClient(fake1, cache_dir=cache_dir).generate_text("prompt")

        fake2 = FakeLLMClient(text_response="second")
        result = CachedLLMClient(fake2, cache_dir=cache_dir).generate_text("prompt")

        assert result == "first"
        assert fake2.call_count == 0


class TestGenerateTextWithPdfCaching:
    def test_cache_miss_delegates_to_wrapped_client(self, tmp_path: Path) -> None:
        fake = FakeLLMClient(text_response="pdf text")
        cached = CachedLLMClient(fake, cache_dir=tmp_path / "cache")
        pdf = tmp_path / "deed.pdf"
        pdf.write_bytes(b"%PDF-1.4 test content")

        result = cached.generate_text_with_pdf("extract", str(pdf))

        assert result == "pdf text"
        assert fake.call_count == 1

    def test_cache_hit_skips_wrapped_client(self, tmp_path: Path) -> None:
        fake = FakeLLMClient(text_response="pdf text")
        cached = CachedLLMClient(fake, cache_dir=tmp_path / "cache")
        pdf = tmp_path / "deed.pdf"
        pdf.write_bytes(b"%PDF-1.4 test content")

        cached.generate_text_with_pdf("extract", str(pdf))
        result = cached.generate_text_with_pdf("extract", str(pdf))

        assert result == "pdf text"
        assert fake.call_count == 1

    def test_different_pdf_content_gets_different_cache(self, tmp_path: Path) -> None:
        fake = FakeLLMClient(text_response="response")
        cached = CachedLLMClient(fake, cache_dir=tmp_path / "cache")

        pdf_a = tmp_path / "a.pdf"
        pdf_a.write_bytes(b"%PDF-1.4 content A")
        pdf_b = tmp_path / "b.pdf"
        pdf_b.write_bytes(b"%PDF-1.4 content B")

        cached.generate_text_with_pdf("extract", str(pdf_a))
        cached.generate_text_with_pdf("extract", str(pdf_b))

        assert fake.call_count == 2

    def test_renamed_pdf_with_same_content_hits_cache(self, tmp_path: Path) -> None:
        fake = FakeLLMClient(text_response="response")
        cached = CachedLLMClient(fake, cache_dir=tmp_path / "cache")

        pdf_a = tmp_path / "original.pdf"
        pdf_a.write_bytes(b"%PDF-1.4 same content")
        cached.generate_text_with_pdf("extract", str(pdf_a))

        pdf_b = tmp_path / "renamed.pdf"
        pdf_b.write_bytes(b"%PDF-1.4 same content")
        cached.generate_text_with_pdf("extract", str(pdf_b))

        assert fake.call_count == 1


class TestClearCache:
    def test_clear_removes_all_entries(self, tmp_path: Path) -> None:
        fake = FakeLLMClient(text_response="response")
        cached = CachedLLMClient(fake, cache_dir=tmp_path / "cache")

        cached.generate_text("prompt 1")
        cached.generate_text("prompt 2")

        count = cached.clear_cache()

        assert count == 2
        assert list((tmp_path / "cache").glob("*.json")) == []

    def test_clear_empty_cache_returns_zero(self, tmp_path: Path) -> None:
        fake = FakeLLMClient()
        cached = CachedLLMClient(fake, cache_dir=tmp_path / "cache")

        assert cached.clear_cache() == 0

    def test_after_clear_next_call_is_cache_miss(self, tmp_path: Path) -> None:
        fake = FakeLLMClient(text_response="response")
        cached = CachedLLMClient(fake, cache_dir=tmp_path / "cache")

        cached.generate_text("prompt")
        cached.clear_cache()
        cached.generate_text("prompt")

        assert fake.call_count == 2
