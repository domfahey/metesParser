# LLM Output Caching Implementation Plan

> Historical snapshot: This plan/design document captures implementation context on its date. It may not reflect current code, defaults, test counts, or workflow state.


> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add file-based LLM response caching so PDF extraction produces consistent results across runs.

**Architecture:** A `CachedLLMClient` wrapper class in `src/metesparser/llm_cache.py` that satisfies the `BaseLLMClient` protocol by delegating to a wrapped client on cache miss and returning cached JSON on cache hit. `PDFProcessor` wraps its client at init time when caching is enabled (default). Cache keys are SHA-256 of prompt + input bytes.

**Tech Stack:** Python stdlib only (`hashlib`, `json`, `pathlib`), structlog for logging, pytest for tests.

---

### Task 1: Create `CachedLLMClient` with `generate_text` caching

**Files:**
- Create: `src/metesparser/llm_cache.py`
- Create: `tests/unit/test_llm_cache.py`

**Step 1: Write the failing tests**

In `tests/unit/test_llm_cache.py`:

```python
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
        assert fake.call_count == 1  # only called once

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

        assert result == "first"  # from cache, not fake2
        assert fake2.call_count == 0
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_llm_cache.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'metesparser.llm_cache'`

**Step 3: Write minimal implementation**

In `src/metesparser/llm_cache.py`:

```python
"""File-based caching wrapper for LLM clients."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
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
            "timestamp": datetime.now(timezone.utc).isoformat(),
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
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_llm_cache.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add src/metesparser/llm_cache.py tests/unit/test_llm_cache.py
git commit -m "feat: add CachedLLMClient with generate_text caching"
```

---

### Task 2: Add `generate_text_with_pdf` caching tests

**Files:**
- Modify: `tests/unit/test_llm_cache.py`

**Step 1: Write the failing tests**

Append to `tests/unit/test_llm_cache.py`:

```python
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

        assert fake.call_count == 1  # same content = cache hit
```

**Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_llm_cache.py -v`
Expected: All 9 tests PASS (implementation already handles this)

**Step 3: Commit**

```bash
git add tests/unit/test_llm_cache.py
git commit -m "test: add generate_text_with_pdf caching tests"
```

---

### Task 3: Add `clear_cache` tests

**Files:**
- Modify: `tests/unit/test_llm_cache.py`

**Step 1: Write the tests**

Append to `tests/unit/test_llm_cache.py`:

```python
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

        assert fake.call_count == 2  # called twice, cache was cleared
```

**Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_llm_cache.py -v`
Expected: All 12 tests PASS

**Step 3: Commit**

```bash
git add tests/unit/test_llm_cache.py
git commit -m "test: add clear_cache tests"
```

---

### Task 4: Integrate caching into `PDFProcessor`

**Files:**
- Modify: `src/metesparser/pdf_processor.py` (lines 23-39)
- Create: `tests/unit/test_pdf_processor_cache.py`

**Step 1: Write the failing test**

In `tests/unit/test_pdf_processor_cache.py`:

```python
"""Tests for PDFProcessor LLM cache integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

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
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_pdf_processor_cache.py -v`
Expected: FAIL — `PDFProcessor.__init__` doesn't accept `cache` or `cache_dir` params yet

**Step 3: Modify `PDFProcessor.__init__`**

In `src/metesparser/pdf_processor.py`, update the `__init__` method:

```python
def __init__(
    self,
    api_key: str | None = None,
    *,
    provider: str | None = None,
    client: BaseLLMClient | None = None,
    cache: bool | None = None,
    cache_dir: Path | None = None,
):
    self._configured_api_key = api_key
    self.client = client or self._create_client(provider)
    self.prompts_dir = Path(__file__).parent.parent.parent / "prompts"

    # Wrap client with caching if enabled
    cache_enabled = cache if cache is not None else os.getenv("METESPARSER_LLM_CACHE", "true").lower() != "false"
    if cache_enabled:
        from .llm_cache import CachedLLMClient

        resolved_cache_dir = cache_dir or Path(os.getenv("METESPARSER_CACHE_DIR", ".cache/llm"))
        self.client = CachedLLMClient(self._unwrap_client(self.client), cache_dir=resolved_cache_dir)

@staticmethod
def _unwrap_client(client: BaseLLMClient) -> BaseLLMClient:
    """Unwrap an already-cached client to avoid double-wrapping."""
    from .llm_cache import CachedLLMClient

    if isinstance(client, CachedLLMClient):
        return client._client
    return client
```

