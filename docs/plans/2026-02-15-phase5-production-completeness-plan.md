# Phase 5: Production Completeness — TDD Implementation Plan

> Historical snapshot: This plan/design document captures implementation context on its date. It may not reflect current code, defaults, test counts, or workflow state.


> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close all remaining gaps between METES_AND_BOUNDS_REFERENCE.md and parser capabilities. Adds curve completeness, deed language richness, historical deed support, and lightweight COGO metadata.

**Architecture:** Ten independent features wired into existing pipeline. Each adds parsing/verification capability without changing core traverse logic. CSV schema stays at 21 fields — new data is metadata on LegalDescription, not per-call.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, structlog, regex

**Current state:** 619 tests passing, 94% coverage, on `main` branch.

---

## Step 1: Models — All New Types and Fields

**Files:**
- Modify: `src/metesparser/models.py`
- Create: `tests/unit/test_phase5_production.py`

Add all new model types and fields needed by Phase 5 features.

### 1a. Write failing tests for model changes

Add to `tests/unit/test_phase5_production.py`:

```python
"""Phase 5: Production Completeness tests.

Covers:
- Degree of curvature parsing
- Extended curve properties (T, E, M)
- Natural monument classification
- 32-point compass system
- Clause taxonomy
- Subdivision lot/block references
- TPOB/RPOB recognition
- Witness trees
- Spiral curve detection
- State Plane metadata
"""

import math

import pytest

from metesparser.models import DeedCall, LegalDescription


class TestPhase5ModelChanges:
    """Tests for Phase 5 model additions."""

    # --- MonumentType additions ---

    def test_monument_type_tree(self) -> None:
        call = DeedCall(
            course=1, direction_text="N 45° E", distance_ft=100.0, monument_type="tree"
        )
        assert call.monument_type == "tree"

    def test_monument_type_rock(self) -> None:
        call = DeedCall(
            course=1, direction_text="N 45° E", distance_ft=100.0, monument_type="rock"
        )
        assert call.monument_type == "rock"

    def test_monument_type_natural_feature(self) -> None:
        call = DeedCall(
            course=1, direction_text="N 45° E", distance_ft=100.0, monument_type="natural_feature"
        )
        assert call.monument_type == "natural_feature"

    # --- CurveType addition ---

    def test_curve_type_spiral(self) -> None:
        call = DeedCall(
            course=1,
            direction_text="N 45° E",
            distance_ft=100.0,
            curve_dir="right",
            radius_ft=500.0,
            delta_deg=30.0,
            curve_type="spiral",
        )
        assert call.curve_type == "spiral"

    # --- DeedClause model ---

    def test_deed_clause_reservation(self) -> None:
        from metesparser.models import DeedClause

        clause = DeedClause(clause_type="reservation", text="RESERVING unto the Grantor a right of way")
        assert clause.clause_type == "reservation"
        assert "RESERVING" in clause.text

    def test_deed_clause_subject_to(self) -> None:
        from metesparser.models import DeedClause

        clause = DeedClause(clause_type="subject_to", text="SUBJECT TO existing easements")
        assert clause.clause_type == "subject_to"

    def test_deed_clause_together_with(self) -> None:
        from metesparser.models import DeedClause

        clause = DeedClause(clause_type="together_with", text="TOGETHER WITH a right of ingress")
        assert clause.clause_type == "together_with"

    def test_deed_clause_rejects_invalid_type(self) -> None:
        from metesparser.models import DeedClause

        with pytest.raises(Exception):
            DeedClause(clause_type="invalid", text="some text")

    def test_deed_clause_forbids_extra(self) -> None:
        from metesparser.models import DeedClause

        with pytest.raises(Exception):
            DeedClause(clause_type="reservation", text="text", foo="bar")

    # --- SubdivisionReference model ---

    def test_subdivision_reference_full(self) -> None:
        from metesparser.models import SubdivisionReference

        ref = SubdivisionReference(
            lot="15",
            block="3",
            subdivision_name="PENNBROOK ESTATES",
            plat_book="14",
            plat_page="22",
        )
        assert ref.lot == "15"
        assert ref.block == "3"
        assert ref.subdivision_name == "PENNBROOK ESTATES"
        assert ref.plat_book == "14"
        assert ref.plat_page == "22"

    def test_subdivision_reference_partial(self) -> None:
        from metesparser.models import SubdivisionReference

        ref = SubdivisionReference(lot="5", subdivision_name="OAKDALE")
        assert ref.lot == "5"
        assert ref.block is None
        assert ref.plat_book is None

    def test_subdivision_reference_forbids_extra(self) -> None:
        from metesparser.models import SubdivisionReference

        with pytest.raises(Exception):
            SubdivisionReference(lot="1", foo="bar")

    # --- LegalDescription new fields ---

    def test_legal_description_clauses_default_empty(self) -> None:
        ld = LegalDescription(calls=[], distance_unit="feet")
        assert ld.clauses == []

    def test_legal_description_clauses_populated(self) -> None:
        from metesparser.models import DeedClause

        clause = DeedClause(clause_type="reservation", text="RESERVING a right of way")
        ld = LegalDescription(calls=[], distance_unit="feet", clauses=[clause])
        assert len(ld.clauses) == 1
        assert ld.clauses[0].clause_type == "reservation"

    def test_legal_description_subdivision_ref_default_none(self) -> None:
        ld = LegalDescription(calls=[], distance_unit="feet")
        assert ld.subdivision_ref is None

    def test_legal_description_subdivision_ref_populated(self) -> None:
        from metesparser.models import SubdivisionReference

        ref = SubdivisionReference(lot="10", block="2", subdivision_name="OAK PARK")
        ld = LegalDescription(calls=[], distance_unit="feet", subdivision_ref=ref)
        assert ld.subdivision_ref is not None
        assert ld.subdivision_ref.lot == "10"

    def test_legal_description_witness_trees_default_empty(self) -> None:
        ld = LegalDescription(calls=[], distance_unit="feet")
        assert ld.witness_trees == []

    def test_legal_description_witness_trees_populated(self) -> None:
        ld = LegalDescription(
            calls=[],
            distance_unit="feet",
            witness_trees=["a white oak, 14 inches diameter, bears N 35° W, 12 links distant"],
        )
        assert len(ld.witness_trees) == 1

    def test_legal_description_coordinate_system_default_none(self) -> None:
        ld = LegalDescription(calls=[], distance_unit="feet")
        assert ld.coordinate_system is None

    def test_legal_description_coordinate_system_populated(self) -> None:
        ld = LegalDescription(
            calls=[],
            distance_unit="feet",
            coordinate_system="State Plane Coordinate System, Texas South Central Zone",
        )
        assert ld.coordinate_system is not None

    def test_legal_description_fips_code_default_none(self) -> None:
        ld = LegalDescription(calls=[], distance_unit="feet")
        assert ld.fips_code is None

    def test_legal_description_fips_code_populated(self) -> None:
        ld = LegalDescription(calls=[], distance_unit="feet", fips_code="4204")
        assert ld.fips_code == "4204"
```

