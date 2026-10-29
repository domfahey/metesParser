# Standalone Claude chat Skill validation

Validated locally on 2026-10-29. Native Claude chat acceptance is not run.

## Distribution

- Build: `make chat-skill-build` (also exercised with `--offline` using cached build dependencies).
- Output: `dist/metesparser-chat-skill.zip`, 529,998 bytes, with SHA-256 sidecar.
- Archive SHA-256: `1caaa183196a9da066069e5b6289ad61b71d9f61518d4a5b7e2439da97ab979b`.
- Layout: one `metesparser-review/SKILL.md`, thirteen embedded procedures, six engine wheels; 81 files and 244 local Markdown links.
- Shared engine fingerprint: `673d766ed1c73f397c108a9a113e76ad57c05dc084b8452d36c6e0ddcb764db1`, unchanged from the plugin distribution. The original engine launcher is also byte-identical.
- The Skill validator, archive navigation checks, checksum checks and bundled runtime hashes passed. No plugin-root variable or source-checkout path is required by packaged instructions.

## Local checks

- `make check`: 1,614 passed, 23 skipped, 93.58% root coverage; root lint, formatting and mypy passed.
- Focused chat/plugin builder, launcher, bootstrap and packaged-navigation suite: 60 passed.
- Focused Ruff and mypy checks passed for the new builder and chat wrapper.
- Bootstrap tests cover missing tools, offline setup, failed downloads, tampered executable/cache data, unsupported platforms, interrupted-install recovery and preserved engine status codes. Cached binaries are checked against executable hashes pinned in the shipped manifest.

## Extracted archive execution

The macOS smoke test used a directory outside the repository whose path contains spaces, an empty cache, no plugin-root variable and no `uv` on `PATH`. It used Python 3.12 from the test host; this was not a Claude-hosted session.

1. Ordinary invocation without `uv` and offline setup with an empty cache returned structured errors without creating the requested output.
2. Explicit setup downloaded and verified pinned `uv` 0.9.6 and provisioned the locked engine dependencies.
3. Warm-cache setup passed offline; subsequent engine operations also ran with offline mode enabled.
4. The analytic square passed review; incomplete source text retained `needs_review`.
5. Plot and dashboard outputs were created with advisory status.
6. Revision template, save, inspection and rendering passed. A complete output ZIP was extracted into a different directory and its saved revision reopened successfully.
7. SVG, PDF and DXF delivery files were created and deterministically inspected offline.

An independent agent followed only the extracted Skill and supplied calls to produce a downloadable plot bundle. It used the plot procedure, stopped after plotting, and preserved the output's unverified/source-review status. This is a local instruction/navigation check, not a native Claude model evaluation.

## Outstanding host acceptance

Upload the exact Skill ZIP in Claude chat and record discovery, source-document reading, dependency/network policy, artifact downloads, revision reupload and interactive HTML behavior. Linux bootstrap records have verified official wheel and executable hashes, but Linux execution has not been exercised in this local run. Online Mapbox/MCP and viewer reachability remain separate optional checks.

See the [distribution and host comparison](../CLAUDE_PLUGIN.md#functional-gaps-for-claude-chat) and [chat installation guide](../../plugins/metesparser-chat/README.md).
