# Audit Sidecar Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `.audit.json` + `.audit.html` sidecar output so surveyors can trace every CSV value back to source deed text.

**Architecture:** Thread an optional `AuditContext` through the existing pipeline. Modules append audit data when `ctx` is provided; behavior is unchanged when `ctx is None`. JSON is the canonical format; HTML is rendered from it.

**Tech Stack:** Pydantic v2 (frozen models), structlog, Python string.Template (no Jinja)

---

## Phase A: Data Model + Pipeline Threading + JSON Serialization

### Task 1: Audit Data Models

**Files:**
- Modify: `src/metesparser/models.py` (append after `ConversionFactors` class, line ~568)
- Test: `tests/unit/test_phase6_audit.py` (create)

**Step 1: Write failing tests for audit models**

```python
# tests/unit/test_phase6_audit.py
"""Tests for Phase 6: Audit Sidecar — data models."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from metesparser.models import (
    AuditContext,
    CallAudit,
    CheckResult,
    Decision,
    ExtractionRecord,
    RunMetadata,
    Transformation,
    VerificationAudit,
)


class TestTransformation:
    def test_create_basic(self):
        t = Transformation(step="extract_bearing", input="South 56 degrees", output="S 56°00' W")
        assert t.step == "extract_bearing"
        assert t.input == "South 56 degrees"
        assert t.output == "S 56°00' W"
        assert t.rule is None

    def test_create_with_rule(self):
        t = Transformation(
            step="classify_monument",
            input="iron pin found",
            output="iron_pin",
            rule=r"iron\s*pin (call_extractor.py:134)",
        )
        assert t.rule == r"iron\s*pin (call_extractor.py:134)"

    def test_frozen(self):
        t = Transformation(step="x", input="a", output="b")
        with pytest.raises(ValidationError):
            t.step = "y"

    def test_extra_forbidden(self):
        with pytest.raises(ValidationError):
            Transformation(step="x", input="a", output="b", bogus="nope")


class TestDecision:
    def test_create_basic(self):
        d = Decision(
            field="monument_type",
            value="iron_pin",
            reason="matched pattern",
            confidence=0.90,
        )
        assert d.field == "monument_type"
        assert d.alternatives == []
        assert d.confidence == 0.90

    def test_with_alternatives(self):
        d = Decision(
            field="monument_type",
            value="iron_pin",
            reason="matched",
            alternatives=["iron_rod"],
            confidence=0.90,
        )
        assert d.alternatives == ["iron_rod"]

    def test_confidence_bounds(self):
        Decision(field="f", value="v", reason="r", confidence=0.0)
        Decision(field="f", value="v", reason="r", confidence=1.0)
        with pytest.raises(ValidationError):
            Decision(field="f", value="v", reason="r", confidence=-0.1)
        with pytest.raises(ValidationError):
            Decision(field="f", value="v", reason="r", confidence=1.1)


class TestCallAudit:
    def test_create_minimal(self):
        ca = CallAudit(course=1, source_excerpt="thence North 100 feet")
        assert ca.course == 1
        assert ca.transformations == []
        assert ca.decisions == []
        assert ca.flags == []

    def test_create_full(self):
        ca = CallAudit(
            course=3,
            source_excerpt="thence S 56°40' W 150.00 feet to an iron pin found",
            transformations=[
                Transformation(step="extract_bearing", input="S 56°40' W", output="236.675"),
            ],
            decisions=[
                Decision(
                    field="monument_type",
                    value="iron_pin",
                    reason="matched",
                    confidence=0.90,
                ),
            ],
            flags=["incomplete_bearing"],
        )
        assert len(ca.transformations) == 1
        assert len(ca.decisions) == 1
        assert ca.flags == ["incomplete_bearing"]


class TestCheckResult:
    def test_create(self):
        cr = CheckResult(
            name="traverse_closure",
            passed=True,
            detail="misclosure: 0.003 ft < 0.01 ft",
        )
        assert cr.name == "traverse_closure"
        assert cr.passed is True
        assert cr.inputs == {}

    def test_with_inputs(self):
        cr = CheckResult(
            name="traverse_closure",
            passed=True,
            detail="ok",
            inputs={"misclosure_ft": 0.003, "tolerance_ft": 0.01},
        )
        assert cr.inputs["misclosure_ft"] == 0.003


class TestRunMetadata:
    def test_create(self):
        rm = RunMetadata(
            parser_version="0.2.0",
            llm_provider="openai",
            llm_model="gpt-5.2",
            prompt_hash="abc123",
            timestamp_utc=datetime(2026, 2, 16, tzinfo=timezone.utc),
            source_pdf="deed.pdf",
            cache_hit=False,
        )
        assert rm.parser_version == "0.2.0"
        assert rm.config == {}


class TestExtractionRecord:
    def test_create(self):
        er = ExtractionRecord(
            raw_llm_response="BEGINNING at...",
            normalized_text="BEGINNING at...",
        )
        assert er.llm_confidence is None
        assert er.confidence_signals == {}


class TestVerificationAudit:
    def test_create_empty(self):
        va = VerificationAudit()
        assert va.checks == []
        assert va.closure_summary == {}


class TestAuditContext:
    def test_create_minimal(self):
        ctx = AuditContext(
            run_metadata=RunMetadata(
                parser_version="0.2.0",
                llm_provider="openai",
                llm_model="gpt-5.2",
                prompt_hash="abc",
                timestamp_utc=datetime(2026, 2, 16, tzinfo=timezone.utc),
                source_pdf="test.pdf",
                cache_hit=False,
            ),
        )
        assert ctx.schema_version == "1.0.0"
        assert ctx.call_audits == []
        assert ctx.extraction_record is None
        assert ctx.verification_audit is None

    def test_json_roundtrip(self):
        ctx = AuditContext(
            run_metadata=RunMetadata(
                parser_version="0.2.0",
                llm_provider="openai",
                llm_model="gpt-5.2",
                prompt_hash="abc",
                timestamp_utc=datetime(2026, 2, 16, tzinfo=timezone.utc),
                source_pdf="test.pdf",
                cache_hit=False,
            ),
            call_audits=[
                CallAudit(course=1, source_excerpt="thence North 100 feet"),
            ],
        )
        json_str = ctx.model_dump_json(indent=2)
        restored = AuditContext.model_validate_json(json_str)
        assert restored.call_audits[0].course == 1
        assert restored.run_metadata.parser_version == "0.2.0"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_phase6_audit.py -v`
