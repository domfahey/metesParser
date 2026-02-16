"""File-based caching wrapper for LLM clients."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import structlog

from .llm_clients import BaseLLMClient, _read_pdf

logger = structlog.get_logger(__name__)


class CachedLLMClient:
    """Wraps a BaseLLMClient and caches responses to disk."""

    def __init__(self, client: BaseLLMClient, cache_dir: Path) -> None:
        self._client = client
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_key(self, *parts: bytes) -> str:
        h = hashlib.sha256()
        for part in parts:
            h.update(part)
        return h.hexdigest()

    def _cache_path(self, key: str) -> Path:
        return self._cache_dir / f"{key}.json"

    def _read_cache(self, key: str) -> str | None:
        path = self._cache_path(key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            logger.debug("Cache hit", cache_key=key[:12])
            return data["response"]
        except (json.JSONDecodeError, KeyError):
            return None

    def _write_cache(
        self,
        key: str,
        response: str,
        prompt_preview: str,
        pdf_name: str | None = None,
    ) -> None:
        entry = {
            "key": key,
            "prompt_preview": prompt_preview[:100],
            "pdf_name": pdf_name,
            "response": response,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._cache_path(key).write_text(json.dumps(entry, ensure_ascii=False))
        logger.debug("Cache stored", cache_key=key[:12])

    def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
        key_parts = [prompt.encode()]
        if response_mime_type:
            key_parts.append(response_mime_type.encode())
        key = self._cache_key(*key_parts)

        cached = self._read_cache(key)
        if cached is not None:
            return cached

        result = self._client.generate_text(prompt, response_mime_type=response_mime_type)
        self._write_cache(key, result, prompt)
        return result

    def generate_text_with_pdf(
        self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
    ) -> str:
        pdf_name, pdf_bytes = _read_pdf(pdf_path)
        key_parts = [prompt.encode(), pdf_bytes]
        if response_mime_type:
            key_parts.append(response_mime_type.encode())
        key = self._cache_key(*key_parts)

        cached = self._read_cache(key)
        if cached is not None:
            return cached

        result = self._client.generate_text_with_pdf(
            prompt, pdf_path, response_mime_type=response_mime_type
        )
        self._write_cache(key, result, prompt, pdf_name=pdf_name)
        return result

    def clear_cache(self) -> int:
        count = 0
        for f in self._cache_dir.glob("*.json"):
            f.unlink()
            count += 1
        logger.info("Cache cleared", entries_removed=count)
        return count
