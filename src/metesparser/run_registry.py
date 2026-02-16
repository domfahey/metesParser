"""Run registry for tracking prompt versions and extraction results."""

from __future__ import annotations

from datetime import datetime

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