Expected: ImportError — models don't exist yet

**Step 3: Implement audit models in models.py**

Add after the `ConversionFactors` class (line ~568):

```python
class Transformation(_Model):
    """A single transformation step in the audit trail."""

    step: str = Field(..., description="Pipeline step name (e.g., 'extract_bearing')")
    input: str = Field(..., description="Input value before transformation")
    output: str = Field(..., description="Output value after transformation")
    rule: str | None = Field(default=None, description="Regex pattern or method that matched")


class Decision(_Model):
    """A parsing decision with confidence and alternatives."""

    field: str = Field(..., description="Field name (e.g., 'monument_type')")
    value: str = Field(..., description="Chosen value")
    reason: str = Field(..., description="Why this value was chosen")
    alternatives: list[str] = Field(default_factory=list, description="Other values considered")
    confidence: FiniteFloat = Field(..., ge=0.0, le=1.0, description="Confidence 0.0-1.0")


class CallAudit(_Model):
    """Audit trail for a single deed call."""

    course: int = Field(..., ge=1, strict=True, description="Course number (matches DeedCall.course)")
    source_excerpt: str = Field(..., description="Verbatim text span this call was parsed from")
    transformations: list[Transformation] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


class CheckResult(_Model):
    """Result of a single verification check."""

    name: str = Field(..., description="Check name (e.g., 'traverse_closure')")
    passed: bool = Field(..., description="Whether the check passed")
    detail: str = Field(..., description="Human-readable detail")
    inputs: dict[str, float | str | bool] = Field(
        default_factory=dict, description="Values used in the check"
    )


class RunMetadata(_Model):
    """Metadata about a pipeline run."""

    parser_version: str = Field(..., description="Parser version (e.g., '0.2.0')")
    llm_provider: str = Field(..., description="LLM provider name")
    llm_model: str = Field(..., description="LLM model identifier")
    prompt_hash: str = Field(..., description="SHA256 hash of prompt template")
    timestamp_utc: datetime = Field(..., description="Run timestamp (UTC)")
    source_pdf: str = Field(..., description="Source PDF filename")
    cache_hit: bool = Field(..., description="Whether LLM response was from cache")
    config: dict[str, float | str | bool] = Field(
        default_factory=dict, description="Configuration snapshot"
    )


class ExtractionRecord(_Model):
    """Record of the LLM extraction step."""

    raw_llm_response: str = Field(..., description="Verbatim LLM output")
    normalized_text: str = Field(..., description="Text after normalization")
    llm_confidence: FiniteFloat | None = Field(
        default=None, ge=0.0, le=1.0, description="Heuristic extraction confidence"
    )
    confidence_signals: dict[str, bool] = Field(
        default_factory=dict, description="Individual confidence signal results"
    )


class VerificationAudit(_Model):
    """Audit trail for verification checks."""

    checks: list[CheckResult] = Field(default_factory=list)
    closure_summary: dict[str, float | str] = Field(default_factory=dict)


class AuditContext(_Model):
    """Complete audit trail for a pipeline run."""

    schema_version: str = Field(default="1.0.0", description="Audit schema version")
    run_metadata: RunMetadata
    extraction_record: ExtractionRecord | None = Field(default=None)
    call_audits: list[CallAudit] = Field(default_factory=list)
    verification_audit: VerificationAudit | None = Field(default=None)
```

Also add `from datetime import datetime` to the imports at the top of `models.py`.

**Step 4: Update `__init__.py` exports**

Add `AuditContext` to the imports and `__all__` list in `src/metesparser/__init__.py`.

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_phase6_audit.py -v`
Expected: All PASS

**Step 6: Run full test suite to verify no regressions**

Run: `uv run pytest`
Expected: ~790 passed

**Step 7: Commit**

```bash
git add src/metesparser/models.py src/metesparser/__init__.py tests/unit/test_phase6_audit.py
git commit -m "feat: add audit sidecar data models (Phase 6a, Task 1)"
```

---

### Task 2: AuditContext Creation in PDFProcessor

**Files:**
- Modify: `src/metesparser/pdf_processor.py:168-260` (process_deed_pdf method)
- Modify: `src/metesparser/__init__.py:13` (version string import)
- Test: `tests/unit/test_phase6_audit.py` (append)

**Step 1: Write failing tests**

Append to `tests/unit/test_phase6_audit.py`:

```python
import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

from metesparser.models import AuditContext, RunMetadata
from metesparser.pdf_processor import PDFProcessor


