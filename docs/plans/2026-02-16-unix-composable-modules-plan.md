# Unix Composable Modules Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refactor metesParser v0.4.0 into 7 independently installable packages in a uv workspace monorepo with JSONL interchange.

**Architecture:** Bottom-up build order following the dependency tree: mp-models (zero deps) → mp-bearing (depends on mp-models) → mp-ocr, mp-parse, mp-verify, mp-export (mid-tier) → metesparser orchestrator (depends on all). Each package gets its own pyproject.toml, src/ layout, and tests/.

**Tech Stack:** Python 3.11+, uv workspaces, pydantic v2, structlog, hatchling, ruff, mypy, pytest

---

## Phase 1: Monorepo Scaffold + mp-models

### Task 1: Initialize uv workspace and package skeleton

**Files:**
- Create: `packages/mp-models/pyproject.toml`
- Create: `packages/mp-models/src/mp_models/__init__.py`
- Create: `packages/mp-models/src/mp_models/py.typed`
- Modify: `pyproject.toml` (root — add workspace config)

**Step 1: Create root workspace config**

Add `[tool.uv.workspace]` to root `pyproject.toml`:

```toml
[tool.uv.workspace]
members = ["packages/*"]
```

Keep the existing `[project]` section intact — it still defines the top-level metesparser package during migration.

**Step 2: Create mp-models package scaffold**

```toml
# packages/mp-models/pyproject.toml
[project]
name = "mp-models"
version = "1.0.0"
requires-python = ">=3.11"
description = "Pydantic schemas for metes and bounds deed parsing"
dependencies = [
    "pydantic>=2.10.0",
    "structlog>=24.4.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3.0",
    "pytest-cov>=6.0.0",
    "ruff>=0.8.0",
    "mypy>=1.13.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/mp_models"]
```

```python
# packages/mp-models/src/mp_models/__init__.py
"""Pydantic schemas for metes and bounds deed parsing."""

__version__ = "1.0.0"
```

Create empty `py.typed` marker file.

**Step 3: Verify workspace resolves**

Run: `uv sync --all-extras --dev`
Expected: resolves both root and mp-models packages

**Step 4: Commit**

```bash
git add packages/mp-models/ pyproject.toml
git commit -m "chore: initialize uv workspace with mp-models package skeleton"
```

---

### Task 2: Extract core domain models into mp-models

**Files:**
- Create: `packages/mp-models/src/mp_models/base.py`
- Create: `packages/mp-models/src/mp_models/deed_call.py`
- Create: `packages/mp-models/src/mp_models/legal_description.py`
- Create: `packages/mp-models/src/mp_models/closure.py`
- Create: `packages/mp-models/src/mp_models/constants.py`
- Create: `packages/mp-models/src/mp_models/units.py`
- Create: `packages/mp-models/tests/test_models.py`
- Modify: `packages/mp-models/src/mp_models/__init__.py`

**Step 1: Write the failing test**

```python
# packages/mp-models/tests/test_models.py
"""Verify core models are importable from mp_models."""

def test_deed_call_importable():
    from mp_models import DeedCall
    call = DeedCall(course=1, direction_text="North 45 degrees East", distance_ft=100.0)
    assert call.course == 1
    assert call.distance_ft == 100.0

def test_legal_description_importable():
    from mp_models import LegalDescription
    ld = LegalDescription()
    assert ld.calls == []

def test_closure_result_importable():
    from mp_models import ClosureResult
    cr = ClosureResult(
        misclosure_x_ft=0.001, misclosure_y_ft=0.002, misclosure_ft=0.003,
        area_sq_ft=7500.0, area_acres=0.172, perimeter_ft=350.0,
        closure_passed=True, angle_check_passed=True, curve_consistency_passed=True,
    )
    assert cr.is_fully_verified()

def test_point_importable():
    from mp_models import Point
    p = Point(x=1.0, y=2.0)
    assert str(p) == "(1.00, 2.00)"

def test_conversion_factors():
    from mp_models import ConversionFactors
    assert ConversionFactors.convert_to_feet(1.0, "chains") == 66.0

def test_audit_context_importable():
    from mp_models import AuditContext, RunMetadata
    from datetime import UTC, datetime
    rm = RunMetadata(
        parser_version="1.0.0", llm_provider="openai", llm_model="gpt-5",
        prompt_hash="abc123", timestamp_utc=datetime.now(UTC),
        source_pdf="deed.pdf", cache_enabled=True,
    )
    ctx = AuditContext(run_metadata=rm)
    assert ctx.call_audits == []

def test_bool_coercion():
    from mp_models import DeedCall
    call = DeedCall(course=1, direction_text="North", distance_ft=100.0, is_exception="true")
    assert call.is_exception is True

def test_frozen_model():
    import pytest
    from mp_models import DeedCall
    call = DeedCall(course=1, direction_text="North", distance_ft=100.0)
    with pytest.raises(Exception):
        call.course = 2  # type: ignore[misc]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest packages/mp-models/tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mp_models'` or import errors

**Step 3: Extract models**

Copy the classes from `src/metesparser/models.py` into the mp-models subpackage files:

- `base.py`: `_Model` class (lines 85-118 of models.py)
- `deed_call.py`: `CurveDirection`, `MonumentType`, `MonumentStatus`, `CurveType`, `DeedClause`, `SubdivisionReference`, `DeedCall` (lines 16-344)
- `legal_description.py`: `LegalDescription` (lines 356-461)
- `closure.py`: `ClosureResult`, `Point`, `CheckResult` (lines 346-354, 464-539, 628-636)
- `constants.py`: `PERMANENT_MONUMENTS`, `PRIOR_CONVEYANCE_SIGNALS` (lines 39-61)
- `units.py`: `DistanceUnit`, `ConversionFactors` (lines 64-589)
- `audit.py` (already listed in design): `Transformation`, `Decision`, `CallAudit`, `RunMetadata`, `ExtractionRecord`, `VerificationAudit`, `AuditContext` (lines 597-688)

Update `__init__.py` to re-export all public names:

```python
# packages/mp-models/src/mp_models/__init__.py
"""Pydantic schemas for metes and bounds deed parsing."""

from .audit import (
    AuditContext,
    CallAudit,
    Decision,
    ExtractionRecord,
    RunMetadata,
    Transformation,
    VerificationAudit,
)
from .base import _Model
from .closure import CheckResult, ClosureResult, Point
from .constants import PERMANENT_MONUMENTS, PRIOR_CONVEYANCE_SIGNALS
from .deed_call import (
    CurveDirection,
    CurveType,
    DeedCall,
    DeedClause,
    MonumentStatus,
    MonumentType,
    SubdivisionReference,
)
from .legal_description import LegalDescription
from .units import ConversionFactors, DistanceUnit

__version__ = "1.0.0"

__all__ = [
    "AuditContext",
    "CallAudit",
    "CheckResult",
    "ClosureResult",
    "ConversionFactors",
    "CurveDirection",
    "CurveType",
    "Decision",
    "DeedCall",
    "DeedClause",
    "DistanceUnit",
    "ExtractionRecord",
    "LegalDescription",
    "MonumentStatus",
    "MonumentType",
    "PERMANENT_MONUMENTS",
    "PRIOR_CONVEYANCE_SIGNALS",
    "Point",
    "RunMetadata",
    "SubdivisionReference",
    "Transformation",
    "VerificationAudit",
    "_Model",
]
```

Key details when splitting:
- `base.py` imports: just pydantic
- `deed_call.py` imports: `from .base import _Model` plus pydantic types
- `legal_description.py` imports: `from .base import _Model`, `from .deed_call import DeedCall, DeedClause, SubdivisionReference`, `from .units import DistanceUnit`
- `closure.py` imports: `from .base import _Model` plus pydantic types
- `audit.py`: `AuditContext` extends `BaseModel` directly (NOT `_Model`), all others extend `_Model`

**Step 4: Run test to verify it passes**

Run: `uv run pytest packages/mp-models/tests/test_models.py -v`
Expected: all 8 tests PASS

**Step 5: Commit**

```bash
git add packages/mp-models/
git commit -m "feat(mp-models): extract core domain models from monolith"
```

---

### Task 3: Extract logging config into mp-models

**Files:**
- Create: `packages/mp-models/src/mp_models/logging.py`
- Create: `packages/mp-models/tests/test_logging.py`
- Modify: `packages/mp-models/src/mp_models/__init__.py`

**Step 1: Write the failing test**

```python
# packages/mp-models/tests/test_logging.py
"""Verify logging config is importable from mp_models."""
import io

def test_configure_logging_importable():
    from mp_models.logging import configure_logging, get_log_format
    buf = io.StringIO()
    configure_logging(level="WARNING", log_format="console", stream=buf)
    assert get_log_format() == "console"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest packages/mp-models/tests/test_logging.py -v`
Expected: FAIL — import error

**Step 3: Copy logging_config.py**

Copy `src/metesparser/logging_config.py` to `packages/mp-models/src/mp_models/logging.py`. No internal import changes needed — it only depends on stdlib + structlog.

**Step 4: Run test to verify it passes**

Run: `uv run pytest packages/mp-models/tests/test_logging.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add packages/mp-models/
git commit -m "feat(mp-models): extract shared logging config"
```

---

### Task 4: Add JSONL envelope to mp-models

**Files:**
- Create: `packages/mp-models/src/mp_models/envelope.py`
- Create: `packages/mp-models/tests/test_envelope.py`
- Modify: `packages/mp-models/src/mp_models/__init__.py`

**Step 1: Write the failing test**

```python
# packages/mp-models/tests/test_envelope.py
"""Verify JSONL envelope read/write."""
import io
import json

def test_write_and_read_raw_text():
    from mp_models.envelope import RawTextMessage, read_jsonl, write_jsonl
    msg = RawTextMessage(
        source="deed.pdf",
        text="BEGINNING at an iron pin",
        llm_provider="openai",
        llm_model="gpt-5",
    )
    buf = io.StringIO()
    write_jsonl(buf, msg)
    buf.seek(0)
    messages = list(read_jsonl(buf))
    assert len(messages) == 1
    assert messages[0].type == "raw_text"
    assert messages[0].source == "deed.pdf"

def test_discriminated_union_parsing():
    from mp_models.envelope import parse_message
    line = json.dumps({"type": "raw_text", "source": "test.pdf", "text": "hello", "llm_provider": "openai", "llm_model": "gpt-5"})
    msg = parse_message(line)
    assert msg.type == "raw_text"

def test_passthrough_fields():
    from mp_models.envelope import RawTextMessage
    msg = RawTextMessage(
        source="deed.pdf", text="hello",
        llm_provider="openai", llm_model="gpt-5",
        extracted_at="2026-02-16T14:30:00Z",
    )
    assert msg.llm_provider == "openai"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest packages/mp-models/tests/test_envelope.py -v`
Expected: FAIL — import error

**Step 3: Implement envelope module**

