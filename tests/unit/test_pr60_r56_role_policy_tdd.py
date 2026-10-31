"""PR #60 round 56: fail closed on inferred description roles (user decision).

When a deed has more than one description and any description's role (main,
addition, exception, easement) was inferred from wording rather than an explicit
TRACT/PARCEL heading, nothing in the deed is verified or exported, through any path:
``mp_verify.verify_closure`` (and the monolith facade), ``export_verified_csv`` (and
the facade), the ``review_text`` API and the monolith Pipeline. A single description
is unaffected, and a deed whose every role comes from a heading still exports its
verified MAIN/ADDITION tracts. The round-55 reviewer probes are replayed here.

Round 57 (the round-56 reviewer probes) tightens the bases: a description introduced
by its own EXCEPT/RESERVING/LESS or easement-grant lead is never the parcel; a heading
with role wording in it or before its BEGINNING is "inferred"; a one-course easement
clause is noted, never a tract; a tie line after the closure is no separate description.
"""

from __future__ import annotations

from pathlib import Path

import mp_models
import pytest
from mp_export import export_verified_csv
from mp_models import (
    DESCRIPTION_ROLES_CHECK,
    DESCRIPTION_ROLES_PREFIX,
    LegalDescription,
    Tract,
    TractType,
    roles_need_review,
)
from mp_parse.calls import extract_calls
from mp_review.api import review_text
from mp_verify import verify_closure, verify_tract

from metesparser import models as monolith
from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker
from metesparser.csv_builder import CSVBuilder


def _square(
    side: float, start: str = "BEGINNING at a pin", close: str = "to the point of beginning"
) -> str:
    return (
        f"{start}; thence N 0° E {side} feet to a pin; thence S 90° E {side} feet to a pin; "
        f"thence S 0° W {side} feet to a pin; thence N 90° W {side} feet {close}."
    )


P = _square(100)
E = _square(10, "BEGINNING at a stake")
E2 = _square(20, "BEGINNING at an iron")
TIE = (
    "COMMENCING at the intersection of Main Street and Elm Avenue; "
    "thence N 0° E 50 feet to the TRUE POINT OF BEGINNING; "
)
EXCEPT_AFTER = "EXCEPTING THEREFROM the following described parcel:"
EASEMENT_AFTER = (
    "TOGETHER WITH an easement for ingress and egress over the following described land:"
)
CLOSINGS = (
    "to the place of beginning",
    "to the point and place of beginning",
    "to the point or place of BEGINNING",
    "to the beginning",
    "to the first mentioned point",
    "to the place of BEGINNING, containing 0.23 acres",
)
LEADS = (
    "EXCEPTING from the following described land the parcel described as follows:",
    "EXCEPTING from the lands hereinafter more particularly described the following:",
    "SAVE AND EXCEPT out of the premises hereinafter described the following parcel:",
    "EXCEPTING from the lands described below the following:",
    "LESS AND EXCEPT from the tract hereinafter described the following:",
)
RECITALS = (
    "EXCEPTING AND RESERVING the oil and gas rights,",
    "excepting the portion within Main Street,",
    "SUBJECT to a 10 foot wide utility easement along the rear line,",
    "SUBJECT to easements of record,",
    "TOGETHER WITH the right of way over the driveway in common with others,",
)
MINERAL = (
    "EXCEPTING AND RESERVING from the premises hereinafter described all oil, gas and minerals,"
)

# The round-55 reviewer probes (one per synthetic deed form).
PROBES: dict[str, str] = {}
for i, closing in enumerate(CLOSINGS):
    PROBES[f"close{i}_exception_after"] = (
        f"ALL THAT lot: {_square(100, close=closing)} {EXCEPT_AFTER} {E}"
    )
    PROBES[f"close{i}_easement_after"] = (
        f"ALL THAT lot: {_square(100, close=closing)} {EASEMENT_AFTER} {E}"
    )
    PROBES[f"close{i}_two_headed_parcels"] = (
        f"PARCEL ONE: {_square(100, close=closing)} PARCEL TWO: {E2}"
    )