class TestAuditContextCreation:
    """Test that PDFProcessor creates and populates AuditContext."""

    def test_process_deed_pdf_returns_audit_context(self):
        """process_deed_pdf should accept audit=True and return (LegalDescription, AuditContext)."""
        mock_client = MagicMock()
        mock_client.generate_text_with_pdf.return_value = "Sample deed text"
        mock_client.generate_text.side_effect = [
            "Legal description extracted",  # extract_legal_description
            "BEGINNING at an iron pin; THENCE North 45 degrees East 100.00 feet to a point; THENCE South 45 degrees East 100.00 feet to a point; THENCE South 45 degrees West 100.00 feet to a point; THENCE North 45 degrees West 100.00 feet to the POINT OF BEGINNING.",  # normalize
        ]

        processor = PDFProcessor(client=mock_client, cache=False)
        result = processor.process_deed_pdf("/fake/path.pdf", audit=True)

        assert isinstance(result, tuple)
        assert len(result) == 2
        legal_desc, ctx = result
        assert ctx is not None
        assert isinstance(ctx, AuditContext)
        assert ctx.run_metadata.source_pdf == "path.pdf"
        assert ctx.run_metadata.parser_version == "0.2.0"

    def test_process_deed_pdf_no_audit_returns_legal_desc_only(self):
        """Default behavior (audit=False) returns just LegalDescription."""
        mock_client = MagicMock()
        mock_client.generate_text_with_pdf.return_value = "Sample deed text"
        mock_client.generate_text.side_effect = [
            "Legal description extracted",
            "BEGINNING at an iron pin; THENCE North 45 degrees East 100.00 feet to a point; THENCE South 45 degrees East 100.00 feet to a point; THENCE South 45 degrees West 100.00 feet to a point; THENCE North 45 degrees West 100.00 feet to the POINT OF BEGINNING.",
        ]

        processor = PDFProcessor(client=mock_client, cache=False)
        result = processor.process_deed_pdf("/fake/path.pdf")

        # Returns LegalDescription directly (not a tuple)
        from metesparser.models import LegalDescription
        assert isinstance(result, LegalDescription)

    def test_audit_context_captures_extraction_record(self):
        """AuditContext should capture the raw LLM response and normalized text."""
        mock_client = MagicMock()
        mock_client.generate_text_with_pdf.return_value = "Raw PDF text"
        mock_client.generate_text.side_effect = [
            "Extracted legal desc",
            "BEGINNING at a point; THENCE North 45 degrees East 100.00 feet to a point; THENCE South 45 degrees East 100.00 feet to a point; THENCE South 45 degrees West 100.00 feet to a point; THENCE North 45 degrees West 100.00 feet to the POINT OF BEGINNING.",
        ]

        processor = PDFProcessor(client=mock_client, cache=False)
        _, ctx = processor.process_deed_pdf("/fake/deed.pdf", audit=True)

        assert ctx.extraction_record is not None
        assert ctx.extraction_record.raw_llm_response == "Extracted legal desc"
        assert len(ctx.extraction_record.normalized_text) > 0
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_phase6_audit.py::TestAuditContextCreation -v`
Expected: TypeError — `process_deed_pdf()` got unexpected keyword argument 'audit'

**Step 3: Implement audit parameter in PDFProcessor.process_deed_pdf**

Modify `process_deed_pdf` signature to accept `audit: bool = False`. When `audit=True`:
1. Create `RunMetadata` with parser version, LLM provider/model info, source PDF name, timestamp
2. Create `AuditContext` with the run metadata
3. After LLM extraction, populate `extraction_record.raw_llm_response`
4. After normalization, populate `extraction_record.normalized_text`
5. Return `(legal_desc, ctx)` when `audit=True`, just `legal_desc` when `audit=False`

Key implementation details:
- Import `datetime` and `hashlib` at the top
- Import `__version__` from `metesparser`
- Get provider name from `self.client` (check class name or store it during `__init__`)
- Get model name from client (add a `model` property if needed, or use a sensible default)
- Hash the prompt template content for `prompt_hash`

The `process_deed_pdf` method should use `overload` or a runtime check:
```python
def process_deed_pdf(
    self, pdf_path: str, *, audit: bool = False
) -> LegalDescription | tuple[LegalDescription, AuditContext]:
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_phase6_audit.py -v`
Expected: All PASS

**Step 5: Run full test suite**

Run: `uv run pytest`
Expected: ~790 passed (existing tests unaffected since `audit` defaults to `False`)

**Step 6: Commit**

```bash
git add src/metesparser/pdf_processor.py tests/unit/test_phase6_audit.py
git commit -m "feat: PDFProcessor creates AuditContext when audit=True (Phase 6a, Task 2)"
```

---

### Task 3: JSON Serialization + File Output

**Files:**
- Modify: `src/metesparser/csv_builder.py:259-303` (export_verified_csv)
- Test: `tests/unit/test_phase6_audit.py` (append)

**Step 1: Write failing tests**

```python
import json
from pathlib import Path