Also add `from pathlib import Path` to the imports (already present).

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_pdf_processor_cache.py tests/unit/test_llm_cache.py -v`
Expected: All tests PASS

**Step 5: Run full test suite to check for regressions**

Run: `uv run pytest tests/ -x -q`
Expected: All existing tests PASS (some tests that inject `client=` will now get it wrapped — verify no breakage)

**Step 6: Commit**

```bash
git add src/metesparser/pdf_processor.py tests/unit/test_pdf_processor_cache.py
git commit -m "feat: integrate LLM cache into PDFProcessor (enabled by default)"
```

---

### Task 5: Add `--no-cache` CLI flag

**Files:**
- Modify: `src/metesparser/cli.py` (lines 154-163, 194-195)

**Step 1: Write the test**

Append to `tests/unit/test_pdf_processor_cache.py`:

```python
class TestCLICacheFlag:
    def test_extract_parser_accepts_no_cache_flag(self) -> None:
        """Verify argparse wiring — the flag is parsed without error."""
        import argparse
        from metesparser.cli import main

        # We just need to check the parser accepts the flag, not run the full command
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        extract_parser = subparsers.add_parser("extract")
        extract_parser.add_argument("pdf")
        extract_parser.add_argument("--no-cache", action="store_true")

        args = parser.parse_args(["extract", "deed.pdf", "--no-cache"])
        assert args.no_cache is True
```

**Step 2: Modify `cli.py`**

Add after the `--llm-provider` argument (around line 163):

```python
extract_parser.add_argument(
    "--no-cache",
    action="store_true",
    default=False,
    help="Disable LLM response caching (re-query the LLM for every call)",
)
```

Update `extract_command` signature (line 27) and the call site (line 195):

```python
# Signature (line 27):
def extract_command(
    pdf_path: str, output: str | None = None, llm_provider: str | None = None, *, no_cache: bool = False
) -> None:

# Inside extract_command, update PDFProcessor init (line 52):
        processor = PDFProcessor(provider=llm_provider, cache=not no_cache)

# Call site (line 195):
        extract_command(args.pdf, args.output, args.llm_provider, no_cache=args.no_cache)
```

**Step 3: Run tests**

Run: `uv run pytest tests/unit/test_pdf_processor_cache.py tests/e2e/ -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add src/metesparser/cli.py tests/unit/test_pdf_processor_cache.py
git commit -m "feat: add --no-cache CLI flag to extract command"
```

---

### Task 6: Add `.cache/` to `.gitignore` and verify

**Files:**
- Modify: `.gitignore` (already has `.cache/` on line 70)

**Step 1: Verify `.cache/` is already gitignored**

Check line 70 of `.gitignore` — it already has `.cache/`. No change needed.

**Step 2: Run lint and full test suite**

Run: `make lint && uv run pytest tests/ -q`
Expected: Lint passes, all tests pass

**Step 3: Commit (only if changes were needed)**

No commit needed if `.cache/` is already in `.gitignore`.

---

### Task 7: Final integration verification

**Step 1: Run full test suite with coverage**

Run: `uv run pytest tests/ --cov=src/metesparser/llm_cache --cov=src/metesparser/pdf_processor --cov-report=term-missing -q`
Expected: All tests pass, `llm_cache.py` has >90% coverage

**Step 2: Run lint**

Run: `make lint`
Expected: Passes

**Step 3: Manual smoke test**

Run: `uv run python scripts/extract_sample_deeds.py` twice and verify second run uses cache (look for "Cache hit" debug logs or much faster execution).

**Step 4: Final commit if any cleanup needed**

```bash
git add -A && git commit -m "chore: final cleanup for LLM cache feature"
```
