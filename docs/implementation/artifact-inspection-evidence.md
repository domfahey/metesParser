# Workstream C: artifact-inspection implementation evidence

This is a chronological checkpoint record. Later independent-review sections
supersede initial counts, hashes, and pending notes. In particular, the recorded
644/3 integration run below is historical. See the [integrated ledger](2026-10-28-evidence-review-ledger.md)
for final combined local gates and [native availability](native-evaluation-availability.md)
for the separately unrun model/client acceptance.

Date: 2026-10-28. Worker: `source_handoffs`; configured model per parent
assignment: GPT-6.1-sol, exact runtime snapshot unavailable. Task: workstream C in
`docs/plans/2026-10-28-skill-evidence-and-review-improvements.md`.
Baseline HEAD: `c0d6074941c9a59e68cc1d37e1f89531621f23e0`.

Owned files: `mp_models/artifact_inspection.py`, `mp_review/artifact_inspect.py`,
`mp-review/tests/test_artifact_inspect.py`, and this evidence file. No commits.
Parent owns CLI/public exports/facades and the review/plot producer hooks.
Parent approved the version 1.0 inventory contract by message before implementation.
`local_status` preserves individually usable evidence separately from effective
usability after declared dependencies are considered.

## RED

```sh
uv run pytest packages/mp-review/tests/test_artifact_inspect.py -q --no-cov --import-mode=importlib -x
```

Initial gate: 1 failed, `ModuleNotFoundError: No module named 'mp_review.artifact_inspect'`.

After the initial adapters existed, the full inspector command (without `-x`)
produced 6 failed / 34 passed. Behavioral failures exposed:

- No direct structured-call input inventory/recommendation.
- A JSON input retained under `source.txt` received an incorrect text CLI command.
- Selection reuse failed to reject dropped source uncertainty.
- Missing dashboard HTML contaminated independently usable calculations.
- Invalid map schema contaminated independently usable calculations.
- Rejected old placement masked the actual changed source/calculation identity.

Implemented independent map/placement/presentation validation around the shared
pure calculator, correct input-kind routing, and source-uncertainty checks.

The expanded same command produced 3 failed / 45 passed, exposing missing
promised-view inventory checks, missing diagnosis source dependencies, and a
self-consistent fabricated composition that lacked source replay. Added exact
display inventories, ID/hash source edges, and replay of retained composition
inputs through existing plot/composition models and pure validators.

```sh
uv run pytest packages/mp-review/tests/test_artifact_inspect.py::test_comparison_is_replayed_without_acquisition_or_dashboard packages/mp-review/tests/test_artifact_inspect.py::test_comparison_fabrication_fails_despite_consistent_hash -q --no-cov --import-mode=importlib
```

2 failed against the explicit unavailable adapter; implemented the landed F
manifest contract and pure `compare_descriptions` replay.

```sh
uv run pytest packages/mp-review/tests/test_artifact_inspect.py::test_online_map_tracks_unique_declared_plot_identity -q --no-cov --import-mode=importlib
```

1 failed (missing plot dependency); added exact calculation/input/geometry hash
bindings. Unchanged local map provenance remains individually usable when its
upstream plot later becomes blocked.

```sh
uv run pytest packages/mp-review/tests/test_artifact_inspect.py::test_repeated_same_byte_candidates_do_not_choose_newest_or_first_occurrence -q --no-cov --import-mode=importlib
```

1 failed after strengthening the assertion: same-text candidates emitted an
ambiguous restart command. Commands are now withheld when occurrence selection
is ambiguous, even when candidate paths happen to be identical.

## GREEN

```sh
uv run pytest packages/mp-review/tests/test_artifact_inspect.py -q --no-cov --import-mode=importlib
```

