# Standalone Claude chat Skill validation

Validated locally on 2026-10-29. Native Claude chat acceptance is not run.

## Initial distribution (`ac4c3cf`)

- Build: `make chat-skill-build` (also exercised with `--offline` using cached build dependencies).
- Output: `dist/metesparser-chat-skill.zip`, 529,998 bytes, with SHA-256 sidecar.
- Archive SHA-256: `1caaa183196a9da066069e5b6289ad61b71d9f61518d4a5b7e2439da97ab979b`.
- Layout: one `metesparser-review/SKILL.md`, thirteen embedded procedures, six engine wheels; 81 files and 244 local Markdown links.
- Shared engine fingerprint: `673d766ed1c73f397c108a9a113e76ad57c05dc084b8452d36c6e0ddcb764db1`, unchanged from the plugin distribution. The original engine launcher is also byte-identical.
- The Skill validator, archive navigation checks, checksum checks and bundled runtime hashes passed. No plugin-root variable or source-checkout path is required by packaged instructions.

## Initial local checks

- `make check`: 1,614 passed, 23 skipped, 93.58% root coverage; root lint, formatting and mypy passed.
- Focused chat/plugin builder, launcher, bootstrap and packaged-navigation suite: 60 passed.
- Focused Ruff and mypy checks passed for the new builder and chat wrapper.
- Bootstrap tests cover missing tools, offline setup, failed downloads, tampered executable/cache data, unsupported platforms, interrupted-install recovery and preserved engine status codes. Cached binaries are checked against executable hashes pinned in the shipped manifest.

## Initial extracted archive execution

The macOS smoke test used a directory outside the repository whose path contains spaces, an empty cache, no plugin-root variable and no `uv` on `PATH`. It used Python 3.12 from the test host; this was not a Claude-hosted session.

1. Ordinary invocation without `uv` and offline setup with an empty cache returned structured errors without creating the requested output.
2. Explicit setup downloaded and verified pinned `uv` 0.9.6 and provisioned the locked engine dependencies.
3. Warm-cache setup passed offline; subsequent engine operations also ran with offline mode enabled.
4. The analytic square passed review; incomplete source text retained `needs_review`.
5. Plot and dashboard outputs were created with advisory status.
6. Revision template, save, inspection and rendering passed. A complete output ZIP was extracted into a different directory and its saved revision reopened successfully.
7. SVG, PDF and DXF delivery files were created and deterministically inspected offline.

An independent agent followed only the extracted Skill and supplied calls to produce a downloadable plot bundle. It used the plot procedure, stopped after plotting, and preserved the output's unverified/source-review status. This is a local instruction/navigation check, not a native Claude model evaluation.

## Documentation audit rebuild

The 2026-10-29 documentation audit corrected the compatibility API examples, chat setup and archive-resume instructions, distribution ownership/testing guidance and release comparison links. Both local archives were rebuilt; the published v0.6.0 release assets were not replaced.

| Local archive | Bytes | SHA-256 |
| --- | ---: | --- |
| `dist/metesparser-chat-skill.zip` | 530,319 | `727dd7bfb7a15f961096b790125998e4f0592d1b68c61ac86ffa8293d3487147` |
| `dist/metesparser-plugin.zip` | 524,725 | `b0112dde34899e3c68bc0f06a3c359667f8478b72bc0036dd7db3d4098d3bcb0` |

- Both checksum sidecars match. The chat ZIP still contains 81 files, one root Skill, thirteen procedures and six wheels. All ten runtime files and the original engine launcher in both archives are byte-identical to the initial extracted distribution above.
- The focused command in `docs/TESTING.md` passed all 58 chat/plugin builder, bootstrap, launcher and navigation tests. It uses `uv run python -m pytest` so checkout build-script imports resolve with importlib mode.
- Local links and heading anchors passed across 86 current source documents and both archives (270 chat links; 281 plugin links). Chat-template references supplied during packaging were checked against the built archive.
- The corrected API examples passed an isolated provider-free check using real parsing, verification and export with a stubbed PDF processor returning actual models. The 100-by-100-foot square was fully verified with `EXCELLENT` closure status; all five documented CSV, metadata, verification and audit files were produced.
- Independent archive review confirmed complete root assignments in setup examples, accurate `uv` bootstrap prerequisites, unpacking and bundle-directory inspection before reuse, and consistent adapted overlay guidance.

