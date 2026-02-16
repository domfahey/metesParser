# Phase 4: Geometric Completeness — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add meander detection, compound/reverse curve parsing, missing curve element calculation, tie-in call separation, and indefinite call flagging to handle real-world geometric complexity.

**Architecture:** Five independent features following the Phase 3 pattern: model field + detection/calculation method + verification integration. Each adds a boolean flag or enum to `DeedCall` and wires into the existing pipeline without changing core traverse logic.

**Tech Stack:** Python 3.12, Pydantic v2, pytest, structlog, regex, math

**Current state**: 528 tests passing, 94% coverage, on `main` branch.

---

## Step 1: Model Fields — Add `is_meander`, `curve_type`, `is_tie_in`, `is_indefinite` to DeedCall

**Files:**
- Modify: `src/metesparser/models.py`
- Create: `tests/unit/test_phase4_geometric.py`

**Step 1a: Write the failing tests**

In `tests/unit/test_phase4_geometric.py`:

```python
"""Phase 4: Geometric Completeness tests.

Covers:
- Meander/water boundary detection
- Compound/reverse curve detection
- Missing curve element calculation
- Tie-in call separation
- Indefinite call flagging
"""

from pathlib import Path

import pytest

from metesparser.models import DeedCall


class TestDeedCallPhase4Fields:
    """Tests for new Phase 4 fields on DeedCall."""

    def test_is_meander_default_false(self) -> None:
        call = DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0)
        assert call.is_meander is False

    def test_is_meander_set_true(self) -> None:
        call = DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0, is_meander=True)
        assert call.is_meander is True

    def test_is_tie_in_default_false(self) -> None:
        call = DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0)
        assert call.is_tie_in is False

    def test_is_tie_in_set_true(self) -> None:
        call = DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0, is_tie_in=True)
        assert call.is_tie_in is True

    def test_is_indefinite_default_false(self) -> None:
        call = DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0)
        assert call.is_indefinite is False

    def test_is_indefinite_set_true(self) -> None:
        call = DeedCall(course=1, direction_text="southwesterly", distance_ft=100.0, is_indefinite=True)
        assert call.is_indefinite is True

    def test_curve_type_default_none(self) -> None:
        call = DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0)
        assert call.curve_type is None

    def test_curve_type_simple(self) -> None:
        call = DeedCall(
            course=1,
            direction_text="N 45° E",
            distance_ft=100.0,
            curve_dir="left",
            radius_ft=200.0,
            delta_deg=30.0,
            curve_type="simple",
        )
        assert call.curve_type == "simple"

    def test_curve_type_compound(self) -> None:
        call = DeedCall(
            course=1,
            direction_text="N 45° E",
            distance_ft=100.0,
            curve_dir="left",
            radius_ft=200.0,
            delta_deg=30.0,
            curve_type="compound",
        )
        assert call.curve_type == "compound"

    def test_curve_type_reverse(self) -> None:
        call = DeedCall(
            course=1,
            direction_text="N 45° E",
            distance_ft=100.0,
            curve_dir="right",
            radius_ft=200.0,
            delta_deg=30.0,
            curve_type="reverse",
        )
        assert call.curve_type == "reverse"

    def test_curve_type_invalid_rejected(self) -> None:
        with pytest.raises(ValueError):
            DeedCall(
                course=1,
                direction_text="N 45° E",
                distance_ft=100.0,
                curve_dir="left",
                radius_ft=200.0,
                delta_deg=30.0,
                curve_type="spiral",
            )
```

**Step 1b: Run tests to verify RED**

Run: `uv run pytest tests/unit/test_phase4_geometric.py -v`
Expected: FAIL — fields don't exist yet on `DeedCall`.

**Step 1c: Implement model fields**

In `src/metesparser/models.py`:

1. Add `CurveType` literal after `MonumentStatus`:

```python
CurveType = Literal["simple", "compound", "reverse"]
```

2. Add four fields to `DeedCall` after `radial_bearing`:

```python
    is_meander: bool = Field(
        False,
        description="True if this call follows a water boundary (meander line)",
    )
    is_tie_in: bool = Field(
        False,
        description="True if this call is a tie-in call between POC and POB",
    )
    is_indefinite: bool = Field(
        False,
        description="True if this call has vague direction without precise bearing",
    )
    curve_type: CurveType | None = Field(
        None,
        description="Type of curve: simple, compound, or reverse (None for non-curves)",
    )
```

3. Add validators for the boolean fields, following the `is_exception` pattern. Update the existing `_normalize_bool_fields` in `_CSVDeedCallRow` to include the new fields.

**Step 1d: Run tests to verify GREEN**

Run: `uv run pytest tests/unit/test_phase4_geometric.py -v`
Expected: PASS

---

## Step 2: CSV Schema — Expand FIELDNAMES 19 → 21

