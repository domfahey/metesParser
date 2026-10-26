# MetesParser Claude plugin

This plugin locates metes-and-bounds descriptions in any supplied document before checking closure. Claude's native document/image reading prepares text from images and PDFs; the bundled deterministic `mp_review` engine parses the selected description and verifies geometry. No separate OCR service or conversion dependency is required.

See the [usage guide](references/usage.md) for input routing, examples, artifact meanings, and troubleshooting, and the [changelog](CHANGELOG.md) for user-visible changes. Each skill directory contains a README with its own usage example.

## Skills

- `review-metes-and-bounds`: locate the intended description first, then parse and check its closure.
- `convert-document-to-text`: use Claude's native reading for images, scanned PDFs, native PDFs, and supported documents.
- `extract-metes-and-bounds`: locate and preserve the complete description with its source references.
- `review-deed`: route deed-specific requests through the shared review workflow.
- `verify-traverse`: check an existing CSV or JSON traverse.
- `plugin-structure`: organize and validate Claude plugin components.
- `plugin-settings`: implement and maintain project-local settings.
- `skill-development`: create, organize, and validate plugin skills.

The review and verification skills use `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py"`; the launcher starts the locked runtime using `uv` and prints the engine's JSON result. Runtime environments and package cache are stored under the user's cache directory, keyed by the bundled engine fingerprint, so the plugin directory can remain read-only. Using the `python3` prefix avoids depending on executable mode preservation when the plugin is packaged.

## Locate before checking closure

Start by locating the boundary description requested, whether it appears in a survey, plat, exhibit, deed, title document, report, correspondence, image, or another source. For document/image sources, use Claude's native conversion to save text, then isolate the description verbatim. Keep page references, exceptions, and uncertainty records. Clarify ambiguous parcels or material illegibility before calculation. For an already selected description or structured call set, identify it as the intended boundary and proceed to the existing deterministic check.

Native conversion and description selection depend on Claude's reading of the source; closure cannot prove those stages were complete or accurate. Retain the acquisition and selection records described in [source preparation](references/source-preparation.md). Native reading must be available in the current Claude session; disclose unsupported or unreadable sources rather than silently substituting another provider.

The engine uses exit code 0 for `checks_passed`, 1 for `needs_review`, and 2 for `error`. A passing status is limited to implemented deterministic checks and is not a legal or survey certification. See `references/review-limits.md`.

## Project settings

From your project root, optionally create `.claude/metesparser.local.md`:

```markdown
---
enabled: true
output_dir: deed-reviews
---
```

Then run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py" review description.txt`; each review gets a fresh folder under `deed-reviews`. Explicit `--output-dir` wins. Set `enabled: false` to stop processing. Settings are read on each run, so no restart is needed. Add `.claude/*.local.md` and `.claude/*.local.json` to your project's `.gitignore`; these files are user-local.

See [settings schema and validation](references/plugin-settings.md). Verification tolerances and parsing strictness are not configurable.