51 passed. Tests stage real producer manifests rather than static mocked hashes.
Coverage includes source/selection/review chains, exact input-kind replay and
full semantic audit comparison; changed and self-consistent fabricated outputs;
direct-call routes; legacy and unavailable identities; occurrence ambiguity;
bounded explicit nested-root discovery; traversal/symlink/version rejection;
map/presentation/placement isolation from arithmetic; plot, composition, online
map, diagnosis, and comparison provenance; read-only/no-provider/no-export guards;
and unexecuted recommendations that never suggest existing output directories.

```sh
uv run mypy packages/mp-models/src/mp_models/artifact_inspection.py packages/mp-review/src/mp_review/artifact_inspect.py
```

Passed: no issues in 2 source files. Ruff lint and format checks pass on the
three owned Python files.

```sh
uv run pytest packages/mp-models/tests/ packages/mp-review/tests/ --no-cov --import-mode=importlib -q
```

644 passed / 3 failed in 19.40s. Failures are in parent-owned new advisory CLI
fixtures: comparison expects `request.json` instead of the frozen
`comparison-request.json`; two read-only settings cases supply an absolute
`output_dir`, which existing settings validation rejects. The parent received
the exact failures. No existing package model/review regression failed.

## Diff identity and limits

| File | SHA-256 |
| --- | --- |
| `mp_models/artifact_inspection.py` | `d60b4031c280ee0c8b065cf5a94698a607840cd3a2d4f456d79caca1e74b3950` |
| `mp_review/artifact_inspect.py` | `5ed00366683a17ee6adc9d7832b02bab6af9d591193255d5d487d8fcd5e27881` |
| `mp-review/tests/test_artifact_inspect.py` | `2e795481dff11ef9df34c26ab8c02f280b31781e3c01dfc8b91008733eb90b1c` |

Independent parent review, CLI/import/facade acceptance, extracted-plugin gates,
and repository-wide checks remain separate. No source reading, provider
request, geographic reprojection, raster warp, or output generation runs during
inspection. The inspector reuses existing pure map-provenance validators and
does not independently authenticate geographic coordinates or source accuracy.

Existing review/plot producers often lack original occurrence IDs. A unique
declared hash can establish a dependency; duplicate occurrences or replaced
identities without a declared linking ID remain unproven. Individually valid
artifacts remain visible, with no filename/timestamp heuristic or full-chain
certification. Native conversion/selection and missing composed input contracts
receive required-input guidance; structured commands are emitted only when the
current input route is unambiguous and executable with the existing CLI.

## Independent C review: description-comparison placement isolation

Reviewer: `skill_docs`, 2026-10-28. The F dashboard schema added
`description_comparison_specs`, which may reference scenes and placements. The
inspector's calculation replay clone removed scenes, placements, and older plot
comparison specs, but retained the new description-comparison specs. A valid
dashboard with a comparison referencing its explicit placements therefore
failed core bundle validation and marked independently replayable calculations
`invalid` (a false negative).

RED reproduction:

```sh
uv run pytest packages/mp-review/tests/test_artifact_inspect.py::test_description_comparison_placement_does_not_invalidate_core_math -q --no-cov
```

Failed as expected: calculation status was `invalid`, expected
`present_valid`. The core-only clone now clears
`description_comparison_specs` with the other optional map/placement inputs.
The regression stages a dashboard generated by the real producer from the
synthetic two-description fixture, with both comparison placements tied to
fresh producer geometry hashes.

GREEN:

```sh
uv run pytest packages/mp-review/tests/test_artifact_inspect.py -q --no-cov
```

52 passed, including the new regression and the inspector's existing bounded
path, source, result, dependency, and replay cases. Ruff lint passed on both
inspector files. Ruff format check initially identified the test file; it was
formatted and the following check passed:

```sh
.venv/bin/ruff check packages/mp-review/src/mp_review/artifact_inspect.py packages/mp-review/tests/test_artifact_inspect.py
.venv/bin/ruff format --check packages/mp-review/src/mp_review/artifact_inspect.py packages/mp-review/tests/test_artifact_inspect.py
```

Reviewed file SHA-256 after this correction:

