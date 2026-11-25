from __future__ import annotations

import pytest
from mp_models import AuditContext
from mp_parse.calls import extract_calls as package_extract_calls_with_tracts
from mp_parse.metadata import extract_distance as package_extract_distance
from mp_verify import verify_closure

from metesparser.call_extractor import CallExtractor
from metesparser.models import AuditContext as MonolithAuditContext
from metesparser.text_parser import TextParser
from tests.fixtures.package_parser import extract_calls as package_extract_calls

PARSERS = (package_extract_calls, CallExtractor.extract_calls)
DISTANCE_PARSERS = (package_extract_distance, TextParser.extract_distance)

REAL_WALNUT_TRACT_3 = (
    "Tract No. 3\n"
    "BEGINNING at a point which is located at the following two courses and distances "
    "from the intersection of the Southwesterly line of Ellis Street (66 feet wide) "
    "with the Southeasterly line of Walnut Street (60 feet wide); thence\n\n"
    "South 71 degrees 54 minutes 50 seconds East along the Southwesterly line of Ellis Street "
    "122.55 feet to a point. South 18 degrees 05 minutes 10 seconds West 123.00 feet to the "
    "point and place of beginning; thence\n\n"
    "(1) South 18 degrees 05 minutes 10 seconds West 82.00 feet to a point; thence\n"
    "(2) North 71 degrees 54 minutes 50 seconds West 53.36 feet to a point; thence\n"
    "(3) North 18 degrees 17 minutes 22 seconds East 82.00 feet to a point; thence\n"
    "(4) South 71 degrees 54 minutes 50 seconds East 53.19 feet to the point and place of beginning."
)


class TestBug1InlineTieInPreamble:
    @pytest.mark.parametrize("parse", PARSERS)
    def test_multiline_walnut_tract_3_extracts_6_calls_and_closes(self, parse):
        calls = parse(REAL_WALNUT_TRACT_3)
        assert len(calls) == 6

        assert calls[0].bearing_quadrant == "S 71°54'50\" E"
        assert calls[0].bearing_azimuth_deg_from_north == pytest.approx(108.0861, abs=0.001)
        assert calls[0].distance_ft == pytest.approx(122.55)
        assert calls[0].is_tie_in is True

        assert calls[1].bearing_azimuth_deg_from_north == pytest.approx(198.0861, abs=0.001)
        assert calls[1].distance_ft == pytest.approx(123.00)
        assert calls[1].is_tie_in is True

        assert [c.distance_ft for c in calls[2:]] == pytest.approx([82.00, 53.36, 82.00, 53.19])
        assert all(not c.is_tie_in for c in calls[2:])

        closure = verify_closure(calls)
        assert closure.misclosure_ft < 0.5

    @pytest.mark.parametrize("parse", PARSERS)
    def test_parenthetical_street_width_before_numbered_calls_not_matched_as_course_1(self, parse):
        text = (
            "Tract No. 3\n"
            "BEGINNING at a point which is located at the following two courses and distances "
            "from the intersection of Ellis Street (66) feet wide with Walnut Street (60) feet wide; "
            "thence\n\n"
            "South 71 degrees 54 minutes 50 seconds East 122.55 feet to a point. "
            "South 18 degrees 05 minutes 10 seconds West 123.00 feet to the point and place of beginning; "
            "thence\n\n"
            "(1) South 18 degrees 05 minutes 10 seconds West 82.00 feet to a point; thence\n"
            "(2) North 71 degrees 54 minutes 50 seconds West 53.36 feet to a point; thence\n"
            "(3) North 18 degrees 17 minutes 22 seconds East 82.00 feet to a point; thence\n"
            "(4) South 71 degrees 54 minutes 50 seconds East 53.19 feet to the point and place of beginning."
        )
        calls = parse(text)
        assert len(calls) == 6
        assert calls[0].is_tie_in is True
        assert calls[0].distance_ft == pytest.approx(122.55)
        assert calls[1].is_tie_in is True
        assert calls[1].distance_ft == pytest.approx(123.00)
        assert all(not c.is_tie_in for c in calls[2:])

    @pytest.mark.parametrize("parse", PARSERS)
    def test_due_cardinal_tie_in_in_inline_preamble_is_split(self, parse):
        text = (
            "BEGINNING at a point located at the following two courses and distances from a stone; "
            "thence S 71°54'50\" E 122.55 feet to a point. "
            "due South 123.00 feet to the point and place of beginning; thence\n"
            "(1) South 18 degrees 05 minutes 10 seconds West 82.00 feet to a point; thence\n"
            "(2) North 71 degrees 54 minutes 50 seconds West 53.36 feet to a point."
        )
        calls = parse(text)
        assert len(calls) == 4
        assert calls[0].is_tie_in is True
        assert calls[1].is_tie_in is True
        assert calls[1].bearing_azimuth_deg_from_north == pytest.approx(180.0)
        assert calls[1].distance_ft == pytest.approx(123.00)
        assert all(not c.is_tie_in for c in calls[2:])

    @pytest.mark.parametrize("parse", PARSERS)
    def test_packed_dms_tie_in_in_inline_preamble_is_split(self, parse):
        text = (
            "BEGINNING at a point located at the following two courses and distances from a stone; "
            "thence S 71°54'50\" E 122.55 feet to a point. "
            "S 18.0510° W 123.00 feet to the point and place of beginning; thence\n"
            "(1) South 18 degrees 05 minutes 10 seconds West 82.00 feet to a point; thence\n"
            "(2) North 71 degrees 54 minutes 50 seconds West 53.36 feet to a point."
        )
        calls = parse(text)
        assert len(calls) == 4
        assert calls[0].is_tie_in is True
        assert calls[1].is_tie_in is True
        assert calls[1].distance_ft == pytest.approx(123.00)
        assert all(not c.is_tie_in for c in calls[2:])


