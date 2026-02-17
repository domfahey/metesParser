"""JSONL message types and read/write helpers."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Literal, TextIO

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag, TypeAdapter


class _Message(BaseModel):
    """Base for all JSONL messages."""

    model_config = ConfigDict(extra="allow", frozen=True)
    source: str = Field(..., description="Source PDF filename")


class RawTextMessage(_Message):
    """Output of mp-ocr: raw legal text extracted from PDF via LLM."""

    type: Literal["raw_text"] = "raw_text"
    text: str = Field(..., description="Extracted legal text")
    llm_provider: str = Field(..., description="LLM provider name")
    llm_model: str = Field(..., description="LLM model identifier")
    extracted_at: str | None = Field(default=None, description="ISO timestamp of extraction")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    cache_hit: bool | None = Field(default=None)


class LegalDescriptionMessage(_Message):
    """Output of mp-parse: structured calls + metadata."""

    type: Literal["legal_description"] = "legal_description"
    calls: list[dict[str, object]] = Field(default_factory=list)
    plss: dict[str, str | None] | None = Field(default=None)
    pob: str | None = Field(default=None)
    area_statement: str | None = Field(default=None)
    llm_provider: str | None = Field(default=None)
    llm_model: str | None = Field(default=None)
    extracted_at: str | None = Field(default=None)


class ClosureResultMessage(_Message):
    """Output of mp-verify: verification results with closure data."""

    type: Literal["closure_result"] = "closure_result"
    is_verified: bool = Field(...)
    misclosure_ft: float = Field(...)
    precision_ratio: str | None = Field(default=None)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    area_sq_ft: float | None = Field(default=None)
    checks: list[dict[str, object]] = Field(default_factory=list)
    calls: list[dict[str, object]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    llm_provider: str | None = Field(default=None)
    llm_model: str | None = Field(default=None)
    extracted_at: str | None = Field(default=None)


MessageType = Annotated[
    Annotated[RawTextMessage, Tag("raw_text")]
    | Annotated[LegalDescriptionMessage, Tag("legal_description")]
    | Annotated[ClosureResultMessage, Tag("closure_result")],
    Discriminator("type"),
]

_message_adapter: TypeAdapter[MessageType] = TypeAdapter(MessageType)


def parse_message(line: str) -> MessageType:
    """Parse a single JSONL line into a typed message."""
    return _message_adapter.validate_json(line)


def read_jsonl(stream: TextIO) -> Iterator[MessageType]:
    """Read JSONL from a stream, yield typed message objects."""
    for line in stream:
        stripped = line.strip()
        if not stripped:
            continue
        yield parse_message(stripped)


def write_jsonl(
    stream: TextIO,
    message: RawTextMessage | LegalDescriptionMessage | ClosureResultMessage,
) -> None:
    """Write one JSONL line to a stream."""
    stream.write(message.model_dump_json())
    stream.write("\n")