class TestAuditJsonSerialization:
    """Test .audit.json file output."""

    def test_audit_json_written_alongside_csv(self, tmp_path):
        """When AuditContext is provided, .audit.json should be written."""
        from metesparser.csv_builder import CSVBuilder
        from metesparser.models import (
            AuditContext,
            CallAudit,
            ClosureResult,
            DeedCall,
            ExtractionRecord,
            RunMetadata,
        )

        ctx = AuditContext(
            run_metadata=RunMetadata(
                parser_version="0.2.0",
                llm_provider="openai",
                llm_model="gpt-5.2",
                prompt_hash="abc123",
                timestamp_utc=datetime(2026, 2, 16, tzinfo=timezone.utc),
                source_pdf="test.pdf",
                cache_hit=False,
            ),
            extraction_record=ExtractionRecord(
                raw_llm_response="raw text",
                normalized_text="normalized text",
            ),
            call_audits=[
                CallAudit(course=1, source_excerpt="thence North 100 feet"),
            ],
        )

        calls = [
            DeedCall(
                course=1,
                direction_text="N 45°00' E",
                bearing_quadrant="N 45°00' E",
                bearing_azimuth_deg_from_north=45.0,
                distance_ft=100.0,
            ),
        ]

        closure = ClosureResult(
            misclosure_x_ft=0.0,
            misclosure_y_ft=0.0,
            misclosure_ft=0.0,
            area_sq_ft=5000.0,
            area_acres=0.1148,
            perimeter_ft=400.0,
            closure_passed=True,
            angle_check_passed=True,
            curve_consistency_passed=True,
        )

        output_path = str(tmp_path / "test.csv")
        CSVBuilder.export_verified_csv(
            calls, closure, output_path, audit_context=ctx
        )

        audit_path = tmp_path / "test_verified.audit.json"
        assert audit_path.exists()
        data = json.loads(audit_path.read_text())
        assert data["schema_version"] == "1.0.0"
        assert data["run_metadata"]["parser_version"] == "0.2.0"
        assert len(data["call_audits"]) == 1

    def test_no_audit_json_without_context(self, tmp_path):
        """Without AuditContext, no .audit.json should be written."""
        from metesparser.csv_builder import CSVBuilder
        from metesparser.models import ClosureResult, DeedCall

        calls = [
            DeedCall(
                course=1,
                direction_text="N 45°00' E",
                bearing_quadrant="N 45°00' E",
                bearing_azimuth_deg_from_north=45.0,
                distance_ft=100.0,
            ),
        ]
        closure = ClosureResult(
            misclosure_x_ft=0.0,
            misclosure_y_ft=0.0,
            misclosure_ft=0.0,
            area_sq_ft=5000.0,
            area_acres=0.1148,
            perimeter_ft=400.0,
            closure_passed=True,
            angle_check_passed=True,
            curve_consistency_passed=True,
        )

        output_path = str(tmp_path / "test.csv")
        CSVBuilder.export_verified_csv(calls, closure, output_path)

        audit_path = tmp_path / "test_verified.audit.json"
        assert not audit_path.exists()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_phase6_audit.py::TestAuditJsonSerialization -v`
Expected: TypeError — `export_verified_csv()` got unexpected keyword argument 'audit_context'

**Step 3: Implement audit_context parameter on export_verified_csv**

Add optional `audit_context: AuditContext | None = None` parameter to `export_verified_csv()`. When provided, write `.audit.json` alongside the verified CSV:

```python
if audit_context is not None:
    audit_path = verified_path.with_suffix(".audit.json")
    audit_path.write_text(audit_context.model_dump_json(indent=2))
    logger.info("Audit trail written", path=str(audit_path))
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_phase6_audit.py -v`
Expected: All PASS

**Step 5: Run full test suite**

Run: `uv run pytest`
Expected: ~790 passed

**Step 6: Commit**

```bash
git add src/metesparser/csv_builder.py tests/unit/test_phase6_audit.py
git commit -m "feat: write .audit.json alongside verified CSV (Phase 6a, Task 3)"
```

---

## Phase B: Source Excerpt Capture + Confidence Scoring

### Task 4: Source Excerpt Capture in CallExtractor

**Files:**
- Modify: `src/metesparser/call_extractor.py:183-246` (extract_calls method)
- Test: `tests/unit/test_phase6_audit.py` (append)

**Step 1: Write failing tests**

```python
class TestSourceExcerptCapture:
    """Test that CallExtractor populates source_excerpt in audit context."""

    def test_extract_calls_populates_call_audits(self):
        from metesparser.call_extractor import CallExtractor
        from metesparser.models import AuditContext, RunMetadata

        ctx = AuditContext(
            run_metadata=RunMetadata(
                parser_version="0.2.0",
                llm_provider="test",
                llm_model="test",
                prompt_hash="test",
                timestamp_utc=datetime(2026, 2, 16, tzinfo=timezone.utc),
                source_pdf="test.pdf",
                cache_hit=False,
            ),
        )

        text = (
            "BEGINNING at a point; "
            "THENCE North 45 degrees East 100.00 feet to a point; "
            "THENCE South 45 degrees East 100.00 feet to a point; "
            "THENCE South 45 degrees West 100.00 feet to a point; "
            "THENCE North 45 degrees West 100.00 feet to the POINT OF BEGINNING."
        )

        calls = CallExtractor.extract_calls(text, audit_context=ctx)

        assert len(calls) == 4
        assert len(ctx.call_audits) == 4
        assert ctx.call_audits[0].course == 1
        assert "North 45 degrees East" in ctx.call_audits[0].source_excerpt
        assert "100.00 feet" in ctx.call_audits[0].source_excerpt

    def test_extract_calls_no_audit_context(self):
        """Without audit_context, extract_calls works as before."""
        from metesparser.call_extractor import CallExtractor

        text = (
            "BEGINNING at a point; "
            "THENCE North 45 degrees East 100.00 feet to a point; "
            "THENCE South 45 degrees East 100.00 feet to a point."
        )

        calls = CallExtractor.extract_calls(text)
        assert len(calls) == 2  # normal behavior, no crash
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_phase6_audit.py::TestSourceExcerptCapture -v`
Expected: TypeError — `extract_calls()` got unexpected keyword argument 'audit_context'

**Step 3: Implement audit_context in extract_calls**

Add `audit_context: AuditContext | None = None` parameter to `extract_calls()`. In the loop at line ~214, after a successful call parse, append a `CallAudit`:

```python
if audit_context is not None:
    audit_context.call_audits.append(
        CallAudit(course=course_num, source_excerpt=call_text)
    )
