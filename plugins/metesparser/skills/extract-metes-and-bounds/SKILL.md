---
name: extract-metes-and-bounds
description: Locates and selects verbatim metes-and-bounds legal descriptions, with their source locations, in a document's full text so each tract can be parsed and verified separately. Use when the user asks to find the legal description or boundary description in a deed, survey or title document, which tract or parcel is described, or to pull out the description text. Not for reading a scanned or image source (use convert-document-to-text first), plotting (use plot-metes-and-bounds) or closure checks (use review-metes-and-bounds).
metadata:
  version: "0.1.0"
---

# Locate and extract metes and bounds

Inspect the supplied document text and its page map. If only an image or PDF is available, first use [Convert Document to Text](../convert-document-to-text/SKILL.md). Use Claude's native reading and reasoning to locate the description; do not introduce a separate LLM provider or claim a regex parser has established the section's boundaries.

Reuse a matching selection record and selected text when source identity/content is unchanged. Do not repeat native reading or selection just because a later stage is requested.

Read the complete supplied text before selecting a section. Apply this to any document type, not only deeds. Look for headings such as boundary description, legal description, survey description, description of premises, Schedule A, or Exhibit A, but do not require a heading. Identify the described tract using its actual boundary language. Follow references and continuation pages. Distinguish a metes-and-bounds description from street addresses, tax parcel identifiers, lot-and-block references, and historical descriptions quoted only as background. Report when no metes-and-bounds description is present.

Preserve the complete selected description verbatim. Include its beginning/commencement language, POC-to-POB tie-ins, all boundary calls and curves, stated area, exceptions and reservations affecting the described boundary, and relevant basis-of-bearing or referenced exhibit language. Do not stop merely because the calls return to the point of beginning; inspect subsequent text for qualifications and exceptions. Exclude unrelated consideration, signature, acknowledgment, and recording boilerplate, while retaining a qualification if its relationship to the boundary is uncertain and flagging that uncertainty.

Keep distinct tracts and candidate descriptions separate. Record each candidate's heading or label, page references, exact opening and closing words, and reason for selection. Ask which tract to review when the requested one is ambiguous. Do not silently choose the first description, combine separate tracts into one traverse, drop exceptions, or substitute a prior conveyance's description for the operative tract. For a referenced but missing exhibit, report the missing source; do not reconstruct it.

## Record each candidate's role

For each candidate, record the verbatim heading or introducing text and whether its role (main (parcel), addition, exception, or easement) comes from an explicit plain heading such as `PARCEL ONE:` or `TRACT 2:`, or is inferred from wording.

- With several descriptions in one deed, verified export requires every role to come from a plain heading. One inferred role blocks verified export for every tract in that deed.
- Easement and exception tracts are never eligible for verified export.
- The review and plot commands accept one description per run (several descriptions return `error`, exit 2). Hand off one description per run.

See [multiple descriptions](../../references/review-limits.md#multiple-descriptions) for the rule and [status and exit codes](../../references/review-limits.md#status-and-exit-codes) for the codes.

## Write and validate the records

1. Write `description-<label>.txt` for each selected candidate and a schema `1.1` `description-selection.json` using [source preparation and handoff](../../references/source-preparation.md).
2. Preserve an exact copy of `source-text.txt`. For noncontiguous source sections, retain their order and separate their source ranges in the record; do not splice text in a way that changes meaning.
3. Do not silently normalize spelling, bearings, distances, or units. Carry forward `[illegible]` markers and source-reading uncertainties.
4. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" validate-source BUNDLE_DIR` before handing the records off. The completed result is advisory (`needs_review`, exit 1), even when structure and hashes match. Review its uncertainty/findings fields; validation does not establish transcription or selection accuracy.
5. Compare each extracted section against the transcription and, where readable, the original document. State that the boundaries were selected by Claude and remain subject to source comparison.
6. If unreadable or missing content could omit a call, bearing, distance, exception, or section boundary, stop before issuing a verified result and request a clearer source or clarification. Do not repair the omission to force closure.

## Several requested tracts

Retain one acquisition with separate candidate IDs, selected text, and downstream output directories per tract. Record historical or background candidates and why they are outside the requested set. One blocked selection must not suppress independent requested results or imply that every tract passed. Follow [intake and source coverage](../../references/source-preparation.md#intake-and-source-coverage); never invent a total source-course count from parsed calls.

## Hand off

Return the selected description file and selection/source records as the deliverable.

1. Continue to [Plot Metes and Bounds](../plot-metes-and-bounds/SKILL.md) when a plot was requested, without automatic verification or dashboard assembly.
2. Continue to [Review Metes and Bounds](../review-metes-and-bounds/SKILL.md) only when the user also requested a geometry review.
3. Preserve unresolved qualifiers in the handoff.
4. Report native conversion, description selection, deterministic parsing, and geometric verification as separate stages; selection alone does not establish completeness, closure, or legal validity.

See [artifact handoffs](../../references/artifact-handoffs.md).
