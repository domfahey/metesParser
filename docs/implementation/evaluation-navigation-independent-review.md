# Independent E/G review and packaged navigation repairs

The counts and byte identities below describe this bounded review snapshot.
See the [integrated ledger](2026-10-28-evidence-review-ledger.md) for final
combined local gates. The archive regression below substitutes runtime build
steps; the later actual-archive inspection is recorded separately at the end.

Date: 2026-10-28. Reviewer: `source_handoffs`; configured model per parent
assignment: GPT-6.1-sol, exact runtime snapshot unavailable. The reviewer did not author the evaluator
helper or skill-navigation additions. No commits. Baseline HEAD:
`c0d6074941c9a59e68cc1d37e1f89531621f23e0`.

## Confirmed findings

1. A nonempty, correctly hashed transcript containing only native client
   authentication failure events, startup metadata, or an empty `turns` array
   admitted fabricated all-pass criterion/action flags. Validation now recognizes
   machine-readable JSON/JSONL turns, distinguishes client/synthetic errors from
   observed model behavior, and rejects scored observations without actual turns.
   Client/session failures require `not_run`; no response-truth judge was added.
2. Two `not_run` conditions could be summarized as an observed `paired` result.
   They now remain `incomplete_pair`, with a reason and no improvement score.
3. Comparison, source-handoff, and closure-diagnosis documentation linked to
   checkout-only `packages/` paths. Those paths escape the extracted plugin ZIP.
   Replaced them with generated packaged JSON schemas and sanitized examples.
   Source examples retain their exact source/transcript/selected bytes and hashes.
   Runtime cross-field/path/math validation remains authoritative; generated
   schemas do not pretend to encode all custom validators.

The helper still cannot authenticate a transcript's origin, verify client
isolation from a self-report, or judge whether a human scored a criterion
correctly. These limits are explicit. Native authentication availability and
retained raw-record hashes are documented separately in
`native-evaluation-availability.md`; no native discovery or document-reading
acceptance was observed.

## RED

```sh
uv run pytest tests/unit/test_packaged_skill_navigation.py tests/unit/test_skill_evals_review.py --no-cov -q
```

**6 failed, 1 passed**: extracted comparison links escaped the ZIP; no local
comparison schema/example existed; auth-only/startup-only/empty-turn transcripts
were accepted as pass; and two unrun conditions were labeled paired.

After expanding navigation coverage to source/diagnosis references:

```sh
uv run pytest tests/unit/test_packaged_skill_navigation.py --no-cov -q
```

**3 failed, 1 passed**: source/diagnosis references escaped the ZIP, and their
local schemas/fixtures did not exist. Copied no checkout code into instructions;
generated schema resources from the actual public Pydantic models instead.

## GREEN

```sh
uv run pytest tests/unit/test_skill_evals.py tests/unit/test_skill_evals_review.py tests/unit/test_packaged_skill_navigation.py tests/unit/test_plugin_build.py --no-cov -q
```

**61 passed in 1.29 seconds**. Seven new evaluator regressions cover unavailable
behavior, honest `not_run` records, incomplete pairs, and malformed outcomes.
Four navigation/resource tests build and extract a real plugin archive while
substituting wheel/lock production only; this is a packaging-resource test,
not a runtime installation or native-client behavior test. Links remain within
the extracted root, generated schemas match current runtime schemas, examples
execute through the public deterministic validators/engines, and source fixture
byte identities match. The parent owns actual wheel builds/runtime acceptance.

`uv run mypy scripts/skill_evals.py` passed with no issues after small existing
annotation/untyped-import repairs. Ruff lint and formatting pass on the helper
and two new test files. New plugin-reference links were scanned for remaining
checkout `packages/` targets; none remain. No build-script changes were needed.

## Reviewed diff identities

| File | SHA-256 |
| --- | --- |
| `scripts/skill_evals.py` | `8796e287c1e2d2df67e8570d5dd4b0ede3434947a9f8838e1f53adc1c15277cb` |
| `test_skill_evals_review.py` | `340aaf5d0908cf828f04de1f119e139069dd2db83eb6a4302098976b3fff7e23` |
| `test_packaged_skill_navigation.py` | `c6e09747bf2cf6989fc47fa2cf3e25b12ac9dd9f98ec4e6523e2f1c3af116f68` |
| Packaged comparison request schema | `8299f704953f11d12c0040451a496879a839bd27975ed75225f33dfe93f63e1a` |
| Packaged acquisition schema | `6fa00d7e5add20b5a332c73dec19d8d43ae59f834223ba5bc461257587b44d91` |
| Packaged selection schema | `94fdeb926c9271616553f3d1cfb2fceb5e55d35e147967ee31f622843199796f` |
| Packaged diagnosis request schema | `64d4939f7c47e10b03f0d8381b8c97d985f0b89d7c3de9a732658a3e8587340a` |

Observed native paired sessions, exact-client routing behavior, native source
reading, live provider display, and the broader model matrix remain `not_run`.
Local schema/navigation tests do not establish those gates.

## Actual built-archive inspection

Inspected both parent-built ZIPs read-only after builds completed, without
running or installing either runtime. Each contains all 11 new packaged
schema/example/source resources byte-for-byte equal to the checked files.
All 19 local links from comparison instructions/README/limits, source
preparation, and closure-diagnosis guidance resolve inside each archive.
Neither archive contains the evaluator directory. This confirms resource
delivery, not native skill discovery, model behavior, or runtime acceptance.

| Archive | SHA-256 |
| --- | --- |
| `dist/metesparser-evidence-plugin.zip` | `98ce9dcd7d5df60d5eefb592faf7d281740f8b928b8a18fc8607d8cadd62992e` |
| `dist/metesparser-evidence-web-map-plugin.zip` | `3a6fb9d650335cce187a8ca953c33487dbc90a5ed5b5915342c891672931ab9f` |
