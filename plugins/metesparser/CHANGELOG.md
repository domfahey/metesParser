# Changelog

Record user-visible plugin changes here. Keep pending changes under Unreleased and group entries by Added, Changed, or Fixed. Dates and release versions should describe actual releases; this plugin has not been published to a marketplace.

## [Unreleased]

### Added

- `convert-document-to-text` uses Claude's native document/image reading for PDFs, scans, images, and other supported sources, with source coverage and uncertainty records.
- `extract-metes-and-bounds` locates complete descriptions in any document, preserves source wording and locations, and separates candidate tracts.
- `review-metes-and-bounds` coordinates description identification before deterministic closure checks.
- Shared usage and source-preparation documentation, plus a README for each skill.
- Evaluation cases for native conversion, illegible survey bearings, historical versus requested descriptions, ambiguous tracts, and missing exhibits.

### Changed

- `review-deed` delegates to the document-agnostic workflow; `verify-traverse` accepts an identified structured boundary and routes unselected documents to description selection.
- Closure requests now locate the intended description before calculation. Native conversion, Claude's section selection, and deterministic verification remain distinct evidence stages.
- Scanned documents use Claude's native reading when available instead of always requiring a user-provided transcription. No separate OCR provider or conversion dependency is added.

## [1.0.0]

Initial local plugin baseline, recorded for the existing manifest version; not a public marketplace release.

### Added

- Deterministic text/CSV/JSON review engine, guarded verified export, field-level audits, and an analytic regression corpus.
- `review-deed` and `verify-traverse` skills with a locked, fingerprinted runtime and portable launcher.
- Project-local `enabled` and `output_dir` settings, with safe YAML validation and per-run reloads.
- `plugin-structure`, `plugin-settings`, and `skill-development` authoring guides.

## Validation limits

Local checks cover skill/frontmatter validation, reference links, deterministic engine behavior, runtime provisioning, and packaged launcher workflows. Native Claude document conversion and end-to-end Claude client behavior have not been exercised. Evaluation scenarios are specifications unless accompanied by recorded execution evidence.