### 1b. Run tests to verify they fail

```bash
uv run pytest tests/unit/test_phase5_production.py -v
```

Expected: Multiple failures — `"tree"`, `"rock"`, `"natural_feature"` not valid MonumentType literals; `"spiral"` not valid CurveType; `DeedClause` and `SubdivisionReference` classes don't exist; `clauses`, `subdivision_ref`, `witness_trees`, `coordinate_system`, `fips_code` fields don't exist on LegalDescription.

### 1c. Implement model changes

Modify `src/metesparser/models.py`:

1. Add `"tree"`, `"rock"`, `"natural_feature"` to `MonumentType` literal (after `"txdot_monument"`, before `"other"`)
2. Add `"spiral"` to `CurveType` literal: `Literal["simple", "compound", "reverse", "spiral"]`
3. Add `DeedClause` class (after `_Model`, before `DeedCall`):

```python
class DeedClause(_Model):
    """A deed clause (reservation, subject-to, or together-with)."""

    clause_type: Literal["reservation", "subject_to", "together_with"]
    text: str = Field(..., min_length=1, description="Verbatim clause text from deed")
```

4. Add `SubdivisionReference` class (after `DeedClause`):

```python
class SubdivisionReference(_Model):
    """Subdivision lot/block reference from a deed."""

    lot: str | None = None
    block: str | None = None
    subdivision_name: str | None = None
    plat_book: str | None = None
    plat_page: str | None = None
```

5. Add new fields to `LegalDescription` (after `stated_area_approximate`):

```python
clauses: list[DeedClause] = Field(default_factory=list, description="Deed clauses (reservations, subject-to, together-with)")
subdivision_ref: SubdivisionReference | None = Field(None, description="Subdivision lot/block reference")
witness_trees: list[str] = Field(default_factory=list, description="Witness tree/reference mark descriptions (verbatim)")
coordinate_system: str | None = Field(None, description="State Plane or other coordinate system reference")
fips_code: str | None = Field(None, description="FIPS zone code for State Plane coordinates")
```

6. Update the `Literal` import to include the `DeedClause` type alias import.

### 1d. Run tests to verify they pass

```bash
uv run pytest tests/unit/test_phase5_production.py -v
```

Expected: All Phase 5 model tests PASS.

### 1e. Run full test suite

```bash
uv run pytest -v
```

Expected: 619+ tests pass (no regressions).

### 1f. Commit

```bash
git add tests/unit/test_phase5_production.py src/metesparser/models.py
git commit -m "feat(models): add Phase 5 types — DeedClause, SubdivisionReference, natural monuments, spiral curves

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Step 2: Degree of Curvature — bearing_converter + call_extractor

**Files:**
- Modify: `src/metesparser/bearing_converter.py` — add `degree_of_curvature_to_radius()`
- Modify: `src/metesparser/call_extractor.py` — parse "degree of curve" in `extract_curve_info()`
- Modify: `tests/unit/test_phase5_production.py`

### 2a. Write failing tests

Add to `tests/unit/test_phase5_production.py`:

```python
from metesparser.bearing_converter import BearingConverter
from metesparser.call_extractor import CallExtractor


class TestDegreeOfCurvature:
    """Tests for degree of curvature parsing."""

    def test_degree_of_curvature_to_radius_5_degrees(self) -> None:
        """D° = 5 → R = 5729.578 / 5 = 1145.9156"""
        radius = BearingConverter.degree_of_curvature_to_radius(5.0)
        assert abs(radius - 1145.9156) < 0.001

    def test_degree_of_curvature_to_radius_1_degree(self) -> None:
        """D° = 1 → R = 5729.578"""
        radius = BearingConverter.degree_of_curvature_to_radius(1.0)
        assert abs(radius - 5729.578) < 0.001

    def test_degree_of_curvature_to_radius_10_degrees(self) -> None:
        """D° = 10 → R = 572.9578"""
        radius = BearingConverter.degree_of_curvature_to_radius(10.0)
        assert abs(radius - 572.9578) < 0.001

    def test_degree_of_curvature_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="non-zero"):
            BearingConverter.degree_of_curvature_to_radius(0.0)

    def test_degree_of_curvature_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            BearingConverter.degree_of_curvature_to_radius(-5.0)

    def test_extract_curve_info_degree_of_curve(self) -> None:
        """Parse 'degree of curve of 5°00'00\"' and convert to radius."""
        text = (
            "along a curve to the right having a degree of curve of 5°00'00\", "
            "a delta angle of 30°00'00\", an arc length of 600.00 feet"
        )
        info = CallExtractor.extract_curve_info(text)
        assert info.get("direction") == "right"
        assert info.get("radius_ft") is not None
        assert abs(info["radius_ft"] - 1145.9156) < 0.1

    def test_extract_curve_info_degree_of_curvature_variant(self) -> None:
        """Parse 'degree of curvature' spelling variant."""
        text = (
            "along a curve to the left having a degree of curvature of 2°30', "
            "a delta angle of 15°, an arc distance of 200.00 feet"
        )
        info = CallExtractor.extract_curve_info(text)
        assert info.get("direction") == "left"
        assert info.get("radius_ft") is not None
        # D° = 2.5 → R = 5729.578 / 2.5 = 2291.8312
        assert abs(info["radius_ft"] - 2291.8312) < 0.1
```

### 2b. Run tests to verify they fail

```bash
uv run pytest tests/unit/test_phase5_production.py::TestDegreeOfCurvature -v
```

Expected: FAIL — `degree_of_curvature_to_radius` does not exist; degree-of-curve not parsed in `extract_curve_info`.

### 2c. Implement

**In `src/metesparser/bearing_converter.py`**, add method to `BearingConverter` class (after `parse_packed_dms`, around line 49):

```python
@classmethod
def degree_of_curvature_to_radius(cls, degree_of_curve: float) -> float:
    """Convert degree of curvature to radius using arc definition.

    The degree of curvature is the central angle subtended by a 100-ft arc.
    Formula: R = 5729.578 / D°

    Args:
        degree_of_curve: Degree of curvature (must be > 0)

    Returns:
        Radius in feet

    Raises:
        ValueError: If degree_of_curve is zero or negative
    """
    if degree_of_curve <= 0:
        raise ValueError(
            f"Degree of curvature must be positive and non-zero, got {degree_of_curve}"
        )
    return 5729.578 / degree_of_curve
