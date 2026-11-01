# Saved alternatives and source corrections

Commands below use the plugin root that the invoking skill printed; substitute it for `${CLAUDE_PLUGIN_ROOT}`.

The dashboard keeps exact draft inputs separate from recorded calls. Supported fields, including incomplete bearings and draft notes, recover in the same browser when local storage is available. A storage failure is shown explicitly; download a copy before leaving. Browser recovery is local to that browser and baseline, not proof of a published revision or valid geometry.

Use **Download draft** to retain the versioned JSON and the original dashboard source bundle for Cowork or another session. **Load draft JSON** checks the baseline and identities before replacing the working copy. An asynchronous load cannot replace edits made after loading started. **Reset to record** resets the selected occurrence while preserving alternatives for other occurrences. A changed baseline requires a fresh revision; do not bypass a mismatch by replacing its hash.

## Publish and inspect

Generate a template only when a draft was not already downloaded:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" revision-template BUNDLE.json --output NEW_DRAFT.json
```

Use the generated shape rather than inventing fields or IDs. Keep every tract occurrence in the inventory; use explicit remove actions instead of omission. Raw edit values are strings and retain whitespace, even when incomplete. Blank or invalid domain values remain drafts, while malformed envelopes and mismatched identities are errors.

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" save-revision BUNDLE.json --revision DRAFT.json --output-dir REVISION_STORE
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" inspect-revision BUNDLE.json --revision-dir REVISION_STORE/REVISION_ID
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" render-revision BUNDLE.json --revision-dir REVISION_STORE/REVISION_ID --output-dir NEW_VIEW
```

Successful commands return `needs_review` (exit 1); malformed input or failed publication is `error` (exit 2). Saving writes an immutable revision directory and publishes its manifest only after required artifacts succeed. Repeating identical input can recover an interrupted publication; different content cannot overwrite an existing revision ID. Inspection is read-only and replays retained results against the baseline. Rendering writes a new offline view, exact draft copy and manifest after replay. An incomplete directory without a valid manifest is not published.

## Structured course editing

The dashboard's **Add, edit, remove or reorder courses** panel produces schema `1.1` drafts. Choose the occurrence and explicit document association. Line, circular-arc and annotation inputs preserve all raw strings; removed additions retain their raw input as explicit tombstones. Retained `call_order` contains every active original or added ID. Removal needs an explicit edit entry; a missing ID alone is invalid. Original call/page identities and verbatim source language remain in the baseline.

Choose a bearing format explicitly: decimal azimuth, quadrant DMS, packed DMS azimuth or packed DMS quadrant. Packed quadrant input requires N/S and E/W. Lengths use native deed feet or explicitly converted meters/international/US survey feet; unknown foot definitions block incompatible conversion. Arcs require direction, radius and sweep or arc length; redundant chord/length/orientation evidence must agree. An inherited tangent requires a compatible, fully resolved adjacent sequence. Full circles, multiple revolutions, spirals and ambiguous radial-bearing orientation remain unsupported raw drafts.

Roles distinguish boundary, tie-in, reference and intentionally omitted evidence. An annotation uses reference/omitted role and has no geometric values. Relative structural replacements require fresh constraints; an existing raw relative-angle patch cannot silently become a full structured call. The immediate browser preview remains straight-only. After a structured edit, download, publish and render the revision to obtain shared-engine geometry, source/call records and errors. A blank or unsupported curve remains recoverable and does not show an older plot as current.

For portable SVG/PDF/DXF/GeoJSON delivery, use [export-review-package](../skills/export-review-package/SKILL.md) with the explicit published revision. `inspect-delivery BUNDLE.json --revision-dir REVISION_STORE/REVISION_ID --package-dir PACKAGE` replays a retained delivery package; it does not grant verification.

Report these states separately:

- `save_state`: whether the revision files were published.
- `state`: `parsed` or `draft`, with per-field errors.
- `current_geometry`: geometry recomputed for this revision when supported.
- `last_valid_geometry`: retained parent geometry, explicitly identified by its own revision; never substitute it as the current result.
- Invalidated placements/comparisons/exports and canonical verification, which are not reinstated by saving.

The operation never performs canonical verification or grants verified-export eligibility. A saved unresolved draft is recoverable, not a completed geometric result. Select an explicit published revision for subsequent delivery; pending or failed edits cannot silently fall back to an older one.

## Saved corridor definitions

For a requested corridor alternative, use schema `1.2` and add a `corridors` entry containing `id`, `action: retain`, and `raw_request_json`: the exact UTF-8 contents of the supplied `CorridorRequest` file as a JSON string. The entry ID must match the request ID. Keep the ordered centerline, width interval endpoints, left/right start/end widths, step/taper rules, join/cap choices, source references and error budget intact. Do not substitute the resulting polygon for its construction.

The existing save/inspect/render commands publish and replay `corridors.json` with the revision manifest. Reopening recomputes the corridor from its retained definition without requiring the original standalone producer directory. The revision view shows the source input, width intervals, construction error, and separate centerline/boundary plots. Browser load, edits, reset and download preserve these definitions; corridor construction is authored through the typed request rather than the course-editing form. Invalid or unsupported construction remains an exact recoverable draft with reasons.

A child revision names `parent_revision_id` and retains the full corridor ID inventory. Use `action: remove` with the unchanged prior raw definition for an explicit tombstone. Missing entries, reuse of a removed ID, or rebinding an existing centerline identity/provenance are rejected; value and width edits recompute the selected revision. A pending or unresolved revision cannot supply export geometry.

To export a saved corridor, use a delivery `source_bindings` entry with `revision_corridor_id` and no `artifact_dir`. Bind the SHA-256 of the selected revision's actual `manifest.json`, the freshly inspected corridor `input_sha256`, and its boundary geometry hash and layer ID. The delivery adapter validates all of these against the selected published revision and retains the exact construction in its snapshot. Standalone producer bindings remain available for independently requested corridor outputs. See [export-review-package](../skills/export-review-package/SKILL.md).

## Source corrections

Browser edits are hypothetical by default. A requested transcription correction must preserve original readings, supply actual supporting page/quote references and rationale, and use `kind: source_correction`. The adapter retains versioned `correction-evidence.json` and `source-calls.json`, with original/revised records and explicit unreviewed/not-requested statuses. These are supplied correction excerpts, not fabricated native acquisition records or proof of a complete selected description.

Use the existing source-reading/selection workflow when a fresh full selection is needed. Missing source evidence remains missing. Publish a new revision, recompute affected artifacts and request canonical verification separately when the user asks for it. Tract deletion as a source correction requires fresh selection evidence; do not reinterpret a missing tract or malformed input as deletion.

The contracts in `mp_models.revisions` and adapters in `mp_review.revisions` remain authoritative. Preserve the [artifact status boundaries](artifact-handoffs.md) when handing off revisions.