Before committing the audit, `make quality` passed without changes and `make test` passed with 1,614 tests, 23 skips and 93.58% root coverage. The cold runtime smoke above belongs to the initial build and was not repeated for these documentation-only changes. Native host acceptance remains unrun.

## Packaging review fixes

A review of the built Skill against Anthropic's [skill best practices](https://docs.claude.com/en/agents-and-tools/agent-skills/best-practices) and the claude.ai upload rules ([custom skills](https://support.claude.com/en/articles/12512198-how-to-create-custom-skills)) led to these changes. They supersede the file counts and hashes recorded above, which describe earlier, non-reproducible builds.

- **Description trigger.** The entrypoint description is 199 characters, third person, and states when to use the Skill ("Use when the user asks to check, plot, verify or export a legal description"). The build fails on a description over 200 characters or without "Use when".
- **One launcher rule.** The generated procedures previously said to locate the launcher "relative to the skill's plugin root" when `METESPARSER_SKILL_ROOT` was missing, contradicting `SKILL.md` and the runtime guide, which forbid guessing. `SKILL.md` and the runtime guide now say to set `METESPARSER_SKILL_ROOT` to the directory from which the model read `SKILL.md`, and the builder rewrites plugin-only phrasing through an explicit table (`TRANSFORMS` in `scripts/build_claude_skill.py`, with a unit test per rule). `_validate` fails the build if "plugin root", "project root", "repository root", `/tmp/`, "Claude Code", `CLAUDE_PLUGIN_ROOT`, `.claude/` or `plugin-settings` survive in any archive Markdown.
- **No project settings in chat.** The shared launcher defaults to a working-directory-relative `.claude/metesparser.local.md`. `run-chat.py` now always passes an explicit never-created settings path (an explicit `--settings` is still honored), and the procedures say to always pass `--output-dir`. An extracted-archive run from a directory containing `enabled: false` settings still produced review artifacts.
- **Smaller archive.** The changelog, per-skill READMEs, `plugin-settings.md` and the deprecated dashboard Mapbox stub are no longer shipped (81 to 65 files for the default profile). The build also fails on any shipped file not linked from `SKILL.md` or a linked file, apart from the engine `runtime/` and `scripts/` and files named by a linked JSON example record. References over 100 lines get a generated contents list.
- **Reproducible ZIP.** Entries are sorted with a fixed timestamp (`SOURCE_DATE_EPOCH` when set, otherwise 1980-01-01) and fixed modes (0755 for scripts, 0644 otherwise). Two consecutive real builds produced byte-identical archives, wheels included.
- **Network hosts.** The README and runtime guide name `files.pythonhosted.org` (the pinned `uv` wheel and locked wheels) and `pypi.org` (the index for `uv sync`) so administrators can allow them. A `uv` already on `PATH` is used as found; only the cached or downloaded copy is verified against the pinned hashes, and the wording now says so.

No archive hash is recorded for these changes: a hash of an uncommitted working tree identifies nothing. To record one for a named build, check out the commit, run `make chat-skill-build`, then `shasum -a 256 dist/metesparser-chat-skill.zip` (or read `dist/metesparser-chat-skill.zip.sha256`) and quote the commit with the result. The same commit and dependency lock yield the same digest on repeated builds.

Verification: `uv run pytest tests/unit/test_chat_skill_build.py tests/unit/test_chat_runtime.py plugins/metesparser/tests --no-cov` covers the table, validation, contents lists, reachability, reproducibility and settings behavior. The archive was unpacked into a new empty directory, `shasum -a 256 -c` on the sidecar passed, and an independent script re-checked the description, forbidden phrases, link closure, reachability and contents lists there. Native Claude chat acceptance remains unrun.

## Outstanding host acceptance

Upload the exact Skill ZIP in Claude chat and record discovery, source-document reading, dependency/network policy, artifact downloads, revision reupload and interactive HTML behavior. Linux bootstrap records have verified official wheel and executable hashes, but Linux execution has not been exercised in this local run. Online Mapbox/MCP and viewer reachability remain separate optional checks.

See the [distribution and host comparison](../CLAUDE_PLUGIN.md#functional-gaps-for-claude-chat) and [chat installation guide](../../plugins/metesparser-chat/README.md).
