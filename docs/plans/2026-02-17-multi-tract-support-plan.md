# Multi-Tract Support Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable the parser to detect, split, and independently verify multi-tract deeds (TRACT markers, multiple BEGINNING blocks, ALSO/EXCEPT clauses).

**Architecture:** Add a `Tract` wrapper model (mp-models), a `split_into_tracts()` splitter (mp-parse), per-tract verification (mp-verify), per-tract CSV export (mp-export), and pipeline wiring. Keep all existing single-tract behavior identical. Mirror all package changes in the monolith.

**Tech Stack:** Python 3.12, Pydantic v2, uv workspace monorepo, pytest, ruff

**Worktree:** `/Users/dfahey/projects/metesParser/.worktrees/multi-tract` (branch: `feat/multi-tract-support`)

**Design Doc:** `docs/plans/2026-02-17-multi-tract-support-design.md`

---

## Task 1: Add `TractType` enum and `Tract` model to mp-models

**Files:**
- Create: `packages/mp-models/src/mp_models/tract.py`
- Modify: `packages/mp-models/src/mp_models/__init__.py`
- Test: `packages/mp-models/tests/test_tract.py`

**Step 1: Write the failing test**

Create `packages/mp-models/tests/test_tract.py`:

```python
"""Tests for Tract model."""

from mp_models import DeedCall, TractType, Tract


class TestTractType:
    def test_main_value(self):
        assert TractType.MAIN == "main"

    def test_exception_value(self):
        assert TractType.EXCEPTION == "exception"

    def test_addition_value(self):
        assert TractType.ADDITION == "addition"

    def test_easement_value(self):
        assert TractType.EASEMENT == "easement"


class TestTract:
    def test_create_minimal_tract(self):
        tract = Tract(label="Tract 1", tract_type=TractType.MAIN, calls=[])
        assert tract.label == "Tract 1"
        assert tract.tract_type == TractType.MAIN
        assert tract.calls == []
        assert tract.pob_description is None
        assert tract.stated_area_sq_ft is None
        assert tract.closure_result is None

    def test_create_tract_with_calls(self):
        call = DeedCall(
            course=1,
            direction_text="N 45°00' E",
            distance_ft=100.0,
        )
        tract = Tract(
            label="Parcel A",
            tract_type=TractType.ADDITION,
            calls=[call],
            pob_description="at an iron pin",
            stated_area_sq_ft=5000.0,
        )
        assert len(tract.calls) == 1
        assert tract.pob_description == "at an iron pin"
        assert tract.stated_area_sq_ft == 5000.0

    def test_tract_is_frozen(self):
        tract = Tract(label="Tract 1", tract_type=TractType.MAIN, calls=[])
        import pytest
        with pytest.raises(Exception):
            tract.label = "changed"  # type: ignore[misc]

    def test_tract_forbids_extra(self):
        import pytest
        with pytest.raises(Exception):
            Tract(label="X", tract_type=TractType.MAIN, calls=[], foo="bar")  # type: ignore[call-arg]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest packages/mp-models/tests/test_tract.py -v --no-cov`
Expected: FAIL with `ImportError` (TractType/Tract not defined)

**Step 3: Write minimal implementation**

Create `packages/mp-models/src/mp_models/tract.py`:

```python
"""Tract model for multi-tract deed support."""

from enum import Enum

from pydantic import Field, FiniteFloat

from .base import _Model
from .closure import ClosureResult
from .deed_call import DeedCall


class TractType(str, Enum):
    """Type of tract in a multi-tract deed."""

    MAIN = "main"
    EXCEPTION = "exception"
    ADDITION = "addition"
    EASEMENT = "easement"


class Tract(_Model):
    """A single tract within a multi-tract deed."""

    label: str = Field(..., description="Tract label (e.g., 'Tract 1', 'Exception 1')")
    tract_type: TractType = Field(..., description="Type of tract")
    calls: list[DeedCall] = Field(default_factory=list, description="Calls for this tract")
    pob_description: str | None = Field(default=None, description="POB for this tract")
    stated_area_sq_ft: FiniteFloat | None = Field(default=None, description="Stated area")
    closure_result: ClosureResult | None = Field(
        default=None, description="Closure result (populated by mp-verify)"
    )
```

Add imports to `packages/mp-models/src/mp_models/__init__.py`:
- Add `from .tract import Tract, TractType` after the `legal_description` import
- Add `"Tract"` and `"TractType"` to `__all__`

**Step 4: Run test to verify it passes**

Run: `uv run pytest packages/mp-models/tests/test_tract.py -v --no-cov`
Expected: PASS (all 6 tests)

**Step 5: Commit**

```bash
git add packages/mp-models/src/mp_models/tract.py packages/mp-models/tests/test_tract.py packages/mp-models/src/mp_models/__init__.py
git commit -m "feat(mp-models): add TractType enum and Tract model for multi-tract support"
```

---

## Task 2: Add `tracts` field and `all_calls` property to `LegalDescription`

**Files:**
- Modify: `packages/mp-models/src/mp_models/legal_description.py:30` (after `calls` field)
- Test: `packages/mp-models/tests/test_tract.py` (extend)

**Step 1: Write the failing test**

Append to `packages/mp-models/tests/test_tract.py`:

```python
from mp_models import LegalDescription


class TestLegalDescriptionTracts:
    def test_tracts_default_empty(self):
        ld = LegalDescription()
        assert ld.tracts == []

    def test_all_calls_returns_flat_calls_when_no_tracts(self):
        call = DeedCall(course=1, direction_text="N 45°00' E", distance_ft=100.0)
        ld = LegalDescription(calls=[call])
        assert ld.all_calls == [call]

    def test_all_calls_merges_tract_calls(self):
        c1 = DeedCall(course=1, direction_text="N 45°00' E", distance_ft=100.0)
        c2 = DeedCall(course=2, direction_text="S 45°00' E", distance_ft=200.0)
        t1 = Tract(label="Tract 1", tract_type=TractType.MAIN, calls=[c1])
        t2 = Tract(label="Tract 2", tract_type=TractType.MAIN, calls=[c2])
        ld = LegalDescription(tracts=[t1, t2])
        assert ld.all_calls == [c1, c2]

    def test_all_calls_prefers_tracts_over_calls(self):
        c1 = DeedCall(course=1, direction_text="N 45°00' E", distance_ft=100.0)
        c2 = DeedCall(course=2, direction_text="S 45°00' E", distance_ft=200.0)
        t1 = Tract(label="Tract 1", tract_type=TractType.MAIN, calls=[c2])
        ld = LegalDescription(calls=[c1], tracts=[t1])
        # When tracts exist, all_calls comes from tracts, not calls
        assert ld.all_calls == [c2]

    def test_num_calls_still_uses_calls_field(self):
        c1 = DeedCall(course=1, direction_text="N 45°00' E", distance_ft=100.0)
        ld = LegalDescription(calls=[c1])
        assert ld.num_calls() == 1
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest packages/mp-models/tests/test_tract.py::TestLegalDescriptionTracts -v --no-cov`
Expected: FAIL with `AttributeError` (no `tracts` field or `all_calls` property)