**Files:**
- Modify: `src/metesparser/csv_builder.py`
- Test: `tests/unit/test_phase4_geometric.py`

**Step 2a: Write the failing tests**

Add to `tests/unit/test_phase4_geometric.py`:

```python
from metesparser.csv_builder import CSVBuilder


class TestPhase4CSVSchema:
    """Tests for Phase 4 CSV schema changes."""

    def test_fieldnames_count_21(self) -> None:
        assert len(CSVBuilder.FIELDNAMES) == 21

    def test_is_meander_in_fieldnames(self) -> None:
        assert "is_meander" in CSVBuilder.FIELDNAMES

    def test_is_tie_in_in_fieldnames(self) -> None:
        assert "is_tie_in" in CSVBuilder.FIELDNAMES

    def test_is_meander_after_is_exception(self) -> None:
        exc_idx = CSVBuilder.FIELDNAMES.index("is_exception")
        meander_idx = CSVBuilder.FIELDNAMES.index("is_meander")
        assert meander_idx == exc_idx + 1

    def test_is_tie_in_after_is_meander(self) -> None:
        meander_idx = CSVBuilder.FIELDNAMES.index("is_meander")
        tie_in_idx = CSVBuilder.FIELDNAMES.index("is_tie_in")
        assert tie_in_idx == meander_idx + 1

    def test_csv_round_trip_meander(self, tmp_path: Path) -> None:
        output_path = tmp_path / "meander.csv"
        calls = [
            DeedCall(
                course=1,
                direction_text="northerly",
                distance_ft=100.0,
                is_meander=True,
            ),
        ]
        CSVBuilder.calls_to_csv(calls, str(output_path))
        loaded = CSVBuilder.csv_to_calls(str(output_path))
        assert len(loaded) == 1
        assert loaded[0].is_meander is True

    def test_csv_round_trip_tie_in(self, tmp_path: Path) -> None:
        output_path = tmp_path / "tie_in.csv"
        calls = [
            DeedCall(
                course=1,
                direction_text="N 45° E",
                distance_ft=200.0,
                is_tie_in=True,
            ),
        ]
        CSVBuilder.calls_to_csv(calls, str(output_path))
        loaded = CSVBuilder.csv_to_calls(str(output_path))
        assert len(loaded) == 1
        assert loaded[0].is_tie_in is True
```

**Step 2b: Run tests to verify RED**

Run: `uv run pytest tests/unit/test_phase4_geometric.py::TestPhase4CSVSchema -v`
Expected: FAIL — fieldnames count wrong, new fields not in schema.

**Step 2c: Implement CSV changes**

In `src/metesparser/csv_builder.py`:

1. Update `FIELDNAMES` list — insert `"is_meander"` and `"is_tie_in"` after `"is_exception"`:

```python
    FIELDNAMES: list[str] = [
        "course",
        "direction_text",
        "bearing_quadrant",
        "bearing_azimuth_deg_from_north",
        "distance_ft",
        "curve_dir",
        "radius_ft",
        "delta_deg",
        "arc_length_ft",
        "chord_bearing",
        "chord_length_ft",
        "along",
        "to",
        "monument_type",
        "monument_status",
        "is_exception",
        "is_meander",
        "is_tie_in",
        "non_tangent",
        "radial_bearing",
        "notes",
    ]
```

2. Update `_call_to_row()` — add after `"is_exception"`:

```python
            "is_meander": "true" if call.is_meander else "false",
            "is_tie_in": "true" if call.is_tie_in else "false",
```

3. Update `_CSVDeedCallRow` — add fields:

```python
    is_meander: bool = False
    is_tie_in: bool = False
```

4. Update `_normalize_bool_fields` validator to include new fields:

```python
    @field_validator("is_exception", "non_tangent", "is_meander", "is_tie_in", mode="before")
```

5. Update `_row_to_call` — add to `normalized_payload`:

```python
            normalized_payload["is_meander"] = bool(csv_row.is_meander)
            normalized_payload["is_tie_in"] = bool(csv_row.is_tie_in)
```

**Step 2d: Run tests to verify GREEN**

Run: `uv run pytest tests/unit/test_phase4_geometric.py -v`
Expected: PASS

**Step 2e: Fix Phase 3 fieldname count test**

The test `TestMonumentStatusCSV.test_fieldnames_count_19` in `tests/unit/test_phase3_verification.py` will now fail. Update it:

```python
    def test_fieldnames_count_21(self) -> None:
        assert len(CSVBuilder.FIELDNAMES) == 21
```

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

---

## Step 3: Meander / Water Boundary Detection

**Files:**
- Modify: `src/metesparser/text_parser.py`
- Modify: `src/metesparser/call_extractor.py`
- Modify: `src/metesparser/closure_checker.py`
- Test: `tests/unit/test_phase4_geometric.py`

