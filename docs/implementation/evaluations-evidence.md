# E1 evaluation fixture and evidence helper

This is a chronological evidence record. The initial E1 handoff below is historical; the follow-up completes comparison fixtures and producer-backed restart fixtures. See the [integrated ledger](2026-10-28-evidence-review-ledger.md) for current local acceptance and [native availability](native-evaluation-availability.md) for the authentication-blocked model gate.

Date: 2026-10-28

Task: E1 from `docs/plans/2026-10-28-skill-evidence-and-review-improvements.md`

Worker: `/root/eval_tools` (Codex subagent; exact model/version was not exposed in the worker context)

Inspected baseline: `c0d6074941c9a59e68cc1d37e1f89531621f23e0`

Current status at initial E1 handoff: helper, evidence checks, and non-comparison fixture families implemented. The follow-up below completes comparison and reuse/restart materialization. No behavior-evaluation pass is claimed by E1 implementation alone.

## RED / GREEN record

- RED command: `uv run pytest tests/unit/test_skill_evals.py --no-cov -q` failed during collection with `ModuleNotFoundError: No module named 'scripts.skill_evals'` (exit 2) before the helper existed.
- Follow-up RED: the same command collected after the first implementation and exposed a malformed criterion record (`TypeError: unhashable type: 'dict'`); the fixture builder was corrected to use rubric criterion IDs. The first full run then showed 9 failures, including the intended validation regressions.
- Review-gap RED: the same pytest command had **4 failures, 26 passes** for overlapping materialization roots, duplicate criterion IDs, weakened evaluator rubric, and an evaluator path inside the candidate bundle.
- GREEN: `uv run ruff format scripts/skill_evals.py tests/unit/test_skill_evals.py` completed; `uv run ruff check scripts/skill_evals.py tests/unit/test_skill_evals.py` passed; final `uv run pytest tests/unit/test_skill_evals.py --no-cov -q` passed **37 tests**.
- The test suite covers missing/wrong transcript hashes, rubric-file leakage, rubric weakening, criterion/action gaps and duplicates, stale candidate hashes, contradictory overall results, missing model/tool evidence, non-equivalent tool schemas, non-run actions, pair/condition mismatches, root overlap/escape/symlinks, malformed list entries, materialized artifacts, and CLI/JSONL summaries.

## Implemented preparation and validation

`scripts/skill_evals.py` provides `materialize`, `validate-run`, and `summarize`. It validates hashes, file references, evaluator/candidate separation, exact criterion/action coverage, evidence for each result, and pair identity including model/client/input and tool schemas. It does not evaluate whether an answer is factually correct or launch any provider.

The request catalog remains `plugins/metesparser/evals/cases.json`. Criterion IDs and required actions are separate in `plugins/metesparser/evals/rubrics.json`; materialization writes that rubric to the evaluator directory, outside the candidate input bundle. The plugin build now excludes the evaluation directory from the runtime package (parent integration; builder regression tests passed).

Materialized, non-comparison fixture families:

- Three actual synthetic, image-only PDF source-reading tasks: a masked bearing digit, a referenced but absent Exhibit A, and two different Exhibit A occurrences on distinct pages.
- Selection-only: a scanned report plus exact UTF-8 text with a historical description, an operative description, and a verbatim exclusion.
- Reuse/restart: changed transcript bytes, an unchanged selection artifact, a downstream plot artifact, and matching SHA-256 dependency records.
- Closure diagnosis: `ClosureDiagnosticRequest` validated against the public `mp_models.diagnostics` schema.
- Map routing and optional interaction: schema-valid `StandaloneWebMapInput`, two distinct synthetic PNG raster layers, visibility/order controls, no claimed browser access.
- Map evidence: a `RasterRegistration` with low fit RMS and independent checkpoint RMS above its stated limit.
- End-to-end review: a synthetic multi-line deed page with a visibly obscured source digit and a separate exception.

