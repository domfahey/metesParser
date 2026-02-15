from __future__ import annotations

import pytest

from metesparser.llm_clients import LLMClientError
from metesparser.pdf_processor import PDFProcessor


def test_normalize_legal_description_uses_prompt_template(monkeypatch):
    class RecordingClient:
        def __init__(self):
            self.calls = 0

        def generate_text(self, prompt: str, response_mime_type: str | None = None):
            self.calls += 1
            assert response_mime_type is None
            assert "Normalize this legal description" in prompt
            return "normalized"

    processor = PDFProcessor(client=RecordingClient())
    monkeypatch.setattr(
        processor,
        "_load_prompt",
        lambda _: {
            "system_prompt": "SYS",
            "user_prompt_template": "Normalize this legal description: {legal_description_text}",
        },
    )

    assert processor.normalize_legal_description("line 1") == "normalized"


def test_extract_calls_ai_raises_for_invalid_json(monkeypatch):
    class InvalidJsonClient:
        def generate_text(self, prompt: str, response_mime_type: str | None = None):
            return "not json"

    processor = PDFProcessor(client=InvalidJsonClient())

    with pytest.raises(ValueError, match="invalid JSON"):
        processor.extract_calls_ai("text")


def test_create_client_raises_value_error_for_client_error(monkeypatch):
    class FailingClient:
        def __init__(self, api_key=None, model=None):
            raise LLMClientError("broken provider")

    monkeypatch.setattr("metesparser.pdf_processor.OpenAIClient", FailingClient)
    with pytest.raises(ValueError, match="broken provider"):
        PDFProcessor(provider="openai")


def test_load_prompt_raises_file_not_found():
    class DummyClient:
        pass

    processor = PDFProcessor(client=DummyClient())

    with pytest.raises(FileNotFoundError, match="Prompt file not found for 'does_not_exist'"):
        processor._load_prompt("does_not_exist")


def test_load_prompt_raises_on_non_mapping_yaml(tmp_path):
    class DummyClient:
        pass

    processor = PDFProcessor(client=DummyClient())
    processor.prompts_dir = tmp_path

    (tmp_path / "bad_prompt.yaml").write_text("[]")

    with pytest.raises(ValueError, match="did not contain a mapping"):
        processor._load_prompt("bad_prompt")


def test_extract_calls_ai_raises_for_non_list_calls():
    class InvalidCallsClient:
        def generate_text(self, prompt: str, response_mime_type: str | None = None):
            return '{"calls": "string"}'

    processor = PDFProcessor(client=InvalidCallsClient())

    with pytest.raises(ValueError, match="malformed calls payload"):
        processor.extract_calls_ai("text")
