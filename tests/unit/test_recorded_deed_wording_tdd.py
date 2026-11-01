"""Wording from the recorded sample deeds, parsed by both parsers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mp_parse import extract_calls as package_extract_with_tracts
from mp_parse import mark_tie_in_calls

from metesparser.call_extractor import CallExtractor
from tests.fixtures.package_parser import extract_calls as package_extract_calls

PARSERS = (package_extract_calls, CallExtractor.extract_calls)
TIE_MARKERS = (mark_tie_in_calls, CallExtractor.mark_tie_in_calls)

SAMPLE_DEEDS = Path(__file__).resolve().parents[2] / "sample_deeds"


def _legal_description(name: str) -> str:
    gt = json.loads((SAMPLE_DEEDS / f"{name}.ground_truth.json").read_text(encoding="utf-8"))
    return str(gt["expected_legal_description"])


@pytest.mark.parametrize("parse", PARSERS)
@pytest.mark.parametrize(
    ("bearing_text", "expected_azimuth"),
    [
        ("North 34 degrees 02' 00\" West", 325.966667),
        ("South 00°44'00\" West", 180.733333),
        ("South 26 deg. 00' 41\" East", 153.988611),
        ("S0DEG 49M 20S W", 180.822222),
        ("N 89D 05M 3SEC W", 270.915833),
    ],
)
def test_bearing_mixing_words_and_symbols(parse, bearing_text, expected_azimuth):
    call = parse(f"thence {bearing_text} 129.00 feet to a point", strict=True)[0]
    assert call.bearing_azimuth_deg_from_north == pytest.approx(expected_azimuth)
    assert call.distance_ft == pytest.approx(129.0)


@pytest.mark.parametrize("parse", PARSERS)
def test_assessor_description_with_offset_preamble(parse):
    """Deed 50062-01403: the "AND" offsets before FROM locate the POB; they are not courses."""
    calls = parse(
        "BEG S0DEG 32M 50S W 401.55FT AND N80DEG 29M 20S W 480.49FT AND S0DEG 49M 20S W "
        "142.75FT AND N89DEG 10M 40S W 2FT FROM NE COR SEC 36 TH S0DEG 49M 20S W 175FT "
        "TH N89DEG 10M 40S W 61.23FT TH N0DEG 49M E 175FT TH S89DEG 10M 40S E 61.26FT POB",
        strict=True,
    )
    assert [call.distance_ft for call in calls] == pytest.approx([175, 61.23, 175, 61.26])


@pytest.mark.parametrize(("parse", "mark"), zip(PARSERS, TIE_MARKERS, strict=True))
def test_commencement_course_ending_for_the_point_of_beginning_is_a_tie(parse, mark):
    """Deed 50837-00216: the closing course is not a tie line."""
    text = (
        "Commencing at the Northwest corner of Lot 15; Thence South 26 deg. 00' 41\" East, "
        "120.00 feet along the Easterly right of way of Fairview Avenue for the point of "
        "beginning; Thence North 58 deg. 14' 00\" East 232.17 feet; Thence South 26 deg. 00' "
        '41" East 120.00 feet; Thence South 58 deg. 14\' 00" West 232.17 feet to the point of '
        "beginning."
    )
    calls = mark(parse(text, strict=True), "the Northwest corner of Lot 15")
    assert [call.is_tie_in for call in calls] == [True, False, False, False]


@pytest.mark.parametrize("mark", TIE_MARKERS)
def test_tie_marking_keeps_tract_level_ties(mark):
    """101-111 Kings Highway E: a commencement in Tract 2 does not reach into Tract 1."""
    calls, _tracts = package_extract_with_tracts(
        _legal_description("101-111 Kings Highway E - Deed Image (7683 - 1295)"), strict=True
    )
    marked = mark(calls, "a point in the revised Northwesterly line of Kings Highway East")
    assert [call.is_tie_in for call in marked] == [call.is_tie_in for call in calls]


@pytest.mark.parametrize("parse", PARSERS)
def test_comma_joined_courses_are_split_but_offsets_are_not(parse):
    """Deed 50306-00349 Parcel 2."""
    calls = parse(
        "beginning at a point South 78 degrees 15 minutes 40 seconds East 445.93 feet, North "
        "73 degrees 05 minutes 24 seconds West 49.61 feet from the corner of Lot 13; thence "
        "South 16 degrees, 54 minutes, 36 seconds West, 85.33 feet, North 73 degrees, 05 "
        "minutes, 24 seconds West, 128.0 feet; thence North 16 degrees, 54 minutes, 36 "
        "seconds East, 85.33 feet to the point of beginning.",
        strict=True,
    )
    assert [call.distance_ft for call in calls] == pytest.approx([85.33, 128.0, 85.33])


@pytest.mark.parametrize("parse", PARSERS)
def test_strip_deeded_for_roadway_is_not_a_course(parse):
    """Deed 50512-00525."""
    calls = parse(
        "Beginning at a point; thence North 00 degrees 04 minutes West, 80 feet to a point; "
        "thence South 89 degrees 48 minutes 45 seconds West, 214 feet to a point of beginning, "
        "except the East 20 feet deeded for roadway.",
        strict=True,
    )
    assert [call.distance_ft for call in calls] == pytest.approx([80, 214])


@pytest.mark.parametrize("parse", PARSERS)
def test_excluding_that_part_is_an_exception(parse):
    """Deed 50428-01001."""
    calls = parse(_legal_description("deed 50428-01001"), strict=False)
    assert [call.distance_ft for call in calls] == pytest.approx([20.0, 50.2, 46.37])
    assert all(call.is_exception for call in calls)


def test_lot_reference_with_excluded_part_parses_in_strict_mode():
    """The parcel is Lot 48 by plat less a triangle; only the excluded triangle has courses."""
    calls, tracts = package_extract_with_tracts(
        _legal_description("deed 50428-01001"), strict=True
    )
    assert [(tract.label, tract.tract_type.value, len(tract.calls)) for tract in tracts] == [
        ("Exception 1", "exception", 3)
    ]
    assert all(call.is_exception for call in calls)


@pytest.mark.parametrize("parse", PARSERS)
def test_endpoint_on_next_curve_and_note_before_unit(parse):
    """Deed 50146-01291."""
    calls = parse(
        "thence North 89 degrees 09 minutes 29 seconds East 551.39 feet to a point on the "
        "Westerly Right-of-Way of I-275, said point also being a point on a non-tangential "
        "curve to the left; thence along said line North 89 degrees 08 minutes 49 seconds "
        "East 704.61 (surveyed as 704.60) feet to a point",
        strict=True,
    )
    assert [call.distance_ft for call in calls] == pytest.approx([551.39, 704.61])
    assert calls[0].curve_dir is None


@pytest.mark.parametrize("parse", PARSERS)
def test_combined_description_after_marked_parcels_has_its_own_ties(parse):
    """Deed 50146-01291: Parcel A, Parcel B and a combined description each commence."""
    calls = parse(_legal_description("deed 50146-01291"), strict=True)
    assert len(calls) == 42
    assert [i for i, call in enumerate(calls, 1) if call.is_tie_in] == [1, 2, 14, 15, 29, 30]


def test_combined_description_is_its_own_tract():
    _calls, tracts = package_extract_with_tracts(
        _legal_description("deed 50146-01291"), strict=True
    )
    assert [(tract.label, len(tract.calls)) for tract in tracts] == [
        ("Parcel A", 13),
        ("Parcel B", 15),
        ("Parcel B, description 2", 14),
    ]


@pytest.mark.parametrize("parse", PARSERS)
def test_exception_stays_with_its_parcel_and_next_parcel_is_not_excepted(parse):
    """Deed 50306-00349: Parcel 1 excepts a parcel that Parcel 2 then conveys."""
    calls = parse(_legal_description("deed 50306-00349"), strict=True)
    assert len(calls) == 26
    assert [call.is_exception for call in calls] == [False] * 4 + [True] * 11 + [False] * 11


DEED_50492 = (
    "Property Commencing 88 degrees 54 minutes 18 seconds West from the Southeast corner of "
    "said Section 7;\nthence along the South line of said Section 7 505.00 feet;\nthence "
    "continuing North 88 degrees 54 minutes 18 seconds West 159.56 feet;\nthence North 00 "
    "degrees 35 minutes 20 seconds East 295.05 feet;\nthence South 89 degrees 18 minutes 20 "
    "second East 160.75 feet;\nthence South 00 degrees 49 minutes 10 seconds West 296.17 feet "
    "to the point of beginning."
)


@pytest.mark.parametrize("parse", PARSERS)
def test_tie_to_an_unstated_point_of_beginning_is_inferred_from_closure(parse):
    """Deed 50492-00960: courses 2-5 close to 0.006 ft without course 1."""
    calls = parse(DEED_50492, strict=True)
    assert [call.is_tie_in for call in calls] == [True, False, False, False, False]
    assert "inferred from closure" in (calls[0].notes or "")


def test_inferred_tie_is_recorded_in_the_audit():
    from datetime import UTC, datetime

    from mp_models import AuditContext, RunMetadata

    audit = AuditContext(
        run_metadata=RunMetadata(
            parser_version="test",
            llm_provider="none",
            llm_model="none",
            prompt_hash="",
            timestamp_utc=datetime.now(UTC),
            source_pdf="isolated text",
            cache_enabled=False,
            config={},
        )
    )
    package_extract_with_tracts(DEED_50492, audit_context=audit, strict=True)
    first = audit.call_audits[0]
    assert "tie_inferred_from_closure" in first.flags
    assert [decision.field for decision in first.decisions][-1] == "is_tie_in"
    assert all("tie_inferred_from_closure" not in entry.flags for entry in audit.call_audits[1:])


@pytest.mark.parametrize("parse", PARSERS)
def test_no_tie_is_inferred_when_every_course_closes(parse):
    calls = parse(
        "Commencing at the Southeast corner of Section 7; thence due North 100.00 feet; thence "
        "due East 100.00 feet; thence due South 100.00 feet; thence due West 100.00 feet to the "
        "point of beginning.",
        strict=True,
    )
    assert len(calls) == 4
    assert not any(call.is_tie_in for call in calls)


def test_tract_with_course_text_but_no_computable_calls_still_fails_in_strict_mode():
    with pytest.raises(ValueError, match="no computable calls"):
        package_extract_with_tracts(
            "TRACT 1: BEGINNING at a point; thence North 10 degrees East 100.00 feet; thence "
            "South 80 degrees East 100.00 feet; thence South 10 degrees West 100.00 feet to the "
            "point of beginning. TRACT 2: BEGINNING at a stone distant 40.00 feet from the corner "
            "of Lot 7.",
            strict=True,
        )