_TIED = _square(100, start="thence", close="to the true point of beginning").replace("thence; ", "")
PROBES["tie_exception_after"] = f"{TIE}{_TIED} {EXCEPT_AFTER} {E}"
PROBES["tie_easement_after"] = f"{TIE}{_TIED} {EASEMENT_AFTER} {E}"
PROBES["starting_exception_after"] = f"{_square(100, start='Starting at a pin')} {EXCEPT_AFTER} {E}"
PROBES["running_exception_after"] = (
    "BEGINNING at a pin and running N 0° E 100 feet, S 90° E 100 feet, S 0° W 100 feet and "
    f"N 90° W 100 feet to the point of beginning. {EXCEPT_AFTER} {E}"
)
PROBES["easement_with_courses_before_parcel"] = (
    f"SUBJECT to a drainage easement more particularly described as follows: {E} "
    f"ALL THAT tract of land described as follows: {P}"
)
PROBES["exception_before_parcel"] = (
    f"EXCEPTING the following described parcel: {E} ALL THAT tract of land described as follows: {P}"
)
for i, lead in enumerate(LEADS):
    PROBES[f"exception_first_lead{i}"] = (
        f"{lead} {E} The said lands being described as follows: {P}"
    )
PROBES["plain"] = P
PROBES["plain_exception_after"] = f"{P} {EXCEPT_AFTER} {E}"
PROBES["plain_easement_after"] = f"{P} {EASEMENT_AFTER} {E}"
PROBES["plain_also"] = f"{P} ALSO all that tract described as follows: {E2}"
for i, recital in enumerate(RECITALS):
    PROBES[f"second_parcel{i}_headed"] = (
        f"PARCEL ONE: {P} PARCEL TWO: ALL THAT tract, {recital} {E2}"
    )
    PROBES[f"second_parcel{i}_also"] = f"{P} ALSO all that tract of land, {recital} {E2}"
    PROBES[f"second_parcel{i}_paragraph"] = (
        f"{P}\n\nALL THAT other tract of land, {recital} bounded and described as follows: {E2}"
    )
PROBES["mineral_single_parcel"] = (
    f"ALL THAT tract of land, {MINERAL} bounded and described as follows: {P}"
)
PROBES["mineral_single_parcel_running_on"] = f"ALL THAT tract of land, {MINERAL} {P}"
PROBES["creek_bed_single_parcel"] = (
    "ALL THAT tract of land, excepting from the land described below the bed of Cooper Creek, "
    f"bounded and described as follows: {P}"
)
PROBES["mineral_parcel_then_exception"] = (
    f"ALL THAT tract of land, {MINERAL} bounded and described as follows: {P} {EXCEPT_AFTER} {E}"
)