```python
# packages/mp-models/src/mp_models/envelope.py
"""JSONL message types and read/write helpers."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Iterator, Literal, TextIO, Union

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag


class _Message(BaseModel):
    """Base for all JSONL messages."""
    model_config = ConfigDict(extra="allow", frozen=True)
    source: str = Field(..., description="Source PDF filename")


class RawTextMessage(_Message):
    """Output of mp-ocr: raw legal text extracted from PDF via LLM."""
    type: Literal["raw_text"] = "raw_text"
    text: str = Field(..., description="Extracted legal text")
    llm_provider: str = Field(..., description="LLM provider name")
    llm_model: str = Field(..., description="LLM model identifier")
    extracted_at: str | None = Field(default=None, description="ISO timestamp of extraction")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    cache_hit: bool | None = Field(default=None)


class LegalDescriptionMessage(_Message):
    """Output of mp-parse: structured calls + metadata."""
    type: Literal["legal_description"] = "legal_description"
    calls: list[dict[str, object]] = Field(default_factory=list)
    plss: dict[str, str | None] | None = Field(default=None)
    pob: str | None = Field(default=None)
    area_statement: str | None = Field(default=None)
    llm_provider: str | None = Field(default=None)
    llm_model: str | None = Field(default=None)
    extracted_at: str | None = Field(default=None)


class ClosureResultMessage(_Message):
    """Output of mp-verify: verification results with closure data."""
    type: Literal["closure_result"] = "closure_result"
    is_verified: bool = Field(...)
    misclosure_ft: float = Field(...)
    precision_ratio: str | None = Field(default=None)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    area_sq_ft: float | None = Field(default=None)
    checks: list[dict[str, object]] = Field(default_factory=list)
    calls: list[dict[str, object]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    llm_provider: str | None = Field(default=None)
    llm_model: str | None = Field(default=None)
    extracted_at: str | None = Field(default=None)


MessageType = Annotated[
    Union[
        Annotated[RawTextMessage, Tag("raw_text")],
        Annotated[LegalDescriptionMessage, Tag("legal_description")],
        Annotated[ClosureResultMessage, Tag("closure_result")],
    ],
    Discriminator("type"),
]


def parse_message(line: str) -> MessageType:
    """Parse a single JSONL line into a typed message."""
    from pydantic import TypeAdapter
    adapter = TypeAdapter(MessageType)
    return adapter.validate_json(line)


def read_jsonl(stream: TextIO) -> Iterator[MessageType]:
    """Read JSONL from a stream, yield typed message objects."""
    for line in stream:
        stripped = line.strip()
        if not stripped:
            continue
        yield parse_message(stripped)


def write_jsonl(stream: TextIO, message: RawTextMessage | LegalDescriptionMessage | ClosureResultMessage) -> None:
    """Write one JSONL line to a stream."""
    stream.write(message.model_dump_json())
    stream.write("\n")
```

Add to `__init__.py`:

```python
from .envelope import (
    ClosureResultMessage,
    LegalDescriptionMessage,
    MessageType,
    RawTextMessage,
    parse_message,
    read_jsonl,
    write_jsonl,
)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest packages/mp-models/tests/test_envelope.py -v`
Expected: all 3 tests PASS

**Step 5: Commit**

```bash
git add packages/mp-models/
git commit -m "feat(mp-models): add JSONL envelope types and read/write helpers"
```

---

## Phase 2: mp-bearing

### Task 5: Create mp-bearing package with azimuth module

**Files:**
- Create: `packages/mp-bearing/pyproject.toml`
- Create: `packages/mp-bearing/src/mp_bearing/__init__.py`
- Create: `packages/mp-bearing/src/mp_bearing/azimuth.py`
- Create: `packages/mp-bearing/tests/test_azimuth.py`

**Step 1: Write the failing test**

```python
# packages/mp-bearing/tests/test_azimuth.py
"""Verify azimuth conversions."""

def test_quadrant_to_azimuth_ne():
    from mp_bearing import quadrant_to_azimuth
    assert quadrant_to_azimuth("N", 45.0, "E") == 45.0

def test_quadrant_to_azimuth_sw():
    from mp_bearing import quadrant_to_azimuth
    assert quadrant_to_azimuth("S", 45.0, "W") == 225.0

def test_parse_quadrant_bearing():
    from mp_bearing import parse_quadrant_bearing
    result = parse_quadrant_bearing("S 56°40' W")
    assert result is not None
    assert result[0] == "S"

def test_bearing_to_azimuth():
    from mp_bearing import bearing_to_azimuth
    az = bearing_to_azimuth("N 45°00' E")
    assert az is not None
    assert abs(az - 45.0) < 0.01

def test_azimuth_to_quadrant():
    from mp_bearing import azimuth_to_quadrant
    result = azimuth_to_quadrant(225.0)
    assert result.startswith("S")
    assert "W" in result

def test_parse_packed_dms():
    from mp_bearing import parse_packed_dms
    result = parse_packed_dms(46.1631)
    assert abs(result - 46.2753) < 0.001

def test_compass_point_to_azimuth():
    from mp_bearing import compass_point_to_azimuth
    assert compass_point_to_azimuth("northeast") == 45.0
    assert compass_point_to_azimuth("south") == 180.0
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest packages/mp-bearing/tests/test_azimuth.py -v`
Expected: FAIL — import errors

**Step 3: Create package and extract azimuth code**

Create `packages/mp-bearing/pyproject.toml`:

```toml
[project]
name = "mp-bearing"
version = "1.0.0"
requires-python = ">=3.11"
description = "Bearing conversion and curve math for metes and bounds parsing"
dependencies = ["mp-models>=1.0.0"]

[project.optional-dependencies]
dev = ["pytest>=8.3.0", "ruff>=0.8.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/mp_bearing"]
```

Extract from `bearing_converter.py` into `packages/mp-bearing/src/mp_bearing/azimuth.py`:
- `QUADRANT_PATTERN` regex
- `COMPASS_POINTS` dict
- `compass_point_to_azimuth()`
- `parse_packed_dms()`
- `degree_of_curvature_to_radius()`
- `parse_quadrant_bearing()`
- `quadrant_to_azimuth()`
- `bearing_to_azimuth()`
- `azimuth_to_quadrant()`

These are all static/classmethod functions — extract them as module-level functions (no class needed).

Update `__init__.py` to re-export.

**Step 4: Run test to verify it passes**

Run: `uv run pytest packages/mp-bearing/tests/test_azimuth.py -v`
Expected: all 7 tests PASS

**Step 5: Commit**

```bash
git add packages/mp-bearing/
git commit -m "feat(mp-bearing): extract azimuth conversion module"
```

---

### Task 6: Add curves and deltas modules to mp-bearing

**Files:**
- Create: `packages/mp-bearing/src/mp_bearing/curves.py`
- Create: `packages/mp-bearing/src/mp_bearing/deltas.py`
- Create: `packages/mp-bearing/tests/test_curves.py`
- Create: `packages/mp-bearing/tests/test_deltas.py`
- Modify: `packages/mp-bearing/src/mp_bearing/__init__.py`

