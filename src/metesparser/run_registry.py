"""Run registry for tracking prompt versions and extraction results."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime
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