# The round-56 reviewer probes (PR #60 round 57).
LOT_REFERENCE = "ALL THAT CERTAIN lot known as Lot 5, Block 3 on the Plan of Smithfield."
# Item 1: a description introduced by its lead's own clause is not the parcel.
INTRODUCED = {
    "r57_lot_then_excepted_parcel_a": (
        f"{LOT_REFERENCE} EXCEPTING THEREFROM the following described parcel: PARCEL A: {E}"
    ),
    "r57_lot_then_less_and_except": (
        f"{LOT_REFERENCE} LESS AND EXCEPT that part described as follows: {E}"
    ),
    "r57_lot_then_excepting_therefrom_colon": f"{LOT_REFERENCE} EXCEPTING THEREFROM:\n\n{E}",
    "r57_lot_then_excepting_and_reserving": (
        f"{LOT_REFERENCE} EXCEPTING AND RESERVING the following described tract: {E}"
    ),
    "r57_lot_then_easement_strip": (
        f"{LOT_REFERENCE} TOGETHER WITH a perpetual easement for ingress and egress over the "
        f"following described strip: {E}"
    ),
}
PROBES.update(INTRODUCED)
PROBES["r57_recital_inside_parcel_sentence"] = (
    "ALL THAT CERTAIN lot, SUBJECT to easements as shown on the plan, bounded and described "
    f"as follows: {P}"
)
# Item 2: a heading proves a description exists, not its role.
WORDED_HEADINGS = {
    "r57_tract_2_easement": (
        f"TRACT 1: {P} TRACT 2: A non-exclusive easement for ingress and egress described as "
        f"follows: {E}"
    ),
    "r57_parcel_b_access_easement": f"PARCEL A: {P} PARCEL B (ACCESS EASEMENT): {E}",
    "r57_less_parcel_b": f"PARCEL A: {P} LESS PARCEL B: {E}",
    "r57_reserving_parcel_b": (
        f"PARCEL A: {P} RESERVING unto the Grantor the following: PARCEL B: {E}"
    ),
    "r57_parcel_a_subject_to_parcel_b": (
        f"PARCEL A: {P} Said Parcel A is subject to the following easement: PARCEL B: {E}"
    ),
}
PROBES.update(WORDED_HEADINGS)
# Item 3: a one-course easement clause is noted, never a tract blocking the parcel.
SEWER = (
    "SUBJECT TO a sewer easement which begins at the northeast corner of said lot and runs "
    "thence South 10 feet."
)
UTILITY = (
    "SUBJECT TO a 10 foot wide utility easement over the rear of said lot, which easement "
    "begins at the Northeast corner thereof and runs thence South 10 feet."
)
PROBES["r57_headed_parcels_then_sewer_clause"] = f"PARCEL ONE: {P} PARCEL TWO: {E2} {SEWER}"
PROBES["r57_parcel_then_utility_clause"] = (
    f"ALL THAT CERTAIN lot, EXCEPTING the mineral rights, bounded and described as follows: "
    f"{P} {UTILITY}"
)
# Item 4: a tie line after the closure is no separate description.
PROBES["r57_mineral_parcel_then_tie_line"] = (
    f"ALL THAT tract, {MINERAL} bounded and described as follows: {P} The said point of "
    "beginning being located from the monument at Main Street as follows: thence N 10° E "
    "50 feet."
)

BOTH_TRACTS = ["deed_verified_tract1.csv", "deed_verified_tract2.csv"]
# Only these probes export: one description, or every role from a heading with no role
# wording (r57: the second_parcel*_headed probes recite a reservation or an easement
# before PARCEL TWO's BEGINNING, so its heading no longer establishes its role).
EXPORTS = {
    **{f"close{i}_two_headed_parcels": BOTH_TRACTS for i in range(len(CLOSINGS))},
    "plain": ["deed_verified.csv"],
    "mineral_single_parcel": ["deed_verified.csv"],
    "mineral_single_parcel_running_on": ["deed_verified.csv"],
    "creek_bed_single_parcel": ["deed_verified.csv"],
    "r57_recital_inside_parcel_sentence": ["deed_verified.csv"],
    "r57_headed_parcels_then_sewer_clause": BOTH_TRACTS,
    "r57_parcel_then_utility_clause": ["deed_verified.csv"],
}


def _export(text: str, directory: Path) -> tuple[list[str], str]:
    calls, tracts = extract_calls(text, strict=False, skipped_courses=[])
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
    return [p.name for p in written], ""


@pytest.mark.parametrize("name", list(PROBES))
def test_probe_exports_only_single_or_headed_descriptions(name: str, tmp_path: Path) -> None:
    calls, tracts = extract_calls(PROBES[name], strict=False, skipped_courses=[])
    written, refusal = _export(PROBES[name], tmp_path / "out")
    assert written == EXPORTS.get(name, []), refusal
    if roles_need_review(tracts):
        assert DESCRIPTION_ROLES_PREFIX in refusal
        for result in verify_closure(calls, tracts=tracts):
            assert any(
                c.name == DESCRIPTION_ROLES_CHECK and c.status == "blocked" for c in result.checks
            )
            assert not result.is_fully_verified()


@pytest.mark.parametrize(
    "name",
    [
        "mineral_single_parcel",
        "mineral_single_parcel_running_on",
        "creek_bed_single_parcel",
        "r57_recital_inside_parcel_sentence",
    ],
)
def test_reservation_in_single_parcel_is_one_main_parcel(name: str) -> None:
    calls, tracts = extract_calls(PROBES[name], strict=True)
    assert tracts == []
    assert [(c.distance_ft, c.is_exception) for c in calls] == [(100.0, False)] * 4
    assert verify_closure(calls).is_fully_verified()