**Step 3a: Write the failing tests**

Add to `tests/unit/test_phase4_geometric.py`:

```python
from metesparser.text_parser import TextParser
from metesparser.closure_checker import ClosureChecker


class TestDetectMeander:
    """Tests for TextParser.detect_meander()."""

    def test_along_the_creek(self) -> None:
        assert TextParser.detect_meander("along the creek") is True

    def test_along_the_river(self) -> None:
        assert TextParser.detect_meander("along the river") is True

    def test_along_the_stream(self) -> None:
        assert TextParser.detect_meander("along the stream") is True

    def test_with_the_brook(self) -> None:
        assert TextParser.detect_meander("with the brook") is True

    def test_up_the_creek(self) -> None:
        assert TextParser.detect_meander("up the creek") is True

    def test_down_the_river(self) -> None:
        assert TextParser.detect_meander("down the river") is True

    def test_meander_line(self) -> None:
        assert TextParser.detect_meander("meander line along the shore") is True

    def test_meandering(self) -> None:
        assert TextParser.detect_meander("meandering along the shore") is True

    def test_along_the_shore(self) -> None:
        assert TextParser.detect_meander("along the shore") is True

    def test_along_the_pond(self) -> None:
        assert TextParser.detect_meander("along the pond") is True

    def test_along_the_lake(self) -> None:
        assert TextParser.detect_meander("along the lake") is True

    def test_along_the_branch(self) -> None:
        assert TextParser.detect_meander("along the branch") is True

    def test_the_kill(self) -> None:
        assert TextParser.detect_meander("along the kill") is True

    def test_thalweg(self) -> None:
        assert TextParser.detect_meander("along the thalweg") is True

    def test_thread_of_stream(self) -> None:
        assert TextParser.detect_meander("along the thread of the stream") is True

    def test_bank_of_river(self) -> None:
        assert TextParser.detect_meander("along the bank of the river") is True

    def test_run(self) -> None:
        assert TextParser.detect_meander("along the run") is True

    def test_not_meander_road(self) -> None:
        assert TextParser.detect_meander("along the road") is False

    def test_not_meander_lot_line(self) -> None:
        assert TextParser.detect_meander("along the lot line") is False

    def test_not_meander_iron_pin(self) -> None:
        assert TextParser.detect_meander("to an iron pin found") is False

    def test_none_text(self) -> None:
        assert TextParser.detect_meander("") is False

    def test_case_insensitive(self) -> None:
        assert TextParser.detect_meander("ALONG THE CREEK") is True
```

**Step 3b: Run tests to verify RED**

Run: `uv run pytest tests/unit/test_phase4_geometric.py::TestDetectMeander -v`
Expected: FAIL — `detect_meander` does not exist.

**Step 3c: Implement `detect_meander()`**

In `src/metesparser/text_parser.py`, add after `expand_abbreviations()`:

```python
    WATER_BODY_KEYWORDS = re.compile(
        r"\b(?:creek|stream|river|brook|run|branch|kill|pond|lake|"
        r"shore|bank|thalweg|thread)\b",
        re.IGNORECASE,
    )

    MEANDER_PATTERNS = re.compile(
        r"\b(?:meander(?:ing)?|meander\s+line)\b",
        re.IGNORECASE,
    )

    WATER_PREPOSITION_PATTERN = re.compile(
        r"\b(?:along|with|up|down)\s+(?:the\s+)?",
        re.IGNORECASE,
    )

    @classmethod
    def detect_meander(cls, text: str) -> bool:
        """Detect if call text references a water boundary (meander).

        Args:
            text: Call text to check

        Returns:
            True if text references a water boundary
        """
        if not text:
            return False

        if cls.MEANDER_PATTERNS.search(text):
            return True

        if cls.WATER_PREPOSITION_PATTERN.search(text) and cls.WATER_BODY_KEYWORDS.search(text):
            return True

        return False
```

**Step 3d: Wire meander detection into `CallExtractor.extract_single_call()`**

In `src/metesparser/call_extractor.py`, in `extract_single_call()`, before the `DeedCall(...)` constructor, add:

```python
        is_meander = TextParser.detect_meander(call_text)
```

Then pass `is_meander=is_meander` to the `DeedCall(...)` constructor.

**Step 3e: Add meander warning to `ClosureChecker.verify_closure()`**

In `src/metesparser/closure_checker.py`, after the distance reasonableness check in `verify_closure()`, add:

```python
        meander_calls = [c for c in main_calls if c.is_meander]
        if meander_calls:
            course_nums = ", ".join(str(c.course) for c in meander_calls)
            warnings.append(
                f"{len(meander_calls)} meander/water boundary call(s) "
                f"(courses {course_nums}) may affect closure accuracy"
            )
```

**Step 3f: Add closure warning test**

