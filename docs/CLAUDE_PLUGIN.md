# Claude plugin and deterministic review

The `mp-review` workspace package reviews supplied UTF-8 TXT/Markdown, CSV, or JSON without OCR, provider keys, or LLM calls. The Claude plugin adds two skills: `review-deed` and `verify-traverse`. All parsing, numeric checks, and verified export decisions run in Python.

```sh
uv sync --extra dev --extra gemini
uv run python -m mp_review review description.txt --output-dir output/review-new
uv run python -m mp_review verify calls.csv --output-dir output/verify-new
make review-corpus
make plugin-build
```

Output directories must not exist. `--area SQFT` supplies a stated area for comparison; never substitute an inferred area. JSON input accepts a list of `DeedCall` objects or a `LegalDescription` object with `calls`. CSV input requires the complete ordered 21-column schema. Multiple named parcels are rejected for separate review.

The CLI writes one JSON result to stdout and diagnostic logs to stderr. Review exits are 0 (`checks_passed`), 1 (`needs_review`), and 2 (`error`). Corpus exits are 0 (`passed`), 1 (`failed`), and 2 for invalid configuration. A review folder contains the original source, parsed calls, verification results, field-level audit, and escaped HTML report. Verified CSV is issued only when the existing verification and export gates pass. Source SHA-256 and deterministic execution metadata are recorded; no LLM extraction is implied.

The reviewed corpus lives in `packages/mp-review/tests/fixtures/corpus.json`. Expectations are explicit analytic values and behaviors; the runner compares them with tolerances and reports individual failures. Existing generated sample-deed ground truth is not treated as authoritative. Add reviewed cases with source provenance rather than copying actual output into expected values.

`scripts/build_claude_plugin.py` builds six engine wheels from the current working tree, pins external runtime dependencies to root `uv.lock` versions, and creates `dist/metesparser-plugin.zip` plus a SHA-256 sidecar. The ZIP contains the manifest at its root, two skills, a launcher, wheel hashes, and a separate runtime lock. Build artifacts include current uncommitted engine changes. Rebuild after changing engine or plugin files.

Extract the ZIP to a fresh directory. In Claude Code, use `claude --plugin-dir /absolute/path/to/extracted-plugin` for a local session. For Cowork, use its plugin upload interface with the built ZIP. No account installation or publication is performed by the build. The launcher requires Python 3.11+ and `uv`; first use downloads the pinned third-party runtime dependencies and creates a fingerprint-specific environment in the user's cache. The source plugin directory has no built runtime: use the extracted distribution for execution. The release is portable Python packaging, but OS-specific client acceptance must still be tested on each target.

Closure does not establish source completeness or legal correctness. Arc–arc and arc–straight intersection checks are outside the engine's current topology checks. Curved boundaries need manual topology review even when implemented checks pass. Missing bearings remain unknown. The skills report these limitations and do not repair source data.
