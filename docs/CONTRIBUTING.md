# Contributing Guide

Guidelines for contributing to metesParser.

## Getting Started

### Prerequisites

- Python 3.11+
- [UV package manager](https://github.com/astral-sh/uv)
- Git
- OpenAI and/or Gemini API key (for PDF extraction, depending on provider)

### Initial Setup

```bash
# Clone repository
git clone <repo-url>
cd metesParser

# Setup development environment
make dev-setup

# Install dependencies
make install

# Run tests to verify setup
make test
```

## Development Workflow

### 1. Create Feature Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/bug-description
```

### 2. Write Tests First (TDD)

```bash
# Create test file
touch tests/unit/test_new_feature.py

# Write failing test
uv run pytest tests/unit/test_new_feature.py -v

# Implement feature
# ...

# Verify test passes
uv run pytest tests/unit/test_new_feature.py -v
```

### 3. Run Quality Checks

```bash
# Before committing
make pre-commit
```

This runs:
- Linting (ruff)
- Formatting (black)
- Type checking (mypy)
- Full test suite

### 4. Commit Changes

```bash
git add .
git commit -m "feat: Add new feature description"
```

**Commit Message Format**:
```
<type>: <description>

[optional body]

[optional footer]
```

**Types**:
- `feat:` - New feature
- `fix:` - Bug fix
- `refactor:` - Code refactoring
- `test:` - Add/update tests
- `docs:` - Documentation
- `chore:` - Maintenance

### 5. Push and Create PR

```bash
git push origin feature/your-feature-name
```

Then create Pull Request on GitHub.

## Code Style

### Python Style

- **Python 3.11+** syntax (use `|` for unions)
- **Type hints** for all functions
- **Docstrings** for public APIs
- **Line length**: 100 characters
- **Formatter**: black + ruff

```python
def calculate_area(points: list[Point]) -> float:
    """Calculate area using shoelace formula.

    Args:
        points: List of Point objects forming a polygon

    Returns:
        Area in square feet

    Raises:
        ValueError: If fewer than 3 points provided
    """
    if len(points) < 3:
        raise ValueError(f"Cannot calculate area with {len(points)} points")

    # Implementation...
    return area
```

### Testing Style

- **Test file**: `tests/unit/test_<module>.py`
- **Test class**: `TestFeatureName`
- **Test function**: `test_specific_behavior`
- **Use fixtures** from `conftest.py`
- **Parametrize** similar tests
- **Document** complex scenarios

```python
import pytest
from metesparser.module import Class

class TestFeature:
    """Test feature description."""

    def test_normal_case(self, square_100ft):
        """Test normal operation."""
        result = Class.method(square_100ft)
        assert result == expected

    @pytest.mark.parametrize("input,expected", [
        (1, 2),
        (2, 4),
    ])
    def test_multiple_cases(self, input, expected):
        """Test multiple similar cases."""
        assert Class.method(input) == expected
```

## Testing Requirements

### Coverage Goals

- New features: **> 90% coverage**
- Bug fixes: **Add regression test**
- Refactoring: **Maintain existing coverage**

### Test Categories

1. **Unit Tests** (`tests/unit/`)
   - Test individual functions
   - Fast execution (< 100ms)
   - No external dependencies

2. **Integration Tests** (`tests/integration/`)
   - Test complete pipeline
   - May be slower
   - Test real scenarios

3. **Regression Tests** (`tests/regression/`)
   - Prevent bug reintroduction
   - Document bug fixes
   - Keep for audit trail

### Running Tests

```bash
# Run all tests
make test

# Run specific category
uv run pytest tests/unit/ -v
uv run pytest tests/integration/ -v

# Run with coverage
make test-cov
```

## Core Principles

### 1. Never Fabricate Data

❌ **Don't**:
```python
if bearing is None:
    bearing = estimate_from_adjacent_calls()  # WRONG
```

✅ **Do**:
```python
if bearing is None:
    call.notes = "incomplete bearing - manual review required"
```

### 2. Preserve Determinism

All processing must be deterministic:
```python
# Temperature=0 for LLM calls
# No random sampling
# Same input → same output always
```

### 3. Validate Early

Use Pydantic for validation:
```python
class DeedCall(BaseModel):
    distance_ft: float = Field(gt=0)  # Must be > 0
```

### 4. Document Assumptions

```python
def calculate_area(points: list[Point]) -> float:
    """Calculate area using shoelace formula.

    NOTE: This is NOT correct for self-intersecting polygons.
    Assumes simple (non-self-intersecting) polygon.
    """
```

## Common Tasks

### Adding a New Module

1. Create `src/metesparser/new_module.py`
2. Create `tests/unit/test_new_module.py`
3. Write tests first
4. Implement module
5. Add to `__init__.py` if public API
6. Update documentation

### Adding a New Fixture

```python
# In tests/conftest.py
@pytest.fixture
def my_fixture():
    """Fixture description."""
    return create_test_data()
```

### Adding a New Test Marker

```python
# In tests/conftest.py
def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "newmarker: Description of marker"
    )

# In test file
@pytest.mark.newmarker
def test_something():
    pass
```

### Fixing a Bug

1. **Write regression test** that fails
2. **Fix the bug**
3. **Verify test passes**
4. **Add to regression/ directory**
5. **Document in commit message**

Example:
```python
# tests/regression/test_bug_fixes.py
class TestBugXYZ:
    """Bug #XYZ: Description of bug."""

    def test_bug_xyz_fixed(self):
        """Verify bug XYZ is fixed."""
        # Test that previously failed
        result = function_that_was_broken(input)
        assert result == expected
```

## Pull Request Guidelines

### Before Submitting

- [ ] All tests pass (`make test`)
- [ ] Code is formatted (`make format`)
- [ ] Linting passes (`make lint`)
- [ ] Coverage meets requirements
- [ ] Documentation updated
- [ ] Commit messages follow format

### PR Description

Include:
1. **What** changed
2. **Why** it changed
3. **How** to test it
4. **Screenshots** (if UI change)
5. **Breaking changes** (if any)

Example:
```markdown
## Description
Add support for chains as distance unit.

## Why
Users requested ability to parse deeds using chains (1 chain = 66 ft).

## Changes
- Added `chain` to `ConversionFactors`
- Updated `TextParser.extract_distance()` to recognize chains
- Added tests for chain conversion

## Testing
```bash
uv run pytest tests/unit/test_text_parser.py::TestDistanceExtraction -v
```

## Breaking Changes
None
```

### Review Process

1. Automated checks must pass (CI/CD)
2. Code review by maintainer
3. Address feedback
4. Squash commits if requested
5. Merge when approved

## What NOT to Commit

❌ **Never commit**:
- `.env` files
- API keys or secrets
- `__pycache__/` directories
- `.pyc` files
- Personal config files
- Unverified CSV files (only `_verified.csv` acceptable)

✅ **Always commit**:
- Source code
- Tests
- Documentation
- Sample data (non-sensitive)
- Configuration templates (`.env.example`)

## Getting Help

- **GitHub Issues** - Bug reports, feature requests
- **Discussions** - Questions, ideas
- **CLAUDE.md** - AI assistant guidance
- **docs/** - Technical documentation

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

---

Thank you for contributing to metesParser! 🎉