```

**Important**: Since `AuditContext` is frozen, `call_audits` is a list (mutable container on a frozen model). Pydantic frozen models prevent attribute reassignment but list `.append()` works — this is the same pattern used with `warnings` on `ClosureResult`. However, `AuditContext` uses `frozen=True` from `_Model`. We need to verify this works. If not, we'll need to make `AuditContext` a non-frozen model (set `model_config = ConfigDict(extra="forbid")` without `frozen=True`).

**Decision**: Make `AuditContext` use `model_config = ConfigDict(extra="forbid")` (NOT frozen) since it's a mutable accumulator, not a domain value object. All other audit models stay frozen.

**Step 4: Run tests**

Run: `uv run pytest tests/unit/test_phase6_audit.py -v`
Expected: All PASS

**Step 5: Run full test suite**

Run: `uv run pytest`
Expected: ~790 passed

**Step 6: Commit**

```bash
git add src/metesparser/call_extractor.py src/metesparser/models.py tests/unit/test_phase6_audit.py
git commit -m "feat: capture source_excerpt per call in audit trail (Phase 6b, Task 4)"
```

---

### Task 5: Transformation + Decision Recording

**Files:**
- Modify: `src/metesparser/call_extractor.py:248-438` (extract_single_call)
- Modify: `src/metesparser/call_extractor.py:127-149` (MonumentClassifier.classify_monument)
- Test: `tests/unit/test_phase6_audit.py` (append)

**Step 1: Write failing tests**

```python
class TestTransformationRecording:
    """Test that transformations and decisions are recorded in audit context."""

    def test_bearing_transformation_recorded(self):
        from metesparser.call_extractor import CallExtractor
        from metesparser.models import AuditContext, RunMetadata

        ctx = AuditContext(
            run_metadata=RunMetadata(
                parser_version="0.2.0",
                llm_provider="test",
                llm_model="test",
                prompt_hash="test",
                timestamp_utc=datetime(2026, 2, 16, tzinfo=timezone.utc),
                source_pdf="test.pdf",
                cache_hit=False,
            ),
        )

        text = (
            "BEGINNING at a point; "
            "THENCE South 56 degrees 40 minutes West 150.00 feet to an iron pin found."
        )

        calls = CallExtractor.extract_calls(text, audit_context=ctx)

        assert len(ctx.call_audits) == 1
        audit = ctx.call_audits[0]

        # Should have transformations for bearing extraction and azimuth computation
        step_names = [t.step for t in audit.transformations]
        assert "extract_bearing" in step_names
        assert "compute_azimuth" in step_names

    def test_monument_decision_recorded(self):
        from metesparser.call_extractor import CallExtractor
        from metesparser.models import AuditContext, RunMetadata

        ctx = AuditContext(
            run_metadata=RunMetadata(
                parser_version="0.2.0",
                llm_provider="test",
                llm_model="test",
                prompt_hash="test",
                timestamp_utc=datetime(2026, 2, 16, tzinfo=timezone.utc),
                source_pdf="test.pdf",
                cache_hit=False,
            ),
        )

        text = (
            "BEGINNING at a point; "
            "THENCE North 45 degrees East 100.00 feet to an iron pin found."
        )

        calls = CallExtractor.extract_calls(text, audit_context=ctx)

        assert len(ctx.call_audits) == 1
        audit = ctx.call_audits[0]

        # Should have a decision for monument_type
        monument_decisions = [d for d in audit.decisions if d.field == "monument_type"]
        assert len(monument_decisions) == 1
        assert monument_decisions[0].value == "iron_pin"
        assert monument_decisions[0].confidence >= 0.8
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_phase6_audit.py::TestTransformationRecording -v`
Expected: AssertionError — transformations list is empty

**Step 3: Implement transformation/decision recording**

In `extract_single_call`, after each parsing step, append to `call_audit.transformations` and `call_audit.decisions`. The `audit_context` is threaded from `extract_calls` into `extract_single_call` via a new optional parameter.

Key recording points in `extract_single_call`:
1. After `extract_direction()` → `Transformation(step="extract_bearing", ...)`
2. After `quadrant_to_azimuth()` → `Transformation(step="compute_azimuth", ...)`
3. After `extract_distance()` → `Transformation(step="extract_distance", ...)`
4. After `classify_monument()` → `Decision(field="monument_type", ...)`
5. After `classify_monument_status()` → `Decision(field="monument_status", ...)`

The `call_audit` object is created in `extract_calls` and passed into `extract_single_call`. After the call is built, transformations/decisions are appended.

Modify `MonumentClassifier.classify_monument()` to optionally return the matched pattern (add a `with_rule: bool = False` parameter or have `extract_single_call` iterate patterns when auditing).

**Step 4: Run tests**

Run: `uv run pytest tests/unit/test_phase6_audit.py -v`
Expected: All PASS

**Step 5: Run full test suite**

Run: `uv run pytest`
Expected: ~790 passed

**Step 6: Commit**

```bash
git add src/metesparser/call_extractor.py tests/unit/test_phase6_audit.py
git commit -m "feat: record transformations and decisions in audit trail (Phase 6b, Task 5)"
```

---

### Task 6: Verification Audit Recording

**Files:**
- Modify: `src/metesparser/closure_checker.py:32-160` (verify_closure)
- Test: `tests/unit/test_phase6_audit.py` (append)

**Step 1: Write failing tests**

```python
class TestVerificationAuditRecording:
    """Test that ClosureChecker populates verification_audit."""

    def test_verify_closure_populates_audit(self, deed_call_factory):
        from metesparser.closure_checker import ClosureChecker
        from metesparser.models import AuditContext, RunMetadata

        ctx = AuditContext(
            run_metadata=RunMetadata(
                parser_version="0.2.0",
                llm_provider="test",
                llm_model="test",
                prompt_hash="test",
                timestamp_utc=datetime(2026, 2, 16, tzinfo=timezone.utc),
                source_pdf="test.pdf",
                cache_hit=False,
            ),
        )

        calls = [
            deed_call_factory(course=1, bearing_azimuth_deg_from_north=0.0, distance_ft=100.0),
            deed_call_factory(course=2, bearing_azimuth_deg_from_north=90.0, distance_ft=100.0),
            deed_call_factory(course=3, bearing_azimuth_deg_from_north=180.0, distance_ft=100.0),
            deed_call_factory(course=4, bearing_azimuth_deg_from_north=270.0, distance_ft=100.0),
        ]

        result = ClosureChecker.verify_closure(calls, audit_context=ctx)

        assert ctx.verification_audit is not None
        assert len(ctx.verification_audit.checks) >= 3  # closure, angles, curves
        assert ctx.verification_audit.closure_summary["status"] == result.get_closure_status()

        # Check that traverse_closure check is present
        check_names = [c.name for c in ctx.verification_audit.checks]
        assert "traverse_closure" in check_names
        assert "interior_angles" in check_names
        assert "curve_consistency" in check_names

    def test_verify_closure_no_audit_context(self, deed_call_factory):
        """Without audit_context, verify_closure works as before."""
        from metesparser.closure_checker import ClosureChecker

        calls = [
            deed_call_factory(course=1, bearing_azimuth_deg_from_north=0.0, distance_ft=100.0),
            deed_call_factory(course=2, bearing_azimuth_deg_from_north=90.0, distance_ft=100.0),
            deed_call_factory(course=3, bearing_azimuth_deg_from_north=180.0, distance_ft=100.0),
            deed_call_factory(course=4, bearing_azimuth_deg_from_north=270.0, distance_ft=100.0),
        ]

        result = ClosureChecker.verify_closure(calls)
        assert result.closure_passed  # normal behavior
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_phase6_audit.py::TestVerificationAuditRecording -v`
Expected: TypeError — `verify_closure()` got unexpected keyword argument 'audit_context'

**Step 3: Implement audit_context in verify_closure**

Add `audit_context: AuditContext | None = None` parameter. After each check, create a `CheckResult` and append to a list. At the end:

```python
if audit_context is not None:
    audit_context.verification_audit = VerificationAudit(
        checks=check_results,
        closure_summary={
            "misclosure_ft": misclosure,
            "precision_ratio": f"1:{round(1.0 / (misclosure / perimeter))}" if perimeter and misclosure / perimeter > 1e-10 else "N/A",
            "area_sq_ft": area_sq_ft,
            "area_acres": area_acres,
            "perimeter_ft": perimeter,
            "confidence_score": confidence,
            "status": closure_result.get_closure_status(),
        },
    )
