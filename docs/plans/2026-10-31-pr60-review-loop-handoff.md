# PR #60 review loop: handoff (paused 2026-10-31)

Status: **PAUSED** at `6db71e4` on `fix/code-review-2026-10-29` (PR #60, "fix: resolve code-review bugs #49-#73 and 57 follow-up review rounds"). All local gates pass at that commit. Nothing is running and no worktrees are open.

## What the loop was

The goal was to keep finding and fixing bugs test-first until a review found none. Each round:

1. Reviewed PR #60 against `origin/main` in temporary worktrees.
2. Fixed the findings on `fix/pr60-rNN-*` branches with red-green TDD.
3. Merged them into a temporary integration worktree and ran every gate.
4. Recorded the round in [`docs/bugs.md`](../bugs.md) (one `### PR #60 … review` section per round, before `## Known Limitations`), pushed, and updated the PR body.

Rounds 1–57 are recorded. Round 58 was started on `617c24b` and stopped before it reported.

## Where it stands

- **Sample deeds.** Since round 51 every review ran all 227 sample texts (`sample_deeds/*.md`, plus the ground-truth `::legal` and `::normalized` texts) through extraction, verification with tracts, verified export and text review on `origin/main` and the previous head. No course value or misclosure has regressed; verification/export changes are limited to the documented role-policy losses (round 55).
- **Synthetic probes keep finding edge cases.** Rounds 43–57 each found 4–10 issues, mostly in free-text tract classification (parcel vs. exception vs. easement) and `along`/`to` wording. The loop has not converged.
- **Fail-closed role policy (user decision, round 55).** Every tract records `role_basis` (`heading`, `single`, `inferred`). When a deed has more than one description and any role is inferred, nothing exports as verified through any path. Every call of a blocked deed, and of any easement/exception tract, carries a registered blocking note, so subsets, CSV/JSON round trips and re-reviews stay blocked. Text review refuses deeds with more than one parcel description. See AGENTS.md "Verification Before Export", README and CHANGELOG `[Unreleased]`.
- **Documented losses from the policy:** 11 multi-description sample texts no longer export a verified tract; only 8 Kings Highway W (7535-929) `.md` verified on `main` (allow-listed in `tests/unit/test_sample_verification_parity.py`).

## Gates at `6db71e4`

| Gate | Result |
|---|---|
| `uv run pytest packages/mp-*/tests plugins/metesparser/tests --no-cov --import-mode=importlib -q` | 7701 passed, 27 skipped (opt-in browser/Mapbox) |
| `uv run pytest tests -q` | 6196 passed, 23 skipped, 95.03% coverage |
| `uv run ruff check packages src tests scripts` and `ruff format --check` | clean |
| `uv run mypy src/metesparser` | clean |
| Package mypy (`mp-review`, `mp-parse`, `mp-export`, `mp-verify`, `mp-models`) | 17 errors, the baseline from before the PR |

Native Claude/Cowork acceptance and live Mapbox acceptance were not run.

## Key tests to keep green

- `packages/mp-parse/tests/test_tract_classification_corpus.py`: 253+ deed cases defining tract classification, each re-run in four course-numbering styles, plus property tests (preamble recitals, rights recitals in a parcel intro) and the role-policy export test (`ROLE_POLICY_EXPORT_LOSSES`, `R56_EXPORTS`).
- `tests/unit/test_pr60_r56_role_policy_tdd.py`, `test_pr60_r57_role_gate_tdd.py`, `test_pr60_r58_mark_tdd.py`: the role gate and the "no subset verifies" property test.
- `tests/unit/test_sample_verification_parity.py`: sample verification against the recorded `main` baseline.

## Next steps

1. **Re-run round 58** on the current head. Ask for (a) any verified export of inferred or non-boundary land, (b) any single-description or plainly headed deed that verified on `main` and no longer does, (c) any single-description deed typed non-MAIN, and (d) CHANGELOG/README accuracy. Use the sample comparison against `origin/main` and the previous head.
2. **Decide whether to merge.** A reasonable stop rule: a round that finds no verified export of inferred/non-boundary land and no single-description or clean-headed regression against `main`. Wording-only and fail-closed findings can then be tracked in `docs/bugs.md` instead of looped on.
3. Open known limitations are listed in each round's "Known limitations" bullet in `docs/bugs.md` (rounds 35–57) and in its `## Known Limitations` section, including the ground-truth discrepancies for 75 Haddon Ave and 101-111 Kings Highway E.

## Notes for a fresh session

- The sample-comparison scripts used during the loop lived in the session scratchpad and are not in the repository; rebuild them from the method above (run every sample text on two worktrees and diff course values, misclosure, area, verification status and export eligibility).
- Agent briefs started with `git merge --ff-only fix/code-review-2026-10-29`, worked on `fix/pr60-rNN-*`, and never stashed, reset or cleaned. Integration happened in a separate worktree so the main checkout stayed on `docs/code-review-2026-10-29`.
- Package mypy needs zsh word splitting when the package paths are held in one variable (`${=P}`).
