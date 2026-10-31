"""PR #60 round 59: role bases are allow-listed (user policy: never export guessed land).

Round 58 decided "heading" and "single" by deny-lists of role wording, so wording the
lists missed exported easement and exception land as verified fee parcels, and a
round-57 deny rule blocked plainly headed deeds that ``main`` exported. The certain
bases are now allow-listed (``mp_parse.tracts``); everything else is "inferred", and
an inferred role blocks every verified export, a single description's too:

* "heading": a plain TRACT/PARCEL heading (its identifier, then at most ':', '.' or a
  dash), followed by nothing or the parcel's own intro ("ALL THAT ...", "Being Lot
  ...", "described as follows", "The land referred to herein ..."), with only harmless
  recitals between the previous description and it (no role wording, generic or
  rights recitals, or a recital about the previous parcel that names no described land
  when a full parcel intro follows), and no role statement after the last description.
* "single": the deed's only description, MAIN, when nothing that introduces or labels
  it (or states its role after it) is easement, exception, exclusion, reservation or
  right-of-way wording other than those harmless recitals and recitals inside the
  parcel's own intro sentence.

The reviewer's probes (A1-A4, B2) are replayed here; B1/B3 (rights-only reservations
after the boundary) are fixed on ``fix/pr60-r59-rights``.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest
from mp_export import export_verified_csv
from mp_models import (
    DESCRIPTION_ROLES_CHECK,
    DESCRIPTION_ROLES_NOTE,
    DESCRIPTION_ROLES_PREFIX,
    LegalDescription,
    TractType,
    roles_need_review,
    split_notes,
)
from mp_parse.calls import extract_calls
from mp_parse.tracts import find_tract_markers
from mp_review.api import review_text
from mp_verify import verify_closure, verify_tract

from metesparser import models as monolith
from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker
from metesparser.csv_builder import CSVBuilder
from tests.fixtures.parser_corpus import ROOT
from tests.unit.test_pr60_r58_mark_tdd import _csv_round_trip, _subsets, _verified_or_exported

# The reviewer's building blocks (round-58 review, mk1.py).
SQ = (
    "BEGINNING at a point in the Southerly line of Main Street; THENCE (1) South 10 degrees "
    "00 minutes 00 seconds East 100.00 feet to a point; THENCE (2) South 80 degrees 00 "
    "minutes 00 seconds West 50.00 feet to a point; THENCE (3) North 10 degrees 00 minutes "
    "00 seconds West 100.00 feet to the Southerly line of Main Street; THENCE (4) along the "
    "same North 80 degrees 00 minutes 00 seconds East 50.00 feet to the point and place of "
    "BEGINNING."
)
SQ2 = (
    "BEGINNING at a point in the Westerly line of Elm Avenue; THENCE (1) North 20 degrees "
    "00 minutes 00 seconds West 30.00 feet to a point; THENCE (2) South 70 degrees 00 "
    "minutes 00 seconds West 20.00 feet to a point; THENCE (3) South 20 degrees 00 minutes "
    "00 seconds East 30.00 feet to a point; THENCE (4) North 70 degrees 00 minutes 00 "
    "seconds East 20.00 feet to the point and place of BEGINNING."
)
INTRO = (
    "ALL THAT CERTAIN lot, piece or parcel of land, with the buildings and improvements "
    "thereon erected, situate, lying and being in the Borough of Haddonfield, County of "
    "Camden and State of New Jersey, bounded and described as follows:\n\n"
)
LOT = "ALL THAT CERTAIN lot known as Lot 5, Block 3 on the Plan of Smithfield, "
BOTH_TRACTS = ["deed_verified_tract1.csv", "deed_verified_tract2.csv"]

# --- A1: the role named after the heading's colon (or in its label) ---------------------
LABELLED = {
    "a1_colon_access_easement": f"PARCEL A: {INTRO}{SQ}\n\nPARCEL B: ACCESS EASEMENT\n{SQ2}",
    "a1_colon_exception_parcel": f"PARCEL A: {INTRO}{SQ}\n\nPARCEL B: EXCEPTION PARCEL\n{SQ2}",
    "a1_colon_parenthetical_easement": f"PARCEL A: {INTRO}{SQ}\n\nPARCEL B: (Easement Parcel) {SQ2}",
    "a1_colon_right_of_way_area": f"TRACT 1: {INTRO}{SQ}\n\nTRACT 2: Right of Way Area. {SQ2}",
    "a1_period_easement_for_ingress": (
        f"PARCEL A. {INTRO}{SQ}\n\nPARCEL B. Easement for ingress and egress. {SQ2}"
    ),
    "a1_newline_drainage_easement": f"PARCEL A\n{INTRO}{SQ}\n\nPARCEL B\nDRAINAGE EASEMENT\n{SQ2}",
    "a1_colon_easement_area": f"PARCEL A: {INTRO}{SQ}\n\nPARCEL B: EASEMENT AREA\n{SQ2}",
    "a1_parenthetical_ingress_and_egress": f"PARCEL A:\n{INTRO}{SQ}\n\nPARCEL B (Ingress and Egress):\n{SQ2}",
    "a1_dash_access_area": f"PARCEL A: {INTRO}{SQ}\n\nPARCEL B - ACCESS AREA: {SQ2}",
    "a1_parenthetical_excluded_area": f"PARCEL A: {INTRO}{SQ}\n\nPARCEL B (Excluded Area): {SQ2}",
    "a1_parenthetical_driveway_rights": (
        f"PARCEL A: {INTRO}{SQ}\n\nPARCEL B (Appurtenant Driveway Rights): {SQ2}"
    ),
    "a1_parenthetical_conveyed_out": f"PARCEL A: {INTRO}{SQ}\n\nPARCEL B (Conveyed Out): {SQ2}",
    "a1_parenthetical_deducted": (
        f"PARCEL A: {INTRO}{SQ}\n\nPARCEL B (to be deducted from Parcel A): {SQ2}"
    ),
    "a1_parenthetical_less_out": f"PARCEL A: {INTRO}{SQ}\n\nPARCEL B (LESS-OUT): {SQ2}",
    "a1_colon_being_portion_excepted": (
        f"PARCEL 1: {INTRO}{SQ}\n\nPARCEL 2: Being the portion excepted from Parcel 1, "
        f"described as follows: {SQ2}"
    ),
}
# --- A2: role wording the round-58 grammar missed, before or after the description ------
WORDED = {
    "a2_easement_area_described": (
        f"PARCEL A: {INTRO}{SQ}\n\nPARCEL B: The non-exclusive easement area described as "
        f"follows: {SQ2}"
    ),
    "a2_right_of_ingress_over_following": (
        f"PARCEL A: {INTRO}{SQ}\n\nPARCEL B: A perpetual right of ingress and egress over the "
        f"following: {SQ2}"
    ),
    "a2_excluding_therefrom_the_following": (
        f"PARCEL A: {INTRO}{SQ}\n\nEXCLUDING therefrom the following:\nPARCEL B: {SQ2}"
    ),
    "a2_grantor_reserves_following_land": (
        f"PARCEL A: {INTRO}{SQ}\n\nThe Grantor reserves unto itself the following described "
        f"land:\nPARCEL B: {SQ2}"
    ),
    "a2_saving_and_excluding_heading": f"PARCEL A: {INTRO}{SQ}\n\nSAVING AND EXCLUDING PARCEL B: {SQ2}",
    "a2_less_and_excluding_heading": f"PARCEL A: {INTRO}{SQ}\n\nLESS AND EXCLUDING PARCEL B: {SQ2}",
    "a2_role_statement_after_description": (
        f"PARCEL A: {INTRO}{SQ}\n\nPARCEL B: {SQ2}\n\nParcel B is a non-exclusive easement "
        "appurtenant to Parcel A for ingress and egress."
    ),
    "a2_exception_statement_after_description": (
        f"PARCEL 1: {INTRO}{SQ}\n\nPARCEL 2: {SQ2}\n\nEXCEPTING from Parcel 1 the land "
        "described as Parcel 2."
    ),
}
# --- A3: a parcel described by reference, then an EXCLUDING / SAVING lead ---------------
EXCLUDED = {
    "a3_excluding_following_described_parcel": (
        f"{LOT}EXCLUDING therefrom the following described parcel: {SQ2}"
    ),
    "a3_saving_following_described_parcel": f"{LOT}SAVING the following described parcel: {SQ2}",
    "a3_saving_and_excluding_following_parcel": (
        f"{LOT}SAVING AND EXCLUDING the following described parcel: {SQ2}"
    ),
}
# --- A4: one description that is an easement or right (single, allow-list) -------------
SINGLE_ROLE = {
    "a4_pipeline_right": (
        "Grantor hereby grants unto Grantee, its successors and assigns, the perpetual right to "
        "construct, maintain and operate a pipeline over, through and across the following "
        f"described land: {SQ2}"
    ),
    "a4_right_of_ingress_and_egress": (
        "Grantor grants to Grantee a non-exclusive right of ingress and egress over the "
        f"following described strip of land: {SQ2}"
    ),
    "a4_sanitary_sewer_easement_area": (
        f"SANITARY SEWER EASEMENT\n\nThe Easement Area is described as follows:\n\n{SQ2}"
    ),
    "a4_heading_easement_area": f"PARCEL 1: EASEMENT AREA\n{SQ2}",
    "a4_temporary_construction_easement_title": f"TEMPORARY CONSTRUCTION EASEMENT AREA\n\n{SQ2}",
    "a4_easement_statement_after": f"{SQ2} The foregoing describes a 20 foot wide access easement.",
    "a4_easement_title_before_plain_heading": f"SANITARY SEWER EASEMENT\n\nPARCEL 1: {SQ2}",
}
# --- B2: a recital about the previous parcel, then a plain heading and full intro -------
HARMLESS_BETWEEN = {
    "b2_subject_to_right_of_way_westerly_10_feet": (
        f"PARCEL ONE: {INTRO}{SQ}\n\nSUBJECT to a right of way for ingress and egress along the "
        f"Westerly 10 feet thereof.\n\nPARCEL TWO: {INTRO}{SQ2}"
    ),
    "b2_together_with_easement_over_common_driveway": (
        f"PARCEL ONE: {INTRO}{SQ}\n\nTOGETHER with a non-exclusive easement for ingress and "
        "egress over the common driveway as shown on the filed plan.\n\n"
        f"PARCEL TWO: {INTRO}{SQ2}"
    ),
    "b2_together_with_right_to_use_driveway_easement": (
        f"PARCEL ONE: {INTRO}{SQ}\n\nTOGETHER with the right to use the 10 foot wide driveway "
        f"easement shown on the plan.\n\nPARCEL TWO: {INTRO}{SQ2}"
    ),
    "b2_reserving_easement_over_driveway": (
        f"PARCEL ONE: {INTRO}{SQ}\n\nRESERVING unto the Grantor, its successors and assigns, an "
        "easement for the maintenance of the existing sewer line, as shown on the plan.\n\n"
        f"PARCEL TWO: {INTRO}{SQ2}"
    ),
    "b2_plain_headings_with_schedule_title": (
        f"SCHEDULE C\nPARCEL ONE: {INTRO}{SQ}\n\nPARCEL TWO: {INTRO}{SQ2}"
    ),
}
# The same recital before a heading with no parcel intro: Parcel TWO might be the right
# of way it recites, so its role is inferred (fail closed).
SPECIFIC_RECITAL_BARE_HEADING = (
    f"PARCEL ONE: {INTRO}{SQ}\n\nTOGETHER with a non-exclusive easement for ingress and egress "
    f"over the common driveway as shown on the filed plan.\n\nPARCEL TWO: {SQ2}"
)
# --- ordinary single parcels (the reviewer's B and D lists that export on main) -------
SINGLE = {
    "plain": INTRO + SQ,
    "beginning_only": SQ,
    "subject_record_after": f"{INTRO}{SQ}\n\nSUBJECT to easements, restrictions and covenants of record.",
    "together_driveway_before": (
        "TOGETHER with the right of ingress and egress over the 10 foot wide driveway easement "
        f"as shown on the filed plan.\n\n{INTRO}{SQ}"
    ),
    "being_lot_before": (
        f"BEING Lot 5, Block 3 as shown on the Tax Map of the Borough of Haddonfield.\n\n{INTRO}{SQ}"
    ),
    "being_same_after": (
        f"{INTRO}{SQ}\n\nBEING the same premises conveyed to John Smith by deed of Mary Jones "
        "dated June 1, 1990 and recorded in Deed Book 1234 page 56."
    ),
    "survey_after": (
        f"{INTRO}{SQ}\n\nThe above description is in accordance with a survey made by Smith "
        "Engineering dated May 1, 2001."
    ),
    "schedule_a_heading": f"SCHEDULE A\nLEGAL DESCRIPTION\n\n{INTRO}{SQ}",
    "exhibit_parcel_id": f"EXHIBIT A\nParcel ID: 123-45\n\n{INTRO}{SQ}",
    "single_tract_heading": f"TRACT NO. 1\n{INTRO}{SQ}",
    "single_parcel_heading": f"PARCEL ONE: {INTRO}{SQ}",
    "subject_right_of_way_westerly_after": (
        f"{INTRO}{SQ}\n\nSUBJECT to a right of way for ingress and egress along the Westerly 10 "
        "feet of the above described premises."
    ),
    "together_benefit_easement_after": (
        f"{INTRO}{SQ}\n\nTOGETHER with the benefit of an easement for ingress and egress as set "
        "forth in Deed Book 100 page 5."
    ),
    "grantor_deed_form": (
        "This Deed is made on June 1, 2005, BETWEEN John Smith, called the Grantor, AND Jane "
        "Doe, called the Grantee. Transfer of Ownership. The Grantor grants and conveys "
        "(transfers ownership of) the property described below to the Grantee. Tax Map "
        "Reference. Municipality of Haddonfield Block 3 Lot 5. Property. The Property consists "
        "of the land and all the buildings and structures on the land in the Borough of "
        "Haddonfield, County of Camden and State of New Jersey. The legal description is:\n\n"
        f"{INTRO}{SQ}\n\nBEING known as 12 Main Street."
    ),
    "commitment": f"The land referred to in this Commitment is described as follows:\n\n{INTRO}{SQ}",
    "subject_utility_easement_after": (
        f"{INTRO}{SQ}\n\nSUBJECT to a utility easement in favor of Public Service Electric and "
        "Gas Company recorded in Deed Book 100 page 5."
    ),
    "together_with_improvements": (
        f"{INTRO}{SQ}\n\nTOGETHER with all and singular the buildings, improvements, ways, "
        "streets, alleys, driveways, passages, waters, water-courses, rights, liberties, "
        "privileges, hereditaments and appurtenances."
    ),
    "subject_drainage_easement_before": (
        f"SUBJECT to a 10 foot wide drainage easement as shown on the filed map.\n\n{INTRO}{SQ}"
    ),
    "subject_easement_inside_intro": (
        "ALL THAT CERTAIN lot, piece or parcel of land, SUBJECT to a sight triangle easement as "
        "shown on the plan, situate in the Borough of Haddonfield, bounded and described as "
        f"follows: {SQ}"
    ),
    "reserving_oil_gas_preamble": f"RESERVING unto the Grantor all oil, gas and mineral rights.\n\n{INTRO}{SQ}",
    "together_access_easement_and_subject_before": (
        "TOGETHER with a non-exclusive easement for ingress and egress over the common driveway "
        "as shown on the plan, and SUBJECT to easements of record.\n\n" + INTRO + SQ
    ),
    "heading_with_easement_benefit_after": (
        f"PARCEL A: {INTRO}{SQ}\n\nTOGETHER with the benefit of a non-exclusive easement for "
        "access over the adjoining lands as recorded in Deed Book 200 page 10."
    ),
    "lot_block_survey_before": (
        "Lot 5, Block 3, Tax Map of the Borough of Haddonfield, more particularly described in "
        "accordance with a survey by Smith Engineering dated May 1, 2001 as follows:\n\n" + SQ
    ),
    "premises_described": f"The premises hereby conveyed are described as follows: {SQ}",
    "also_known_as": f"{INTRO}{SQ}\n\nALSO known as Lot 5, Block 3 on the Tax Map.",
    "including_bed_of_street": (
        f"{INTRO}{SQ}\n\nINCLUDING the Grantor's right, title and interest in and to the bed of "
        "Main Street abutting the above described premises."
    ),
    "subject_rights_of_public_after": (
        f"{INTRO}{SQ}\n\nSUBJECT to the rights of the public in and to that portion of the "
        "premises lying within the bed of Main Street."
    ),
    "under_and_subject_after": f"{INTRO}{SQ}\n\nUNDER AND SUBJECT to the rights of the public in Main Street.",
    "subject_drainage_rear_after": (
        f"{INTRO}{SQ}\n\nSUBJECT to a 10 foot wide drainage easement along the rear line of the "
        "above described premises."
    ),
    "together_easement_described_in_book_after": (
        f"{INTRO}{SQ}\n\nTOGETHER with a non-exclusive easement for ingress and egress over the "
        "driveway located on the adjoining lot to the West, as more fully described in Deed "
        "Book 300 page 20."
    ),
    "commonly_known_after": (
        f"{INTRO}{SQ}\n\nCommonly known as 12 Main Street, Haddonfield, New Jersey 08033.\n\n"
        "FOR INFORMATIONAL PURPOSES ONLY: Being Lot 5, Block 3 on the Tax Map."
    ),
    "title_note_after": (
        f"{INTRO}{SQ}\n\nNOTE FOR INFORMATION: Being Lot 5 in Block 3 on the Tax Map of the "
        "Borough of Haddonfield. The policy does not insure the area or quantity of land."
    ),
    "together_and_subject_inside_intro": (
        "ALL THAT CERTAIN lot, TOGETHER WITH and SUBJECT TO a common driveway easement, situate "
        f"in the Borough of Haddonfield, bounded and described as follows: {SQ}"
    ),
    "survey_easement_word_inside_intro": (
        "ALL THAT CERTAIN lot, parcel or tract of land, situate in the Borough of Haddonfield, "
        "being more particularly described in accordance with a survey which shows a 5 foot "
        f"utility easement along the Easterly line, as follows: {SQ}"
    ),
    "reserving_sewer_easement_after": (
        f"{INTRO}{SQ}\n\nRESERVING unto the Grantor, its successors and assigns, an easement for "
        "the maintenance of the existing sewer line, as shown on the plan."
    ),
    "subject_right_of_way_in_favor_after": (
        f"{INTRO}{SQ}\n\nSUBJECT to a right of way in favor of the adjoining owner as described "
        "in Deed Book 100 page 5."
    ),
    "also_subject_sight_triangle_after": (
        f"{INTRO}{SQ}\n\nALSO SUBJECT to a sight triangle easement as shown on the filed map."
    ),
    # The rights-only agent's report: a standalone mineral reservation sentence before the
    # description read every course as an exception (no computable traverse).
    "mineral_reservation_sentence_before_intro": (
        f"EXCEPTING AND RESERVING all oil, gas and mineral rights.\n\n{INTRO}{SQ}"
    ),
    "mineral_reservation_sentence_before_beginning": (
        f"EXCEPTING AND RESERVING all oil, gas and mineral rights.\n\n{SQ}"
    ),
    "excepting_mineral_rights_sentence_before_beginning": (
        f"EXCEPTING all oil, gas and mineral rights. {SQ}"
    ),
    "mineral_reservation_unto_grantor_before_beginning": (
        f"EXCEPTING AND RESERVING unto the Grantor all oil, gas and mineral rights.\n\n{SQ}"
    ),
}


def _extract(text: str):
    return extract_calls(text, strict=False, skipped_courses=[])


def _export(text: str, directory: Path) -> tuple[list[str], str]:
    calls, tracts = _extract(text)
    directory.mkdir()
    try:
        if tracts:
            results = verify_closure(calls, tracts=tracts)
            written = export_verified_csv(
                calls,
                results[0],
                str(directory / "deed.csv"),
                legal_desc=LegalDescription(calls=calls, tracts=tracts),
                tract_results=list(zip(tracts, results, strict=True)),
            )
        else:
            written = export_verified_csv(calls, verify_closure(calls), str(directory / "deed.csv"))
    except ValueError as error:
        assert list(directory.iterdir()) == []
        return [], str(error)
    return [p.name for p in written if p.suffix == ".csv"], ""


# --- A1/A2: a heading with role wording, or a role stated about it, is inferred ---------


@pytest.mark.parametrize("name", [*LABELLED, *WORDED])
def test_headed_role_wording_is_inferred_and_blocks_the_deed(name: str, tmp_path: Path) -> None:
    text = {**LABELLED, **WORDED}[name]
    calls, tracts = _extract(text)
    assert len(tracts) == 2
    first, second = tracts
    assert (first.tract_type, first.role_basis) == (TractType.MAIN, "heading")
    assert second.role_basis == "inferred"
    assert roles_need_review(tracts)
    results = verify_closure(calls, tracts=tracts)
    assert not any(r.is_fully_verified() for r in results)
    # Geometry is still computed for review.
    assert all(r.closure_passed for r in results)
    written, refusal = _export(text, tmp_path / "out")
    assert written == [] and DESCRIPTION_ROLES_PREFIX in refusal


@pytest.mark.parametrize(
    "name",
    [
        "a2_excluding_therefrom_the_following",
        "a2_saving_and_excluding_heading",
        "a2_less_and_excluding_heading",
    ],
)
def test_excluding_and_saving_leads_type_the_heading_an_exception(name: str) -> None:
    _, tracts = _extract(WORDED[name])
    assert [(t.tract_type, t.role_basis) for t in tracts] == [
        (TractType.MAIN, "heading"),
        (TractType.EXCEPTION, "inferred"),
    ]


# --- A3: EXCLUDING / SAVING leads introduce the only traverse ---------------------------


@pytest.mark.parametrize("name", list(EXCLUDED))
def test_excluded_or_saved_parcel_is_an_exception(name: str, tmp_path: Path) -> None:
    calls, tracts = extract_calls(EXCLUDED[name], strict=True)
    assert [(t.tract_type, t.role_basis, len(t.calls)) for t in tracts] == [
        (TractType.EXCEPTION, "inferred", 4)
    ]
    assert all(c.is_exception for c in calls)
    assert not verify_closure(calls, tracts=tracts)[0].is_fully_verified()
    written, refusal = _export(EXCLUDED[name], tmp_path / "out")
    assert written == [] and DESCRIPTION_ROLES_PREFIX in refusal
    assert not [c for c in CallExtractor.extract_calls(EXCLUDED[name]) if not c.is_exception]


# --- A4: a single description whose role is not established is never exported -----------


@pytest.mark.parametrize("name", list(SINGLE_ROLE))
def test_single_description_with_role_wording_is_inferred(name: str, tmp_path: Path) -> None:
    text = SINGLE_ROLE[name]
    calls, tracts = extract_calls(text, strict=True)
    assert [(t.tract_type, t.role_basis, len(t.calls)) for t in tracts] == [
        (TractType.MAIN, "inferred", 4)
    ]
    reasons = roles_need_review(tracts)
    assert reasons and "sole description" in reasons[0]
    # Every call carries the role-review mark, so no subset verifies or exports.
    assert calls and all(DESCRIPTION_ROLES_NOTE in split_notes(c.notes) for c in calls)
    for result in (verify_closure(calls), verify_closure(calls, tracts=tracts)[0]):
        assert not result.is_fully_verified()
        assert result.closure_passed
        assert any(
            c.name == DESCRIPTION_ROLES_CHECK and c.status == "blocked" for c in result.checks
        )
    assert not verify_tract(tracts[0].calls).is_fully_verified()
    written, refusal = _export(text, tmp_path / "out")
    assert written == [] and DESCRIPTION_ROLES_PREFIX in refusal
    review = review_text(text, output_dir=tmp_path / "review")
    assert review["status"] == "needs_review"
    assert "description_roles_inferred" in [e["code"] for e in review["errors"]]
    assert not (tmp_path / "review" / "calls_verified.csv").exists()
    legacy = CallExtractor.extract_calls(text)
    assert legacy and all(DESCRIPTION_ROLES_NOTE in split_notes(c.notes) for c in legacy)
    assert not ClosureChecker.verify_closure(legacy).is_fully_verified()


# --- B2: a recital about the previous parcel before a plain heading is harmless ----------


@pytest.mark.parametrize("name", list(HARMLESS_BETWEEN))
def test_recital_between_plain_headings_keeps_both_parcels(name: str, tmp_path: Path) -> None:
    calls, tracts = extract_calls(HARMLESS_BETWEEN[name], strict=True)
    assert [(t.tract_type, t.role_basis, len(t.calls)) for t in tracts] == [
        (TractType.MAIN, "heading", 4)
    ] * 2
    assert all(r.is_fully_verified() for r in verify_closure(calls, tracts=tracts))
    assert _export(HARMLESS_BETWEEN[name], tmp_path / "out") == (BOTH_TRACTS, "")


def test_specific_recital_before_a_bare_heading_is_inferred() -> None:
    _, tracts = extract_calls(SPECIFIC_RECITAL_BARE_HEADING, strict=True)
    assert [(t.tract_type, t.role_basis) for t in tracts] == [
        (TractType.MAIN, "heading"),
        (TractType.MAIN, "inferred"),
    ]


# --- ordinary single parcels stay single and verified -----------------------------------


@pytest.mark.parametrize("name", list(SINGLE))
def test_ordinary_single_parcel_stays_single_and_exported(name: str, tmp_path: Path) -> None:
    text = SINGLE[name]
    # Non-strict: strict extraction refuses a course-free ALSO / INCLUDING clause split
    # off as a tract of its own ("ALSO known as Lot 5"), as before round 59.
    calls, tracts = _extract(text)
    assert [(t.tract_type, t.role_basis) for t in tracts] in ([], [(TractType.MAIN, "single")])
    assert not any(c.is_exception for c in calls)
    assert not any(DESCRIPTION_ROLES_NOTE in split_notes(c.notes) for c in calls)
    assert [c.distance_ft for c in calls] == ([100.0, 50.0] * 2 if SQ in text else [30.0, 20.0] * 2)
    assert verify_closure(calls).is_fully_verified()
    written, refusal = _export(text, tmp_path / "out")
    assert len(written) == 1, refusal
    legacy = CallExtractor.extract_calls(text, strict=False, skipped_courses=[])
    assert ClosureChecker.verify_closure(legacy).is_fully_verified()


def test_review_text_passes_an_ordinary_single_parcel(tmp_path: Path) -> None:
    for i, name in enumerate(("plain", "mineral_reservation_sentence_before_beginning")):
        result = review_text(SINGLE[name], output_dir=tmp_path / str(i))
        assert result["status"] == "checks_passed", name
        assert (tmp_path / str(i) / "calls_verified.csv").exists()


@pytest.mark.parametrize(
    "lead",
    [
        "LESS AND EXCEPT any portion thereof conveyed to the State of New Jersey for highway "
        "purposes.",
        "EXCEPTING the westerly 10 feet thereof.",
    ],
)
def test_lone_land_exception_before_the_description_stays_fail_closed(
    lead: str, tmp_path: Path
) -> None:
    # Only a rights recital opening the text is the description's preamble; a lead
    # taking land keeps blocking the parcel as before (every course an exception, or the
    # strip noted as an unapplied exception), so nothing exports.
    calls, tracts = _extract(f"{lead}\n\n{SQ}")
    assert tracts == [] and len(calls) == 4
    assert not verify_closure(calls).is_fully_verified()
    assert _export(f"{lead}\n\n{SQ}", tmp_path / "out")[0] == []


# --- property 1: no path verifies or exports easement, exception or reserved land -------

# Every reviewer probe whose text describes easement, exception, excluded or reserved
# land by courses (A1-A4).
NON_PARCEL_LAND = {**LABELLED, **WORDED, **EXCLUDED, **SINGLE_ROLE}


def _monolith_tracts(text: str) -> tuple[list[monolith.DeedCall], list[monolith.Tract]]:
    tracts: list[monolith.Tract] = []
    calls = CallExtractor.extract_calls(text, strict=False, skipped_courses=[], tracts=tracts)
    return calls, tracts


def deed_paths_accepting(text: str, directory: Path, *, subsets: bool = True) -> list[str]:
    """Every verification/export path that accepts any of the deed's land (none may).

    The package with and without tracts (the flat calls and each tract's calls alone),
    text review, and the monolith facades; with ``subsets`` also every call subset, JSON
    and CSV round trip and forged result r58's property test takes.
    """
    accepted: list[str] = []
    calls, tracts = _extract(text)
    results = verify_closure(calls, tracts=tracts) if tracts else [verify_closure(calls)]
    if any(r.is_fully_verified() for r in results):
        accepted.append("verify_closure(tracts=)")
    for tract in tracts:
        if verify_tract(tract.calls, tract=tract).is_fully_verified():
            accepted.append(f"verify_tract({tract.label}, tract=)")
    written, _ = _export(text, directory / "export")
    if written:
        accepted.append(f"export_verified_csv {written}")
    for i, (label, alone) in enumerate([("flat", calls), *((t.label, t.calls) for t in tracts)]):
        if not alone:
            continue
        result = verify_closure(alone)
        if result.is_fully_verified():
            accepted.append(f"verify_closure({label})")
        try:
            export_verified_csv(alone, result, str(directory / f"alone{i}.csv"))
            accepted.append(f"export_verified_csv({label})")
        except ValueError:
            pass
    review = review_text(text, output_dir=directory / "review")
    if (
        review["status"] == "checks_passed"
        or (directory / "review" / "calls_verified.csv").exists()
    ):
        accepted.append("review_text")
    default = CallExtractor.extract_calls(text, strict=False, skipped_courses=[])
    if default:
        checked_default = ClosureChecker.verify_closure(default)
        if checked_default.is_fully_verified():
            accepted.append("ClosureChecker.verify_closure(CallExtractor default)")
        try:
            CSVBuilder.export_verified_csv(
                default, checked_default, str(directory / "legacy_default.csv")
            )
            accepted.append("CSVBuilder.export_verified_csv(CallExtractor default)")
        except ValueError:
            pass
    legacy, legacy_tracts = _monolith_tracts(text)
    if legacy_tracts:
        checked = ClosureChecker.verify_closure([], tracts=legacy_tracts)
        if any(r.is_fully_verified() for r in checked):
            accepted.append("ClosureChecker.verify_closure(tracts=)")
        try:
            CSVBuilder.export_verified_csv(
                [],
                checked[0],
                str(directory / "legacy.csv"),
                tract_results=list(zip(legacy_tracts, checked, strict=True)),
            )
            accepted.append("CSVBuilder.export_verified_csv(tract_results=)")
        except ValueError:
            pass
    if any(directory.glob("**/*verified*.csv")):
        accepted.append("files written")
    if not subsets:
        return accepted
    # Every call subset a caller can take (flat, per tract, monolith, JSON and CSV round
    # trips, forged results): r58's property paths.
    for label, subset in _subsets(text):
        for representation, subset_calls in (
            (label, subset),
            (f"{label} via CSV", _csv_round_trip(subset, directory)),
        ):
            paths = _verified_or_exported(subset_calls, directory)
            accepted += [f"{representation}: {path}" for path in paths]
    return accepted


@pytest.mark.parametrize("name", sorted(NON_PARCEL_LAND))
def test_no_path_verifies_easement_or_exception_land(name: str, tmp_path: Path) -> None:
    assert deed_paths_accepting(NON_PARCEL_LAND[name], tmp_path) == []


def _load_corpus() -> ModuleType:
    path = ROOT / "packages" / "mp-parse" / "tests" / "test_tract_classification_corpus.py"
    spec = importlib.util.spec_from_file_location("_r59_tract_corpus", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered first: its dataclasses resolve their module while it executes.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_CORPUS = _load_corpus()
_NON_BOUNDARY = {TractType.EXCEPTION, TractType.EASEMENT}
# Every corpus deed describing easement, exception, excluded or reserved land: a typed
# EXCEPTION/EASEMENT tract, a lead introducing the only traverse, an exception described
# first, or (r59) a description whose wording names its role.
CORPUS_NON_PARCEL_LAND = {
    **{
        f"case:{name}": case.text
        for name, case in _CORPUS.CASES.items()
        if case.error is None
        and (
            any(kind in _NON_BOUNDARY for kind, _ in case.tracts)
            or name in _CORPUS.R59_NON_PARCEL_LAND
        )
    },
    **{f"introduced:{name}": text for name, (text, _) in _CORPUS.INTRODUCED.items()},
    **{f"first:{name}": text for name, (text, _) in _CORPUS.R56_EXCEPTION_FIRST.items()},
}


@pytest.mark.parametrize("name", sorted(CORPUS_NON_PARCEL_LAND))
def test_no_path_verifies_corpus_easement_or_exception_land(name: str, tmp_path: Path) -> None:
    assert deed_paths_accepting(CORPUS_NON_PARCEL_LAND[name], tmp_path, subsets=False) == []


# --- property 2: harmless recitals never cost a plain parcel its export ------------------

# Recitals that grant, except or reserve no described land.
HARMLESS_RECITALS = (
    "SUBJECT to easements and restrictions of record.",
    "TOGETHER WITH all improvements and appurtenances thereto.",
    "BEING the same premises conveyed to John Smith by deed recorded in Deed Book 1234 page 56.",
    "Commonly known as 12 Main Street.",
    "UNDER AND SUBJECT to the rights of the public in and to Main Street.",
    "TOGETHER with all easements and rights of way appurtenant thereto.",
)
# Rights-only reservations: they reserve or except rights, never described land.
RIGHTS_RESERVATIONS = (
    "EXCEPTING AND RESERVING all oil, gas and mineral rights.",
    "EXCEPTING AND RESERVING unto the Grantor all oil, gas and mineral rights.",
    "RESERVING unto the Grantor the coal and mining rights.",
    "EXCEPT the rights of the public in and to Main Street.",
    "EXCEPTING therefrom the rights of the public in Main Street.",
)
# Plainly headed deeds and plain single parcels (each exports every parcel unchanged).
PLAIN_DEEDS = {
    **{f"single_{name}": text for name, text in SINGLE.items()},
    **HARMLESS_BETWEEN,
    "headed_plain": f"PARCEL ONE: {INTRO}{SQ}\n\nPARCEL TWO: {INTRO}{SQ2}",
    "headed_bare": f"PARCEL ONE: {SQ}\n\nPARCEL TWO: {SQ2}",
    "tract_headed_bare": f"TRACT 1: {SQ} TRACT 2: {SQ2}",
}


def _second_heading(text: str) -> int | None:
    markers = find_tract_markers(text)
    return markers[1][0] if len(markers) > 1 else None


def _prepend(text: str, recital: str) -> str | None:
    return f"{recital}\n\n{text}"


def _append(text: str, recital: str) -> str | None:
    return f"{text}\n\n{recital}"


def _between(text: str, recital: str) -> str | None:
    position = _second_heading(text)
    if position is None:
        return None
    return f"{text[:position].rstrip()}\n\n{recital}\n\n{text[position:]}"


POSITIONS: dict[str, Callable[[str, str], str | None]] = {
    "prepended": _prepend,
    "between": _between,
    "appended": _append,
}


def _deed_outcome(text: str, directory: Path) -> tuple:
    skips: list = []
    calls, tracts = extract_calls(text, strict=False, skipped_courses=skips)
    if skips:
        return ("skipped", [s.course for s in skips])
    results = verify_closure(calls, tracts=tracts) if tracts else [verify_closure(calls)]
    return (
        [(t.label, t.tract_type, t.role_basis, len(t.calls)) for t in tracts],
        [(c.bearing_azimuth_deg_from_north, c.distance_ft, c.is_exception) for c in calls],
        [r.is_fully_verified() for r in results],
        _export(text, directory)[0],
    )


_PLAIN_OUTCOMES: dict[str, tuple] = {}


def _comparable(outcome: tuple) -> tuple:
    """A lone MAIN tract with the 'single' basis is the same parcel as a flat one.

    A noted recital can route a single description through the tract path; only the
    verified CSV's file name changes (``_tract1``), not the calls or the outcome.
    """
    if len(outcome) != 4:
        return outcome
    tracts, calls, verified, exported = outcome
    if len(tracts) == 1 and tracts[0][1] == TractType.MAIN and tracts[0][2] == "single":
        tracts = []
        exported = [name.replace("_tract1", "") for name in exported]
    return (tracts, calls, verified, exported)


def _recital_params() -> list:
    params = []
    for position in POSITIONS:
        for recital in (*HARMLESS_RECITALS, *RIGHTS_RESERVATIONS):
            params.append(pytest.param(position, recital, id=f"{position}-{recital}"))
    return params


# Corpus deeds with one description or headed MAIN/ADDITION parcels only; those whose
# every parcel verifies and exports are the plain ones (others are skipped).
CORPUS_CANDIDATES = {
    f"case:{name}": case.text
    for name, case in _CORPUS.CASES.items()
    if case.error is None
    and name not in _CORPUS.EASEMENT_DEED_CASES
    and not any(kind in _NON_BOUNDARY for kind, _ in case.tracts)
    and (not case.tracts or find_tract_markers(case.text))
}


@pytest.mark.parametrize(("position", "recital"), _recital_params())
def test_harmless_recital_keeps_every_plain_parcel_exported(
    position: str, recital: str, tmp_path: Path
) -> None:
    failures: dict[str, tuple] = {}
    for i, (name, text) in enumerate({**PLAIN_DEEDS, **CORPUS_CANDIDATES}.items()):
        if name not in _PLAIN_OUTCOMES:
            _PLAIN_OUTCOMES[name] = _deed_outcome(text, tmp_path / f"plain{i}")
        expected = _PLAIN_OUTCOMES[name]
        plain = (
            len(expected) == 4
            and bool(expected[3])
            and all(expected[2])
            and len(expected[3]) == len(expected[2])
        )
        if name in PLAIN_DEEDS:
            assert plain, name
        elif not plain:
            continue
        changed = POSITIONS[position](text, recital)
        if changed is None:
            continue
        got = _deed_outcome(changed, tmp_path / f"r{i}")
        if _comparable(got) != _comparable(expected):
            failures[name] = got
    assert failures == {}
