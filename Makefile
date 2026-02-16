SHELL := /bin/bash

# Tooling and path defaults.
UV ?= uv
UV_RUN := $(UV) run
PY_SRC := src/metesparser
PY_TESTS := tests
TRASH ?= trash

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

# --------------------------------------------------------------------------- #
# Help (auto-generated from ## comments; ##@ lines become section headers)
# --------------------------------------------------------------------------- #

.PHONY: help
help: ## Show available commands.
	@awk 'BEGIN {FS = ":.*##"; printf "\nMetes Parser — Development Commands\n\n"} \
		/^##@/ {printf "\033[1m%s\033[0m\n", substr($$0, 5)} \
		/^[a-zA-Z0-9_-]+:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' \
		$(MAKEFILE_LIST)
	@echo ""

# =========================================================================== #
##@ Setup
# =========================================================================== #

.PHONY: install install-minimal install-dev install-offline check-tools lockfile-check doctor dev-setup

install: ## Install dependencies (defaults to all extras + dev).
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
		$(UV_RUN) pytest --version >/dev/null 2>&1 || \
			{ echo "WARN: missing expected dependencies (ruff/pytest)"; }; \
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
install-minimal: install ## Install runtime dependencies only (no dev).

install-dev: UV_SYNC_ARGS=$(UV_SYNC_ARGS_DEV)
install-dev: install ## Install dependencies with extras and dev tooling.

install-offline: OFFLINE=1
install-offline: install ## Install in offline mode (no dependency sync).

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
	fi
	@provider="$${METESPARSER_LLM_PROVIDER:-openai}"; \
	if [ -z "$$provider" ]; then \
		provider="openai"; \
	fi; \
	case "$$provider" in \
		openai|gemini) \
			echo "✓ METESPARSER_LLM_PROVIDER=$$provider"; \
			;; \
		*) \
			echo "ERROR: unsupported METESPARSER_LLM_PROVIDER=$$provider"; \
			echo "Expected: openai or gemini"; \
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
	else \
		if [ -z "$$GEMINI_API_KEY" ]; then \
			echo "ERROR: GEMINI_API_KEY is required when provider is gemini"; \
			exit 1; \
		fi; \
		echo "✓ GEMINI_API_KEY is set"; \
		provider_url="https://generativelanguage.googleapis.com"; \
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

lockfile-check: ## Ensure uv.lock is in sync with pyproject.toml.
	@echo "Checking uv.lock freshness..."
	@[ -f uv.lock ] || { echo "ERROR: uv.lock not found"; exit 1; }
	@if [ pyproject.toml -nt uv.lock ]; then \
		echo "ERROR: pyproject.toml was modified after uv.lock"; \
		echo "Run 'uv lock' to refresh dependency resolution metadata."; \
		exit 1; \
	fi
	@echo "✓ uv.lock present and up to date"

dev-setup: install ## Bootstrap local environment (.env + dependencies).
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "✓ Created .env file — please add your API keys"; \
	fi
	@echo ""
	@echo "✓ Development setup complete!"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Edit .env and set METESPARSER_LLM_PROVIDER plus the matching API key"
	@echo "  2. Run 'make lint' to check code quality"
	@echo "  3. Run 'make test' to run tests"

# =========================================================================== #
##@ Code Quality
# =========================================================================== #

.PHONY: lint lint-fix format format-check quality type check

lint: ## Run static analysis with Ruff.
	@echo "Running ruff linter..."
	$(UV_RUN) ruff check $(PY_SRC) $(PY_TESTS)
	@echo "✓ Linting complete"

lint-fix: ## Auto-fix Ruff-detected issues.
	@echo "Running ruff linter with auto-fix..."
	$(UV_RUN) ruff check $(PY_SRC) $(PY_TESTS) --fix
	@echo "✓ Auto-fix complete"

format: ## Format source files with Ruff.
	@echo "Formatting code with ruff..."
	$(UV_RUN) ruff format $(PY_SRC) $(PY_TESTS)
	@echo "✓ Formatting complete"

format-check: ## Verify formatting without making changes.
	@echo "Checking code formatting..."
	$(UV_RUN) ruff format $(PY_SRC) $(PY_TESTS) --check
	@echo "✓ Format check passed"

quality: lint format-check ## Run lint + format checks (read-only).
	@echo "✓ Quality checks complete"

type: ## Run mypy static type checking.
	@echo "Running mypy checks..."
	$(UV_RUN) mypy src/metesparser
	@echo "✓ Type checks complete"

check: lint format-check type test ## Run all checks (lint + format-check + type + test).
	@echo "✓ All checks passed"

# =========================================================================== #
##@ Testing
# =========================================================================== #

.PHONY: test test-fast test-cov test-unit test-integration test-e2e test-watch ci