class TestBug2ExtractDistance:
    @pytest.mark.parametrize("extract", DISTANCE_PARSERS)
    @pytest.mark.parametrize(
        "text",
        [
            "N 45°35' to a point",
            "N 45° 35' to a point",
            "S 12°05' to an iron pin",
            "S 12° 05' along the road",
        ],
    )
    def test_dms_minutes_apostrophe_does_not_fabricate_feet(self, extract, text):
        distance, _unit = extract(text)
        assert distance == 0.0

    @pytest.mark.parametrize("parse", PARSERS)
    def test_compound_false_positive_in_strip_and_easement_clause(self, parse):
        calls = parse(
            "N 45°00' E 100.00 feet along a 50 foot strip and 60 foot easement to a point"
        )
        assert len(calls) == 1
        assert calls[0].distance_ft == pytest.approx(100.0)

    @pytest.mark.parametrize("parse", PARSERS)
    def test_compound_false_positive_in_acre_tracts_clause(self, parse):
        calls = parse("N 45°00' E 100.00 feet to the corner of 10 acre tract and 20 acre tract")
        assert len(calls) == 1
        assert calls[0].distance_ft == pytest.approx(100.0)

    @pytest.mark.parametrize("parse", PARSERS)
    def test_primary_distance_precedes_later_offset_compound_distances(self, parse):
        calls = parse("N 45°00' E 100.00 feet to a point 10 feet and 20 feet from the street")
        assert len(calls) == 1
        assert calls[0].distance_ft == pytest.approx(100.0)

    @pytest.mark.parametrize("parse", PARSERS)
    def test_missing_primary_distance_with_non_linear_and_raises_missing_not_compound(self, parse):
        with pytest.raises(ValueError, match="Missing boundary course distance"):
            parse("THENCE N 45°00' E to the corner of 10 acre tract and 20 acre tract", strict=True)