**Step 3: Write minimal implementation**

In `packages/mp-models/src/mp_models/legal_description.py`:

Add import at top:
```python
from .tract import Tract
```

After the `calls` field (line 32), add:
```python
    tracts: list[Tract] = Field(
        default_factory=list,
        description="Tracts in a multi-tract deed (empty for single-tract)",
    )
```

After the `has_incomplete_calls()` method (end of class), add:
```python
    @property
    def all_calls(self) -> list[DeedCall]:
        """Flat list of all calls across all tracts.

        Returns tract calls when tracts exist, otherwise falls back to self.calls.
        """
        if self.tracts:
            return [c for t in self.tracts for c in t.calls]
        return list(self.calls)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest packages/mp-models/tests/test_tract.py -v --no-cov`
Expected: PASS (all 11 tests)

**Step 5: Run full test suite for regressions**

Run: `uv run pytest --tb=short -q`
Expected: 996 passed (no regressions — `tracts` defaults to empty list)

**Step 6: Commit**

```bash
git add packages/mp-models/src/mp_models/legal_description.py packages/mp-models/tests/test_tract.py
git commit -m "feat(mp-models): add tracts field and all_calls property to LegalDescription"
```

---

## Task 3: Add `split_into_tracts()` to mp-parse

**Files:**
- Create: `packages/mp-parse/src/mp_parse/tracts.py`
- Modify: `packages/mp-parse/src/mp_parse/__init__.py`
- Test: `packages/mp-parse/tests/test_tracts.py`

**Step 1: Write the failing test**

Create `packages/mp-parse/tests/test_tracts.py`:

```python
"""Tests for tract splitting logic."""

import pytest
from mp_models import TractType
from mp_parse.tracts import split_into_tracts


class TestExplicitTractMarkers:
    """Priority 1: TRACT #N, TRACT A, PARCEL N markers."""

    def test_tract_numbered(self):
        text = (
            "TRACT #1: BEGINNING at a point... THENCE N 45°00' E 100 feet "
            "to the POINT OF BEGINNING. "
            "TRACT #2: BEGINNING at a point... THENCE S 45°00' E 200 feet "
            "to the POINT OF BEGINNING."
        )
        result = split_into_tracts(text)
        assert len(result) == 2
        assert result[0][1] == "Tract 1"
        assert result[0][2] == TractType.MAIN
        assert result[1][1] == "Tract 2"
        assert result[1][2] == TractType.MAIN

    def test_tract_lettered(self):
        text = (
            "TRACT A: BEGINNING at a point... THENCE N 45°00' E 100 feet "
            "to the POINT OF BEGINNING. "
            "TRACT B: BEGINNING at a point... THENCE S 45°00' E 200 feet "
            "to the POINT OF BEGINNING."
        )
        result = split_into_tracts(text)
        assert len(result) == 2
        assert result[0][1] == "Tract A"
        assert result[1][1] == "Tract B"

    def test_parcel_numbered(self):
        text = (
            "PARCEL 1: BEGINNING at a point... THENCE N 45°00' E 100 feet "
            "to the POINT OF BEGINNING. "
            "PARCEL 2: BEGINNING at a point... THENCE S 45°00' E 200 feet "
            "to the POINT OF BEGINNING."
        )
        result = split_into_tracts(text)
        assert len(result) == 2
        assert result[0][1] == "Parcel 1"
        assert result[1][1] == "Parcel 2"


class TestMultipleBeginningBlocks:
    """Priority 2: Multiple BEGINNING blocks."""

    def test_two_beginning_blocks(self):
        text = (
            "BEGINNING at an iron pin... THENCE N 45°00' E 100 feet "
            "to the POINT OF BEGINNING. "
            "ALSO BEGINNING at a concrete monument... THENCE S 45°00' E 200 feet "
            "to the POINT OF BEGINNING."
        )
        result = split_into_tracts(text)
        assert len(result) >= 2

    def test_single_beginning_block_no_split(self):
        text = (
            "BEGINNING at a point... THENCE N 45°00' E 100 feet "
            "to the POINT OF BEGINNING."
        )
        result = split_into_tracts(text)
        assert len(result) == 1


class TestExceptAlsoFallback:
    """Priority 3: EXCEPT/ALSO fallback."""

    def test_except_clause(self):
        text = (
            "BEGINNING at a point... THENCE N 45°00' E 100 feet "
            "to the POINT OF BEGINNING. "
            "EXCEPT BEGINNING at another point... THENCE S 45°00' E 50 feet "
            "to the POINT OF BEGINNING."
        )
        result = split_into_tracts(text)
        # Should have main + exception
        types = [r[2] for r in result]
        assert TractType.MAIN in types
        assert TractType.EXCEPTION in types

    def test_also_clause(self):
        text = (
            "BEGINNING at a point... THENCE N 45°00' E 100 feet "
            "to the POINT OF BEGINNING. "
            "ALSO BEGINNING at another point... THENCE S 45°00' E 50 feet "
            "to the POINT OF BEGINNING."
        )
        result = split_into_tracts(text)
        types = [r[2] for r in result]
        assert TractType.MAIN in types
        assert TractType.ADDITION in types


class TestSingleTract:
    """Single-tract deeds pass through unchanged."""

    def test_simple_single_tract(self):
        text = "THENCE N 45°00' E 100 feet to the POINT OF BEGINNING."
        result = split_into_tracts(text)
        assert len(result) == 1
        assert result[0][1] == "Tract 1"
        assert result[0][2] == TractType.MAIN

    def test_return_type(self):
        text = "THENCE N 45°00' E 100 feet."
        result = split_into_tracts(text)
        # Each element is (text, label, tract_type)
        assert isinstance(result, list)
        text_val, label, tract_type = result[0]
        assert isinstance(text_val, str)
        assert isinstance(label, str)
        assert isinstance(tract_type, TractType)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest packages/mp-parse/tests/test_tracts.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError` (mp_parse.tracts not found)

**Step 3: Write minimal implementation**

Create `packages/mp-parse/src/mp_parse/tracts.py`:

