"""Integration tests for cross-component pipeline contracts."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker
from metesparser.csv_builder import CSVBuilder
from metesparser.models import LegalDescription
from metesparser.text_parser import TextParser
from tests.fixtures import sample_deeds


def _build_legal_description(text: str, source_doc: str) -> LegalDescription:
    normalized = TextParser.normalize_legal_description(text)
    calls = CallExtractor.extract_calls(normalized)
    calls = CallExtractor.enrich_calls_with_azimuths(calls)
    pob = TextParser.extract_pob(normalized)
    return LegalDescription(
        source_doc=source_doc,
        pob_description=pob,
        calls=calls,
    )


def _count_rows(path: Path) -> int:
    with path.open(newline="", encoding="utf-8") as f:
        return sum(1 for _ in csv.DictReader(f))


@pytest.mark.integration
def test_verified_export_roundtrip_preserves_calls_and_artifacts(tmp_path):
    legal_desc = _build_legal_description(sample_deeds.SQUARE_100FT, "square-100ft.pdf")
    closure = ClosureChecker.verify_closure(legal_desc.calls)
    assert closure.is_fully_verified()

    output = tmp_path / "square.csv"
    CSVBuilder.export_verified_csv(legal_desc.calls, closure, str(output), legal_desc)

    verified_csv = tmp_path / "square_verified.csv"
    verification_txt = verified_csv.with_suffix(".verification.txt")
    metadata_txt = verified_csv.with_suffix(".metadata.txt")
    assert verified_csv.exists()
    assert verification_txt.exists()
    assert metadata_txt.exists()
    assert "Status: FULLY VERIFIED ✓" in verification_txt.read_text(encoding="utf-8")
    assert "source_doc: square-100ft.pdf" in metadata_txt.read_text(encoding="utf-8")
    assert _count_rows(verified_csv) == legal_desc.num_calls()

    parsed_calls = CSVBuilder.csv_to_calls(str(verified_csv))
    assert len(parsed_calls) == legal_desc.num_calls()
    assert [call.course for call in parsed_calls] == [call.course for call in legal_desc.calls]
    assert [call.distance_ft for call in parsed_calls] == pytest.approx(
        [call.distance_ft for call in legal_desc.calls]
    )
    assert [call.bearing_azimuth_deg_from_north for call in parsed_calls] == pytest.approx(
        [call.bearing_azimuth_deg_from_north for call in legal_desc.calls],
        nan_ok=False,
    )


@pytest.mark.integration
def test_open_traverse_contract_rejects_verified_export(tmp_path):
    legal_desc = _build_legal_description(sample_deeds.OPEN_TRAVERSE, "open-traverse.pdf")
    closure = ClosureChecker.verify_closure(legal_desc.calls)

    assert not closure.is_fully_verified()

    output = tmp_path / "open_traverse.csv"
    CSVBuilder.legal_description_to_csv(legal_desc, str(output))

    assert output.exists()
    assert _count_rows(output) == legal_desc.num_calls()
    assert CSVBuilder.csv_to_calls(str(output)) == legal_desc.calls

    with pytest.raises(ValueError, match="verification checks failed"):
        CSVBuilder.export_verified_csv(legal_desc.calls, closure, str(output), legal_desc)

    verified_csv = tmp_path / "open_traverse_verified.csv"
    assert not verified_csv.exists()