class TestBug3PackageNonMetesClausesStrict:
    @pytest.mark.parametrize(
        "clause",
        [
            "EXCEPTING right-of-way for public roads.",
            "ALSO known as 123 Main Street.",
            "INCLUDING all buildings and improvements thereon.",
        ],
    )
    def test_non_metes_clause_does_not_crash_in_strict_mode(self, clause):
        text = (
            "BEGINNING at a point; "
            "THENCE N 0°00' E 100.00 feet to a point; "
            "THENCE S 90°00' E 100.00 feet to a point; "
            "THENCE S 0°00' W 100.00 feet to a point; "
            "THENCE N 90°00' W 100.00 feet to the point of beginning. "
            f"{clause}"
        )
        calls, tracts = package_extract_calls_with_tracts(text, strict=True)
        assert len(calls) == 4
        assert tracts == []

    def test_explicit_empty_tract_header_still_raises_in_strict_mode(self):
        text = (
            "TRACT 1: BEGINNING at a point; "
            "THENCE N 0°00' E 100.00 feet to a point; "
            "THENCE S 90°00' E 100.00 feet to a point; "
            "THENCE S 0°00' W 100.00 feet to a point; "
            "THENCE N 90°00' W 100.00 feet to the point of beginning. "
            "TRACT 2: Lot 5 of Elm Subdivision."
        )
        with pytest.raises(ValueError, match="has no computable calls"):
            package_extract_calls_with_tracts(text, strict=True)


class TestBug7NumberedPreambleWithoutThence:
    @pytest.mark.parametrize("parse", PARSERS)
    def test_heading_before_beginning_with_numbered_calls_and_no_thence(self, parse):
        text = (
            "Lot 5 of Elm Subdivision.\n"
            "BEGINNING at a point in the North line of Oak Street (50 feet wide);\n"
            "(1) North 00°00'00\" East 100.00 feet to a point;\n"
            "(2) South 90°00'00\" East 100.00 feet to a point;\n"
            "(3) South 00°00'00\" West 100.00 feet to a point;\n"
            "(4) North 90°00'00\" West 100.00 feet to the point of beginning."
        )
        calls = parse(text, strict=True)
        assert len(calls) == 4
        assert [c.distance_ft for c in calls] == pytest.approx([100.0, 100.0, 100.0, 100.0])


class TestBug13AuditSingleCallUsesBoundaryCourseText:
    def test_package_audit_distance_ignores_witness_tree_distance(self):
        ctx = AuditContext(
            run_metadata={
                "parser_version": "test",
                "llm_provider": "test",
                "llm_model": "test",
                "prompt_hash": "test",
                "cache_enabled": False,
                "source_pdf": "test.pdf",
                "timestamp_utc": "2026-01-01T00:00:00Z",
            }
        )
        calls, _ = package_extract_calls_with_tracts(
            "THENCE N 45°00' E 100' to an iron pin, from which a witness tree bears S 45° W 50 feet",
            audit_context=ctx,
        )
        assert len(calls) == 1
        assert calls[0].distance_ft == pytest.approx(100.0)
        dist_transforms = [
            t for t in ctx.call_audits[0].transformations if t.step == "extract_distance"
        ]
        assert len(dist_transforms) == 1
        assert dist_transforms[0].input == "100.0 feet"
        assert dist_transforms[0].output == "100.0"

    def test_monolith_audit_distance_ignores_witness_tree_distance(self):
        ctx = MonolithAuditContext(
            run_metadata={
                "parser_version": "test",
                "llm_provider": "test",
                "llm_model": "test",
                "prompt_hash": "test",
                "cache_enabled": False,
                "source_pdf": "test.pdf",
                "timestamp_utc": "2026-01-01T00:00:00Z",
            }
        )
        calls = CallExtractor.extract_calls(
            "THENCE N 45°00' E 100' to an iron pin, from which a witness tree bears S 45° W 50 feet",
            audit_context=ctx,
        )
        assert len(calls) == 1
        assert calls[0].distance_ft == pytest.approx(100.0)
        dist_transforms = [
            t for t in ctx.call_audits[0].transformations if t.step == "extract_distance"
        ]
        assert len(dist_transforms) == 1
        assert dist_transforms[0].input == "100.0 feet"
        assert dist_transforms[0].output == "100.0"
