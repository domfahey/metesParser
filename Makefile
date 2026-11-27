SHELL := /bin/bash
.DEFAULT_GOAL := all

# Tooling and path defaults.
UV ?= uv
UV_RUN := $(UV) run

.PHONY: review-corpus plugin-build chat-skill-build
review-corpus: ## Run reviewed deterministic pipeline fixtures without OCR.
	$(UV_RUN) python -m mp_review corpus packages/mp-review/tests/fixtures/corpus.json

plugin-build: ## Build the Claude plugin ZIP with a locked deterministic runtime.
	$(UV_RUN) python scripts/build_claude_plugin.py

chat-skill-build: ## Build the standalone Claude chat Skill ZIP and checksum.
	$(UV_RUN) python scripts/build_claude_skill.py
PY_SRC := src/metesparser
PY_TESTS := tests
PKG_PY_SRCS := $(sort $(wildcard packages/*/src))
PKG_COV_MODULES := $(sort $(notdir $(patsubst %/__init__.py,%,$(wildcard packages/*/src/*/__init__.py))))
PKG_COV_ARGS := $(addprefix --cov=,$(PKG_COV_MODULES))
PKG_COV_EXTRAS ?= --extra dev --extra delivery --extra geo --extra web-map --extra gemini
PKG_COV_FLOOR ?= 95

# Cache/tooling behavior.
UV_CACHE_DIR ?= $(CURDIR)/.uv-cache
export UV_CACHE_DIR

# Install mode flags.
OFFLINE ?= 0

# Dependency sync profiles.
UV_SYNC_ARGS ?= --all-extras --dev
UV_SYNC_ARGS_MINIMAL ?= --no-dev
UV_SYNC_ARGS_DEV ?= --all-extras --dev
# Set to 1 to fail doctor when provider endpoints are unreachable.
DOCTOR_REQUIRE_CONNECTIVITY ?= 0

# Default target when running `make` with no args.
.DEFAULT_GOAL := help

# Targets that are not real files.
.PHONY: all help install install-minimal install-dev install-offline check-tools lockfile-check quality ci distclean test-fast lint lint-fix format format-check check test test-packages test-packages-cov test-plugin test-cov clean run-extract run-verify dev-setup pre-commit doctor type review-corpus plugin-build chat-skill-build
.NOTPARALLEL:

all: help

help: ## Show available development commands and their usage.
	@echo "Metes Parser - Development Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make install       Install full dependency set (defaults to all extras + dev)"
	@echo "  make install-minimal Install runtime dependencies only (skip dev dependencies)"
	@echo "  make install-dev     Install dependencies with extras and dev tooling"
	@echo "  make install-offline Install deps without network access (uses existing environment)"
	@echo "  make install-offline OFFLINE=1  Also works as a direct alias"
	@echo "  make check-tools   Verify required CLI tools"
	@echo "  make lockfile-check Verify uv.lock sync state"
	@echo "  make doctor        Check project dependencies and environment"
	@echo "  make dev-setup     Bootstrap repo and create .env"
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint          Run ruff linter"
	@echo "  make lint-fix      Run ruff with auto-fix"
	@echo "  make format        Format code with ruff"
	@echo "  make format-check  Check formatter compliance"
	@echo "  make type          Run mypy type checks"
	@echo "  make check         Run all checks (lint + format + type + test)"
	@echo "  make quality       Run lint + formatting checks"
	@echo ""
	@echo "Testing:"
	@echo "  make test          Run pytest test suite"
	@echo "  make test-packages     Run composable package test suites"
	@echo "  make test-packages-cov Run composable package tests with coverage report"
	@echo "  make test-plugin       Run Claude plugin test suite"
	@echo "  make test-fast     Run tests with fail-fast behavior"
	@echo "  make test-cov      Run tests with coverage report"
	@echo "  make review-corpus Run reviewed deterministic pipeline fixtures without OCR"
	@echo "  make ci            Run the CI-style full check workflow"
	@echo ""
	@echo "Utility:"
	@echo "  make clean         Remove build artifacts and cache"
	@echo "  make distclean     Remove environment and ephemeral caches"
	@echo "  make plugin-build  Build the Claude plugin ZIP with a locked deterministic runtime"
	@echo "  make chat-skill-build Build the standalone Claude chat Skill ZIP and checksum"
	@echo "  make run-extract   Extract from sample PDF (requires PDF_FILE var)"
	@echo "  make run-verify    Verify sample CSV (requires CSV_FILE var)"
	@echo "  make pre-commit    Run lint-fix, format, and tests"

install: ## Install dependencies using UV with default profile (extras + dev).
	@echo "Setting up virtual environment and installing dependencies..."
	@if [ -d ".venv" ]; then \
		echo "Using existing virtual environment at .venv"; \
	else \
		$(UV) venv; \
	fi
	@if [ "$(OFFLINE)" = "1" ]; then \
		echo "Running in offline mode (OFFLINE=1): skipping network dependency sync."; \
		echo "Verifying existing runtime tooling..."; \
		$(UV_RUN) ruff --version >/dev/null 2>&1 && \
		$(UV_RUN) pytest --version >/dev/null 2>&1 || { echo "WARN: missing expected dependencies (ruff/pytest)"; }; \
	else \
		if ! $(UV) sync $(UV_SYNC_ARGS); then \
			echo "✗ Dependency installation failed"; \
			echo "Hint: this often happens when network/DNS is unavailable."; \
			echo "If you are offline, run this on a machine with network access to complete setup."; \
			exit 1; \
		fi; \
	fi
	@echo "✓ Installation complete"

install-minimal: UV_SYNC_ARGS=$(UV_SYNC_ARGS_MINIMAL)
install-minimal: install ## Install runtime dependencies only.
	@echo "Minimal install complete."

install-dev: UV_SYNC_ARGS=$(UV_SYNC_ARGS_DEV)
install-dev: install ## Install dependencies with extras and dev tooling.
	@echo "Development install complete."

install-offline: OFFLINE=1
install-offline: install ## Install in offline mode (no dependency sync).
	@echo "Offline install requested; rerun 'make install' on a networked machine when available."

check-tools: ## Verify required CLI tools are available.
	@echo "Checking required CLI tools..."
	@command -v $(UV) >/dev/null 2>&1 || { echo "ERROR: uv not installed"; exit 1; }
	@echo "✓ uv is installed"
	@command -v make >/dev/null 2>&1 || { echo "ERROR: make is not installed"; exit 1; }
	@echo "✓ make is installed"

doctor: check-tools lockfile-check ## Validate environment and dependency health.
	@echo "Running project doctor checks..."
	@echo "Checking project metadata..."
	@[ -f pyproject.toml ] || { echo "ERROR: pyproject.toml not found"; exit 1; }
	@echo "✓ pyproject.toml present"
	@echo "Verifying toolchain access..."
	@$(UV_RUN) python --version
	@missing_tools=0; \
	for dep in ruff pytest mypy; do \
		$(UV_RUN) "$${dep}" --version >/dev/null 2>&1 || { echo "ERROR: missing dependency in .venv: $${dep}"; missing_tools=1; }; \
	done; \
	if [ "$$missing_tools" -ne 0 ]; then \
		echo "Run 'make install' to install required tool dependencies."; \
		exit 1; \
	fi
	@echo "Checking UV cache directory..."
	@if [ ! -d "$(UV_CACHE_DIR)" ]; then \
		mkdir -p "$(UV_CACHE_DIR)" || { echo "ERROR: unable to create UV cache directory: $(UV_CACHE_DIR)"; exit 1; }; \
		echo "✓ created UV cache directory $(UV_CACHE_DIR)"; \
	fi
	@cache_check_file="$(UV_CACHE_DIR)/.doctor-write-test"; \
	echo "test" > "$$cache_check_file" || { echo "ERROR: cannot write to UV cache directory: $(UV_CACHE_DIR)"; exit 1; }; \
	rm -f "$$cache_check_file"
	@echo "✓ UV cache directory is writable: $(UV_CACHE_DIR)"
	@if [ -f .env ]; then \
		echo "✓ .env file present"; \
	else \
		echo "WARN: .env file missing; run 'make dev-setup' or copy from .env.example"; \
	fi
	@if [ -f .env ]; then \
		echo "Loading .env values for validation..."; \
		set -a; . ./.env; set +a; \
	else \
		echo "INFO: continuing with current shell environment only"; \
	fi; \
	provider="$${METESPARSER_LLM_PROVIDER:-openai}"; \
	if [ -z "$$provider" ]; then \
		provider="openai"; \
	fi; \
	provider="$$(printf '%s' "$$provider" | tr '[:upper:]' '[:lower:]')"; \
	case "$$provider" in \
		openai|gemini|openrouter) \
			echo "✓ METESPARSER_LLM_PROVIDER=$$provider"; \
			;; \
		*) \
			echo "ERROR: unsupported METESPARSER_LLM_PROVIDER=$$provider"; \
			echo "Expected: openai, gemini, or openrouter"; \
			exit 1; \
			;; \
	esac; \
	if [ "$$provider" = "openai" ]; then \
		if [ -z "$$OPENAI_API_KEY" ]; then \
			echo "ERROR: OPENAI_API_KEY is required when provider is openai"; \
			exit 1; \
		fi; \
		echo "✓ OPENAI_API_KEY is set"; \
		provider_url="https://api.openai.com"; \
	elif [ "$$provider" = "gemini" ]; then \
		if [ -z "$$GEMINI_API_KEY" ]; then \
			echo "ERROR: GEMINI_API_KEY is required when provider is gemini"; \
			exit 1; \
		fi; \
		echo "✓ GEMINI_API_KEY is set"; \
		provider_url="https://generativelanguage.googleapis.com"; \
	else \
		if [ -z "$$OPENROUTER_API_KEY" ]; then \
			echo "ERROR: OPENROUTER_API_KEY is required when provider is openrouter"; \
			exit 1; \
		fi; \
		echo "✓ OPENROUTER_API_KEY is set"; \
		provider_url="https://openrouter.ai"; \
	fi; \
	echo "Checking network connectivity to $$provider provider endpoint..."; \
	connectivity_ok=1; \
	if command -v curl >/dev/null 2>&1; then \
		if curl -sS -m 6 -o /dev/null "$$provider_url" >/dev/null; then \
			echo "✓ provider endpoint reachable: $$provider_url"; \
		else \
			echo "ERROR: cannot reach $$provider_url from this environment (possible DNS/network restriction)."; \
			connectivity_ok=0; \
		fi; \
	else \
		echo "ERROR: curl not installed; cannot verify provider endpoint reachability."; \
		connectivity_ok=0; \
	fi; \
	if [ "$$connectivity_ok" -eq 0 ] && [ "$(DOCTOR_REQUIRE_CONNECTIVITY)" = "1" ]; then \
		echo "Set DOCTOR_REQUIRE_CONNECTIVITY=0 to allow doctor to pass without outbound connectivity."; \
		exit 1; \
	fi
	@echo "✓ Doctor checks complete"

lockfile-check: ## Ensure uv.lock is present and in sync with pyproject.toml.
	@echo "Checking uv.lock freshness..."
	@[ -f uv.lock ] || { echo "ERROR: uv.lock not found"; exit 1; }
	@$(UV) lock --check || { echo "ERROR: uv.lock is out of sync with pyproject.toml; run 'uv lock' to refresh."; exit 1; }
	@echo "✓ uv.lock present and up to date"

lint: ## Run static analysis with Ruff.
	@echo "Running ruff linter..."
	$(UV_RUN) ruff check $(PY_SRC) $(PY_TESTS)
	@echo "✓ Linting complete"

format: ## Format source files with Ruff.
	@echo "Formatting code with ruff..."
	$(UV_RUN) ruff format $(PY_SRC) $(PY_TESTS)
	@echo "✓ Formatting complete"

lint-fix: ## Auto-fix Ruff-detected issues.
	@echo "Running ruff linter with auto-fix..."
	$(UV_RUN) ruff check $(PY_SRC) $(PY_TESTS) --fix
	@echo "✓ Auto-fix complete"

format-check: ## Verify formatting without making changes.
	@echo "Checking code formatting..."
	$(UV_RUN) ruff format $(PY_SRC) $(PY_TESTS) --check
	@echo "✓ All checks passed"

quality: lint format-check ## Run lint + format checks.
	@echo "✓ Quality checks complete"

check: lint format type test ## Run lint, format, type checks, and tests.
	@echo "✓ All checks passed"

type: ## Run mypy static type checking.
	@echo "Running mypy checks..."
	$(UV_RUN) mypy src/metesparser
	@echo "✓ Type checks complete"

test: ## Run full test suite.
	@echo "Running test suite..."
	$(UV_RUN) pytest
	@echo "✓ Tests complete"

test-packages: ## Run composable package test suites.
	@echo "Running package test suites..."
	$(UV_RUN) pytest packages/*/tests --no-cov --import-mode=importlib
	@echo "✓ Package tests complete"

test-packages-cov: ## Run composable package tests with per-package and aggregate coverage floors.
	@echo "Running package test suites with coverage..."
	@test -n "$(strip $(PKG_PY_SRCS))" || { echo "ERROR: PKG_PY_SRCS expanded empty; run from repository root."; exit 1; }
	@test -n "$(strip $(PKG_COV_MODULES))" || { echo "ERROR: PKG_COV_MODULES expanded empty; run from repository root."; exit 1; }
	@test -n "$(strip $(PKG_COV_FLOOR))" || { echo "ERROR: PKG_COV_FLOOR must be set."; exit 1; }
	@mkdir -p htmlcov/packages
	@rm -f htmlcov/packages/packages.coverage htmlcov/packages/packages.coverage.* htmlcov/packages/coverage.json
	COVERAGE_FILE=htmlcov/packages/packages.coverage $(UV_RUN) $(PKG_COV_EXTRAS) pytest -o addopts="-v --strict-markers" packages/*/tests --import-mode=importlib $(PKG_COV_ARGS) --cov-report=html:htmlcov/packages --cov-report=term-missing --cov-report=json:htmlcov/packages/coverage.json --cov-fail-under="$(PKG_COV_FLOOR)"
	@$(UV_RUN) --no-sync python -c 'import json, pathlib, re, sys; from coverage.results import display_covered, should_fail_under; data = json.loads(pathlib.Path("htmlcov/packages/coverage.json").read_text(encoding="utf-8")); floor = float(sys.argv[1]); mods = sys.argv[2:]; mod_set = set(mods); totals = {m: [0, 0] for m in mods}; unmatched = []; rx_pkg = re.compile(r"(?:^|/)packages/[^/]+/src/([^/]+)/"); rx_sp = re.compile(r"(?:^|/)site-packages/([^/]+)/"); resolve = lambda raw: (m1.group(1) if (m1 := rx_pkg.search(raw)) else (m2[-1] if (m2 := rx_sp.findall(raw)) else raw.split("/", 1)[0])); [totals.__setitem__(m, [totals[m][0] + info["summary"]["covered_lines"], totals[m][1] + info["summary"]["num_statements"]]) if (m := resolve(f.replace("\\", "/"))) in mod_set else unmatched.append((f, m)) for f, info in data["files"].items()]; unmatched and sys.exit(f"FAIL: coverage files did not map to a workspace package: {unmatched}"); failed = []; [print(f"  {m:12s} {c}/{t} ({display_covered(pct, 2)}%)") or ((not t or should_fail_under(pct, floor, 2)) and failed.append((m, c, t))) for m, (c, t) in totals.items() for pct in [100.0 * c / t if t else 0.0]]; sys.exit(f"FAIL: per-package coverage below {floor:.2f}%: {failed}") if failed else print(f"OK: all {len(mods)} workspace packages met >= {floor:.2f}% floor")' "$(PKG_COV_FLOOR)" $(PKG_COV_MODULES)
	@echo "✓ Package coverage report generated in htmlcov/packages/"

test-plugin: ## Run Claude plugin test suite.
	@echo "Running plugin test suite..."
	$(UV_RUN) pytest plugins/metesparser/tests --no-cov --import-mode=importlib
	@echo "✓ Plugin tests complete"

test-fast: ## Run tests with fail-fast behavior.
	@echo "Running tests with fail-fast..."
	$(UV_RUN) pytest -x --maxfail=1
	@echo "✓ Fast tests complete"

.PHONY: test-dashboard-browser
test-dashboard-browser: ## Require Chromium/Node and run offline dashboard browser regressions.
	$(UV_RUN) --extra browser-test python scripts/check_dashboard_browser.py
	METESPARSER_BROWSER_TESTS=1 $(UV_RUN) --extra browser-test pytest tests/browser --no-cov --import-mode=importlib

.PHONY: test-mapbox-browser test-mapbox-live
test-mapbox-browser: ## Test the map adapter and pinned SDK locally, without provider credentials.
	$(UV_RUN) --extra browser-test --extra web-map python scripts/check_mapbox_browser.py
	METESPARSER_MAPBOX_BROWSER_TESTS=1 $(UV_RUN) --extra browser-test --extra web-map pytest packages/mp-export/tests/browser/test_online_map_ui.py packages/mp-export/tests/browser/test_standalone_map_ui.py packages/mp-export/tests/browser/test_mapbox_sdk.py --no-cov --import-mode=importlib

test-mapbox-live: ## Explicit provider acceptance; requires a runtime public token and network access.
	$(UV_RUN) --extra browser-test --extra web-map python scripts/check_mapbox_browser.py --live
	METESPARSER_MAPBOX_LIVE_TESTS=1 $(UV_RUN) --extra browser-test --extra web-map pytest packages/mp-export/tests/browser/test_mapbox_live.py --no-cov --import-mode=importlib

test-cov: ## Run tests with HTML and terminal coverage reports.
	@echo "Running tests with coverage..."
	@mkdir -p htmlcov
	@rm -f htmlcov/root.coverage htmlcov/root.coverage.*
	COVERAGE_FILE=htmlcov/root.coverage $(UV_RUN) pytest
	@echo "✓ Coverage report generated in htmlcov/"

ci: check-tools install quality test-cov test-packages-cov ## CI-oriented end-to-end validation lane.
	@echo "✓ CI checks complete"

clean: ## Remove generated artifacts and caches.
	@echo "Cleaning build artifacts..."
	rm -rf .venv
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info
	rm -rf .pytest_cache/
	rm -rf .ruff_cache/
	rm -rf .mypy_cache/
	rm -rf htmlcov/
	rm -rf .coverage .coverage.*
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	@echo "✓ Cleanup complete"

distclean: clean ## Remove environments and extra local artifacts.
	@echo "Cleaning extra development artifacts..."
	rm -rf .uv-cache
	rm -rf output/
	@echo "✓ Dist-clean complete"

run-extract: ## Run extraction on a deed PDF (requires PDF_FILE).
	@if [ -z "$(PDF_FILE)" ]; then \
		echo "Error: PDF_FILE variable not set"; \
		echo "Usage: make run-extract PDF_FILE=path/to/deed.pdf"; \
		exit 1; \
	fi
	@if [ ! -f "$(PDF_FILE)" ]; then \
		echo "Error: PDF file not found: $(PDF_FILE)"; \
		exit 1; \
	fi
	@if [ ! -s "$(PDF_FILE)" ]; then \
		echo "Error: PDF file is empty: $(PDF_FILE)"; \
		exit 1; \
	fi
	@echo "Extracting legal description from $(PDF_FILE)..."
	$(UV_RUN) metesparser extract "$(PDF_FILE)"

run-verify: ## Run CSV verification workflow (requires CSV_FILE).
	@if [ -z "$(CSV_FILE)" ]; then \
		echo "Error: CSV_FILE variable not set"; \
		echo "Usage: make run-verify CSV_FILE=path/to/calls.csv"; \
		exit 1; \
	fi
	@echo "Verifying calls from $(CSV_FILE)..."
	@if [ ! -f "$(CSV_FILE)" ]; then \
		echo "Error: CSV file not found: $(CSV_FILE)"; \
		exit 1; \
	fi
	@if [ ! -s "$(CSV_FILE)" ]; then \
		echo "Error: CSV file is empty: $(CSV_FILE)"; \
		exit 1; \
	fi
	$(UV_RUN) metesparser verify "$(CSV_FILE)"

# Development workflow shortcuts
dev-setup: install ## Bootstrap local environment (.env + dependencies).
	@echo "Creating .env file from example..."
	@if [ ! -f .env ]; then cp .env.example .env; echo "✓ Created .env file - please add your API keys"; fi
	@echo ""
	@echo "✓ Development setup complete!"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Edit .env and set METESPARSER_LLM_PROVIDER plus the matching API key"
	@echo "  2. Run 'make lint' to check code quality"
	@echo "  3. Run 'make test' to run tests"

# Quick quality check before commit
pre-commit: lint-fix format test ## Run pre-commit style quality checks.
	@echo "✓ Pre-commit checks complete - ready to commit!"
