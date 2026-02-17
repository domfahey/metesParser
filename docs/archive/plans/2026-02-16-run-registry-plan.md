# Run Registry Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Track prompt versions (via git SHA) and extraction results per LLM run, enabling A/B comparison of prompt changes via CLI.

**Architecture:** New `run_registry.py` module with Pydantic models for run manifests, git-based prompt version resolution, and a `compare-runs` CLI subcommand. Per-run JSON files stored in gitignored `runs/` directory. Integrates into `extract_command` after verification.

**Tech Stack:** Pydantic v2, subprocess (git SHA lookup), argparse (CLI), structlog

---

### Task 1: Add `runs/` to `.gitignore`

**Files:**
- Modify: `.gitignore`

**Step 1: Add runs/ to gitignore**

Add `runs/` to the Generated output section of `.gitignore`, near the existing `results/` entry:

```
runs/
```

**Step 2: Commit**

```bash
git add .gitignore
git commit -m "chore: add runs/ to .gitignore"
```

---

### Task 2: Create `PromptVersion` and `RunManifest` models

**Files:**
- Create: `src/metesparser/run_registry.py`
- Test: `tests/unit/test_run_registry.py`

**Step 1: Write failing tests for models**

```python
"""Tests for run_registry.py — run manifest models and I/O."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from metesparser.run_registry import (
    PromptVersion,
    RunManifest,
    RunResults,
)


class TestPromptVersion:
    def test_create_with_git_sha(self) -> None:
        pv = PromptVersion(git_sha="abc1234", content_hash="sha256deadbeef")
        assert pv.git_sha == "abc1234"
        assert pv.content_hash == "sha256deadbeef"

    def test_create_without_git_sha(self) -> None:
        pv = PromptVersion(git_sha=None, content_hash="sha256deadbeef")
        assert pv.git_sha is None


class TestRunResults:
    def test_create(self) -> None:
        r = RunResults(
            call_count=4,
            closure_passed=True,
            misclosure_ft=0.001,
            area_sq_ft=2971.0,
            confidence_score=0.85,
            warnings=[],
        )
        assert r.call_count == 4
        assert r.closure_passed is True

    def test_with_warnings(self) -> None:
        r = RunResults(
            call_count=4,
            closure_passed=False,
            misclosure_ft=0.5,
            area_sq_ft=2971.0,
            confidence_score=0.6,
            warnings=["Misclosure exceeds tolerance"],
        )
        assert len(r.warnings) == 1


class TestRunManifest:
    def test_create_full(self) -> None:
        m = RunManifest(
            run_id="test-uuid",
            timestamp_utc=datetime(2026, 2, 16, tzinfo=UTC),
            source_pdf="test.pdf",
            llm_provider="openai",
            llm_model="gpt-5.2",
            cache_hit=False,
            prompt_versions={
                "extract_text_from_pdf": PromptVersion(
                    git_sha="aaa", content_hash="bbb"
                ),
            },
            results=RunResults(
                call_count=4,
                closure_passed=True,
                misclosure_ft=0.0,
                area_sq_ft=10000.0,
                confidence_score=0.9,
                warnings=[],
            ),
            parser_version="0.4.0",
        )
        assert m.schema_version == "1.0.0"
        assert m.source_pdf == "test.pdf"

    def test_roundtrip_json(self) -> None:
        m = RunManifest(
            run_id="test-uuid",
            timestamp_utc=datetime(2026, 2, 16, tzinfo=UTC),
            source_pdf="test.pdf",
            llm_provider="openai",
            llm_model="gpt-5.2",
            cache_hit=False,
            prompt_versions={},
            results=RunResults(
                call_count=4,
                closure_passed=True,
                misclosure_ft=0.0,
                area_sq_ft=10000.0,
                confidence_score=0.9,
                warnings=[],
            ),
            parser_version="0.4.0",
        )
        json_str = m.model_dump_json()
        loaded = RunManifest.model_validate_json(json_str)
        assert loaded.run_id == m.run_id
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_run_registry.py -v`
Expected: FAIL — ImportError (module doesn't exist)

**Step 3: Implement models**

```python
"""Run registry for tracking prompt versions and extraction results."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field


class PromptVersion(BaseModel):
    """Version info for a single prompt file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    git_sha: str | None = Field(default=None, description="Git commit SHA of the prompt file")
    content_hash: str = Field(..., description="SHA-256 of prompt file content")


class RunResults(BaseModel):
    """Key extraction quality metrics for one run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    call_count: int = Field(..., description="Number of calls extracted")
    closure_passed: bool = Field(..., description="Whether traverse closure passed")
    misclosure_ft: float = Field(..., description="Misclosure distance in feet")
    area_sq_ft: float = Field(..., description="Computed area in square feet")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Overall confidence 0-1")
    warnings: list[str] = Field(default_factory=list, description="Verification warnings")


class RunManifest(BaseModel):
    """Complete record of a single extraction run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(default="1.0.0")
    run_id: str = Field(..., description="UUID for this run")
    timestamp_utc: datetime = Field(..., description="Run timestamp (UTC)")
    source_pdf: str = Field(..., description="Source PDF filename")
    llm_provider: str = Field(..., description="LLM provider name")
    llm_model: str = Field(..., description="LLM model identifier")
    cache_hit: bool = Field(..., description="Whether LLM cache was used")
    prompt_versions: dict[str, PromptVersion] = Field(
        default_factory=dict, description="Per-prompt version info"
    )
    results: RunResults = Field(..., description="Extraction quality metrics")
    parser_version: str = Field(..., description="Parser version string")
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_run_registry.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/metesparser/run_registry.py tests/unit/test_run_registry.py
git commit -m "feat: add RunManifest, PromptVersion, RunResults models"
```

---

### Task 3: Implement `get_prompt_versions()`

**Files:**
- Modify: `src/metesparser/run_registry.py`
- Test: `tests/unit/test_run_registry.py`

**Step 1: Write failing tests**

```python
class TestGetPromptVersions:
    def test_returns_dict_of_prompt_versions(self, tmp_path: Path) -> None:
        prompt_file = tmp_path / "test_prompt.yaml"
        prompt_file.write_text("system_prompt: hello\n")

        from metesparser.run_registry import get_prompt_versions

        versions = get_prompt_versions(tmp_path)
        assert "test_prompt" in versions
        assert versions["test_prompt"].content_hash  # non-empty hash

    def test_content_hash_changes_with_content(self, tmp_path: Path) -> None:
        prompt_file = tmp_path / "test_prompt.yaml"

        prompt_file.write_text("version: 1\n")
        from metesparser.run_registry import get_prompt_versions

        v1 = get_prompt_versions(tmp_path)

        prompt_file.write_text("version: 2\n")
        v2 = get_prompt_versions(tmp_path)

        assert v1["test_prompt"].content_hash != v2["test_prompt"].content_hash

    def test_git_sha_is_none_outside_repo(self, tmp_path: Path) -> None:
        prompt_file = tmp_path / "test_prompt.yaml"
        prompt_file.write_text("system_prompt: hello\n")

        from metesparser.run_registry import get_prompt_versions

        versions = get_prompt_versions(tmp_path)
        # tmp_path is not inside a git repo, so git_sha should be None
        assert versions["test_prompt"].git_sha is None
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_run_registry.py::TestGetPromptVersions -v`
Expected: FAIL — ImportError

**Step 3: Implement `get_prompt_versions`**

Add to `run_registry.py`:

```python
import hashlib
import subprocess
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


def _git_sha_for_file(file_path: Path) -> str | None:
    """Get the latest git commit SHA that modified a file. Returns None if not in a repo."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", str(file_path)],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=file_path.parent,
        )
        sha = result.stdout.strip()
        return sha if sha else None
    except (subprocess.SubprocessError, FileNotFoundError):
        return None


def _content_hash(file_path: Path) -> str:
    """Compute SHA-256 hex digest of a file's content."""
    return hashlib.sha256(file_path.read_bytes()).hexdigest()


def get_prompt_versions(prompts_dir: Path) -> dict[str, PromptVersion]:
    """Resolve git SHA and content hash for each prompt YAML file.

    Args:
        prompts_dir: Directory containing prompt YAML files.

    Returns:
        Mapping of prompt name (without .yaml) to PromptVersion.
    """
    versions: dict[str, PromptVersion] = {}
    for yaml_file in sorted(prompts_dir.glob("*.yaml")):
        name = yaml_file.stem
        versions[name] = PromptVersion(
            git_sha=_git_sha_for_file(yaml_file),
            content_hash=_content_hash(yaml_file),
        )
    return versions
```

**Step 4: Run tests**

Run: `uv run pytest tests/unit/test_run_registry.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/metesparser/run_registry.py tests/unit/test_run_registry.py
git commit -m "feat: add get_prompt_versions() with git SHA + content hash"
```

---

### Task 4: Implement `write_run_manifest()` and `load_run_manifests()`

**Files:**
- Modify: `src/metesparser/run_registry.py`
- Test: `tests/unit/test_run_registry.py`

**Step 1: Write failing tests**

```python
class TestWriteRunManifest:
    def _make_manifest(self) -> "RunManifest":
        return RunManifest(
            run_id="test-uuid",
            timestamp_utc=datetime(2026, 2, 16, 15, 30, 0, tzinfo=UTC),
            source_pdf="18 Pennbrook Dr - Deed Image (11985 - 00829).pdf",
            llm_provider="openai",
            llm_model="gpt-5.2",
            cache_hit=False,
            prompt_versions={},
            results=RunResults(
                call_count=4,
                closure_passed=True,
                misclosure_ft=0.0,
                area_sq_ft=10000.0,
                confidence_score=0.9,
                warnings=[],
            ),
            parser_version="0.4.0",
        )

    def test_writes_json_file(self, tmp_path: Path) -> None:
        from metesparser.run_registry import write_run_manifest

        manifest = self._make_manifest()
        path = write_run_manifest(manifest, tmp_path)

        assert path.exists()
        assert path.suffix == ".json"
        data = json.loads(path.read_text())
        assert data["run_id"] == "test-uuid"

    def test_filename_contains_timestamp_and_pdf_stem(self, tmp_path: Path) -> None:
        from metesparser.run_registry import write_run_manifest

        manifest = self._make_manifest()
        path = write_run_manifest(manifest, tmp_path)

        assert "2026-02-16" in path.name
        assert "18-pennbrook" in path.name.lower()

    def test_creates_runs_dir_if_missing(self, tmp_path: Path) -> None:
        from metesparser.run_registry import write_run_manifest

        runs_dir = tmp_path / "runs"
        manifest = self._make_manifest()
        path = write_run_manifest(manifest, runs_dir)

        assert runs_dir.exists()
        assert path.exists()


class TestLoadRunManifests:
    def test_loads_all_manifests(self, tmp_path: Path) -> None:
        from metesparser.run_registry import load_run_manifests, write_run_manifest

        for i in range(3):
            m = RunManifest(
                run_id=f"uuid-{i}",
                timestamp_utc=datetime(2026, 2, 16, 15, i, 0, tzinfo=UTC),
                source_pdf="test.pdf",
                llm_provider="openai",
                llm_model="gpt-5.2",
                cache_hit=False,
                prompt_versions={},
                results=RunResults(
                    call_count=4,
                    closure_passed=True,
                    misclosure_ft=0.0,
                    area_sq_ft=10000.0,
                    confidence_score=0.9,
                    warnings=[],
                ),
                parser_version="0.4.0",
            )
            write_run_manifest(m, tmp_path)

        manifests = load_run_manifests(tmp_path)
        assert len(manifests) == 3

    def test_empty_dir_returns_empty_list(self, tmp_path: Path) -> None:
        from metesparser.run_registry import load_run_manifests

        manifests = load_run_manifests(tmp_path)
        assert manifests == []

    def test_skips_malformed_json(self, tmp_path: Path) -> None:
        (tmp_path / "bad.json").write_text("{invalid json")

        from metesparser.run_registry import load_run_manifests

        manifests = load_run_manifests(tmp_path)
        assert manifests == []
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_run_registry.py::TestWriteRunManifest -v`
Expected: FAIL — ImportError

**Step 3: Implement write and load functions**

Add to `run_registry.py`:

```python
import json
import re


def _slugify_pdf_name(pdf_name: str) -> str:
    """Convert PDF filename to a short slug for the manifest filename."""
    stem = Path(pdf_name).stem
    # Take first ~30 chars, lowercase, replace non-alphanumeric with hyphens
    slug = re.sub(r"[^a-z0-9]+", "-", stem[:30].lower()).strip("-")
    return slug


def write_run_manifest(manifest: RunManifest, runs_dir: Path) -> Path:
    """Write a run manifest to a JSON file.

    Args:
        manifest: The run manifest to write.
        runs_dir: Directory to write the manifest to.

    Returns:
        Path to the written JSON file.
    """
    runs_dir.mkdir(parents=True, exist_ok=True)
    ts = manifest.timestamp_utc.strftime("%Y-%m-%dT%H%M%S")
    slug = _slugify_pdf_name(manifest.source_pdf)
    filename = f"{ts}-{slug}.json"
    path = runs_dir / filename
    path.write_text(manifest.model_dump_json(indent=2))
    logger.debug("Run manifest written", path=str(path))
    return path


def load_run_manifests(runs_dir: Path) -> list[RunManifest]:
    """Load all run manifests from a directory.

    Args:
        runs_dir: Directory containing run manifest JSON files.

    Returns:
        List of RunManifest objects, sorted by timestamp.
    """
    if not runs_dir.exists():
        return []
    manifests: list[RunManifest] = []
    for json_file in sorted(runs_dir.glob("*.json")):
        try:
            data = json.loads(json_file.read_text())
            manifests.append(RunManifest.model_validate(data))
        except (json.JSONDecodeError, Exception):
            logger.warning("Skipping malformed run manifest", path=str(json_file))
    return manifests
```

**Step 4: Run tests**

Run: `uv run pytest tests/unit/test_run_registry.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/metesparser/run_registry.py tests/unit/test_run_registry.py
git commit -m "feat: add write_run_manifest() and load_run_manifests()"
```

---

### Task 5: Wire run manifest into `extract_command`

**Files:**
- Modify: `src/metesparser/cli.py:26-80` (extract_command)
- Modify: `src/metesparser/pdf_processor.py` (expose prompts_dir)
- Test: `tests/unit/test_cli.py`

**Step 1: Write failing test**

Add to `tests/unit/test_cli.py`:

```python
class TestExtractRunManifest:
    def test_extract_writes_run_manifest(self, tmp_path, monkeypatch):
        """Extract command should write a run manifest to runs/ directory."""
        from metesparser.run_registry import load_run_manifests

        # Create a fake PDF
        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")

        runs_dir = tmp_path / "runs"

        # Mock PDFProcessor to return a simple LegalDescription
        from metesparser.models import DeedCall, LegalDescription

        fake_desc = LegalDescription(
            pob_description="test",
            calls=[
                DeedCall(
                    course=1,
                    direction_text="N 0° E",
                    bearing_quadrant="N 0° E",
                    bearing_azimuth_deg_from_north=0.0,
                    distance_ft=100.0,
                ),
                DeedCall(
                    course=2,
                    direction_text="S 90° E",
                    bearing_quadrant="N 90° E",
                    bearing_azimuth_deg_from_north=90.0,
                    distance_ft=100.0,
                ),
                DeedCall(
                    course=3,
                    direction_text="S 0° W",
                    bearing_quadrant="S 0° W",
                    bearing_azimuth_deg_from_north=180.0,
                    distance_ft=100.0,
                ),
                DeedCall(
                    course=4,
                    direction_text="N 90° W",
                    bearing_quadrant="N 90° W",
                    bearing_azimuth_deg_from_north=270.0,
                    distance_ft=100.0,
                ),
            ],
            source_doc="test.pdf",
        )

        monkeypatch.setattr(
            "metesparser.cli.PDFProcessor",
            lambda **_kw: type("P", (), {"process_deed_pdf": lambda self, *a, **k: fake_desc, "prompts_dir": tmp_path})(),
        )
        monkeypatch.setattr("metesparser.cli.RUNS_DIR", runs_dir)

        from metesparser.cli import extract_command

        extract_command(str(pdf), str(tmp_path / "out.csv"))

        manifests = load_run_manifests(runs_dir)
        assert len(manifests) == 1
        assert manifests[0].source_pdf == "test.pdf"
        assert manifests[0].results.call_count == 4
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_cli.py::TestExtractRunManifest -v`
Expected: FAIL — `RUNS_DIR` not defined

**Step 3: Implement run manifest writing in extract_command**

In `cli.py`, add near the top:

```python
RUNS_DIR = Path("runs")
```

In `extract_command`, after the `closure_result` is computed and CSV is exported, add:

```python
        # Write run manifest
        try:
            from .run_registry import (
                RunManifest,
                RunResults,
                get_prompt_versions,
                write_run_manifest,
            )

            import metesparser

            prompt_versions = get_prompt_versions(processor.prompts_dir)
            manifest = RunManifest(
                run_id=run_id,
                timestamp_utc=datetime.now(UTC),
                source_pdf=pdf_file.name,
                llm_provider=llm_provider or os.getenv("METESPARSER_LLM_PROVIDER", "openai"),
                llm_model=getattr(getattr(processor, "client", None), "model", "unknown"),
                cache_hit=False,
                prompt_versions=prompt_versions,
                results=RunResults(
                    call_count=len(legal_desc.calls),
                    closure_passed=closure_result.closure_passed,
                    misclosure_ft=closure_result.misclosure_ft,
                    area_sq_ft=closure_result.area_sq_ft,
                    confidence_score=closure_result.confidence_score or 0.0,
                    warnings=closure_result.warnings,
                ),
                parser_version=metesparser.__version__,
            )
            write_run_manifest(manifest, RUNS_DIR)
        except Exception:
            command_logger.warning("Failed to write run manifest", exc_info=True)
```

Also add `from datetime import UTC, datetime` to `cli.py` imports.

**Step 4: Run tests**

Run: `uv run pytest tests/unit/test_cli.py -v`
Expected: PASS (all existing + new test)

**Step 5: Commit**

```bash
git add src/metesparser/cli.py tests/unit/test_cli.py
git commit -m "feat: write run manifest on every extract command"
```

---

### Task 6: Add `compare-runs` CLI subcommand

**Files:**
- Modify: `src/metesparser/run_registry.py` (add `format_comparison_table`)
- Modify: `src/metesparser/cli.py` (add subcommand)
- Test: `tests/unit/test_run_registry.py`

**Step 1: Write failing test for comparison formatter**

```python
class TestFormatComparisonTable:
    def test_formats_grouped_by_pdf(self) -> None:
        from metesparser.run_registry import format_comparison_table

        manifests = [
            RunManifest(
                run_id="uuid-1",
                timestamp_utc=datetime(2026, 2, 16, 15, 0, 0, tzinfo=UTC),
                source_pdf="deed_a.pdf",
                llm_provider="openai",
                llm_model="gpt-5.2",
                cache_hit=False,
                prompt_versions={
                    "normalize_text": PromptVersion(git_sha="aaa1111bbb2222ccc", content_hash="x"),
                },
                results=RunResults(
                    call_count=4,
                    closure_passed=True,
                    misclosure_ft=0.001,
                    area_sq_ft=10000.0,
                    confidence_score=0.9,
                    warnings=[],
                ),
                parser_version="0.4.0",
            ),
            RunManifest(
                run_id="uuid-2",
                timestamp_utc=datetime(2026, 2, 16, 16, 0, 0, tzinfo=UTC),
                source_pdf="deed_a.pdf",
                llm_provider="openai",
                llm_model="gpt-5.2",
                cache_hit=False,
                prompt_versions={
                    "normalize_text": PromptVersion(git_sha="ddd4444eee5555fff", content_hash="y"),
                },
                results=RunResults(
                    call_count=5,
                    closure_passed=False,
                    misclosure_ft=0.5,
                    area_sq_ft=10200.0,
                    confidence_score=0.7,
                    warnings=["Misclosure too high"],
                ),
                parser_version="0.4.0",
            ),
        ]

        output = format_comparison_table(manifests)
        assert "deed_a.pdf" in output
        assert "aaa1111" in output
        assert "ddd4444" in output
        assert "PASS" in output
        assert "FAIL" in output

    def test_empty_manifests(self) -> None:
        from metesparser.run_registry import format_comparison_table

        output = format_comparison_table([])
        assert "No runs found" in output

    def test_filter_by_pdf(self) -> None:
        from metesparser.run_registry import format_comparison_table

        manifests = [
            RunManifest(
                run_id=f"uuid-{i}",
                timestamp_utc=datetime(2026, 2, 16, 15, i, 0, tzinfo=UTC),
                source_pdf=f"deed_{c}.pdf",
                llm_provider="openai",
                llm_model="gpt-5.2",
                cache_hit=False,
                prompt_versions={},
                results=RunResults(
                    call_count=4,
                    closure_passed=True,
                    misclosure_ft=0.0,
                    area_sq_ft=10000.0,
                    confidence_score=0.9,
                    warnings=[],
                ),
                parser_version="0.4.0",
            )
            for i, c in enumerate(["a", "b"])
        ]

        output = format_comparison_table(manifests, pdf_filter="deed_a")
        assert "deed_a.pdf" in output
        assert "deed_b.pdf" not in output
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_run_registry.py::TestFormatComparisonTable -v`
Expected: FAIL — ImportError

**Step 3: Implement `format_comparison_table`**

Add to `run_registry.py`:

```python
from itertools import groupby


def _short_prompt_sha(manifest: RunManifest) -> str:
    """Return the first 7 chars of the first prompt git SHA, or content hash."""
    for pv in manifest.prompt_versions.values():
        if pv.git_sha:
            return pv.git_sha[:7]
    for pv in manifest.prompt_versions.values():
        return pv.content_hash[:7]
    return "unknown"


def format_comparison_table(
    manifests: list[RunManifest], pdf_filter: str | None = None
) -> str:
    """Format run manifests as a grouped comparison table.

    Args:
        manifests: List of run manifests to display.
        pdf_filter: Optional substring to filter by PDF name.

    Returns:
        Formatted table string.
    """
    if pdf_filter:
        manifests = [m for m in manifests if pdf_filter.lower() in m.source_pdf.lower()]

    if not manifests:
        return "No runs found."

    lines: list[str] = []
    sorted_manifests = sorted(manifests, key=lambda m: (m.source_pdf, m.timestamp_utc))

    header = f"{'Timestamp':<20} {'Prompt':<9} {'Calls':>5} {'Misclosure':>11} {'Confidence':>10} {'Status':>6}"
    separator = "-" * len(header)

    for pdf_name, group in groupby(sorted_manifests, key=lambda m: m.source_pdf):
        lines.append(f"\n{pdf_name}")
        lines.append(separator)
        lines.append(header)
        lines.append(separator)
        for m in group:
            ts = m.timestamp_utc.strftime("%Y-%m-%d %H:%M")
            prompt_sha = _short_prompt_sha(m)
            status = "PASS" if m.results.closure_passed else "FAIL"
            lines.append(
                f"{ts:<20} {prompt_sha:<9} {m.results.call_count:>5} "
                f"{m.results.misclosure_ft:>10.4f}' {m.results.confidence_score:>9.2f} "
                f"{status:>6}"
            )

    return "\n".join(lines)
```

**Step 4: Run tests**

Run: `uv run pytest tests/unit/test_run_registry.py -v`
Expected: PASS

**Step 5: Add `compare-runs` subcommand to CLI**

In `cli.py`, add a `compare_runs_command` function:

```python
def compare_runs_command(runs_dir: str | None = None, pdf_filter: str | None = None) -> None:
    """Compare extraction runs across prompt versions."""
    from .run_registry import format_comparison_table, load_run_manifests

    resolved_dir = Path(runs_dir) if runs_dir else RUNS_DIR
    manifests = load_run_manifests(resolved_dir)
    output = format_comparison_table(manifests, pdf_filter=pdf_filter)
    print(output)
```

In `main()`, after the verify subparser, add:

```python
    compare_parser = subparsers.add_parser("compare-runs", help="Compare extraction runs")
    compare_parser.add_argument(
        "--runs-dir", help="Directory containing run manifests (default: runs/)"
    )
    compare_parser.add_argument(
        "--pdf", help="Filter by PDF name (substring match)"
    )
```

In the command dispatch section, add:

```python
    elif args.command == "compare-runs":
        compare_runs_command(args.runs_dir, args.pdf)
```

**Step 6: Run full tests**

Run: `uv run pytest -v`
Expected: All tests PASS

**Step 7: Commit**

```bash
git add src/metesparser/run_registry.py src/metesparser/cli.py tests/unit/test_run_registry.py
git commit -m "feat: add compare-runs CLI command for prompt A/B testing"
```

---

### Task 7: Run linting, type checks, and full test suite

**Files:** None (verification only)

**Step 1: Run full quality gate**

Run: `make check`
Expected: All checks pass (lint, format, type, tests)

**Step 2: Fix any issues found**

Address any ruff, mypy, or test failures.

**Step 3: Commit any fixes**

```bash
git add -A
git commit -m "fix: address lint/type issues in run registry"
```

---

### Task 8: Update CLAUDE.md and CHANGELOG

**Files:**
- Modify: `CLAUDE.md` — add run registry to feature table and data flow
- Modify: `CHANGELOG.md` — add run registry entry under `[Unreleased]`

**Step 1: Add feature #35 to CLAUDE.md feature table**

```
| 35 | Run registry | `run_registry.py` | `RunManifest`, `get_prompt_versions()` | Git SHA prompt versioning, per-run JSON, compare-runs CLI |
```

**Step 2: Add to CHANGELOG.md under [Unreleased]**

Replace `_No unreleased changes._` with:

```markdown
### Added
- Run registry for prompt A/B testing (`run_registry.py`)
- `RunManifest`, `PromptVersion`, `RunResults` Pydantic models for run tracking
- `get_prompt_versions()` — resolves git SHA + content hash per prompt file
- `write_run_manifest()` / `load_run_manifests()` — per-run JSON I/O in `runs/` directory
- `metesparser compare-runs` CLI command — grouped table comparing extraction results across prompt versions
- `--pdf` filter and `--runs-dir` options for compare-runs command
```

**Step 3: Commit**

```bash
git add CLAUDE.md CHANGELOG.md
git commit -m "docs: add run registry to CLAUDE.md feature table and CHANGELOG"
```
