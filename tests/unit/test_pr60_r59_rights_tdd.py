"""PR #60 round 59: rights reservations after the boundary, through the monolith and review.

See ``packages/mp-parse/tests/test_pr60_r59_rights_tdd.py``. The monolith facades and text
review must agree with the package: a rights-only EXCEPT/RESERVING clause after the
boundary is kept verbatim under its own note and never blocks verification or export;
a land exception still does.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from mp_models import split_notes
from mp_review.api import review_text

from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker

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
RIGHTS = {
    "mineral": "EXCEPTING AND RESERVING all oil, gas and mineral rights.",
    "easement": (
        "EXCEPTING AND RESERVING unto the Grantor an easement for ingress and egress "
        "over the existing driveway."
    ),
    "row_record": (
        "EXCEPTING AND RESERVING unto the Grantor a right of way as described in "
        "Deed Book 100 page 5."
    ),
    "public": "EXCEPTING therefrom the rights of the public in Main Street.",
}
LAND = {
    "strip": "EXCEPTING the westerly 10 feet thereof.",
    "conveyed": "EXCEPTING that portion conveyed to the County.",
}
PREFIX = "rights reserved, not a land exception: "


@pytest.mark.parametrize("name", RIGHTS)
def test_monolith_facade_verifies_a_rights_reservation(name: str) -> None:
    calls = CallExtractor.extract_calls(INTRO + SQ + "\n\n" + RIGHTS[name], strict=False)
    notes = [part for call in calls for part in split_notes(call.notes)]
    assert notes == [PREFIX + RIGHTS[name].rstrip(".")]
    result = ClosureChecker.verify_closure(calls)
    assert result.is_fully_verified(), result.warnings


@pytest.mark.parametrize("name", LAND)
def test_monolith_facade_still_blocks_a_land_exception(name: str) -> None:
    calls = CallExtractor.extract_calls(INTRO + SQ + "\n\n" + LAND[name], strict=False)
    assert not ClosureChecker.verify_closure(calls).is_fully_verified()


@pytest.mark.parametrize("name", RIGHTS)
def test_text_review_passes_a_rights_reservation(name: str, tmp_path: Path) -> None:
    result = review_text(INTRO + SQ + "\n\n" + RIGHTS[name], output_dir=tmp_path / "r")
    assert result["status"] == "checks_passed", result["errors"]
    assert (tmp_path / "r" / "calls_verified.csv").exists()


@pytest.mark.parametrize("name", LAND)
def test_text_review_still_blocks_a_land_exception(name: str, tmp_path: Path) -> None:
    result = review_text(INTRO + SQ + "\n\n" + LAND[name], output_dir=tmp_path / "r")
    assert result["status"] != "checks_passed"
    assert not (tmp_path / "r" / "calls_verified.csv").exists()


def test_parcel_one_of_two_keeps_export_beside_a_rights_reservation() -> None:
    text = (
        "PARCEL ONE: " + INTRO + SQ + "\n\n" + RIGHTS["mineral"] + "\n\nPARCEL TWO: " + INTRO + SQ2
    )
    tracts: list = []
    CallExtractor.extract_calls(text, strict=False, tracts=tracts)
    assert len(tracts) == 2
    for tract in tracts:
        assert ClosureChecker.verify_tract(tract.calls, tract=tract).is_fully_verified()