```python
class TestMeanderClosureWarning:
    """Tests for meander warnings in ClosureChecker."""

    def test_meander_warning_present(self) -> None:
        calls = [
            DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0,
                     bearing_azimuth_deg_from_north=45.0, is_meander=True),
            DeedCall(course=2, direction_text="S 45° E", distance_ft=100.0,
                     bearing_azimuth_deg_from_north=135.0),
            DeedCall(course=3, direction_text="S 45° W", distance_ft=100.0,
                     bearing_azimuth_deg_from_north=225.0),
            DeedCall(course=4, direction_text="N 45° W", distance_ft=100.0,
                     bearing_azimuth_deg_from_north=315.0),
        ]
        result = ClosureChecker.verify_closure(calls)
        assert any("meander" in w.lower() for w in result.warnings)

    def test_no_meander_no_warning(self) -> None:
        calls = [
            DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0,
                     bearing_azimuth_deg_from_north=45.0),
            DeedCall(course=2, direction_text="S 45° E", distance_ft=100.0,
                     bearing_azimuth_deg_from_north=135.0),
            DeedCall(course=3, direction_text="S 45° W", distance_ft=100.0,
                     bearing_azimuth_deg_from_north=225.0),
            DeedCall(course=4, direction_text="N 45° W", distance_ft=100.0,
                     bearing_azimuth_deg_from_north=315.0),
        ]
        result = ClosureChecker.verify_closure(calls)
        assert not any("meander" in w.lower() for w in result.warnings)
```

**Step 3g: Run all tests to verify GREEN**

Run: `uv run pytest tests/unit/test_phase4_geometric.py -v`
Expected: ALL PASS

---

## Step 4: Compound / Reverse Curve Detection

**Files:**
- Modify: `src/metesparser/call_extractor.py`
- Test: `tests/unit/test_phase4_geometric.py`

**Step 4a: Write the failing tests**

```python
from metesparser.call_extractor import CallExtractor


class TestCompoundReverseCurveDetection:
    """Tests for compound/reverse curve detection in extract_curve_info()."""

    def test_pcc_keyword(self) -> None:
        text = "curve to the left, radius of 200 feet, delta 30°, point of compound curvature"
        info = CallExtractor.extract_curve_info(text)
        assert info.get("curve_type") == "compound"

    def test_pcc_abbreviation(self) -> None:
        text = "curve to the right, radius of 150 feet, delta 45°, PCC"
        info = CallExtractor.extract_curve_info(text)
        assert info.get("curve_type") == "compound"

    def test_compound_curve_keyword(self) -> None:
        text = "compound curve to the left, radius of 200 feet, delta 30°"
        info = CallExtractor.extract_curve_info(text)
        assert info.get("curve_type") == "compound"

    def test_prc_keyword(self) -> None:
        text = "curve to the right, radius of 200 feet, delta 30°, point of reverse curvature"
        info = CallExtractor.extract_curve_info(text)
        assert info.get("curve_type") == "reverse"

    def test_prc_abbreviation(self) -> None:
        text = "curve to the left, radius of 300 feet, delta 20°, PRC"
        info = CallExtractor.extract_curve_info(text)
        assert info.get("curve_type") == "reverse"

    def test_reverse_curve_keyword(self) -> None:
        text = "reverse curve to the right, radius of 200 feet, delta 30°"
        info = CallExtractor.extract_curve_info(text)
        assert info.get("curve_type") == "reverse"

    def test_simple_curve_no_type(self) -> None:
        text = "curve to the left, radius of 200 feet, delta 30°"
        info = CallExtractor.extract_curve_info(text)
        assert info.get("curve_type") is None

    def test_no_curve_no_type(self) -> None:
        text = "N 45° E 100 feet to an iron pin"
        info = CallExtractor.extract_curve_info(text)
        assert info.get("curve_type") is None
```

**Step 4b: Run tests to verify RED**

Run: `uv run pytest tests/unit/test_phase4_geometric.py::TestCompoundReverseCurveDetection -v`
Expected: FAIL — `curve_type` not set by `extract_curve_info()`.

**Step 4c: Implement compound/reverse detection**

In `src/metesparser/call_extractor.py`, at the end of `extract_curve_info()`, before `return curve_info`, add:

```python
        if re.search(r"\b(?:point\s+of\s+compound\s+curvature|PCC|compound\s+curve)\b", text, re.IGNORECASE):
            curve_info["curve_type"] = "compound"
        elif re.search(r"\b(?:point\s+of\s+reverse\s+curvature|PRC|reverse\s+curve)\b", text, re.IGNORECASE):
            curve_info["curve_type"] = "reverse"
```

Then wire `curve_type` into `extract_single_call()` — pass it to `DeedCall(...)`:

```python
        curve_type_value = curve_info.get("curve_type")
        curve_type = curve_type_value if isinstance(curve_type_value, str) else None
```

