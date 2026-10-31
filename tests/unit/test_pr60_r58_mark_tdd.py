"""PR #60 round 58: the fail-closed role gate travels with the calls.

Round 57 marked only a blocked deed's merged flat calls, so a tract's own calls (and an
easement tract's calls, which never reach the flat list) verified and exported alone.
The block now travels with the data: when a deed's description roles need review, every
tract's calls carry the role-review mark (``DESCRIPTION_ROLES_NOTE``) as well as the
flat calls, and the calls of an easement or exception tract always carry a registered
non-boundary note that verification blocks on with or without the tract. Any subset of
calls taken from a blocked deed or from a non-boundary tract therefore never verifies or
exports, through any API: the package, the monolith facades (``CallExtractor`` default
and ``tracts=``, ``ClosureChecker``, ``CSVBuilder``), and CSV/JSON round trips. Text
review refuses a description the tract split divides into several parcel boundaries.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Iterator
from pathlib import Path

import mp_models
import pytest
from mp_export.csv_writer import calls_to_csv, csv_to_calls, export_verified_csv
from mp_models import (
    DESCRIPTION_ROLES_CHECK,
    DESCRIPTION_ROLES_NOTE,
    DESCRIPTION_ROLES_PREFIX,
    FIXED_NOTES,
    DeedCall,
    Tract,
    TractType,
    is_boundary_tract,
    roles_need_review,
    split_notes,
)
from mp_parse.calls import extract_calls
from mp_review.api import review_text
from mp_verify import verify_closure, verify_tract

from metesparser import models as monolith
from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker
from metesparser.csv_builder import CSVBuilder
from tests.unit.test_pr60_r56_role_policy_tdd import PROBES, _square

NON_BOUNDARY_CHECK = "non_boundary_tract"
P = _square(100)
E2 = _square(20, "BEGINNING at an iron")
# The round-57 reviewer's reproduction: a lot, then an easement described by its courses.
LOT_EASEMENT = (
    f"ALL THAT CERTAIN lot bounded and described as follows: {P} TOGETHER WITH an easement "
    f"for ingress and egress described as follows: {_square(10, 'BEGINNING at a stake')}"
)
HEADED_PARCELS = {
    "parcel_one_two": f"PARCEL ONE: {P} PARCEL TWO: {E2}",
    "tract_1_2": f"TRACT 1: {P} TRACT 2: {E2}",
}


def _tracts(text: str) -> tuple[list[DeedCall], list[Tract]]:
    return extract_calls(text, strict=False, skipped_courses=[])


# Every deed whose description roles need review, and the reproduction. Easement and
# exception roles are never established by a heading, so every deed with a
# non-boundary tract is among them.
DEEDS = {
    "lot_then_easement": LOT_EASEMENT,
    **{name: text for name, text in PROBES.items() if roles_need_review(_tracts(text)[1])},
}
NON_BOUNDARY_DEEDS = [
    name
    for name, text in DEEDS.items()
    if any(not is_boundary_tract(t.tract_type) for t in _tracts(text)[1])
]


def _marked(call: DeedCall | monolith.DeedCall) -> bool:
    return DESCRIPTION_ROLES_NOTE in split_notes(call.notes)


def _non_boundary_notes(call: DeedCall | monolith.DeedCall) -> list[str]:
    notes = split_notes(call.notes)
    return [note for note in mp_models.NON_BOUNDARY_NOTES if note in notes]


def _stripped(calls: list[DeedCall]) -> list[DeedCall]:
    """The calls without any role-review or non-boundary mark (a hand-edited artifact)."""
    marks = {DESCRIPTION_ROLES_NOTE, *getattr(mp_models, "NON_BOUNDARY_NOTES", ())}
    return [
        c.model_copy(
            update={"notes": "; ".join(n for n in split_notes(c.notes) if n not in marks) or None}
        )
        for c in calls
    ]


def _count(result: mp_models.ClosureResult | monolith.ClosureResult, name: str) -> int:
    return [c.name for c in result.checks].count(name)


def _role_warnings_match_checks(result: mp_models.ClosureResult) -> bool:
    """One warning per role check: none duplicated, none without its check."""
    roles = [w for w in result.warnings if w.startswith(DESCRIPTION_ROLES_PREFIX)]
    non_boundary = [w for w in result.warnings if w.startswith(f"{NON_BOUNDARY_CHECK}:")]
    return (len(roles), len(non_boundary)) == (
        _count(result, DESCRIPTION_ROLES_CHECK),
        _count(result, NON_BOUNDARY_CHECK),
    )


# --- the registry -------------------------------------------------------------------------


def test_non_boundary_notes_are_registered_fixed_notes() -> None:
    easement, exception = mp_models.EASEMENT_TRACT_NOTE, mp_models.EXCEPTION_TRACT_NOTE
    assert mp_models.NON_BOUNDARY_NOTES == (easement, exception)
    for note in (easement, exception):
        assert note in FIXED_NOTES and "; " not in note
        assert note.startswith("not part of the parcel boundary (")
        assert note.endswith(" tract) - not eligible for verified export")
    joined = f"record call: N 10° E 5 feet; x; {exception}; {DESCRIPTION_ROLES_NOTE}"
    assert split_notes(joined)[-2:] == [exception, DESCRIPTION_ROLES_NOTE]


# --- item 1: every tract's calls carry the marks ------------------------------------------


@pytest.mark.parametrize("name", sorted(DEEDS))
def test_every_call_of_a_blocked_deed_is_marked(name: str) -> None:
    calls, tracts = _tracts(DEEDS[name])
    assert all(_marked(c) for c in calls)
    assert tracts and all(_marked(c) for t in tracts for c in t.calls)


@pytest.mark.parametrize("name", sorted(NON_BOUNDARY_DEEDS))
def test_non_boundary_tract_calls_carry_their_note(name: str) -> None:
    calls, tracts = _tracts(DEEDS[name])
    notes = {
        TractType.EASEMENT: mp_models.EASEMENT_TRACT_NOTE,
        TractType.EXCEPTION: mp_models.EXCEPTION_TRACT_NOTE,
    }
    for tract in tracts:
        expected = [notes[tract.tract_type]] if tract.tract_type in notes else []
        assert all(_non_boundary_notes(c) == expected for c in tract.calls), tract.label
        # The exception flag is unchanged: an exception tract's calls are exceptions.
        assert all(c.is_exception == (tract.tract_type == TractType.EXCEPTION) for c in tract.calls)
    # An easement's legs still never reach the flat list; an exception's do, flagged.
    assert mp_models.EASEMENT_TRACT_NOTE not in [n for c in calls for n in _non_boundary_notes(c)]
    assert all(c.is_exception for c in calls if _non_boundary_notes(c))


def test_lot_then_easement_tract_calls_never_verify_or_export(tmp_path: Path) -> None:
    calls, tracts = _tracts(LOT_EASEMENT)
    assert [(t.tract_type, t.role_basis) for t in tracts] == [
        (TractType.MAIN, "inferred"),
        (TractType.EASEMENT, "inferred"),
    ]
    for tract in tracts:
        result = verify_closure(tract.calls)
        assert not result.is_fully_verified()
        assert _count(result, DESCRIPTION_ROLES_CHECK) == 1
        assert _count(result, NON_BOUNDARY_CHECK) == (
            0 if tract.tract_type == TractType.MAIN else 1
        )
        assert not verify_tract(tract.calls).is_fully_verified()
        with pytest.raises(ValueError, match="Cannot export verified CSV"):
            export_verified_csv(tract.calls, result, str(tmp_path / "x.csv"))
    assert list(tmp_path.iterdir()) == []
    # The geometry closes: only the marks block it.
    assert all(verify_tract(_stripped(t.calls)).is_fully_verified() for t in tracts)


def test_the_non_boundary_note_blocks_without_the_role_mark(tmp_path: Path) -> None:
    easement = _tracts(LOT_EASEMENT)[1][1]
    noted = [
        c.model_copy(update={"notes": mp_models.EASEMENT_TRACT_NOTE})
        for c in _stripped(easement.calls)
    ]
    for result in (verify_closure(noted), verify_tract(noted)):
        assert not result.is_fully_verified()
        assert _count(result, NON_BOUNDARY_CHECK) == 1
        assert _count(result, DESCRIPTION_ROLES_CHECK) == 0
    with pytest.raises(ValueError, match="Cannot export verified CSV"):
        export_verified_csv(noted, verify_tract(_stripped(noted)), str(tmp_path / "x.csv"))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("name", sorted(DEEDS))
def test_tract_verification_reports_each_role_check_once(name: str) -> None:
    calls, tracts = _tracts(DEEDS[name])
    for tract, result in zip(tracts, verify_closure(calls, tracts=tracts), strict=True):
        alone = verify_tract(tract.calls, tract=tract)
        for checked in (result, alone):
            assert _count(checked, DESCRIPTION_ROLES_CHECK) == 1
            assert _count(checked, NON_BOUNDARY_CHECK) == (
                0 if is_boundary_tract(tract.tract_type) else 1
            )
            assert _role_warnings_match_checks(checked)
            assert not checked.is_fully_verified()
    if calls:
        flat = verify_closure(calls)
        assert _count(flat, DESCRIPTION_ROLES_CHECK) == 1
        assert _count(flat, NON_BOUNDARY_CHECK) <= 1
        assert _role_warnings_match_checks(flat)


@pytest.mark.parametrize("name", ["close0_two_headed_parcels", "plain", "mineral_single_parcel"])
def test_established_roles_leave_every_call_unmarked(name: str) -> None:
    calls, tracts = _tracts(PROBES[name])
    every = [*calls, *(c for t in tracts for c in t.calls)]
    assert not any(_marked(c) or _non_boundary_notes(c) for c in every)
    for tract, result in zip(tracts, verify_closure(calls, tracts=tracts), strict=True):
        assert result.is_fully_verified()
        assert verify_tract(tract.calls).is_fully_verified()


# --- item 2: the monolith tract facade ------------------------------------------------------


def _monolith_tracts(text: str) -> tuple[list[monolith.DeedCall], list[monolith.Tract]]:
    tracts: list[monolith.Tract] = []
    calls = CallExtractor.extract_calls(text, strict=False, skipped_courses=[], tracts=tracts)
    return calls, tracts


def test_monolith_verify_tract_takes_the_tract_like_the_package() -> None:
    assert "tract" in inspect.signature(ClosureChecker.verify_tract).parameters
    _, tracts = _monolith_tracts(LOT_EASEMENT)
    _, package_tracts = _tracts(LOT_EASEMENT)
    for tract, package_tract in zip(tracts, package_tracts, strict=True):
        facade = ClosureChecker.verify_tract(tract.calls, tract=tract)
        package = verify_tract(package_tract.calls, tract=package_tract)
        assert [(c.name, c.status) for c in facade.checks] == [
            (c.name, c.status) for c in package.checks
        ]
        assert facade.warnings == package.warnings
        assert not facade.is_fully_verified()
        assert _count(facade, DESCRIPTION_ROLES_CHECK) == 1
    headed = _monolith_tracts(HEADED_PARCELS["parcel_one_two"])[1]
    assert all(ClosureChecker.verify_tract(t.calls, tract=t).is_fully_verified() for t in headed)


def test_monolith_tract_calls_never_verify_or_export(tmp_path: Path) -> None:
    _, tracts = _monolith_tracts(LOT_EASEMENT)
    easement = tracts[1]
    assert easement.tract_type == monolith.TractType.EASEMENT
    assert all(c.is_exception is False for c in easement.calls)
    for tract in tracts:
        assert not ClosureChecker.verify_tract(tract.calls).is_fully_verified()
        result = ClosureChecker.verify_closure(tract.calls)
        assert not result.is_fully_verified()
        with pytest.raises(ValueError, match="Cannot export verified CSV"):
            CSVBuilder.export_verified_csv(tract.calls, result, str(tmp_path / "x.csv"))
    assert list(tmp_path.iterdir()) == []


# --- item 3: the monolith default extraction ------------------------------------------------


@pytest.mark.parametrize(
    "name", ["lot_then_easement", "plain_also", "plain_exception_after", "close0_easement_after"]
)
def test_monolith_default_extraction_is_the_package_extraction(name: str, tmp_path: Path) -> None:
    text = DEEDS[name]
    calls = CallExtractor.extract_calls(text)
    flat, _ = extract_calls(text)
    assert [(c.course, c.distance_ft, c.is_exception, c.notes) for c in calls] == [
        (c.course, c.distance_ft, c.is_exception, c.notes) for c in flat
    ]
    assert calls and all(_marked(c) for c in calls)
    assert calls == _monolith_tracts(text)[0]
    result = ClosureChecker.verify_closure(calls)
    assert not result.is_fully_verified()
    with pytest.raises(ValueError, match="Cannot export verified CSV"):
        CSVBuilder.export_verified_csv(calls, result, str(tmp_path / "x.csv"))
    assert list(tmp_path.iterdir()) == []


def test_monolith_default_extraction_of_one_description_is_unchanged() -> None:
    calls = CallExtractor.extract_calls(PROBES["plain"])
    assert [(c.course, c.distance_ft, c.notes) for c in calls] == [
        (i, 100.0, None) for i in range(1, 5)
    ]
    assert ClosureChecker.verify_closure(calls).is_fully_verified()


# --- item 4: text review never presents two parcels as one boundary ------------------------


@pytest.mark.parametrize(
    "text", [*HEADED_PARCELS.values(), PROBES["plain_also"]], ids=[*HEADED_PARCELS, "plain_also"]
)
def test_text_review_refuses_several_parcel_boundaries(text: str, tmp_path: Path) -> None:
    result = review_text(text, output_dir=tmp_path / "r")
    assert result["status"] == "error"
    assert result["errors"] == [
        {
            "code": "invalid_input",
            "message": "Multiple parcel descriptions require separate reviews.",
        }
    ]
    assert result["calls"] == []
    assert json.loads((tmp_path / "r" / "calls.json").read_text(encoding="utf-8")) == []
    assert csv_to_calls(str(tmp_path / "r" / "calls.csv")) == []
    assert not (tmp_path / "r" / "calls_verified.csv").exists()


def test_text_review_still_reviews_one_parcel_and_its_exception(tmp_path: Path) -> None:
    single = review_text(f"PARCEL ONE: {P}", output_dir=tmp_path / "single")
    assert single["status"] == "checks_passed"
    excepted = review_text(PROBES["plain_exception_after"], output_dir=tmp_path / "excepted")
    assert excepted["status"] == "needs_review"
    assert "description_roles_inferred" in [e["code"] for e in excepted["errors"]]
    assert len(excepted["calls"]) == 8
    assert not (tmp_path / "excepted" / "calls_verified.csv").exists()


# --- property: no subset path verifies or exports inferred or non-boundary land -------------


def _subsets(text: str) -> Iterator[tuple[str, list[DeedCall]]]:
    """Every call set a caller can take from the deed, directly or after a round trip."""
    calls, tracts = _tracts(text)
    taken = [("flat", calls), *((f"tract {t.label}", t.calls) for t in tracts)]
    # A caller clearing the exception flag (verify_tract does) makes them a boundary.
    taken += [
        (f"{label} as boundary", [c.model_copy(update={"is_exception": False}) for c in subset])
        for label, subset in taken
        if any(c.is_exception for c in subset)
    ]
    # The monolith extractions: default and tracts=, read back as package calls.
    default = CallExtractor.extract_calls(text, strict=False, skipped_courses=[])
    mono_flat, mono_tracts = _monolith_tracts(text)
    taken += [
        (f"monolith {label}", [DeedCall.model_validate(c.model_dump()) for c in subset])
        for label, subset in [
            ("default", default),
            ("flat", mono_flat),
            *((f"tract {t.label}", t.calls) for t in mono_tracts),
        ]
    ]
    for label, subset in taken:
        if not subset:
            continue
        yield label, subset
        yield (
            f"{label} via JSON",
            [
                DeedCall.model_validate(record)
                for record in json.loads(json.dumps([c.model_dump(mode="json") for c in subset]))
            ],
        )


def _csv_round_trip(calls: list[DeedCall], directory: Path) -> list[DeedCall]:
    path = directory / "round_trip.csv"
    calls_to_csv(calls, str(path))
    loaded = csv_to_calls(str(path))
    path.unlink()
    return loaded


def _verified_or_exported(calls: list[DeedCall], directory: Path) -> list[str]:
    """Which verification or export paths accept these calls (none may)."""
    accepted: list[str] = []
    out = str(directory / "deed.csv")
    if verify_closure(calls).is_fully_verified():
        accepted.append("verify_closure")
    if verify_tract(calls).is_fully_verified():
        accepted.append("verify_tract")
    # The exporter, given the calls' own result and a forged result for the same
    # geometry without its marks.
    for label, result in (
        ("own", verify_closure(calls)),
        ("forged", verify_closure(_stripped(calls))),
    ):
        try:
            export_verified_csv(calls, result, out)
            accepted.append(f"export_verified_csv ({label} result)")
        except ValueError:
            pass
    legacy = [monolith.DeedCall.model_validate(c.model_dump(exclude_unset=True)) for c in calls]
    if ClosureChecker.verify_closure(legacy).is_fully_verified():
        accepted.append("ClosureChecker.verify_closure")
    if ClosureChecker.verify_tract(legacy).is_fully_verified():
        accepted.append("ClosureChecker.verify_tract")
    forged = ClosureChecker.verify_closure(
        [
            monolith.DeedCall.model_validate(c.model_dump(exclude_unset=True))
            for c in _stripped(calls)
        ]
    )
    try:
        CSVBuilder.export_verified_csv(legacy, forged, out)
        accepted.append("CSVBuilder.export_verified_csv")
    except ValueError:
        pass
    if any(directory.glob("deed_verified*")):
        accepted.append("files written")
    return accepted


@pytest.mark.parametrize("name", sorted(DEEDS))
def test_no_subset_of_inferred_or_non_boundary_land_verifies(name: str, tmp_path: Path) -> None:
    accepted: dict[str, list[str]] = {}
    closes_unmarked = False
    for label, subset in _subsets(DEEDS[name]):
        for representation, calls in (
            (label, subset),
            (f"{label} via CSV", _csv_round_trip(subset, tmp_path)),
        ):
            paths = _verified_or_exported(calls, tmp_path)
            if paths:
                accepted[representation] = paths
        closes_unmarked = closes_unmarked or verify_tract(_stripped(subset)).is_fully_verified()
    assert accepted == {}
    # Not vacuous: some taken traverse closes once its marks are removed.
    assert closes_unmarked
