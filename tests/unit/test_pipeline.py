"""End-to-end behavioral tests for metesparser.pipeline — Pipeline orchestrator."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest
from mp_models import AuditContext, ClosureResult

from metesparser.llm_clients import BaseLLMClient
from metesparser.pipeline import Pipeline, PipelineResult

_SQUARE_100_DEED = (
    "BEGINNING at an iron pin found at the southwest corner; "
    "THENCE North 0 degrees 00 minutes East 100.00 feet to an iron pin; "
    "THENCE South 90 degrees 00 minutes East 100.00 feet to an iron pin; "
    "THENCE South 0 degrees 00 minutes West 100.00 feet to an iron pin; "
    "THENCE North 90 degrees 00 minutes West 100.00 feet to the POINT OF BEGINNING. "
    "CONTAINING 10,000 square feet."
)

_TWO_TRACT_DEED = (
    "TRACT #1: BEGINNING at a point; "
    "THENCE North 0 degrees 00 minutes East 100.00 feet; "
    "THENCE South 90 degrees 00 minutes East 100.00 feet; "
    "THENCE South 0 degrees 00 minutes West 100.00 feet; "
    "THENCE North 90 degrees 00 minutes West 100.00 feet to the POINT OF BEGINNING. "
    "TRACT #2: BEGINNING at a point; "
    "THENCE North 0 degrees 00 minutes East 50.00 feet; "
    "THENCE South 90 degrees 00 minutes East 50.00 feet; "
    "THENCE South 0 degrees 00 minutes West 50.00 feet; "
    "THENCE North 90 degrees 00 minutes West 50.00 feet to the POINT OF BEGINNING."
)

_TRACT_WITH_EASEMENT_DEED = (
    "TRACT #1: BEGINNING at a point; "
    "THENCE North 0 degrees 00 minutes East 100.00 feet; "
    "THENCE South 90 degrees 00 minutes East 100.00 feet; "
    "THENCE South 0 degrees 00 minutes West 100.00 feet; "
    "THENCE North 90 degrees 00 minutes West 100.00 feet to the POINT OF BEGINNING. "
    "CONTAINING 50,000 square feet. "
    "TOGETHER WITH AN EASEMENT: BEGINNING at a point; "
    "THENCE North 0 degrees 00 minutes East 20.00 feet; "
    "THENCE South 90 degrees 00 minutes East 20.00 feet; "
    "THENCE South 0 degrees 00 minutes West 20.00 feet; "
    "THENCE North 90 degrees 00 minutes West 20.00 feet to the POINT OF BEGINNING."
)


def _make_fake_provider_cls(
    *,
    legal_description: str,
    model_name: str,
    call_log: list[tuple[str, str]],
) -> type[BaseLLMClient]:
    """Build a deterministic fake LLM client class at the provider SDK boundary."""

    class _FakeProviderClient(BaseLLMClient):
        def __init__(self, api_key: str | None = None, **_kwargs: Any) -> None:
            self.api_key = api_key
            self.model = model_name

        def generate_text_with_pdf(
            self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
        ) -> str:
            call_log.append(("pdf", Path(pdf_path).name))
            return f"OCR TEXT FOR {Path(pdf_path).name}\n{legal_description}"

        def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
            call_log.append(("text", model_name))
            return legal_description

    return _FakeProviderClient


class TestPipelineRun:
    """Pipeline.run() executes OCR -> parse -> verify end-to-end without exporting CSV."""

    def test_default_run_verifies_square_uses_openai_cache_and_writes_no_csv(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        call_log: list[tuple[str, str]] = []
        fake_openai = _make_fake_provider_cls(
            legal_description=_SQUARE_100_DEED,
            model_name="fake-openai-model",
            call_log=call_log,
        )
        monkeypatch.setattr("metesparser.pdf_processor.OpenAIClient", fake_openai)
        monkeypatch.setenv("METESPARSER_CACHE_DIR", str(tmp_path / "llm_cache"))

        pdf_path = tmp_path / "square_deed.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

        pipe = Pipeline()
        first = pipe.run(pdf_path)

        assert isinstance(first, ClosureResult)
        assert first.closure_passed is True
        assert first.is_fully_verified() is True
        assert first.misclosure_ft == pytest.approx(0.0, abs=1e-6)
        assert first.area_sq_ft == pytest.approx(10000.0, abs=1e-6)
        assert first.perimeter_ft == pytest.approx(400.0, abs=1e-6)
        assert len(call_log) == 3  # OCR + extract_legal + normalize

        # Default cache=True serves the second run without invoking the provider again.
        second = pipe.run(pdf_path)
        assert isinstance(second, ClosureResult)
        assert second.area_sq_ft == pytest.approx(10000.0, abs=1e-6)
        assert len(call_log) == 3

        # Pipeline.run() never writes CSV exports or sidecar files alongside the PDF.
        assert sorted(p.name for p in tmp_path.iterdir()) == ["llm_cache", "square_deed.pdf"]

    def test_custom_provider_cache_disabled_and_audit_context(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        call_log: list[tuple[str, str]] = []
        fake_gemini = _make_fake_provider_cls(
            legal_description=_SQUARE_100_DEED,
            model_name="fake-gemini-model",
            call_log=call_log,
        )
        monkeypatch.setattr("metesparser.pdf_processor.GeminiClient", fake_gemini)
        monkeypatch.setenv("METESPARSER_CACHE_DIR", str(tmp_path / "llm_cache"))

        pdf_path = tmp_path / "gemini_deed.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

        pipe = Pipeline(provider="gemini", cache=False, audit=True)
        result = pipe.run(pdf_path)

        assert isinstance(result, tuple)
        closure, audit_ctx = result
        assert isinstance(closure, ClosureResult)
        assert isinstance(audit_ctx, AuditContext)

        assert closure.closure_passed is True
        assert closure.area_sq_ft == pytest.approx(10000.0, abs=1e-6)
        assert audit_ctx.run_metadata.llm_provider == "gemini"
        assert audit_ctx.run_metadata.llm_model == "fake-gemini-model"
        assert audit_ctx.run_metadata.cache_enabled is False
        assert audit_ctx.run_metadata.source_pdf == "gemini_deed.pdf"
        assert audit_ctx.extraction_record is not None
        assert [s.stage for s in audit_ctx.extraction_record.llm_stages] == [
            "extract_text_from_pdf",
            "extract_legal_description",
            "normalize_text",
        ]
        assert len(audit_ctx.call_audits) == 4
        assert audit_ctx.verification_audit is not None
        assert any(
            c.name == "traverse_closure" and c.status == "passed"
            for c in audit_ctx.verification_audit.checks
        )

        # With cache=False, a second run invokes the provider again and creates no cache/CSV.
        pipe.run(pdf_path)
        assert len(call_log) == 6
        assert sorted(p.name for p in tmp_path.iterdir()) == ["gemini_deed.pdf"]


class TestPipelineMultiTract:
    """Pipeline verifies each tract independently for multi-tract deeds."""

    def test_multi_tract_returns_per_tract_closure_results_and_audit(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        call_log: list[tuple[str, str]] = []
        fake_openai = _make_fake_provider_cls(
            legal_description=_TWO_TRACT_DEED,
            model_name="fake-openai-model",
            call_log=call_log,
        )
        monkeypatch.setattr("metesparser.pdf_processor.OpenAIClient", fake_openai)

        pdf_path = tmp_path / "two_tracts.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

        results = Pipeline(provider="openai", cache=False).run(pdf_path)
        assert isinstance(results, list)
        assert len(results) == 2
        assert all(r.closure_passed is True for r in results)
        assert results[0].area_sq_ft == pytest.approx(10000.0, abs=1e-6)
        assert results[1].area_sq_ft == pytest.approx(2500.0, abs=1e-6)
        assert results[0].perimeter_ft == pytest.approx(400.0, abs=1e-6)
        assert results[1].perimeter_ft == pytest.approx(200.0, abs=1e-6)

        audited = Pipeline(provider="openai", cache=False, audit=True).run(pdf_path)
        assert isinstance(audited, tuple)
        audited_results, audit_ctx = audited
        assert isinstance(audited_results, list)
        assert len(audited_results) == 2
        assert isinstance(audit_ctx, AuditContext)
        assert len(audit_ctx.call_audits) == 8
        assert [a.tract_label for a in audit_ctx.tract_verification_audits] == [
            "Tract 1",
            "Tract 2",
        ]
        assert list(tmp_path.glob("*.csv")) == []

    def test_multi_tract_with_single_boundary_stated_area_passes_area_to_verify(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import metesparser.pipeline as pipeline_mod

        call_log: list[tuple[str, str]] = []
        fake_openai = _make_fake_provider_cls(
            legal_description=_TRACT_WITH_EASEMENT_DEED,
            model_name="fake-openai-model",
            call_log=call_log,
        )
        monkeypatch.setattr("metesparser.pdf_processor.OpenAIClient", fake_openai)

        forwarded_stated_areas: list[float | None] = []
        real_verify = pipeline_mod.verify_closure

        def _spy_verify(*args: Any, **kwargs: Any) -> Any:
            forwarded_stated_areas.append(kwargs.get("stated_area_sq_ft"))
            return real_verify(*args, **kwargs)

        monkeypatch.setattr(pipeline_mod, "verify_closure", _spy_verify)

        pdf_path = tmp_path / "tract_with_easement.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

        results = Pipeline(provider="openai", cache=False).run(pdf_path)
        assert isinstance(results, list)
        assert len(results) == 2
        main_result, easement_result = results
        assert forwarded_stated_areas == [50000.0]
        assert main_result.closure_passed is True
        assert main_result.area_sq_ft == pytest.approx(10000.0, abs=1e-6)
        assert easement_result.closure_passed is True
        assert easement_result.area_sq_ft == pytest.approx(400.0, abs=1e-6)
        assert any(
            c.name == "non_boundary_tract" and c.status == "blocked" for c in easement_result.checks
        )
        assert any(
            c.name == "description_roles_inferred" and c.status == "blocked"
            for c in main_result.checks
        )
        # Single-boundary stated area (50,000 sq ft vs 10,000 sq ft computed) must fail
        # area_reasonableness on the boundary tract and remain not_applicable on the easement.
        assert any(
            c.name == "area_reasonableness" and c.status == "failed" for c in main_result.checks
        )
        assert any(
            c.name == "area_reasonableness" and c.status == "not_applicable"
            for c in easement_result.checks
        )
        assert list(tmp_path.glob("*.csv")) == []


class TestPipelineRunDetailed:
    """Pipeline.run_detailed() returns a frozen PipelineResult matching Pipeline.run()."""

    def test_run_detailed_returns_frozen_pipeline_result_and_matches_run_single_tract(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        call_log: list[tuple[str, str]] = []
        fake_openai = _make_fake_provider_cls(
            legal_description=_SQUARE_100_DEED,
            model_name="fake-openai-model",
            call_log=call_log,
        )
        monkeypatch.setattr("metesparser.pdf_processor.OpenAIClient", fake_openai)

        pdf_path = tmp_path / "square_deed.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

        pipe = Pipeline(provider="openai", cache=False, audit=False)
        detailed = pipe.run_detailed(pdf_path)

        assert isinstance(detailed, PipelineResult)
        with pytest.raises(FrozenInstanceError):
            detailed.provider = "gemini"  # type: ignore[misc]

        assert detailed.pdf_path == pdf_path
        assert detailed.is_multi_tract is False
        assert isinstance(detailed.closure, ClosureResult)
        assert detailed.closure.closure_passed is True
        assert detailed.closure.is_fully_verified() is True
        assert detailed.closure_results == (detailed.closure,)
        assert isinstance(detailed.calls, tuple)
        assert len(detailed.calls) == 4
        assert detailed.tract_results == ()
        assert detailed.audit_context is None
        assert detailed.raw_llm_response is None
        assert detailed.normalized_text is None
        assert detailed.escalation_report is not None
        assert detailed.escalation_report.triggered is False
        assert detailed.escalation_report.policy == "never"
        assert pipe.last_escalation_report == detailed.escalation_report
        assert detailed.provider == "openai"
        assert detailed.primary_model == "fake-openai-model"
        assert detailed.prompts_dir is not None and detailed.prompts_dir.exists()

        legacy = pipe.run(pdf_path)
        assert isinstance(legacy, ClosureResult)
        assert legacy == detailed.closure
        assert sorted(p.name for p in tmp_path.iterdir()) == ["square_deed.pdf"]

    def test_run_detailed_with_audit_and_multi_tract_exposes_tracts_and_text(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        call_log: list[tuple[str, str]] = []
        fake_gemini = _make_fake_provider_cls(
            legal_description=_TWO_TRACT_DEED,
            model_name="fake-gemini-model",
            call_log=call_log,
        )
        monkeypatch.setattr("metesparser.pdf_processor.GeminiClient", fake_gemini)

        pdf_path = tmp_path / "two_tracts.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

        pipe = Pipeline(provider="gemini", cache=False, audit=True)
        detailed = pipe.run_detailed(str(pdf_path))

        assert isinstance(detailed, PipelineResult)
        assert detailed.pdf_path == pdf_path
        assert detailed.is_multi_tract is True
        assert isinstance(detailed.closure, tuple)
        assert len(detailed.closure) == 2
        assert detailed.closure_results == detailed.closure
        assert isinstance(detailed.calls, tuple)
        assert len(detailed.calls) == 8
        assert len(detailed.tract_results) == 2
        assert [t.label for t, _ in detailed.tract_results] == ["Tract 1", "Tract 2"]
        assert all(res.closure_passed is True for _, res in detailed.tract_results)
        assert detailed.audit_context is not None
        assert detailed.audit_context.run_metadata.llm_provider == "gemini"
        assert detailed.audit_context.run_metadata.llm_model == "fake-gemini-model"
        assert detailed.raw_llm_response is not None and "TRACT #1" in detailed.raw_llm_response
        assert detailed.normalized_text is not None and "TRACT #1" in detailed.normalized_text
        assert detailed.provider == "gemini"
        assert detailed.primary_model == "fake-gemini-model"
        assert detailed.escalation_report is not None
        assert detailed.escalation_report.triggered is False

        legacy = pipe.run(pdf_path)
        assert isinstance(legacy, tuple)
        legacy_closures, legacy_ctx = legacy
        assert isinstance(legacy_closures, list)
        assert legacy_closures == list(detailed.closure)
        assert legacy_ctx.run_metadata.llm_provider == "gemini"
        assert sorted(p.name for p in tmp_path.iterdir()) == ["two_tracts.pdf"]