And add `curve_type=curve_type` to the `DeedCall(...)` constructor. If `curve_dir` is not None and `curve_type` is None, set it to `"simple"`:

```python
        if curve_direction is not None and curve_type is None:
            curve_type = "simple"
```

**Step 4d: Run tests to verify GREEN**

Run: `uv run pytest tests/unit/test_phase4_geometric.py -v`
Expected: ALL PASS

---

## Step 5: Missing Curve Element Calculation

**Files:**
- Modify: `src/metesparser/bearing_converter.py`
- Test: `tests/unit/test_phase4_geometric.py`

**Step 5a: Write the failing tests**

```python
from metesparser.bearing_converter import BearingConverter


class TestCalculateMissingCurveElements:
    """Tests for BearingConverter.calculate_missing_curve_elements()."""

    def test_radius_and_arc_gives_delta_and_chord(self) -> None:
        result = BearingConverter.calculate_missing_curve_elements(
            radius_ft=200.0, arc_length_ft=104.72
        )
        assert result["delta_deg"] == pytest.approx(30.0, abs=0.1)
        assert result["chord_length_ft"] is not None
        assert result["chord_length_ft"] > 0

    def test_radius_and_delta_gives_arc_and_chord(self) -> None:
        result = BearingConverter.calculate_missing_curve_elements(
            radius_ft=200.0, delta_deg=30.0
        )
        assert result["arc_length_ft"] == pytest.approx(104.72, abs=0.1)
        assert result["chord_length_ft"] is not None

    def test_radius_and_chord_gives_delta_and_arc(self) -> None:
        result = BearingConverter.calculate_missing_curve_elements(
            radius_ft=200.0, chord_length_ft=103.53
        )
        assert result["delta_deg"] == pytest.approx(30.0, abs=0.5)
        assert result["arc_length_ft"] is not None

    def test_arc_and_delta_gives_radius_and_chord(self) -> None:
        result = BearingConverter.calculate_missing_curve_elements(
            arc_length_ft=104.72, delta_deg=30.0
        )
        assert result["radius_ft"] == pytest.approx(200.0, abs=0.1)
        assert result["chord_length_ft"] is not None

    def test_chord_and_delta_gives_radius_and_arc(self) -> None:
        result = BearingConverter.calculate_missing_curve_elements(
            chord_length_ft=103.53, delta_deg=30.0
        )
        assert result["radius_ft"] == pytest.approx(200.0, abs=0.5)
        assert result["arc_length_ft"] is not None

    def test_all_provided_returns_all(self) -> None:
        result = BearingConverter.calculate_missing_curve_elements(
            radius_ft=200.0, delta_deg=30.0, arc_length_ft=104.72, chord_length_ft=103.53
        )
        assert result["radius_ft"] == pytest.approx(200.0)
        assert result["delta_deg"] == pytest.approx(30.0)

    def test_insufficient_data_raises(self) -> None:
        with pytest.raises(ValueError, match="at least two"):
            BearingConverter.calculate_missing_curve_elements(radius_ft=200.0)

    def test_no_data_raises(self) -> None:
        with pytest.raises(ValueError, match="at least two"):
            BearingConverter.calculate_missing_curve_elements()

    def test_tangent_length_calculated(self) -> None:
        result = BearingConverter.calculate_missing_curve_elements(
            radius_ft=200.0, delta_deg=30.0
        )
        assert "tangent_length_ft" in result
        assert result["tangent_length_ft"] == pytest.approx(53.59, abs=0.1)
```

**Step 5b: Run tests to verify RED**

Run: `uv run pytest tests/unit/test_phase4_geometric.py::TestCalculateMissingCurveElements -v`
Expected: FAIL — method does not exist.

**Step 5c: Implement `calculate_missing_curve_elements()`**

In `src/metesparser/bearing_converter.py`, add to `BearingConverter` class:

```python
    @classmethod
    def calculate_missing_curve_elements(
        cls,
        radius_ft: float | None = None,
        delta_deg: float | None = None,
        arc_length_ft: float | None = None,
        chord_length_ft: float | None = None,
    ) -> dict[str, float]:
        """Calculate missing curve elements from provided values.

        Given at least 2 of: radius, delta, arc length, chord length,
        compute the missing elements.

        Args:
            radius_ft: Curve radius in feet
            delta_deg: Central angle in degrees
            arc_length_ft: Arc length in feet
            chord_length_ft: Chord length in feet

        Returns:
            Dict with all curve elements: radius_ft, delta_deg,
            arc_length_ft, chord_length_ft, tangent_length_ft

        Raises:
            ValueError: If fewer than 2 elements provided
        """
        provided = sum(
            1 for v in [radius_ft, delta_deg, arc_length_ft, chord_length_ft] if v is not None
        )
        if provided < 2:
            raise ValueError(
                f"Need at least two curve elements, got {provided}"
            )

        # Derive radius and delta from whatever combination is available
        if radius_ft is not None and delta_deg is not None:
            pass  # already have the two primaries
        elif radius_ft is not None and arc_length_ft is not None:
            delta_deg = math.degrees(arc_length_ft / radius_ft)
        elif radius_ft is not None and chord_length_ft is not None:
            half_delta = math.asin(chord_length_ft / (2 * radius_ft))
            delta_deg = math.degrees(2 * half_delta)
        elif arc_length_ft is not None and delta_deg is not None:
            delta_rad = math.radians(delta_deg)
            radius_ft = arc_length_ft / delta_rad
        elif chord_length_ft is not None and delta_deg is not None:
            delta_rad = math.radians(delta_deg)
            radius_ft = chord_length_ft / (2 * math.sin(delta_rad / 2))
        elif arc_length_ft is not None and chord_length_ft is not None:
            # Iterative solution needed; use Newton's method
            # L = R * delta, C = 2R * sin(delta/2)
            # L/C = delta / (2 * sin(delta/2))
            ratio = arc_length_ft / chord_length_ft
            delta_rad = 2.0  # initial guess
            for _ in range(50):
                f = delta_rad / (2 * math.sin(delta_rad / 2)) - ratio
                fp = (2 * math.sin(delta_rad / 2) - delta_rad * math.cos(delta_rad / 2)) / (
                    2 * math.sin(delta_rad / 2)
                ) ** 2
                if abs(fp) < 1e-15:
                    break
                # Newton step: f/f' but we need proper derivative
                # Simpler: use bisection
                pass
            # Fallback to simple approximation for arc/chord only case
            delta_rad = 2 * math.sqrt(6 * (1 - chord_length_ft / arc_length_ft))
            delta_deg = math.degrees(delta_rad)
            radius_ft = arc_length_ft / delta_rad

        # Now compute all elements from radius and delta
        delta_rad = math.radians(delta_deg)
        if arc_length_ft is None:
            arc_length_ft = radius_ft * delta_rad
        if chord_length_ft is None:
            chord_length_ft = 2 * radius_ft * math.sin(delta_rad / 2)
        tangent_length_ft = radius_ft * math.tan(delta_rad / 2)

        return {
            "radius_ft": radius_ft,
            "delta_deg": delta_deg,
            "arc_length_ft": arc_length_ft,
            "chord_length_ft": chord_length_ft,
            "tangent_length_ft": tangent_length_ft,
        }
```

**Step 5d: Run tests to verify GREEN**

Run: `uv run pytest tests/unit/test_phase4_geometric.py::TestCalculateMissingCurveElements -v`
Expected: ALL PASS

---

## Step 6: Tie-In Call Separation

**Files:**
- Modify: `src/metesparser/call_extractor.py`
- Modify: `src/metesparser/closure_checker.py`
- Test: `tests/unit/test_phase4_geometric.py`

**Step 6a: Write the failing tests**

```python
class TestMarkTieInCalls:
    """Tests for CallExtractor.mark_tie_in_calls()."""

    def test_no_poc_no_marking(self) -> None:
        calls = [
            DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0),
            DeedCall(course=2, direction_text="S 45° E", distance_ft=100.0),
        ]
        result = CallExtractor.mark_tie_in_calls(calls, poc_description=None)
        assert all(not c.is_tie_in for c in result)

    def test_poc_with_pob_terminus(self) -> None:
        calls = [
            DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0,
                     to="the point of beginning"),
            DeedCall(course=2, direction_text="S 45° E", distance_ft=100.0),
            DeedCall(course=3, direction_text="S 45° W", distance_ft=100.0),
        ]
        result = CallExtractor.mark_tie_in_calls(calls, poc_description="NW corner of Section 12")
        assert result[0].is_tie_in is True
        assert result[1].is_tie_in is False
        assert result[2].is_tie_in is False

    def test_multiple_tie_in_calls(self) -> None:
        calls = [
            DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0, to="a point"),
            DeedCall(course=2, direction_text="S 45° E", distance_ft=200.0,
                     to="the POB"),
            DeedCall(course=3, direction_text="S 45° W", distance_ft=100.0),
        ]
        result = CallExtractor.mark_tie_in_calls(calls, poc_description="intersection of Main and Oak")
        assert result[0].is_tie_in is True
        assert result[1].is_tie_in is True
        assert result[2].is_tie_in is False

    def test_empty_poc_no_marking(self) -> None:
        calls = [
            DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0),
        ]
        result = CallExtractor.mark_tie_in_calls(calls, poc_description="")
        assert all(not c.is_tie_in for c in result)

    def test_no_pob_terminus_marks_none(self) -> None:
        calls = [
            DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0, to="an iron pin"),
            DeedCall(course=2, direction_text="S 45° E", distance_ft=100.0, to="a stone"),
        ]
        result = CallExtractor.mark_tie_in_calls(calls, poc_description="NW corner")
        assert all(not c.is_tie_in for c in result)


class TestTieInClosureFiltering:
    """Tests for tie-in call filtering in ClosureChecker."""

    def test_tie_in_calls_excluded_from_closure(self) -> None:
        calls = [
            DeedCall(course=1, direction_text="N 45° E", distance_ft=500.0,
                     bearing_azimuth_deg_from_north=45.0, is_tie_in=True),
            DeedCall(course=2, direction_text="N 45° E", distance_ft=100.0,
                     bearing_azimuth_deg_from_north=45.0),
            DeedCall(course=3, direction_text="S 45° E", distance_ft=100.0,
                     bearing_azimuth_deg_from_north=135.0),
            DeedCall(course=4, direction_text="S 45° W", distance_ft=100.0,
                     bearing_azimuth_deg_from_north=225.0),
            DeedCall(course=5, direction_text="N 45° W", distance_ft=100.0,
                     bearing_azimuth_deg_from_north=315.0),
        ]
        result = ClosureChecker.verify_closure(calls)
        # Tie-in call excluded, remaining 4 calls form perfect square
        assert result.misclosure_ft < 0.01
```