```python
"""Split legal descriptions into tracts.

Detects multi-tract patterns in priority order:
1. Explicit markers: TRACT #N, TRACT A, PARCEL N
2. Multiple BEGINNING blocks with independent closures
3. EXCEPT/ALSO clauses (reuses split_exception_clauses)
"""

from __future__ import annotations

import re

from mp_models import TractType

from .metadata import split_exception_clauses

# TRACT #1, TRACT 1, TRACT A, TRACT ONE (with optional colon/dash)
_TRACT_MARKER = re.compile(
    r"\bTRACT\s+(?:#\s*)?([A-Z0-9]+)\s*[:.\-—]?\s*",
    re.IGNORECASE,
)

# PARCEL 1, PARCEL A (with optional colon/dash)
_PARCEL_MARKER = re.compile(
    r"\bPARCEL\s+(?:#\s*)?([A-Z0-9]+)\s*[:.\-—]?\s*",
    re.IGNORECASE,
)

# BEGINNING at/in (start of a metes block)
_BEGINNING_PATTERN = re.compile(
    r"\bBEGINNING\s+(?:at|in)\b",
    re.IGNORECASE,
)

# Closure to POB
_POB_CLOSE_PATTERN = re.compile(
    r"(?:POINT\s+(?:AND\s+PLACE\s+)?OF\s+BEGINNING|place\s+of\s+BEGINNING|POB)\b",
    re.IGNORECASE,
)


def find_tract_markers(
    text: str,
) -> list[tuple[int, str, str]]:
    """Find explicit TRACT or PARCEL markers.

    Returns: list of (position, label, marker_kind)
    """
    markers: list[tuple[int, str, str]] = []
    for m in _TRACT_MARKER.finditer(text):
        markers.append((m.start(), f"Tract {m.group(1)}", "tract"))
    for m in _PARCEL_MARKER.finditer(text):
        markers.append((m.start(), f"Parcel {m.group(1)}", "parcel"))
    markers.sort(key=lambda x: x[0])
    return markers


def split_on_markers(
    text: str,
    markers: list[tuple[int, str, str]],
) -> list[tuple[str, str, TractType]]:
    """Split text on explicit markers."""
    result: list[tuple[str, str, TractType]] = []
    for i, (pos, label, _kind) in enumerate(markers):
        end = markers[i + 1][0] if i + 1 < len(markers) else len(text)
        segment = text[pos:end].strip()
        result.append((segment, label, TractType.MAIN))
    return result


def find_beginning_blocks(text: str) -> list[tuple[int, int]]:
    """Find BEGINNING...POB blocks.

    Returns: list of (start, end) positions
    """
    blocks: list[tuple[int, int]] = []
    for m in _BEGINNING_PATTERN.finditer(text):
        # Look for matching POB closure after this BEGINNING
        close = _POB_CLOSE_PATTERN.search(text, m.end())
        if close:
            # Verify this block has at least one THENCE
            block_text = text[m.start() : close.end()]
            if re.search(r"\bTHENCE\b", block_text, re.IGNORECASE):
                blocks.append((m.start(), close.end()))
    return blocks


def label_beginning_blocks(
    blocks: list[tuple[int, int]],
    text: str,
) -> list[tuple[str, str, TractType]]:
    """Label multiple BEGINNING blocks as tracts.

    Inspects the text preceding each block to detect ALSO/EXCEPT keywords
    and assign the correct TractType.
    """
    result: list[tuple[str, str, TractType]] = []
    main_count = 0
    exception_count = 0
    addition_count = 0

    for start, end in blocks:
        segment = text[start:end].strip()

        # Check text before this block for EXCEPT or ALSO keywords
        preceding = text[max(0, start - 80) : start]
        tract_type = TractType.MAIN

        if re.search(r"\b(?:LESS\s+AND\s+)?EXCEPT(?:ING)?\b", preceding, re.IGNORECASE):
            tract_type = TractType.EXCEPTION
            exception_count += 1
            label = f"Exception {exception_count}"
        elif re.search(r"\b(?:ALSO|INCLUDING)\b", preceding, re.IGNORECASE):
            tract_type = TractType.ADDITION
            addition_count += 1
            label = f"Addition {addition_count}"
        else:
            main_count += 1
            label = f"Tract {main_count}"

        result.append((segment, label, tract_type))

    return result


def _auto_label(index: int, is_exception: bool) -> str:
    """Generate a label for an exception/main clause."""
    if is_exception:
        return f"Exception {index + 1}"
    return f"Tract {index + 1}"


def split_into_tracts(text: str) -> list[tuple[str, str, TractType]]:
    """Split legal description text into tract segments.

    Detection priority:
    1. Explicit TRACT/PARCEL markers
    2. Multiple BEGINNING blocks
    3. EXCEPT/ALSO clauses (fallback)

    Returns: list of (tract_text, label, tract_type)
    """
    # 1. Try explicit TRACT/PARCEL markers
    markers = find_tract_markers(text)
    if markers:
        return split_on_markers(text, markers)

    # 2. Try multiple BEGINNING blocks
    blocks = find_beginning_blocks(text)
    if len(blocks) > 1:
        return label_beginning_blocks(blocks, text)

    # 3. Fall back to EXCEPT/ALSO splitting
    clauses = split_exception_clauses(text)
    if len(clauses) > 1:
        result: list[tuple[str, str, TractType]] = []
        main_idx = 0
        exc_idx = 0
        for clause_text, is_exc in clauses:
            if is_exc:
                exc_idx += 1
                result.append((clause_text, f"Exception {exc_idx}", TractType.EXCEPTION))
            else:
                # Check if this looks like an ALSO/ADDITION clause
                if re.search(r"\b(?:ALSO|INCLUDING)\b", clause_text[:50], re.IGNORECASE):
                    result.append((clause_text, f"Addition {main_idx + 1}", TractType.ADDITION))
                else:
                    main_idx += 1
                    result.append((clause_text, f"Tract {main_idx}", TractType.MAIN))
        return result

    # Single tract — pass through
    return [(text, "Tract 1", TractType.MAIN)]
```

Add to `packages/mp-parse/src/mp_parse/__init__.py`:
- Add `from .tracts import split_into_tracts` to imports
- Add `"split_into_tracts"` to `__all__`

**Step 4: Run test to verify it passes**

Run: `uv run pytest packages/mp-parse/tests/test_tracts.py -v --no-cov`
Expected: PASS (all tests)

**Step 5: Run full test suite for regressions**

Run: `uv run pytest --tb=short -q`
Expected: 996 passed

**Step 6: Commit**

```bash
git add packages/mp-parse/src/mp_parse/tracts.py packages/mp-parse/tests/test_tracts.py packages/mp-parse/src/mp_parse/__init__.py
git commit -m "feat(mp-parse): add split_into_tracts() for multi-tract detection"
```

---

## Task 4: Wire `split_into_tracts()` into `extract_calls()` to populate `Tract` objects