```

**In `src/metesparser/call_extractor.py`**, in `extract_curve_info()`, add degree-of-curvature detection after the existing radius extraction (around line 430, in the `else` branch after `radius_match`):

```python
# Degree of curvature → radius conversion
doc_match = re.search(
    r"degree\s+of\s+(?:curve|curvature)\s+(?:of\s+)?"
    r"(\d+(?:\.\d+)?)(?:°|(?:\s+)?degrees?)"
    r"(?:\s*(\d+(?:\.\d+)?)(?:'|\s+minutes?))?"
    r'(?:\s*(\d+(?:\.\d+)?)(?:"|\s+seconds?))?',
    text,
    re.IGNORECASE,
)
if doc_match and curve_info.get("radius_ft") is None:
    doc_deg = float(doc_match.group(1))
    if doc_match.group(2):
        doc_deg += float(doc_match.group(2)) / 60.0
    if doc_match.group(3):
        doc_deg += float(doc_match.group(3)) / 3600.0
    if doc_deg > 0:
        curve_info["radius_ft"] = BearingConverter.degree_of_curvature_to_radius(doc_deg)
```

Also add it to the primary `CURVE_PATTERN` match branch (around line 410), in case "degree of curve" appears alongside the main curve pattern.

### 2d. Run tests to verify they pass

```bash
uv run pytest tests/unit/test_phase5_production.py::TestDegreeOfCurvature -v
```

Expected: All PASS.

### 2e. Run full test suite

```bash
uv run pytest -v
```

Expected: All tests pass (no regressions).

### 2f. Commit

```bash
git add src/metesparser/bearing_converter.py src/metesparser/call_extractor.py tests/unit/test_phase5_production.py
git commit -m "feat: add degree of curvature parsing (D° → R = 5729.578/D°)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Step 3: Extended Curve Properties (T, E, M) — bearing_converter

**Files:**
- Modify: `src/metesparser/bearing_converter.py`
- Modify: `tests/unit/test_phase5_production.py`

### 3a. Write failing tests

```python
class TestExtendedCurveProperties:
    """Tests for external distance (E) and middle ordinate (M)."""

    def test_calculate_curve_properties_includes_tangent(self) -> None:
        """T = R * tan(Δ/2) — already computed in calculate_missing_curve_elements."""
        result = BearingConverter.calculate_curve_properties(100.0, delta_deg=90.0)
        # T = 100 * tan(45°) = 100.0
        assert "tangent_length_ft" in result
        assert abs(result["tangent_length_ft"] - 100.0) < 0.01

    def test_calculate_curve_properties_external_distance(self) -> None:
        """E = R * (1/cos(Δ/2) - 1)"""
        result = BearingConverter.calculate_curve_properties(100.0, delta_deg=90.0)
        # E = 100 * (1/cos(45°) - 1) = 100 * (1.41421 - 1) = 41.421
        assert "external_distance_ft" in result
        assert abs(result["external_distance_ft"] - 41.421) < 0.01

    def test_calculate_curve_properties_middle_ordinate(self) -> None:
        """M = R * (1 - cos(Δ/2))"""
        result = BearingConverter.calculate_curve_properties(100.0, delta_deg=90.0)
        # M = 100 * (1 - cos(45°)) = 100 * (1 - 0.70711) = 29.289
        assert "middle_ordinate_ft" in result
        assert abs(result["middle_ordinate_ft"] - 29.289) < 0.01

    def test_calculate_curve_properties_small_delta(self) -> None:
        """Small delta should produce small E and M values."""
        result = BearingConverter.calculate_curve_properties(500.0, delta_deg=10.0)
        assert result["external_distance_ft"] < 5.0
        assert result["middle_ordinate_ft"] < 5.0
        assert result["tangent_length_ft"] < 50.0

    def test_calculate_missing_curve_elements_includes_e_and_m(self) -> None:
        """calculate_missing_curve_elements should also return E and M."""
        result = BearingConverter.calculate_missing_curve_elements(
            radius_ft=100.0, delta_deg=90.0
        )
        assert "external_distance_ft" in result
        assert "middle_ordinate_ft" in result
        assert abs(result["external_distance_ft"] - 41.421) < 0.01
        assert abs(result["middle_ordinate_ft"] - 29.289) < 0.01
```

### 3b. Run tests to verify they fail

```bash
uv run pytest tests/unit/test_phase5_production.py::TestExtendedCurveProperties -v
```

Expected: FAIL — `tangent_length_ft`, `external_distance_ft`, `middle_ordinate_ft` not in `calculate_curve_properties()` return dict.

### 3c. Implement

**In `src/metesparser/bearing_converter.py`**:

1. In `calculate_curve_properties()` (around line 258), add three new keys to the return dict:

```python
tangent_length_ft = radius_ft * math.tan(delta_rad / 2)
external_distance_ft = radius_ft * (1.0 / math.cos(delta_rad / 2) - 1.0)
middle_ordinate_ft = radius_ft * (1.0 - math.cos(delta_rad / 2))

return {
    "radius_ft": radius_ft,
    "delta_deg": delta_deg,
    "delta_rad": delta_rad,
    "arc_length_ft": arc,
    "chord_length_ft": chord,
    "tangent_length_ft": tangent_length_ft,
    "external_distance_ft": external_distance_ft,
    "middle_ordinate_ft": middle_ordinate_ft,
}
```

2. In `calculate_missing_curve_elements()` (around line 399-406), add `external_distance_ft` and `middle_ordinate_ft` after `tangent_length_ft`:

```python
tangent_length_ft = radius_ft * math.tan(delta_rad / 2)
external_distance_ft = radius_ft * (1.0 / math.cos(delta_rad / 2) - 1.0)
middle_ordinate_ft = radius_ft * (1.0 - math.cos(delta_rad / 2))

return {
    "radius_ft": radius_ft,
    "delta_deg": delta_deg,
    "arc_length_ft": arc_length_ft,
    "chord_length_ft": chord_length_ft,
    "tangent_length_ft": tangent_length_ft,
    "external_distance_ft": external_distance_ft,
    "middle_ordinate_ft": middle_ordinate_ft,
}
```

### 3d. Run tests to verify they pass

```bash
uv run pytest tests/unit/test_phase5_production.py::TestExtendedCurveProperties -v
```

Expected: All PASS.

### 3e. Run full test suite

```bash
uv run pytest -v
```

Expected: All tests pass.

### 3f. Commit

```bash
git add src/metesparser/bearing_converter.py tests/unit/test_phase5_production.py
git commit -m "feat: add extended curve properties — tangent (T), external distance (E), middle ordinate (M)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Step 4: Natural Monument Classification — call_extractor

**Files:**
- Modify: `src/metesparser/call_extractor.py`
- Modify: `tests/unit/test_phase5_production.py`

### 4a. Write failing tests

```python
from metesparser.call_extractor import MonumentClassifier


