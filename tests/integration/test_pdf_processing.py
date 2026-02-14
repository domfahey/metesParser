"""Integration tests for `PDFProcessor` using mocked OpenAI responses.

These tests exercise the high-level PDF pipeline without making network calls.
They patch the OpenAI client entry points and feed deterministic deed text
fixtures so contributors can run the suite locally and in CI.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import pytest

from metesparser.closure_checker import ClosureChecker
from metesparser.models import LegalDescription
from metesparser.pdf_processor import PDFProcessor
from metesparser.text_parser import TextParser

from ..fixtures import sample_deeds


@dataclass(frozen=True)
class PdfCase:
    """Container for mocked PDF extraction expectations."""

    case_id: str
    raw_text: str
    expected_distances: list[float]
    expected_azimuths: list[float]
    expected_area_sq_ft: float
    expected_perimeter_ft: float

    @property
    def normalized_text(self) -> str:
        """Pre-compute normalized text for the mocked pipeline."""
        return TextParser.normalize_legal_description(self.raw_text)


PDF_CASES: tuple[PdfCase, ...] = (
    PdfCase(
        case_id="square-100ft",
        raw_text=sample_deeds.SQUARE_100FT,
        expected_distances=[100.0, 100.0, 100.0, 100.0],
        expected_azimuths=[0.0, 90.0, 180.0, 270.0],
        expected_area_sq_ft=10000.0,
        expected_perimeter_ft=400.0,
    ),
    PdfCase(
        case_id="pennbrook-18",
        raw_text=sample_deeds.PENNBROOK_18,
        expected_distances=[60.0, 125.0, 60.0, 125.0],
        expected_azimuths=[146.666667, 236.666667, 326.666667, 56.666667],
        expected_area_sq_ft=7500.0,
        expected_perimeter_ft=370.0,
    ),
    PdfCase(
        case_id="pennbrook-24",
        raw_text=sample_deeds.PENNBROOK_24,
        expected_distances=[125.0, 142.0, 125.0, 142.0],
        expected_azimuths=[233.848889, 143.848889, 53.848889, 323.848889],
        expected_area_sq_ft=17750.0,
        expected_perimeter_ft=534.0,
    ),
)


@pytest.fixture
def pdf_processor_factory(monkeypatch: pytest.MonkeyPatch):
    """Return a factory that builds a `PDFProcessor` with mocked OpenAI calls."""

    class DummyOpenAIClient:
        def __init__(self, api_key: str | None = None, model: str | None = None):
            self.api_key = api_key
            self.model = model

        def generate_text(
            self, prompt: str, *, response_mime_type: str | None = None
        ) -> str:  # pragma: no cover - defensive stub
            return ""

        def generate_text_with_pdf(
            self, prompt: str, pdf_path: str, *, response_mime_type: str | None = None
        ) -> str:  # pragma: no cover - defensive stub
            return ""

    def factory(case: PdfCase) -> PDFProcessor:
        # Patch OpenAI so PDFProcessor can be constructed without real credentials.
        monkeypatch.setattr("metesparser.pdf_processor.OpenAIClient", DummyOpenAIClient)

        # Patch extraction steps to return deterministic fixtures.
        def extract_legal_description(self, _pdf_path: str, *, _text=case.raw_text) -> str:
            return _text

        def normalize_legal_description(
            self, _text: str, *, _normalized=case.normalized_text
        ) -> str:
            return _normalized

        monkeypatch.setattr(
            PDFProcessor, "extract_legal_description", extract_legal_description, raising=False
        )
        monkeypatch.setattr(
            PDFProcessor,
            "normalize_legal_description",
            normalize_legal_description,
            raising=False,
        )

        return PDFProcessor(api_key="test-token")

    return factory


@pytest.fixture(params=PDF_CASES, ids=lambda c: c.case_id)
def processed_case(
    request: pytest.FixtureRequest, tmp_path: Path, pdf_processor_factory
) -> tuple[PdfCase, LegalDescription]:
    """Process each mocked PDF case once per parametrized test."""

    case: PdfCase = request.param
    pdf_path = tmp_path / f"{case.case_id}.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% mocked content\n")  # create a placeholder file

    processor = pdf_processor_factory(case)
    legal_desc = processor.process_deed_pdf(str(pdf_path))
    return case, legal_desc


def test_process_deed_pdf_structures_calls(processed_case):
    """Pipeline should produce structured calls with expected geometry."""

    case, legal_desc = processed_case

    assert legal_desc.source_doc.endswith(".pdf")
    assert legal_desc.pob_description  # normalized text should retain POB wording
    assert legal_desc.num_calls() == len(case.expected_distances)

    distances = [call.distance_ft for call in legal_desc.calls]
    for distance, expected in zip(distances, case.expected_distances, strict=True):
        assert math.isclose(distance, expected, abs_tol=0.01)

    azimuths = [call.bearing_azimuth_deg_from_north for call in legal_desc.calls]
    for azimuth, expected in zip(azimuths, case.expected_azimuths, strict=True):
        assert azimuth is not None
        assert math.isclose(azimuth, expected, abs_tol=0.01)


def test_process_deed_pdf_closure_metrics(processed_case):
    """Closure checks should reflect the mocked parcel geometry."""

    case, legal_desc = processed_case
    closure = ClosureChecker.verify_closure(legal_desc.calls)

    assert closure.closure_passed
    assert math.isclose(closure.area_sq_ft, case.expected_area_sq_ft, abs_tol=0.1)
    assert math.isclose(closure.perimeter_ft, case.expected_perimeter_ft, abs_tol=0.1)
    assert not closure.warnings  # mocked calls are fully specified