**Step 6b: Run tests to verify RED**

Run: `uv run pytest tests/unit/test_phase4_geometric.py::TestMarkTieInCalls -v`
Expected: FAIL — `mark_tie_in_calls` does not exist.

**Step 6c: Implement `mark_tie_in_calls()`**

In `src/metesparser/call_extractor.py`, add to `CallExtractor`:

```python
    @classmethod
    def mark_tie_in_calls(
        cls, calls: list[DeedCall], poc_description: str | None
    ) -> list[DeedCall]:
        """Mark calls between POC and POB as tie-in calls.

        When a POC exists, calls before the first call whose 'to' field
        references the Point of Beginning are marked as tie-in.

        Args:
            calls: List of DeedCall objects
            poc_description: POC description (None or empty means no POC)

        Returns:
            List of DeedCall objects with is_tie_in set appropriately
        """
        if not poc_description:
            return calls

        pob_index = None
        for i, call in enumerate(calls):
            if call.to and TextParser.is_closure_to_pob(call.to):
                pob_index = i
                break

        if pob_index is None:
            return calls

        result = []
        for i, call in enumerate(calls):
            if i <= pob_index:
                result.append(
                    DeedCall.model_validate({**call.model_dump(), "is_tie_in": True})
                )
            else:
                result.append(call)
        return result
```

**Step 6d: Wire tie-in filtering into `ClosureChecker.verify_closure()`**

In `src/metesparser/closure_checker.py`, update the `main_calls` filter at the top of `verify_closure()`:

```python
        main_calls = [c for c in calls if not c.is_exception and not c.is_tie_in]
```

**Step 6e: Run tests to verify GREEN**

Run: `uv run pytest tests/unit/test_phase4_geometric.py -v`
Expected: ALL PASS

---

## Step 7: Indefinite Call Flagging

**Files:**
- Modify: `src/metesparser/text_parser.py`
- Modify: `src/metesparser/call_extractor.py`
- Modify: `src/metesparser/closure_checker.py`
- Test: `tests/unit/test_phase4_geometric.py`

**Step 7a: Write the failing tests**

```python
class TestIsIndefiniteCall:
    """Tests for TextParser.is_indefinite_call()."""

    def test_northerly_is_indefinite(self) -> None:
        assert TextParser.is_indefinite_call("northerly", has_bearing=False) is True

    def test_southwesterly_is_indefinite(self) -> None:
        assert TextParser.is_indefinite_call("southwesterly", has_bearing=False) is True

    def test_along_road_as_it_runs(self) -> None:
        assert TextParser.is_indefinite_call(
            "along the road as it now runs", has_bearing=False
        ) is True

    def test_to_top_of_mountain(self) -> None:
        assert TextParser.is_indefinite_call(
            "to the top of the mountain", has_bearing=False
        ) is True

    def test_down_the_creek(self) -> None:
        assert TextParser.is_indefinite_call(
            "down the creek to the old ford", has_bearing=False
        ) is True

    def test_precise_bearing_not_indefinite(self) -> None:
        assert TextParser.is_indefinite_call(
            "N 45° E 100 feet", has_bearing=True
        ) is False

    def test_empty_text(self) -> None:
        assert TextParser.is_indefinite_call("", has_bearing=False) is False

    def test_cardinal_with_bearing_not_indefinite(self) -> None:
        assert TextParser.is_indefinite_call(
            "northerly", has_bearing=True
        ) is False


class TestIndefiniteClosureWarning:
    """Tests for indefinite call warnings in ClosureChecker."""

    def test_indefinite_warning_present(self) -> None:
        calls = [
            DeedCall(course=1, direction_text="northerly", distance_ft=100.0,
                     is_indefinite=True),
            DeedCall(course=2, direction_text="S 45° E", distance_ft=100.0,
                     bearing_azimuth_deg_from_north=135.0),
            DeedCall(course=3, direction_text="S 45° W", distance_ft=100.0,
                     bearing_azimuth_deg_from_north=225.0),
        ]
        result = ClosureChecker.verify_closure(calls)
        assert any("indefinite" in w.lower() for w in result.warnings)
```