**Step 1: Write the failing tests**

```python
# packages/mp-bearing/tests/test_curves.py
import math

def test_curve_properties_from_delta():
    from mp_bearing import calculate_curve_properties
    result = calculate_curve_properties(100.0, delta_deg=30.0)
    assert abs(result["arc_length_ft"] - 100.0 * math.radians(30.0)) < 0.01

def test_curve_properties_from_arc():
    from mp_bearing import calculate_curve_properties
    result = calculate_curve_properties(100.0, arc_length_ft=52.36)
    assert result["delta_deg"] is not None
    assert result["chord_length_ft"] is not None

def test_missing_curve_elements():
    from mp_bearing import calculate_missing_curve_elements
    result = calculate_missing_curve_elements(radius_ft=100.0, delta_deg=30.0)
    assert "arc_length_ft" in result
    assert "chord_length_ft" in result

def test_chord_bearing():
    from mp_bearing import calculate_chord_bearing
    chord_az = calculate_chord_bearing(90.0, 30.0, "right")
    assert abs(chord_az - 105.0) < 0.01
```

```python
# packages/mp-bearing/tests/test_deltas.py
import math

def test_calculate_deltas():
    from mp_bearing import calculate_deltas
    dx, dy = calculate_deltas(90.0, 100.0)
    assert abs(dx - 100.0) < 0.01
    assert abs(dy) < 0.01

def test_calculate_deltas_north():
    from mp_bearing import calculate_deltas
    dx, dy = calculate_deltas(0.0, 100.0)
    assert abs(dx) < 0.01
    assert abs(dy - 100.0) < 0.01
```

**Step 2: Run test to verify they fail**

Run: `uv run pytest packages/mp-bearing/tests/test_curves.py packages/mp-bearing/tests/test_deltas.py -v`
Expected: FAIL — import errors

**Step 3: Extract curves and deltas**

Extract from `bearing_converter.py`:
- `curves.py`: `calculate_curve_properties()`, `calculate_chord_bearing()`, `compute_curve_endpoint()`, `calculate_missing_curve_elements()` — these use `math` and `mp_models.Point`, no other internal deps
- `deltas.py`: `calculate_deltas()` — just `math`, no internal deps

Also extract `enrich_call_with_azimuth()` into `azimuth.py` (it uses `mp_models.DeedCall` and `bearing_to_azimuth`).

Update `__init__.py` to re-export all public functions.

**Step 4: Run test to verify they pass**

Run: `uv run pytest packages/mp-bearing/tests/ -v`
Expected: all tests PASS

**Step 5: Commit**

```bash
git add packages/mp-bearing/
git commit -m "feat(mp-bearing): add curves and deltas modules"
```

---

## Phase 3: mp-ocr

### Task 7: Create mp-ocr package with LLM clients

**Files:**
- Create: `packages/mp-ocr/pyproject.toml`
- Create: `packages/mp-ocr/src/mp_ocr/__init__.py`
- Create: `packages/mp-ocr/src/mp_ocr/clients.py`
- Create: `packages/mp-ocr/src/mp_ocr/cache.py`
- Create: `packages/mp-ocr/tests/test_clients.py`

**Step 1: Write the failing test**

```python
# packages/mp-ocr/tests/test_clients.py
"""Verify LLM client protocol and cache are importable."""

def test_base_client_protocol():
    from mp_ocr import BaseLLMClient
    assert hasattr(BaseLLMClient, "generate_text")

def test_llm_client_error():
    from mp_ocr import LLMClientError
    assert issubclass(LLMClientError, RuntimeError)

def test_cached_client_importable():
    from mp_ocr import CachedLLMClient
    assert CachedLLMClient is not None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest packages/mp-ocr/tests/test_clients.py -v`
Expected: FAIL

**Step 3: Create package and extract clients**

Create `packages/mp-ocr/pyproject.toml`:

```toml
[project]
name = "mp-ocr"
version = "1.0.0"
requires-python = ">=3.11"
description = "LLM-based OCR extraction for deed PDFs"
dependencies = [
    "mp-models>=1.0.0",
    "openai>=2.3.0",
    "pypdf>=6.1.1",
    "pyyaml>=6.0.2",
    "structlog>=24.4.0",
]

[project.optional-dependencies]
gemini = ["google-genai>=0.3.0"]
dev = ["pytest>=8.3.0", "ruff>=0.8.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/mp_ocr"]

[tool.hatch.build.targets.wheel.force-include]
"src/mp_ocr/prompts" = "mp_ocr/prompts"
```

Copy `llm_clients.py` → `packages/mp-ocr/src/mp_ocr/clients.py` (no internal import changes — all stdlib/third-party).

Copy `llm_cache.py` → `packages/mp-ocr/src/mp_ocr/cache.py`. Update import:
```python
# Change: from .llm_clients import BaseLLMClient, _read_pdf
# To:     from .clients import BaseLLMClient, _read_pdf
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest packages/mp-ocr/tests/test_clients.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add packages/mp-ocr/
git commit -m "feat(mp-ocr): extract LLM clients and cache module"
```

---

### Task 8: Extract PDF processor and prompts into mp-ocr

**Files:**
- Create: `packages/mp-ocr/src/mp_ocr/extract.py`
- Copy: `src/metesparser/prompts/*.yaml` → `packages/mp-ocr/src/mp_ocr/prompts/`
- Create: `packages/mp-ocr/tests/test_extract.py`
- Modify: `packages/mp-ocr/src/mp_ocr/__init__.py`

**Step 1: Write the failing test**