Comparison cases are present in the shared catalog/rubric, but their input payloads have not yet been checked against F's finalized schema. `materialize` rejects these three IDs until the schema-aligned fixtures land. They are provisional and are **not included in the completed-family claim**.

## Generated fixture evidence

The helper materialized the non-comparison matrix in a temporary directory at `/var/folders/ny/sgsj847n58xbb1d4rxgbxzw80000gn/T/metesparser-e1-matrix-final-ow2l5mo2`. The following are SHA-256 hashes of its candidate manifests; each manifest also records hashes for every source artifact.

| Case | Manifest SHA-256 |
| --- | --- |
| `source-reading-obscured-digits` | `485293148bf9398a78c3a42b7969f15cebb71afb392f79c4848c7a422aa68ab5` |
| `source-reading-missing-exhibit` | `cb5b494a071a864f7d18866f9c518568ab35b2a0ebbf5a4591908fd677b75ccd` |
| `source-reading-repeated-occurrences` | `458e5950d2a990fdf92b8901686816205379fb94e5e5af5c217614bc32e153f1` |
| `selection-only` | `f7d8ec74362592c1ce3a0a20b677ba89325d4b8432d2c70e58f008cddcb17ed2` |
| `reuse-restart` | `5ac015426d51a8b400cb10d7b00a959d8cf41296fade2eb32b8515e4b44f5355` |
| `closure-diagnosis` | `b88c3a7441d8e7640ccbd04b9728638d7cac676535d08a6eeedffa3ad1e19e6a` |
| `map-presentation-routing` | `8811ca9bd188ebdba691ffaa52da06527a6144b56c186beec523cce7cd6ce7ac` |
| `map-interaction-optional` | `7933a5ac3ceb230884a74364bfdafc73aea242aa7bbfaf9d20aed19bc0e05935` |
| `map-evidence-checkpoints` | `869b0c4bf6b2892535b808d7b41d2437c215c3fc6729bc7a8b83afdfc2f7fd73` |
| `end-to-end-review` | `9ffa4abdb36ff2a791840e289078afaceb80df09fc4beffdfedfa0e52211e880` |

Each manifest records hashes for every included source artifact. Repeated-occurrence, map, reuse, and end-to-end fixtures are generated independently from the cases above; they are synthetic test material only.

## Unrun gates and limitations

- No baseline/with-skill model sessions were run; no transcripts or outcomes were created.
- No native Claude document-reading, Haiku/Sonnet/Opus, Codex behavior comparison, browser-controlled map interaction, live Mapbox, or native-client display session was run.
- Comparison fixture materialization awaits F's frozen request schema and must then receive schema-validation tests.
- A paired run is only considered equivalent when its record verifies matching tools/tool schemas and input/model/client identity. In this environment, repository access is available to the agent, so an actual client pair must be marked `non_equivalent` unless isolation is independently established.
- The generated PDFs are synthetic image-only pages rendered with Pillow. Fixture preparation requires the repository's `web-map` extra (`uv sync --all-extras --dev`).

Reviewed diff identity: baseline commit above plus these exact owned-file SHA-256 values at handoff (the evidence note itself is excluded because it contains this list).

| File | SHA-256 |
| --- | --- |
| `scripts/skill_evals.py` | `c0f257b03864db3a4e6f3e0ce19fa34336407801a842a4331927185ca6bca84d` |
| `tests/unit/test_skill_evals.py` | `83dac766865e9ace9d395bfdb615996f30d7f87fc4419588b02cbdde8052af6d` |
| `plugins/metesparser/evals/cases.json` | `9f26c128eed367f0f4ec06808d35b92eabd99112581233c043ead29a34397402` |
| `plugins/metesparser/evals/rubrics.json` | `b060b0966b90d3de3eb9e63e9ddd927ac548b4680a1cce60eb07cc38179100e4` |
| `plugins/metesparser/evals/README.md` | `af14f79293093bde769d3805ad10ad89236834a37439dfe9bdba5bbbacba8295` |

## E1 follow-up: comparison fixtures, real restart artifacts, and run validation

