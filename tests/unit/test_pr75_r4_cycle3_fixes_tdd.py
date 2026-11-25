"""Red-Green TDD tests for Cycle 3 re-review fixes on PR #75."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SQUARE_ZERO_AREA = (
    "BEGINNING at an iron pin; "
    "THENCE N 0°00'00\" E, 100.00 feet; "
    "THENCE N 90°00'00\" E, 100.00 feet; "
    "THENCE S 0°00'00\" W, 100.00 feet; "
    "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning, "
    "containing 0 acres."
)

_TWO_TRACT_SECOND_ZERO_AREA = (
    "TRACT 1: BEGINNING at an iron pin; "
    "THENCE N 0°00'00\" E, 100.00 feet; "
    "THENCE N 90°00'00\" E, 100.00 feet; "
    "THENCE S 0°00'00\" W, 100.00 feet; "
    "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning, "
    "containing 10,000 square feet.\n\n"
    "TRACT 2: BEGINNING at a concrete monument; "
    "THENCE N 0°00'00\" E, 100.00 feet; "
    "THENCE N 90°00'00\" E, 100.00 feet; "
    "THENCE S 0°00'00\" W, 100.00 feet; "
    "THENCE N 90°00'00\" W, 100.00 feet to the point of beginning, "
    "containing 0 acres."
)


class TestCodexR3ThCardinalStarter:
    """Codex R3 P1: retain TH courses followed by cardinal boundary wording."""

    def test_th_n_along_not_dropped_as_preamble(self) -> None:
        from mp_export.csv_writer import _validate_export_geometry
        from mp_models import LegalDescription
        from mp_parse.calls import extract_calls
        from mp_parse.normalizer import normalize_legal_description
        from mp_review.api import review_text
        from mp_verify import verify_closure

        deed = (
            "BEG TH N ALONG SAID LINE 100FT "
            "TH N0D E 100FT "
            "TH S45D E 141.4213562373095FT "
            "TH N90D W 100FT POB"
        )
        normalized = normalize_legal_description(deed)
        assert "thence n along" in normalized.lower()

        calls, _ = extract_calls(normalized)
        assert len(calls) == 4
        assert calls[0].bearing_azimuth_deg_from_north is None

        closure = verify_closure(calls)
        assert not closure.is_fully_verified()
        with pytest.raises(ValueError):
            _validate_export_geometry(calls, closure, LegalDescription(calls=calls))

        result = review_text(deed)
        assert result["status"] == "needs_review"
        assert len(result["calls"]) == 4

    @pytest.mark.parametrize(
        "text",
        [
            "BEG TH E ALONG SAID LINE 100FT",
            "BEG TH E, 100FT",
            "BEG TH S TO A PIN 50FT",
            "BEG TH W WITH THE ROAD 50FT",
            "BEG TH N. ALONG SAID LINE 100FT",
        ],
    )
    def test_th_cardinal_boundary_variants_expand(self, text: str) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        expanded = expand_assessor_abbreviations(text)
        assert "thence " in expanded.lower()

    @pytest.mark.parametrize(
        "text",
        [
            "ALONG TH E LINE OF SAID TRACT",
            "TO TH E CORNER OF LOT 4",
            "TO TH AT CORNER",
            "4 TH STREET",
            "20 th day of May",
        ],
    )
    def test_th_ocr_splits_and_ordinals_stay_unexpanded(self, text: str) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        expanded = expand_assessor_abbreviations(text)
        assert "thence" not in expanded.lower()


class TestCodexR3CompactBearingTrailingDigits:
    """Codex R3 P2: allow distance digits immediately after final quadrant letter."""

    def test_compact_n45e100ft_parses_azimuth_and_distance(self) -> None:
        from mp_parse.calls import extract_calls
        from mp_parse.normalizer import normalize_legal_description

        calls, _ = extract_calls(normalize_legal_description("THENCE N45°E100FT to a pin"))
        assert len(calls) == 1
        assert calls[0].bearing_azimuth_deg_from_north == pytest.approx(45.0)
        assert calls[0].distance_ft == pytest.approx(100.0)

    def test_compact_n45d_e100ft_parses_azimuth_and_distance(self) -> None:
        from mp_parse.calls import extract_calls
        from mp_parse.normalizer import normalize_legal_description

        calls, _ = extract_calls(normalize_legal_description("THENCE N45D E100FT to a pin"))
        assert len(calls) == 1
        assert calls[0].bearing_azimuth_deg_from_north == pytest.approx(45.0)
        assert calls[0].distance_ft == pytest.approx(100.0)

    def test_azimuth_and_monolith_bearing_converter_allow_digit_reject_word(self) -> None:
        from mp_bearing.azimuth import bearing_to_azimuth, parse_quadrant_bearing

        from metesparser.bearing_converter import BearingConverter

        assert parse_quadrant_bearing("N 45° E100 feet") == ("N", 45.0, "E")
        assert bearing_to_azimuth("N 45° E100 feet") == pytest.approx(45.0)
        assert BearingConverter.parse_quadrant_bearing("N 45° E100 feet") == ("N", 45.0, "E")
        assert BearingConverter.bearing_to_azimuth("N 45° E100 feet") == pytest.approx(45.0)

        for bad in ("N 45° End", "N 45° Easterly", "S 30° Westward"):
            assert parse_quadrant_bearing(bad) is None
            assert BearingConverter.parse_quadrant_bearing(bad) is None


class TestCodexR3SubdivisionLeadingArticle:
    """Codex R3 P2: preserve legitimate subdivision names starting with THE."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Lot 1 THE OAKS SUBDIVISION", "THE OAKS SUBDIVISION"),
            ("Lot 2, Block 3, THE NORTH HILLS SUBDIVISION", "THE NORTH HILLS SUBDIVISION"),
            ("Lot 4, THE MEADOWS", "THE MEADOWS"),
        ],
    )
    def test_the_subdivision_names_preserved(self, text: str, expected: str) -> None:
        from mp_parse.metadata import extract_subdivision_reference

        ref = extract_subdivision_reference(text)
        assert ref is not None
        assert ref.subdivision_name == expected

    @pytest.mark.parametrize(
        "text",
        [
            "Lot 1 THE SAID TRACT",
            "Lot 1 THE SAID SUBDIVISION",
            "Lot 1 THE NORTH HALF",
            "Lot 1 THE FOLLOWING DESCRIBED PARCEL",
            "Lot 1 THE PLAT OF RECORD",
            "Lot 1 THE",
        ],
    )
    def test_the_recital_phrases_still_rejected(self, text: str) -> None:
        from mp_parse.metadata import extract_subdivision_reference

        ref = extract_subdivision_reference(text)
        assert ref is not None
        assert ref.subdivision_name is None


