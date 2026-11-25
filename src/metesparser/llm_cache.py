"""File-based caching wrapper for LLM clients."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import structlog

from .llm_clients import BaseLLMClient, _read_pdf

logger = structlog.get_logger(__name__)

_CACHE_KEY_VERSION = "llm-response-cache-v2"
_MODEL_CONFIG_FIELDS = ("model", "fallback_model")


class CachedLLMClient:
    """Wraps a BaseLLMClient and caches responses to disk."""

    def __init__(self, client: BaseLLMClient, cache_dir: Path) -> None:
        self._client = client
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_key(
        self,
        prompt: str,
        response_mime_type: str | None,
        pdf_bytes: bytes | None = None,
    ) -> str:
        client_type = type(self._client)
        client_config = {
            name: getattr(self._client, name)
            for name in _MODEL_CONFIG_FIELDS
            if hasattr(self._client, name)
        }
        identity = {
            "namespace": _CACHE_KEY_VERSION,
            "client": client_type.__name__,
            "config": client_config,
            "prompt": prompt,
            "response_mime_type": response_mime_type,
            "pdf_sha256": hashlib.sha256(pdf_bytes).hexdigest() if pdf_bytes is not None else None,
        }
        serialized = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _cache_path(self, key: str) -> Path:
        return self._cache_dir / f"{key}.json"

    def _read_cache(self, key: str) -> str | None:
        path = self._cache_path(key)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return None
            response: object = data.get("response")
            if not isinstance(response, str):
                return None
            logger.debug("Cache hit", cache_key=key[:12])
            return response
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
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
        target_path = self._cache_path(key)
        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._cache_dir,
                prefix=f".{key}.",
                suffix=".tmp",
                delete=False,
            ) as tmp_file:
                tmp_path = tmp_file.name
                json.dump(entry, tmp_file, ensure_ascii=False)
                tmp_file.flush()
            os.replace(tmp_path, target_path)
            tmp_path = None
        finally:
            if tmp_path is not None:
                Path(tmp_path).unlink(missing_ok=True)
        logger.debug("Cache stored", cache_key=key[:12])

    def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
        key = self._cache_key(prompt, response_mime_type)

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
        key = self._cache_key(prompt, response_mime_type, pdf_bytes)

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
