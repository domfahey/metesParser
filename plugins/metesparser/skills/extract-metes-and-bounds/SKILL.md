---
name: extract-metes-and-bounds
description: This skill should be used when the user asks to "locate the metes and bounds description", "extract the legal description", or "find the boundary description" within a complete document's text. Selects verbatim parcel descriptions and their source locations before deterministic parsing and verification.
metadata:
  version: "0.1.0"
---

# Locate and extract metes and bounds

Inspect the supplied document text and its page map. If only an image or PDF is available, first use [Convert Document to Text](../convert-document-to-text/SKILL.md). Use Claude's native reading and reasoning to locate the description; do not introduce a separate LLM provider or claim a regex parser has established the section's boundaries.

Reuse a matching selection record and selected text when source identity/content is unchanged. Do not repeat native reading or selection just because a later stage is requested.

Read the complete supplied text before selecting a section. Apply this to any document type, not only deeds. Look for headings such as boundary description, legal description, survey description, description of premises, Schedule A, or Exhibit A, but do not require a heading. Identify the described tract using its actual boundary language. Follow references and continuation pages. Distinguish a metes-and-bounds description from street addresses, tax parcel identifiers, lot-and-block references, and historical descriptions quoted only as background. Report when no metes-and-bounds description is present.

Preserve the complete selected description verbatim. Include its beginning/commencement language, POC-to-POB tie-ins, all boundary calls and curves, stated area, exceptions and reservations affecting the described boundary, and relevant basis-of-bearing or referenced exhibit language. Do not stop merely because the calls return to the point of beginning; inspect subsequent text for qualifications and exceptions. Exclude unrelated consideration, signature, acknowledgment, and recording boilerplate, while retaining a qualification if its relationship to the boundary is uncertain and flagging that uncertainty.

Keep distinct parcels and candidate descriptions separate. Record each candidate's heading or label, page references, exact opening and closing words, and reason for selection. Ask which parcel to review when the requested tract is ambiguous. Do not silently choose the first description, combine separate parcels into one traverse, drop exceptions, or substitute a prior conveyance's description for the operative parcel. For a referenced but missing exhibit, report the missing source; do not reconstruct it.

Write `description-<label>.txt` for each selected candidate and `description-selection.json` using [source preparation and handoff](../../references/source-preparation.md). Preserve an exact copy of `source-text.txt`. For noncontiguous source sections, retain their order and separate their source ranges in the record; do not splice text in a way that changes meaning. Do not silently normalize spelling, bearings, distances, or units. Carry forward `[illegible]` markers and source-reading uncertainties.

Compare each extracted section against the transcription and, where readable, the original document before handing it off. State that the boundaries were selected by Claude and remain subject to source comparison. If unreadable or missing content could omit a call, bearing, distance, exception, or section boundary, stop before issuing a verified result and request a clearer source or clarification. Do not repair the omission to force closure.

Return the selected description file and selection/source records as the deliverable. Continue to [Review Metes and Bounds](../review-metes-and-bounds/SKILL.md) only when the user also requested a geometry review. Preserve unresolved qualifiers in the handoff. Report native conversion, description selection, deterministic parsing, and geometric verification as separate stages; selection alone does not establish completeness, closure, or legal validity. See [artifact handoffs](../../references/artifact-handoffs.md).
