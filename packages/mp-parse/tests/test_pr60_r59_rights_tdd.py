"""PR #60 round 59: a reservation of rights after the boundary is no land exception.

Round 48 set every stated EXCEPT clause after a closed description aside as an unapplied
land exception, whose blocking warning stops verification. `main` verified and exported
deeds ending in "EXCEPTING AND RESERVING all oil, gas and mineral rights.", although the
same wording before the description is exempt (``tracts._RIGHTS_RECITAL``, r58).

A reservation or exception of RIGHTS (mineral, oil, gas and coal rights, an easement or
right of way not described by courses, rights of the public, riparian, water and air
rights) is not land: it is kept verbatim in the notes under its own registered prefix and
raises no warning. Land exceptions (strips, "that portion conveyed to ...", described
parcels, a portion lying within a street) keep "exception not applied" and the warning.
One predicate (``mp_parse.rights``) serves both positions.
"""

from __future__ import annotations

import pytest
from mp_models import (
    FIXED_NOTE_PREFIXES,
    VERBATIM_NOTE_PREFIXES,
    split_notes,
    unapplied_exceptions,
)
from mp_parse import extract_calls
from mp_verify import verify_closure, verify_tract

INTRO = (
    "ALL THAT CERTAIN lot, piece or parcel of land, with the buildings and improvements "
    "thereon erected, situate, lying and being in the Borough of Haddonfield, County of "
    "Camden and State of New Jersey, bounded and described as follows:\n\n"
)
SQ = (
    "BEGINNING at a point in the Southerly line of Main Street; THENCE (1) South 10 degrees "
    "00 minutes 00 seconds East 100.00 feet to a point; THENCE (2) South 80 degrees 00 minutes "
    "00 seconds West 50.00 feet to a point; THENCE (3) North 10 degrees 00 minutes 00 seconds "
    "West 100.00 feet to the Southerly line of Main Street; THENCE (4) along the same North 80 "
    "degrees 00 minutes 00 seconds East 50.00 feet to the point and place of BEGINNING."
)
SQ2 = (
    "BEGINNING at a point in the Westerly line of Elm Avenue; THENCE (1) North 20 degrees 00 "
    "minutes 00 seconds West 30.00 feet to a point; THENCE (2) South 70 degrees 00 minutes "
    "00 seconds West 20.00 feet to a point; THENCE (3) South 20 degrees 00 minutes 00 seconds "
    "East 30.00 feet to a point; THENCE (4) North 70 degrees 00 minutes 00 seconds East 20.00 "
    "feet to the point and place of BEGINNING."
)
RIGHTS_PREFIX = "rights reserved, not a land exception: "

# Rights-only clauses after the boundary (the wording, without its final period).
RIGHTS_CLAUSES = {
    "mineral": "EXCEPTING AND RESERVING all oil, gas and mineral rights",
    "easement": (
        "EXCEPTING AND RESERVING unto the Grantor an easement for ingress and egress "
        "over the existing driveway"
    ),
    "row_record": (
        "EXCEPTING AND RESERVING unto the Grantor a right of way as described in "
        "Deed Book 100 page 5"
    ),
    "public": "EXCEPTING therefrom the rights of the public in Main Street",
    "coal_timber": "EXCEPT AND RESERVE unto the Grantor the coal and timber rights",
    "less_mineral": "LESS AND EXCEPT all mineral rights",
    "water": "EXCEPTING AND RESERVING all riparian and water rights",
    "air": "EXCEPTING AND RESERVING all air rights above the existing building",
    "row_plural": "SAVE AND EXCEPT the rights of way of record",
}
# Land exceptions keep "exception not applied" and the blocking warning.
LAND_CLAUSES = {
    "strip": "EXCEPTING the westerly 10 feet thereof",
    "conveyed": "EXCEPTING that portion conveyed to the County",
    "bed": "EXCEPTING thereout and therefrom all that portion lying within the bed of Main Street",
    "parcel": "LESS AND EXCEPT the parcel conveyed to John Smith by deed recorded in Book 5",
    "strip_row": "EXCEPTING a right of way strip 30 feet wide along the Westerly line",
    "row_parcel": "EXCEPTING the right of way and the parcel conveyed to the State",
    "lot": "EXCEPTING Lot 7 as shown on the filed map",
}


def _single(clause: str) -> str:
    return INTRO + SQ + "\n\n" + clause + "."


@pytest.mark.parametrize("name", RIGHTS_CLAUSES)
def test_rights_reservation_after_boundary_is_not_a_land_exception(name: str) -> None:
    clause = RIGHTS_CLAUSES[name]
    calls, _ = extract_calls(_single(clause), strict=False)
    assert len(calls) == 4
    notes = [part for call in calls for part in split_notes(call.notes)]
    assert notes == [RIGHTS_PREFIX + clause]
    assert all(unapplied_exceptions(call.notes) == [] for call in calls)
    result = verify_closure(calls)
    assert result.is_fully_verified(), result.warnings
    assert not any("not applied" in warning for warning in result.warnings)


