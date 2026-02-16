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

    processor = PDFProcessor(client=InvalidCallsClient(), cache=False)

    with pytest.raises(ValueError, match="malformed calls payload"):
        processor.extract_calls_ai("text")


def test_process_deed_pdf_logs_progress_without_print(monkeypatch, tmp_path):
    class DummyClient:
        pass

    processor = PDFProcessor(client=DummyClient())
    pdf_path = tmp_path / "deed.pdf"
    pdf_path.write_text("pdf")

    monkeypatch.setattr(processor, "extract_legal_description", lambda _: "LEGAL")
    monkeypatch.setattr(processor, "normalize_legal_description", lambda _: "NORMALIZED")
    monkeypatch.setattr("metesparser.text_parser.TextParser.extract_plss_metadata", lambda _: {})
    monkeypatch.setattr(
        "metesparser.text_parser.TextParser.extract_poc_and_pob", lambda _: ("POC", "POB")
    )
    monkeypatch.setattr("metesparser.text_parser.TextParser.extract_area_statement", lambda _: None)
    monkeypatch.setattr("metesparser.text_parser.TextParser.infer_distance_unit", lambda _: None)
    monkeypatch.setattr(
        "metesparser.call_extractor.CallExtractor.extract_calls", lambda _, distance_unit="feet": []
    )
    monkeypatch.setattr(
        "metesparser.call_extractor.CallExtractor.enrich_calls_with_azimuths",
        lambda calls: calls,
    )
    monkeypatch.setattr(
        "metesparser.call_extractor.CallExtractor.mark_tie_in_calls",
        lambda calls, poc_description: calls,
    )
    monkeypatch.setattr(
        "metesparser.text_parser.TextParser.extract_basis_of_bearing", lambda _: None
    )
    monkeypatch.setattr(
        "metesparser.text_parser.TextParser.extract_surveyor_certification", lambda _: None
    )
    monkeypatch.setattr(
        "metesparser.text_parser.TextParser.extract_prior_conveyance", lambda _: None
    )
    monkeypatch.setattr("metesparser.text_parser.TextParser.extract_deed_clauses", lambda _: [])
    monkeypatch.setattr(
        "metesparser.text_parser.TextParser.extract_subdivision_reference", lambda _: None
    )
    monkeypatch.setattr("metesparser.text_parser.TextParser.extract_witness_trees", lambda _: [])
    monkeypatch.setattr(
        "metesparser.text_parser.TextParser.extract_coordinate_system", lambda _: (None, None)
    )

    captured_events: list[tuple[str, dict[str, object]]] = []

    class RecordingLogger:
        def bind(self, **kwargs: object) -> RecordingLogger:
            return self

        def info(self, event: str, **kwargs: object) -> None:
            captured_events.append((event, kwargs))

    monkeypatch.setattr("metesparser.pdf_processor.logger", RecordingLogger())

    def _unexpected_print(*args: object, **kwargs: object) -> None:
        raise AssertionError("process_deed_pdf should not call print")

    monkeypatch.setattr("builtins.print", _unexpected_print)

    legal_desc = processor.process_deed_pdf(str(pdf_path))

    assert legal_desc.num_calls() == 0
    assert [event for event, _ in captured_events] == [
        "Extracting legal description from PDF",
        "Normalizing text",
        "Extracting PLSS metadata",
        "Extracting Point of Commencement and Point of Beginning",
        "Extracting area statement",
        "Inferring distance unit",
        "Distance unit resolved",
        "Extracting calls",
        "Marking tie-in calls",
        "Extracting deed clauses",
        "Extracting subdivision reference",
        "Extracting witness trees",
        "Extracting coordinate system",
        "Extracted calls",
    ]
    assert captured_events[-1][1]["count"] == 0