def test_second_fee_parcel_with_mineral_reservation_is_never_exported() -> None:
    # r57: the reservation recited before PARCEL TWO's BEGINNING is role wording, so its
    # heading does not establish its role; the deed is blocked, headed or not.
    _, headed = extract_calls(PROBES["second_parcel0_headed"], strict=True)
    assert [(t.tract_type, t.role_basis) for t in headed] == [
        (TractType.MAIN, "heading"),
        (TractType.MAIN, "inferred"),
    ]
    assert not any(r.is_fully_verified() for r in verify_closure([], tracts=headed))
    # Unheaded, the reservation types the second parcel EXCEPTION (a wrong guess): the
    # policy blocks the deed rather than exporting the first parcel alone.
    _, unheaded = extract_calls(PROBES["second_parcel0_also"], strict=True)
    assert [(t.tract_type, t.role_basis) for t in unheaded] == [
        (TractType.MAIN, "inferred"),
        (TractType.EXCEPTION, "inferred"),
    ]
    assert not any(r.is_fully_verified() for r in verify_closure([], tracts=unheaded))


# --- r57: the round-56 reviewer probes ------------------------------------------------


@pytest.mark.parametrize("name", list(INTRODUCED))
def test_description_introduced_by_its_lead_is_not_the_parcel(name: str, tmp_path: Path) -> None:
    # The parcel is described by reference only; its one traverse is the exception or
    # easement its lead introduces. No tract is MAIN, every role is inferred (never
    # "single"), and nothing is verified or exported on any path. (Strict extraction
    # fails on the reference-only parcel, which has no computable calls.)
    skips: list = []
    calls, tracts = extract_calls(PROBES[name], strict=False, skipped_courses=skips)
    assert skips == [] and len(tracts) == 1
    assert tracts[0].tract_type in (TractType.EXCEPTION, TractType.EASEMENT)
    assert tracts[0].role_basis == "inferred" and roles_need_review(tracts)
    assert len(tracts[0].calls) == 4 and not [c for c in calls if not c.is_exception]
    assert not verify_closure(calls, tracts=tracts)[0].is_fully_verified()
    result = review_text(PROBES[name], output_dir=tmp_path / "review")
    assert result["status"] != "checks_passed"
    assert not (tmp_path / "review" / "calls_verified.csv").exists()


@pytest.mark.parametrize("name", list(WORDED_HEADINGS))
def test_heading_with_role_wording_is_inferred(name: str) -> None:
    calls, tracts = extract_calls(PROBES[name], strict=True)
    assert [t.role_basis for t in tracts] == ["heading", "inferred"]
    assert tracts[0].tract_type == TractType.MAIN
    results = verify_closure(calls, tracts=tracts)
    assert not any(r.is_fully_verified() for r in results)
    assert all(r.closure_passed for r in results)


@pytest.mark.parametrize(
    ("name", "clause"),
    [
        ("r57_headed_parcels_then_sewer_clause", SEWER),
        ("r57_parcel_then_utility_clause", UTILITY),
    ],
)
def test_one_course_easement_clause_is_noted_not_a_tract(name: str, clause: str) -> None:
    calls, tracts = extract_calls(PROBES[name], strict=True)
    assert TractType.EASEMENT not in [t.tract_type for t in tracts]
    assert [c.distance_ft for c in calls if c.distance_ft != 100.0] in ([], [20.0] * 4)
    notes = [part for c in calls for part in mp_models.split_notes(c.notes)]
    assert mp_models.SEPARATE_EASEMENT_NOTE_PREFIX + clause.rstrip(".") in notes


def test_tie_line_after_closure_is_no_separate_description() -> None:
    calls, tracts = extract_calls(PROBES["r57_mineral_parcel_then_tie_line"], strict=True)
    # One description: the reservation is its preamble, never an EXCEPTION tract.
    assert tracts == [] and not any(c.is_exception for c in calls)
    assert [c.distance_ft for c in calls[:4]] == [100.0] * 4


