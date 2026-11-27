from __future__ import annotations

from pathlib import Path

import pytest
import structlog

from metesparser.llm_clients import BaseLLMClient, LLMClientError
from metesparser.pdf_processor import PDFProcessor

_CLEAN_SQUARE = (
    "BEGINNING at an iron pin; "
    "THENCE North 0 degrees 00 minutes East 100.00 feet; "
    "THENCE South 90 degrees 00 minutes East 100.00 feet; "
    "THENCE South 0 degrees 00 minutes West 100.00 feet; "
    "THENCE North 90 degrees 00 minutes West 100.00 feet to the POINT OF BEGINNING."
)


class _DeterministicLLMClient(BaseLLMClient):
    """Deterministic fake BaseLLMClient for exercising real PDFProcessor parsing."""

    def __init__(self, *, legal_description: str) -> None:
        self._legal_description = legal_description

    def generate_text_with_pdf(
        self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
    ) -> str:
        return "RAW DEED DOCUMENT"

    def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
        return self._legal_description


def test_normalize_legal_description_uses_prompt_template(tmp_path: Path) -> None:
    class RecordingClient(BaseLLMClient):
        def __init__(self) -> None:
            self.calls = 0

        def generate_text_with_pdf(
            self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
        ) -> str:
            raise AssertionError("generate_text_with_pdf should not be called")

        def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
            self.calls += 1
            assert response_mime_type is None
            assert prompt == "SYS\n\nNormalize this legal description: line 1"
            return "normalized"

    (tmp_path / "normalize_text.yaml").write_text(
        "system_prompt: SYS\n"
        'user_prompt_template: "Normalize this legal description: {legal_description_text}"\n',
        encoding="utf-8",
    )
    client = RecordingClient()
    processor = PDFProcessor(client=client, cache=False)
    processor.prompts_dir = tmp_path

    assert processor.normalize_legal_description("line 1") == "normalized"
    assert client.calls == 1


def test_extract_calls_ai_raises_for_invalid_json() -> None:
    class InvalidJsonClient(BaseLLMClient):
        def generate_text_with_pdf(
            self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
        ) -> str:
            raise AssertionError("unexpected pdf call")

        def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
            assert response_mime_type == "application/json"
            return "not json"

    processor = PDFProcessor(client=InvalidJsonClient(), cache=False)

    with pytest.raises(ValueError, match="invalid JSON"):
        processor.extract_calls_ai("text")


def test_create_client_raises_value_error_for_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingClient:
        def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
            raise LLMClientError("broken provider")

    monkeypatch.setattr("metesparser.pdf_processor.OpenAIClient", FailingClient)
    with pytest.raises(ValueError, match="broken provider"):
        PDFProcessor(provider="openai")


def test_load_prompt_raises_file_not_found() -> None:
    processor = PDFProcessor(client=_DeterministicLLMClient(legal_description=""), cache=False)

    with pytest.raises(FileNotFoundError, match="Prompt file not found for 'does_not_exist'"):
        processor._load_prompt("does_not_exist")


def test_normalize_legal_description_raises_on_non_mapping_prompt_yaml(tmp_path: Path) -> None:
    processor = PDFProcessor(client=_DeterministicLLMClient(legal_description=""), cache=False)
    processor.prompts_dir = tmp_path
    (tmp_path / "normalize_text.yaml").write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="did not contain a mapping"):
        processor.normalize_legal_description("BEGINNING at a point.")


def test_extract_calls_ai_raises_for_non_list_calls() -> None:
    class InvalidCallsClient(BaseLLMClient):
        def generate_text_with_pdf(
            self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
        ) -> str:
            raise AssertionError("unexpected pdf call")

        def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
            return '{"calls": "string"}'

    processor = PDFProcessor(client=InvalidCallsClient(), cache=False)

    with pytest.raises(ValueError, match="malformed calls payload"):
        processor.extract_calls_ai("text")


class TestPriorConveyanceWarning:
    """Warn when extracted text contains prior conveyance language."""

    @pytest.mark.parametrize(
        "conveyance_clause,expected_pattern",
        [
            ("BEING the same premises conveyed to Grantor.", "BEING the same premises"),
            ("This land was previously conveyed by Deed Book 100.", "previously conveyed"),
            ("This parcel is derived from Lot 5.", "derived from"),
            ("See deed recorded in Book 200, Page 50.", "recorded in Book"),
            ("As conveyed by deed dated January 1, 2020.", "by deed dated"),
        ],
    )
    def test_warns_on_prior_conveyance_patterns(
        self,
        conveyance_clause: str,
        expected_pattern: str,
        tmp_path: Path,
    ) -> None:
        """Should emit structlog warning while still parsing real calls."""
        deed_text = f"{_CLEAN_SQUARE} {conveyance_clause}"
        processor = PDFProcessor(
            client=_DeterministicLLMClient(legal_description=deed_text),
            cache=False,
        )
        pdf_path = tmp_path / "deed.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

        with structlog.testing.capture_logs() as logs:
            legal_desc = processor.process_deed_pdf(str(pdf_path))

        warnings = [e for e in logs if e.get("log_level") == "warning"]
        assert legal_desc.num_calls() == 4
        assert len(warnings) == 1
        assert warnings[0]["event"] == "Extracted text may contain prior conveyance language"
        matched_patterns = warnings[0]["matched_patterns"]
        assert isinstance(matched_patterns, list)
        assert any(expected_pattern in str(p) for p in matched_patterns)

    def test_no_warning_for_clean_description(self, tmp_path: Path) -> None:
        """Should not warn when extracted text has no prior conveyance language."""
        processor = PDFProcessor(
            client=_DeterministicLLMClient(legal_description=_CLEAN_SQUARE),
            cache=False,
        )
        pdf_path = tmp_path / "deed.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

        with structlog.testing.capture_logs() as logs:
            legal_desc = processor.process_deed_pdf(str(pdf_path))

        assert legal_desc.num_calls() == 4
        assert [e for e in logs if e.get("log_level") == "warning"] == []


