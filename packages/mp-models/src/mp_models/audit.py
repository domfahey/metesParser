"""Audit sidecar models for pipeline traceability."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

from .base import _Model
from .closure import CheckResult


class Transformation(_Model):
    """A single transformation step in the audit trail."""

    step: str = Field(..., description="Pipeline step name")
    input: str = Field(..., description="Input value before transformation")
    output: str = Field(..., description="Output value after transformation")
    rule: str | None = Field(default=None, description="Regex pattern or method that matched")


class Decision(_Model):
    """A parsing decision with confidence and alternatives."""

    field: str = Field(..., description="Field name (e.g., 'monument_type')")
    value: str = Field(..., description="Chosen value")
    reason: str = Field(..., description="Why this value was chosen")
    alternatives: list[str] = Field(default_factory=list, description="Other values considered")
    confidence: FiniteFloat = Field(..., ge=0.0, le=1.0, description="Confidence 0.0-1.0")


class CallAudit(_Model):
    """Audit trail for a single deed call."""

    course: int = Field(
        ...,
        ge=1,
        strict=True,
        description="Course number (matches DeedCall.course)",
    )
    source_excerpt: str = Field(..., description="Verbatim text span this call was parsed from")
    transformations: list[Transformation] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


class RunMetadata(_Model):
    """Metadata about a pipeline run."""

    parser_version: str = Field(..., description="Parser version")
    llm_provider: str = Field(..., description="LLM provider name")
    llm_model: str = Field(..., description="LLM model identifier")
    prompt_hash: str = Field(..., description="SHA256 hash of prompt template")
    timestamp_utc: datetime = Field(..., description="Run timestamp (UTC)")
    source_pdf: str = Field(..., description="Source PDF filename")
    cache_enabled: bool = Field(..., description="Whether LLM response caching is enabled")
    config: dict[str, float | str | bool] = Field(
        default_factory=dict, description="Configuration snapshot"
    )


class LLMStageRecord(_Model):
    """Rendered prompt and response evidence for one audited LLM call."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, str_strip_whitespace=False, validate_assignment=True
    )

    stage: str = Field(..., description="Pipeline prompt stage name")
    prompt: str = Field(..., description="Fully rendered prompt sent to the provider")
    prompt_sha256: str = Field(..., description="SHA-256 of the rendered prompt")
    response: str = Field(..., description="Verbatim provider response")
    response_sha256: str = Field(..., description="SHA-256 of the provider response")
    provider: str = Field(..., description="Provider name, or unknown")
    model: str = Field(..., description="Model name, or unknown")


class ExtractionRecord(_Model):
    """Record of the LLM extraction step."""

    raw_llm_response: str = Field(..., description="Verbatim LLM output")
    normalized_text: str = Field(..., description="Text after normalization")
    llm_confidence: FiniteFloat | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Heuristic extraction confidence",
    )
    confidence_signals: dict[str, bool] = Field(
        default_factory=dict,
        description="Individual confidence signal results",
    )
    llm_stages: list[LLMStageRecord] = Field(
        default_factory=list, description="Audited rendered prompts and responses by stage"
    )


class VerificationAudit(_Model):
    """Audit trail for verification checks."""

    checks: list[CheckResult] = Field(default_factory=list)
    closure_summary: dict[str, float | str] = Field(default_factory=dict)
    tract_label: str | None = Field(
        default=None, description="Tract label when recorded by per-tract verification"
    )


class AuditContext(BaseModel):
    """Complete audit trail for a pipeline run.

    NOT frozen -- this is a mutable accumulator that gets populated
    as data flows through the pipeline. Other audit models are frozen.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0.0", description="Audit schema version")
    run_metadata: RunMetadata
    extraction_record: ExtractionRecord | None = Field(default=None)
    call_audits: list[CallAudit] = Field(default_factory=list)
    verification_audit: VerificationAudit | None = Field(default=None)
    tract_verification_audits: list[VerificationAudit] = Field(
        default_factory=list, description="Per-tract verification audits, in tract order"
    )
