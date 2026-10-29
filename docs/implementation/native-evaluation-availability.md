# Native evaluation availability: October 28, 2026

Native skill behavior and document reading were **not observed**. Two attempts
to start the same with-skill source-reading case failed authentication before
inference. No baseline/with-skill pair, criterion score, improvement score, or
native skill-routing acceptance is claimed.

Case: `source-reading-obscured-digits`. Client metadata records Claude Code
**2.1.296**. The requested model alias was `haiku`; the client's initialization
metadata resolved it to **`claude-haiku-5-5`**. This records the configured model
identity, not a successful provider inference or a measured model result.

| Attempt | Observed outcome |
| --- | --- |
| Initial native CLI attempt | Parent observed process exit 1; terminal JSON has `is_error: true`, duration 44 ms, recorded cost USD 0, and empty `modelUsage`. |
| Escalated retry | Parent observed process exit 1; terminal JSON has `is_error: true`, duration 40 ms, recorded cost USD 0, and empty `modelUsage`. |

Both transcripts contain an assistant event marked
`error: authentication_failed`, with model `<synthetic>`, and the terminal
message: “Failed to authenticate: OAuth session expired and could not be
refreshed”. The terminal event's `subtype: success` must not override its
`is_error: true`. Empty stderr does not indicate success; the failure is in the
structured stdout transcript. The process exits are the parent's observed tool
results; JSONL itself records the terminal error rather than a process exit code.

The initialization metadata lists plugin skill names. That demonstrates metadata
registration only. No skill selection, resource reading, native PDF/image
reading, requested artifact creation, or response evaluation was observed.
Isolation/equivalence was not established, and no baseline session was run.
Sonnet/Opus and the remaining native matrix were not attempted in this check.

## Retained records

Files remain outside the repository under
`/private/tmp/metesparser-native-evals-20261028/source-reading-obscured-digits/`.
Only identities and sanitized outcomes are recorded here; no credentials or
private session payloads are copied.

| Relative record | SHA-256 |
| --- | --- |
| `evaluator/with-skill-command.json` | `d33113125672da79fb84a933777451ff521a8ac9d1c1af627e11a0dc72905eab` |
| `evaluator/with-skill-transcript.jsonl` | `3620f758bb5074277da932fd6e4def1d9e90cd50f98e1499d91eaa64bb631640` |
| `evaluator/with-skill-retry-transcript.jsonl` | `7b48448b3e6c7a14095f0b6ac6130b8879050e87fa7b16954dff6f5dff3fd911` |
| `with-skill/request.json` | `406008914ca2e23498a119f93cd074f57bbf5d4d585ea88b3591be72cf7ab27e` |
| `with-skill/manifest.json` | `6e739a0168c00dd9bc7e09ebac40d2a4e9214b6323d9178cad5edfe18ce638d2` |
| `evaluator/rubric.json` | `6ab42916c3fb97b804c1dfd13bc523c2ddf6e0527b6e8bd3dc1d60129dabaee8` |

The next native evaluation requires an authenticated client and verified
baseline/with-skill isolation, identical input/tool availability, fresh sessions,
and complete observed transcripts. Local engine tests, extracted-archive link
checks, generated schemas, and resource availability remain separate evidence;
they do not pass native skill discovery or source-reading acceptance.

## Continuation availability check

A bounded no-tool availability prompt on October 28 again failed before inference,
both inside and outside the filesystem sandbox. Although `claude auth status`
reported `loggedIn: true`, each actual request exited 1 with the same expired
OAuth error, empty `modelUsage`, and USD 0 cost. The prompt requested only `READY`;
it was an availability check, not a scored evaluation or a paired run.

The transcripts are retained directly under
`/private/tmp/metesparser-native-evals-20261028/`:

| Record | SHA-256 |
| --- | --- |
| `auth-recheck-transcript.jsonl` | `b6b16febbd4c8df44064c131470ccda5bebf6e6ae6909c1f776c54bfd08945a5` |
| `auth-recheck-escalated-transcript.jsonl` | `39b37c0eed22eb3a02f0ab2300ac1d14e197c932915e497668c2d5d87863b62c` |

The independent live Mapbox preflight also exited 1 before provider requests:
`uv run --extra browser-test --extra web-map python scripts/check_mapbox_browser.py --live`
reported that the runtime public token environment variable was unavailable.
The uv cache permission failure was retried through explicit escalation. No
credential values were printed or copied. No Mapbox connector tools were exposed
to the parent at this check. Provider and native-client display acceptance remain
`not_run`; they are separate from the passing offline SDK checks.

## Final prerequisite recheck

The next goal continuation repeated the bounded no-tool Claude prompt outside the
sandbox. It again exited 1 before inference with expired OAuth, USD 0 cost and
empty `modelUsage`. Transcript:
`/private/tmp/metesparser-native-evals-20261028/final-availability-transcript.jsonl`,
SHA-256 `9214e6beafb7c0fa11902a67b4cc6c00f3f2b96d42efaef9c7d7155ee527f833`.
The Mapbox live preflight again exited 1 for the missing runtime public token;
no Mapbox connector was exposed. The reviewed implementation and final local
checks remain complete, but external acceptance cannot advance without restored
access and verified evaluation isolation. No model scores or provider success
were recorded.