```

**Step 4: Run tests**

Run: `uv run pytest tests/unit/test_phase6_audit.py -v`
Expected: All PASS

**Step 5: Run full test suite**

Run: `uv run pytest`
Expected: ~790 passed

**Step 6: Commit**

```bash
git add src/metesparser/closure_checker.py tests/unit/test_phase6_audit.py
git commit -m "feat: record verification checks in audit trail (Phase 6b, Task 6)"
```

---

### Task 7: LLM Extraction Confidence Scoring

**Files:**
- Modify: `src/metesparser/pdf_processor.py` (new method `_compute_llm_confidence`)
- Test: `tests/unit/test_phase6_audit.py` (append)

**Step 1: Write failing tests**

```python
class TestLLMConfidenceScoring:
    """Test heuristic LLM extraction confidence scoring."""

    def test_high_confidence_complete_description(self):
        from metesparser.pdf_processor import PDFProcessor

        text = (
            "BEGINNING at an iron pin found in the Southerly line; "
            "THENCE South 33 degrees 20 minutes East 60.00 feet; "
            "THENCE South 56 degrees 40 minutes West 125.00 feet; "
            "THENCE North 33 degrees 20 minutes West 60.00 feet; "
            "THENCE North 56 degrees 40 minutes East 125.00 feet to the "
            "POINT OF BEGINNING. Section 12, Township 15 North, Range 3 East."
        )
        confidence, signals = PDFProcessor._compute_llm_confidence(text)
        assert confidence >= 0.8
        assert signals["has_pob"] is True
        assert signals["has_bearing_calls"] is True
        assert signals["has_closure_language"] is True

    def test_low_confidence_garbled_text(self):
        from metesparser.pdf_processor import PDFProcessor

        text = "Th3nc3 N0rth @#$ d3gr33s"
        confidence, signals = PDFProcessor._compute_llm_confidence(text)
        assert confidence < 0.5

    def test_medium_confidence_missing_closure(self):
        from metesparser.pdf_processor import PDFProcessor

        text = (
            "BEGINNING at a point; "
            "THENCE North 45 degrees East 100.00 feet; "
            "THENCE South 45 degrees East 100.00 feet; "
            "THENCE South 45 degrees West 100.00 feet."
        )
        confidence, signals = PDFProcessor._compute_llm_confidence(text)
        assert signals["has_closure_language"] is False
        assert confidence < 0.9
```

**Step 2: Run to verify fail**

Run: `uv run pytest tests/unit/test_phase6_audit.py::TestLLMConfidenceScoring -v`
Expected: AttributeError — `_compute_llm_confidence` doesn't exist

**Step 3: Implement `_compute_llm_confidence`**

Static method on `PDFProcessor`:

```python
@staticmethod
def _compute_llm_confidence(text: str) -> tuple[float, dict[str, bool]]:
    """Compute heuristic confidence score for LLM extraction quality."""
    signals = {
        "has_pob": bool(re.search(r"\b(?:BEGINNING|POINT\s+OF\s+BEGINNING|POB)\b", text, re.IGNORECASE)),
        "has_bearing_calls": len(re.findall(r"\b[NS]\s+\d+\s+degrees?", text, re.IGNORECASE)) >= 3,
        "has_closure_language": bool(re.search(r"\b(?:POINT\s+OF\s+BEGINNING|place\s+of\s+beginning)\b", text, re.IGNORECASE)),
        "has_distances": bool(re.search(r"\d+\.\d+\s+(?:feet|ft)\b", text, re.IGNORECASE)),
        "text_length_reasonable": 50 < len(text) < 50000,
        "has_plss": bool(re.search(r"\b(?:Section|Township|Range)\b", text, re.IGNORECASE)),
        "no_garbled_chars": len(re.findall(r"[^\x00-\x7F°′″''\"–—]", text)) / max(len(text), 1) < 0.05,
    }
    weights = {
        "has_pob": 0.20,
        "has_bearing_calls": 0.20,
        "has_closure_language": 0.15,
        "has_distances": 0.15,
        "text_length_reasonable": 0.10,
        "has_plss": 0.10,
        "no_garbled_chars": 0.10,
    }
    confidence = sum(weights[k] for k, v in signals.items() if v)
    return confidence, signals