class TestNativeR3PlssInPrepositionAndSpacing:
    """Native R3 #1: keep aliquots before 'in Section/Township' while disqualifying units."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("THE NW 1/4 IN SECTION 12, T15N, R3E", "NW 1/4"),
            ("SW 1/4 OF NE 1/4 IN SECTION 10, T2N, R1W", "SW 1/4 OF NE 1/4"),
            ("THE E 1/2 OF NW 1/4 IN TOWNSHIP 15 NORTH, RANGE 3 EAST", "E 1/2 OF NW 1/4"),
        ],
    )
    def test_aliquot_followed_by_in_preposition_preserved(self, text: str, expected: str) -> None:
        from mp_parse.metadata import extract_plss_metadata

        assert extract_plss_metadata(text)["aliquot"] == expected

    @pytest.mark.parametrize(
        "text",
        [
            "N 1/2 IN. PIPE, Section 12, T15N, R3E",
            'W 1/4 " pipe, Section 12, T15N, R3E',
            'W 1/4" pipe, Section 12, T15N, R3E',
            "N 1/2-mile from corner, Section 12, T15N, R3E",
            "N 1/2 ft. iron pin, Section 12, T15N, R3E",
            "N 1/2 yd. stake, Section 12, T15N, R3E",
        ],
    )
    def test_measurement_units_and_spaced_quotes_still_disqualified(self, text: str) -> None:
        from mp_parse.metadata import extract_plss_metadata

        assert extract_plss_metadata(text)["aliquot"] is None


class TestNativeR3NonPositiveStatedAreaMultiTractAndArtifactReplay:
    """Native R3 #2 and #3: non-positive stated area blocks multi-tract and re-verified artifacts."""

    def test_extract_calls_marks_non_positive_tract_area_in_multi_tract_deed(self) -> None:
        from mp_models import INVALID_STATED_AREA_NOTE_PREFIX
        from mp_parse.calls import extract_calls
        from mp_verify import verify_closure

        _, tracts = extract_calls(_TWO_TRACT_SECOND_ZERO_AREA)
        assert len(tracts) == 2
        assert tracts[0].stated_area_sq_ft == pytest.approx(10000.0)
        assert not any(INVALID_STATED_AREA_NOTE_PREFIX in (c.notes or "") for c in tracts[0].calls)
        assert tracts[1].stated_area_sq_ft is None
        assert any(INVALID_STATED_AREA_NOTE_PREFIX in (c.notes or "") for c in tracts[1].calls)

        tract_results = verify_closure([], tracts=tracts)
        assert isinstance(tract_results, list)
        assert len(tract_results) == 2
        assert tract_results[0].is_fully_verified()
        assert not tract_results[1].is_fully_verified()
        assert any("invalid stated area" in w.lower() for w in tract_results[1].warnings)

    def test_pdf_processor_multi_tract_second_tract_zero_area_cannot_export(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from metesparser.closure_checker import ClosureChecker
        from metesparser.csv_builder import CSVBuilder
        from metesparser.pdf_processor import PDFProcessor

        pdf = tmp_path / "two_tracts.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
        processor = PDFProcessor(client=object(), cache=False)  # type: ignore[arg-type]
        monkeypatch.setattr(
            processor,
            "extract_text_from_pdf",
            lambda *a, **kw: _TWO_TRACT_SECOND_ZERO_AREA,
        )
        monkeypatch.setattr(
            processor,
            "extract_legal_description",
            lambda *a, **kw: _TWO_TRACT_SECOND_ZERO_AREA,
        )
        monkeypatch.setattr(
            processor,
            "normalize_legal_description",
            lambda *a, **kw: _TWO_TRACT_SECOND_ZERO_AREA,
        )

        legal = processor.process_deed_pdf(str(pdf), audit=False)
        assert len(legal.tracts) == 2

        tract_results = ClosureChecker.verify_closure([], tracts=legal.tracts)
        assert isinstance(tract_results, list)
        assert len(tract_results) == 2
        assert tract_results[0].is_fully_verified()
        assert not tract_results[1].is_fully_verified()

        written = CSVBuilder.export_verified_csv(
            legal.all_calls,
            tract_results[0],
            str(tmp_path / "out.csv"),
            legal_desc=legal,
            tract_results=list(zip(legal.tracts, tract_results, strict=True)),
        )
        assert [p.name for p in written] == ["out_verified_tract1.csv"]

        with pytest.raises(ValueError, match="Cannot export verified CSV"):
            CSVBuilder.export_verified_csv(
                legal.tracts[1].calls,
                tract_results[1],
                str(tmp_path / "tract2.csv"),
                legal_desc=legal,
                tract_results=[(legal.tracts[1], tract_results[1])],
            )

    def test_mp_review_persists_invalid_stated_area_note_blocking_rereview_export(
        self, tmp_path: Path
    ) -> None:
        from mp_models import INVALID_STATED_AREA_NOTE_PREFIX
        from mp_review.api import review_text, verify_file

        out1 = tmp_path / "run1"
        r1 = review_text(_SQUARE_ZERO_AREA, output_dir=out1)
        assert r1["status"] == "needs_review"
        assert any(e.get("code") == "invalid_stated_area" for e in r1["errors"])
        assert any("invalid stated area" in w.lower() for w in r1["verification"]["warnings"])
        assert not (out1 / "calls_verified.csv").exists()

        saved_calls = json.loads((out1 / "calls.json").read_text(encoding="utf-8"))
        assert any(INVALID_STATED_AREA_NOTE_PREFIX in (c.get("notes") or "") for c in saved_calls)

        out2 = tmp_path / "run2"
        r2 = verify_file(out1 / "calls.json", output_dir=out2)
        assert r2["status"] == "needs_review"
        assert any("invalid stated area" in w.lower() for w in r2["verification"]["warnings"])
        assert not (out2 / "calls_verified.csv").exists()


class TestNativeR3BuildPluginPep503WheelValidation:
    """Native R3 #4: reject separator-only or non-PEP-503 wheel prefixes and unsafe filenames."""

    @pytest.mark.parametrize(
        "bad_wheel",
        [
            "-1.0.0-py3-none-any.whl",
            "___-1.0.0-py3-none-any.whl",
            "..-1.0.0-py3-none-any.whl",
            "foo_-1.0.0-py3-none-any.whl",
            'bad"name-1.0.0-py3-none-any.whl',
            "mp_models-1.0.0-py3-none-any.tar.gz",
        ],
    )
    def test_runtime_project_rejects_malformed_wheel_names(self, bad_wheel: str) -> None:
        script_path = Path(__file__).resolve().parents[2] / "scripts" / "build_claude_plugin.py"
        spec = importlib.util.spec_from_file_location("build_claude_plugin_r4_test", script_path)
        assert spec is not None and spec.loader is not None
        build_claude_plugin = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build_claude_plugin)

        with pytest.raises(ValueError, match="Unexpected wheel filename"):
            build_claude_plugin.runtime_project([Path(bad_wheel)])
