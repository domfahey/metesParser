---
name: export-review-package
description: Exports a selected published review revision as an immutable SVG, PDF, DXF or geographic GeoJSON delivery package, freezing explicit layer, unit, coordinate and presentation choices with source and omission metadata. Use when the user asks for a CAD file, DXF, GIS or GeoJSON export, a PDF or SVG deliverable, or a print-ready package of the reviewed tract. Not for a quick plot (use plot-metes-and-bounds), an online map (use render-online-map) or a verified CSV; blocks unresolved drafts and stale placement instead of exporting older geometry as current.
metadata:
  version: "0.1.0"
---

# Export a review package

Use this capability for an explicitly requested delivery of existing review work. It does not acquire sources, select a tract, verify calls or publish/share files externally. Require the identified source bundle, intended published revision directory and explicit export choices. A partly entered or unsaved current draft must not be replaced by a convenient older revision. Retain and resolve/save the intended draft through the [review workflow](../deed-closure-dashboard/SKILL.md) when requested before exporting it.

Read [runtime prerequisites](../../references/usage.md#runtime-prerequisites). Start from the [synthetic request](references/example.json); consult the generated [`DeliveryRequest` schema](references/request.schema.json) (about 560 lines) only for specific field definitions, for example with `grep` or `jq`. The [matching bundle](references/bundle-example.json) and [revision definition](references/revision-example.json) are software examples; the revision definition alone is not a published store. Use the supplied real published revision/baseline identities, not copied example hashes.

Derived corridor and PLSS reference layers need typed `source_bindings`:

1. Give exactly one locator: the actual standalone producer `artifact_dir`, or a corridor's `revision_corridor_id` from the selected published revision.
2. Supply the matching manifest, input and geometry hashes and the exact selected boundary/layer identity. For a revision corridor, the manifest hash identifies the selected revision manifest and its definition and geometry are freshly replayed from retained input; a standalone producer bundle is freshly replayed. A JSON attachment alone is insufficient. See [saved corridor definitions](../../references/revisions.md#saved-corridor-definitions).
3. Corridor placement binds its original centerline, then composes the retained boundary origin exactly once. A PLSS layer retains its original declared reference scene.
4. Keep source construction labeled as derived geometry; it never becomes a deed call or verification result.
5. Inline reference page bytes are omitted unless full-source inclusion is requested; retained hashes identify the original source and the explicit omission.

Freeze the requested revision ID/generation and baseline, recorded-versus-scenario geometry, selected layers/order/visibility/opacity/required flags, coordinate mode, output units, formats, labels and presentation rotation/pivot. Retain full original corridor definitions and PLSS source/dataset identities when those inputs are part of the selected work; a derived polygon alone cannot replace them.

- Local output preserves a declared local frame. Placed output requires the selected scene and explicit source-backed, freshly validated placements; no fitted alignment or inferred CRS/foot definition.
- SVG/PDF are presentation outputs. Presentation rotation changes drawing orientation, without rewriting recorded bearings or CAD/GIS coordinates. Recorded and scenario values remain distinct.
- DXF preserves supported line/arc primitives and stable layer/call identities. Geographic GeoJSON requires validated projected geographic evidence and a declared curve-linearization tolerance. Neither format reproduces raster content or drawn labels; report omissions, and block a request that requires unsupported appearance.
- `visible=false` excludes geometry while retaining the frozen membership. Opacity zero is a drawing choice; CAD/GIS geometry and tables remain present. Include full source documents only when requested; otherwise retain source references.

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" export-review BUNDLE.json --revision-dir REVISION_DIR --request REQUEST.json --output-dir NEW_DIR
```

The source-checkout equivalent begins `uv run metes-review export-review`; the adapter uses `mp_review.delivery.publish_delivery` after fresh `prepare_delivery` replay. The package is stored under the output root and `request.id`. Report `needs_review`/exit 1 with `save_state="published"` only after the final manifest exists. Failed schema, unresolved/stale revision, required representation, or conflicting publication is an error; no partial package counts as complete. Retry only the identical frozen request/snapshot.

Return requested format files, `calls.json`, `revision-calls.json`, `metrics.json`, `snapshot.json`, `request.json`, `delivery-manifest.json`, and optional full-source artifact only when actually produced. Inspect omissions and scope before calling the package complete. No HTML export is implied. Preserve request, snapshot/revision hashes, source links, units/CRS, transform policy, unavailable findings and format limitations. Stop at the local delivery package; it cannot authorize verified CSV or promote canonical/source review. See [artifact handoffs](../../references/artifact-handoffs.md).

Keep the two call sidecars distinct: `calls.json` identifies the actual selected drawing inputs; `revision-calls.json` has purpose `selected_revision_evidence`, drawing geometry mode, and revision ID/generation, and retains the selected revision’s alternatives, raw input and original source evidence. For recorded output from a scenario revision, the drawing/call table may retain 100 feet while that explicitly labeled alternative evidence retains a hypothetical 101 feet. Do not present alternative evidence as the drawing inputs.