```

Wire it into `process_deed_pdf` when `audit=True`.

**Step 4: Run tests**

Run: `uv run pytest tests/unit/test_phase6_audit.py -v`
Expected: All PASS

**Step 5: Run full test suite**

Run: `uv run pytest`
Expected: ~790 passed

**Step 6: Commit**

```bash
git add src/metesparser/pdf_processor.py tests/unit/test_phase6_audit.py
git commit -m "feat: add heuristic LLM extraction confidence scoring (Phase 6b, Task 7)"
```

---

### Task 8: Per-Field Parse Confidence

**Files:**
- Modify: `src/metesparser/call_extractor.py` (confidence values in decisions)
- Test: `tests/unit/test_phase6_audit.py` (append)

**Step 1: Write failing tests**

```python
class TestPerFieldConfidence:
    """Test confidence scores on per-field decisions."""

    def test_exact_bearing_high_confidence(self):
        from metesparser.call_extractor import CallExtractor
        from metesparser.models import AuditContext, RunMetadata

        ctx = AuditContext(
            run_metadata=RunMetadata(
                parser_version="0.2.0",
                llm_provider="test",
                llm_model="test",
                prompt_hash="test",
                timestamp_utc=datetime(2026, 2, 16, tzinfo=timezone.utc),
                source_pdf="test.pdf",
                cache_hit=False,
            ),
        )

        text = "BEGINNING at a point; THENCE South 56 degrees 40 minutes West 150.00 feet to a point."
        CallExtractor.extract_calls(text, audit_context=ctx)

        bearing_decisions = [
            d for ca in ctx.call_audits for d in ca.decisions
            if d.field == "bearing_azimuth_deg_from_north"
        ]
        assert len(bearing_decisions) == 1
        assert bearing_decisions[0].confidence == 0.95

    def test_cardinal_only_low_confidence(self):
        from metesparser.call_extractor import CallExtractor
        from metesparser.models import AuditContext, RunMetadata

        ctx = AuditContext(
            run_metadata=RunMetadata(
                parser_version="0.2.0",
                llm_provider="test",
                llm_model="test",
                prompt_hash="test",
                timestamp_utc=datetime(2026, 2, 16, tzinfo=timezone.utc),
                source_pdf="test.pdf",
                cache_hit=False,
            ),
        )

        text = "BEGINNING at a point; THENCE southwesterly 150.00 feet to a point."
        CallExtractor.extract_calls(text, audit_context=ctx)

        # Cardinal-only bearing should have low confidence
        bearing_decisions = [
            d for ca in ctx.call_audits for d in ca.decisions
            if d.field == "bearing_azimuth_deg_from_north"
        ]
        # No azimuth decision for cardinal-only (azimuth is None)
        assert len(bearing_decisions) == 0

        # But should have an incomplete_bearing flag
        assert "incomplete_bearing" in ctx.call_audits[0].flags
```

**Step 2: Run to verify fail**

Run: `uv run pytest tests/unit/test_phase6_audit.py::TestPerFieldConfidence -v`

**Step 3: Implement confidence values**

Add confidence scores to the Decision objects created in Task 5:
- Exact bearing regex match: `confidence=0.95`
- Specific monument keyword: `confidence=0.90`
- Generic monument fallback: `confidence=0.60`
- Cardinal-only: no azimuth decision, add `"incomplete_bearing"` to flags
- Monument status: `confidence=0.95` for explicit keywords

**Step 4-6: Test, verify full suite, commit**

```bash
git add src/metesparser/call_extractor.py tests/unit/test_phase6_audit.py
git commit -m "feat: add per-field confidence scores to audit decisions (Phase 6b, Task 8)"
```

---

## Phase C: HTML Audit Report

### Task 9: HTML Report Generator

**Files:**
- Create: `src/metesparser/audit_reporter.py`
- Test: `tests/unit/test_phase6_audit.py` (append)

**Step 1: Write failing tests**

```python
class TestAuditReporter:
    """Test HTML audit report generation."""

    def test_generate_html_contains_key_sections(self):
        from metesparser.audit_reporter import AuditReporter
        from metesparser.models import (
            AuditContext,
            CallAudit,
            CheckResult,
            Decision,
            ExtractionRecord,
            RunMetadata,
            Transformation,
            VerificationAudit,
        )

        ctx = AuditContext(
            run_metadata=RunMetadata(
                parser_version="0.2.0",
                llm_provider="openai",
                llm_model="gpt-5.2",
                prompt_hash="abc123",
                timestamp_utc=datetime(2026, 2, 16, tzinfo=timezone.utc),
                source_pdf="test_deed.pdf",
                cache_hit=False,
            ),
            extraction_record=ExtractionRecord(
                raw_llm_response="BEGINNING at an iron pin...",
                normalized_text="BEGINNING at an iron pin...",
                llm_confidence=0.85,
            ),
            call_audits=[
                CallAudit(
                    course=1,
                    source_excerpt="thence S 56°40' W 150.00 feet to an iron pin found",
                    transformations=[
                        Transformation(
                            step="extract_bearing",
                            input="S 56°40' W",
                            output="236.675",
                        ),
                    ],
                    decisions=[
                        Decision(
                            field="monument_type",
                            value="iron_pin",
                            reason="matched pattern",
                            confidence=0.90,
                        ),
                    ],
                ),
            ],
            verification_audit=VerificationAudit(
                checks=[
                    CheckResult(name="traverse_closure", passed=True, detail="0.003 ft"),
                ],
                closure_summary={"status": "EXCELLENT", "misclosure_ft": 0.003},
            ),
        )

        html = AuditReporter.generate_html(ctx)

        # Key sections present
        assert "AUDIT REPORT" in html
        assert "test_deed.pdf" in html
        assert "0.2.0" in html
        assert "openai" in html or "gpt-5.2" in html
        assert "LLM Extraction" in html or "Extraction" in html
        assert "iron_pin" in html
        assert "traverse_closure" in html or "Traverse" in html
        assert "EXCELLENT" in html

        # Self-contained (no external references)
        assert "http://" not in html or "https://" not in html
        assert "<style>" in html  # embedded CSS

    def test_write_report_creates_file(self, tmp_path):
        from metesparser.audit_reporter import AuditReporter
        from metesparser.models import AuditContext, RunMetadata

        ctx = AuditContext(
            run_metadata=RunMetadata(
                parser_version="0.2.0",
                llm_provider="test",
                llm_model="test",
                prompt_hash="test",
                timestamp_utc=datetime(2026, 2, 16, tzinfo=timezone.utc),
                source_pdf="test.pdf",
                cache_hit=False,
            ),
        )

        output_path = tmp_path / "test.audit.html"
        AuditReporter.write_report(ctx, output_path)

        assert output_path.exists()
        content = output_path.read_text()
        assert "<!DOCTYPE html>" in content

    def test_confidence_color_coding(self):
        from metesparser.audit_reporter import AuditReporter

        assert AuditReporter._confidence_class(0.95) == "confidence-high"
        assert AuditReporter._confidence_class(0.65) == "confidence-medium"
        assert AuditReporter._confidence_class(0.30) == "confidence-low"
