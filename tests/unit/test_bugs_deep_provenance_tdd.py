"""Deep regressions for cache validation, run identity, and OCR provenance."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from mp_ocr.cache import CachedLLMClient as PackageCachedClient

from metesparser.llm_cache import CachedLLMClient as MonolithCachedClient
from metesparser.run_registry import RunManifest, RunResults, write_run_manifest


class FakeClient:
    model = "fake-model"

    def __init__(self, text: str = "fresh text", pdf_text: str = "fresh pdf") -> None:
        self.text = text
        self.pdf_text = pdf_text
        self.text_calls = 0
        self.pdf_calls = 0

    def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
        self.text_calls += 1
        return self.text

    def generate_text_with_pdf(
        self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
    ) -> str:
        self.pdf_calls += 1
        return self.pdf_text


@pytest.mark.parametrize("cache_type", [MonolithCachedClient, PackageCachedClient])
@pytest.mark.parametrize(
    "bad_payload",
    [
        "[]",
        '{"other": "missing response"}',
        '{"response": []}',
        '{"response": null}',
        '{"response": 42}',
        "not json",
    ],
)
def test_invalid_cache_shapes_refresh_text_and_pdf(
    tmp_path: Path, cache_type: Any, bad_payload: str
) -> None:
    cache_dir = tmp_path / "cache"
    pdf = tmp_path / "deed.pdf"
    pdf.write_bytes(b"small fake pdf")
    fake = FakeClient()
    cache = cache_type(fake, cache_dir)

    text_key = cache._cache_key("prompt", None)
    pdf_key = cache._cache_key("pdf prompt", None, pdf.read_bytes())
    cache._cache_path(text_key).write_text(bad_payload)
    cache._cache_path(pdf_key).write_text(bad_payload)

    assert cache.generate_text("prompt") == "fresh text"
    assert cache.generate_text_with_pdf("pdf prompt", str(pdf)) == "fresh pdf"
    assert fake.text_calls == fake.pdf_calls == 1
    assert json.loads(cache._cache_path(text_key).read_text())["response"] == "fresh text"
    assert json.loads(cache._cache_path(pdf_key).read_text())["response"] == "fresh pdf"


@pytest.mark.parametrize("cache_type", [MonolithCachedClient, PackageCachedClient])
def test_invalid_utf8_cache_refreshes_text_and_pdf(tmp_path: Path, cache_type: Any) -> None:
    cache_dir = tmp_path / "cache"
    pdf = tmp_path / "deed.pdf"
    pdf.write_bytes(b"small fake pdf")
    fake = FakeClient()
    cache = cache_type(fake, cache_dir)

    text_key = cache._cache_key("prompt", None)
    pdf_key = cache._cache_key("pdf prompt", None, pdf.read_bytes())
    cache._cache_path(text_key).write_bytes(b'{"response": \xff}')
    cache._cache_path(pdf_key).write_bytes(b'{"response": \xff}')

    assert cache.generate_text("prompt") == "fresh text"
    assert cache.generate_text_with_pdf("pdf prompt", str(pdf)) == "fresh pdf"
    assert fake.text_calls == fake.pdf_calls == 1


def test_manifest_filename_preserves_distinct_run_ids_at_same_timestamp(tmp_path: Path) -> None:
    base = {
        "timestamp_utc": datetime(2026, 2, 16, 15, 30, 0, tzinfo=UTC),
        "source_pdf": "same deed.pdf",
        "llm_provider": "fake",
        "llm_model": "fake-model",
        "cache_enabled": False,
        "prompt_versions": {},
        "results": RunResults(
            call_count=1,
            closure_passed=True,
            misclosure_ft=0.0,
            area_sq_ft=100.0,
            confidence_score=1.0,
            warnings=[],
        ),
        "parser_version": "test",
    }
    first = RunManifest(run_id="run-one", **base)
    second = RunManifest(run_id="run-two", **base)

    path_one = write_run_manifest(first, tmp_path)
    path_two = write_run_manifest(second, tmp_path)

    assert path_one != path_two
    assert json.loads(path_one.read_text())["run_id"] == "run-one"
    assert json.loads(path_two.read_text())["run_id"] == "run-two"


def test_manifest_filename_length_does_not_depend_on_run_id_length(tmp_path: Path) -> None:
    manifest = RunManifest(
        run_id="run-" + "a" * 1000,
        timestamp_utc=datetime(2026, 2, 16, tzinfo=UTC),
        source_pdf="deed.pdf",
        llm_provider="fake",
        llm_model="fake",
        cache_enabled=False,
        parser_version="test",
        results=RunResults(
            call_count=4, closure_passed=True, misclosure_ft=0, area_sq_ft=10000, confidence_score=1
        ),
    )
    path = write_run_manifest(manifest, tmp_path)
    assert path.parent == tmp_path
    assert len(path.name.encode()) <= 255
    assert json.loads(path.read_text())["run_id"] == manifest.run_id


def test_manifest_filename_distinguishes_ids_with_same_sanitized_form(tmp_path: Path) -> None:
    base = {
        "timestamp_utc": datetime(2026, 2, 16, 15, 30, 0, tzinfo=UTC),
        "source_pdf": "same deed.pdf",
        "llm_provider": "fake",
        "llm_model": "fake-model",
        "cache_enabled": False,
        "prompt_versions": {},
        "results": RunResults(
            call_count=1,
            closure_passed=True,
            misclosure_ft=0.0,
            area_sq_ft=100.0,
            confidence_score=1.0,
            warnings=[],
        ),
        "parser_version": "test",
    }
    path_one = write_run_manifest(RunManifest(run_id="run/id", **base), tmp_path)
    path_two = write_run_manifest(RunManifest(run_id="run?id", **base), tmp_path)

    assert path_one != path_two
    assert len(path_one.name) < 100
    assert len(path_two.name) < 100
    assert json.loads(path_one.read_text())["run_id"] == "run/id"
    assert json.loads(path_two.read_text())["run_id"] == "run?id"


class PipelineFakeClient(FakeClient):
    def __init__(self) -> None:
        super().__init__()
        self.responses = iter(
            [
                "ORIGINAL OCR RESPONSE",
                "BEGINNING at an iron pin; thence North 10 degrees East 100 feet;",
                "BEGINNING at an iron pin; thence North 10 degrees East 100 feet;",
            ]
        )
        self.prompts: list[str] = []

    def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
        self.prompts.append(prompt)
        return next(self.responses)

    def generate_text_with_pdf(
        self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
    ) -> str:
        self.prompts.append(prompt)
        return next(self.responses)


@pytest.mark.parametrize("processor_type", ["monolith", "package"])
def test_audited_pipeline_retains_each_rendered_llm_exchange(
    tmp_path: Path, processor_type: str
) -> None:
    from mp_ocr.extract import PDFProcessor as PackageProcessor

    from metesparser.pdf_processor import PDFProcessor as MonolithProcessor

    processor_cls = MonolithProcessor if processor_type == "monolith" else PackageProcessor
    client = PipelineFakeClient()
    processor = processor_cls(client=client, cache=False)
    if processor_type == "monolith":
        _, context = processor.process_deed_pdf(str(tmp_path / "deed.pdf"), audit=True)
    else:
        # mp-ocr intentionally exposes standalone extraction methods; the orchestrator
        # owns when audited collection starts and passes that evidence into the builder.
        legal_text = processor.extract_legal_description(str(tmp_path / "deed.pdf"), audit=True)
        normalized = processor.normalize_legal_description(legal_text, audit=True)
        context = processor._build_audit_context(
            pdf_path=str(tmp_path / "deed.pdf"),
            legal_desc_text=legal_text,
            normalized_text=normalized,
            distance_unit="feet",
        )

    record = context.extraction_record
    assert record is not None
    assert (
        record.raw_llm_response
        == "BEGINNING at an iron pin; thence North 10 degrees East 100 feet;"
    )
    stages = record.llm_stages
    assert [stage.stage for stage in stages] == [
        "extract_text_from_pdf",
        "extract_legal_description",
        "normalize_text",
    ]
    assert stages[0].response == "ORIGINAL OCR RESPONSE"
    assert "ORIGINAL OCR RESPONSE" in stages[1].prompt
    assert "BEGINNING at an iron pin" in stages[2].prompt
    for stage in stages:
        assert stage.prompt_sha256 == hashlib.sha256(stage.prompt.encode()).hexdigest(), stage.stage
        assert stage.response_sha256 == hashlib.sha256(stage.response.encode()).hexdigest(), (
            stage.stage
        )
    assert all(stage.provider == "unknown" and stage.model == "fake-model" for stage in stages)


def test_reused_processor_starts_a_fresh_audit_stage_list(tmp_path: Path) -> None:
    from metesparser.pdf_processor import PDFProcessor

    client = PipelineFakeClient()
    processor = PDFProcessor(client=client, cache=False)
    _, first = processor.process_deed_pdf(str(tmp_path / "first.pdf"), audit=True)
    client.responses = iter(
        [
            "SECOND OCR RESPONSE",
            "SECOND LEGAL DESCRIPTION",
            "SECOND NORMALIZED DESCRIPTION",
        ]
    )
    _, second = processor.process_deed_pdf(str(tmp_path / "second.pdf"), audit=True)

    assert first.extraction_record is not None
    assert second.extraction_record is not None
    assert first.extraction_record.llm_stages[0].response == "ORIGINAL OCR RESPONSE"
    assert second.extraction_record.llm_stages[0].response == "SECOND OCR RESPONSE"
    assert len(second.extraction_record.llm_stages) == 3
    assert processor._audit_stage_records is None


def test_failed_audit_cannot_leak_into_later_non_audited_calls(monkeypatch: Any) -> None:
    from mp_ocr.extract import PDFProcessor

    client = PipelineFakeClient()
    processor = PDFProcessor(client=client, cache=False)
    monkeypatch.setattr(
        processor,
        "_load_prompt",
        lambda _name: (_ for _ in ()).throw(FileNotFoundError("missing prompt")),
    )

    with pytest.raises(FileNotFoundError):
        processor.normalize_legal_description("input", audit=True)

    processor._load_prompt = lambda _name: {
        "user_prompt_template": "OCR",
        "response_mime_type": None,
    }
    assert processor.extract_text_from_pdf("other.pdf") == "ORIGINAL OCR RESPONSE"
    assert processor._audit_stage_records is None
