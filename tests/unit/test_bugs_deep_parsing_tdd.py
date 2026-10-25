"""Deep parser regressions where silent data loss can produce false closure."""

import pytest
from mp_parse.calls import extract_calls

from metesparser.call_extractor import CallExtractor

APIS = [extract_calls, CallExtractor.extract_calls]


@pytest.mark.parametrize("parse_calls", APIS)
def test_explicit_feet_overrides_document_chains(parse_calls):
    calls = parse_calls("THENCE N 45° E 100'", distance_unit="chains")
    assert len(calls) == 1
    assert calls[0].distance_ft == pytest.approx(100)


@pytest.mark.parametrize("parse_calls", APIS)
def test_apostrophe_feet_with_word_unit_overrides_document_unit(parse_calls):
    calls = parse_calls("THENCE N 45° E 100' feet", distance_unit="chains")
    assert len(calls) == 1
    assert calls[0].distance_ft == pytest.approx(100)


@pytest.mark.parametrize("parse_calls", APIS)
def test_engineer_units_are_recognized_in_curve_radius_and_arc(parse_calls):
    calls = parse_calls(
        "THENCE N 45° E along curve to the right, radius of 10 engineer chains, "
        "delta angle of 90 degrees, arc length 15.707963 engineer chains"
    )
    assert len(calls) == 1
    assert calls[0].radius_ft == pytest.approx(1000)
    assert calls[0].arc_length_ft == pytest.approx(1570.7963)


@pytest.mark.parametrize("parse_calls", APIS)
def test_engineer_links_are_recognized_as_engineer_units(parse_calls):
    calls = parse_calls(
        "THENCE N 45° E along curve to the right, radius of 10 engineer links, "
        "delta angle of 90 degrees"
    )
    assert len(calls) == 1
    assert calls[0].radius_ft == pytest.approx(10)


@pytest.mark.parametrize("parse_calls", APIS)
def test_initial_course_before_thence_is_preserved_without_beginning_preamble(parse_calls):
    calls = parse_calls(
        "N 45°30' E 100 feet; THENCE S 45° E 100 feet; THENCE "
        "S 45° W 100 feet; THENCE N 45° W 100 feet"
    )
    assert len(calls) == 4
    assert calls[0].course == 1
    assert calls[0].bearing_azimuth_deg_from_north == pytest.approx(45.5)
    assert calls[0].distance_ft == pytest.approx(100)


@pytest.mark.parametrize("parse_calls", APIS)
def test_endpoint_point_of_beginning_does_not_make_initial_course_a_preamble(parse_calls):
    calls = parse_calls(
        "N 45° E 100 feet; THENCE S 45° E 100 feet; THENCE "
        "S 45° W 100 feet; THENCE N 45° W 100 feet to the point of beginning"
    )
    assert len(calls) == 4


@pytest.mark.parametrize("parse_calls", APIS)
def test_due_cardinal_initial_course_before_thence_is_preserved(parse_calls):
    calls = parse_calls("due east 100 feet; THENCE due south 100 feet")
    assert len(calls) == 2
    assert calls[0].course == 1
    assert calls[0].bearing_azimuth_deg_from_north == pytest.approx(90)
    assert calls[0].distance_ft == pytest.approx(100)


@pytest.mark.parametrize("parse_calls", APIS)
def test_fullword_bearing_initial_course_before_thence_is_preserved(parse_calls):
    calls = parse_calls("North 45 degrees East 100 feet; THENCE South 45 degrees East 100 feet")
    assert len(calls) == 2
    assert calls[0].course == 1
    assert calls[0].bearing_azimuth_deg_from_north == pytest.approx(45)
    assert calls[0].distance_ft == pytest.approx(100)


@pytest.mark.parametrize("parse_calls", APIS)
def test_cardinal_only_initial_course_before_thence_is_preserved(parse_calls):
    calls = parse_calls("Northerly 100 feet; THENCE due east 100 feet")
    assert len(calls) == 2
    assert calls[0].course == 1
    assert calls[0].bearing_azimuth_deg_from_north is None
    assert calls[0].notes == "incomplete bearing - cardinal only"
    assert calls[0].distance_ft == pytest.approx(100)


@pytest.mark.parametrize("parse_calls", APIS)
def test_south_lot_strip_comma_does_not_mark_following_course_exception(parse_calls):
    calls = parse_calls(
        "Lot 12, except the South 1,200 feet of said Lot in even width, "
        "and all of Lot 13. THENCE N 45° E 100 feet"
    )
    assert len(calls) == 1
    assert calls[0].is_exception is False


@pytest.mark.parametrize("parse_calls", APIS)
def test_strict_default_rejects_malformed_course_instead_of_returning_partial_traverse(parse_calls):
    text = (
        "THENCE N 0° E 100 feet; THENCE N 90° E 100 feet; "
        "THENCE S 0° W 100 feet; THENCE N 90° W 100 feet; "
        "THENCE N 12.5960° E 10 feet"
    )
    with pytest.raises(ValueError, match=r"course 5.*N 12\.5960"):
        parse_calls(text)


@pytest.mark.parametrize("parse_calls", APIS)
@pytest.mark.parametrize(
    "unreadable_course",
    ["100 feet to an unreadable corner", "unreadable course"],
)
def test_strict_default_rejects_unreadable_explicit_thence_course(parse_calls, unreadable_course):
    text = (
        "THENCE N 0° E 100 feet; THENCE N 90° E 100 feet; "
        "THENCE S 0° W 100 feet; THENCE N 90° W 100 feet; "
        f"THENCE {unreadable_course}"
    )
    with pytest.raises(ValueError, match=r"course 5.*" + unreadable_course):
        parse_calls(text)


@pytest.mark.parametrize("parse_calls", APIS)
def test_strict_default_ignores_non_metes_text_without_thence(parse_calls):
    assert parse_calls("This paragraph has no survey calls.") == []


@pytest.mark.parametrize("parse_calls", APIS)
def test_strict_default_rejects_unreadable_numbered_course(parse_calls):
    text = "1. N 0° E 100 feet\n2. unreadable course"
    with pytest.raises(ValueError, match=r"course 2.*unreadable course"):
        parse_calls(text)


@pytest.mark.parametrize("parse_calls", APIS)
def test_strict_false_allows_explicit_partial_recovery(parse_calls):
    text = "THENCE N 0° E 100 feet; THENCE N 12.5960° E 10 feet"
    calls = parse_calls(text, strict=False)
    assert len(calls) == 1
    assert calls[0].course == 1
    assert calls[0].bearing_azimuth_deg_from_north == pytest.approx(0)
    assert calls[0].distance_ft == pytest.approx(100)