**Files:**
- Modify: `packages/mp-parse/src/mp_parse/calls.py:126-208` (`extract_calls`)
- Test: `packages/mp-parse/tests/test_tracts.py` (extend)

**Step 1: Write the failing test**

Append to `packages/mp-parse/tests/test_tracts.py`:

```python
from mp_parse.calls import extract_calls


class TestExtractCallsMultiTract:
    """extract_calls returns Tract objects when multi-tract patterns detected."""

    def test_returns_tracts_for_tract_markers(self):
        text = (
            "TRACT #1: BEGINNING at a point THENCE North 45 degrees 00 minutes 00 seconds East, "
            "a distance of 100.00 feet to a point; THENCE South 45 degrees 00 minutes 00 seconds East, "
            "a distance of 100.00 feet to a point; THENCE South 45 degrees 00 minutes 00 seconds West, "
            "a distance of 100.00 feet to a point; THENCE North 45 degrees 00 minutes 00 seconds West, "
            "a distance of 100.00 feet to the POINT OF BEGINNING. "
            "TRACT #2: BEGINNING at a point THENCE South 45 degrees 00 minutes 00 seconds East, "
            "a distance of 50.00 feet to a point; THENCE South 45 degrees 00 minutes 00 seconds West, "
            "a distance of 50.00 feet to a point; THENCE North 45 degrees 00 minutes 00 seconds West, "
            "a distance of 50.00 feet to a point; THENCE North 45 degrees 00 minutes 00 seconds East, "
            "a distance of 50.00 feet to the POINT OF BEGINNING."
        )
        calls, tracts = extract_calls(text)
        assert len(tracts) == 2
        assert tracts[0].label == "Tract 1"
        assert tracts[1].label == "Tract 2"
        # Course numbering resets per tract
        assert tracts[0].calls[0].course == 1
        assert tracts[1].calls[0].course == 1

    def test_single_tract_returns_empty_tracts(self):
        text = (
            "THENCE North 45 degrees 00 minutes 00 seconds East, "
            "a distance of 100.00 feet to a point; THENCE South 45 degrees 00 minutes 00 seconds East, "
            "a distance of 100.00 feet to the POINT OF BEGINNING."
        )
        calls, tracts = extract_calls(text)
        assert tracts == []
        assert len(calls) == 2

    def test_except_clause_returns_tracts(self):
        text = (
            "THENCE North 45 degrees 00 minutes 00 seconds East, a distance of 100.00 feet; "
            "THENCE South 45 degrees 00 minutes 00 seconds East, a distance of 100.00 feet; "
            "THENCE South 45 degrees 00 minutes 00 seconds West, a distance of 100.00 feet; "
            "THENCE North 45 degrees 00 minutes 00 seconds West, a distance of 100.00 feet "
            "EXCEPT THENCE South 10 degrees 00 minutes 00 seconds East, a distance of 50.00 feet; "
            "THENCE South 10 degrees 00 minutes 00 seconds West, a distance of 50.00 feet"
        )
        calls, tracts = extract_calls(text)
        assert len(tracts) >= 2
        types = [t.tract_type for t in tracts]
        assert TractType.MAIN in types
        assert TractType.EXCEPTION in types
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest packages/mp-parse/tests/test_tracts.py::TestExtractCallsMultiTract -v --no-cov`
Expected: FAIL (extract_calls returns list, not tuple)

**Step 3: Modify `extract_calls()` to return tracts**

In `packages/mp-parse/src/mp_parse/calls.py`:

Change the signature and body of `extract_calls()` (line 126) to:

```python
def extract_calls(
    text: str,
    distance_unit: str = "feet",
    *,
    audit_context: AuditContext | None = None,
) -> tuple[list[DeedCall], list["Tract"]]:
    """Extract all calls from normalized legal description text.

    Handles multi-tract deeds (TRACT markers, multiple BEGINNINGs,
    EXCEPT/ALSO clauses) and marks calls accordingly.

    Args:
        text: Normalized legal description text
        distance_unit: Primary distance unit (feet, poles, etc.)
        audit_context: Optional audit context for recording parsing decisions

    Returns:
        Tuple of (flat_calls, tracts).
        - For single-tract deeds: flat_calls populated, tracts is empty.
        - For multi-tract deeds: flat_calls is the merged list, tracts has per-tract objects.
    """
    from mp_models import Tract, TractType
    from .tracts import split_into_tracts

    normalized = normalize_legal_description(text)
    segments = split_into_tracts(normalized)

    # Single-tract fast path: preserve backward-compatible behavior
    if len(segments) == 1 and segments[0][2] == TractType.MAIN:
        # Check if this was a genuine single tract (no EXCEPT/ALSO splitting)
        flat_calls = _extract_calls_from_text(
            normalized, distance_unit, audit_context=audit_context, course_start=1
        )
        return flat_calls, []

    # Multi-tract path
    all_calls: list[DeedCall] = []
    tracts: list[Tract] = []

    for segment_text, label, tract_type in segments:
        tract_calls = _extract_calls_from_text(
            segment_text, distance_unit, audit_context=audit_context, course_start=1
        )

        if tract_type == TractType.EXCEPTION:
            tract_calls = [c.model_copy(update={"is_exception": True}) for c in tract_calls]

        tract = Tract(
            label=label,
            tract_type=tract_type,
            calls=tract_calls,
        )
        tracts.append(tract)
        all_calls.extend(tract_calls)

    return all_calls, tracts
```

Extract the inner loop into `_extract_calls_from_text()`:

```python
def _extract_calls_from_text(
    text: str,
    distance_unit: str = "feet",
    *,
    audit_context: AuditContext | None = None,
    course_start: int = 1,
) -> list[DeedCall]:
    """Extract calls from a single text segment (one tract).

    This is the inner extraction loop, factored out for reuse by
    both single-tract and multi-tract paths.
    """
    # Strip POB preamble
    thence_match = re.search(r"\bTHENCE\b", text, re.IGNORECASE)
    if thence_match:
        text = text[thence_match.start():]

    call_texts = split_into_calls(text)
    calls: list[DeedCall] = []
    course_num = course_start

    for call_text in call_texts:
        try:
            call = extract_single_call(
                call_text, course=course_num, distance_unit=distance_unit
            )
        except (ValidationError, ValueError, TypeError) as exc:
            payload = {
                "course": course_num,
                "call_preview": _call_preview(call_text),
                "call_hash": _call_hash(call_text),
                "error": str(exc),
                "error_type": type(exc).__name__,
            }
            if _is_debug_logging_enabled():
                logger.warning("Skipping malformed call", **payload, call_text=call_text, exc_info=exc)
            else:
                logger.warning("Skipping malformed call", **payload)
            continue

        if call is None:
            continue

        calls.append(call)

        if audit_context is not None:
            transformations, decisions, flags = _audit_single_call(call_text, call)
            audit_context.call_audits.append(
                CallAudit(
                    course=course_num,
                    source_excerpt=call_text,
                    transformations=transformations,
                    decisions=decisions,
                    flags=flags,
                )
            )

        course_num += 1

    return calls
```

