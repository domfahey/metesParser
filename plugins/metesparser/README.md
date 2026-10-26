# MetesParser Claude plugin

This plugin runs the bundled deterministic `mp_review` engine for text-first deed review and traverse verification. It does not OCR PDFs.

## Skills

- `review-deed`: parse supplied deed text or structured input and review implemented checks.
- `verify-traverse`: check an existing CSV or JSON traverse.

Both skills use `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/run-review.py`; the launcher starts the locked runtime using `uv` and prints the engine's JSON result. Runtime environments and package cache are stored under the user's cache directory, keyed by the bundled engine fingerprint, so the plugin directory can remain read-only. Using the `python3` prefix avoids depending on executable mode preservation when the plugin is packaged.

The engine uses exit code 0 for `checks_passed`, 1 for `needs_review`, and 2 for `error`. A passing status is limited to implemented deterministic checks and is not a legal or survey certification. See `references/review-limits.md`.
