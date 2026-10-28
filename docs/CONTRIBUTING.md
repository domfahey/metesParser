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

# Verify setup with full quality checks
make check
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
- Lint auto-fix (ruff)
- Formatting (ruff)
- Full test suite

Use `make check` for the full quality gate (adds type checking with mypy).

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
- **Formatter**: ruff

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

### Updating Plugin Skills and Their Documentation

Start with the [skill catalog](../plugins/metesparser/README.md#skills) and [handoff contract](../plugins/metesparser/references/artifact-handoffs.md). Keep capabilities independently usable, let workflows select the required stages, and reuse matching artifacts. Preserve `review-deed` as a delegate to the shared review workflow.

Follow the [maintenance guide](CLAUDE_PLUGIN.md#maintain-the-skill-composition) for documentation ownership, shared implementation boundaries, and change validation. Keep substantial procedures in linked references, schemas in the Python models, and user examples in the existing READMEs/usage guide. For documentation-only edits, validate links and changed examples; behavior changes also need relevant engine tests and realistic skill evaluations. Native-host acceptance is a separate check from local tests.

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
- [ ] Per-package tests pass (`for pkg in packages/mp-*/tests/; do uv run pytest "$pkg" -v --no-cov; done`)
- [ ] Cross-package imports verified (`uv run pytest tests/unit/test_cross_package_imports.py -v`)
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

### Online Map Viewer Changes

Keep the optional companion within existing dashboard composition and [online handoff contracts](../plugins/metesparser/references/artifact-handoffs.md#optional-online-map-handoff). Validate token-free configuration against `WebMapRequest` and actual CLI flags. Check package/plugin tests, offline zero-network behavior, adapter interactions, and extracted optional distribution separately. Pinned real-SDK, live provider/WebGL visual composition, and native-host loopback acceptance require their own recorded runs; mocks and authored eval cases cannot satisfy those gates. Never retain real tokens in test traces, logs, artifacts, or screenshots.

#### Manual Mapbox smoke test

Run these commands from the repository root. This developer example reuses the [browser fixture](../packages/mp-export/tests/browser/conftest.py): a four-course rectangle, a parcel context polygon, and an asymmetric 8 × 8 PNG representing a registered tax scan at a known land location. All evidence and placement are synthetic; this does not test a real property's boundary alignment. The fixture imports pytest, so retain the default development dependencies.

```bash
uv sync --extra browser-test --extra web-map
uv run --no-sync python - <<'PY'
import json
import runpy
from pathlib import Path

root = Path("output/mapbox-manual")
root.mkdir(parents=True, exist_ok=False)
helper = runpy.run_path("packages/mp-export/tests/browser/conftest.py")
prepared, _ = helper["synthetic_map"]()
(root / "input.json").write_text(prepared.bundle.model_dump_json(indent=2))
(root / "request.json").write_text(json.dumps({"scene_id": "grid"}))
PY
```

Generate the local dashboard and the MCP handoff in separate commands:

```bash
uv run --no-sync metes-review dashboard output/mapbox-manual/input.json \
  --output-dir output/mapbox-manual/dashboard \
  --online-map-config output/mapbox-manual/request.json
uv run --no-sync metes-review mapbox-mcp output/mapbox-manual/dashboard \
  --output-dir output/mapbox-manual/mcp
```

Both commands return exit **1** with `status: "needs_review"` for valid review artifacts; exit **2** means invalid input. Do not chain them with `&&`. For this fixture, expect dashboard `online_map_availability: "ready"` and MCP `availability: "partial"`, because the scan is omitted from the MCP view. Confirm that `mapbox-mcp-arguments.json` exists and read `mapbox-mcp-handoff.json` for omissions. Each output directory must be new; choose another `output/mapbox-manual` name throughout the recipe when repeating it.

**Test the interactive preview in Claude Code.** If the Mapbox MCP connection is not configured, follow Mapbox's [hosted setup guide](https://github.com/mapbox/mcp-server/blob/main/docs/hosted-mcp-guide.md):

```bash
claude mcp add --transport http mapbox-mcp-production https://mcp.mapbox.com/mcp
claude
```

Inside Claude, run `/mcp` and authenticate the Mapbox connection through its browser OAuth flow. From a session opened in this repository, use this prompt:

> Read `output/mapbox-manual/mcp/mapbox-mcp-arguments.json` and the adjacent handoff report. Inspect the connected `render_map_tool` schema. If compatible, pass the generated arguments unchanged as the final visualization tool call. Report any compatibility error instead of rewriting the payload, and disclose the omitted scan.

Expect the deed's four course segments, its POB marker, and parcel context over the basemap. Confirm that an interactive panel is actually visible and pans/zooms; a successful tool response alone does not establish client rendering. If the tool is unavailable, retain the generated files and record MCP/client acceptance as not run. See the [MCP handoff reference](../plugins/metesparser/skills/deed-closure-dashboard/references/mapbox-mcp.md) for the payload contract and size limit.

**Test the basemap, tax scan, and deed together locally.** Keep this server running in a terminal:

```bash
uv run --no-sync metes-review serve-map output/mapbox-manual/dashboard --port 8765
```

Open `http://localhost:8765/online-map.html`. Enter a public Mapbox `pk.` token in the masked runtime field and click **Connect**; keep the token out of chat, configuration files, and generated artifacts. Use a token permitted for that localhost origin. The page makes no provider requests before Connect. Stop the server with Ctrl+C when finished.

Check the following in the viewer:

- The basemap, orange synthetic scan with its green corner pixel, parcel polygon, and deed appear together with attribution.
- Layer toggles, scan opacity, and standard/satellite style switching work; overlays survive a style change.
- Selecting a course shows its details. Missing source-page images are identified explicitly; the synthetic scan is not a recorded deed page.
- Disconnect clears the token and provider map while the offline dashboard remains available.

For real evidence, replace the fixture with a bundle containing an evidenced projected placement and registered scan, and select its actual scene ID. Follow the [configuration and registration requirements](../plugins/metesparser/skills/deed-closure-dashboard/references/dashboard-bundle.md#optional-mapbox-companion); a visually plausible fit does not establish a boundary.

#### Automated browser checks

Prepare Chromium and explicitly download the pinned SDK into the ignored cache before running the browser gate:

```bash
uv sync --extra browser-test --extra web-map
uv run playwright install chromium
mkdir -p .uv-cache/mapbox/v3.33.0
curl --fail --location https://api.mapbox.com/mapbox-gl-js/v3.33.0/mapbox-gl.js --output .uv-cache/mapbox/v3.33.0/mapbox-gl.js
curl --fail --location https://api.mapbox.com/mapbox-gl-js/v3.33.0/mapbox-gl.css --output .uv-cache/mapbox/v3.33.0/mapbox-gl.css
make test-dashboard-browser
make test-mapbox-browser
```

The preflight verifies SDK bytes against [the provider descriptor](../packages/mp-export/src/mp_export/dashboard_assets/mapbox-sdk.json); tests do not fetch missing assets. The deterministic Mapbox target runs adapter tests and the actual SDK with local data and `testMode`; it does not establish live basemap rendering.

Run `make test-mapbox-live` separately with `MAPBOX_PUBLIC_TOKEN` (or `MAPBOX_ACCESS_TOKEN`) supplied through an existing secret environment facility. Restrict that public token to `http://localhost:8765`; `MAPBOX_PREVIEW_PORT` selects another explicit test port. The live gate uses synthetic evidence at a known land location and retains only map screenshots under ignored `output/playwright/mapbox-live/`. Missing credentials or browser prerequisites are failures, not skipped acceptance. Native plugin-host reachability still needs a separate host run.