**Important:** Every caller of `extract_calls()` now needs to handle the tuple return. The old code did `calls = extract_calls(text)` — now it must do `calls, tracts = extract_calls(text)` or `calls, _ = extract_calls(text)`.

**Step 4: Update all callers of `extract_calls()`**

Search for all callers and update them. Key locations:
- `packages/mp-parse/src/mp_parse/__init__.py` (re-export)
- `src/metesparser/pdf_processor.py` (monolith — Task 8)

For now, check if there are callers in the packages:

Run: `grep -rn "extract_calls(" packages/ src/ tests/ --include="*.py" | grep -v "test_tracts"`

Update each caller to unpack the tuple. Most will just need `calls, _ = extract_calls(text)` for backward compat.

**Step 5: Run test to verify it passes**

Run: `uv run pytest packages/mp-parse/tests/test_tracts.py -v --no-cov`
Expected: PASS

**Step 6: Run full test suite — fix any callers that break**

Run: `uv run pytest --tb=short -q`
Expected: Some tests may break from the new return type. Fix each by unpacking the tuple.

**Step 7: Commit**

```bash
git add packages/mp-parse/src/mp_parse/calls.py packages/mp-parse/tests/test_tracts.py
# Also add any other files modified to fix callers
git commit -m "feat(mp-parse): wire split_into_tracts into extract_calls, return Tract objects"
```

---

## Task 5: Add `verify_tract()` and multi-tract `verify_closure()` to mp-verify

**Files:**
- Modify: `packages/mp-verify/src/mp_verify/closure.py:148` (add `verify_tract`, update `verify_closure`)
- Test: `packages/mp-verify/tests/test_multi_tract_verify.py`

**Step 1: Write the failing test**

Create `packages/mp-verify/tests/test_multi_tract_verify.py`:

```python
"""Tests for multi-tract verification."""

import pytest
from mp_models import ClosureResult, DeedCall, Tract, TractType
from mp_verify import verify_closure
from mp_verify.closure import verify_tract


def _square_calls(size: float = 100.0, course_start: int = 1) -> list[DeedCall]:
    """Generate a perfect square of calls."""
    return [
        DeedCall(course=course_start, direction_text="N 45°00' E",
                 bearing_quadrant="N 45°00' E", bearing_azimuth_deg_from_north=45.0,
                 distance_ft=size),
        DeedCall(course=course_start + 1, direction_text="S 45°00' E",
                 bearing_quadrant="S 45°00' E", bearing_azimuth_deg_from_north=135.0,
                 distance_ft=size),
        DeedCall(course=course_start + 2, direction_text="S 45°00' W",
                 bearing_quadrant="S 45°00' W", bearing_azimuth_deg_from_north=225.0,
                 distance_ft=size),
        DeedCall(course=course_start + 3, direction_text="N 45°00' W",
                 bearing_quadrant="N 45°00' W", bearing_azimuth_deg_from_north=315.0,
                 distance_ft=size),
    ]


class TestVerifyTract:
    def test_single_tract_closes(self):
        calls = _square_calls()
        result = verify_tract(calls)
        assert isinstance(result, ClosureResult)
        assert result.closure_passed
        assert result.area_sq_ft > 0

    def test_verify_tract_does_not_split_exceptions(self):
        """verify_tract treats all calls as one traverse — no splitting."""
        calls = _square_calls()
        # Mark some as exception — verify_tract should still include them
        calls_with_exc = [c.model_copy(update={"is_exception": True}) for c in calls]
        result = verify_tract(calls_with_exc)
        # Should still verify (because verify_tract doesn't filter exceptions)
        assert isinstance(result, ClosureResult)


class TestVerifyClosureMultiTract:
    def test_multi_tract_returns_list(self):
        t1 = Tract(label="Tract 1", tract_type=TractType.MAIN, calls=_square_calls(100.0))
        t2 = Tract(label="Exception 1", tract_type=TractType.EXCEPTION, calls=_square_calls(50.0))
        result = verify_closure(_square_calls(100.0), tracts=[t1, t2])
        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(r, ClosureResult) for r in result)

    def test_no_tracts_returns_single_result(self):
        """Backward compat: no tracts param = single ClosureResult."""
        result = verify_closure(_square_calls())
        assert isinstance(result, ClosureResult)

    def test_per_tract_closure_independent(self):
        t1 = Tract(label="Tract 1", tract_type=TractType.MAIN, calls=_square_calls(100.0))
        t2 = Tract(label="Tract 2", tract_type=TractType.MAIN, calls=_square_calls(50.0))
        results = verify_closure(_square_calls(100.0), tracts=[t1, t2])
        assert isinstance(results, list)
        # Each tract verified independently
        assert results[0].closure_passed
        assert results[1].closure_passed
        # Areas should differ (100^2 vs 50^2 ≈ 10000 vs 2500)
        assert results[0].area_sq_ft > results[1].area_sq_ft
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest packages/mp-verify/tests/test_multi_tract_verify.py -v --no-cov`
Expected: FAIL (no `verify_tract`, no `tracts` param on `verify_closure`)

**Step 3: Implement `verify_tract()` and update `verify_closure()`**

In `packages/mp-verify/src/mp_verify/closure.py`:

Add import at top:
```python
from mp_models import Tract
```

Add `verify_tract()` function before `verify_closure()`:

