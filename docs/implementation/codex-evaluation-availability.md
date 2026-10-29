# Codex paired-evaluation availability — 2026-10-28

This is a bounded, no-model setup investigation for the Codex evaluation lane described in the [evaluation protocol](../../plugins/metesparser/evals/README.md). It is separate from native Claude availability in [native-evaluation-availability.md](native-evaluation-availability.md).

## Observed local availability

- `codex --version` reported `codex-cli 0.165.0`.
- `codex login status` reported `Logged in using ChatGPT`. This confirms local CLI login status only; no inference, model availability, or account usage was tested.
- `codex exec --help` exposes `--json` for JSONL events, `--ephemeral`, `-C/--cd`, `--sandbox`, and `-c/--config`. The installed CLI accepts `codex exec --json` in its documented interface. OpenAI's [skill-evaluation guidance](https://developers.openai.com/blog/eval-skills) describes saving these JSONL events as the run trace.
- The existing `~/.codex/config.toml` was read without displaying its values. It has no named `permissions` profiles and no `default_permissions` setting. No global configuration or authentication file was changed.

## Isolation probe

OpenAI's [Codex permissions guide](https://learn.chatgpt.com/codex/permissions) documents named filesystem permission profiles, including deny rules for paths and workspace subpaths. A no-model probe attempted to verify that a repository path could be denied to the sandboxed command. It only tested file readability and did not print or open file contents:

```sh
codex sandbox -P eval -C /private/tmp \
  -c 'default_permissions="eval"' \
  -c 'permissions={eval={filesystem={"/Users/dfahey/projects/metesParser"="deny"}}}' \
  -- /bin/sh -c 'test -r /Users/dfahey/projects/metesParser/plugins/metesparser/README.md'
```

The in-environment attempt exited **71** with `sandbox-exec: sandbox_apply: Operation not permitted`. An escalated retry of the same no-model command exited **134** with no output. Neither attempt established whether the path denial works. A prior dotted-key override attempt was rejected as an invalid path before sandbox startup; it did not read the target file either.

No JSONL run transcript, model response, usage record, or probe log was retained; these were help/status/config checks and failed no-model probes. No inference was launched.

## Status and limits

Codex CLI output capture is available, but the required baseline isolation is **unverified under the current setup**. The paired protocol requires denying baseline access to repository/plugin/rubric materials, equal tool schemas and input bytes, and complete transcripts; until isolation is demonstrated, any such pair must be recorded `non_equivalent`, not scored as paired evidence. See the [run-record requirements](../../plugins/metesparser/evals/README.md#suggested-run-record).

The shipped MetesParser artifact is a Claude plugin. Any Codex evaluation would be a separate client lane and would need to expose the skill resources through Codex-native skill discovery; it would not establish native Claude skill discovery or document-reading acceptance. Claude's expired OAuth attempts are documented separately and were not part of this investigation.

No setup changes were made. This note does not claim the Codex lane is impossible; a later attempt can proceed if a sandbox profile can be applied and its denial of repository, plugin, and rubric paths is verified before inference.
