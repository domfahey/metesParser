# Dashboard bundle reference

The offline dashboard accepts one JSON object with `schema_version: "1.0"`. Its Pydantic schema is `mp_models.dashboard.DashboardBundle`; the package is the authoritative, versioned contract. This page summarizes the fields and important validation rules without duplicating every model constraint.

## Top-level fields

| Field | Purpose |
| --- | --- |
| `title` | Dashboard title. |
| `documents` | Source identity, label, optional SHA-256, and expected page count. |
| `pages` | One indexed source page, reading status, notes, and optional embedded page image. |
| `parcels` | Parcel labels used to group description occurrences. |
| `occurrences` | Each distinct description/version, transcript, its page IDs, and source reading/review status. Repeated descriptions remain separate occurrences. |
| `calls` | Source-linked course quote/text, reading status/note, and optional structured `DeedCall`. Unknown readings must not include an interpreted call. |
| `evidence` | Optional page/call-linked crops, notes, and pixel bounds. |
| `calculations` | Canonical or relative method, frame, assumptions, and optional stated area. |
| `scenarios` | Optional isolated sensitivity presets linked to a calculation and its calls. |
| `presentation` | Subtitle and method notes rendered with the review. |

All IDs are unique across record groups and references must resolve within the same occurrence. Embedded page and evidence images use PNG, JPEG, or WebP data URIs with matching SHA-256. Keep original source files and external acquisition/selection records separately; an embedded image and hash do not attest that it was reviewed.

For `canonical`, use `frame.basis: "recorded_bearings"` and source bearings. For `relative`, provide `relative` constraints, use `frame.basis: "arbitrary_local"`, and match its frame name. See [relative-analysis.md](relative-analysis.md) for its structured contract. Relative calculations accept straight courses with source-linked known distances and preserve the record's bearing values; a local frame does not create a recorded bearing.

## Status fields

The renderer reports three separate concepts:

1. `geometry_status`: `analyzed`, `unresolved`, `inconsistent`, or `blocked`. This describes whether the selected calculation could be performed and what it found.
2. `engine_status`: `checks_passed` or `needs_review`. This is canonical engine status. Relative calculations always remain `needs_review`.
3. `source_review_complete`: a derived completeness flag based on supplied page/occurrence/call attestations and expected page coverage. It cannot validate the truth of those attestations or establish source acquisition/selection quality.

For a canonical calculation, `verified_export_eligible` is true only when the canonical geometry checks pass and the calculation's source review and bundle-wide source review are complete. Relative calculations are never engine-verified or export-eligible. The dashboard CLI's top-level `verified_export_eligible` is always false and the command does not write a verified CSV. Scenario outputs are browser-only advisory results and do not change record result fields.

Per-check engine outcomes use `passed`, `failed`, `not_applicable`, and `blocked`. Legacy `CheckResult` payloads with only a `passed` boolean are supported: absent explicit status, true maps to `passed`, false to `failed`; explicit status wins when both fields exist, and serialization synchronizes `passed` to true only for `passed`. A historic boolean is not evidence that a check was skipped or performed; do not upgrade a skip to a pass.

## Output, cache, and invalidation

Run with the plugin's launcher or the package CLI and use an unused output directory:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" dashboard bundle.json --output-dir dashboard-new --cache-dir dashboard-cache
# or, in the development workspace:
uv run metes-review dashboard bundle.json --output-dir dashboard-new --cache-dir dashboard-cache
```

Valid bundles produce top-level `needs_review` (exit 1), not `checks_passed`. The output directory contains these exact artifacts:

| File | Contents |
| --- | --- |
| `source.json` | Original input bundle bytes. |
| `dashboard.html` | Self-contained offline dashboard. |
| `source-review.json` | Source/page/occurrence/call/evidence stage used by calculations. |
| `calculations.json` | Deterministically calculated record results. |
| `stage-manifest.json` | Source, calculation, and presentation hashes plus calculator and cache metadata. |
| `render-manifest.json` | Renderer fingerprint, HTML SHA-256, and presentation hash. |

Invalid input/rendering produces `error` (exit 2) with an `invalid_dashboard` detail.

The manifest separates hashes for source-review data, calculation inputs/results, and presentation. A cache hit requires matching source and calculation input hashes plus intact, validated saved stages. Editing source records, page evidence, or calculation specs/assumptions invalidates calculation reuse. Presentation changes, including title, method notes, or scenario presets, have their own hash and can reuse valid calculations. Even after a cache hit, rendering freshly recomputes and validates the deterministic geometry against the bundle before producing HTML; `cache_reused` does not mean geometry checks were skipped. Hash equality proves only that the checked data bytes/stages match; it is not a review log or evidence of a human reading a document.

## Runnable example

[`dashboard-example.json`](dashboard-example.json) is copied from the package's absolute-bearing rectangular fixture. It is synthetic, includes a tiny placeholder image, and demonstrates schema shape and a scenario only. It is not a real deed, native-reading demonstration, evidence of page coverage, or proof that the reader or host reviewed a source.

From the repository root, run it with fresh output/cache paths:

```sh
uv run metes-review dashboard plugins/metesparser/skills/deed-closure-dashboard/references/dashboard-example.json --output-dir /tmp/metesparser-dashboard-example --cache-dir /tmp/metesparser-dashboard-cache
```