def test_process_deed_pdf_logs_progress_without_print(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    processor = PDFProcessor(
        client=_DeterministicLLMClient(legal_description=_CLEAN_SQUARE),
        cache=False,
    )
    pdf_path = tmp_path / "deed.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    def _unexpected_print(*args: object, **kwargs: object) -> None:
        raise AssertionError("process_deed_pdf should not call print")

    monkeypatch.setattr("builtins.print", _unexpected_print)

    with structlog.testing.capture_logs() as logs:
        legal_desc = processor.process_deed_pdf(str(pdf_path))

    assert legal_desc.num_calls() == 4
    assert [c.distance_ft for c in legal_desc.calls] == [100.0, 100.0, 100.0, 100.0]
    assert [e for e in logs if e.get("log_level") == "warning"] == []
    info_events = [e for e in logs if e.get("log_level") == "info"]
    assert [e["event"] for e in info_events] == [
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
    assert info_events[-1]["count"] == 4


def test_load_prompt_falls_back_to_packaged_resource_and_handles_missing_package(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    processor = PDFProcessor(client=_DeterministicLLMClient(legal_description=""), cache=False)
    processor.prompts_dir = tmp_path / "empty_prompts"
    processor.prompts_dir.mkdir()

    pkg_dir = tmp_path / "pkg"
    (pkg_dir / "prompts").mkdir(parents=True)
    (pkg_dir / "prompts" / "packaged_only_prompt.yaml").write_text(
        "system_prompt: packaged\nuser_prompt_template: body\n", encoding="utf-8"
    )
    monkeypatch.setattr("metesparser.pdf_processor.resources.files", lambda _pkg: pkg_dir)
    loaded = processor._load_prompt("packaged_only_prompt")
    assert loaded == {"system_prompt": "packaged", "user_prompt_template": "body"}

    def _raise_missing(_pkg: str) -> object:
        raise ModuleNotFoundError("no metesparser package resources")

    monkeypatch.setattr("metesparser.pdf_processor.resources.files", _raise_missing)
    with pytest.raises(FileNotFoundError, match="Prompt file not found"):
        processor._load_prompt("packaged_only_prompt")


def test_extract_calls_ai_rejects_non_object_json_payload() -> None:
    class ListJsonClient(BaseLLMClient):
        def generate_text_with_pdf(
            self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
        ) -> str:
            raise AssertionError("unexpected pdf call")

        def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
            return '[{"course": 1}]'

    processor = PDFProcessor(client=ListJsonClient(), cache=False)
    with pytest.raises(ValueError, match="non-object JSON payload"):
        processor.extract_calls_ai("text")


def test_process_deed_pdf_applies_supported_inferred_unit_and_warns_on_unsupported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pdf_path = tmp_path / "deed.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    # Supported inferred unit ("varas") flows naturally through real TextParser + CallExtractor.
    vara_deed = (
        "BEGINNING at a stone corner, all distances measured in varas; "
        "THENCE North 0 degrees 00 minutes East 100 varas; "
        "THENCE South 90 degrees 00 minutes East 100 varas; "
        "THENCE South 0 degrees 00 minutes West 100 varas; "
        "THENCE North 90 degrees 00 minutes West 100 varas to the POINT OF BEGINNING."
    )
    vara_processor = PDFProcessor(
        client=_DeterministicLLMClient(legal_description=vara_deed),
        cache=False,
    )
    legal_varas = vara_processor.process_deed_pdf(str(pdf_path))
    assert legal_varas.distance_unit == "varas"
    assert legal_varas.num_calls() == 4
    assert legal_varas.calls[0].distance_ft == pytest.approx(277.8, abs=1e-6)

    # Unsupported inferred unit logs a warning and falls back to feet while parsing real calls.
    fallback_processor = PDFProcessor(
        client=_DeterministicLLMClient(legal_description=_CLEAN_SQUARE),
        cache=False,
    )
    monkeypatch.setattr(
        "metesparser.text_parser.TextParser.infer_distance_unit", lambda _: "cubits"
    )
    with structlog.testing.capture_logs() as logs:
        legal_fallback = fallback_processor.process_deed_pdf(str(pdf_path))
    warnings = [e for e in logs if e.get("log_level") == "warning"]
    assert legal_fallback.distance_unit == "feet"
    assert legal_fallback.num_calls() == 4
    assert len(warnings) == 1
    assert "Unsupported inferred distance unit" in warnings[0]["event"]
    assert warnings[0]["inferred_unit"] == "cubits"


def test_compute_prompt_hash_returns_unknown_when_prompt_missing() -> None:
    processor = PDFProcessor(client=_DeterministicLLMClient(legal_description=""), cache=False)
    assert processor._compute_prompt_hash("nonexistent_prompt_xyz") == "unknown"
