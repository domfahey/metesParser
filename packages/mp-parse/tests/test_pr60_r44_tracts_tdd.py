"""PR #60 round 44: strip exceptions and appurtenant easements never join the boundary.

A strip exception ("EXCEPTING the westerly 10 feet thereof") states no course: it
is recorded verbatim on the boundary's closing course, never parsed as an
exception traverse, and verification reports the exception as unapplied. An
easement described by its own courses ("Together with an easement ... BEGINNING
...; thence ...") is its own easement tract; its legs are never appended to the
parcel boundary.
"""

from __future__ import annotations

import pytest
from mp_models import UNAPPLIED_EXCEPTION_NOTE_PREFIX, TractType
from mp_parse.calls import _extract_calls_from_text, extract_calls
from mp_parse.metadata import detect_strip_exceptions
from mp_parse.tracts import split_into_tracts
from mp_verify import verify_closure

SQUARE = (
    "BEGINNING at a pin; thence N 0° E 100 feet to a pin; thence S 90° E 100 feet to a pin; "
    "thence S 0° W 100 feet to a pin; thence N 90° W 100 feet to the point of beginning."
)
STRIPS = [
    " EXCEPTING the westerly 10 feet thereof.",
    " LESS AND EXCEPT the north 10 feet thereof.",
]
EASEMENTS = [
    " Together with an easement 10 feet wide, BEGINNING at a stake; "
    "thence N 5° E 20 feet; thence S 85° E 10 feet.",
    " ALSO an easement for ingress and egress described as follows: BEGINNING at a stake; "
    "thence N 5° E 20 feet; thence S 85° E 10 feet.",
    " Subject to a right of way described as follows: BEGINNING at a stake; "
    "thence N 5° E 20 feet; thence S 85° E 10 feet.",
]


def _boundary(calls):
    return [
        (c.course, c.bearing_azimuth_deg_from_north, c.distance_ft, c.to, c.is_exception)
        for c in calls
    ]


@pytest.fixture(scope="module")
def square_calls():
    calls, tracts = extract_calls(SQUARE)
    assert tracts == []
    return calls


@pytest.mark.parametrize("strip", STRIPS)
def test_strip_exception_is_not_an_exception_traverse(strip, square_calls) -> None:
    calls, tracts = extract_calls(SQUARE + strip)
    assert tracts == []
    assert _boundary(calls) == _boundary(square_calls)
    assert all(c.bearing_azimuth_deg_from_north is not None for c in calls)


@pytest.mark.parametrize("strip", STRIPS)
def test_flat_extraction_ignores_strip_exception(strip, square_calls) -> None:
    calls = _extract_calls_from_text(SQUARE + strip)
    assert _boundary(calls) == _boundary(square_calls)


@pytest.mark.parametrize("strip", STRIPS)
def test_strip_exception_is_recorded_verbatim_on_closing_course(strip) -> None:
    for calls in (extract_calls(SQUARE + strip)[0], _extract_calls_from_text(SQUARE + strip)):
        assert calls[-1].notes == UNAPPLIED_EXCEPTION_NOTE_PREFIX + strip.strip().rstrip(".")
        assert all(not c.notes for c in calls[:-1])


@pytest.mark.parametrize("strip", STRIPS)
def test_unapplied_strip_exception_blocks_eligibility_but_keeps_closure(strip) -> None:
    clean = verify_closure(extract_calls(SQUARE)[0])
    assert clean.is_fully_verified()
    result = verify_closure(extract_calls(SQUARE + strip)[0])
    assert result.misclosure_available and result.closure_passed
    assert not result.is_fully_verified()
    assert any("not applied" in w and strip.strip().rstrip(".") in w for w in result.warnings)


def test_strip_exception_detection_reads_erly_directions_and_whole_less_and_except() -> None:
    (west,) = detect_strip_exceptions("to the POB. EXCEPTING the westerly 10 feet thereof.")
    assert (west["direction"], west["width_ft"]) == ("West", 10.0)
    assert west["original_text"] == "EXCEPTING the westerly 10 feet thereof"
    (north,) = detect_strip_exceptions("to the POB. LESS AND EXCEPT the north 10 feet thereof.")
    assert north["original_text"] == "LESS AND EXCEPT the north 10 feet thereof"


def test_strip_exception_purpose_after_thereof_is_part_of_the_strip() -> None:
    (strip,) = detect_strip_exceptions(
        "to the point of beginning, except the North 60.00 feet thereof taken for road purposes."
    )
    assert strip["original_text"] == "except the North 60.00 feet thereof taken for road purposes"
    assert strip["purpose"] == "taken for road purposes"


def test_strip_exception_followed_by_another_tract_is_still_a_strip() -> None:
    text = "to the point of beginning, except the South 30 feet thereof. TRACT 2: BEGINNING at a pin; thence N 10° E 5 feet"
    assert [s["direction"] for s in detect_strip_exceptions(text)] == ["South"]


def test_lot_strip_with_trailing_qualifier_is_not_a_strip() -> None:
    # "of said Lot in even width ..." continues the exception; a partial strip is not read.
    assert (
        detect_strip_exceptions("Lot 12, except the South 43.65 feet of said Lot in even width")
        == []
    )


