# Workstream A: source-handoff implementation evidence

This is a chronological checkpoint record. Later independent-review sections
supersede initial counts, hashes, and pending notes. See the [integrated ledger](2026-10-28-evidence-review-ledger.md)
for final combined local gates and [native availability](native-evaluation-availability.md)
for the separately unrun model/client acceptance.

Date: 2026-10-28. Worker: `source_handoffs`; configured model per parent
assignment: GPT-6.1-sol, exact runtime snapshot unavailable. Task: workstream A of
`docs/plans/2026-10-28-skill-evidence-and-review-improvements.md`.

Owned diff: the new `mp_models/source_handoff.py`, `mp_review/source_handoff.py`,
their package tests, and `mp-review/tests/fixtures/source_handoff/`. No commits.
Parent owns CLI, exports, root facades, distribution, and skill documentation.
Baseline HEAD: `c0d6074941c9a59e68cc1d37e1f89531621f23e0`.
Implementation SHA-256 identities at this gate:

| Artifact | SHA-256 |
| --- | --- |
| `mp_models/source_handoff.py` | `7f773f4c1543916f0ca5bf9459933dfe5b0c0ed8794900eec0982f287222ad5d` |
| `mp_review/source_handoff.py` | `6062e4bf152a5c43383a46286117b22f3350d5e0888c8204a85113ed901fef91` |
| `source-acquisition.json` fixture | `321bb8ab7639d3144c9f7c8f416d2c7d97e2e4e354cd61ebaf04b6b1517840e3` |
| `description-selection.json` fixture | `747fe254b15de4b03386aa1972ede44a9203527c5e128ebda36f20c51025db66` |

## RED

Initial import gate:

```sh
uv run pytest packages/mp-review/tests/test_source_handoff.py -q --no-cov --import-mode=importlib -x
```

Failed `test_exact_multibyte_bom_crlf_noncontiguous_selection_is_valid` with
`ModuleNotFoundError: No module named 'mp_review.source_handoff'` (1 failed).
An earlier fixture-generation attempt hit uv cache sandbox access; rerunning
with the required escalation created the fixtures before this recorded gate.

Behavioral gate after the contracts and partial adapter existed:

```sh
uv run pytest packages/mp-review/tests/test_source_handoff.py::test_changed_bytes_identify_affected_file -q --no-cov --import-mode=importlib -x
```

Failed changed `original.bin` identity: expected `mismatched`, observed
`matched` (1 failed). Implemented raw-byte identity comparison, including
separate unavailable/null cases; did not change expected bytes or hash results.

Additional behavioral RED:

```sh
uv run pytest packages/mp-review/tests/test_source_handoff.py::test_known_page_inventory_gaps_remain_unknown_not_complete packages/mp-review/tests/test_source_handoff.py::test_missing_exhibit_uncertainty_is_carried_without_fabricating_a_span packages/mp-review/tests/test_source_handoff.py::test_invalid_invocation_cannot_claim_matching_identity -q --no-cov --import-mode=importlib
```

3 failed: missing known pages were reported `none_declared`, missing-exhibit
uncertainty was dropped, and invalid invocation identity was `matched`.
Implemented gap findings, missing-page uncertainty carry-forward, and
unverifiable invocation identity. Page-gap reporting uses ranges and bounds the
expanded page-number list rather than allocating by an untrusted page count.

## GREEN

```sh
uv run pytest packages/mp-models/tests/test_source_handoff.py packages/mp-review/tests/test_source_handoff.py --no-cov --import-mode=importlib -q
```

109 passed (19 model and 90 adapter behavior cases).

```sh
uv run pytest packages/mp-models/tests/ packages/mp-review/tests/test_source_handoff.py --no-cov --import-mode=importlib -q
```

231 passed, including concurrent diagnosis model tests. Ruff lint and formatting
were applied only to these four owned files. Strict mypy on the two production
modules passed (`Success: no issues found in 2 source files`).

Coverage includes exact BOM/CRLF/multibyte and whitespace preservation;
noncontiguous span reconstruction; UTF-8 boundaries; byte/line/page ranges;
source/transcript/selected/acquisition identity; missing originals; opaque
attachments; unknown hashes and counts; missing/unreadable pages; uncertainty
carry-forward; separate historical/operative candidates; malformed, duplicate,
dangling, legacy and unknown-version records; path traversal and symlink
rejection; explicit bundle-root resolution; standalone prerequisites; no
mutation or output-directory creation. No source accuracy attestation is emitted.

## Acceptance limits

Independent review, parent CLI/import/facade integration, extracted-plugin
outside-checkout acceptance, full repository checks, and native-reader/model
evaluations are separate gates and were not run by this worker at this point.
No live source reading or provider calls were made. No migration writes occur;
legacy 1.0 records remain unverifiable, with explicit migration guidance.

## Independent Unicode/path review follow-up

A separate reviewer reproduced unhandled exceptions from JSON-escaped lone surrogates in original/transcript/selected-file paths and explicit span separators. A malformed invocation override containing a lone surrogate or NUL similarly raised from `Path.read_bytes` instead of returning structured findings.

- RED: `uv run pytest packages/mp-review/tests/test_source_handoff_unicode_review.py -q --no-cov` → **6 failed, 2 passed**. Failures exercised actual `UnicodeEncodeError`/embedded-NUL `ValueError` paths, beyond import checks.
- Fix: the shared source-record model validates Unicode scalar strings (including tuple separator elements), rejects invalid surrogates as schema errors, and preserves every valid string unchanged. The file reader also reports unrepresentable invocation paths as structured `record_unavailable` errors. No replacement, normalization, source mutation, or provider calls were added.
- GREEN: `uv run pytest packages/mp-review/tests/test_source_handoff_unicode_review.py packages/mp-review/tests/test_source_handoff.py packages/mp-models/tests/test_source_handoff.py -q --no-cov --import-mode=importlib` → **117 passed in 0.36s**. Existing BOM/CRLF/multibyte exact-span coverage and new valid non-ASCII/emoji nonmutation assertions passed.
- `uv run mypy packages/mp-models/src/mp_models/source_handoff.py packages/mp-review/src/mp_review/source_handoff.py` → **2 source files clean**.

Review also traced source/page/uncertainty bindings, root-confinement and below-root symlink rejection, byte/line/page attribution, UTF-8 character boundaries and exact selected-span reconstruction. Matching bytes remain identity evidence; the validator still makes no source-reading accuracy or canonical-verification claim.
