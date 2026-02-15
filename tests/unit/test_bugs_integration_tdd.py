from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace

from metesparser.closure_checker import ClosureChecker
from metesparser.csv_builder import CSVBuilder
from metesparser.llm_clients import OpenAIClient
from metesparser.models import DeedCall
from metesparser.pdf_processor import PDFProcessor


class _NoopClient:
    def generate_text(self, prompt: str, *, response_mime_type: str | None = None) -> str:
        return "{}"

    def generate_text_with_pdf(
        self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
    ) -> str:
        return ""


def _load_script_module(script_name: str):
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(f"test_{script_name}", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_openai_client_forwards_json_response_format(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    openai_module = ModuleType("openai")

    class FakeResponses:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(output_text="ok")

    class FakeOpenAI:
        def __init__(self, api_key: str):
            self.responses = FakeResponses()

    openai_module.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", openai_module)

    client = OpenAIClient()
    client.generate_text("hello", response_mime_type="application/json")

    kwargs = client._client.responses.calls[0]
    assert "text" in kwargs


def test_calls_to_csv_writes_metadata_sidecar_when_metadata_provided(tmp_path: Path) -> None:
    output_path = tmp_path / "calls.csv"
    calls = [
        DeedCall(
            course=1,
            direction_text="N 45° E",
            bearing_quadrant="N 45° E",
            bearing_azimuth_deg_from_north=45.0,
            distance_ft=100.0,
        )
    ]

    CSVBuilder.calls_to_csv(calls, str(output_path), metadata={"source_doc": "example.pdf"})

    metadata_path = output_path.with_suffix(".metadata.txt")
    assert metadata_path.exists()
    assert "source_doc: example.pdf" in metadata_path.read_text()


def test_zero_delta_curve_values_are_valid_and_not_dropped_in_serialization() -> None:
    call = DeedCall(
        course=1,
        direction_text="curve",
        bearing_azimuth_deg_from_north=0.0,
        distance_ft=100.0,
        curve_dir="left",
        radius_ft=50.0,
        delta_deg=0.0,
        arc_length_ft=0.0,
        chord_length_ft=0.0,
    )

    row = CSVBuilder._call_to_row(call)
    assert row["delta_deg"] == "0.000000"
    assert row["arc_length_ft"] == "0.00"
    assert row["chord_length_ft"] == "0.00"


def test_compute_traverse_keeps_zero_delta_curve_call() -> None:
    calls = [
        DeedCall(
            course=1,
            direction_text="curve",
            bearing_azimuth_deg_from_north=0.0,
            distance_ft=100.0,
            curve_dir="left",
            radius_ft=50.0,
            delta_deg=0.0,
            arc_length_ft=0.0,
            chord_length_ft=0.0,
        )
    ]

    points = ClosureChecker.compute_traverse(calls)
    assert len(points) == 2


def test_pdf_processor_loads_prompts_when_filesystem_prompt_dir_missing(tmp_path: Path) -> None:
    processor = PDFProcessor(client=_NoopClient())
    processor.prompts_dir = tmp_path / "missing-prompts"

    prompt = processor._load_prompt("normalize_text")
    assert isinstance(prompt, dict)
    assert "system_prompt" in prompt


def test_extract_sample_deeds_script_points_to_repo_sample_deeds() -> None:
    module = _load_script_module("extract_sample_deeds.py")
    expected = Path(module.__file__).resolve().parent.parent / "sample_deeds"
    assert module.SAMPLE_DEEDS_DIR == expected


def test_generate_ground_truth_notes_uses_runtime_timestamp(tmp_path: Path) -> None:
    module = _load_script_module("generate_ground_truth.py")

    class FakeProcessor:
        def extract_text_from_pdf(self, pdf_path: str) -> str:
            return "RAW"

        def extract_legal_description(self, pdf_path: str) -> str:
            return "THENCE N 45° E 100 feet to a point"

        def normalize_legal_description(self, legal_desc_text: str) -> str:
            return legal_desc_text

    pdf_path = tmp_path / "example.pdf"
    pdf_path.write_bytes(b"%PDF")

    result = module.generate_ground_truth(pdf_path, FakeProcessor())
    notes = result["notes"]

    assert notes.startswith("Ground truth generated at ")
    timestamp = notes.removeprefix("Ground truth generated at ")
    datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


def test_root_package_exports_documented_public_classes() -> None:
    import metesparser

    assert hasattr(metesparser, "PDFProcessor")
    assert hasattr(metesparser, "ClosureChecker")
    assert hasattr(metesparser, "CallExtractor")
    assert hasattr(metesparser, "CSVBuilder")
    assert hasattr(metesparser, "TextParser")
    assert hasattr(metesparser, "LegalDescription")
