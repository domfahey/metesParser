SHELL := /bin/bash

# Tooling and path defaults.
UV ?= uv
UV_RUN := $(UV) run
PY_SRC := src/metesparser

# Cache/tooling behavior.
UV_CACHE_DIR ?= $(CURDIR)/.uv-cache
export UV_CACHE_DIR

# Install mode flags.
OFFLINE ?= 0

# Dependency sync profiles.
UV_SYNC_ARGS ?= --all-extras --dev
UV_SYNC_ARGS_MINIMAL ?= --no-dev
UV_SYNC_ARGS_DEV ?= --all-extras --dev

# Default target when running `make` with no args.
.DEFAULT_GOAL := help

# Targets that are not real files.
.PHONY: all help install install-minimal install-dev install-offline check-tools lockfile-check quality ci distclean test-fast lint lint-fix format format-check check test test-cov clean run-extract run-verify dev-setup pre-commit doctor

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
	@echo "  make format        Format code with ruff and black"
	@echo "  make format-check  Check formatter compliance"
	@echo "  make check         Run all checks (lint + format check)"
	@echo "  make quality       Run lint + formatting checks"
	@echo ""
	@echo "Testing:"
	@echo "  make test          Run pytest test suite"
	@echo "  make test-fast     Run tests with fail-fast behavior"
	@echo "  make test-cov      Run tests with coverage report"
	@echo "  make ci            Run the CI-style full check workflow"
	@echo ""
	@echo "Utility:"
	@echo "  make clean         Remove build artifacts and cache"
	@echo "  make distclean      Remove environment and ephemeral caches"
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
		$(UV_RUN) pytest --version >/dev/null 2>&1 && \
		$(UV_RUN) black --version >/dev/null 2>&1 || { echo "WARN: missing expected dependencies (ruff/pytest/black)"; }; \
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
	for dep in ruff pytest black; do \
		$(UV_RUN) "$${dep}" --version >/dev/null 2>&1 || { echo "ERROR: missing dependency in .venv: $${dep}"; missing_tools=1; }; \
	done; \
	if [ "$$missing_tools" -ne 0 ]; then \
		echo "Run 'make install' to install required tool dependencies."; \
		exit 1; \
	fi
	@if [ -f .env ]; then \
		echo "✓ .env file present"; \
	else \
		echo "WARN: .env file missing; run 'make dev-setup' or copy from .env.example"; \
	fi
	@echo "✓ Doctor checks complete"

lockfile-check: ## Ensure uv.lock is present and in sync with pyproject.toml.
	@echo "Checking uv.lock freshness..."
	@[ -f uv.lock ] || { echo "ERROR: uv.lock not found"; exit 1; }
	@if [ pyproject.toml -nt uv.lock ]; then \
		echo "ERROR: pyproject.toml was modified after uv.lock"; \
		echo "Run 'uv lock' to refresh dependency resolution metadata."; \
		exit 1; \
	fi
	@echo "✓ uv.lock present and up to date"

lint: ## Run static analysis with Ruff.
	@echo "Running ruff linter..."
	$(UV_RUN) ruff check $(PY_SRC)
	@echo "✓ Linting complete"

format: ## Format source files with Ruff and Black.
	@echo "Formatting code with ruff..."
	$(UV_RUN) ruff format $(PY_SRC)
	@echo "Formatting code with black..."
	$(UV_RUN) black $(PY_SRC) --exclude text_parser.py
	@echo "✓ Formatting complete"

lint-fix: ## Auto-fix Ruff-detected issues.
	@echo "Running ruff linter with auto-fix..."
	$(UV_RUN) ruff check $(PY_SRC) --fix
	@echo "✓ Auto-fix complete"

format-check: ## Verify formatting without making changes.
	@echo "Checking code formatting..."
	$(UV_RUN) ruff format $(PY_SRC) --check
	$(UV_RUN) black $(PY_SRC) --exclude text_parser.py --check
	@echo "✓ All checks passed"

quality: lint format-check ## Run lint + format checks.
	@echo "✓ Quality checks complete"

check: lint format-check ## Alias for lint + format checks.
	@echo "✓ All checks passed"

test: ## Run full test suite.
	@echo "Running test suite..."
	$(UV_RUN) pytest
	@echo "✓ Tests complete"

test-fast: ## Run tests with fail-fast behavior.
	@echo "Running tests with fail-fast..."
	$(UV_RUN) pytest -x --maxfail=1
	@echo "✓ Fast tests complete"

test-cov: ## Run tests with HTML and terminal coverage reports.
	@echo "Running tests with coverage..."
	$(UV_RUN) pytest --cov=$(PY_SRC) --cov-report=html --cov-report=term-missing
	@echo "✓ Coverage report generated in htmlcov/"

ci: clean check-tools install quality test-cov ## CI-oriented end-to-end validation lane.
	@echo "✓ CI checks complete"

clean: ## Remove generated artifacts and caches.
	@echo "Cleaning build artifacts..."
	rm -rf .venv
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info
	rm -rf .pytest_cache/
	rm -rf .ruff_cache/
	rm -rf htmlcov/
	rm -rf .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	@echo "✓ Cleanup complete"

distclean: clean ## Remove environments and extra local artifacts.
	@echo "Cleaning extra development artifacts..."
	rm -rf .uv-cache
	rm -rf output/
	rm -rf extraction_output/
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
