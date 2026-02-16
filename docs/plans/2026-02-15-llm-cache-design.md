# LLM Output Caching Design

## Problem

LLM extraction results are non-deterministic between runs even with `temperature=0`. This causes inconsistent call extraction — the same PDF may yield 0 calls on one run and 8 on the next.

## Solution

A `CachedLLMClient` wrapper that intercepts all LLM calls, caches responses to disk keyed by `SHA-256(prompt + input_bytes)`, and returns cached results on subsequent runs.

## Architecture

### New file: `src/metesparser/llm_cache.py`

`CachedLLMClient` wraps any `BaseLLMClient` and satisfies the same protocol:

- `generate_text(prompt, response_mime_type?)` — key = `sha256(prompt + response_mime_type)`
- `generate_text_with_pdf(prompt, pdf_path, response_mime_type?)` — key = `sha256(prompt + pdf_bytes + response_mime_type)`
- `clear_cache()` — deletes all cached entries, returns count

### Cache storage

File-based JSON in `.cache/llm/`, one file per unique call:

```
.cache/llm/
├── ab3f...7d.json
└── c1e2...9a.json
```

Each file contains:
```json
{
  "key": "ab3f...7d",
  "prompt_preview": "Extract all text from...",
  "pdf_name": "24 Pennbrook Dr.pdf",
  "response": "ALL that certain lot...",
  "timestamp": "2026-02-15T12:00:00Z"
}
```

### Cache key

`SHA-256` of concatenated: prompt text + pdf file bytes (if applicable) + response_mime_type (if applicable). Content-based, so renaming a file doesn't invalidate the cache.

### Integration

`PDFProcessor.__init__` wraps the client when caching is enabled:

```python
if cache_enabled:
    self.client = CachedLLMClient(self.client, cache_dir=cache_dir)
```

### Configuration

| Method | How | Default |
|--------|-----|---------|
| Environment variable | `METESPARSER_LLM_CACHE=false` | enabled |
| Environment variable | `METESPARSER_CACHE_DIR=path` | `.cache/llm` |
| CLI flag | `--no-cache` on `extract` command | enabled |
| Constructor | `PDFProcessor(cache=False)` | enabled |

### .gitignore

Add `.cache/` entry.

## Testing

Unit tests with a `FakeLLMClient`:
- Cache miss → delegates to wrapped client, stores result
- Cache hit → returns stored result without calling wrapped client
- Key stability — same inputs produce same key
- `clear_cache()` removes files and returns count
- `cache=False` passes through without caching
- PDF content change invalidates cache
- Prompt change invalidates cache
