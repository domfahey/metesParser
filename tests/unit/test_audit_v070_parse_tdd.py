"""Red-Green TDD regressions for v0.7.0 Parser, Normalizer, Metadata & Parcel fixes."""

from __future__ import annotations

import re
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from mp_models import AuditContext, RunMetadata, SkippedCourse

ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# 1. normalizer.py
# ---------------------------------------------------------------------------


class TestNormalizerFixes:
    def test_standardize_cardinal_directions_uppercase_and_variants(self) -> None:
        from mp_parse.normalizer import standardize_cardinal_directions

        assert standardize_cardinal_directions("north 45 degrees east") == "N 45° E"
        assert standardize_cardinal_directions("n 45°30'15\" e") == "N 45°30'15\" E"
        assert standardize_cardinal_directions("N 45 degrees 30 minutes E") == "N 45°30' E"
        assert standardize_cardinal_directions("S 45 degrees East") == "S 45° E"
        assert standardize_cardinal_directions("S0 degrees E") == "S 0° E"
        assert standardize_cardinal_directions("North 45 degrees, 30 minutes East") == "N 45°30' E"
        assert standardize_cardinal_directions("North 45 degrees, East") == "N 45° E"

    def test_th_expansion_not_blocked_by_following_word(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        res_e = expand_assessor_abbreviations("FROM NE COR TH E 100 FT")
        assert "thence due East 100 feet" in res_e

        res_a = expand_assessor_abbreviations("BEG TH A CURVE TO THE RIGHT")
        assert "thence A CURVE" in res_a

        res_at = expand_assessor_abbreviations("BEG TH AT 100 FT")
        assert "thence AT 100 feet" in res_at

        # Words beginning with TH must still remain untouched.
        preserved = expand_assessor_abbreviations("THE ABOVE THAT THIS THEREOF THENCE THROUGH")
        assert "thence" not in preserved.replace("THENCE", "").lower()
        assert "THE ABOVE THAT THIS THEREOF" in preserved

    def test_row_expansion_is_uppercase_only(self) -> None:
        from mp_parse.normalizer import expand_abbreviations

        assert (
            expand_abbreviations("along the ROW of Route 1") == "along the right-of-way of Route 1"
        )
        assert expand_abbreviations("along a row of trees") == "along a row of trees"

    def test_unicode_primes_normalized(self) -> None:
        from mp_parse.normalizer import normalize_dms_symbols

        assert normalize_dms_symbols("N 45\u00b030\u203215\u2033 E") == "N 45°30'15\" E"

    def test_clean_ocr_errors_n0rth_and_optional_seconds(self) -> None:
        from mp_parse.normalizer import clean_ocr_errors

        assert clean_ocr_errors("N0rth 45 degrees East") == "North 45 degrees East"
        assert clean_ocr_errors("N 45 0 30' 15\" E") == "N 45°30'15\" E"
        assert (
            clean_ocr_errors("North 45 0 30' 15\" East")
            == "North 45 degrees 30 minutes 15 seconds East"
        )

    def test_expand_assessor_abbreviations_guards_node_sod_lot_2d_and_sec(self) -> None:
        from mp_parse.normalizer import expand_assessor_abbreviations

        assert expand_assessor_abbreviations("AT NODE 4") == "AT NODE 4"
        assert expand_assessor_abbreviations("SOD FARM") == "SOD FARM"
        assert expand_assessor_abbreviations("LOT 2D") == "LOT 2D"
        assert expand_assessor_abbreviations("LOT 12 SEC 4") == "LOT 12 SEC 4"
        assert "1/4 SEC 10" in expand_assessor_abbreviations("PART OF SE 1/4 SEC 10")


# ---------------------------------------------------------------------------
# 2. calls.py
# ---------------------------------------------------------------------------


class TestCallsFixes:
    def test_curve_with_delta_and_arc_without_radius_fails_closed(self) -> None:
        from mp_parse.calls import _is_curve_segment, extract_calls, extract_single_call

        curve_text = (
            "THENCE along a curve to the right having a delta angle of 90 degrees "
            "and an arc length of 157.08 feet to a point"
        )
        assert _is_curve_segment(
            "along a curve having a delta angle of 90 degrees and an arc length of 157.08 feet"
        )
        # Never fabricate unstated radius_ft: strict mode rejects; non-strict skips course.
        with pytest.raises(ValueError, match="Curve geometry requires radius_ft"):
            extract_single_call(curve_text, 1)
        skipped: list[SkippedCourse] = []
        calls, _ = extract_calls(curve_text, strict=False, skipped_courses=skipped)
        assert calls == []
        assert len(skipped) == 1
        assert "radius_ft" in skipped[0].error

    def test_extract_direction_non_strict_invalid_packed_and_text_order_priority(self) -> None:
        from mp_parse.calls import extract_direction

        # Default strict=True rejects invalid packed DMS (minutes=75)
        with pytest.raises(ValueError, match=r"Invalid packed DMS: minutes=75 \(must be 0-59\)"):
            extract_direction("THENCE N 45.75° E 100 feet")

        # Direct strict=False returns non-fabricated verbatim packed token
        assert extract_direction("THENCE N 45.75° E 100 feet", strict=False) == "N 45.75° E"

        # Text-order priority: quadrant vs packed
        assert extract_direction("N 45°30' E 100 feet to a point N 46.1631° E") == "N 45°30' E"
        # Text-order priority: cardinal vs abbrev
        assert extract_direction("NW along the north line 100 feet") == "nw"
        assert extract_direction("north along the NW line 100 feet") == "north"

    def test_initial_curve_course_before_first_thence_is_preserved(self) -> None:
        from mp_parse.calls import _is_initial_course_prefix, extract_calls

        prefix = (
            "along a curve to the right having a radius of 100.00 feet "
            "and an arc length of 50.00 feet to a point;"
        )
        assert _is_initial_course_prefix(prefix) is True

        text = (
            "along a curve to the right having a radius of 100.00 feet "
            "and an arc length of 50.00 feet to a point; "
            "THENCE S 45° E 100.00 feet; "
            "THENCE S 45° W 100.00 feet; "
            "THENCE N 45° W 100.00 feet to the point of beginning."
        )
        calls, _ = extract_calls(text, strict=True)
        assert len(calls) == 4
        assert calls[0].curve_dir == "right"
        assert calls[0].radius_ft == pytest.approx(100.0)
        assert calls[0].arc_length_ft == pytest.approx(50.0)

    def test_audit_single_call_records_rule_for_other_monument(self) -> None:
        from mp_parse.calls import extract_calls

        audit = AuditContext(
            run_metadata=RunMetadata(
                parser_version="test",
                llm_provider="none",
                llm_model="none",
                prompt_hash="test",
                timestamp_utc=datetime.now(UTC),
                source_pdf="test.pdf",
                cache_enabled=False,
            )
        )
        extract_calls(
            "BEGINNING at a point; THENCE N 45° E 100 feet to a monument; "
            "THENCE S 45° W 100 feet to the point of beginning.",
            audit_context=audit,
            strict=True,
        )
        monument_steps = [
            t for t in audit.call_audits[0].transformations if t.step == "classify_monument"
        ]
        assert len(monument_steps) == 1
        assert monument_steps[0].output == "other"
        assert monument_steps[0].rule == r"\bmonument\b"

    def test_multitract_populates_pob_and_stated_area_per_tract(self) -> None:
        from mp_parse.calls import extract_calls

        text = (
            "TRACT 1: BEGINNING at an oak tree; "
            "THENCE N 0° E 100 feet; THENCE N 90° E 100 feet; "
            "THENCE S 0° W 100 feet; THENCE N 90° W 100 feet to the point of beginning. "
            "Containing 1.5 acres.\n\n"
            "TRACT 2: BEGINNING at an iron pin; "
            "THENCE N 0° E 200 feet; THENCE N 90° E 200 feet; "
            "THENCE S 0° W 200 feet; THENCE N 90° W 200 feet to the point of beginning. "
            "Containing 2.5 acres."
        )
        _, tracts = extract_calls(text, strict=True)
        assert len(tracts) == 2
        assert tracts[0].role_basis == "heading"
        assert tracts[1].role_basis == "heading"
        assert tracts[0].pob_description is not None
        assert "oak tree" in tracts[0].pob_description.lower()
        assert tracts[1].pob_description is not None
        assert "iron pin" in tracts[1].pob_description.lower()
        assert tracts[0].stated_area_sq_ft == pytest.approx(1.5 * 43560.0)
        assert tracts[1].stated_area_sq_ft == pytest.approx(2.5 * 43560.0)


# ---------------------------------------------------------------------------
# 3. metadata.py & numbers.py
# ---------------------------------------------------------------------------


class TestMetadataAndNumbersFixes:
    def test_extract_pob_decimal_safe(self) -> None:
        from mp_parse.metadata import extract_pob

        text = "BEGINNING at an iron pin 12.5 feet from the corner; THENCE N 45° E 100 feet"
        assert extract_pob(text) == "an iron pin 12.5 feet from the corner"

    def test_is_closure_to_pob_variants(self) -> None:
        from mp_parse.metadata import is_closure_to_pob

        assert is_closure_to_pob("100 feet to the point and place of beginning") is True
        assert is_closure_to_pob("100 feet to the P.O.B") is True
        assert is_closure_to_pob("100 feet to the T.P.O.B") is True
        assert is_closure_to_pob("100 feet to the R.P.O.B") is True
        assert is_closure_to_pob("100 feet to the T.P.O.B.") is True
        assert is_closure_to_pob("100 feet to the R.P.O.B.") is True

    def test_extract_distance_allows_monument_counts_rejects_unsupported_units(self) -> None:
        from mp_parse.calls import extract_single_call
        from mp_parse.metadata import extract_distance

        assert extract_distance("100 feet and 2 concrete monuments") == (100.0, "feet")
        call = extract_single_call(
            "THENCE N 45° E 100 feet and 2 concrete monuments to a corner", 1
        )
        assert call is not None
        assert call.distance_ft == pytest.approx(100.0)
        assert extract_distance("10 feet and 25 cubits") == (0.0, "feet")

    def test_comma_number_rejects_malformed_commas(self) -> None:
        from mp_parse.numbers import COMMA_NUMBER

        pattern = re.compile(COMMA_NUMBER)
        assert pattern.fullmatch("500,") is None
        assert pattern.fullmatch("1,,2") is None
        assert pattern.fullmatch("1,200.50") is not None

    def test_detect_meander_ignores_streets_and_financial_banks(self) -> None:
        from mp_parse.metadata import detect_meander

        assert detect_meander("along Lake Avenue 100 feet") is False
        assert detect_meander("along River Road 100 feet") is False
        assert detect_meander("along Creek Drive 100 feet") is False
        assert detect_meander("along Bay Street 100 feet") is False
        assert detect_meander("along First National Bank 100 feet") is False
        assert detect_meander("along Chase Bank 100 feet") is False
        assert detect_meander("along the creek 100 feet") is True
        assert detect_meander("along the west bank of the river 100 feet") is True

    def test_extract_witness_trees_word_boundary(self) -> None:
        from mp_parse.metadata import extract_witness_trees

        assert extract_witness_trees("Washington Road bears N 45 E 10 feet") == []
        trees = extract_witness_trees("a white ash 12 inches bears N 45 E 10 links")
        assert len(trees) == 1

    def test_infer_distance_unit_word_boundaries_and_state_case(self) -> None:
        from mp_parse.metadata import infer_distance_unit

        assert infer_distance_unit("along Alvarado Street 100 feet") is None
        assert infer_distance_unit("along Carpenter Road 100 feet") is None
        assert infer_distance_unit("100 feet", state="tx", year=1850) == "varas"
        assert infer_distance_unit("100 feet", state="la") == "arpents"

    def test_detect_strip_exceptions_degree_symbol_and_full_overlap(self) -> None:
        from mp_parse.metadata import detect_strip_exceptions

        geom = "EXCEPT the West 20 feet, S 45° E 100 feet, N 45° E 20 feet to the beginning."
        assert detect_strip_exceptions(geom) == []

    def test_extract_prior_conveyance_page_and_decimal_safe(self) -> None:
        from mp_parse.metadata import extract_prior_conveyance

        book = extract_prior_conveyance("Recorded in Deed Book 123, Page 456 of County Records.")
        assert book == "Deed Book 123, Page 456"

        being = extract_prior_conveyance(
            "BEING the same premises containing 2.5 acres conveyed by Smith."
        )
        assert being is not None
        assert "2.5 acres conveyed by Smith" in being

    def test_extract_plss_metadata_fixes(self) -> None:
        from mp_parse.metadata import extract_plss_metadata

        time_text = "RECORDED AT 3 P.M. ON MONDAY"
        assert extract_plss_metadata(time_text)["principal_meridian"] is None

        sec_dot = extract_plss_metadata("SEC. 14, T2S, R9E")
        assert sec_dot["section"] == "14"

        aliquot = extract_plss_metadata("the NE 1/4 of Section 12")
        assert aliquot["aliquot"] == "NE 1/4"

    def test_extract_subdivision_reference_boilerplate_guard(self) -> None:
        from mp_parse.metadata import extract_subdivision_reference

        ref1 = extract_subdivision_reference(
            "Lot 5, BEGINNING at an iron pin; THENCE North 100 feet"
        )
        assert ref1 is not None
        assert ref1.lot == "5"
        assert ref1.subdivision_name is None

        ref2 = extract_subdivision_reference("Lot 5, THENCE North 100 feet")
        assert ref2 is not None
        assert ref2.subdivision_name is None

    def test_extract_area_statement_square_foot_and_parent_parcel_lot(self) -> None:
        from mp_parse.metadata import extract_area_statement

        sq_ft = extract_area_statement("CONTAINING 1 square foot")
        assert sq_ft is not None
        assert sq_ft["value_sq_ft"] == pytest.approx(1.0)
        assert sq_ft["unit"] == "sq_ft"

        assert extract_area_statement("containing 10.0 acres of the parent parcel") is None
        assert extract_area_statement("containing 10.0 acres of the original lot") is None


# ---------------------------------------------------------------------------
# 4. parcels.py, __init__.py, pyproject.toml
# ---------------------------------------------------------------------------


class TestParcelsExportsAndPackagingFixes:
    def test_parcels_does_not_split_on_mid_call_adjoining_reference(self) -> None:
        from mp_parse.parcels import detect_parcel_markers, split_into_parcels

        text = (
            "BEGINNING at a point; "
            "THENCE N 0° E 100 feet along the west line of Parcel A; "
            "THENCE S 90° E 100 feet to the point of beginning."
        )
        assert detect_parcel_markers(text) == []
        parcels = split_into_parcels(text)
        assert len(parcels) == 1

    def test_mp_parse_exports_normalizer_and_metadata_helpers(self) -> None:
        import mp_parse

        for symbol in (
            "normalize_legal_description",
            "extract_pob",
            "extract_area_statement",
            "extract_plss_metadata",
            "is_closure_to_pob",
            "detect_meander",
        ):
            assert hasattr(mp_parse, symbol), f"mp_parse missing export {symbol}"

    def test_mp_parse_pyproject_declares_pydantic_dependency(self) -> None:
        data = tomllib.loads((ROOT / "packages" / "mp-parse" / "pyproject.toml").read_text())
        deps = data["project"]["dependencies"]
        assert any(dep.startswith("pydantic>=2.10.0") for dep in deps)