```python
def verify_tract(
    calls: list[DeedCall],
    *,
    stated_area_sq_ft: float = 0.0,
    closure_tolerance_ft: float | None = None,
    audit_context: AuditContext | None = None,
) -> ClosureResult:
    """Verify one tract's closure independently.

    Unlike verify_closure(), this does NOT split by is_exception.
    All calls are treated as a single traverse.
    """
    tolerance = closure_tolerance_ft if closure_tolerance_ft is not None else CLOSURE_TOLERANCE_FT

    # Use all calls — no exception filtering
    active_calls = [c for c in calls if not c.is_tie_in]
    points = compute_traverse(active_calls)

    computable = sum(1 for c in active_calls if c.bearing_azimuth_deg_from_north is not None)
    has_computable = computable > 0

    misclosure_x = points[-1].x - points[0].x
    misclosure_y = points[-1].y - points[0].y
    misclosure = math.sqrt(misclosure_x**2 + misclosure_y**2)

    warnings: list[str] = []
    if not has_computable:
        warnings.append("No computable traverse — all calls lack bearings")

    try:
        area_sq_ft = calculate_area(points)
        area_acres = area_sq_ft / 43560.0
    except ValueError as e:
        area_sq_ft = 0.0
        area_acres = 0.0
        warnings.append(f"Cannot calculate area: {e}")

    perimeter = calculate_perimeter(active_calls)
    closure_passed = has_computable and misclosure < tolerance
    angle_check_passed = check_interior_angles(active_calls, points)
    curve_ok, curve_warnings = check_curve_consistency(active_calls)
    warnings.extend(curve_warnings)
    warnings.extend(check_parallelism(active_calls))
    warnings.extend(check_bearing_reversals(active_calls))
    warnings.extend(check_distance_reasonableness(active_calls))

    if stated_area_sq_ft > 0:
        diff_pct = abs(area_sq_ft - stated_area_sq_ft) / stated_area_sq_ft * 100
        if diff_pct > 5.0:
            warnings.append(
                f"Computed area differs from stated by {diff_pct:.1f}% "
                f"(computed: {area_sq_ft:.1f} sq ft, stated: {stated_area_sq_ft:.1f} sq ft)"
            )

    result = ClosureResult(
        misclosure_x_ft=misclosure_x,
        misclosure_y_ft=misclosure_y,
        misclosure_ft=misclosure,
        area_sq_ft=area_sq_ft,
        area_acres=area_acres,
        perimeter_ft=perimeter,
        closure_passed=closure_passed,
        angle_check_passed=angle_check_passed,
        curve_consistency_passed=curve_ok,
        warnings=warnings,
        points=points,
        precision_ratio=misclosure / perimeter if perimeter else None,
    )
    confidence = calculate_confidence_score(result, active_calls)
    return result.model_copy(update={"confidence_score": confidence})
```

Update `verify_closure()` signature to accept optional `tracts`:

```python
def verify_closure(
    calls: list[DeedCall],
    *,
    tracts: list[Tract] | None = None,
    stated_area_sq_ft: float = 0.0,
    closure_tolerance_ft: float | None = None,
    double_entry_calls: list[DeedCall] | None = None,
    audit_context: AuditContext | None = None,
) -> ClosureResult | list[ClosureResult]:
```

At the beginning of the function body, add the multi-tract branch:

```python
    if tracts:
        results: list[ClosureResult] = []
        for tract in tracts:
            result = verify_tract(
                tract.calls,
                stated_area_sq_ft=tract.stated_area_sq_ft or 0.0,
                closure_tolerance_ft=closure_tolerance_ft,
                audit_context=audit_context,
            )
            results.append(result)
        return results
```

Then the existing single-tract code follows unchanged.

Update `__init__.py` to export `verify_tract`:
- Add `from .closure import verify_tract` and `"verify_tract"` to `__all__`

**Step 4: Run test to verify it passes**

Run: `uv run pytest packages/mp-verify/tests/test_multi_tract_verify.py -v --no-cov`
Expected: PASS

**Step 5: Run full test suite for regressions**

Run: `uv run pytest --tb=short -q`
Expected: 996+ passed (existing callers unaffected — `tracts` defaults to None)

**Step 6: Commit**

```bash
git add packages/mp-verify/src/mp_verify/closure.py packages/mp-verify/tests/test_multi_tract_verify.py packages/mp-verify/src/mp_verify/__init__.py
git commit -m "feat(mp-verify): add verify_tract() and multi-tract verify_closure()"
```

---

## Task 6: Add per-tract CSV export to mp-export

**Files:**
- Modify: `packages/mp-export/src/mp_export/csv_writer.py:242` (`export_verified_csv`)
- Test: `packages/mp-export/tests/test_multi_tract_export.py`

**Step 1: Write the failing test**

Create `packages/mp-export/tests/test_multi_tract_export.py`:

```python
"""Tests for multi-tract CSV export."""

from pathlib import Path

import pytest
from mp_models import ClosureResult, DeedCall, Tract, TractType
from mp_export.csv_writer import export_verified_csv


def _square_calls(size: float = 100.0) -> list[DeedCall]:
    return [
        DeedCall(course=1, direction_text="N 45°00' E",
                 bearing_quadrant="N 45°00' E", bearing_azimuth_deg_from_north=45.0,
                 distance_ft=size),
        DeedCall(course=2, direction_text="S 45°00' E",
                 bearing_quadrant="S 45°00' E", bearing_azimuth_deg_from_north=135.0,
                 distance_ft=size),
        DeedCall(course=3, direction_text="S 45°00' W",
                 bearing_quadrant="S 45°00' W", bearing_azimuth_deg_from_north=225.0,
                 distance_ft=size),
        DeedCall(course=4, direction_text="N 45°00' W",
                 bearing_quadrant="N 45°00' W", bearing_azimuth_deg_from_north=315.0,
                 distance_ft=size),
    ]


def _good_closure(area: float = 10000.0) -> ClosureResult:
    return ClosureResult(
        misclosure_x_ft=0.0, misclosure_y_ft=0.0, misclosure_ft=0.0,
        area_sq_ft=area, area_acres=area / 43560.0, perimeter_ft=400.0,
        closure_passed=True, angle_check_passed=True,
        curve_consistency_passed=True, warnings=[],
    )


class TestMultiTractExport:
    def test_single_tract_returns_single_path(self, tmp_path: Path):
        result = export_verified_csv(
            _square_calls(), _good_closure(), str(tmp_path / "deed.csv"),
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert "_verified" in result[0].stem

    def test_multi_tract_returns_multiple_paths(self, tmp_path: Path):
        t1 = Tract(label="Tract 1", tract_type=TractType.MAIN, calls=_square_calls(100.0))
        t2 = Tract(label="Exception 1", tract_type=TractType.EXCEPTION, calls=_square_calls(50.0))
        result = export_verified_csv(
            _square_calls(), _good_closure(),
            str(tmp_path / "deed.csv"),
            tract_results=[(t1, _good_closure(10000)), (t2, _good_closure(2500))],
        )
        assert isinstance(result, list)
        assert len(result) == 2
        assert "tract1" in result[0].stem
        assert "tract2" in result[1].stem

    def test_multi_tract_files_exist(self, tmp_path: Path):
        t1 = Tract(label="Tract 1", tract_type=TractType.MAIN, calls=_square_calls(100.0))
        t2 = Tract(label="Tract 2", tract_type=TractType.MAIN, calls=_square_calls(50.0))
        paths = export_verified_csv(
            _square_calls(), _good_closure(),
            str(tmp_path / "deed.csv"),
            tract_results=[(t1, _good_closure(10000)), (t2, _good_closure(2500))],
        )
        for p in paths:
            assert p.exists()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest packages/mp-export/tests/test_multi_tract_export.py -v --no-cov`