def test_closing_course_with_strip_is_no_longer_ambiguous() -> None:
    # MIWAYN-50795: the strip's width was read as a second course length.
    text = (
        "Beginning at a point distant North 2 degrees 56 minutes 20 seconds West 955.85 feet "
        "from the East 1/4 corner of Section 16, and proceeding thence South 87 degrees 03 "
        "minutes 40 seconds West 138.0 feet; thence North 2 degrees 56 minutes 20 seconds West "
        "324.0 feet; thence North 87 degrees 03 minutes 40 seconds East 138.0 feet; thence "
        "South 2 degrees 56 minutes 20 seconds East 324.0 feet to the Point of Beginning, "
        "except the South 30 feet thereof."
    )
    skips: list = []
    calls, tracts = extract_calls(text, strict=False, skipped_courses=skips)
    assert skips == [] and tracts == []
    assert [c.distance_ft for c in calls] == [138.0, 324.0, 138.0, 324.0]
    assert calls[-1].to == "the Point of Beginning"
    assert calls[-1].notes == UNAPPLIED_EXCEPTION_NOTE_PREFIX + "except the South 30 feet thereof"


def test_geometric_exception_is_still_an_exception_tract() -> None:
    text = (
        SQUARE + " EXCEPTING THEREFROM: BEGINNING at a pin; thence N 0° E 10 feet; "
        "thence S 90° E 10 feet; thence S 0° W 10 feet; thence N 90° W 10 feet to the point of beginning."
    )
    _calls, tracts = extract_calls(text)
    assert [(t.tract_type, len(t.calls)) for t in tracts] == [
        (TractType.MAIN, 4),
        (TractType.EXCEPTION, 4),
    ]


@pytest.mark.parametrize("easement", EASEMENTS)
def test_appurtenant_easement_is_its_own_tract(easement, square_calls) -> None:
    calls, tracts = extract_calls(SQUARE + easement)
    assert [(t.label, t.tract_type, len(t.calls)) for t in tracts] == [
        ("Tract 1", TractType.MAIN, 4),
        ("Easement 1", TractType.EASEMENT, 2),
    ]
    assert _boundary(tracts[0].calls) == _boundary(square_calls)
    assert [c.distance_ft for c in tracts[1].calls] == [20.0, 10.0]
    # The flat boundary list never carries easement legs.
    assert _boundary(calls) == _boundary(square_calls)
    assert verify_closure(tracts[0].calls).closure_passed


@pytest.mark.parametrize("easement", EASEMENTS)
def test_flat_extraction_keeps_easement_legs_out_of_the_boundary(easement, square_calls) -> None:
    calls = _extract_calls_from_text(SQUARE + easement)
    assert _boundary(calls) == _boundary(square_calls)
    assert easement.strip() in (calls[-1].notes or "")
    result = verify_closure(calls)
    assert result.closure_passed


def test_split_into_tracts_types_easement() -> None:
    segments = split_into_tracts(SQUARE + EASEMENTS[0])
    assert [(label, kind) for _, label, kind in segments] == [
        ("Tract 1", TractType.MAIN),
        ("Easement 1", TractType.EASEMENT),
    ]
    assert segments[1][0] == EASEMENTS[0].strip()


def test_easement_wording_inside_an_open_description_is_not_split(square_calls) -> None:
    text = SQUARE.replace("BEGINNING at a pin;", "BEGINNING at a pin, subject to a right of way,")
    calls, tracts = extract_calls(text)
    assert tracts == []
    assert len(calls) == 4


def test_easement_clause_without_courses_stays_a_clause(square_calls) -> None:
    calls, tracts = extract_calls(SQUARE + " Together with an easement of record for utilities.")
    assert tracts == []
    assert _boundary(calls) == _boundary(square_calls)


def test_also_inside_a_commencing_clause_is_not_an_easement() -> None:
    # MIWAYN-50837: ", also being the Southerly right of way of Mack Avenue" names a corner.
    text = (
        "Commencing at the Northwest corner of Lot 15, also being the Southerly right of way "
        "of Mack Avenue; Thence S 26° E 120.00 feet for the point of beginning; "
        "Thence N 58° E 100 feet; Thence S 32° E 50 feet; Thence S 58° W 100 feet; "
        "Thence N 32° W 50 feet to the point of beginning."
    )
    calls, tracts = extract_calls(text)
    assert tracts == []
    assert [c.distance_ft for c in calls] == [120.0, 100.0, 50.0, 100.0, 50.0]


def test_point_of_beginning_tie_followed_by_courses_does_not_close_the_exception() -> None:
    # 36 Kresson Rd (9888-954): "(B) ... to a point and place of beginning, thence; (1) ..."
    import json
    from pathlib import Path

    sample = next(
        Path(__file__)
        .resolve()
        .parents[3]
        .glob("sample_deeds/36 Kresson Rd - Deed Image (9888 - 954).ground_truth.json")
    )
    truth = json.loads(sample.read_text())
    _calls, tracts = extract_calls(truth["expected_legal_description"])
    expected = [(c["direction_text"], c["distance_ft"]) for c in truth["expected_calls"]]
    assert [(t.tract_type, len(t.calls)) for t in tracts] == [
        (TractType.MAIN, 4),
        (TractType.EXCEPTION, 5),
    ]
    assert [(c.direction_text, c.distance_ft) for t in tracts for c in t.calls] == expected


def test_excepted_right_of_way_is_an_exception_not_an_easement() -> None:
    text = (
        SQUARE
        + " ALSO EXCEPTING therefrom a right of way described as follows: BEGINNING at a pin; "
        "thence N 0° E 10 feet; thence S 90° E 10 feet; thence S 0° W 10 feet; "
        "thence N 90° W 10 feet to the point of beginning."
    )
    _calls, tracts = extract_calls(text)
    assert [t.tract_type for t in tracts] == [TractType.MAIN, TractType.EXCEPTION]