# --- roles_need_review ---------------------------------------------------------------


def _tract(label: str, kind: TractType = TractType.MAIN, basis=None) -> Tract:
    return Tract(label=label, tract_type=kind, role_basis=basis)


def test_role_review_rules() -> None:
    # A sole tract with a single, heading or unrecorded basis is established.
    for basis in ("single", "heading", None):
        assert roles_need_review([_tract("T", basis=basis)]) == []
    # An inferred role always needs review, even passed alone.
    assert roles_need_review([_tract("Tract 1", basis="inferred")]) == [
        "Tract 1 (main): main role assumed from its position, without a tract heading"
    ]
    # Several tracts: every one needs a heading; unrecorded (stored artifacts that
    # predate the field) and "single" bases fail closed.
    assert roles_need_review([_tract("A", basis="heading"), _tract("B", basis="heading")]) == []
    reasons = roles_need_review(
        [
            _tract("A", basis="heading"),
            _tract("B", TractType.EXCEPTION, "inferred"),
            _tract("C", TractType.EASEMENT, None),
            _tract("D", TractType.ADDITION, "single"),
        ]
    )
    assert reasons == [
        "B (exception): exception role inferred from EXCEPT wording",
        "C (easement): role basis not recorded, so no explicit tract heading is established",
        "D (addition): marked the sole description, but the deed has 4 descriptions",
    ]


def test_stored_tract_without_role_basis_loads_as_unrecorded() -> None:
    payload = {"label": "Tract 1", "tract_type": "main", "calls": []}
    tract = Tract.model_validate(payload)
    assert tract.role_basis is None
    assert "role_basis" not in tract.model_dump(exclude_unset=True)
    stored = LegalDescription.model_validate(
        {"calls": [], "tracts": [payload, {**payload, "label": "Tract 2"}]}
    )
    assert len(roles_need_review(stored.tracts)) == 2
    with pytest.raises(ValueError):
        Tract.model_validate({**payload, "role_basis": "guessed"})


# --- every eligibility consumer ---------------------------------------------------------

TWO_UNHEADED = PROBES["plain_exception_after"]


def test_verify_tract_blocks_an_inferred_tract_passed_alone(tmp_path: Path) -> None:
    _, tracts = extract_calls(TWO_UNHEADED, strict=True)
    main = tracts[0]
    assert main.role_basis == "inferred"
    alone = verify_tract(main.calls, tract=main)
    assert not alone.is_fully_verified()
    assert any(c.name == DESCRIPTION_ROLES_CHECK for c in alone.checks)
    # Round 58: the tract's calls carry the role-review mark, so they are blocked even
    # without the tract.
    assert not verify_tract(main.calls).is_fully_verified()
    # A forged tract-unaware result for the same geometry (its mark removed) is refused
    # by the exporter.
    forged = verify_tract([c.model_copy(update={"notes": None}) for c in main.calls])
    assert forged.is_fully_verified()
    with pytest.raises(ValueError, match="description roles need review"):
        export_verified_csv([], forged, str(tmp_path / "deed.csv"), tract_results=[(main, forged)])
    # So is the flat path when the description's tracts are supplied.
    calls, _ = extract_calls(TWO_UNHEADED, strict=True)
    with pytest.raises(ValueError, match="description roles need review"):
        export_verified_csv(
            main.calls,
            forged,
            str(tmp_path / "flat.csv"),
            LegalDescription(calls=main.calls, tracts=tracts),
        )
    assert list(tmp_path.iterdir()) == []
    assert calls


