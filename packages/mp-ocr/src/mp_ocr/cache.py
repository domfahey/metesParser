"""File-based caching wrapper for LLM clients."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import structlog

from .clients import BaseLLMClient, _read_pdf

logger = structlog.get_logger(__name__)

_CACHE_KEY_VERSION = "llm-response-cache-v2"
_MODEL_CONFIG_FIELDS = (
    "model",
    "model_name",
    "fallback_model",
    "thinking_level",
    "thinking_budget",
    "pdf_engine",
    "reasoning_effort",
    "base_url",
)
_SHARED_CLIENT_ALIASES: dict[tuple[str, str], str] = {
    ("mp_ocr.clients", "OpenAIClient"): "OpenAIClient",
    ("metesparser.llm_clients", "OpenAIClient"): "OpenAIClient",
    ("mp_ocr.clients", "GeminiClient"): "GeminiClient",
    ("metesparser.llm_clients", "GeminiClient"): "GeminiClient",
    ("mp_ocr.clients", "OpenRouterClient"): "OpenRouterClient",
    ("metesparser.llm_clients", "OpenRouterClient"): "OpenRouterClient",
}


def _is_cache_wrapper(client: object) -> bool:
    """Return True when *client* behaves like a CachedLLMClient wrapper."""
    return callable(getattr(type(client), "clear_cache", None)) and hasattr(client, "_client")


def _unwrap_client_chain(client: BaseLLMClient) -> BaseLLMClient:
    """Unwrap nested cache wrappers (with cycle guard) to the underlying client."""
    current: Any = client
    seen: set[int] = set()
    while id(current) not in seen and _is_cache_wrapper(current):
        seen.add(id(current))
        next_client = current._client
        if id(next_client) in seen:
            break
        current = next_client
    return cast(BaseLLMClient, current)


class CachedLLMClient:
    """Wraps a BaseLLMClient and caches responses to disk."""

    def __init__(self, client: BaseLLMClient, cache_dir: Path) -> None:
        self._client = client
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def model_name(self) -> str | None:
        """Return the underlying LLM model identifier if available."""
        inner = _unwrap_client_chain(self)
        if inner is self or _is_cache_wrapper(inner):
            return None
        name: object = getattr(inner, "model_name", None)
        if isinstance(name, str) and name:
            return name
        model: object = getattr(inner, "model", None)
        return model if isinstance(model, str) and model else None

    def _cache_key(
        self,
        prompt: str,
        response_mime_type: str | None,
        pdf_bytes: bytes | None = None,
    ) -> str:
        target = _unwrap_client_chain(self)
        client_type = type(target)
        client_id = _SHARED_CLIENT_ALIASES.get(
            (client_type.__module__, client_type.__qualname__),
            f"{client_type.__module__}.{client_type.__qualname__}",
        )
        client_config = {
            name: getattr(target, name) for name in _MODEL_CONFIG_FIELDS if hasattr(target, name)
        }
        identity = {
            "namespace": _CACHE_KEY_VERSION,
            "client": client_id,
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
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return None
            response: object = data.get("response")
            if not isinstance(response, str):
                return None
            logger.debug("Cache hit", cache_key=key[:12])
            return response
        except (OSError, json.JSONDecodeError, KeyError, TypeError, UnicodeDecodeError):
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
        tmp_path: Path | None = None
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._cache_dir,
                prefix=f".{key}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                tmp_path = Path(handle.name)
                handle.write(json.dumps(entry, ensure_ascii=False))
            os.replace(tmp_path, self._cache_path(key))
            tmp_path = None
            logger.debug("Cache stored", cache_key=key[:12])
        except OSError as exc:
            logger.warning("Cache write failed", cache_key=key[:12], error=str(exc))
        finally:
            if tmp_path is not None and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

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
