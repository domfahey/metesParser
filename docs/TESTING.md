# Testing Guide

Comprehensive guide to the metesParser test suite (snapshot: 795 tests collected on 2026-02-16).

## Table of Contents

- [Overview](#overview)
- [Test Organization](#test-organization)
- [Running Tests](#running-tests)
- [PDF Processing Tests](#pdf-processing-tests)
- [Writing Tests](#writing-tests)
- [Fixtures and Helpers](#fixtures-and-helpers)
- [Test Markers](#test-markers)
- [Coverage](#coverage)
- [Best Practices](#best-practices)

## Overview

The test suite ensures correctness of metes & bounds parsing with:
- **795 collected tests** across unit, integration, regression, and e2e categories (snapshot: 2026-02-16)
- **Shared fixtures** for common test scenarios (squares, rectangles, curves)
- **Parametrized tests** to reduce duplication
- **Custom markers** for selective test execution
- **Fast local feedback** for non-PDF tests

### Test Statistics

| Category | Tests | Files | Purpose |
|----------|-------|-------|---------|
| Unit | 722 | 31 | Individual module testing |
| Integration | 31 | 4 | End-to-end text/PDF/pipeline integration |
| Regression | 40 | 1 | Bug fix validation |
| E2E | 2 | 1 | End-to-end CLI workflows |
| **Total** | **795** | **37** | Full coverage |

## Test Organization

Tests are organized into a 5-tier hierarchy:

```
tests/
├── conftest.py
├── helpers.py
├── fixtures/
│   ├── __init__.py
│   └── sample_deeds.py
├── unit/                    # 31 files, 722 tests (snapshot: 2026-02-16)
├── integration/             # 4 files, 31 tests
├── e2e/                     # 1 file, 2 tests
└── regression/              # 1 file, 40 tests
```

### Test File Naming

- `test_<module>.py` - Unit tests for specific module
- Test classes: `TestFeatureName` or `TestMethodName`
- Test functions: `test_specific_behavior`

## Running Tests

### Quick Commands

```bash
# Run all tests
make test

# Run all tests with coverage
make test-cov
```

### Selective Execution

```bash
# Run only unit tests (fast)
uv run pytest tests/unit/ -v

# Run only integration tests
uv run pytest tests/integration/ -v

# Run only regression tests (bug fixes)
uv run pytest tests/regression/ -v

# Run specific test file
uv run pytest tests/unit/test_bearing_converter.py -v

# Run specific test class
uv run pytest tests/unit/test_bearing_converter.py::TestQuadrantParsing -v

# Run specific test function
uv run pytest tests/unit/test_bearing_converter.py::TestQuadrantParsing::test_parse_nde_format -v

# Run tests matching pattern
uv run pytest -k "curve" -v
uv run pytest -k "bearing and not curve" -v
```

### Using Test Markers

```bash
# Run only curve-related tests
uv run pytest -m curve -v

# Run only validation tests
uv run pytest -m validation -v

# Skip slow tests
uv run pytest -m "not slow" -v

# Run integration and regression tests
uv run pytest -m "integration or regression" -v
```

### Debugging Tests

```bash
# Drop into debugger on failure
uv run pytest --pdb

# Drop into debugger on error
uv run pytest --pdbcls=IPython.terminal.debugger:TerminalPdb

# Show local variables on failure
uv run pytest -l

# Verbose output with print statements
uv run pytest -v -s

# Stop on first failure
uv run pytest -x
```

### Parallel Execution

```bash
# Install pytest-xdist
uv add --dev pytest-xdist

# Run tests in parallel (N workers)
uv run pytest -n 4

# Run tests in parallel (auto-detect CPU count)
uv run pytest -n auto
```

## PDF Processing Tests

The `test_pdf_processing.py` module contains 2 integration tests that validate the PDF extraction pipeline using fixture deed text with mocked LLM clients. Additional integration coverage lives in `test_integration.py`, `test_pipeline_contracts.py`, and `test_script_and_packaging_contracts.py`.

### Sample Deeds

Six sample deed PDFs are included for testing:
- `18 Pennbrook Dr - Deed Image (11985 - 00829).pdf`
- `24 Pennbrook Dr - Deed Image (11793 - 00217).pdf`
- `31 Pennbrook Dr - Deed Image (4618 - 717).pdf`
- `31 Pennbrook Dr - Deed Image (9777 - 1354).pdf`
- `31 Pennbrook Dr - Deed Image (10989 - 916).pdf`
- `31 Pennbrook Dr - Deed Image (11191 - 01716).pdf`

The integration fixture uses sample deed text from `sample_deeds.py` (including Pennbrook parcels and a square case) to validate extraction orchestration and closure behavior.

### Prerequisites

PDF processing tests do not require network access by default:
1. **Sample PDFs**: PDFs should be present in `sample_deeds/`
2. **pytest + project dependencies**: Environment is installable via UV
3. **Provider keys**: Required only for optional live-mode experiments (`OPENAI_API_KEY` or `GEMINI_API_KEY`)

If provider keys are absent, tests still run against the mocked client stubs.

### Running PDF Tests

```bash
# Run all PDF processing tests (mocked LLM client by default)
uv run pytest tests/integration/test_pdf_processing.py -v

# Run tests for one fixture case
uv run pytest tests/integration/test_pdf_processing.py -k "square-100ft" -v

# Run a specific PDF-related test
uv run pytest tests/integration/test_pdf_processing.py::test_process_deed_pdf_closure_metrics -v

# Skip PDF tests during development
uv run pytest -m "not slow"

# Run only PDF tests
uv run pytest tests/integration/test_pdf_processing.py -v

# Run PDF tests with output logging
uv run pytest tests/integration/test_pdf_processing.py -v -s
```

### Test Coverage

PDF tests validate:

#### 1. Extraction Pipeline
- PDF → configured LLM provider → legal description extraction
- Text normalization and OCR error correction
- Call parsing from extracted text
- Monument type classification
- POC vs POB distinction

#### 2. Closure Verification
- Traverse closure calculation
- Area and perimeter computation
- Misclosure tolerance checks
- Angle sum verification

#### 3. CSV Export
- Standard CSV export (always works)
- Verified CSV export (only if fully verified)
- Metadata file generation
- Round-trip import/export validation

#### 4. Error Handling
- Missing PDF file handling
- Empty path handling
- Malformed PDF handling

### Test Class Organization

```python
@dataclass(frozen=True)
class PdfCase:
    """Container for mocked PDF fixture expectations."""

    case_id: str
    raw_text: str
    expected_distances: list[float]
    expected_azimuths: list[float]


@pytest.fixture(params=PDF_CASES, ids=lambda case: case.case_id)
def processed_case(request, tmp_path, pdf_processor_factory):
    """Process one mocked PDF case per parametrized test."""
    case = request.param
    pdf_path = tmp_path / f"{case.case_id}.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    processor = pdf_processor_factory(case)
    return case, processor.process_deed_pdf(str(pdf_path))


def test_process_deed_pdf_structures_calls(processed_case):
    ...


def test_process_deed_pdf_closure_metrics(processed_case):
    ...
```

### Expected Behavior

#### 18 Pennbrook Dr
- **Shape**: Parallelogram (NOT rectangle)
- **Calls**: 4
- **Bearings**: N 33°20' E, S 56°40' W, S 33°20' W, N 56°40' E
- **Distances**: 60 ft, 125 ft, 60 ft, 125 ft
- **Closure**: Should close perfectly (misclosure < 0.01 ft)
- **Area**: ~2,971 sq ft
- **Perimeter**: ~370 ft

#### 24 Pennbrook Dr
- **Shape**: Quadrilateral with oblique sides
- **Calls**: 4
- **Area**: ~17,750 sq ft
- **Perimeter**: ~534 ft

#### Square 100 ft fixture
- **Shape**: Right-angle square
- **Calls**: 4
- **Bearings**: N 0° E, E, S 0° E, W
- **Area**: 10,000 sq ft
- **Perimeter**: 400 ft

### Cost Considerations

PDF tests are mocked by default and do not use live provider APIs:
- **Default test cost**: none
- **Behavior**: fully deterministic, fast, network-independent
- **Recommendation**: run against live providers only in custom test variants

Use `pytest -m "not slow"` to run the rest of the suite during development.

### Setup Instructions

1. **Create .env file** (if not exists):
   ```bash
   cp .env.example .env
   ```

2. **Add provider key (optional)**:
   ```bash
   # Optional for live provider runs
   echo "OPENAI_API_KEY=sk-your-actual-key-here" >> .env
   # or
   echo "GEMINI_API_KEY=your-gemini-key" >> .env
   ```

3. **Verify sample PDFs exist**:
   ```bash
   ls -1 sample_deeds/*.pdf
   ```

4. **Run a single test to verify setup**:
   ```bash
   uv run pytest tests/integration/test_pdf_processing.py -k "square-100ft and structures" -v
   ```

5. **Run full PDF suite**:
   ```bash
   uv run pytest tests/integration/test_pdf_processing.py -v
   ```

### Troubleshooting PDF Tests

**"Missing API key for configured LLM provider"**
- Mocked PDF tests still run without provider keys
- Add `OPENAI_API_KEY` or `GEMINI_API_KEY` when running live-mode variants
- Confirm `METESPARSER_LLM_PROVIDER` matches your installed provider package

**"PDF not found" error**
- Verify PDFs are in `sample_deeds/`
- Check exact filenames match (case-sensitive)
- Re-download PDFs if missing

**Custom live-test failures**
- Use provider-specific error messages from the client library
- Confirm API keys and provider selection in `.env`
- Keep live tests limited while iterating to avoid noise and costs

## Writing Tests

### Basic Test Structure

```python
"""Tests for module_name.py - Purpose of tests."""

import pytest
from metesparser.module_name import ClassName


class TestFeatureName:
    """Test specific feature or method."""

    def test_basic_case(self):
        """Test normal operation."""
        result = ClassName.method(input_data)
        assert result == expected_value

    def test_edge_case(self):
        """Test boundary condition."""
        result = ClassName.method(edge_input)
        assert result is not None
```

### Using Fixtures

```python
def test_with_fixture(square_100ft):
    """Use shared fixture from conftest.py."""
    # square_100ft is automatically provided
    result = ClosureChecker.verify_closure(square_100ft)
    assert result.closure_passed is True
```

### Parametrized Tests

```python
@pytest.mark.parametrize(
    "bearing,expected_azimuth",
    [
        ("N 45° E", 45.0),
        ("S 45° E", 135.0),
        ("S 45° W", 225.0),
        ("N 45° W", 315.0),
    ],
)
def test_quadrant_to_azimuth(bearing, expected_azimuth):
    """Test azimuth conversion for all quadrants."""
    azimuth = BearingConverter.bearing_to_azimuth(bearing)
    assert azimuth == expected_azimuth
```

### Using Test Markers

```python
@pytest.mark.slow
def test_large_dataset():
    """This test takes > 1 second."""
    pass

@pytest.mark.curve
def test_curve_calculation():
    """Test curve-specific behavior."""
    pass

@pytest.mark.validation
def test_input_validation():
    """Test input validation logic."""
    pass
```

### Testing Exceptions

```python
def test_invalid_input_raises():
    """Test that invalid input raises ValueError."""
    with pytest.raises(ValueError, match="Radius must be positive"):
        BearingConverter.calculate_curve_properties(radius_ft=0.0, delta_deg=90.0)
```

## Fixtures and Helpers

### Available Fixtures

Fixtures are defined in `tests/conftest.py` and automatically available in all tests.

#### Factory Fixtures

```python
def test_with_factory(deed_call_factory):
    """Create custom DeedCall with defaults."""
    call = deed_call_factory(
        course=5,
        bearing_azimuth_deg_from_north=45.0,
        distance_ft=200.0
    )
    assert call.course == 5
```

#### Shape Fixtures

```python
def test_square(square_100ft):
    """100x100 ft square that closes perfectly."""
    result = ClosureChecker.verify_closure(square_100ft)
    assert result.area_sq_ft == 10000.0

def test_rectangle(pennbrook_18_rectangle):
    """18 Pennbrook parcel (parallelogram, not rectangle!)."""
    result = ClosureChecker.verify_closure(pennbrook_18_rectangle)
    assert result.closure_passed is True
```

#### Curve Fixtures

```python
def test_curve(curve_90deg_right):
    """90° right curve with radius 100 ft."""
    assert curve_90deg_right.delta_deg == 90.0
    assert curve_90deg_right.radius_ft == 100.0
```

### Helper Functions

Helpers are in `tests/helpers.py`:

```python
from tests.helpers import assert_point_near, assert_closure_within_tolerance

def test_with_helpers(square_100ft, origin):
    """Use assertion helpers for cleaner tests."""
    points = ClosureChecker.compute_traverse(square_100ft)

    # Assert last point near origin
    assert_point_near(points[-1], origin, tolerance=0.01)

    # Assert closure
    result = ClosureChecker.verify_closure(square_100ft)
    assert_closure_within_tolerance(result, tolerance=0.01)
```

### Data Generators

```python
from tests.helpers import create_square, create_rectangle

def test_generated_square():
    """Generate test data dynamically."""
    calls = create_square(size=50.0, start_azimuth=0.0)
    result = ClosureChecker.verify_closure(calls)
    assert result.area_sq_ft == 2500.0  # 50 * 50
```

### Sample Legal Descriptions

```python
from tests.fixtures import sample_deeds

def test_with_sample_deed():
    """Use realistic legal description."""
    calls = CallExtractor.extract_calls(sample_deeds.PENNBROOK_18)
    assert len(calls) == 4
```

## Test Markers

Custom markers are registered in `conftest.py`:

| Marker | Purpose | Usage |
|--------|---------|-------|
| `slow` | Tests taking > 1 second | `-m "not slow"` to skip |
| `integration` | End-to-end tests | `-m integration` |
| `regression` | Bug fix tests | `-m regression` |
| `curve` | Curve-specific tests | `-m curve` |
| `validation` | Input validation | `-m validation` |

### Adding New Markers

1. Register in `conftest.py`:
```python
def pytest_configure(config):
    config.addinivalue_line("markers", "newmarker: description")
```

2. Use in tests:
```python
@pytest.mark.newmarker
def test_something():
    pass
```

## Coverage

### Generating Coverage Reports

```bash
# Run tests with coverage
make test-cov

# View HTML report
open htmlcov/index.html

# View terminal report
uv run pytest --cov=src/metesparser --cov-report=term-missing
```

### Coverage Goals

- **Overall target**: > 90% line coverage
- **Critical modules stretch target**: > 95% coverage
- Regenerate current metrics with `make test-cov` and inspect `htmlcov/index.html`

### Excluding from Coverage

Some files are intentionally excluded:
- No module-level omit list is configured by default.
- Use `make test-cov` to inspect current per-module coverage in `htmlcov/index.html`.

## Best Practices

### DO

✅ **Use fixtures for common test data**
```python
def test_with_fixture(square_100ft):
    result = verify_closure(square_100ft)
```

✅ **Parametrize similar tests**
```python
@pytest.mark.parametrize("input,expected", [...])
def test_many_cases(input, expected):
```

✅ **Test edge cases**
- Boundary values (0, 90, 360 degrees)
- Empty inputs
- Invalid inputs
- Rounding edge cases

✅ **Use descriptive test names**
```python
def test_bearing_rounds_to_60_minutes():  # Good
def test_bug_fix_1():                     # Bad
```

✅ **Use assertion helpers**
```python
assert_point_near(p1, p2, tolerance=0.01)
assert_closure_within_tolerance(result)
```

✅ **Document complex test logic**
```python
def test_complex_scenario():
    """Test parallelogram area calculation.

    Note: This is a parallelogram (not rectangle), so area ≠ width × height.
    The actual area is width × height × sin(angle).
    """
```

### DON'T

❌ **Don't repeat test setup code**
```python
# Bad
def test_one():
    call = DeedCall(course=1, direction_text="N", ...)

def test_two():
    call = DeedCall(course=1, direction_text="N", ...)  # Duplicate!

# Good - use fixture
def test_one(deed_call_factory):
    call = deed_call_factory()
```

❌ **Don't use magic numbers**
```python
# Bad
assert math.isclose(dx, 32.9, abs_tol=0.1)

# Good
from tests.helpers import EXPECTED_DX_N33E_60FT
assert math.isclose(dx, EXPECTED_DX_N33E_60FT, abs_tol=0.1)
```

❌ **Don't test implementation details**
```python
# Bad - testing internal state
assert obj._internal_cache == {...}

# Good - testing public behavior
assert obj.get_result() == expected
```

❌ **Don't create brittle tests**
```python
# Bad - assumes specific error message
with pytest.raises(ValueError):
    func(invalid_input)

# Good - matches error message pattern
with pytest.raises(ValueError, match="Radius must be positive"):
    func(invalid_input)
```

## Continuous Integration

### Pre-commit Checks

Run before every commit:
```bash
make pre-commit
```

This runs:
1. Linting (ruff)
2. Formatting (black)
3. Type checking (mypy)
4. Full test suite

### CI/CD Pipeline

Recommended GitHub Actions workflow:

```yaml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install UV
        run: pip install uv
      - name: Install dependencies
        run: uv sync --all-extras --dev
      - name: Run tests
        run: uv run pytest
      - name: Upload coverage
        uses: codecov/codecov-action@v3
```

## Troubleshooting

### Tests Fail After Refactoring

1. Check if fixtures need updating
2. Verify imports are correct
3. Run with `-v` to see which tests fail
4. Use `--pdb` to debug interactively

### Slow Test Suite

1. Use markers to skip slow tests during development:
   ```bash
   uv run pytest -m "not slow"
   ```

2. Run tests in parallel:
   ```bash
   uv run pytest -n auto
   ```

3. Profile tests to find bottlenecks:
   ```bash
   uv run pytest --durations=10
   ```

### Import Errors

Ensure test directories have `__init__.py` files:
```
tests/
├── __init__.py
├── unit/__init__.py
├── integration/__init__.py
└── regression/__init__.py
```

### Fixture Not Found

Check that:
1. Fixture is defined in `conftest.py`
2. Function name matches fixture name exactly
3. No typos in fixture parameter name

## Future Improvements

### Planned Enhancements

- [ ] Add CSV builder unit tests
- [ ] Add models validation tests
- [ ] Split large closure_checker test file
- [ ] Add more parametrization to bearing_converter tests
- [ ] Add property-based testing with Hypothesis
- [ ] Add mutation testing with mutmut
- [ ] Add benchmarking with pytest-benchmark

### Contributing Tests

When adding new features:
1. Write tests first (TDD)
2. Aim for > 90% coverage
3. Use existing fixtures when possible
4. Add new fixtures for reusable scenarios
5. Update this documentation

---

For more information:
- [pytest documentation](https://docs.pytest.org/)
- [pytest fixtures guide](https://docs.pytest.org/en/stable/fixture.html)
- [pytest parametrize](https://docs.pytest.org/en/stable/how-to/parametrize.html)