Expected: FAIL (no `tract_results` param, wrong return type)

**Step 3: Update `export_verified_csv()` to support multi-tract**

In `packages/mp-export/src/mp_export/csv_writer.py`, update the function:

```python
def export_verified_csv(
    calls: list[DeedCall],
    closure_result: ClosureResult,
    output_path: str,
    legal_desc: LegalDescription | None = None,
    *,
    tract_results: list[tuple[Tract, ClosureResult]] | None = None,
    audit_context: AuditContext | None = None,
) -> list[Path]:
    """Export verified CSV(s).

    For multi-tract deeds (tract_results provided), writes one CSV per tract:
    deed_verified_tract1.csv, deed_verified_tract2.csv, etc.

    Returns:
        List of written file paths.
    """
    if not closure_result.is_fully_verified():
        raise ValueError(
            "Cannot export verified CSV: verification checks failed. "
            f"Misclosure: {closure_result.misclosure_ft:.4f} ft, "
            f"Warnings: {len(closure_result.warnings)}"
        )

    output_file = Path(output_path)
    written_paths: list[Path] = []

    if tract_results:
        # Multi-tract: one file per tract
        for i, (tract, tract_result) in enumerate(tract_results, start=1):
            tract_path = output_file.with_stem(f"{output_file.stem}_verified_tract{i}")
            calls_to_csv(tract.calls, str(tract_path))
            written_paths.append(tract_path)
            logger.info("Verified tract CSV exported", path=str(tract_path), tract=tract.label)
    else:
        # Single-tract
        verified_path = output_file.with_stem(output_file.stem + "_verified")
        if legal_desc:
            legal_description_to_csv(legal_desc, str(verified_path))
        else:
            calls_to_csv(calls, str(verified_path))
        written_paths.append(verified_path)
        logger.info("Verified CSV exported", path=str(verified_path))

    # Write verification summary (uses first/summary result)
    summary_path = output_file.with_stem(output_file.stem + "_verified").with_suffix(".verification.txt")
    from mp_verify import get_closure_summary
    summary = get_closure_summary(closure_result)
    with open(summary_path, "w") as f:
        f.write(summary)
    logger.info("Verification summary written", path=str(summary_path))

    # Write audit files if context provided
    if audit_context is not None:
        audit_base = output_file.with_stem(output_file.stem + "_verified")
        audit_json_path = audit_base.with_suffix(".audit.json")
        audit_json_path.write_text(audit_context.model_dump_json(indent=2))
        logger.info("Audit trail written", path=str(audit_json_path))

        from .audit_html import write_report
        audit_html_path = audit_base.with_suffix(".audit.html")
        write_report(audit_context, audit_html_path)
        logger.info("Audit HTML report written", path=str(audit_html_path))

    return written_paths
```

Add import at top:
```python
from mp_models import Tract
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest packages/mp-export/tests/test_multi_tract_export.py -v --no-cov`
Expected: PASS

**Step 5: Run full test suite for regressions**

Run: `uv run pytest --tb=short -q`
Expected: Fix any callers of `export_verified_csv()` that expect `None` return (now returns `list[Path]`)

**Step 6: Commit**

```bash
git add packages/mp-export/src/mp_export/csv_writer.py packages/mp-export/tests/test_multi_tract_export.py
git commit -m "feat(mp-export): add per-tract CSV export with tract_results parameter"
```

---

## Task 7: Wire multi-tract through Pipeline

**Files:**
- Modify: `src/metesparser/pipeline.py:28` (`Pipeline.run`)
- Test: `tests/unit/test_pipeline.py` (extend)

**Step 1: Write the failing test**

Append a new test class to `tests/unit/test_pipeline.py`:

```python
class TestPipelineMultiTract:
    """Pipeline populates tracts on LegalDescription for multi-tract deeds."""

    def test_pipeline_passes_tracts_to_verify(self, monkeypatch):
        """When extract_calls returns tracts, pipeline uses multi-tract verify."""
        from mp_models import DeedCall, Tract, TractType, ClosureResult

        fake_calls = [
            DeedCall(course=1, direction_text="N 45°00' E",
                     bearing_quadrant="N 45°00' E",
                     bearing_azimuth_deg_from_north=45.0, distance_ft=100.0),
        ]
        fake_tract = Tract(label="Tract 1", tract_type=TractType.MAIN, calls=fake_calls)

        # Verify that when tracts exist, verify_closure is called with tracts
        verify_called_with_tracts = []

        original_verify = verify_closure
        def mock_verify(calls, *, tracts=None, **kw):
            verify_called_with_tracts.append(tracts)
            return original_verify(calls, **kw)

        monkeypatch.setattr("src.metesparser.pipeline.verify_closure", mock_verify)
        # ... additional mocking as needed for PDFProcessor
```

(This test is illustrative — the exact mocking depends on how `Pipeline.run()` is structured. The key assertion is that `tracts` is passed to `verify_closure`.)

**Step 2: Update Pipeline.run()**

In `src/metesparser/pipeline.py`, after `process_deed_pdf()` returns and `legal_desc` is extracted:

```python
    # If legal_desc has tracts, use multi-tract verification
    if legal_desc.tracts:
        tract_results = verify_closure(
            legal_desc.all_calls,
            tracts=legal_desc.tracts,
            audit_context=audit_ctx,
        )
        assert isinstance(tract_results, list)

        # Build summary ClosureResult
        main_area = sum(
            r.area_sq_ft for r, t in zip(tract_results, legal_desc.tracts)
            if t.tract_type in (TractType.MAIN, TractType.ADDITION)
        )
        exc_area = sum(
            r.area_sq_ft for r, t in zip(tract_results, legal_desc.tracts)
            if t.tract_type == TractType.EXCEPTION
        )
        net_area = main_area - exc_area
        # ... build summary closure_result
    else:
        closure_result = verify_closure(legal_desc.calls, audit_context=audit_ctx)
```

**Step 3: Run tests**

Run: `uv run pytest tests/unit/test_pipeline.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add src/metesparser/pipeline.py tests/unit/test_pipeline.py
git commit -m "feat(pipeline): wire multi-tract verify and export through Pipeline.run()"
```

---

## Task 8: Sync all changes to monolith modules

**Files:**
- Modify: `src/metesparser/models.py` — add `TractType`, `Tract`, `tracts` field, `all_calls` property
- Modify: `src/metesparser/call_extractor.py` — update `extract_calls()` return type
- Modify: `src/metesparser/closure_checker.py` — add `verify_tract()`, update `verify_closure()`
- Modify: `src/metesparser/csv_builder.py` — update `export_verified_csv()` return type
- Modify: `src/metesparser/pdf_processor.py` — update `extract_calls()` caller

