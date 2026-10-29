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

# Verify the root package (also formats its source and tests)
make check
```

`make dev-setup` already installs dependencies. API keys are needed for live PDF
extraction, not the mocked test suite. Run the additional package and browser
checks described in [Testing](TESTING.md) when those components change.

## Development Workflow

### 1. Create Feature Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/bug-description
```

### 2. Write Tests First (TDD)

```bash
# Write a failing test in the package that owns the behavior
uv run pytest packages/mp-verify/tests/ -v --no-cov

# Implement feature
# ...

# Verify test passes
uv run pytest packages/mp-verify/tests/ -v --no-cov
```

### 3. Run Quality Checks

```bash
# Before committing
make pre-commit
```

This runs:

- Lint auto-fix (ruff)
- Formatting (ruff)
- Root test suite (`tests/`, with coverage)

Use `make check` for the root quality gate, including mypy. Both targets modify
formatting; inspect the diff afterward. Package and plugin tests, package linting,
and explicit browser checks are separate; see [Testing](TESTING.md#running-tests).
`make ci` removes `.venv` and `dist` before reinstalling and running quality/coverage
checks; it does not run mypy or the separate package/browser lanes.

### 4. Commit Changes

```bash
git diff --check
git add path/to/changed-file.py path/to/test_changed_behavior.py
git diff --cached
git commit -m "feat: add new feature description"
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

- Aim for **> 90% coverage** on new features; the enforced root-suite floor is the configured 80% for `src/metesparser/` (see [Testing](TESTING.md)). Workspace package coverage is not included in that root threshold.
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
# Run root tests (package/plugin suites are separate)
make test

# Run specific category
uv run pytest tests/unit/ -v
uv run pytest tests/integration/ -v

# Run with coverage
make test-cov
```

Package and plugin suites are separate from these root commands. Use the focused commands in [Testing](TESTING.md#per-package-and-plugin-tests) for saved revisions, revision-bound corridors, delivery, raster picker, PLSS and skill materialization/navigation. The offline dashboard browser target checks local preview interactions; it does not establish Claude/Cowork conversation behavior or real-world deed placement. Native paired evaluations and live Mapbox rendering remain separately recorded gates.

## Core Principles

### 1. Never Fabricate Data

❌ **Don't**:
```python
if bearing is None:
    bearing = estimate_from_adjacent_calls()  # WRONG
```

✅ **Do**:
```python
from mp_models import DeedCall

call = DeedCall(
    course=1,
    direction_text="southwesterly",
    bearing_azimuth_deg_from_north=None,
    distance_ft=100.0,
    notes="incomplete bearing - cardinal only",
)
```

### 2. Preserve Determinism

Parsing, verification, and rendering must be reproducible from retained inputs.
LLM source extraction is not guaranteed to reproduce identical text, even at
temperature zero. Retain extraction evidence, mock provider calls in tests, and
keep numerical derivation in the deterministic packages. Native Claude document
reading belongs to the plugin workflow; it is separate from Python `mp-ocr`.

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

Maintain shared capability procedures under `plugins/metesparser/` and chat-specific dispatch, setup and download guidance under `plugins/metesparser-chat/`. The chat builder adapts shared procedures and keeps the engine unchanged. After changing shared instructions, rebuild both distributions with `make plugin-build` and `make chat-skill-build`, then check navigation in the extracted archives. After chat-only edits, rebuild the chat archive. Source chat templates intentionally link to shared resources added at build time. Use the [chat testing lane](TESTING.md#standalone-chat-distribution) for builder/setup changes, and record actual host acceptance separately from local checks.

### Adding a New Module

1. Choose the owning package using [Architecture](ARCHITECTURE.md#composable-package-architecture).
2. Add a failing behavior test in `packages/mp-<owner>/tests/`.
3. Implement in that package without introducing a dependency cycle.
4. For duplicated legacy APIs, keep `src/metesparser/` behavior in sync. For shared
   review functionality, use a thin compatibility facade rather than copying logic.
5. Test the public API and any affected cross-package/legacy entrypoints.
6. Update the owning documentation and changelog.

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

- [ ] Root checks pass (`make check`)
- [ ] Affected package/plugin checks pass (see [Testing](TESTING.md#per-package-and-plugin-tests))
- [ ] Cross-package imports verified (`uv run pytest tests/unit/test_cross_package_imports.py -v`)
- [ ] Formatting changes reviewed; affected package code linted/formatted separately
- [ ] Relevant browser checks passed; live/native acceptance reported separately
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
````markdown
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
````

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
- Unverified generated deed CSV outputs; intentionally synthetic test inputs remain separate fixtures

✅ **Always commit**:
- Source code
- Tests
- Documentation
- Sample data (non-sensitive)
- Configuration templates (`.env.example`)

## Getting Help

- **GitHub Issues** - Bug reports, feature requests
- **Discussions** - Questions, ideas
- **[AGENTS.md](../AGENTS.md)** - AI assistant guidance (`CLAUDE.md` is its symlink)
- **docs/** - Technical documentation

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

---

Thank you for contributing to metesParser! 🎉

### Online Map Viewer Changes

Keep online rendering in the [render-online-map capability](../plugins/metesparser/skills/render-online-map/SKILL.md) and follow the [online handoff contracts](../plugins/metesparser/references/artifact-handoffs.md#optional-online-map-handoff). Both standalone prepared plots/maps and existing dashboards use the shared preparation and rendering code. Validate token-free configuration against `WebMapRequest` and actual CLI flags. Check package/plugin tests, offline zero-network behavior, adapter interactions, and extracted optional distribution separately. Pinned real-SDK, live provider/WebGL visual composition, and native-host loopback acceptance require their own recorded runs; mocks and authored eval cases cannot satisfy those gates. Never retain real tokens in test traces, logs, artifacts, or screenshots.

#### Manual Mapbox smoke test

Run these commands from the repository root. This developer example reuses the [browser fixture](../packages/mp-export/tests/browser/conftest.py): a four-course rectangle, a parcel context polygon, and an asymmetric 8 × 8 PNG representing a registered tax scan at a known land location. All evidence and placement are synthetic; this does not test a real property's boundary alignment. The fixture imports pytest, so retain the default development dependencies.

```bash
uv sync --extra browser-test --extra web-map
uv run --no-sync python - <<'PY'
import json
import runpy
from pathlib import Path
from mp_models.plot_request import PlotCall, PlotRequest
from mp_models.webmap import StandaloneWebMapInput
from mp_verify.plot import prepare_plot

root = Path("output/mapbox-manual")
root.mkdir(parents=True, exist_ok=False)
helper = runpy.run_path("packages/mp-export/tests/browser/conftest.py")
prepared, _ = helper["synthetic_map"]()
bundle = prepared.bundle
spec = bundle.calculations[0]
plot = prepare_plot(PlotRequest(
    title="Synthetic boundary", calculation_id=spec.id,
    foot_definition=spec.frame.foot_definition,
    calls=tuple(PlotCall(
        id=c.id, call=c.call, quote=c.quote,
        source_reference="Synthetic browser fixture",
        page_id=c.page_id, occurrence_id=c.occurrence_id,
    ) for c in bundle.calls),
))
standalone = StandaloneWebMapInput(
    title="Synthetic standalone map", plots=(plot,), scenes=bundle.scenes,
    map_sources=bundle.map_sources, vector_layers=bundle.vector_layers,
    raster_layers=bundle.raster_layers,
    placements=tuple(p.model_copy(update={"geometry_hash": plot.geometry.geometry_hash})
                     for p in bundle.placements),
)
(root / "input.json").write_text(standalone.model_dump_json(indent=2))
(root / "request.json").write_text(json.dumps({"scene_id": "grid"}))
PY
```

Generate the standalone local map and the MCP handoff in separate commands:

```bash
uv run --no-sync metes-review render-map output/mapbox-manual/input.json \
  --output-dir output/mapbox-manual/map \
  --online-map-config output/mapbox-manual/request.json
uv run --no-sync metes-review mapbox-mcp output/mapbox-manual/map \
  --output-dir output/mapbox-manual/mcp
```

Both commands return exit **1** with `status: "needs_review"` for valid review artifacts; exit **2** means invalid input. Do not chain them with `&&`. For this fixture, expect local `online_map_availability: "ready"` and MCP `availability: "partial"`, because the scan is omitted from the MCP view. Confirm that `mapbox-mcp-arguments.json` exists and read `mapbox-mcp-handoff.json` for omissions. Each output directory must be new; choose another `output/mapbox-manual` name throughout the recipe when repeating it. The standalone output retains `map-evidence.html` with local plots and original scans; it creates no dashboard or source-review attestations. Existing dashboard bundles still support `dashboard --online-map-config` and the same MCP/preview commands.

**Test the interactive preview in Claude Code.** If the Mapbox MCP connection is not configured, follow Mapbox's [hosted setup guide](https://github.com/mapbox/mcp-server/blob/main/docs/hosted-mcp-guide.md):

```bash
claude mcp add --transport http mapbox-mcp-production https://mcp.mapbox.com/mcp
claude
```

Inside Claude, run `/mcp` and authenticate the Mapbox connection through its browser OAuth flow. From a session opened in this repository, use this prompt:

> Read `output/mapbox-manual/mcp/mapbox-mcp-arguments.json` and the adjacent handoff report. Discover the connected Mapbox rendering tool's exact fully qualified host identifier and inspect its live schema; do not call the bare upstream `render_map_tool` name or guess a server prefix. If compatible, pass the generated arguments unchanged to that identifier as the final visualization tool call. Report any compatibility error instead of rewriting the payload, and disclose the omitted scan.

Expect the deed's four course segments, its POB marker, and parcel context over the basemap. Confirm that an interactive panel is actually visible and pans/zooms; a successful tool response alone does not establish client rendering. If the tool is unavailable, retain the generated files and record MCP/client acceptance as not run. See the [MCP handoff reference](../plugins/metesparser/skills/render-online-map/references/mapbox-mcp.md) for the payload contract and size limit.

**Test the basemap, tax scan, and deed together locally.** Keep this server running in a terminal:

```bash
uv run --no-sync metes-review serve-map output/mapbox-manual/map --port 8765
```

Open `http://localhost:8765/online-map.html`. Enter a public Mapbox `pk.` token in the masked runtime field and click **Connect**; keep the token out of chat, configuration files, and generated artifacts. Use a token permitted for that localhost origin. The page makes no provider requests before Connect. Stop the server with Ctrl+C when finished.

Check the following in the viewer:

- The basemap, orange synthetic scan with its green corner pixel, parcel polygon, and deed appear together with attribution.
- Layer toggles, scan opacity, and standard/satellite style switching work; overlays survive a style change.
- Selecting a course shows its details. Missing source-page images are identified explicitly; the synthetic scan is not a recorded deed page.
- Disconnect clears the token and provider map while the offline map evidence remains available.

For real evidence, compose existing plot and overlay artifacts with a supplied projected placement and registered scan, and select the actual scene ID. Follow the [composition, configuration and placement requirements](../plugins/metesparser/skills/render-online-map/references/local-viewer.md); a visually plausible fit does not establish a boundary.

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