| File | SHA-256 |
| --- | --- |
| `mp_models/artifact_inspection.py` | `d60b4031c280ee0c8b065cf5a94698a607840cd3a2d4f456d79caca1e74b3950` |
| `mp_review/artifact_inspect.py` | `e2e50294a34b391bc78ff40528e438883fe6465cc7591c532d60274b1de44f01` |
| `mp-review/tests/test_artifact_inspect.py` | `7c21a6c00fd1c046e5e506073ec3345687fc54bc6171a63d6cf2a0e2b3d91418` |

This review found no demonstrated false-positive reuse in the focused C paths
examined. Full cross-package and CLI integration suites were not rerun here;
parent integration review remains separate.

## Final requirement audit: integrated dashboard comparison stage

The requirement audit identified one concrete C completeness gap: standalone comparison manifests were replayed, but the dashboard producer's `description-comparisons.json` and its two stage-manifest hashes were not inventoried. A valid dashboard comparison could not satisfy requested `compare-descriptions`, and changed saved comparison stages were invisible.

RED:

```sh
uv run pytest packages/mp-review/tests/test_artifact_inspect.py -k 'integrated_dashboard or unplaced_dashboard_comparison' -q --no-cov
```

**4 failed** against actual `dashboard_file` output. The cases cover unchanged stage discovery/reuse, self-consistent derived-output tampering, changed comparison specifications and vector-only independence from optional map failures.

The inspector now creates a dedicated `comparison` artifact for the integrated stage, replays the immutable source-owned comparison specifications and validates both comparison manifest hashes and complete saved result equality. Unknown identity, missing stage, changed inputs and fabricated outputs remain distinct. Comparison artifacts do not inherit canonical status. Their calculation dependency propagates source changes; explicit positioning requests also depend on fresh plot/map/placement evidence. Unplaced vector comparisons use only their source calculations and requested scene inputs, so unrelated malformed map layers do not invalidate them. Dashboard rendering depends on the comparison stage, while verification-only usability remains independent.

GREEN:

```sh
uv run pytest packages/mp-review/tests/test_artifact_inspect.py -q --no-cov
uv run mypy packages/mp-review/src/mp_review/artifact_inspect.py
```

**60 passed in 0.98s**; mypy **1 source file clean**. Additional cases verify missing/changed/unknown stage identity, conditional placement dependencies, requested-stage resume guidance and read-only nonmutation. No provider, output generation, automatic workflow execution or canonical-status changes were introduced.

Stable implementation/test snapshot sent for independent review:

| File | SHA-256 |
| --- | --- |
| `packages/mp-review/src/mp_review/artifact_inspect.py` | `787abae307f8219f834e31563916e9242ae6e0aeacc330b8770c93a74268de11` |
| `packages/mp-review/tests/test_artifact_inspect.py` | `224209e77b58c95d22ffd03f96845963f2c12ddde8db7838d7ef4f4291238eb1` |

SHA-256 over each ordered relative filename, NUL, complete bytes, NUL: `1c99e44216527458b6c9fb12fb3a8d61c01acac377d2d1dfb7a1865188497a1a`. This checkpoint precedes independent review and any final package/archive regeneration.

## Literal stage outcomes, causal restart and source-aware guidance

The final requirement audit also closed stage-level outcome completeness: summaries now aggregate stable, deduplicated actual dependency IDs and reasons, attributing each reason to its affected artifact. Valid/unrequested stages receive no invented reason. A requested destination with no artifact receives an explicit inventory-missing reason.