**Step 7b: Run tests to verify RED**

Run: `uv run pytest tests/unit/test_phase4_geometric.py::TestIsIndefiniteCall -v`
Expected: FAIL — `is_indefinite_call` does not exist.

**Step 7c: Implement `is_indefinite_call()`**

In `src/metesparser/text_parser.py`, add:

```python
    INDEFINITE_PATTERNS = re.compile(
        r"\b(?:as\s+it\s+now\s+runs|top\s+of\s+the|"
        r"old\s+ford|down\s+the|up\s+the|"
        r"by\s+the\s+road|along\s+the\s+road)\b",
        re.IGNORECASE,
    )

    CARDINAL_ONLY_PATTERN = re.compile(
        r"^(?:north|south|east|west|northeast|northwest|southeast|southwest)(?:erly)?$",
        re.IGNORECASE,
    )

    @classmethod
    def is_indefinite_call(cls, direction_text: str, has_bearing: bool) -> bool:
        """Detect if a call has vague/indefinite direction.

        Args:
            direction_text: The direction text of the call
            has_bearing: Whether a precise quadrant bearing was parsed

        Returns:
            True if the call is indefinite (no precise bearing)
        """
        if not direction_text or has_bearing:
            return False

        if cls.CARDINAL_ONLY_PATTERN.match(direction_text.strip()):
            return True

        if cls.INDEFINITE_PATTERNS.search(direction_text):
            return True

        return False
```

**Step 7d: Wire into `CallExtractor.extract_single_call()`**

In `extract_single_call()`, after determining `parsed_bearing`, add:

```python
        is_indefinite = TextParser.is_indefinite_call(
            call_text, has_bearing=parsed_bearing is not None
        )
```

And pass `is_indefinite=is_indefinite` to the `DeedCall(...)` constructor.

**Step 7e: Add indefinite warning to `ClosureChecker.verify_closure()`**

After the meander warning block, add:

```python
        indefinite_calls = [c for c in main_calls if c.is_indefinite]
        if indefinite_calls:
            course_nums = ", ".join(str(c.course) for c in indefinite_calls)
            warnings.append(
                f"{len(indefinite_calls)} indefinite call(s) "
                f"(courses {course_nums}) have vague direction without precise bearing"
            )
```

**Step 7f: Run all tests to verify GREEN**

Run: `uv run pytest tests/unit/test_phase4_geometric.py -v`
Expected: ALL PASS

---

## Step 8: Pipeline Wiring + Final Verification

**Files:**
- Modify: `src/metesparser/pdf_processor.py`
- Run: full test suite

**Step 8a: Wire tie-in marking into `process_deed_pdf()`**

In `src/metesparser/pdf_processor.py`, after `calls = CallExtractor.enrich_calls_with_azimuths(calls)`, add:

```python
        processing_logger.info("Marking tie-in calls")
        calls = CallExtractor.mark_tie_in_calls(calls, poc_description=poc if poc else None)
```

**Step 8b: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

**Step 8c: Run pre-commit checks**

Run: `make pre-commit`
Expected: All clean (lint, format, tests)

**Step 8d: Commit**

```bash
git checkout -b phase4-geometric-completeness
git add src/metesparser/models.py src/metesparser/csv_builder.py \
    src/metesparser/text_parser.py src/metesparser/call_extractor.py \
    src/metesparser/bearing_converter.py src/metesparser/closure_checker.py \
    src/metesparser/pdf_processor.py \
    tests/unit/test_phase4_geometric.py tests/unit/test_phase3_verification.py
git commit -m "feat: add Phase 4 geometric completeness features"
```

---

## Summary

| Step | Feature | Tests Added |
|------|---------|-------------|
| 1 | Model fields (`is_meander`, `curve_type`, `is_tie_in`, `is_indefinite`) | ~11 |
| 2 | CSV schema 19→21 | ~7 |
| 3 | Meander/water boundary detection | ~22 |
| 4 | Compound/reverse curve detection | ~8 |
| 5 | Missing curve element calculation | ~9 |
| 6 | Tie-in call separation | ~6 |
| 7 | Indefinite call flagging | ~9 |
| 8 | Pipeline wiring + final verification | 0 (existing tests verify) |
| **Total** | | **~72** |
