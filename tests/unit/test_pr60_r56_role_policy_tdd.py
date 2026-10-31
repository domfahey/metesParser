"""PR #60 round 56: fail closed on inferred description roles (user decision).

When a deed has more than one description and any description's role (main,
addition, exception, easement) was inferred from wording rather than an explicit
TRACT/PARCEL heading, nothing in the deed is verified or exported, through any path:
``mp_verify.verify_closure`` (and the monolith facade), ``export_verified_csv`` (and
the facade), the ``review_text`` API and the monolith Pipeline. A single description
is unaffected, and a deed whose every role comes from a heading still exports its
verified MAIN/ADDITION tracts. The round-55 reviewer probes are replayed here.
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

BOTH_TRACTS = ["deed_verified_tract1.csv", "deed_verified_tract2.csv"]
# Only these probes export: one description, or every role from a heading.
EXPORTS = {
    **{f"close{i}_two_headed_parcels": BOTH_TRACTS for i in range(len(CLOSINGS))},
    **{f"second_parcel{i}_headed": BOTH_TRACTS for i in range(len(RECITALS))},
    "plain": ["deed_verified.csv"],
    "mineral_single_parcel": ["deed_verified.csv"],
    "mineral_single_parcel_running_on": ["deed_verified.csv"],
    "creek_bed_single_parcel": ["deed_verified.csv"],
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
    "name", ["mineral_single_parcel", "mineral_single_parcel_running_on", "creek_bed_single_parcel"]
)
def test_reservation_in_single_parcel_is_one_main_parcel(name: str) -> None:
    calls, tracts = extract_calls(PROBES[name], strict=True)
    assert tracts == []
    assert [(c.distance_ft, c.is_exception) for c in calls] == [(100.0, False)] * 4
    assert verify_closure(calls).is_fully_verified()


def test_second_fee_parcel_with_mineral_reservation_exports_only_under_headings() -> None:
    _, headed = extract_calls(PROBES["second_parcel0_headed"], strict=True)
    assert [(t.tract_type, t.role_basis) for t in headed] == [
        (TractType.MAIN, "heading"),
        (TractType.MAIN, "heading"),
    ]
    assert all(r.is_fully_verified() for r in verify_closure([], tracts=headed))
    # Unheaded, the reservation types the second parcel EXCEPTION (a wrong guess): the
    # policy blocks the deed rather than exporting the first parcel alone.
    _, unheaded = extract_calls(PROBES["second_parcel0_also"], strict=True)
    assert [(t.tract_type, t.role_basis) for t in unheaded] == [
        (TractType.MAIN, "inferred"),
        (TractType.EXCEPTION, "inferred"),
    ]
    assert not any(r.is_fully_verified() for r in verify_closure([], tracts=unheaded))


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
    # A forged tract-unaware result for the same calls is refused by the exporter.
    forged = verify_tract(main.calls)
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
    headed = [t.model_copy(update={"role_basis": "heading"}) for t in legacy]
    assert ClosureChecker.verify_closure([], tracts=headed)[0].is_fully_verified()


def test_review_text_never_passes_inferred_roles(tmp_path: Path) -> None:
    result = review_text(PROBES["plain_also"], output_dir=tmp_path / "review")
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
