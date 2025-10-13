.PHONY: help install lint format test test-cov clean run-extract run-verify

help:
	@echo "Metes Parser - Development Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make install       Install dependencies with uv"
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint          Run ruff linter"
	@echo "  make format        Format code with ruff and black"
	@echo "  make check         Run all checks (lint + format check)"
	@echo ""
	@echo "Testing:"
	@echo "  make test          Run pytest test suite"
	@echo "  make test-cov      Run tests with coverage report"
	@echo ""
	@echo "Utility:"
	@echo "  make clean         Remove build artifacts and cache"
	@echo "  make run-extract   Extract from sample PDF (requires PDF_FILE var)"
	@echo "  make run-verify    Verify sample CSV (requires CSV_FILE var)"

install:
	@echo "Setting up virtual environment and installing dependencies..."
	uv venv
	uv sync --all-extras --dev
	@echo "✓ Installation complete"

lint:
	@echo "Running ruff linter..."
	uv run ruff check src/metesparser
	@echo "✓ Linting complete"

format:
	@echo "Formatting code with ruff..."
	uv run ruff format src/metesparser
	@echo "Formatting code with black..."
	uv run black src/metesparser --exclude text_parser.py || true
	@echo "✓ Formatting complete"

lint-fix:
	@echo "Running ruff linter with auto-fix..."
	uv run ruff check src/metesparser --fix
	@echo "✓ Auto-fix complete"

check: lint
	@echo "Checking code formatting..."
	uv run ruff format src/metesparser --check
	@echo "✓ All checks passed"

test:
	@echo "Running test suite..."
	uv run pytest
	@echo "✓ Tests complete"

test-cov:
	@echo "Running tests with coverage..."
	uv run pytest --cov=src/metesparser --cov-report=html --cov-report=term-missing
	@echo "✓ Coverage report generated in htmlcov/"

clean:
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

run-extract:
	@if [ -z "$(PDF_FILE)" ]; then \
		echo "Error: PDF_FILE variable not set"; \
		echo "Usage: make run-extract PDF_FILE=path/to/deed.pdf"; \
		exit 1; \
	fi
	@echo "Extracting legal description from $(PDF_FILE)..."
	uv run metesparser extract $(PDF_FILE)

run-verify:
	@if [ -z "$(CSV_FILE)" ]; then \
		echo "Error: CSV_FILE variable not set"; \
		echo "Usage: make run-verify CSV_FILE=path/to/calls.csv"; \
		exit 1; \
	fi
	@echo "Verifying calls from $(CSV_FILE)..."
	uv run metesparser verify $(CSV_FILE)

# Development workflow shortcuts
dev-setup: install
	@echo "Creating .env file from example..."
	@if [ ! -f .env ]; then cp .env.example .env; echo "✓ Created .env file - please add your API keys"; fi
	@echo ""
	@echo "✓ Development setup complete!"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Edit .env and add your OPENAI_API_KEY"
	@echo "  2. Run 'make lint' to check code quality"
	@echo "  3. Run 'make test' to run tests"

# Quick quality check before commit
pre-commit: lint-fix format test
	@echo "✓ Pre-commit checks complete - ready to commit!"
