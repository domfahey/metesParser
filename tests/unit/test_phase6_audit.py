"""Tests for Phase 6: Audit Sidecar — data models."""

from datetime import UTC, datetime

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
            timestamp_utc=datetime(2026, 2, 16, tzinfo=UTC),
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
                timestamp_utc=datetime(2026, 2, 16, tzinfo=UTC),
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
                timestamp_utc=datetime(2026, 2, 16, tzinfo=UTC),
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

    def test_mutable_accumulator(self):
        """AuditContext must allow appending to call_audits (not frozen)."""
        ctx = AuditContext(
            run_metadata=RunMetadata(
                parser_version="0.2.0",
                llm_provider="test",
                llm_model="test",
                prompt_hash="test",
                timestamp_utc=datetime(2026, 2, 16, tzinfo=UTC),
                source_pdf="test.pdf",
                cache_hit=False,
            ),
        )
        ctx.call_audits.append(CallAudit(course=1, source_excerpt="test"))
        assert len(ctx.call_audits) == 1

    def test_mutable_attribute_assignment(self):
        """AuditContext must allow setting extraction_record and verification_audit."""
        ctx = AuditContext(
            run_metadata=RunMetadata(
                parser_version="0.2.0",
                llm_provider="test",
                llm_model="test",
                prompt_hash="test",
                timestamp_utc=datetime(2026, 2, 16, tzinfo=UTC),
                source_pdf="test.pdf",
                cache_hit=False,
            ),
        )
        ctx.extraction_record = ExtractionRecord(
            raw_llm_response="test",
            normalized_text="test",
        )
        assert ctx.extraction_record is not None
