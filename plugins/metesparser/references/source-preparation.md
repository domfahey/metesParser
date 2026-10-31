# Source preparation and handoff

Commands below use the plugin root that the invoking skill printed; substitute it for `${CLAUDE_PLUGIN_ROOT}`.

Acquisition and description-selection records preserve what was supplied, read, selected, and left uncertain. They are separate from the deterministic engine's `audit.json`, which records parsing and geometry. Neither record attests that a transcription or selection is accurate.

Keep the original document and exact UTF-8 transcript. A common working folder is:

```text
original.pdf
source-text.txt
source-acquisition.json
description-tract-a.txt
description-selection.json
review-tract-a/          # fresh deterministic review output
```

## Schema 1.1

The authoritative Pydantic contracts are `mp_models.source_handoff.SourceAcquisitionRecord` and `DescriptionSelectionRecord`. Their generated packaged JSON schemas are [acquisition](source-handoff/source-acquisition.schema.json) and [selection](source-handoff/description-selection.schema.json); the runtime additionally enforces cross-field references, safe paths, and exact-byte span rules. Complete synthetic examples are [source-acquisition.json](source-handoff/source-acquisition.json) and [description-selection.json](source-handoff/description-selection.json), alongside their byte-exact source/transcript/selected files in `references/source-handoff/`. Those fixtures are software examples, not real source-reading evidence. Keep records at schema version `1.1` and use only observed facts.

| Record | Required evidence |
| --- | --- |
| Acquisition | `id`, actual `method`, optional known `model`, actual `request` and `conversion_instructions`; `sources` with ID and exactly one root-relative `path` or opaque `attachment_id`; transcript path; source/transcript SHA-256 when computed; source `page_count` when known; page map with IDs, source/page, and transcript line bounds; `supplied_pages`, `read_pages`, `unreadable_pages`, `missing_pages`; and `uncertainties`. |
| Selection | `id`, linked `acquisition_id`, acquisition/transcript hashes when known, actual request/instructions, and separate `candidates`. Each candidate has label and `operative`/`historical`/`other` role; selected-text path/hash; source page IDs, zero-based half-open UTF-8 byte spans and one-based transcript line spans; explicit separators; exact opening/closing words; rationale; unresolved references; and carried uncertainty IDs. |

Byte offsets refer to the exact transcript bytes, including a UTF-8 BOM and CRLF bytes. Do not normalize the source before measuring spans. The validator checks structure, confined local paths, page inventory, and recorded byte identities. It cannot judge whether source reading or selection is correct.

Validate a bundle read-only after writing the records. The folder is the explicit root for all local paths; optional arguments select records at other root-relative paths:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" validate-source BUNDLE_DIR
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" validate-source BUNDLE_DIR --acquisition source-acquisition.json --selection description-selection.json
```

The package equivalent is `uv run metes-review validate-source BUNDLE_DIR`. A completed validation returns JSON status `needs_review` and exit 1, even when structure is valid and recorded hashes match. Inspect `structure`, `identity`, `source_uncertainties`, `findings`, and `limitations`; exit 1 is advisory, not a validation failure. Invalid invocation/schema or inability to produce a result returns `error` and exit 2. Validation does not rewrite records or produce verified output.

## Reading and selection evidence

Record the real conversion request, instructions, source IDs, ordering, supplied/read/unreadable/missing pages, and unresolved text. Include a Claude model identifier only when known. Compute SHA-256 over the exact source and transcript bytes when possible; otherwise use `null` and leave identity unverifiable. Distinguish unreadable content from an absent page or missing exhibit. Keep uncertainty descriptions and affected page/source references; do not turn an unknown into an empty list or claim complete coverage.

Transcribe the whole supplied document before selecting. Preserve words, notation, page order, and source wording. Mark unreadable text as `[illegible]` and retain surrounding words and affected field when apparent. Separate operative and historical descriptions. Keep noncontiguous spans in order with explicit separators; do not fabricate coordinates or splice away context. Preserve commencement calls, exceptions, qualifications, and unresolved exhibit references.

## Legacy records

Legacy schema `1.0` records are readable as legacy evidence but remain unverifiable by the `1.1` validator. Migrate by preserving the originals, then creating new `1.1` records from the underlying source and transcript: recompute hashes from exact bytes; use stable IDs for sources/pages/candidates; record only observed page and line facts; calculate selection byte ranges against the exact transcript; and carry every known uncertainty forward. Use `null` for unknown hashes/model/page counts, an opaque attachment ID when no local path exists, and explicit missing-page records when the source identifies a missing page. Do not infer missing page ranges, source identifiers, selection spans, or accuracy from legacy fields. If a fact cannot be recovered, leave it unknown and note it in `uncertainties` or `unresolved_references`.

After validation, hand off the selected text and both source records with later review artifacts. Closure cannot establish transcription completeness or correct section selection. A material unreadable or missing passage that may contain a boundary call or exception must be resolved before reporting a verified result. See [artifact handoffs](artifact-handoffs.md) for identity, reuse, and stage boundaries.

## Intake and source coverage

Return a compact intake before the requested result: intended tract/candidate and source page/span; supplied/read/missing or unknown coverage; supported and unresolved geometry; available/missing position and orientation evidence; and the exact next input needed (for example, page 3 continuation, a readable bearing digit, or the user's choice between candidates). Use “unknown” where the source does not establish a count or fact. Complete local calls can be plotted without geographic placement. Lot/block-only text, including comma-separated lot lists, is identification without a traverse; PLSS labels alone do not supply section geometry.

Account for source material using existing candidate spans, call quotations/audit records, uncertainty IDs and unresolved references. Present a source-linked table or short inventory with these parallel categories:

| Material | Required accounting |
| --- | --- |
| Parsed boundary | Actual candidate, page/span and call identity; explain calculation participation. |
| Commencement/tie or reference | Retain wording/location and reason it is outside boundary geometry. |
| Intentionally excluded | Retain page/span and rationale, including unrequested historical descriptions; never hide a boundary qualification here. |
| Unresolved/rejected | Quote/location where known, missing field or parser rejection, and effect on completeness. Unknown locations stay unknown. |

This is a delivery view of existing evidence, not a new schema or parser-derived source attestation. Where normalized text cannot be matched reliably to a narrower source span, cite the known wider passage and mark the finer association unresolved. Do not invent spans or total course counts. Reconcile parsed output with the selected text, checking unreadable middle courses, repeated/missing calls, missing continuations, and exceptions after the POB. A closing surviving subset cannot establish completeness or justify verified delivery. Retain partial plot limitations and request missing source evidence.

For several explicitly identified requested tracts, reuse one acquisition; preserve stable, distinct candidate/occurrence IDs, selections and result directories. Return a combined inventory naming each tract's source, current result, unresolved issues and retained path. Record why historical quotations and other candidates are outside scope. Continue independent results when another tract is blocked; no aggregate pass or combined traverse. On resume, invalidate only dependent selections/results, while preserving the source comparison needed to establish that other tracts remain unchanged.