```

**Step 2: Run to verify fail**

Run: `uv run pytest tests/unit/test_phase6_audit.py::TestAuditReporter -v`
Expected: ImportError — `audit_reporter` module doesn't exist

**Step 3: Implement audit_reporter.py**

Create `src/metesparser/audit_reporter.py` with:
- `AuditReporter` class with static methods
- `generate_html(ctx: AuditContext) -> str` — builds HTML from context
- `write_report(ctx: AuditContext, path: Path) -> None` — writes to file
- `_confidence_class(score: float) -> str` — returns CSS class name
- Uses Python `string.Template` or f-strings (no external template engine)
- Embedded CSS with confidence color coding: `.confidence-high` (green), `.confidence-medium` (yellow), `.confidence-low` (red)
- Collapsible sections using `<details>/<summary>` HTML elements (no JavaScript needed)
- Self-contained: no external CSS/JS references

**Step 4: Run tests**

Run: `uv run pytest tests/unit/test_phase6_audit.py -v`
Expected: All PASS

**Step 5: Run full test suite**

Run: `uv run pytest`
Expected: ~790 passed

**Step 6: Commit**

```bash
git add src/metesparser/audit_reporter.py tests/unit/test_phase6_audit.py
git commit -m "feat: add HTML audit report generator (Phase 6c, Task 9)"
```

---

### Task 10: Wire HTML Report into Export Pipeline

**Files:**
- Modify: `src/metesparser/csv_builder.py:259-303` (export_verified_csv)
- Modify: `src/metesparser/__init__.py` (export AuditReporter)
- Test: `tests/unit/test_phase6_audit.py` (append)

**Step 1: Write failing tests**

```python
class TestHtmlReportIntegration:
    """Test that HTML report is written alongside audit JSON."""

    def test_export_verified_csv_writes_html_report(self, tmp_path):
        from metesparser.csv_builder import CSVBuilder
        from metesparser.models import (
            AuditContext,
            ClosureResult,
            DeedCall,
            RunMetadata,
        )

        ctx = AuditContext(
            run_metadata=RunMetadata(
                parser_version="0.2.0",
                llm_provider="test",
                llm_model="test",
                prompt_hash="test",
                timestamp_utc=datetime(2026, 2, 16, tzinfo=timezone.utc),
                source_pdf="test.pdf",
                cache_hit=False,
            ),
        )

        calls = [
            DeedCall(
                course=1,
                direction_text="N 45°00' E",
                bearing_quadrant="N 45°00' E",
                bearing_azimuth_deg_from_north=45.0,
                distance_ft=100.0,
            ),
        ]
        closure = ClosureResult(
            misclosure_x_ft=0.0,
            misclosure_y_ft=0.0,
            misclosure_ft=0.0,
            area_sq_ft=5000.0,
            area_acres=0.1148,
            perimeter_ft=400.0,
            closure_passed=True,
            angle_check_passed=True,
            curve_consistency_passed=True,
        )

        output_path = str(tmp_path / "test.csv")
        CSVBuilder.export_verified_csv(calls, closure, output_path, audit_context=ctx)

        # Both audit files should exist
        assert (tmp_path / "test_verified.audit.json").exists()
        assert (tmp_path / "test_verified.audit.html").exists()

        html_content = (tmp_path / "test_verified.audit.html").read_text()
        assert "<!DOCTYPE html>" in html_content
```

**Step 2: Run to verify fail**

Run: `uv run pytest tests/unit/test_phase6_audit.py::TestHtmlReportIntegration -v`
Expected: AssertionError — HTML file not created

**Step 3: Add HTML generation to export_verified_csv**

In `export_verified_csv`, after writing `.audit.json`:

```python
from .audit_reporter import AuditReporter

html_path = verified_path.with_suffix(".audit.html")
AuditReporter.write_report(audit_context, html_path)
logger.info("Audit HTML report written", path=str(html_path))
```

**Step 4: Run tests**

Run: `uv run pytest tests/unit/test_phase6_audit.py -v`
Expected: All PASS

**Step 5: Run full test suite**

Run: `uv run pytest`
Expected: ~790 passed

**Step 6: Commit**

```bash
git add src/metesparser/csv_builder.py src/metesparser/__init__.py tests/unit/test_phase6_audit.py
git commit -m "feat: generate HTML audit report alongside JSON (Phase 6c, Task 10)"
```

---

### Task 11: Final Integration + CLAUDE.md Update

**Files:**
- Modify: `CLAUDE.md` (add Phase 6 to feature table)
- Test: run full suite + lint + type check

**Step 1: Run all checks**

```bash
make check
```

Expected: All pass (lint, format, type, tests)

**Step 2: Update CLAUDE.md feature table**

Add rows 29-31 to the feature reference table:

```markdown
| 29 | Audit sidecar (JSON) | `models.py`, `csv_builder.py` | `AuditContext`, `export_verified_csv(audit_context=)` | .audit.json with full provenance chain |
| 30 | Audit report (HTML) | `audit_reporter.py` | `AuditReporter.generate_html()` | Self-contained, collapsible, color-coded |
| 31 | LLM extraction confidence | `pdf_processor.py` | `_compute_llm_confidence()` | Heuristic scoring (7 signals, 0.0-1.0) |
```

Update pipeline diagram to show audit context threading.

Update test count and version if needed.

**Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add Phase 6 audit sidecar features to CLAUDE.md"
```

**Step 4: Create PR**

```bash
gh pr create --title "feat: audit sidecar for transparency by design" --body "..."
```