- RED: `uv run pytest packages/mp-review/tests/test_artifact_inspect.py -k stage_summaries -q --no-cov` → **1 failed, 1 passed** (missing stage-level dependencies/reasons).
- Independent review then found blocked dashboard rendering was incorrectly chosen before its invalid comparison dependency because enum order put dashboard first. `uv run pytest packages/mp-review/tests/test_artifact_inspect.py -k 'integrated_dashboard_comparison_tamper or causal_restart' -q --no-cov` → **2 failed**. Restart choice now selects relevant causal failing prerequisites before blocked descendants, using the documented stage order only as a stable tie-break among independent causes. Tests retain stable results with unrelated invalid branches and multiple independent relevant failures.
- Parent review added source-aware integrated comparison guidance. The assertion first failed once because generic standalone-request guidance did not describe the retained DashboardBundle. The result now names the actual retained dashboard source and its source-owned comparison specifications, asks for dashboard-producer regeneration into a new directory, and states that this integrated stage retains no standalone ComparisonRequest. It never suggests a nonexistent request filename or automatically runs a command.
- Real positional coverage now uses documented shared bearing basis, explicit placements and nonempty supplied context source/vector evidence. The real producer yields positional `agree`; the inspector replays the identical comparison despite omitting unrelated maps from its narrow request. Changing a selected placement invalidates positional comparison and selects its map/placement prerequisite while preserving verification-only usability.

Final affected gate at the frozen implementation:

```sh
uv run pytest packages/mp-review/tests/test_artifact_inspect.py -q --no-cov
uv run mypy packages/mp-models/src/mp_models/artifact_inspection.py packages/mp-review/src/mp_review/artifact_inspect.py
```

**64 passed in 1.04s**, mypy **2 source files clean**; Ruff lint and formatting passed. Source/test code frozen for independent signoff and parent final package/archive gates. No broad suites were rerun by this worker.

| Frozen file | SHA-256 |
| --- | --- |
| `packages/mp-models/src/mp_models/artifact_inspection.py` | `4f196641b98b773668d4734a2dda55c5ce6843ce83136aa9b9dcf3a4fe92ed76` |
| `packages/mp-review/src/mp_review/artifact_inspect.py` | `72bb5d14c0ddcebe7f098886843c48c95611ba1512439794d83d2a3718fe503c` |
| `packages/mp-review/tests/test_artifact_inspect.py` | `9c60ebaa7f50fa66825ef092a2aabfaa925ae5444ec67f98844d86fb620cf64b` |

Ordered relative-filename/NUL/bytes/NUL combined identity: `da5831d3deb548ca1655c3f767d424381d5a6fe9fb85e364307bf9da69cedb03`.

## Independent final C signoff

Reviewer: `source_handoffs`; configured model per parent assignment GPT-6.1-sol,
exact runtime snapshot unavailable. The integrated-comparison follow-up was
authored by the separate `comparison` worker. This review inspected its replay,
conditional positioning dependencies, stage reason/dependency aggregation,
causal restart selection and source-aware guidance. It found and reported the
causal restart defect described above; the author supplied the regression and
fix. No unresolved finding remained at the frozen file identities above.

The review independently ran four focused cases: self-consistent integrated
comparison tampering, declared-basis positioned comparison, attributed stage
summaries, and causal restart with unrelated invalid artifacts. Three passed;
the guidance case failed while the parent-requested guidance assertion had
landed before its implementation. After the author froze that implementation,
the reviewer reran only the previously failing case:

```sh
uv run pytest packages/mp-review/tests/test_artifact_inspect.py::test_integrated_dashboard_comparison_tamper_is_invalid_despite_self_consistent_hash --no-cov -q
```

**1 passed in 0.18s**. The reviewer independently verified all three final file
SHA-256 identities above. The 64-test and mypy results belong to the author gate;
the reviewer did not repeat those broader checks. Integrated guidance now names
the retained `DashboardBundle` at `dashboard/source.json`, its source-owned
comparison specifications and regeneration through the dashboard producer into
a new output directory; standalone guidance remains separate. Parent final
combined gates and rebuilt archives remain separate acceptance evidence.

Independent reviewer `source_handoffs` signed off the frozen bytes above: causal restart, attributed stage reasons/dependencies, integrated comparison replay, known-basis positional fixture and retained DashboardBundle guidance had no unresolved finding. The final guidance/tamper regression passed independently **1/1 in 0.18s**; the other three focused review cases had already passed. The reviewer made no C production edits.
