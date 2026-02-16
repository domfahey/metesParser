# Run Registry Design — Prompt A/B Testing

## Goal

Track prompt versions and extraction results across LLM runs to enable A/B comparison of prompt changes. Know which prompt version produced which results for any given PDF.

## Decisions

- **Prompt versioning**: Git SHA of each prompt file (content hash fallback)
- **Storage**: Per-run JSON files in `runs/` directory (gitignored)
- **Comparison**: CLI command `metesparser compare-runs`

## Run Manifest Schema

Each `metesparser extract` invocation writes a JSON file to `runs/<timestamp>-<pdf-stem>.json`:

```json
{
  "schema_version": "1.0.0",
  "run_id": "uuid4",
  "timestamp_utc": "2026-02-16T15:30:00Z",
  "source_pdf": "18 Pennbrook Dr - Deed Image (11985 - 00829).pdf",
  "llm_provider": "openai",
  "llm_model": "gpt-5.2",
  "cache_hit": true,
  "prompt_versions": {
    "extract_text_from_pdf": {"git_sha": "abc1234", "content_hash": "sha256..."},
    "extract_legal_description": {"git_sha": "abc1234", "content_hash": "sha256..."},
    "normalize_text": {"git_sha": "def5678", "content_hash": "sha256..."}
  },
  "results": {
    "call_count": 4,
    "closure_passed": true,
    "misclosure_ft": 0.0001,
    "area_sq_ft": 2971.0,
    "confidence_score": 0.85,
    "warnings": []
  },
  "parser_version": "0.4.0"
}
```

## Components

### 1. Prompt Version Resolution

Utility function `get_prompt_versions(prompts_dir) -> dict[str, PromptVersion]`:

- For each `.yaml` file in `prompts/`, run `git log -1 --format=%H -- <path>`
- Compute SHA-256 of file content as fallback
- Returns mapping of prompt name to `{git_sha, content_hash}`
- Replaces the existing single `prompt_hash` on `RunMetadata`

### 2. Run Manifest Writer (`run_registry.py`)

New module with:

- `PromptVersion` — Pydantic model: `git_sha: str | None`, `content_hash: str`
- `RunResults` — Pydantic model: `call_count`, `closure_passed`, `misclosure_ft`, `area_sq_ft`, `confidence_score`, `warnings`
- `RunManifest` — Pydantic model matching the full JSON schema above
- `write_run_manifest(manifest, runs_dir)` — writes JSON to `runs/<timestamp>-<pdf-stem>.json`
- `load_run_manifests(runs_dir)` — reads and parses all manifests from directory
- `get_prompt_versions(prompts_dir)` — resolves git SHA + content hash per prompt

Called at the end of `process_deed_pdf()` — always runs (not gated on `audit=True`).

### 3. CLI Compare Command

New `metesparser compare-runs` subcommand:

- Loads all run manifests from `runs/` (default) or `--runs-dir <path>`
- Groups by PDF name
- For each PDF, prints a table sorted by timestamp:
  - Columns: timestamp, prompt SHA (short 7-char), call count, misclosure, confidence, pass/fail
- `--pdf <name>` filter to focus on one deed
- Output is formatted table to stdout

### 4. Integration Points

- `PDFProcessor.process_deed_pdf()` — after building `LegalDescription`, construct and write `RunManifest`
- `cli.py` — add `compare-runs` subcommand
- `.gitignore` — add `runs/` directory
- `RunMetadata.prompt_hash` — replace single hash with `prompt_versions` dict (backward-compatible: keep field, populate from first prompt)

## What This Does NOT Include

- Token counting or cost tracking (out of scope)
- HTML comparison reports (CLI table is sufficient)
- Experiment framework for batch re-running (YAGNI)
- Automatic prompt version bumping