class TestNaturalMonumentClassification:
    """Tests for natural monument classification."""

    # Tree patterns
    def test_classify_oak_tree(self) -> None:
        assert MonumentClassifier.classify_monument("a white oak tree") == "tree"

    def test_classify_hickory_tree(self) -> None:
        assert MonumentClassifier.classify_monument("a hickory tree, 14 inches diameter") == "tree"

    def test_classify_pine_tree(self) -> None:
        assert MonumentClassifier.classify_monument("a pine tree") == "tree"

    def test_classify_elm_tree(self) -> None:
        assert MonumentClassifier.classify_monument("an elm tree") == "tree"

    def test_classify_walnut_tree(self) -> None:
        assert MonumentClassifier.classify_monument("a black walnut") == "tree"

    def test_classify_sycamore_tree(self) -> None:
        assert MonumentClassifier.classify_monument("a sycamore tree") == "tree"

    def test_classify_generic_tree(self) -> None:
        assert MonumentClassifier.classify_monument("a marked tree") == "tree"

    # Rock patterns
    def test_classify_rock_outcrop(self) -> None:
        assert MonumentClassifier.classify_monument("a rock outcrop") == "rock"

    def test_classify_standing_rock(self) -> None:
        assert MonumentClassifier.classify_monument("a standing rock") == "rock"

    def test_classify_large_rock(self) -> None:
        assert MonumentClassifier.classify_monument("a large rock") == "rock"

    def test_classify_boulder(self) -> None:
        assert MonumentClassifier.classify_monument("a boulder") == "rock"

    # Natural feature patterns
    def test_classify_stream(self) -> None:
        assert MonumentClassifier.classify_monument("center of the stream") == "natural_feature"

    def test_classify_creek(self) -> None:
        assert MonumentClassifier.classify_monument("bank of Bear Creek") == "natural_feature"

    def test_classify_river(self) -> None:
        assert MonumentClassifier.classify_monument("edge of the river") == "natural_feature"

    def test_classify_ridge(self) -> None:
        assert MonumentClassifier.classify_monument("top of the ridge") == "natural_feature"

    def test_classify_shoreline(self) -> None:
        assert MonumentClassifier.classify_monument("the shoreline") == "natural_feature"

    # Priority: artificial monuments should still match first
    def test_stone_monument_still_matches_stone(self) -> None:
        """Existing 'stone' pattern should still work."""
        assert MonumentClassifier.classify_monument("a stone monument") == "stone"

    def test_iron_pin_still_matches(self) -> None:
        assert MonumentClassifier.classify_monument("iron pin found") == "iron_pin"
```

### 4b. Run tests to verify they fail

```bash
uv run pytest tests/unit/test_phase5_production.py::TestNaturalMonumentClassification -v
```

Expected: FAIL — tree/rock/natural_feature types not in MONUMENT_PATTERNS.

### 4c. Implement

**In `src/metesparser/call_extractor.py`**, add natural monument patterns to `MONUMENT_PATTERNS` list. Insert AFTER the existing artificial patterns (after line 47's `landscaping` entry) but BEFORE the generic `"monument"` catch-all at line 69:

```python
# Natural monuments — trees
(r"\b(?:oak|hickory|elm|pine|walnut|sycamore|maple|beech|poplar|cedar|ash|birch|chestnut|cottonwood|willow|cypress)\b", "tree"),
(r"\btree\b", "tree"),
# Natural monuments — rocks
(r"\bboulder\b", "rock"),
(r"\brock\s+outcrop\b", "rock"),
(r"\bstanding\s+rock\b", "rock"),
(r"\blarge\s+rock\b", "rock"),
# Natural features — catch-all for water/terrain
(r"\b(?:stream|creek|river|brook|branch|run)\b", "natural_feature"),
(r"\b(?:ridge|bluff|cliff|shoreline|lakeshore|shore)\b", "natural_feature"),
```

**Important:** These must come AFTER the `"stone"` patterns (lines 39-40) to preserve priority for artificial "stone monument" matches.

### 4d. Run tests to verify they pass

```bash
uv run pytest tests/unit/test_phase5_production.py::TestNaturalMonumentClassification -v
```

Expected: All PASS.

### 4e. Run full test suite

```bash
uv run pytest -v
```

Expected: All tests pass.

### 4f. Commit

```bash
git add src/metesparser/call_extractor.py tests/unit/test_phase5_production.py
git commit -m "feat: add natural monument classification — tree, rock, natural_feature

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Step 5: 32-Point Compass System — bearing_converter + call_extractor

**Files:**
- Modify: `src/metesparser/bearing_converter.py` — add `compass_point_to_azimuth()`
- Modify: `src/metesparser/call_extractor.py` — add compass point detection in `extract_direction()`
- Modify: `tests/unit/test_phase5_production.py`

### 5a. Write failing tests

```python
class TestCompassPointSystem:
    """Tests for 32-point mariner's compass system."""

    def test_north(self) -> None:
        assert BearingConverter.compass_point_to_azimuth("North") == 0.0

    def test_north_by_east(self) -> None:
        assert abs(BearingConverter.compass_point_to_azimuth("North by East") - 11.25) < 0.01

    def test_north_northeast(self) -> None:
        assert abs(BearingConverter.compass_point_to_azimuth("North-Northeast") - 22.5) < 0.01

    def test_northeast(self) -> None:
        assert abs(BearingConverter.compass_point_to_azimuth("Northeast") - 45.0) < 0.01

    def test_east(self) -> None:
        assert abs(BearingConverter.compass_point_to_azimuth("East") - 90.0) < 0.01

    def test_south(self) -> None:
        assert abs(BearingConverter.compass_point_to_azimuth("South") - 180.0) < 0.01

    def test_west(self) -> None:
        assert abs(BearingConverter.compass_point_to_azimuth("West") - 270.0) < 0.01

    def test_southwest(self) -> None:
        assert abs(BearingConverter.compass_point_to_azimuth("Southwest") - 225.0) < 0.01

    def test_south_by_west(self) -> None:
        assert abs(BearingConverter.compass_point_to_azimuth("South by West") - 191.25) < 0.01

    def test_case_insensitive(self) -> None:
        assert abs(BearingConverter.compass_point_to_azimuth("NORTH BY EAST") - 11.25) < 0.01

    def test_invalid_point_returns_none(self) -> None:
        assert BearingConverter.compass_point_to_azimuth("Northish") is None

    def test_extract_direction_compass_point(self) -> None:
        """extract_direction should detect compass points as fallback."""
        result = CallExtractor.extract_direction("North by East 125 feet to an iron pin")
        assert result.lower() == "north by east"

    def test_extract_direction_northeast_by_north(self) -> None:
        result = CallExtractor.extract_direction("Northeast by North 200 feet")
        assert result.lower() == "northeast by north"

    def test_extract_direction_prefers_quadrant_over_compass(self) -> None:
        """Quadrant bearings should take priority over compass points."""
        result = CallExtractor.extract_direction("S 45°30' E along the North line 100 feet")
        assert "45" in result  # should be the quadrant bearing, not "North"
```

### 5b. Run tests to verify they fail

```bash
uv run pytest tests/unit/test_phase5_production.py::TestCompassPointSystem -v
```

Expected: FAIL — `compass_point_to_azimuth` does not exist; compass points not detected in `extract_direction`.

### 5c. Implement

**In `src/metesparser/bearing_converter.py`**, add to `BearingConverter` class:

```python
COMPASS_POINTS: dict[str, float] = {
    "north": 0.0,
    "north by east": 11.25,
    "north-northeast": 22.5,
    "northeast by north": 33.75,
    "northeast": 45.0,
    "northeast by east": 56.25,
    "east-northeast": 67.5,
    "east by north": 78.75,
    "east": 90.0,
    "east by south": 101.25,
    "east-southeast": 112.5,
    "southeast by east": 123.75,
    "southeast": 135.0,
    "southeast by south": 146.25,
    "south-southeast": 157.5,
    "south by east": 168.75,
    "south": 180.0,
    "south by west": 191.25,
    "south-southwest": 202.5,
    "southwest by south": 213.75,
    "southwest": 225.0,
    "southwest by west": 236.25,
    "west-southwest": 247.5,
    "west by south": 258.75,
    "west": 270.0,
    "west by north": 281.25,
    "west-northwest": 292.5,
    "northwest by west": 303.75,
    "northwest": 315.0,
    "northwest by north": 326.25,
    "north-northwest": 337.5,
    "north by west": 348.75,
}

@classmethod
def compass_point_to_azimuth(cls, compass_point: str) -> float | None:
    """Convert a 32-point compass direction to azimuth.

    Args:
        compass_point: Compass point name (e.g., "North by East", "Northeast")

    Returns:
        Azimuth in degrees or None if not a recognized compass point
    """
    normalized = compass_point.strip().lower()
    return cls.COMPASS_POINTS.get(normalized)
```

**In `src/metesparser/call_extractor.py`**, in `extract_direction()` (around line 345), add compass point detection as a third fallback after the cardinal pattern:

```python
# Compass point fallback (32-point system)
# Build regex from compass points, longest first to avoid partial matches
compass_names = sorted(BearingConverter.COMPASS_POINTS.keys(), key=len, reverse=True)
compass_regex = r"\b(" + "|".join(re.escape(name) for name in compass_names) + r")\b"
compass_match = re.search(compass_regex, text, re.IGNORECASE)
if compass_match:
    return compass_match.group(0).lower()
```

**Important:** This must come AFTER the quadrant and cardinal fallbacks (the existing return order ensures quadrant > cardinal > compass). However, the cardinal check will match simple "north", "south", etc. before the compass check, which is correct — compass point detection only adds the compound points like "north by east".

### 5d. Run tests to verify they pass

```bash
uv run pytest tests/unit/test_phase5_production.py::TestCompassPointSystem -v
```

Expected: All PASS.

### 5e. Run full test suite

```bash
uv run pytest -v
```

Expected: All tests pass.

### 5f. Commit

```bash
git add src/metesparser/bearing_converter.py src/metesparser/call_extractor.py tests/unit/test_phase5_production.py
git commit -m "feat: add 32-point compass system — mariner's notation to azimuth conversion

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Step 6: Clause Taxonomy — text_parser

**Files:**
- Modify: `src/metesparser/text_parser.py` — add `extract_deed_clauses()`
- Modify: `tests/unit/test_phase5_production.py`

### 6a. Write failing tests

```python
from metesparser.text_parser import TextParser


class TestClauseTaxonomy:
    """Tests for deed clause extraction."""

    def test_extract_reservation_clause(self) -> None:
        text = "RESERVING unto the Grantor a right of way 20 feet wide along the northern boundary."
        clauses = TextParser.extract_deed_clauses(text)
        assert len(clauses) == 1
        assert clauses[0].clause_type == "reservation"
        assert "RESERVING" in clauses[0].text

    def test_extract_subject_to_clause(self) -> None:
        text = "SUBJECT TO existing easements of record and all applicable zoning ordinances."
        clauses = TextParser.extract_deed_clauses(text)
        assert len(clauses) == 1
        assert clauses[0].clause_type == "subject_to"
        assert "SUBJECT TO" in clauses[0].text

    def test_extract_together_with_clause(self) -> None:
        text = "TOGETHER WITH a right of ingress and egress over the private road."
        clauses = TextParser.extract_deed_clauses(text)
        assert len(clauses) == 1
        assert clauses[0].clause_type == "together_with"
        assert "TOGETHER WITH" in clauses[0].text

    def test_extract_multiple_clauses(self) -> None:
        text = (
            "RESERVING unto the Grantor mineral rights. "
            "SUBJECT TO existing utility easements. "
            "TOGETHER WITH appurtenant water rights."
        )
        clauses = TextParser.extract_deed_clauses(text)
        assert len(clauses) == 3
        types = {c.clause_type for c in clauses}
        assert types == {"reservation", "subject_to", "together_with"}

    def test_no_clauses_returns_empty(self) -> None:
        text = "BEGINNING at an iron pin, thence N 45° E 100 feet to a point."
        clauses = TextParser.extract_deed_clauses(text)
        assert clauses == []

    def test_reserving_variant_spelling(self) -> None:
        text = "RESERVING UNTO the grantor and his heirs all oil and gas rights."
        clauses = TextParser.extract_deed_clauses(text)
        assert len(clauses) == 1
        assert clauses[0].clause_type == "reservation"

    def test_subject_to_covenants(self) -> None:
        text = "Subject to covenants, conditions, and restrictions of record."
        clauses = TextParser.extract_deed_clauses(text)
        assert len(clauses) == 1
        assert clauses[0].clause_type == "subject_to"
```

### 6b. Run tests to verify they fail

```bash
uv run pytest tests/unit/test_phase5_production.py::TestClauseTaxonomy -v
```

Expected: FAIL — `extract_deed_clauses` does not exist.

### 6c. Implement

**In `src/metesparser/text_parser.py`**, add method to `TextParser` class (after `extract_prior_conveyance`, around line 731):

```python
@classmethod
def extract_deed_clauses(cls, text: str) -> list:
    """Extract deed clauses (reservations, subject-to, together-with).

    These are metadata clauses that don't change the boundary geometry.

    Args:
        text: Legal description text

    Returns:
        List of DeedClause objects
    """
    from .models import DeedClause

    clauses: list[DeedClause] = []

    patterns: list[tuple[str, str]] = [
        (r"(RESERVING\b.*?)(?=\.\s+[A-Z]|\.\s*$|$)", "reservation"),
        (r"(SUBJECT\s+TO\b.*?)(?=\.\s+[A-Z]|\.\s*$|$)", "subject_to"),
        (r"(TOGETHER\s+WITH\b.*?)(?=\.\s+[A-Z]|\.\s*$|$)", "together_with"),
    ]

    for pattern, clause_type in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE | re.DOTALL):
            clause_text = match.group(1).strip().rstrip(".")
            if clause_text:
                clauses.append(DeedClause(clause_type=clause_type, text=clause_text))

    return clauses
```

### 6d. Run tests to verify they pass

```bash
uv run pytest tests/unit/test_phase5_production.py::TestClauseTaxonomy -v
```

Expected: All PASS.

### 6e. Run full test suite

```bash
uv run pytest -v
```

### 6f. Commit

```bash
git add src/metesparser/text_parser.py tests/unit/test_phase5_production.py
git commit -m "feat: add clause taxonomy — reservation, subject_to, together_with extraction

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Step 7: Subdivision Lot/Block + TPOB/RPOB — text_parser

