# Makefile Improvements Design

> Historical snapshot: This plan/design document captures implementation context on its date. It may not reflect current code, defaults, test counts, or workflow state.


**Date:** 2026-02-16
**Approach:** Surgical Cleanup + Targeted Additions (Approach A)

## Bug Fixes & Correctness

1. **`rm` -> `trash`**: Replace all `rm -rf` / `find -delete` in `clean` and `distclean` with `trash`. Add `TRASH ?= trash` variable (CI can override to `rm -rf`).
2. **Drop `black`**: Remove from `format`, `format-check`, `doctor`, dev deps, and `[tool.black]` config. Ruff handles formatting.
3. **Fix `check` target**: Change `check: lint format type test` to `check: lint format-check type test` (was running formatter instead of checking).
4. **Separate coverage from default test**: Remove `--cov` flags from `pyproject.toml` `addopts`. `make test` becomes fast; `make test-cov` adds coverage explicitly.

## Auto-Generated Help

Replace 34-line manual echo help with `grep`/`awk` pattern extracting `## ` comments. Add `##@` convention for section headers (Setup, Quality, Testing, Utility).

## Structural Cleanup

1. **`.PHONY` grouping**: Break single 200-char line into per-section groups near their targets.
2. **Remove `all: help`**: Redundant with `.DEFAULT_GOAL := help`.
3. **Trim redundant echo messages**: `install-minimal`/`install-dev` double-echo after `install`.

## New Targets

1. **Test subsets**: `test-unit`, `test-integration`, `test-e2e` — directory-scoped pytest runs.
2. **Test watch**: `test-watch` using `pytest-watch` (`ptw`) for TDD iteration. Requires adding `pytest-watch` to dev deps.
3. **Version bumps**: `bump-patch` (0.2.0 -> 0.2.1) and `bump-minor` (0.2.0 -> 0.3.0) — pure shell, no extra deps.

## pyproject.toml Changes

- Remove `black` from `[project.optional-dependencies] dev`
- Remove `[tool.black]` section
- Add `pytest-watch` to dev deps
- Remove `--cov` flags from `[tool.pytest.ini_options] addopts`

## Out of Scope

- GitHub Actions CI workflow (future effort)
- `.pre-commit-config.yaml` framework (future effort)
- `make release` target (future effort)
