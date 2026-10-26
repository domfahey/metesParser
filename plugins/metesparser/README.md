# MetesParser Claude plugin

This plugin runs the bundled deterministic `mp_review` engine for text-first deed review and traverse verification. It does not OCR PDFs.

## Skills

- `review-deed`: parse supplied deed text or structured input and review implemented checks.
- `verify-traverse`: check an existing CSV or JSON traverse.
- `plugin-structure`: organize and validate Claude plugin components.
- `plugin-settings`: implement and maintain project-local settings.
- `skill-development`: create, organize, and validate plugin skills.

The two deed-review skills use `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py"`; the launcher starts the locked runtime using `uv` and prints the engine's JSON result. Runtime environments and package cache are stored under the user's cache directory, keyed by the bundled engine fingerprint, so the plugin directory can remain read-only. Using the `python3` prefix avoids depending on executable mode preservation when the plugin is packaged.

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