**Files:**
- Modify: `src/metesparser/text_parser.py` — add `extract_subdivision_reference()`, extend POB patterns
- Modify: `tests/unit/test_phase5_production.py`

### 7a. Write failing tests

```python
class TestSubdivisionReference:
    """Tests for subdivision lot/block extraction."""

    def test_full_subdivision_reference(self) -> None:
        text = "Lot 15, Block 3, PENNBROOK ESTATES, as recorded in Plat Book 14, Page 22"
        ref = TextParser.extract_subdivision_reference(text)
        assert ref is not None
        assert ref.lot == "15"
        assert ref.block == "3"
        assert ref.subdivision_name == "PENNBROOK ESTATES"
        assert ref.plat_book == "14"
        assert ref.plat_page == "22"

    def test_lot_only(self) -> None:
        text = "Lot 5, OAKDALE SUBDIVISION"
        ref = TextParser.extract_subdivision_reference(text)
        assert ref is not None
        assert ref.lot == "5"
        assert ref.block is None

    def test_lot_and_block_no_plat(self) -> None:
        text = "Lot 12, Block 7, SUNSET HILLS"
        ref = TextParser.extract_subdivision_reference(text)
        assert ref is not None
        assert ref.lot == "12"
        assert ref.block == "7"
        assert ref.subdivision_name == "SUNSET HILLS"

    def test_no_subdivision_returns_none(self) -> None:
        text = "BEGINNING at an iron pin, thence N 45° E 100 feet"
        ref = TextParser.extract_subdivision_reference(text)
        assert ref is None

    def test_plat_book_and_page(self) -> None:
        text = "recorded in Plat Book 23, Page 45 of the County Records"
        ref = TextParser.extract_subdivision_reference(text)
        assert ref is not None
        assert ref.plat_book == "23"
        assert ref.plat_page == "45"


class TestTPOBRecognition:
    """Tests for True/Remote Point of Beginning recognition."""

    def test_tpob_recognized_as_pob(self) -> None:
        text = "thence to the TRUE POINT OF BEGINNING"
        assert TextParser.is_closure_to_pob("to the TRUE POINT OF BEGINNING") is True

    def test_tpob_abbreviation(self) -> None:
        assert TextParser.is_closure_to_pob("to the TPOB") is True

    def test_tpob_dotted(self) -> None:
        assert TextParser.is_closure_to_pob("to the T.P.O.B.") is True

    def test_rpob_recognized_as_pob(self) -> None:
        assert TextParser.is_closure_to_pob("to the REMOTE POINT OF BEGINNING") is True

    def test_rpob_abbreviation(self) -> None:
        assert TextParser.is_closure_to_pob("to the RPOB") is True

    def test_rpob_dotted(self) -> None:
        assert TextParser.is_closure_to_pob("to the R.P.O.B.") is True

    def test_extract_pob_with_tpob(self) -> None:
        text = "TRUE POINT OF BEGINNING at the corner of Lot 5; THENCE N 45° E"
        pob = TextParser.extract_pob(text)
        assert "corner of Lot 5" in pob

    def test_extract_pob_with_tpob_abbreviation(self) -> None:
        text = "TPOB at an iron pin found; THENCE S 30° W"
        pob = TextParser.extract_pob(text)
        assert "iron pin" in pob
```

### 7b. Run tests to verify they fail

```bash
uv run pytest tests/unit/test_phase5_production.py::TestSubdivisionReference tests/unit/test_phase5_production.py::TestTPOBRecognition -v
```

Expected: FAIL — `extract_subdivision_reference` does not exist; TPOB/RPOB patterns not in `is_closure_to_pob` or `extract_pob`.

### 7c. Implement

**In `src/metesparser/text_parser.py`**:

1. Add `extract_subdivision_reference()` method (after `extract_deed_clauses`):

```python
@classmethod
def extract_subdivision_reference(cls, text: str):
    """Extract subdivision lot/block reference from deed text.

    Args:
        text: Legal description text

    Returns:
        SubdivisionReference or None if no subdivision reference found
    """
    from .models import SubdivisionReference

    lot = None
    block = None
    subdivision_name = None
    plat_book = None
    plat_page = None

    lot_match = re.search(r"\bLot\s+(\w+)", text, re.IGNORECASE)
    if lot_match:
        lot = lot_match.group(1)

    block_match = re.search(r"\bBlock\s+(\w+)", text, re.IGNORECASE)
    if block_match:
        block = block_match.group(1)

    # Subdivision name: typically in ALL CAPS after Lot/Block
    name_match = re.search(
        r"(?:Block\s+\w+|Lot\s+\w+),?\s+([A-Z][A-Z\s]+(?:ESTATES?|SUBDIVISION|ADDITION|HEIGHTS?|HILLS?|PARK|PLACE|MANOR|ACRES|VILLAGE|LANDING|TERRACE|GARDENS?)?)\b",
        text,
    )
    if name_match:
        subdivision_name = name_match.group(1).strip()

    plat_match = re.search(
        r"Plat\s+Book\s+(\d+),?\s*Page\s+(\d+)", text, re.IGNORECASE
    )
    if plat_match:
        plat_book = plat_match.group(1)
        plat_page = plat_match.group(2)

    if any([lot, block, subdivision_name, plat_book]):
        return SubdivisionReference(
            lot=lot,
            block=block,
            subdivision_name=subdivision_name,
            plat_book=plat_book,
            plat_page=plat_page,
        )

    return None
```

2. Extend `is_closure_to_pob()` closure patterns (around line 265-271) — add TPOB/RPOB patterns:

```python
r"\bto\s+(?:the\s+)?(?:true\s+)?(?:point\s+of\s+)?beginning\b",
r"\bto\s+(?:the\s+)?(?:remote\s+)?(?:point\s+of\s+)?beginning\b",
r"\bto\s+(?:the\s+)?T\.?P\.?O\.?B\.?\b",
r"\bto\s+(?:the\s+)?R\.?P\.?O\.?B\.?\b",
r"\bto\s+(?:the\s+)?TPOB\b",
r"\bto\s+(?:the\s+)?RPOB\b",
```

3. Extend `extract_pob()` POB patterns (around line 241-244) — add TPOB/RPOB:

```python
r"TRUE\s+POINT\s+OF\s+BEGINNING\s+at\s+(.*?)(?:\.|;|THENCE)",
r"TPOB\s+at\s+(.*?)(?:\.|;|THENCE)",
r"T\.P\.O\.B\.\s+at\s+(.*?)(?:\.|;|THENCE)",
r"REMOTE\s+POINT\s+OF\s+BEGINNING\s+at\s+(.*?)(?:\.|;|THENCE)",
r"RPOB\s+at\s+(.*?)(?:\.|;|THENCE)",
```