test: ## Run full test suite.
	@echo "Running test suite..."
	$(UV_RUN) pytest
	@echo "✓ Tests complete"

test-fast: ## Run tests with fail-fast (stop on first failure).
	@echo "Running tests with fail-fast..."
	$(UV_RUN) pytest -x --maxfail=1
	@echo "✓ Fast tests complete"

test-cov: ## Run tests with HTML and terminal coverage reports.
	@echo "Running tests with coverage..."
	$(UV_RUN) pytest --cov=$(PY_SRC) --cov-report=html --cov-report=term-missing
	@echo "✓ Coverage report generated in htmlcov/"

test-unit: ## Run unit tests only.
	@echo "Running unit tests..."
	$(UV_RUN) pytest tests/unit -v
	@echo "✓ Unit tests complete"

test-integration: ## Run integration tests only.
	@echo "Running integration tests..."
	$(UV_RUN) pytest tests/integration -v
	@echo "✓ Integration tests complete"

test-e2e: ## Run end-to-end tests only.
	@echo "Running end-to-end tests..."
	$(UV_RUN) pytest tests/e2e -v
	@echo "✓ End-to-end tests complete"

test-watch: ## Re-run unit tests on file changes (requires pytest-watcher).
	$(UV_RUN) ptw . -- tests/unit -v --maxfail=1

ci: clean check-tools install quality test-cov ## CI-oriented full validation lane.
	@echo "✓ CI checks complete"

# =========================================================================== #
##@ Utility
# =========================================================================== #

.PHONY: clean distclean run-extract run-verify pre-commit bump-patch bump-minor

clean: ## Remove generated artifacts and caches.
	@echo "Cleaning build artifacts..."
	$(TRASH) .venv 2>/dev/null || true
	$(TRASH) build 2>/dev/null || true
	$(TRASH) dist 2>/dev/null || true
	$(TRASH) *.egg-info 2>/dev/null || true
	$(TRASH) .pytest_cache 2>/dev/null || true
	$(TRASH) .ruff_cache 2>/dev/null || true
	$(TRASH) htmlcov 2>/dev/null || true
	$(TRASH) .coverage 2>/dev/null || true
	find . -type d -name __pycache__ -exec $(TRASH) {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -exec $(TRASH) {} + 2>/dev/null || true
	find . -type f -name "*.pyo" -exec $(TRASH) {} + 2>/dev/null || true
	@echo "✓ Cleanup complete"

distclean: clean ## Remove environment and extra local caches.
	@echo "Cleaning extra development artifacts..."
	$(TRASH) .uv-cache 2>/dev/null || true
	$(TRASH) output 2>/dev/null || true
	$(TRASH) extraction_output 2>/dev/null || true
	@echo "✓ Dist-clean complete"

run-extract: ## Extract from a deed PDF (requires PDF_FILE=...).
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

run-verify: ## Verify a CSV file (requires CSV_FILE=...).
	@if [ -z "$(CSV_FILE)" ]; then \
		echo "Error: CSV_FILE variable not set"; \
		echo "Usage: make run-verify CSV_FILE=path/to/calls.csv"; \
		exit 1; \
	fi
	@if [ ! -f "$(CSV_FILE)" ]; then \
		echo "Error: CSV file not found: $(CSV_FILE)"; \
		exit 1; \
	fi
	@if [ ! -s "$(CSV_FILE)" ]; then \
		echo "Error: CSV file is empty: $(CSV_FILE)"; \
		exit 1; \
	fi
	@echo "Verifying calls from $(CSV_FILE)..."
	$(UV_RUN) metesparser verify "$(CSV_FILE)"

pre-commit: lint-fix format test ## Lint-fix, format, and test before committing.
	@echo "✓ Pre-commit checks complete — ready to commit!"

bump-patch: ## Bump patch version (e.g. 0.2.0 -> 0.2.1).
	@current=$$(grep -m1 '^version = ' pyproject.toml | cut -d'"' -f2); \
	IFS='.' read -r major minor patch <<< "$$current"; \
	new="$$major.$$minor.$$((patch+1))"; \
	sed -i '' "s/version = \"$$current\"/version = \"$$new\"/" pyproject.toml; \
	echo "Bumped $$current -> $$new"

bump-minor: ## Bump minor version (e.g. 0.2.0 -> 0.3.0).
	@current=$$(grep -m1 '^version = ' pyproject.toml | cut -d'"' -f2); \
	IFS='.' read -r major minor patch <<< "$$current"; \
	new="$$major.$$((minor+1)).0"; \
	sed -i '' "s/version = \"$$current\"/version = \"$$new\"/" pyproject.toml; \
	echo "Bumped $$current -> $$new"
