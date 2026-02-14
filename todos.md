# Pydantic Audit To-Dos

- [x] High: Add cross-field validation for `DeedCall` curve geometry in `src/metesparser/models.py`.
  - Use `@model_validator(mode="after")` to enforce consistency for `curve_dir`, `radius_ft`, `delta_deg`, `arc_length_ft`, and `chord_length_ft`.
- [x] Medium: Harden assignment behavior for mutable models in `src/metesparser/models.py`.
  - Enable `validate_assignment=True` in model config.
  - Replace in-place mutation of `DeedCall` instances (e.g., `call.bearing_azimuth_deg_from_north = ...`) with `call.model_copy(update={...})` where practical.
- [x] Medium: Normalize enum-like textual inputs for `curve_dir` and `monument_type`.
  - Add normalization/validation so case and formatting differences from CSV/LLM inputs are handled consistently.
- [x] Medium: Reject non-finite numeric values across models.
  - Add finite-number constraints (`finite=True`) for `DeedCall`, `Point`, and `ClosureResult` numeric fields.
- [x] Medium: Tighten model config defaults for external payloads.
  - Set explicit `extra` handling (`"forbid"` or equivalent), and normalize/strip strings at model boundaries.
- [x] Low: Remove redundant azimuth validation overlap.
  - Keep range checks in field constraints and simplify custom azimuth validator to only enforce non-field expressible rules.
- [x] Low: Align `LegalDescription.distance_unit` typing with conversion support.
  - Ensure supported units match `ConversionFactors.convert_to_feet` (including any aliases like `perches` / `links`).

## Documentation Audit To-Dos (2026-02-14)

- [ ] High: Fix broken public API examples in docs that import non-exported package symbols.
  - Update `README.md:99`, `docs/API.md:8`, and `docs/API.md:214` imports to import concrete modules or export symbols in `src/metesparser/__init__.py:6`.
- [ ] High: Correct `CHANGELOG.md` backfill completeness claims.
  - `CHANGELOG.md:10-36` says all commits are included in Unreleased, but `git log -n 30` includes commits not represented (e.g., `602557b`, `8eda598`).
  - Either include missing entries or adjust scope wording.
- [ ] High: Replace or guard references to missing scripts in docs.
  - `README.md:35`, `README.md:44`, and `prompts/README.md:181` reference `scripts/generate_ground_truth.py` / `extract_sample_deeds.py`.
  - These files are not tracked by git (`git ls-files` does not return them).
- [ ] Medium: Update stale test-count language.
  - `README.md:183`, `README.md:302`, `docs/ARCHITECTURE.md:33`, and `docs/TESTING.md:3,20,34` state ~188/190+ tests.
  - Current suite reports 228 collected tests (`pytest --collect-only -q`).
- [ ] Medium: Reconcile versioning mismatch across docs and package metadata.
  - `CLAUDE.md:9` states `0.3.1` while `src/metesparser/__init__.py:6` is `0.1.0`.
  - Align with a single source of truth.
- [ ] Medium: Update test path guidance to current layout.
  - `CLAUDE.md:43`, `CLAUDE.md:135` and related sections reference `tests/test_*.py`.
  - Use current layout (`tests/unit`, `tests/integration`, `tests/regression`).
- [ ] Medium: Align docs coverage targets with current status.
  - `docs/TESTING.md:547-551` claims >90%/95% coverage targets, which do not match current measured coverage output.
  - Clarify as targets or recalculate from current baseline.
- [ ] Low: Correct legal wording for deed dataset documentation.
  - Replace “public domain” phrasing in `sample_deeds/README.md:3` and `sample_deeds/README.md:73` with public-records language.
- [ ] Low: Update fixture-path reference in `AGENTS.md`.
  - `AGENTS.md:8-9` references `tests/data`; current fixtures are under `tests/fixtures`.