### 7d. Run tests to verify they pass

```bash
uv run pytest tests/unit/test_phase5_production.py::TestSubdivisionReference tests/unit/test_phase5_production.py::TestTPOBRecognition -v
```

Expected: All PASS.

### 7e. Run full test suite

```bash
uv run pytest -v
```

### 7f. Commit

```bash
git add src/metesparser/text_parser.py tests/unit/test_phase5_production.py
git commit -m "feat: add subdivision lot/block extraction and TPOB/RPOB recognition

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Step 8: Witness Trees — text_parser

**Files:**
- Modify: `src/metesparser/text_parser.py` — add `extract_witness_trees()`
- Modify: `tests/unit/test_phase5_production.py`

### 8a. Write failing tests

```python
class TestWitnessTrees:
    """Tests for witness tree / reference mark extraction."""

    def test_extract_single_witness_tree(self) -> None:
        text = "a white oak, 14 inches diameter, bears N 35° W, 12 links distant"
        trees = TextParser.extract_witness_trees(text)
        assert len(trees) == 1
        assert "white oak" in trees[0]
        assert "14 inches" in trees[0]

    def test_extract_multiple_witness_trees(self) -> None:
        text = (
            "a white oak, 14 inches diameter, bears N 35° W, 12 links distant; "
            "a hickory, 10 inches diameter, bears S 60° E, 8 links distant"
        )
        trees = TextParser.extract_witness_trees(text)
        assert len(trees) == 2

    def test_extract_witness_tree_with_bears(self) -> None:
        text = "a post oak 12 in dia bears N 22°30' E 15 links dist"
        trees = TextParser.extract_witness_trees(text)
        assert len(trees) == 1

    def test_no_witness_trees(self) -> None:
        text = "thence N 45° E 100 feet to an iron pin found"
        trees = TextParser.extract_witness_trees(text)
        assert trees == []

    def test_witness_tree_preserves_verbatim(self) -> None:
        """Verbatim text should be preserved per architecture principle #3."""
        original = "a black walnut, 18 inches diameter, bears S 15° W, 20 links distant"
        trees = TextParser.extract_witness_trees(original)
        assert len(trees) == 1
        assert trees[0] == original.strip()
```

### 8b. Run tests to verify they fail

```bash
uv run pytest tests/unit/test_phase5_production.py::TestWitnessTrees -v
```

Expected: FAIL — `extract_witness_trees` does not exist.

### 8c. Implement

**In `src/metesparser/text_parser.py`**, add method (after `extract_subdivision_reference`):

```python
@classmethod
def extract_witness_trees(cls, text: str) -> list[str]:
    """Extract witness tree / reference mark descriptions.

    Historical surveyors recorded trees near corners with species,
    diameter, bearing and distance. Stored verbatim per architecture
    principle #3 (preserve deed language).

    Args:
        text: Legal description text

    Returns:
        List of verbatim witness tree descriptions
    """
    trees: list[str] = []

    # Pattern: tree species + diameter + bears + direction + distance
    tree_pattern = re.compile(
        r"((?:a\s+)?(?:\w+\s+)?(?:oak|hickory|elm|pine|walnut|sycamore|maple|beech|"
        r"poplar|cedar|ash|birch|chestnut|cottonwood|willow|cypress)"
        r"[^;.]*?\bbears?\b[^;.]*?(?:dist(?:ant)?|links?|feet|ft)[^;.]*)",
        re.IGNORECASE,
    )

    for match in tree_pattern.finditer(text):
        trees.append(match.group(1).strip())

    return trees
```

### 8d. Run tests to verify they pass

```bash
uv run pytest tests/unit/test_phase5_production.py::TestWitnessTrees -v
```

Expected: All PASS.

### 8e. Run full test suite

```bash
uv run pytest -v
```

### 8f. Commit

```bash
git add src/metesparser/text_parser.py tests/unit/test_phase5_production.py
git commit -m "feat: add witness tree / reference mark extraction (verbatim)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Step 9: Spiral Curves + State Plane Metadata — call_extractor + text_parser

**Files:**
- Modify: `src/metesparser/call_extractor.py` — detect "spiral" in `extract_curve_info()`
- Modify: `src/metesparser/text_parser.py` — add `extract_coordinate_system()`
- Modify: `tests/unit/test_phase5_production.py`

### 9a. Write failing tests

```python
class TestSpiralCurveDetection:
    """Tests for spiral (transition) curve detection."""

    def test_spiral_keyword_detected(self) -> None:
        text = "along a spiral curve to the right having a radius of 500 feet, delta of 15°, arc length of 130.90 feet"
        info = CallExtractor.extract_curve_info(text)
        assert info.get("curve_type") == "spiral"

    def test_transition_curve_detected(self) -> None:
        text = "along a transition curve to the left, radius 800 feet, delta 10°, arc distance of 139.63 feet"
        info = CallExtractor.extract_curve_info(text)
        assert info.get("curve_type") == "spiral"

    def test_regular_curve_not_spiral(self) -> None:
        text = "along a curve to the right having a radius of 500 feet, delta of 30°"
        info = CallExtractor.extract_curve_info(text)
        assert info.get("curve_type") != "spiral"


class TestStatePlaneMetadata:
    """Tests for State Plane coordinate system metadata extraction."""

    def test_extract_full_state_plane(self) -> None:
        text = "State Plane Coordinate System, Texas South Central Zone, FIPS 4204, NAD 83"
        system, fips = TextParser.extract_coordinate_system(text)
        assert system is not None
        assert "Texas South Central" in system
        assert fips == "4204"

    def test_extract_state_plane_no_fips(self) -> None:
        text = "Based on the Pennsylvania State Plane Coordinate System, South Zone"
        system, fips = TextParser.extract_coordinate_system(text)
        assert system is not None
        assert "Pennsylvania" in system or "South Zone" in system
        assert fips is None

    def test_extract_fips_code_only(self) -> None:
        text = "Coordinates referenced to FIPS Zone 3200, NAD 83"
        system, fips = TextParser.extract_coordinate_system(text)
        assert fips == "3200"

    def test_no_coordinate_system(self) -> None:
        text = "BEGINNING at an iron pin, thence N 45° E 100 feet"
        system, fips = TextParser.extract_coordinate_system(text)
        assert system is None
        assert fips is None

    def test_extract_nad_83_reference(self) -> None:
        text = "All coordinates based on NAD 83, State Plane Coordinate System, Florida East Zone, FIPS 0901"
        system, fips = TextParser.extract_coordinate_system(text)
        assert system is not None
        assert fips == "0901"
```

### 9b. Run tests to verify they fail

```bash
uv run pytest tests/unit/test_phase5_production.py::TestSpiralCurveDetection tests/unit/test_phase5_production.py::TestStatePlaneMetadata -v
```

Expected: FAIL — spiral not detected; `extract_coordinate_system` does not exist.

### 9c. Implement