@pytest.mark.parametrize("name", LAND_CLAUSES)
def test_land_exception_after_boundary_stays_blocked(name: str) -> None:
    clause = LAND_CLAUSES[name]
    calls, _ = extract_calls(_single(clause), strict=False)
    notes = [part for call in calls for part in split_notes(call.notes)]
    assert notes == ["exception not applied: " + clause]
    result = verify_closure(calls)
    assert not result.is_fully_verified()
    assert any("not applied" in warning for warning in result.warnings)


def test_rights_reservation_before_boundary_is_unchanged() -> None:
    # The same wording before the description was already exempt (tracts._RIGHTS_RECITAL).
    calls, _ = extract_calls(
        "RESERVING unto the Grantor all oil, gas and mineral rights.\n\n" + INTRO + SQ,
        strict=False,
    )
    assert len(calls) == 4
    assert verify_closure(calls).is_fully_verified()


def test_rights_and_land_exceptions_side_by_side_keep_the_land_block() -> None:
    text = INTRO + SQ + "\n\n" + RIGHTS_CLAUSES["mineral"] + ".\n\n" + LAND_CLAUSES["strip"] + "."
    calls, _ = extract_calls(text, strict=False)
    notes = [part for call in calls for part in split_notes(call.notes)]
    assert notes == [
        RIGHTS_PREFIX + RIGHTS_CLAUSES["mineral"],
        "exception not applied: " + LAND_CLAUSES["strip"],
    ]
    result = verify_closure(calls)
    assert not result.is_fully_verified()
    assert [w for w in result.warnings if "not applied" in w] == [
        w for w in result.warnings if "westerly 10 feet" in w
    ]


def test_parcel_one_keeps_export_beside_a_rights_reservation() -> None:
    text = (
        "PARCEL ONE: "
        + INTRO
        + SQ
        + "\n\n"
        + RIGHTS_CLAUSES["mineral"]
        + ".\n\nPARCEL TWO: "
        + INTRO
        + SQ2
    )
    _, tracts = extract_calls(text, strict=False)
    assert len(tracts) == 2
    for tract in tracts:
        result = verify_tract(tract.calls, tract=tract)
        assert result.is_fully_verified(), (tract.label, result.warnings)
    first = [part for call in tracts[0].calls for part in split_notes(call.notes)]
    assert first == [RIGHTS_PREFIX + RIGHTS_CLAUSES["mineral"]]


def test_rights_note_prefix_is_registered_and_round_trips() -> None:
    assert RIGHTS_PREFIX in VERBATIM_NOTE_PREFIXES
    assert RIGHTS_PREFIX not in FIXED_NOTE_PREFIXES
    wording = "EXCEPTING AND RESERVING all oil, gas and mineral rights; and the coal; thereunder"
    notes = "; ".join(
        [
            "incomplete bearing - cardinal only",
            RIGHTS_PREFIX + wording,
            "exception not applied: EXCEPTING the West 10 feet thereof; conveyed to the County",
            "record call: 100 feet",
        ]
    )
    parts = split_notes(notes)
    assert parts == [
        "incomplete bearing - cardinal only",
        RIGHTS_PREFIX + wording,
        "exception not applied: EXCEPTING the West 10 feet thereof; conveyed to the County",
        "record call: 100 feet",
    ]
    assert "; ".join(parts) == notes
    assert unapplied_exceptions(notes) == [
        "EXCEPTING the West 10 feet thereof; conveyed to the County"
    ]


def test_one_predicate_serves_both_positions() -> None:
    from mp_parse.rights import is_rights_clause, is_rights_reservation

    for clause in RIGHTS_CLAUSES.values():
        assert is_rights_reservation(clause), clause
    for clause in LAND_CLAUSES.values():
        assert not is_rights_reservation(clause), clause
    # The clause after a lead (the position before the description).
    assert is_rights_clause(" all oil, gas and mineral rights")
    assert is_rights_clause(" unto the Grantor an easement for access over the driveway")
    assert not is_rights_clause(" the westerly 10 feet thereof")
    assert not is_rights_clause(" the right of way and the parcel conveyed to Smith")
    # The rights recitals tracts exempts before a description (r58) are rights here too,
    # except a portion lying within a street, which may be the land described next.
    for clause in (
        " unto the Grantor the mineral rights",
        " the oil and gas rights",
        " all oil, gas and minerals",
        " the coal and mining rights",
        " the rights of the public in and to Main Street",
        " the rights of way of record",
    ):
        assert is_rights_clause(clause), clause
    assert not is_rights_clause(" any portion lying within the right of way of Main Street")
    assert not is_rights_clause(" any portion within Main Street")
    # A land noun that only locates the rights names no land; one that is excepted does.
    assert is_rights_reservation("RESERVING all minerals in and under the premises")
    assert not is_rights_reservation("EXCEPTING all mineral rights and the premises conveyed")
    assert not is_rights_reservation("EXCEPTING an easement 20 feet wide along Elm Avenue")
