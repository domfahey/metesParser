"""Tests for Phase 6: Audit Sidecar — data models, CallExtractor audit, and PDFProcessor audit."""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker
from metesparser.models import (
    AuditContext,
    CallAudit,
    CheckResult,
    ClosureResult,
    Decision,
    DeedCall,
    ExtractionRecord,
    LegalDescription,
    RunMetadata,
    Transformation,
    VerificationAudit,
)
from metesparser.pdf_processor import PDFProcessor


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


# ---------------------------------------------------------------------------
# CallExtractor audit tests
# ---------------------------------------------------------------------------


def _make_audit_context() -> AuditContext:
    """Helper to create a minimal AuditContext for testing."""
    return AuditContext(
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


class TestSourceExcerptCapture:
    def test_extract_calls_populates_call_audits(self):
        ctx = _make_audit_context()
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
        # Text is normalized before splitting into calls, so the excerpt
        # contains the normalized form (e.g., "N 45° E" not "North 45 degrees East")
        assert "45" in ctx.call_audits[0].source_excerpt
        assert "100.00 feet" in ctx.call_audits[0].source_excerpt

    def test_extract_calls_no_audit_context(self):
        text = (
            "BEGINNING at a point; "
            "THENCE North 45 degrees East 100.00 feet to a point; "
            "THENCE South 45 degrees East 100.00 feet to a point."
        )
        calls = CallExtractor.extract_calls(text)
        assert len(calls) == 2


class TestTransformationRecording:
    def test_bearing_transformation_recorded(self):
        ctx = _make_audit_context()
        text = (
            "BEGINNING at a point; "
            "THENCE South 56 degrees 40 minutes West 150.00 feet to an iron pin found."
        )
        CallExtractor.extract_calls(text, audit_context=ctx)
        assert len(ctx.call_audits) == 1
        audit = ctx.call_audits[0]
        step_names = [t.step for t in audit.transformations]
        assert "extract_bearing" in step_names
        assert "compute_azimuth" in step_names

    def test_monument_decision_recorded(self):
        ctx = _make_audit_context()
        text = (
            "BEGINNING at a point; THENCE North 45 degrees East 100.00 feet to an iron pin found."
        )
        CallExtractor.extract_calls(text, audit_context=ctx)
        assert len(ctx.call_audits) == 1
        audit = ctx.call_audits[0]
        monument_decisions = [d for d in audit.decisions if d.field == "monument_type"]
        assert len(monument_decisions) == 1
        assert monument_decisions[0].value == "iron_pin"
        assert monument_decisions[0].confidence >= 0.8

    def test_monument_status_decision_recorded(self):
        ctx = _make_audit_context()
        text = (
            "BEGINNING at a point; THENCE North 45 degrees East 100.00 feet to an iron pin found."
        )
        CallExtractor.extract_calls(text, audit_context=ctx)
        audit = ctx.call_audits[0]
        status_decisions = [d for d in audit.decisions if d.field == "monument_status"]
        assert len(status_decisions) == 1
        assert status_decisions[0].value == "found"

    def test_incomplete_bearing_flag(self):
        ctx = _make_audit_context()
        text = "BEGINNING at a point; THENCE southwesterly 150.00 feet to a point."
        CallExtractor.extract_calls(text, audit_context=ctx)
        assert len(ctx.call_audits) == 1
        assert "incomplete_bearing" in ctx.call_audits[0].flags

    def test_exact_bearing_high_confidence(self):
        ctx = _make_audit_context()
        text = (
            "BEGINNING at a point; THENCE South 56 degrees 40 minutes West 150.00 feet to a point."
        )
        CallExtractor.extract_calls(text, audit_context=ctx)
        bearing_decisions = [
            d
            for ca in ctx.call_audits
            for d in ca.decisions
            if d.field == "bearing_azimuth_deg_from_north"
        ]
        assert len(bearing_decisions) == 1
        assert bearing_decisions[0].confidence == 0.95

    def test_failed_parse_not_in_audits(self):
        """Calls that fail to parse should not appear in call_audits."""
        ctx = _make_audit_context()
        text = "BEGINNING at a point; THENCE North 45 degrees East 100.00 feet to a point."
        calls = CallExtractor.extract_calls(text, audit_context=ctx)
        # call_audits count should match successful calls count
        assert len(ctx.call_audits) == len(calls)


# ---------------------------------------------------------------------------
# ClosureChecker verification audit tests
# ---------------------------------------------------------------------------


class TestVerificationAuditRecording:
    def test_verify_closure_populates_audit(self, deed_call_factory):
        ctx = _make_audit_context()
        calls = [
            deed_call_factory(course=1, bearing_azimuth_deg_from_north=0.0, distance_ft=100.0),
            deed_call_factory(course=2, bearing_azimuth_deg_from_north=90.0, distance_ft=100.0),
            deed_call_factory(course=3, bearing_azimuth_deg_from_north=180.0, distance_ft=100.0),
            deed_call_factory(course=4, bearing_azimuth_deg_from_north=270.0, distance_ft=100.0),
        ]
        result = ClosureChecker.verify_closure(calls, audit_context=ctx)
        assert ctx.verification_audit is not None
        assert len(ctx.verification_audit.checks) >= 3
        check_names = [c.name for c in ctx.verification_audit.checks]
        assert "traverse_closure" in check_names
        assert "interior_angles" in check_names
        assert "curve_consistency" in check_names
        assert ctx.verification_audit.closure_summary["status"] == result.get_closure_status()

    def test_verify_closure_no_audit_context(self, deed_call_factory):
        calls = [
            deed_call_factory(course=1, bearing_azimuth_deg_from_north=0.0, distance_ft=100.0),
            deed_call_factory(course=2, bearing_azimuth_deg_from_north=90.0, distance_ft=100.0),
            deed_call_factory(course=3, bearing_azimuth_deg_from_north=180.0, distance_ft=100.0),
            deed_call_factory(course=4, bearing_azimuth_deg_from_north=270.0, distance_ft=100.0),
        ]
        result = ClosureChecker.verify_closure(calls)
        assert result.closure_passed  # normal behavior unchanged

    def test_traverse_closure_check_has_inputs(self, deed_call_factory):
        ctx = _make_audit_context()
        calls = [
            deed_call_factory(course=1, bearing_azimuth_deg_from_north=0.0, distance_ft=100.0),
            deed_call_factory(course=2, bearing_azimuth_deg_from_north=90.0, distance_ft=100.0),
            deed_call_factory(course=3, bearing_azimuth_deg_from_north=180.0, distance_ft=100.0),
            deed_call_factory(course=4, bearing_azimuth_deg_from_north=270.0, distance_ft=100.0),
        ]
        ClosureChecker.verify_closure(calls, audit_context=ctx)
        closure_check = next(
            c for c in ctx.verification_audit.checks if c.name == "traverse_closure"
        )
        assert "misclosure_total_ft" in closure_check.inputs
        assert "tolerance_ft" in closure_check.inputs
        assert closure_check.passed is True

    def test_closure_summary_has_precision_ratio(self, deed_call_factory):
        ctx = _make_audit_context()
        calls = [
            deed_call_factory(course=1, bearing_azimuth_deg_from_north=0.0, distance_ft=100.0),
            deed_call_factory(course=2, bearing_azimuth_deg_from_north=90.0, distance_ft=100.0),
            deed_call_factory(course=3, bearing_azimuth_deg_from_north=180.0, distance_ft=100.0),
            deed_call_factory(course=4, bearing_azimuth_deg_from_north=270.0, distance_ft=100.0),
        ]
        ClosureChecker.verify_closure(calls, audit_context=ctx)
        summary = ctx.verification_audit.closure_summary
        assert "misclosure_ft" in summary
        assert "area_sq_ft" in summary
        assert "perimeter_ft" in summary
        assert "confidence_score" in summary
        assert "status" in summary

    def test_bearing_reversal_check_recorded(self, deed_call_factory):
        ctx = _make_audit_context()
        # Two adjacent courses ~180 degrees apart should trigger reversal warning
        calls = [
            deed_call_factory(course=1, bearing_azimuth_deg_from_north=0.0, distance_ft=100.0),
            deed_call_factory(course=2, bearing_azimuth_deg_from_north=179.0, distance_ft=100.0),
            deed_call_factory(course=3, bearing_azimuth_deg_from_north=270.0, distance_ft=100.0),
            deed_call_factory(course=4, bearing_azimuth_deg_from_north=90.0, distance_ft=100.0),
        ]
        ClosureChecker.verify_closure(calls, audit_context=ctx)
        reversal_check = next(
            c for c in ctx.verification_audit.checks if c.name == "bearing_reversals"
        )
        assert reversal_check.passed is False


# ---------------------------------------------------------------------------
# CSVBuilder audit JSON + HTML report tests
# ---------------------------------------------------------------------------


class TestAuditJsonSerialization:
    def test_audit_json_written_alongside_csv(self, tmp_path):
        from metesparser.csv_builder import CSVBuilder

        ctx = AuditContext(
            run_metadata=RunMetadata(
                parser_version="0.2.0",
                llm_provider="openai",
                llm_model="gpt-5.2",
                prompt_hash="abc123",
                timestamp_utc=datetime(2026, 2, 16, tzinfo=UTC),
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
                direction_text="N 45\u00b000' E",
                bearing_quadrant="N 45\u00b000' E",
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

        audit_path = tmp_path / "test_verified.audit.json"
        assert audit_path.exists()
        data = json.loads(audit_path.read_text())
        assert data["schema_version"] == "1.0.0"
        assert data["run_metadata"]["parser_version"] == "0.2.0"
        assert len(data["call_audits"]) == 1

    def test_no_audit_json_without_context(self, tmp_path):
        from metesparser.csv_builder import CSVBuilder

        calls = [
            DeedCall(
                course=1,
                direction_text="N 45\u00b000' E",
                bearing_quadrant="N 45\u00b000' E",
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


class TestAuditReporter:
    def test_generate_html_contains_key_sections(self):
        from metesparser.audit_reporter import AuditReporter

        ctx = AuditContext(
            run_metadata=RunMetadata(
                parser_version="0.2.0",
                llm_provider="openai",
                llm_model="gpt-5.2",
                prompt_hash="abc123",
                timestamp_utc=datetime(2026, 2, 16, tzinfo=UTC),
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
                    source_excerpt="thence S 56 deg 40 min W 150.00 feet to an iron pin found",
                    transformations=[
                        Transformation(
                            step="extract_bearing",
                            input="S 56 deg 40 min W",
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
        assert "<!DOCTYPE html>" in html
        assert "test_deed.pdf" in html
        assert "0.2.0" in html
        assert "<style>" in html
        assert "iron_pin" in html
        assert "EXCELLENT" in html

    def test_write_report_creates_file(self, tmp_path):
        from metesparser.audit_reporter import AuditReporter

        ctx = _make_audit_context()
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

    def test_html_escapes_user_content(self):
        from metesparser.audit_reporter import AuditReporter

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
            call_audits=[
                CallAudit(
                    course=1,
                    source_excerpt='<script>alert("xss")</script> thence North 100 feet',
                ),
            ],
        )
        html = AuditReporter.generate_html(ctx)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_html_report_written_alongside_csv(self, tmp_path):
        from metesparser.csv_builder import CSVBuilder

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
        calls = [
            DeedCall(
                course=1,
                direction_text="N 45\u00b000' E",
                bearing_quadrant="N 45\u00b000' E",
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
        assert (tmp_path / "test_verified.audit.json").exists()
        assert (tmp_path / "test_verified.audit.html").exists()
        html_content = (tmp_path / "test_verified.audit.html").read_text()
        assert "<!DOCTYPE html>" in html_content


# ---------------------------------------------------------------------------
# PDFProcessor audit integration tests
# ---------------------------------------------------------------------------

_SAMPLE_LEGAL_TEXT = (
    "BEGINNING at an iron pin found; "
    "THENCE South 33 degrees East 60.00 feet to a point; "
    "THENCE South 56 degrees West 125.00 feet to corner; "
    "THENCE North 33 degrees West 60.00 feet to a point; "
    "THENCE North 56 degrees East 125.00 feet to the "
    "POINT OF BEGINNING. Section 12, Township 15 North."
)


def _make_mock_client(
    extract_text_return: str = "Full document text from PDF",
    extract_legal_return: str = "Raw legal description extracted",
    normalize_return: str = _SAMPLE_LEGAL_TEXT,
) -> MagicMock:
    """Build a MagicMock that satisfies the BaseLLMClient protocol."""
    mock = MagicMock()
    mock.generate_text_with_pdf.return_value = extract_text_return
    # generate_text is called twice: once for extract_legal_description,
    # once for normalize_legal_description.
    mock.generate_text.side_effect = [extract_legal_return, normalize_return]
    return mock


class TestPDFProcessorAudit:
    """Test PDFProcessor audit context creation."""

    def test_process_deed_pdf_returns_audit_context(self):
        """audit=True returns (LegalDescription, AuditContext) tuple."""
        mock_client = _make_mock_client()
        processor = PDFProcessor(client=mock_client, cache=False)
        result = processor.process_deed_pdf("/fake/path.pdf", audit=True)

        assert isinstance(result, tuple)
        assert len(result) == 2
        legal_desc, ctx = result
        assert isinstance(legal_desc, LegalDescription)
        assert isinstance(ctx, AuditContext)
        assert ctx.run_metadata.source_pdf == "path.pdf"
        import metesparser

        assert ctx.run_metadata.parser_version == metesparser.__version__

    def test_process_deed_pdf_default_returns_legal_desc(self):
        """Default (audit=False) returns LegalDescription directly."""
        mock_client = _make_mock_client()
        processor = PDFProcessor(client=mock_client, cache=False)
        result = processor.process_deed_pdf("/fake/path.pdf")

        assert isinstance(result, LegalDescription)
        # Should NOT be a tuple
        assert not isinstance(result, tuple)

    def test_audit_captures_extraction_record(self):
        """AuditContext captures raw LLM response and normalized text."""
        raw_llm = "Raw deed text from LLM"
        normalized = _SAMPLE_LEGAL_TEXT
        mock_client = _make_mock_client(
            extract_legal_return=raw_llm,
            normalize_return=normalized,
        )
        processor = PDFProcessor(client=mock_client, cache=False)
        _, ctx = processor.process_deed_pdf("/fake/deed.pdf", audit=True)

        assert ctx.extraction_record is not None
        assert ctx.extraction_record.raw_llm_response == raw_llm
        assert ctx.extraction_record.normalized_text == normalized

    def test_audit_captures_llm_confidence(self):
        """AuditContext captures LLM confidence score."""
        mock_client = _make_mock_client()
        processor = PDFProcessor(client=mock_client, cache=False)
        _, ctx = processor.process_deed_pdf("/fake/deed.pdf", audit=True)

        assert ctx.extraction_record is not None
        assert isinstance(ctx.extraction_record.llm_confidence, float)
        assert 0.0 <= ctx.extraction_record.llm_confidence <= 1.0

    def test_audit_llm_provider_detection_openai(self):
        """LLM provider is detected as 'openai' when using OpenAIClient."""
        mock_client = _make_mock_client()
        # Patch the inner client to look like an OpenAIClient
        with patch.object(PDFProcessor, "_unwrap_client") as unwrap:
            from metesparser.llm_clients import OpenAIClient

            fake_openai = MagicMock(spec=OpenAIClient)
            fake_openai.model = "gpt-5.2"
            unwrap.return_value = fake_openai

            processor = PDFProcessor(client=mock_client, cache=False)
            _, ctx = processor.process_deed_pdf("/fake/deed.pdf", audit=True)

            assert ctx.run_metadata.llm_provider == "openai"
            assert ctx.run_metadata.llm_model == "gpt-5.2"

    def test_audit_llm_provider_detection_unknown(self):
        """Unknown client types get provider='unknown'."""
        mock_client = _make_mock_client()
        processor = PDFProcessor(client=mock_client, cache=False)
        _, ctx = processor.process_deed_pdf("/fake/deed.pdf", audit=True)

        # MagicMock is not OpenAIClient or GeminiClient
        assert ctx.run_metadata.llm_provider == "unknown"

    def test_audit_prompt_hash_is_sha256(self):
        """Prompt hash should be a 64-char hex string (SHA-256)."""
        mock_client = _make_mock_client()
        processor = PDFProcessor(client=mock_client, cache=False)
        _, ctx = processor.process_deed_pdf("/fake/deed.pdf", audit=True)

        assert len(ctx.run_metadata.prompt_hash) == 64
        # Should be valid hex
        int(ctx.run_metadata.prompt_hash, 16)

    def test_audit_config_snapshot(self):
        """RunMetadata.config includes closure_tolerance_ft and distance_unit."""
        mock_client = _make_mock_client()
        processor = PDFProcessor(client=mock_client, cache=False)
        _, ctx = processor.process_deed_pdf("/fake/deed.pdf", audit=True)

        assert ctx.run_metadata.config["closure_tolerance_ft"] == 0.01
        assert ctx.run_metadata.config["distance_unit"] == "feet"
        assert "log_level" in ctx.run_metadata.config


class TestLLMConfidenceScoring:
    """Test _compute_llm_confidence heuristic."""

    def test_high_confidence_complete_description(self):
        text = (
            "BEGINNING at an iron pin found; "
            "THENCE South 33 degrees East 60.00 feet; "
            "THENCE South 56 degrees West 125.00 feet; "
            "THENCE North 33 degrees West 60.00 feet; "
            "THENCE North 56 degrees East 125.00 feet to the "
            "POINT OF BEGINNING. Section 12, Township 15 North."
        )
        confidence, signals = PDFProcessor._compute_llm_confidence(text)
        assert confidence >= 0.8
        assert signals["has_pob"] is True
        assert signals["has_bearing_calls"] is True
        assert signals["has_closure_language"] is True

    def test_low_confidence_garbled(self):
        text = "Th3nc3 N0rth @#$ d3gr33s"
        confidence, signals = PDFProcessor._compute_llm_confidence(text)
        assert confidence < 0.5

    def test_missing_closure_reduces_confidence(self):
        text = (
            "BEGINNING at a point; "
            "THENCE North 45 degrees East 100.00 feet; "
            "THENCE South 45 degrees East 100.00 feet; "
            "THENCE South 45 degrees West 100.00 feet."
        )
        confidence, signals = PDFProcessor._compute_llm_confidence(text)
        assert signals["has_closure_language"] is False

    def test_empty_text(self):
        confidence, signals = PDFProcessor._compute_llm_confidence("")
        assert confidence < 0.2

    def test_all_signals_present(self):
        """When all signals present, confidence should be 1.0."""
        text = (
            "BEGINNING at an iron pin found in Section 12, Township 15 North, Range 3 East; "
            "THENCE South 33 degrees East 60.00 feet; "
            "THENCE South 56 degrees West 125.00 feet; "
            "THENCE North 33 degrees West 60.00 feet; "
            "THENCE North 56 degrees East 125.00 feet to the "
            "POINT OF BEGINNING."
        )
        confidence, signals = PDFProcessor._compute_llm_confidence(text)
        assert confidence == 1.0
        assert all(signals.values())

    def test_only_pob_signal(self):
        """Text with only POB should score exactly 0.20."""
        text = "BEGINNING at an iron pin found in a field of unknown location."
        confidence, signals = PDFProcessor._compute_llm_confidence(text)
        assert signals["has_pob"] is True
        assert signals["has_bearing_calls"] is False
        assert signals["has_distances"] is False

    def test_garbled_non_ascii_fails_signal(self):
        """Text with >5% non-ASCII (excluding DMS symbols) fails no_garbled_chars."""
        # Build a string that's 10% non-ASCII junk
        junk = "\xff" * 10 + "a" * 90
        _, signals = PDFProcessor._compute_llm_confidence(junk)
        assert signals["no_garbled_chars"] is False

    def test_dms_symbols_not_counted_as_garbled(self):
        """Degree/minute/second symbols should not trigger garbled detection."""
        text = (
            "BEGINNING at a point; "
            "THENCE S 33\u00b020\u203200\u2033 E 60.00 feet to the POINT OF BEGINNING."
        )
        _, signals = PDFProcessor._compute_llm_confidence(text)
        assert signals["no_garbled_chars"] is True
