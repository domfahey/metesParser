"""Regressions for cache identity across LLM models and providers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from mp_ocr.cache import CachedLLMClient as PackageCachedLLMClient

from metesparser.llm_cache import CachedLLMClient as MonolithCachedLLMClient


class FakeClient:
    def __init__(self, response: str, *, model: str, api_key: str = "secret-token") -> None:
        self.response = response
        self.model = model
        self.api_key = api_key
        self.calls: list[tuple[str, str | None, str | None]] = []

    def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
        self.calls.append(("text", prompt, response_mime_type))
        return self.response

    def generate_text_with_pdf(
        self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
    ) -> str:
        self.calls.append(("pdf", prompt, response_mime_type))
        return self.response


class OtherProviderClient(FakeClient):
    pass


@pytest.fixture(
    params=[MonolithCachedLLMClient, PackageCachedLLMClient], ids=["monolith", "package"]
)
def cached_client_type(request: pytest.FixtureRequest) -> Any:
    return request.param


def test_model_and_provider_are_part_of_text_cache_identity(
    tmp_path: Path, cached_client_type: Any
) -> None:
    cache_dir = tmp_path / "cache"
    first = FakeClient("response from model A", model="model-a")
    assert (
        cached_client_type(first, cache_dir).generate_text("same prompt") == "response from model A"
    )

    second = FakeClient("response from model B", model="model-b")
    result = cached_client_type(second, cache_dir).generate_text("same prompt")

    assert result == "response from model B"
    assert len(first.calls) == len(second.calls) == 1

    third = OtherProviderClient("response from other provider", model="model-b")
    result = cached_client_type(third, cache_dir).generate_text("same prompt")
    assert result == "response from other provider"
    assert len(third.calls) == 1


def test_same_model_configuration_keeps_text_cache_hit(
    tmp_path: Path, cached_client_type: Any
) -> None:
    cache_dir = tmp_path / "cache"
    first = FakeClient("cached response", model="model-a")
    cached_client_type(first, cache_dir).generate_text("same prompt")

    second = FakeClient("must not be used", model="model-a")
    result = cached_client_type(second, cache_dir).generate_text("same prompt")

    assert result == "cached response"
    assert second.calls == []


def test_response_format_is_part_of_cache_identity(tmp_path: Path, cached_client_type: Any) -> None:
    cache_dir = tmp_path / "cache"
    client = FakeClient("response", model="model-a")
    cached = cached_client_type(client, cache_dir)

    cached.generate_text("same prompt", response_mime_type=None)
    cached.generate_text("same prompt", response_mime_type="application/json")

    assert len(client.calls) == 2


def test_model_is_part_of_pdf_cache_identity(tmp_path: Path, cached_client_type: Any) -> None:
    cache_dir = tmp_path / "cache"
    pdf = tmp_path / "deed.pdf"
    pdf.write_bytes(b"%PDF-1.4 tiny mocked deed")

    first = FakeClient("model A plain response", model="model-a")
    cached_client_type(first, cache_dir).generate_text_with_pdf("extract", str(pdf))

    second = FakeClient("model B JSON response", model="model-b")
    result = cached_client_type(second, cache_dir).generate_text_with_pdf("extract", str(pdf))

    assert result == "model B JSON response"
    assert len(second.calls) == 1


def test_model_configuration_includes_gemini_fallback(
    tmp_path: Path, cached_client_type: Any
) -> None:
    class GeminiLikeClient(FakeClient):
        def __init__(self, response: str, fallback_model: str) -> None:
            super().__init__(response, model="gemini-primary")
            self.fallback_model = fallback_model

    cache_dir = tmp_path / "cache"
    first = GeminiLikeClient("fallback one", "gemini-fallback-a")
    cached_client_type(first, cache_dir).generate_text("same prompt")
    second = GeminiLikeClient("fallback two", "gemini-fallback-b")

    result = cached_client_type(second, cache_dir).generate_text("same prompt")

    assert result == "fallback two"
    assert len(second.calls) == 1


def test_cache_identity_metadata_does_not_expose_credentials(
    tmp_path: Path, cached_client_type: Any
) -> None:
    cache_dir = tmp_path / "cache"
    cached_client_type(FakeClient("response", model="model-a"), cache_dir).generate_text(
        "same prompt"
    )

    files = list(cache_dir.glob("*.json"))
    assert len(files) == 1
    raw = files[0].read_text()
    entry = json.loads(raw)
    assert entry["key"] == files[0].stem
    assert "secret-token" not in raw