```python
# packages/mp-ocr/tests/test_extract.py
"""Verify PDF processor extraction logic."""
import re

def test_compute_llm_confidence_high():
    from mp_ocr.extract import compute_llm_confidence
    text = (
        "BEGINNING at an iron pin found in the Southerly line of Elm Street; "
        "thence South 56 degrees 40 minutes East, a distance of 150.00 feet; "
        "thence North 33 degrees 20 minutes East, 125.00 feet; "
        "thence North 56 degrees 40 minutes West, 150.00 feet; "
        "to the POINT OF BEGINNING. "
        "Section 12, Township 3N, Range 2W. "
        "CONTAINING 0.43 acres more or less."
    )
    confidence, signals = compute_llm_confidence(text)
    assert confidence > 0.7
    assert signals["has_pob"] is True
    assert signals["has_bearing_calls"] is True

def test_compute_llm_confidence_low():
    from mp_ocr.extract import compute_llm_confidence
    confidence, signals = compute_llm_confidence("This is not a legal description at all.")
    assert confidence < 0.3
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest packages/mp-ocr/tests/test_extract.py -v`
Expected: FAIL

**Step 3: Extract PDFProcessor**

Copy `pdf_processor.py` → `packages/mp-ocr/src/mp_ocr/extract.py`. Key changes:
- Update imports to use `mp_models` and local `.clients`/`.cache`
- Extract `_compute_llm_confidence()` as a module-level function `compute_llm_confidence()`
- Copy prompt YAML files to `packages/mp-ocr/src/mp_ocr/prompts/`
- Update `prompts_dir` path resolution

Update `__init__.py`:

```python
from .cache import CachedLLMClient
from .clients import BaseLLMClient, GeminiClient, LLMClientError, OpenAIClient
from .extract import PDFProcessor, compute_llm_confidence
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest packages/mp-ocr/tests/ -v`
Expected: PASS

**Step 5: Commit**

```bash
git add packages/mp-ocr/
git commit -m "feat(mp-ocr): extract PDF processor with prompts and confidence scoring"
```

---

## Phase 4: mp-parse

### Task 9: Create mp-parse with numbers utility module

**Files:**
- Create: `packages/mp-parse/pyproject.toml`
- Create: `packages/mp-parse/src/mp_parse/__init__.py`
- Create: `packages/mp-parse/src/mp_parse/numbers.py`
- Create: `packages/mp-parse/tests/test_numbers.py`

**Step 1: Write the failing test**

```python
# packages/mp-parse/tests/test_numbers.py
def test_parse_comma_number():
    from mp_parse.numbers import parse_comma_number
    assert parse_comma_number("1,200.50") == 1200.50
    assert parse_comma_number("100") == 100.0

def test_comma_number_pattern():
    import re
    from mp_parse.numbers import COMMA_NUMBER
    pattern = re.compile(COMMA_NUMBER)
    assert pattern.match("1,200.50")
    assert pattern.match("100")
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest packages/mp-parse/tests/test_numbers.py -v`
Expected: FAIL

**Step 3: Create package and numbers module**

```toml
# packages/mp-parse/pyproject.toml
[project]
name = "mp-parse"
version = "1.0.0"
requires-python = ">=3.11"
description = "Rule-based parsing for metes and bounds legal descriptions"
dependencies = [
    "mp-models>=1.0.0",
    "mp-bearing>=1.0.0",
    "structlog>=24.4.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.3.0", "ruff>=0.8.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/mp_parse"]
```

```python
# packages/mp-parse/src/mp_parse/numbers.py
"""Shared numeric parsing utilities."""

COMMA_NUMBER = r"\d[\d,]*(?:\.\d+)?"

def parse_comma_number(s: str) -> float:
    """Parse a number string with optional commas. '1,200.50' -> 1200.5"""
    return float(s.replace(",", ""))
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest packages/mp-parse/tests/test_numbers.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add packages/mp-parse/
git commit -m "feat(mp-parse): create package with shared number parsing utility"
```

---

### Task 10: Extract text normalizer and metadata into mp-parse

**Files:**
- Create: `packages/mp-parse/src/mp_parse/normalizer.py`
- Create: `packages/mp-parse/src/mp_parse/metadata.py`
- Create: `packages/mp-parse/tests/test_normalizer.py`
- Create: `packages/mp-parse/tests/test_metadata.py`

**Step 1: Write the failing tests**

```python
# packages/mp-parse/tests/test_normalizer.py
def test_expand_abbreviations():
    from mp_parse.normalizer import expand_abbreviations
    text = "to an IPF in the line of N/F Smith"
    result = expand_abbreviations(text)
    assert "Iron Pin Found" in result
    assert "now or formerly" in result
```

```python
# packages/mp-parse/tests/test_metadata.py
def test_extract_plss_metadata():
    from mp_parse.metadata import extract_plss_metadata
    text = "the NW 1/4 of Section 12, Township 3 North, Range 2 West of the Willamette Meridian"
    result = extract_plss_metadata(text)
    assert result["section"] == "12"

def test_extract_poc_and_pob():
    from mp_parse.metadata import extract_poc_and_pob
    text = "COMMENCING at an iron pin; thence North 100 feet to the POINT OF BEGINNING"
    poc, pob = extract_poc_and_pob(text)
    assert poc is not None
    assert pob is not None
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/mp-parse/tests/test_normalizer.py packages/mp-parse/tests/test_metadata.py -v`
Expected: FAIL

**Step 3: Extract from text_parser.py**

Split `text_parser.py` (959 lines) into:

- `normalizer.py`: `normalize_dms_symbols()`, `merge_line_wrapped_calls()`, `standardize_cardinal_directions()`, `clean_ocr_errors()`, `expand_abbreviations()`, `normalize_legal_description()` (if it's just text cleanup)
- `metadata.py`: `extract_plss_metadata()`, `extract_poc_and_pob()`, `extract_area_statement()`, `extract_basis_of_bearing()`, `extract_surveyor_certification()`, `extract_prior_conveyance()`, `extract_deed_clauses()`, `extract_subdivision_reference()`, `extract_witness_trees()`, `extract_coordinate_system()`, `infer_distance_unit()`, `is_indefinite_call()`, `detect_meander()`, `is_closure_to_pob()`, `split_into_calls()`, `extract_distance()`, `split_exception_clauses()`

These are all static/classmethod functions — extract as module-level functions.

Update imports in each to use `mp_models` instead of `.models`.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/mp-parse/tests/ -v`
Expected: PASS

**Step 5: Commit**

```bash
git add packages/mp-parse/
git commit -m "feat(mp-parse): extract text normalizer and metadata extraction"
```

---

### Task 11: Extract call extractor and monument classifier into mp-parse

**Files:**
- Create: `packages/mp-parse/src/mp_parse/calls.py`
- Create: `packages/mp-parse/src/mp_parse/monuments.py`
- Create: `packages/mp-parse/tests/test_calls.py`
- Create: `packages/mp-parse/tests/test_monuments.py`
- Modify: `packages/mp-parse/src/mp_parse/__init__.py`

**Step 1: Write the failing tests**

```python
# packages/mp-parse/tests/test_monuments.py
def test_classify_monument_iron_pin():
    from mp_parse.monuments import classify_monument
    result = classify_monument("an iron pin found")
    assert result == "iron_pin"

def test_classify_monument_status_found():
    from mp_parse.monuments import classify_monument_status
    assert classify_monument_status("iron pin found") == "found"

def test_classify_monument_status_set():
    from mp_parse.monuments import classify_monument_status
    assert classify_monument_status("iron pin set") == "set"
```

```python
# packages/mp-parse/tests/test_calls.py
def test_extract_calls_basic():
    from mp_parse.calls import extract_calls
    text = (
        "BEGINNING at an iron pin; thence South 56 degrees 40 minutes West, "
        "150.00 feet to an iron pin; thence North 33 degrees 20 minutes West, "
        "125.00 feet to an iron pin; thence North 56 degrees 40 minutes East, "
        "150.00 feet to an iron pin; thence South 33 degrees 20 minutes East, "
        "125.00 feet to the POINT OF BEGINNING."
    )
    calls = extract_calls(text)
    assert len(calls) >= 4
    assert calls[0].course == 1
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/mp-parse/tests/test_monuments.py packages/mp-parse/tests/test_calls.py -v`
Expected: FAIL

**Step 3: Extract from call_extractor.py**

Split `call_extractor.py` (907 lines) into:

- `monuments.py`: `MonumentClassifier` class (classify_monument, classify_monument_status)
- `calls.py`: `CallExtractor` class methods → module-level functions: `extract_calls()`, `extract_curve_info()`, `mark_tie_in_calls()`, `enrich_calls_with_azimuths()` (which delegates to `mp_bearing`)

Key import changes:
- `from mp_bearing import bearing_to_azimuth, enrich_call_with_azimuth` (instead of `from .bearing_converter`)
- `from mp_models import DeedCall, CallAudit, ...` (instead of `from .models`)
- `from .numbers import COMMA_NUMBER, parse_comma_number` (instead of `from .text_parser`)
- `from .normalizer import ...` and `from .metadata import ...` (instead of `from .text_parser`)

**Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/mp-parse/tests/ -v`
Expected: PASS

**Step 5: Commit**

```bash
git add packages/mp-parse/
git commit -m "feat(mp-parse): extract call extractor and monument classifier"
```

---

## Phase 5: mp-verify

### Task 12: Create mp-verify with closure and checks

**Files:**
- Create: `packages/mp-verify/pyproject.toml`
- Create: `packages/mp-verify/src/mp_verify/__init__.py`
- Create: `packages/mp-verify/src/mp_verify/closure.py`
- Create: `packages/mp-verify/src/mp_verify/checks.py`
- Create: `packages/mp-verify/src/mp_verify/confidence.py`
- Create: `packages/mp-verify/tests/test_closure.py`
- Create: `packages/mp-verify/tests/test_checks.py`

**Step 1: Write the failing tests**

```python
# packages/mp-verify/tests/test_closure.py
def test_verify_closure_square():
    """A perfect 100ft square should close with near-zero misclosure."""
    from mp_models import DeedCall
    from mp_verify import verify_closure

    calls = [
        DeedCall(course=1, direction_text="North", bearing_quadrant="N 00°00' E",
                 bearing_azimuth_deg_from_north=0.0, distance_ft=100.0),
        DeedCall(course=2, direction_text="East", bearing_quadrant="N 90°00' E",
                 bearing_azimuth_deg_from_north=90.0, distance_ft=100.0),
        DeedCall(course=3, direction_text="South", bearing_quadrant="S 00°00' E",
                 bearing_azimuth_deg_from_north=180.0, distance_ft=100.0),
        DeedCall(course=4, direction_text="West", bearing_quadrant="N 90°00' W",
                 bearing_azimuth_deg_from_north=270.0, distance_ft=100.0),
    ]
    result = verify_closure(calls)
    assert result.closure_passed
    assert result.misclosure_ft < 0.01
    assert abs(result.area_sq_ft - 10000.0) < 1.0
```

```python
# packages/mp-verify/tests/test_checks.py
def test_confidence_scoring():
    from mp_models import DeedCall, ClosureResult
    from mp_verify.confidence import calculate_confidence_score

    result = ClosureResult(
        misclosure_x_ft=0.001, misclosure_y_ft=0.001, misclosure_ft=0.002,
        area_sq_ft=10000.0, area_acres=0.23, perimeter_ft=400.0,
        closure_passed=True, angle_check_passed=True, curve_consistency_passed=True,
    )
    calls = [
        DeedCall(course=i, direction_text="North", bearing_quadrant="N 00°00' E",
                 bearing_azimuth_deg_from_north=0.0, distance_ft=100.0)
        for i in range(1, 5)
    ]
    score = calculate_confidence_score(result, calls)
    assert 0.0 <= score <= 1.0
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/mp-verify/tests/ -v`
Expected: FAIL

**Step 3: Create package and extract from closure_checker.py**

```toml
# packages/mp-verify/pyproject.toml
[project]
name = "mp-verify"
version = "1.0.0"
requires-python = ">=3.11"
description = "Geometric verification for metes and bounds traverses"
dependencies = [
    "mp-models>=1.0.0",
    "mp-bearing>=1.0.0",
    "structlog>=24.4.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.3.0", "ruff>=0.8.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/mp_verify"]
```

Split `closure_checker.py` (804 lines) into:
- `closure.py`: `_compute_traverse()`, `verify_closure()`, `get_closure_summary()` — the core traverse logic
- `checks.py`: `check_interior_angles()`, `check_parallelism()`, `check_curve_consistency()`, `check_area_reasonableness()`, `check_double_entry()`, `check_bearing_reversals()`, `check_distance_reasonableness()` — individual check methods
- `confidence.py`: `score_call_quality()`, `calculate_confidence_score()` — scoring functions

Import changes: `from mp_bearing import calculate_deltas, ...` and `from mp_models import ...`

**Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/mp-verify/tests/ -v`
Expected: PASS

**Step 5: Commit**

```bash
git add packages/mp-verify/
git commit -m "feat(mp-verify): extract closure checker, verification checks, and confidence scoring"
```

---

## Phase 6: mp-export

### Task 13: Create mp-export with CSV and audit HTML writers

**Files:**
- Create: `packages/mp-export/pyproject.toml`
- Create: `packages/mp-export/src/mp_export/__init__.py`
- Create: `packages/mp-export/src/mp_export/csv_writer.py`
- Create: `packages/mp-export/src/mp_export/audit_html.py`
- Create: `packages/mp-export/tests/test_csv_writer.py`
- Create: `packages/mp-export/tests/test_audit_html.py`

**Step 1: Write the failing tests**

```python
# packages/mp-export/tests/test_csv_writer.py
import csv
import io

def test_csv_fieldnames_count():
    from mp_export.csv_writer import CSVWriter
    assert len(CSVWriter.FIELDNAMES) == 21

def test_calls_to_csv(tmp_path):
    from mp_models import DeedCall
    from mp_export.csv_writer import CSVWriter

    calls = [
        DeedCall(course=1, direction_text="North 45 East",
                 bearing_quadrant="N 45°00' E",
                 bearing_azimuth_deg_from_north=45.0, distance_ft=100.0),
    ]
    out = tmp_path / "test.csv"
    CSVWriter.calls_to_csv(calls, str(out))
    assert out.exists()
    with open(out) as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["course"] == "1"
```

```python
# packages/mp-export/tests/test_audit_html.py
from datetime import UTC, datetime

def test_generate_audit_html():
    from mp_models import AuditContext, RunMetadata
    from mp_export.audit_html import AuditHTMLWriter

    rm = RunMetadata(
        parser_version="1.0.0", llm_provider="openai", llm_model="gpt-5",
        prompt_hash="abc123", timestamp_utc=datetime.now(UTC),
        source_pdf="deed.pdf", cache_enabled=True,
    )
    ctx = AuditContext(run_metadata=rm)
    html = AuditHTMLWriter.generate_html(ctx)
    assert "<!DOCTYPE html>" in html
    assert "deed.pdf" in html
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/mp-export/tests/ -v`
Expected: FAIL

**Step 3: Create package and extract**

```toml
# packages/mp-export/pyproject.toml
[project]
name = "mp-export"
version = "1.0.0"
requires-python = ">=3.11"
description = "Export metes and bounds data to CSV, JSON, and audit HTML"
dependencies = [
    "mp-models>=1.0.0",
    "structlog>=24.4.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.3.0", "ruff>=0.8.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/mp_export"]
```

- `csv_writer.py`: Copy from `csv_builder.py`. Rename class to `CSVWriter`. Update imports to `from mp_models import ...`.
- `audit_html.py`: Copy from `audit_reporter.py`. Rename class to `AuditHTMLWriter`. Update imports to `from mp_models import AuditContext`.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/mp-export/tests/ -v`
Expected: PASS

**Step 5: Commit**

```bash
git add packages/mp-export/
git commit -m "feat(mp-export): extract CSV writer and audit HTML reporter"
```

---

## Phase 7: metesparser Orchestrator

### Task 14: Create metesparser orchestrator package

**Files:**
- Create: `packages/metesparser/pyproject.toml`
- Create: `packages/metesparser/src/metesparser/__init__.py`
- Create: `packages/metesparser/src/metesparser/pipeline.py`
- Create: `packages/metesparser/src/metesparser/run_registry.py`
- Create: `packages/metesparser/src/metesparser/cli.py`
- Create: `packages/metesparser/tests/test_pipeline.py`

**Step 1: Write the failing test**

```python
# packages/metesparser/tests/test_pipeline.py
def test_pipeline_importable():
    from metesparser import Pipeline
    assert Pipeline is not None

def test_pipeline_construction():
    """Pipeline should be constructable (but won't run without API keys)."""
    from metesparser.pipeline import Pipeline
    # Just verify the class exists and accepts params
    assert callable(Pipeline)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest packages/metesparser/tests/test_pipeline.py -v`
Expected: FAIL

**Step 3: Create orchestrator package**

```toml
# packages/metesparser/pyproject.toml
[project]
name = "metesparser"
version = "1.0.0"
requires-python = ">=3.11"
description = "Metes and bounds deed parser - orchestrator"
dependencies = [
    "mp-models>=1.0.0",
    "mp-bearing>=1.0.0",
    "mp-ocr>=1.0.0",
    "mp-parse>=1.0.0",
    "mp-verify>=1.0.0",
    "mp-export>=1.0.0",
    "python-dotenv>=1.0.0",
    "structlog>=24.4.0",
]

[project.optional-dependencies]
gemini = ["mp-ocr[gemini]>=1.0.0"]
dev = ["pytest>=8.3.0", "ruff>=0.8.0"]

[project.scripts]
mp = "metesparser.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/metesparser"]
```

Create `pipeline.py`:

```python
# packages/metesparser/src/metesparser/pipeline.py
"""Pipeline orchestrator that chains all stages."""

from __future__ import annotations

from pathlib import Path

from mp_models import ClosureResult, LegalDescription


class Pipeline:
    """Chain mp-ocr → mp-parse → mp-verify → mp-export."""

    def __init__(
        self,
        provider: str = "openai",
        *,
        cache: bool = True,
        audit: bool = False,
    ) -> None:
        self.provider = provider
        self.cache = cache
        self.audit = audit

    def run(self, pdf_path: Path) -> ClosureResult:
        """Run the full pipeline on a PDF."""
        from mp_ocr import PDFProcessor
        from mp_parse.calls import extract_calls
        from mp_parse.calls import enrich_calls_with_azimuths
        from mp_parse.calls import mark_tie_in_calls
        from mp_parse.metadata import (
            extract_plss_metadata,
            extract_poc_and_pob,
            extract_area_statement,
            extract_basis_of_bearing,
            extract_surveyor_certification,
            extract_prior_conveyance,
            extract_deed_clauses,
            extract_subdivision_reference,
            extract_witness_trees,
            extract_coordinate_system,
        )
        from mp_verify import verify_closure

        processor = PDFProcessor(provider=self.provider, cache=self.cache)
        result = processor.process_deed_pdf(str(pdf_path), audit=self.audit)

        if self.audit:
            legal_desc, audit_ctx = result  # type: ignore[misc]
        else:
            legal_desc = result  # type: ignore[assignment]
            audit_ctx = None

        closure_result = verify_closure(legal_desc.calls)
        return closure_result
```

Copy `run_registry.py` → `packages/metesparser/src/metesparser/run_registry.py` (no import changes needed — all stdlib/pydantic).

Create minimal `cli.py` with `mp` entry point.

**Step 4: Run test to verify it passes**

Run: `uv run pytest packages/metesparser/tests/test_pipeline.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add packages/metesparser/
git commit -m "feat(metesparser): create orchestrator with pipeline and CLI"
```

---

## Phase 8: Integration Verification

### Task 15: Run all existing tests against the workspace

**Step 1: Run the full test suite**

Run: `uv run pytest --tb=short -q`
Expected: ~956 tests pass. The original `src/metesparser/` package should still work since we haven't removed any code yet.

**Step 2: Run per-package tests**

Run each in sequence:
```bash
uv run pytest packages/mp-models/tests/ -v
uv run pytest packages/mp-bearing/tests/ -v
uv run pytest packages/mp-ocr/tests/ -v
uv run pytest packages/mp-parse/tests/ -v
uv run pytest packages/mp-verify/tests/ -v
uv run pytest packages/mp-export/tests/ -v
uv run pytest packages/metesparser/tests/ -v
```

Expected: all package tests pass

**Step 3: Run lint and type checks**

```bash
uv run ruff check packages/
uv run ruff format --check packages/
```

**Step 4: Commit any fixes**

```bash
git commit -m "test: verify all package tests pass in workspace"
```

---

### Task 16: Add cross-package import tests

**Files:**
- Create: `packages/metesparser/tests/test_imports.py`

**Step 1: Write the test**

```python
# packages/metesparser/tests/test_imports.py
"""Verify cross-package imports work correctly."""

def test_mp_models_imports():
    from mp_models import DeedCall, LegalDescription, ClosureResult, Point, AuditContext
    assert DeedCall is not None

def test_mp_bearing_imports():
    from mp_bearing import quadrant_to_azimuth, calculate_deltas, calculate_curve_properties
    assert quadrant_to_azimuth is not None

def test_mp_export_imports():
    from mp_export import CSVWriter, AuditHTMLWriter
    assert CSVWriter is not None

def test_mp_verify_imports():
    from mp_verify import verify_closure
    assert verify_closure is not None

def test_mp_parse_imports():
    from mp_parse.calls import extract_calls
    from mp_parse.monuments import classify_monument
    assert extract_calls is not None

def test_mp_models_envelope():
    from mp_models.envelope import RawTextMessage, read_jsonl, write_jsonl
    assert RawTextMessage is not None

def test_full_pipeline_import():
    from metesparser import Pipeline
    assert Pipeline is not None
```

**Step 2: Run the tests**

Run: `uv run pytest packages/metesparser/tests/test_imports.py -v`
Expected: all PASS

**Step 3: Commit**

```bash
git add packages/metesparser/tests/test_imports.py
git commit -m "test: add cross-package import verification tests"
```

---

## Notes for the Implementing Engineer

### Key References
- **Design doc**: `docs/plans/2026-02-16-unix-composable-modules-design.md` — approved architecture
- **CLAUDE.md**: Project conventions (ruff, uv, TDD, conventional commits)
- **Current models.py**: The source of truth for all Pydantic schemas (688 lines)
- **Current bearing_converter.py**: Pure math functions (522 lines)
- **Current text_parser.py**: 959 lines, excluded from ruff — handle Unicode DMS symbols carefully
- **Current call_extractor.py**: 907 lines, tightest coupling (imports from text_parser + bearing_converter)

### Gotchas
- `AuditContext` extends `BaseModel` directly (NOT `_Model`) — it's mutable
- `_COMMA_NUMBER` and `parse_comma_number` are shared between call_extractor and text_parser — both land in mp-parse
- `text_parser.py` is excluded from ruff in pyproject.toml due to Unicode DMS symbols
- Boolean fields in `DeedCall` use `_coerce_bool_field` validator — do NOT add `strict=True`
- The `enrich_call_with_azimuth()` method on `BearingConverter` depends on `DeedCall` — it belongs in mp-bearing since mp-bearing already depends on mp-models
- `_read_pdf()` helper in `llm_clients.py` is also used by `llm_cache.py` — keep it in `clients.py`

### Build Order
Must be built in this order (dependency tree):
1. mp-models (zero deps)
2. mp-bearing (depends on mp-models)
3. mp-ocr (depends on mp-models)
4. mp-parse (depends on mp-models + mp-bearing)
5. mp-verify (depends on mp-models + mp-bearing)
6. mp-export (depends on mp-models)
7. metesparser (depends on all)

### What This Plan Does NOT Do
- Remove the original `src/metesparser/` code (left for backward compat during migration)
- Add CLI entry points for individual packages (mp-bearing, mp-parse, etc.) — those are Phase 2 work
- Implement JSONL stdin/stdout piping CLIs — the envelope types are in place but CLI wiring is separate
- Migrate the 50 existing test files — they continue to test the original package
