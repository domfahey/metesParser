# Source preparation and handoff

The acquisition and selection records are separate from the deterministic engine's `audit.json`. That engine records parsing and geometry; it does not attest that Claude's transcription or section selection matches a document. Retain these records alongside review outputs and preserve the original source.

Use a fresh working folder; do not overwrite source documents or existing review artifacts. Keep this layout as a convention, without requiring additional conversion software:

```text
source-text.txt
source-acquisition.json
description-parcel-a.txt
description-selection.json
review-parcel-a/          # New directory created by the deterministic review engine
```

## Native reading record

Record the actual conversion request and instructions applied, the resulting full transcription file, native reading method, source filenames or attachment identifiers, pages supplied and read, ordering, missing pages, and uncertainties. Include the Claude model identifier only when known. Compute source/text SHA-256 hashes with available tools when possible; otherwise leave hashes null and disclose that they were not computed. Do not store a guessed hash or mark native transcription as deterministic.

An acquisition record may use this shape (replace examples with observed facts):

```json
{
  "schema_version": "1.0",
  "method": "claude_native_document_reading",
  "source_identifiers": ["source.pdf"],
  "source_sha256": null,
  "model": null,
  "request": "Convert the supplied document to text.",
  "conversion_instructions": "Record the actual instructions applied here.",
  "transcription_file": "source-text.txt",
  "transcription_sha256": null,
  "page_map": [{"source": "source.pdf", "page": 1, "start_line": 1, "end_line": 42}],
  "missing_pages": [],
  "uncertainties": []
}
```

Use line numbers from the saved transcript. Record unreadable text with page, surrounding quotation, and affected field when apparent. Do not convert an absent exhibit into an empty uncertainty list.

## Description selection record

Record the actual selection request/instructions and each candidate's label, selected text file, source ranges, exact opening and closing words, selection rationale, unresolved references, and carried uncertainties. Use observed transcript line ranges and page references, rather than invented coordinates. Record noncontiguous source ranges separately and explain any inserted separators. Keep each selected section verbatim; retain the complete transcription as the comparison source.

Do not represent a source-derived street address as a metes-and-bounds description. For multiple candidate tracts, request clarification unless the requested parcel is clear from the task. Preserve historic description candidates as distinct from the selected operative description.

## Stage boundaries

1. Convert with Claude's native document/image capabilities and disclose reading gaps.
2. Locate and copy the operative metes-and-bounds description with its context and source locations.
3. Resolve parcel ambiguity or material illegibility before verification.
4. Run the existing deterministic review on the selected text. Link its artifacts to these acquisition/selection records in the response.

Never imply that geometric closure proves correct transcription or section selection. A successful deterministic result does not remove missing-page, transcription, or section-boundary uncertainties.