**In `src/metesparser/call_extractor.py`**, in `extract_curve_info()`, add spiral detection. After the compound/reverse detection block (around line 487), add:

```python
elif re.search(
    r"\b(?:spiral\s+curve|transition\s+curve)\b",
    text,
    re.IGNORECASE,
):
    curve_info["curve_type"] = "spiral"
```

Also update the initial `"curve"` keyword check at line 393 to also match "spiral" and "transition":

```python
if not re.search(r"\b(?:curve|spiral|transition)\b", text, re.IGNORECASE):
    return curve_info
```

**In `src/metesparser/text_parser.py`**, add method (after `extract_witness_trees`):

```python
@classmethod
def extract_coordinate_system(cls, text: str) -> tuple[str | None, str | None]:
    """Extract State Plane or other coordinate system reference.

    Advisory only — no grid correction computation.

    Args:
        text: Legal description text

    Returns:
        Tuple of (coordinate_system, fips_code) — both may be None
    """
    coordinate_system = None
    fips_code = None

    spcs_match = re.search(
        r"(State\s+Plane\s+Coordinate\s+System[^.;]*?)(?:\.|;|$)",
        text,
        re.IGNORECASE,
    )
    if spcs_match:
        coordinate_system = spcs_match.group(1).strip()

    fips_match = re.search(r"\bFIPS\s+(?:Zone\s+)?(\d{4})\b", text, re.IGNORECASE)
    if fips_match:
        fips_code = fips_match.group(1)

    return (coordinate_system, fips_code)
```

### 9d. Run tests to verify they pass

```bash
uv run pytest tests/unit/test_phase5_production.py::TestSpiralCurveDetection tests/unit/test_phase5_production.py::TestStatePlaneMetadata -v
```

Expected: All PASS.

### 9e. Run full test suite

```bash
uv run pytest -v
```

### 9f. Commit

```bash
git add src/metesparser/call_extractor.py src/metesparser/text_parser.py tests/unit/test_phase5_production.py
git commit -m "feat: add spiral curve detection and State Plane metadata extraction

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Step 10: Pipeline Wiring + Final Verification

**Files:**
- Modify: `src/metesparser/pdf_processor.py` — wire new extraction methods into `process_deed_pdf()`
- Modify: `src/metesparser/csv_builder.py` — add new metadata fields to `legal_description_to_csv()`
- Modify: `tests/unit/test_phase5_production.py` — integration-style test

### 10a. Write failing tests

```python
class TestPipelineWiring:
    """Tests for Phase 5 pipeline integration."""

    def test_legal_description_to_csv_includes_new_metadata(self, tmp_path) -> None:
        """New Phase 5 metadata should appear in the metadata file."""
        from metesparser.csv_builder import CSVBuilder
        from metesparser.models import DeedClause, SubdivisionReference

        ld = LegalDescription(
            calls=[
                DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0),
            ],
            distance_unit="feet",
            clauses=[DeedClause(clause_type="reservation", text="RESERVING mineral rights")],
            subdivision_ref=SubdivisionReference(lot="15", block="3", subdivision_name="PENNBROOK ESTATES"),
            witness_trees=["a white oak, 14 in dia, bears N 35° W"],
            coordinate_system="State Plane, Texas South Central Zone",
            fips_code="4204",
        )
        output_path = str(tmp_path / "test_output.csv")
        CSVBuilder.legal_description_to_csv(ld, output_path)

        # Read metadata file
        metadata_path = tmp_path / "test_output.metadata.txt"
        assert metadata_path.exists()
        metadata_content = metadata_path.read_text()
        assert "coordinate_system" in metadata_content
        assert "fips_code" in metadata_content
        assert "4204" in metadata_content

    def test_csv_schema_still_21_fields(self) -> None:
        """CSV schema must remain at 21 fields."""
        from metesparser.csv_builder import CSVBuilder

        assert len(CSVBuilder.FIELDNAMES) == 21
```

### 10b. Run tests to verify they fail

```bash
uv run pytest tests/unit/test_phase5_production.py::TestPipelineWiring -v
```

Expected: FAIL — new metadata fields not in `legal_description_to_csv()`.

### 10c. Implement

**In `src/metesparser/csv_builder.py`**, in `legal_description_to_csv()` (around line 156-173), add new metadata fields to the metadata dict:

```python
"coordinate_system": legal_desc.coordinate_system,
"fips_code": legal_desc.fips_code,
"clauses": "; ".join(f"[{c.clause_type}] {c.text}" for c in legal_desc.clauses) if legal_desc.clauses else None,
"subdivision_ref": (
    f"Lot {legal_desc.subdivision_ref.lot or '?'}, Block {legal_desc.subdivision_ref.block or '?'}, {legal_desc.subdivision_ref.subdivision_name or '?'}"
    if legal_desc.subdivision_ref else None
),
"witness_trees": "; ".join(legal_desc.witness_trees) if legal_desc.witness_trees else None,
```

**In `src/metesparser/pdf_processor.py`**, in `process_deed_pdf()` (around line 161-188), add calls to new extraction methods before constructing the `LegalDescription`:

```python
processing_logger.info("Extracting deed clauses")
clauses = TextParser.extract_deed_clauses(normalized_text)

processing_logger.info("Extracting subdivision reference")
subdivision_ref = TextParser.extract_subdivision_reference(normalized_text)

processing_logger.info("Extracting witness trees")
witness_trees = TextParser.extract_witness_trees(normalized_text)

processing_logger.info("Extracting coordinate system")
coordinate_system, fips_code = TextParser.extract_coordinate_system(normalized_text)
```

And add these to the `LegalDescription` constructor kwargs:

```python
clauses=clauses,
subdivision_ref=subdivision_ref,
witness_trees=witness_trees,
coordinate_system=coordinate_system,
fips_code=fips_code,
```

### 10d. Run tests to verify they pass

```bash
uv run pytest tests/unit/test_phase5_production.py::TestPipelineWiring -v
```

Expected: All PASS.

### 10e. Run full test suite

```bash
uv run pytest -v
```

Expected: All tests pass. CSV schema still 21 fields.

### 10f. Commit

```bash
git add src/metesparser/csv_builder.py src/metesparser/pdf_processor.py tests/unit/test_phase5_production.py
git commit -m "feat: wire Phase 5 features into pipeline — clauses, subdivision, witness trees, SPCS metadata

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Post-Implementation Checklist

After all 10 steps:

1. Run full test suite: `uv run pytest -v` — all tests pass
2. Run coverage: `uv run pytest --cov=src/metesparser --cov-report=term-missing` — maintain 90%+
3. Run linting: `make lint` — clean (text_parser.py excluded)
4. Run formatting: `make format` — clean
5. Update `__init__.py` version to `0.3.0`
6. Update CLAUDE.md feature table with 10 new features (#26-35)
7. Update CLAUDE.md pipeline diagram with new extraction steps
8. Use `superpowers:finishing-a-development-branch` to complete the branch
