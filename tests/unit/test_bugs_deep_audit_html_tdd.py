"""Ensure captured LLM provenance is visible and escaped in exported audit reports."""

import hashlib
import html
from datetime import UTC, datetime

import mp_models
import pytest
from mp_export.audit_html import generate_html

from metesparser import models
from metesparser.audit_reporter import AuditReporter


@pytest.mark.parametrize(
    "model_module,render", [(mp_models, generate_html), (models, AuditReporter.generate_html)]
)
def test_audit_report_displays_each_llm_prompt_response_and_fingerprint(model_module, render):
    prompt = "Render <prompt> & preserve its text"
    response = "Original OCR <response> & boundary"
    stage = model_module.LLMStageRecord(
        stage="extract_text_from_pdf",
        prompt=prompt,
        prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
        response=response,
        response_sha256=hashlib.sha256(response.encode()).hexdigest(),
        provider="test-provider",
        model="test-model",
    )
    ctx = model_module.AuditContext(
        run_metadata=model_module.RunMetadata(
            parser_version="test",
            llm_provider="test",
            llm_model="test",
            prompt_hash="legacy",
            timestamp_utc=datetime.now(UTC),
            source_pdf="deed.pdf",
            cache_enabled=False,
        ),
        extraction_record=model_module.ExtractionRecord(
            raw_llm_response="legal description", normalized_text="normalized", llm_stages=[stage]
        ),
    )
    report = render(ctx)
    for value in (
        stage.stage,
        prompt,
        response,
        stage.prompt_sha256,
        stage.response_sha256,
        stage.provider,
        stage.model,
    ):
        assert html.escape(value) in report
    assert prompt not in report
    assert response not in report
