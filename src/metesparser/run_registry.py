"""Run registry for tracking prompt versions and extraction results."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime
from itertools import groupby
from pathlib import Path

import structlog
from pydantic import BaseModel, ConfigDict, Field

logger = structlog.get_logger(__name__)


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
    area_sq_ft: float | None = Field(
        ..., description="Computed area in square feet; None when area is not determined"
    )
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
    cache_enabled: bool = Field(..., description="Whether LLM caching was enabled")
    prompt_versions: dict[str, PromptVersion] = Field(
        default_factory=dict, description="Per-prompt version info"
    )
    results: RunResults = Field(..., description="Extraction quality metrics")
    parser_version: str = Field(..., description="Parser version string")


def _git_sha_for_file(file_path: Path) -> str | None:
    """Get the latest git commit SHA that modified a file.

    Returns None if the file is not in a git repository or has no commits.
    """
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
        Mapping of prompt name (without .yaml extension) to PromptVersion.
    """
    versions: dict[str, PromptVersion] = {}
    for yaml_file in sorted(prompts_dir.glob("*.yaml")):
        name = yaml_file.stem
        versions[name] = PromptVersion(
            git_sha=_git_sha_for_file(yaml_file),
            content_hash=_content_hash(yaml_file),
        )
        logger.debug("resolved_prompt_version", prompt=name, git_sha=versions[name].git_sha)
    return versions


def _slugify_pdf_name(pdf_name: str) -> str:
    """Convert PDF filename to a short slug for the manifest filename."""
    stem = Path(pdf_name).stem
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
    run_id_digest = hashlib.sha256(manifest.run_id.encode("utf-8")).hexdigest()
    filename = f"{ts}-{slug}-{run_id_digest}.json"
    path = runs_dir / filename
    path.write_text(manifest.model_dump_json(indent=2))
    logger.debug("Run manifest written", path=str(path))
    return path


def load_run_manifests(runs_dir: Path) -> list[RunManifest]:
    """Load all run manifests from a directory.

    Args:
        runs_dir: Directory containing run manifest JSON files.

    Returns:
        List of RunManifest objects, sorted by filename.
    """
    if not runs_dir.exists():
        return []
    manifests: list[RunManifest] = []
    for json_file in sorted(runs_dir.glob("*.json")):
        try:
            data = json.loads(json_file.read_text())
            manifests.append(RunManifest.model_validate(data))
        except (json.JSONDecodeError, ValueError):
            logger.warning("Skipping malformed run manifest", path=str(json_file))
    return manifests


def _short_prompt_sha(manifest: RunManifest) -> str:
    """Return the first 7 chars of the first prompt git SHA, or content hash."""
    for pv in manifest.prompt_versions.values():
        if pv.git_sha:
            return pv.git_sha[:7]
    for pv in manifest.prompt_versions.values():
        return pv.content_hash[:7]
    return "unknown"


def format_comparison_table(manifests: list[RunManifest], pdf_filter: str | None = None) -> str:
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

    header = (
        f"{'Timestamp':<20} {'Prompt':<9} {'Calls':>5} "
        f"{'Misclosure':>11} {'Confidence':>10} {'Status':>6}"
    )
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
                f"{m.results.misclosure_ft:>10.4f}' {m.results.confidence_score:>10.2f} "
                f"{status:>6}"
            )

    return "\n".join(lines)