def test_monolith_facades_block_and_refuse_identically(tmp_path: Path) -> None:
    _, tracts = extract_calls(TWO_UNHEADED, strict=True)
    legacy = [monolith.Tract.model_validate(t.model_dump()) for t in tracts]
    assert [t.role_basis for t in legacy] == ["inferred", "inferred"]
    results = ClosureChecker.verify_closure([], tracts=legacy)
    assert not any(r.is_fully_verified() for r in results)
    assert all(any(c.name == DESCRIPTION_ROLES_CHECK for c in r.checks) for r in results)
    forged = ClosureChecker.verify_closure(legacy[0].calls)
    with pytest.raises(ValueError, match="description roles need review"):
        CSVBuilder.export_verified_csv(
            [], forged, str(tmp_path / "deed.csv"), tract_results=[(legacy[0], forged)]
        )
    # Round 58: the tracts' calls carry the role-review mark, so relabelling the roles
    # alone stays blocked; a deed whose roles are established has unmarked calls.
    headed = [t.model_copy(update={"role_basis": "heading"}) for t in legacy]
    assert not ClosureChecker.verify_closure([], tracts=headed)[0].is_fully_verified()
    reviewed = [
        t.model_copy(update={"calls": [c.model_copy(update={"notes": None}) for c in t.calls]})
        for t in headed
    ]
    assert ClosureChecker.verify_closure([], tracts=reviewed)[0].is_fully_verified()


def test_review_text_never_passes_inferred_roles(tmp_path: Path) -> None:
    # Round 58: two parcel boundaries ("plain_also") are refused for separate reviews;
    # a parcel and its excepted land are reviewed together, and blocked.
    refused = review_text(PROBES["plain_also"], output_dir=tmp_path / "refused")
    assert refused["status"] == "error"
    assert "calls_verified.csv" not in refused["artifacts"]
    result = review_text(TWO_UNHEADED, output_dir=tmp_path / "review")
    assert result["status"] == "needs_review"
    codes = [e["code"] for e in result["errors"]]
    assert "description_roles_inferred" in codes
    assert "calls_verified.csv" not in result["artifacts"]
    assert not (tmp_path / "review" / "calls_verified.csv").exists()
    # A single description (with a reservation) still passes.
    single = review_text(PROBES["mineral_single_parcel"], output_dir=tmp_path / "single")
    assert single["status"] == "checks_passed"
    assert (tmp_path / "single" / "calls_verified.csv").exists()


def test_review_json_with_stored_tracts_needs_review(tmp_path: Path) -> None:
    from mp_review.api import review_file

    calls, tracts = extract_calls(TWO_UNHEADED, strict=True)
    stored = LegalDescription(calls=tracts[0].calls, tracts=tracts)
    path = tmp_path / "deed.json"
    path.write_text(stored.model_dump_json(), encoding="utf-8")
    result = review_file(path, output_dir=tmp_path / "review")
    assert result["status"] == "needs_review"
    assert "description_roles_inferred" in [e["code"] for e in result["errors"]]
    assert calls


def description_tracts(text: str) -> list[monolith.Tract]:
    """The monolith's tracts, from its one extraction (round 57: no second parse)."""
    tracts: list[monolith.Tract] = []
    CallExtractor.extract_calls(text, strict=False, skipped_courses=[], tracts=tracts)
    return tracts


def test_monolith_description_tracts_carry_role_bases() -> None:
    assert description_tracts(PROBES["plain"]) == []
    assert description_tracts(PROBES["mineral_single_parcel"]) == []
    unheaded = description_tracts(TWO_UNHEADED)
    assert [(t.tract_type.value, t.role_basis) for t in unheaded] == [
        ("main", "inferred"),
        ("exception", "inferred"),
    ]
    assert roles_need_review(unheaded)
    headed = description_tracts(PROBES["close0_two_headed_parcels"])
    assert [t.role_basis for t in headed] == ["heading", "heading"]
    assert roles_need_review(headed) == []


def test_pipeline_blocks_every_tract_of_an_inferred_deed(monkeypatch) -> None:
    from metesparser.pipeline import Pipeline

    calls, tracts = extract_calls(TWO_UNHEADED, strict=True)
    legal = mp_models.LegalDescription(calls=calls, tracts=tracts)

    class FakeProcessor:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def process_deed_pdf(self, *args, **kwargs):
            return legal

    monkeypatch.setattr("metesparser.pipeline.PDFProcessor", FakeProcessor)
    results = Pipeline(provider="openai").run(Path("deed.pdf"))
    assert isinstance(results, list) and len(results) == 2
    assert not any(r.is_fully_verified() for r in results)
