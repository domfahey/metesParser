"""Version 1.1 source evidence contracts; strings and offsets preserve raw UTF-8.

Offsets are zero-based, half-open byte ranges in the acquisition transcript, not
the original document. Display lines are one-based and LF-delimited; a CR before
LF and a UTF-8 BOM remain part of the bytes. These contracts attest no accuracy.
"""

from pathlib import PurePosixPath
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

Identifier = Annotated[StrictStr, Field(pattern=r"^[A-Za-z][A-Za-z0-9_.:-]*$")]
Digest = Annotated[StrictStr, Field(pattern=r"^[a-f0-9]{64}$")]
Text = Annotated[StrictStr, Field(min_length=1)]
PositiveInt = Annotated[StrictInt, Field(ge=1)]
ByteOffset = Annotated[StrictInt, Field(ge=0)]


def _relative_path(value: str) -> str:
    if (
        not value
        or "\x00" in value
        or "\\" in value
        or ":" in value
        or PurePosixPath(value).is_absolute()
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ValueError("local references must be nonempty root-relative POSIX paths")
    return value


LocalPath = Annotated[StrictStr, AfterValidator(_relative_path)]


def _unique(values: tuple[str, ...], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {label}")


class _SourceModel(BaseModel):
    # Do not inherit the shared whitespace-stripping model for verbatim evidence.
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    @field_validator("*")
    @classmethod
    def _unicode_scalars(cls, value: Any) -> Any:
        """Reject JSON-escaped lone surrogates without replacing valid evidence."""

        def check(item: Any) -> None:
            if isinstance(item, str):
                try:
                    item.encode("utf-8")
                except UnicodeEncodeError as exc:
                    raise ValueError("source strings require valid Unicode scalar values") from exc
            elif isinstance(item, (tuple, list)):
                for member in item:
                    check(member)

        check(value)
        return value


class TranscriptReference(_SourceModel):
    path: LocalPath
    sha256: Digest | None = None


class SourceReference(_SourceModel):
    id: Identifier
    path: LocalPath | None = None
    attachment_id: Text | None = None
    sha256: Digest | None = None
    page_count: PositiveInt | None = None

    @model_validator(mode="after")
    def _one_reference(self) -> Self:
        if (self.path is None) == (self.attachment_id is None):
            raise ValueError("source requires exactly one local path or opaque attachment ID")
        return self


class MissingSourcePage(_SourceModel):
    id: Identifier
    source_id: Identifier
    page: PositiveInt


class SourcePage(MissingSourcePage):
    start_line: PositiveInt
    end_line: PositiveInt

    @model_validator(mode="after")
    def _line_order(self) -> Self:
        if self.end_line < self.start_line:
            raise ValueError("page end_line precedes start_line")
        return self


class SourceUncertainty(_SourceModel):
    id: Identifier
    description: Text
    page_ids: tuple[Identifier, ...] = ()
    source_id: Identifier | None = None
    affected_field: StrictStr | None = None
    quote: StrictStr | None = None

    @model_validator(mode="after")
    def _pages_unique(self) -> Self:
        _unique(self.page_ids, "uncertainty page IDs")
        return self


class SourceAcquisitionRecord(_SourceModel):
    schema_version: Literal["1.1"] = "1.1"
    id: Identifier
    method: Text
    model: Text | None = None
    request: Text
    conversion_instructions: Text
    sources: Annotated[tuple[SourceReference, ...], Field(min_length=1)]
    transcript: TranscriptReference
    page_map: tuple[SourcePage, ...]
    supplied_pages: tuple[Identifier, ...]
    read_pages: tuple[Identifier, ...]
    unreadable_pages: tuple[Identifier, ...]
    missing_pages: tuple[MissingSourcePage, ...]
    uncertainties: tuple[SourceUncertainty, ...]

    @model_validator(mode="after")
    def _references(self) -> Self:
        _unique(tuple(s.id for s in self.sources), "source IDs")
        _unique(tuple(p.id for p in (*self.page_map, *self.missing_pages)), "page IDs")
        _unique(tuple(u.id for u in self.uncertainties), "uncertainty IDs")
        sources = {source.id: source for source in self.sources}
        pages = {page.id: page for page in self.page_map}
        all_pages = {page.id: page for page in (*self.page_map, *self.missing_pages)}
        source_pages = [(page.source_id, page.page) for page in all_pages.values()]
        if len(source_pages) != len(set(source_pages)):
            raise ValueError("duplicate source page number")
        for page in all_pages.values():
            if page.source_id not in sources:
                raise ValueError(f"dangling source ID {page.source_id}")
            count = sources[page.source_id].page_count
            if count is not None and page.page > count:
                raise ValueError(f"page {page.id} exceeds known page count")
        previous_end = 0
        for page in sorted(self.page_map, key=lambda p: p.start_line):
            if page.start_line <= previous_end:
                raise ValueError("page transcript line ranges overlap")
            previous_end = page.end_line
        for label in ("supplied_pages", "read_pages", "unreadable_pages"):
            ids = getattr(self, label)
            _unique(ids, label)
            if not set(ids).issubset(pages):
                raise ValueError(f"dangling page ID in {label}")
        supplied = set(self.supplied_pages)
        if not set(self.read_pages).issubset(supplied) or not set(self.unreadable_pages).issubset(
            supplied
        ):
            raise ValueError("read/unreadable pages must have been supplied")
        if set(self.read_pages) & set(self.unreadable_pages):
            raise ValueError("a page cannot be both read and unreadable")
        for uncertainty in self.uncertainties:
            if not set(uncertainty.page_ids).issubset(all_pages):
                raise ValueError(f"dangling uncertainty page ID in {uncertainty.id}")
            if uncertainty.source_id is not None and uncertainty.source_id not in sources:
                raise ValueError(f"dangling uncertainty source ID in {uncertainty.id}")
            if uncertainty.source_id is not None and any(
                all_pages[p].source_id != uncertainty.source_id for p in uncertainty.page_ids
            ):
                raise ValueError("uncertainty page and source references disagree")
        return self


class SelectionSpan(_SourceModel):
    page_id: Identifier
    start_byte: ByteOffset
    end_byte: ByteOffset
    start_line: PositiveInt
    end_line: PositiveInt

    @model_validator(mode="after")
    def _order(self) -> Self:
        if self.end_byte <= self.start_byte or self.end_line < self.start_line:
            raise ValueError("span requires increasing bytes and nondecreasing lines")
        return self


class DescriptionCandidate(_SourceModel):
    id: Identifier
    label: Text
    role: Literal["operative", "historical", "other"]
    selected_text: TranscriptReference
    spans: Annotated[tuple[SelectionSpan, ...], Field(min_length=1)]
    separators: tuple[StrictStr, ...]
    opening_words: Text
    closing_words: Text
    rationale: Text
    unresolved_references: tuple[Text, ...]
    carried_uncertainty_ids: tuple[Identifier, ...]

    @model_validator(mode="after")
    def _spans(self) -> Self:
        if len(self.separators) != len(self.spans) - 1:
            raise ValueError(
                "one explicit separator is required between each adjacent pair of spans"
            )
        for first, second in zip(self.spans, self.spans[1:], strict=False):
            if first.end_byte > second.start_byte:
                raise ValueError("selection spans must be ordered and nonoverlapping")
        _unique(self.carried_uncertainty_ids, "carried uncertainty IDs")
        return self


class DescriptionSelectionRecord(_SourceModel):
    schema_version: Literal["1.1"] = "1.1"
    id: Identifier
    acquisition_id: Identifier
    acquisition_sha256: Digest | None = None
    transcript_sha256: Digest | None = None
    request: Text
    selection_instructions: Text
    candidates: Annotated[tuple[DescriptionCandidate, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def _candidates_unique(self) -> Self:
        _unique(tuple(c.id for c in self.candidates), "candidate IDs")
        return self