**Step 1: Mirror TractType + Tract to monolith models.py**

In `src/metesparser/models.py`, add after the `ClosureResult` class:

```python
class TractType(str, Enum):
    MAIN = "main"
    EXCEPTION = "exception"
    ADDITION = "addition"
    EASEMENT = "easement"


class Tract(_Model):
    label: str = Field(..., description="Tract label")
    tract_type: TractType = Field(..., description="Type of tract")
    calls: list[DeedCall] = Field(default_factory=list)
    pob_description: str | None = Field(default=None)
    stated_area_sq_ft: FiniteFloat | None = Field(default=None)
    closure_result: ClosureResult | None = Field(default=None)
```

Add `tracts` field and `all_calls` property to monolith `LegalDescription`.

**Step 2: Mirror extract_calls changes to monolith call_extractor.py**

Update `src/metesparser/call_extractor.py` `extract_calls()` to return `tuple[list[DeedCall], list[Tract]]`.

**Step 3: Mirror verify_tract to monolith closure_checker.py**

Add `verify_tract()` classmethod to `ClosureChecker`.

**Step 4: Mirror export changes to monolith csv_builder.py**

Update `export_verified_csv()` to accept `tract_results` and return `list[Path]`.

**Step 5: Update pdf_processor.py callers**

Update all places that call `extract_calls()` to unpack the tuple.

**Step 6: Run full test suite**

Run: `uv run pytest --tb=short -q`
Expected: 996+ passed

**Step 7: Commit**

```bash
git add src/metesparser/models.py src/metesparser/call_extractor.py src/metesparser/closure_checker.py src/metesparser/csv_builder.py src/metesparser/pdf_processor.py
git commit -m "feat(monolith): sync multi-tract support to monolith modules"
```

---

## Task 9: Add cross-package import tests

**Files:**
- Modify: `tests/unit/test_cross_package_imports.py`

**Step 1: Add import tests for new exports**

```python
def test_tract_type_importable():
    from mp_models import TractType
    assert TractType.MAIN == "main"

def test_tract_importable():
    from mp_models import Tract
    assert Tract is not None

def test_split_into_tracts_importable():
    from mp_parse import split_into_tracts
    assert callable(split_into_tracts)

def test_verify_tract_importable():
    from mp_verify import verify_tract
    assert callable(verify_tract)
```

**Step 2: Run and verify**

Run: `uv run pytest tests/unit/test_cross_package_imports.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/unit/test_cross_package_imports.py
git commit -m "test: add cross-package import tests for multi-tract exports"
```

---

## Task 10: Integration test with real deed text

**Files:**
- Create: `tests/unit/test_multi_tract_integration.py`

**Step 1: Write integration tests using sample deed text**

Use text from `219 Berlin Rd` (two BEGINNING blocks: main tract + easement) and `36 Kresson Rd` (EXCEPT clause).

```python
"""Integration tests for multi-tract support with real deed text."""

from mp_parse.calls import extract_calls
from mp_parse.tracts import split_into_tracts
from mp_models import TractType
from mp_verify import verify_closure


class TestRealDeedMultiTract:
    def test_219_berlin_rd_two_tracts(self):
        """219 Berlin Rd has main tract + easement (two BEGINNING blocks)."""
        text = (
            "BEGINNING at a point in the Northerly line of Haddonfield-Berlin Road "
            "(60.00 feet wide at this point)... "  # abbreviated for plan
            # Use actual text from sample deed in implementation
        )
        segments = split_into_tracts(text)
        assert len(segments) >= 2

    def test_except_clause_creates_exception_tract(self):
        """EXCEPT clause creates TractType.EXCEPTION."""
        text = (
            "THENCE North 45 degrees 00 minutes 00 seconds East, a distance of 100.00 feet; "
            "THENCE South 45 degrees 00 minutes 00 seconds East, a distance of 100.00 feet; "
            "THENCE South 45 degrees 00 minutes 00 seconds West, a distance of 100.00 feet; "
            "THENCE North 45 degrees 00 minutes 00 seconds West, a distance of 100.00 feet "
            "to the POINT OF BEGINNING. "
            "EXCEPT BEGINNING at a point THENCE South 10 degrees 00 minutes 00 seconds East, "
            "a distance of 50.00 feet; "
            "THENCE South 10 degrees 00 minutes 00 seconds West, a distance of 50.00 feet; "
            "THENCE North 10 degrees 00 minutes 00 seconds West, a distance of 50.00 feet; "
            "THENCE North 10 degrees 00 minutes 00 seconds East, a distance of 50.00 feet "
            "to the POINT OF BEGINNING."
        )
        calls, tracts = extract_calls(text)
        assert len(tracts) >= 2
        types = {t.tract_type for t in tracts}
        assert TractType.MAIN in types
        assert TractType.EXCEPTION in types
```

**Step 2: Run and verify**

Run: `uv run pytest tests/unit/test_multi_tract_integration.py -v`
Expected: PASS

**Step 3: Run full test suite**

Run: `uv run pytest --tb=short -q`
Expected: All tests pass (996+)

**Step 4: Commit**

```bash
git add tests/unit/test_multi_tract_integration.py
git commit -m "test: add multi-tract integration tests with real deed patterns"
```

---

## Task 11: Final regression check and lint

**Step 1: Run full test suite**

Run: `uv run pytest --tb=short -q`
Expected: All tests pass

**Step 2: Run linter**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: Clean

**Step 3: Run type checker**

Run: `uv run mypy .`
Expected: Clean (or pre-existing issues only)

**Step 4: Run per-package tests**

Run: `for pkg in packages/mp-*/tests/; do uv run pytest "$pkg" -v --no-cov; done`
Expected: All pass

**Step 5: Commit any lint fixes**

```bash
git add -A
git commit -m "chore: lint and format fixes for multi-tract support"
```

---

## Summary

| Task | Package | What |
|------|---------|------|
| 1 | mp-models | `TractType` enum + `Tract` model |
| 2 | mp-models | `tracts` field + `all_calls` property on `LegalDescription` |
| 3 | mp-parse | `split_into_tracts()` function |
| 4 | mp-parse | Wire `split_into_tracts()` into `extract_calls()` |
| 5 | mp-verify | `verify_tract()` + multi-tract `verify_closure()` |
| 6 | mp-export | Per-tract CSV export |
| 7 | pipeline | Wire through `Pipeline.run()` |
| 8 | monolith | Sync all changes to `src/metesparser/` |
| 9 | tests | Cross-package import tests |
| 10 | tests | Integration tests with real deed text |
| 11 | all | Final regression + lint check |
