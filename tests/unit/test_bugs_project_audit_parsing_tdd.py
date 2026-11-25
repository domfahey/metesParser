"""Regression TDD tests for project audit parsing, normalizer, metadata, and monument bugs."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from mp_models import AuditContext, DeedCall, RunMetadata
from mp_parse import calls as pkg_calls
from mp_parse import metadata as pkg_metadata
from mp_parse import normalizer as pkg_normalizer

from metesparser.call_extractor import CallExtractor
from metesparser.models import AuditContext as MonoAuditContext
from metesparser.models import DeedCall as MonoDeedCall
from metesparser.models import RunMetadata as MonoRunMetadata
from metesparser.text_parser import TextParser

REPO_ROOT = Path(__file__).resolve().parents[2]


def _pkg_extract_calls_flat(
    text: str,
    distance_unit: str = "feet",
    *,
    audit_context: AuditContext | None = None,
    strict: bool = True,
) -> list[DeedCall]:
    calls, _ = pkg_calls.extract_calls(
        text, distance_unit, audit_context=audit_context, strict=strict
    )
    return calls


# ---------------------------------------------------------------------------
# B1-B9: Normalizer fixes (package + monolith)
# ---------------------------------------------------------------------------


class TestB1StandardizeCardinalDirections:
    @pytest.mark.parametrize(
        "fn",
        [
            pkg_normalizer.standardize_cardinal_directions,
            TextParser.standardize_cardinal_directions,
        ],
    )
    def test_single_letter_no_space_and_comma(self, fn) -> None:
        assert fn("S0 degrees 32 minutes 50 seconds W") == "S 0°32'50\" W"
        assert fn("N 45 degrees, 30 minutes, 15 seconds E") == "N 45°30'15\" E"
        assert fn("n 45 degrees, 30 minutes e") == "N 45°30' E"
        assert fn("s 10 degrees w") == "S 10° W"


class TestB2ThenceExpansion:
    @pytest.mark.parametrize(
        "fn",
        [pkg_normalizer.expand_assessor_abbreviations, TextParser.expand_assessor_abbreviations],
    )
    def test_th_before_e_and_a(self, fn) -> None:
        res_e = fn("TH E 100 FT")
        assert res_e.lower().startswith("thence ")
        assert "100 feet" in res_e

        res_a = fn("TH A CURVE TO THE RIGHT")
        assert res_a.lower().startswith("thence a curve")

        res_the = fn("THE ABOVE THEREOF")
        assert "thence" not in res_the.lower()


class TestB4BareCardinalGuard:
    @pytest.mark.parametrize(
        "fn",
        [pkg_normalizer.expand_assessor_abbreviations, TextParser.expand_assessor_abbreviations],
    )
    def test_ocr_dropped_degree_not_fabricated_as_due(self, fn) -> None:
        res_min = fn("THENCE N 56 40' W 100 feet")
        assert "due" not in res_min.lower()

        res_card = fn("THENCE N 45 W 100 feet")
        assert "due" not in res_card.lower()

        res_due = fn("THENCE S 289.81 feet")
        assert res_due == "THENCE due South 289.81 feet"


class TestB5AmpersandAndSeparator:
    @pytest.mark.parametrize(
        "fn",
        [pkg_normalizer.expand_assessor_abbreviations, TextParser.expand_assessor_abbreviations],
    )
    def test_and_before_assessor_expanded_degrees(self, fn) -> None:
        result = fn("S0DEG 32M 50S W 100FT AND N80DEG 29M 20S W 200FT")
        assert "100 feet thence N" in result


class TestB6TpobRpobProtection:
    @pytest.mark.parametrize(
        "fn",
        [pkg_normalizer.expand_assessor_abbreviations, TextParser.expand_assessor_abbreviations],
    )
    def test_tpob_rpob_not_mangled(self, fn) -> None:
        assert "T.P.O.B." in fn("to the T.P.O.B.")
        assert "R.P.O.B." in fn("to the R.P.O.B.")
        assert "point of beginning" not in fn("to the T.P.O.B.").lower()
        assert "point of beginning" not in fn("to the R.P.O.B.").lower()


class TestB7AbbreviationIdempotencyAndRowCase:
    @pytest.mark.parametrize(
        "fn",
        [pkg_normalizer.expand_abbreviations, TextParser.expand_abbreviations],
    )
    def test_pk_idempotent_and_row_case_sensitive(self, fn) -> None:
        once = fn("to a PK")
        twice = fn(once)
        assert once == "to a pk nail"
        assert twice == "to a pk nail"

        assert fn("along a row of cedar trees") == "along a row of cedar trees"
        assert fn("along the ROW line") == "along the right-of-way line"
        assert fn("along the r/w line") == "along the right-of-way line"


class TestB8UnicodePrimeSymbols:
    @pytest.mark.parametrize(
        "fn",
        [pkg_normalizer.normalize_dms_symbols, TextParser.normalize_dms_symbols],
    )
    def test_unicode_prime_and_double_prime(self, fn) -> None:
        assert fn("N 45°30\u203215\u2033 E") == "N 45°30'15\" E"


class TestB9CleanOcrErrors:
    @pytest.mark.parametrize(
        "fn",
        [pkg_normalizer.clean_ocr_errors, TextParser.clean_ocr_errors],
    )
    def test_north_case_sensitive_n0rth_and_zero_degree_seconds(self, fn) -> None:
        assert fn("NORTH 45 degrees East") == "NORTH 45 degrees East"
        assert fn("north line of lot") == "north line of lot"
        assert fn("NOrth 45 degrees East") == "North 45 degrees East"
        assert fn("N0rth 45 degrees East") == "North 45 degrees East"

        res_sym = fn("n 45 0 30' 15\" e")
        assert "45°30'15\"" in res_sym
        res_word = fn("north 45 0 30' 15\" east")
        assert "45 degrees 30 minutes 15 seconds" in res_word.lower()


# ---------------------------------------------------------------------------
# B10-B12: POC / POB / Closure
# ---------------------------------------------------------------------------


class TestB10PocAndMarkTieInGuard:
    def test_mark_tie_in_does_not_mark_all_calls_when_pob_is_last(self) -> None:
        pkg_list = [
            DeedCall(course=1, direction_text="N 0° E", distance_ft=100.0, to="a pin"),
            DeedCall(
                course=2,
                direction_text="S 0° W",
                distance_ft=100.0,
                to="the point of beginning",
            ),
        ]
        res_pkg = pkg_calls.mark_tie_in_calls(pkg_list, poc_description="iron pin")
        assert all(not c.is_tie_in for c in res_pkg)

        mono_list = [
            MonoDeedCall(course=1, direction_text="N 0° E", distance_ft=100.0, to="a pin"),
            MonoDeedCall(
                course=2,
                direction_text="S 0° W",
                distance_ft=100.0,
                to="the point of beginning",
            ),
        ]
        res_mono = CallExtractor.mark_tie_in_calls(mono_list, poc_description="iron pin")
        assert all(not c.is_tie_in for c in res_mono)

    @pytest.mark.parametrize("fn", [pkg_metadata.extract_poc, TextParser.extract_poc])
    def test_terminal_closing_pob_does_not_fabricate_poc(self, fn) -> None:
        text = (
            "COMMENCING at an iron pin; THENCE N 0° E 100 feet; "
            "THENCE E 100 feet; THENCE S 0° W 100 feet; "
            "THENCE W 100 feet to the point of beginning."
        )
        assert fn(text) == ""


class TestB11ExtractPobDecimals:
    @pytest.mark.parametrize("fn", [pkg_metadata.extract_pob, TextParser.extract_pob])
    def test_decimal_in_pob_not_truncated(self, fn) -> None:
        text = "BEGINNING at a point 50.5 feet north of the corner; THENCE N 45° E 100 feet"
        pob = fn(text)
        assert "50.5 feet north of the corner" in pob


class TestB12IsClosureToPob:
    @pytest.mark.parametrize("fn", [pkg_metadata.is_closure_to_pob, TextParser.is_closure_to_pob])
    def test_point_and_place_and_optional_dots(self, fn) -> None:
        assert fn("N 45° E 100 feet to the point and place of beginning") is True
        assert fn("N 45° E 100 feet to the place of beginning") is True
        assert fn("N 45° E 100 feet to the T.P.O.B") is True
        assert fn("N 45° E 100 feet to the R.P.O.B") is True
        assert fn("N 45° E 100 feet to the P.O.B.") is True


# ---------------------------------------------------------------------------
# B13-B17, B29, I4, I6: Curves, Distance-Alt, Direction, Initial Curve, Audit
# ---------------------------------------------------------------------------


class TestB13ExtractCurveInfo:
    @pytest.mark.parametrize("fn", [pkg_calls.extract_curve_info, CallExtractor.extract_curve_info])
    def test_chord_bearing_units_commas_decimals_and_radial_comma(self, fn) -> None:
        info = fn(
            "along a curve to the right, radius of 300.00 feet, "
            "chord bearing N 45°30' E, 1,250.50 feet."
        )
        assert info.get("chord_bearing") == "N 45°30' E"
        assert info.get("chord_length_ft") == pytest.approx(1250.50)

        info_chains = fn(
            "along a curve to the right, radius of 300.00 feet, chord bears N 45°30' E, 2 chains."
        )
        assert info_chains.get("chord_length_ft") == pytest.approx(132.0)

        info_radial = fn(
            "along a curve to the right, radial line bears North 45 degrees 30 minutes, "
            "15 seconds East, radius of 300.00 feet"
        )
        assert info_radial.get("radial_bearing") == "N 45°30'15\" E"


class TestB14ExtractDistanceAlternate:
    @pytest.mark.parametrize(
        "fn",
        [pkg_calls.extract_distance_alternate, CallExtractor.extract_distance_alternate],
    )
    def test_skips_bearing_minutes_and_parses_comma_apostrophe(self, fn) -> None:
        assert fn("N 45 30' 125.26' to a pin") == pytest.approx(125.26)
        assert fn("1,200' along the line") == pytest.approx(1200.0)

    def test_single_call_alternate_uses_feet_not_default_unit(self, monkeypatch) -> None:
        monkeypatch.setattr(pkg_calls, "extract_distance", lambda _t: (0.0, "feet"))
        call_pkg = pkg_calls.extract_single_call(
            "N 45° E 100' to a pin", course=1, distance_unit="poles"
        )
        assert call_pkg is not None
        assert call_pkg.distance_ft == pytest.approx(100.0)

        monkeypatch.setattr(TextParser, "extract_distance", lambda _t: (0.0, "feet"))
        call_mono = CallExtractor.extract_single_call(
            "N 45° E 100' to a pin", course=1, distance_unit="poles"
        )
        assert call_mono is not None
        assert call_mono.distance_ft == pytest.approx(100.0)


class TestB15InvalidPackedDmsNonStrict:
    @pytest.mark.parametrize("parse", [_pkg_extract_calls_flat, CallExtractor.extract_calls])
    def test_invalid_packed_dms_does_not_crash_non_strict(self, parse) -> None:
        text = "BEGINNING at pin; THENCE\n1. N 46.9999° E 100 feet\n2. S 45°00' E 100 feet"
        calls = parse(text, strict=False)
        assert len(calls) == 1
        assert calls[0].bearing_azimuth_deg_from_north == pytest.approx(135.0)

    @pytest.mark.parametrize("parse", [_pkg_extract_calls_flat, CallExtractor.extract_calls])
    def test_invalid_packed_dms_in_num_prefix_non_strict(self, parse) -> None:
        text = "Some intro N 46.9999° E\n1. S 45°00' E 100 feet"
        calls = parse(text, strict=False)
        assert len(calls) == 1
        assert calls[0].bearing_azimuth_deg_from_north == pytest.approx(135.0)

    def test_invalid_packed_dms_in_empty_tract_non_strict(self) -> None:
        text = "TRACT 1: N 46.9999° E\nTRACT 2: S 45°00' E 100 feet"
        calls = _pkg_extract_calls_flat(text, strict=False)
        assert len(calls) == 1
        assert calls[0].bearing_azimuth_deg_from_north == pytest.approx(135.0)


class TestB16ExtractDirectionOrdering:
    @pytest.mark.parametrize("fn", [pkg_calls.extract_direction, CallExtractor.extract_direction])
    def test_earliest_match_wins(self, fn) -> None:
        assert fn("N 45°30' E along line of S 12.3456° W") == "N 45°30' E"
        assert fn("NE along the southerly line") == "ne"


class TestB17InitialCurvePreserved:
    @pytest.mark.parametrize("parse", [_pkg_extract_calls_flat, CallExtractor.extract_calls])
    def test_initial_curve_before_first_thence(self, parse) -> None:
        text = (
            "along a curve to the right, radius of 200.00 feet, "
            "delta angle of 30°00', arc length of 104.72 feet; "
            "THENCE N 45°00' E 100 feet"
        )
        calls = parse(text)
        assert len(calls) == 2
        assert calls[0].curve_dir == "right"
        assert calls[0].distance_ft == pytest.approx(104.72)


class TestB29AuditDueCardinalAndOtherMonument:
    def test_audit_due_cardinal_and_other_monument(self) -> None:
        text = "THENCE due North 100 feet to a monument"
        pkg_ctx = AuditContext(
            run_metadata=RunMetadata(
                parser_version="test",
                llm_provider="test",
                llm_model="test",
                prompt_hash="test",
                timestamp_utc="2026-01-01T00:00:00Z",
                source_pdf="test.pdf",
                cache_enabled=False,
            )
        )
        pkg_calls.extract_calls(text, audit_context=pkg_ctx)
        assert len(pkg_ctx.call_audits) == 1
        ca = pkg_ctx.call_audits[0]
        assert any(t.step == "compute_azimuth" for t in ca.transformations)
        assert any(
            d.field == "bearing_azimuth_deg_from_north"
            and d.reason == "due cardinal direction parsed"
            for d in ca.decisions
        )
        mon_t = [t for t in ca.transformations if t.step == "classify_monument"]
        assert len(mon_t) == 1
        assert mon_t[0].rule == r"\bmonument\b"

        mono_ctx = MonoAuditContext(
            run_metadata=MonoRunMetadata(
                parser_version="test",
                llm_provider="test",
                llm_model="test",
                prompt_hash="test",
                timestamp_utc="2026-01-01T00:00:00Z",
                source_pdf="test.pdf",
                cache_enabled=False,
            )
        )
        CallExtractor.extract_calls(text, audit_context=mono_ctx)
        assert len(mono_ctx.call_audits) == 1
        mca = mono_ctx.call_audits[0]
        assert any(t.step == "compute_azimuth" for t in mca.transformations)
        assert any(
            d.field == "bearing_azimuth_deg_from_north"
            and d.reason == "due cardinal direction parsed"
            for d in mca.decisions
        )
        mmon_t = [t for t in mca.transformations if t.step == "classify_monument"]
        assert len(mmon_t) == 1
        assert mmon_t[0].rule == r"\bmonument\b"


class TestI4AndI6PackagingAndEnrichment:
    def test_py_typed_and_pydantic_dep(self) -> None:
        py_typed = REPO_ROOT / "packages" / "mp-parse" / "src" / "mp_parse" / "py.typed"
        assert py_typed.is_file()
        pyproject = tomllib.loads(
            (REPO_ROOT / "packages" / "mp-parse" / "pyproject.toml").read_text()
        )
        deps = pyproject["project"]["dependencies"]
        assert any(d.startswith("pydantic>=") for d in deps)

    def test_enrich_clears_incomplete_notes_for_quadrant(self) -> None:
        pkg_call = DeedCall(
            course=1,
            direction_text="N 45°00' E",
            bearing_quadrant="N 45°00' E",
            distance_ft=100.0,
            bearing_azimuth_deg_from_north=None,
            notes="incomplete bearing",
        )
        res_pkg = pkg_calls.enrich_calls_with_azimuths([pkg_call])[0]
        assert res_pkg.bearing_azimuth_deg_from_north == pytest.approx(45.0)
        assert res_pkg.notes is None

        mono_call = MonoDeedCall(
            course=1,
            direction_text="N 45°00' E",
            bearing_quadrant="N 45°00' E",
            distance_ft=100.0,
            bearing_azimuth_deg_from_north=None,
            notes="incomplete bearing",
        )
        res_mono = CallExtractor.enrich_calls_with_azimuths([mono_call])[0]
        assert res_mono.bearing_azimuth_deg_from_north == pytest.approx(45.0)
        assert res_mono.notes is None


# ---------------------------------------------------------------------------
# B18-B24: Metadata fixes
# ---------------------------------------------------------------------------


class TestB18WitnessTrees:
    @pytest.mark.parametrize(
        "fn", [pkg_metadata.extract_witness_trees, TextParser.extract_witness_trees]
    )
    def test_washington_chord_radial_and_decimals(self, fn) -> None:
        assert fn("along Washington Street bears N 45° E 100 feet") == []
        assert fn("along Oak Street, chord bears N 45° E 100 feet") == []
        assert fn("along Pine Lane, radial line bears S 30° W 100 feet") == []
        trees = fn("a white oak 12 inches bears N 45 E 20.5 feet")
        assert len(trees) == 1
        assert "20.5 feet" in trees[0]


class TestB19InferDistanceUnit:
    @pytest.mark.parametrize(
        "fn", [pkg_metadata.infer_distance_unit, TextParser.infer_distance_unit]
    )
    def test_word_boundaries_and_case_insensitive_state(self, fn) -> None:
        assert fn("along Carpenter Road 100 feet") is None
        assert fn("along Alvarado Street 100 feet") is None
        assert fn("100 feet", state="tx", year=1850) == "varas"
        assert fn("100 feet", state="la") == "arpents"


class TestB20StripExceptions:
    def test_less_and_except_multiword_purpose_and_boundaries(self) -> None:
        cleaned = pkg_metadata.remove_strip_exceptions(
            "to the point of beginning, LESS AND EXCEPT the North 15 feet thereof."
        )
        assert "LESS AND" not in cleaned

        multi = pkg_metadata.detect_strip_exceptions(
            "except the East 20 feet deeded for public roadway."
        )
        assert len(multi) == 1
        assert multi[0]["purpose"] == "public roadway"

        followed_by_tract = pkg_metadata.detect_strip_exceptions(
            "except the East 20 feet deeded for roadway. TRACT 2: THENCE N 45° E 100 feet"
        )
        assert len(followed_by_tract) == 1

        metes_degree = pkg_metadata.detect_strip_exceptions(
            "EXCEPT the South 20 feet thereof, N 45° E 100 feet"
        )
        assert metes_degree == []


class TestB21AbbreviationsInMetadata:
    @pytest.mark.parametrize(
        "fn", [pkg_metadata.extract_prior_conveyance, TextParser.extract_prior_conveyance]
    )
    def test_prior_conveyance_book_page_and_initials(self, fn) -> None:
        book = fn("Recorded in Deed Book 1234, Page 567 of the County Records.")
        assert book == "Deed Book 1234, Page 567"
        initial = fn("BEING the same premises conveyed to John A. Smith by deed.")
        assert initial is not None
        assert "John A. Smith" in initial

    @pytest.mark.parametrize(
        "fn",
        [
            pkg_metadata.extract_surveyor_certification,
            TextParser.extract_surveyor_certification,
        ],
    )
    def test_surveyor_cert_acronyms(self, fn) -> None:
        res = fn("Certified by: Jane A. Doe, P.L.S. No. 12345.")
        assert res is not None
        assert "P.L.S." in res
        assert "12345" in res

    @pytest.mark.parametrize(
        "fn", [pkg_metadata.extract_basis_of_bearing, TextParser.extract_basis_of_bearing]
    )
    def test_basis_of_bearing_acronyms_and_decimals(self, fn) -> None:
        res = fn("Basis of Bearings: NAD 83, N.C. Grid North 2.5 deg.")
        assert res is not None
        assert "N.C." in res
        assert "2.5" in res

    @pytest.mark.parametrize(
        "fn", [pkg_metadata.extract_coordinate_system, TextParser.extract_coordinate_system]
    )
    def test_coordinate_system_acronyms(self, fn) -> None:
        coord, _ = fn("State Plane Coordinate System, N.C. Zone 3200, NAD 83.")
        assert coord is not None
        assert "Zone 3200" in coord


class TestB22PlssMetadata:
    @pytest.mark.parametrize(
        "fn", [pkg_metadata.extract_plss_metadata, TextParser.extract_plss_metadata]
    )
    def test_time_pm_sec_aliquot_and_meridian_prefix(self, fn) -> None:
        res_pm = fn("Recorded at 3 P.M. in Section 12")
        assert res_pm["principal_meridian"] is None

        res_pm_time = fn("Recorded at 12:30 P.M.")
        assert res_pm_time["principal_meridian"] is None

        res_sec = fn("SEC. 12, T3N, R2W")
        assert res_sec["section"] == "12"

        res_aliquot = fn("NE 1/4 of Section 12")
        assert res_aliquot["aliquot"] == "NE 1/4"

        res_pm_clean = fn(
            "Section 12, Township 3 North, Range 4 West of the Willamette Principal Meridian"
        )
        assert res_pm_clean["principal_meridian"] == "Willamette Principal Meridian"


class TestB23SubdivisionReference:
    @pytest.mark.parametrize(
        "fn",
        [
            pkg_metadata.extract_subdivision_reference,
            TextParser.extract_subdivision_reference,
        ],
    )
    def test_stopwords_rejected_and_uppercase_lot_block(self, fn) -> None:
        assert fn("CONTAINING a lot of land with a concrete block wall.") is None
        ref = fn("LOT 5, BLOCK 2, SUNRISE ESTATES")
        assert ref is not None
        assert ref.lot == "5"
        assert ref.block == "2"
        assert ref.subdivision_name == "SUNRISE ESTATES"


class TestB24AreaStatement:
    @pytest.mark.parametrize(
        "fn", [pkg_metadata.extract_area_statement, TextParser.extract_area_statement]
    )
    def test_square_foot_and_parent_parcel_lot(self, fn) -> None:
        res = fn("CONTAINING 5,000 square foot more or less")
        assert res is not None
        assert res["value_sq_ft"] == pytest.approx(5000.0)

        assert fn("CONTAINING 10 acres of the parent parcel") is None
        assert fn("CONTAINING 10 acres of the original lot") is None