Date: 2026-10-28. Worker: `/root/skill_docs` (Codex subagent; exact runtime model version not exposed). Comparison contracts/engine were supplied by F; no provider sessions were launched by this fixture work.

### RED / GREEN

Initial behavioral RED after replacing the pending expectations:

```sh
uv run pytest tests/unit/test_skill_evals.py::test_map_selection_and_reuse_fixture_inputs_have_concrete_observations tests/unit/test_skill_evals.py::test_comparison_fixtures_are_schema_valid_and_run_engine --no-cov -q
```

Result: **4 failed**. Restart inspection could not find valid producer stages, and all three comparison cases were deliberately blocked by `PENDING_SCHEMA_CASES`. After the first implementation attempt, the same command remained red because the synthetic page declared an out-of-range transcript line and the restarted fixture variant had prematurely updated all source records; those were fixed by correcting observed line counts and mutating transcript bytes only after producing the unchanged acquisition/selection/review/plot chain.

Run-evidence hardening RED:

```sh
uv run pytest tests/unit/test_skill_evals.py::test_validate_run_rejects_changed_exposed_skill_resource tests/unit/test_skill_evals.py::test_validate_run_rejects_empty_transcript_even_with_matching_hash tests/unit/test_skill_evals.py::test_validate_run_reports_malformed_nested_values_without_raising --no-cov -q
```

Result: **4 failed, 1 passed**. A changed exposed skill file was accepted, an empty transcript with its matching empty hash was accepted, a null resource list raised `TypeError`, and a null criterion ID raised while sorting. The null-tool-evidence array case already returned an error.

Final GREEN:

```sh
uv run pytest tests/unit/test_skill_evals.py --no-cov -q
```

Result: **44 passed**. `uv run ruff check scripts/skill_evals.py tests/unit/test_skill_evals.py` passed; `uv run ruff format --check scripts/skill_evals.py tests/unit/test_skill_evals.py` reported both changed files already formatted after applying Ruff formatting.

### Delivered fixture behavior

- `comparison-reversed-lines`, `comparison-incompatible-basis`, and `comparison-structural-tentative` now materialize schema-valid `ComparisonRequest` files and execute `compare_descriptions` in regressions. Assertions cover reverse traversal agreement, unknown-basis vector/position unavailability while preserving structural monument changes, and tentative split/merge candidates. Candidate bundles contain the request and source fixtures only; evaluator rubrics remain in the separate evaluator directory.
- `reuse-restart` materializes two schema 1.1 acquisition/selection bundles. The unchanged bundle's review and plot stages are real outputs of `review_file` and `plot_file`, and `inspect_artifacts` confirms both reusable. In the changed variant, only `source-text.txt` is changed after preserving the old exact acquisition/selection and producer outputs; inspection detects stale conversion, stale selection, and blocked downstream review/plot. This exercises the real inspector rather than trusting hand-written `{stage, hash}` placeholders.
- `validate_run` now verifies exposed skill resource paths and bytes against recorded hashes, rejects an empty transcript even when the hash matches, validates run arrays before iterating, and rejects malformed condition/result/criterion/action IDs without type errors.

Updated worker-file SHA-256 values at this gate:

| File | SHA-256 |
| --- | --- |
| `scripts/skill_evals.py` | `ac2709bb37f07e7b51965fb04c2b68e6c0f50b14f2dbdafaa9c3f8d3455daaef` |
| `tests/unit/test_skill_evals.py` | `4f0ae032198f0dd33045c252a9d9f0ed5e0b44c7d819dcc1960fa208fc0f7b4a` |
| `plugins/metesparser/evals/cases.json` | `a0938546534d57c09e7017f85c8b689d8fcf88350a5acf2a44cdf6312ed2bd98` |

No paired model results are inferred from these tests. Native Claude model sessions, paired baselines, native document reading, live Mapbox, and native-client display remain separate observed gates; todo 6 remains open until its required runs and transcripts exist.
