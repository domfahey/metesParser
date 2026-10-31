"""PR #60 round 52: easement/exception tracts never reach verified export.

The monolith ``ClosureChecker``/``CSVBuilder`` facades block and skip non-boundary
tracts exactly like the packages, and parsed easement text never yields a verified
CSV for the easement.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from mp_models import LegalDescription, TractType
from mp_parse.calls import extract_calls
from mp_verify import verify_closure

from tests.unit.test_pr60_r28_csv_facade_tdd import _differential, _square

SQUARE = (
    "BEGINNING at a pin; thence N 0° E 100 feet to a pin; thence S 90° E 100 feet to a pin; "
    "thence S 0° W 100 feet to a pin; thence N 90° W 100 feet to the point of beginning."
)
EASEMENT = "TOGETHER WITH an easement for access as follows: " + SQUARE.replace("100", "10")


def _export(flat, tracts, path: Path):
    from mp_export import export_verified_csv

    results = verify_closure(flat, tracts=tracts)
    return results, export_verified_csv(
        flat,
        results[0],
        str(path),
        legal_desc=LegalDescription(calls=flat, tracts=tracts),
        tract_results=list(zip(tracts, results, strict=True)),
    )


def test_parsed_boundary_plus_easement_exports_nothing(tmp_path: Path) -> None:
    # Round 56: the easement's role is inferred from its grant wording, so the whole
    # deed is blocked (fail closed); before, the boundary tract was exported.
    flat, tracts = extract_calls(SQUARE + " " + EASEMENT)
    assert [t.tract_type for t in tracts] == [TractType.MAIN, TractType.EASEMENT]
    with pytest.raises(ValueError, match="description roles need review"):
        _export(flat, tracts, tmp_path / "deed.csv")
    assert list(tmp_path.iterdir()) == []
    assert [r.is_fully_verified() for r in verify_closure(flat, tracts=tracts)] == [False, False]


def test_parsed_easement_only_is_refused(tmp_path: Path) -> None:
    flat, tracts = extract_calls(EASEMENT)
    assert [t.tract_type for t in tracts] == [TractType.EASEMENT]
    # Round 57: the easement's role came from its grant ("inferred", never "single"),
    # so the role review refuses it first; trusted, it is still no parcel boundary.
    assert [t.role_basis for t in tracts] == ["inferred"]
    with pytest.raises(ValueError, match="description roles need review"):
        _export(flat, tracts, tmp_path / "deed.csv")
    trusted = [t.model_copy(update={"role_basis": "single"}) for t in tracts]
    with pytest.raises(ValueError, match="no parcel boundary tract"):
        _export(flat, trusted, tmp_path / "deed.csv")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("kind", ["EASEMENT", "EXCEPTION"])
def test_facade_blocks_and_skips_non_boundary_tract_identically(tmp_path, kind):
    def scenario(impl, out):
        m = impl["m"]
        main = m.Tract(
            label="Tract 1", tract_type=m.TractType.MAIN, role_basis="heading", calls=_square(m)
        )
        other = m.Tract(
            label="Other 1",
            tract_type=getattr(m.TractType, kind),
            role_basis="heading",
            calls=_square(m, side=10.0),
        )
        results = impl["verify"]([], tracts=[main, other])
        assert [r.is_fully_verified() for r in results] == [True, False]
        assert any(c.name == "non_boundary_tract" for c in results[1].checks)
        pairs = [(main, results[0]), (other, results[1])]
        return impl["export"]([], results[0], str(out / "deed.csv"), tract_results=pairs)

    got = _differential(tmp_path, scenario)
    assert got["outcome"] == ("ok", ["deed_verified_tract1.csv"])
    assert b"not a parcel boundary" in got["files"]["deed_verified.verification.txt"]


@pytest.mark.parametrize("kind", ["EASEMENT", "EXCEPTION"])
def test_facade_refuses_non_boundary_only_identically(tmp_path, kind):
    def scenario(impl, out):
        m = impl["m"]
        other = m.Tract(label="Other 1", tract_type=getattr(m.TractType, kind), calls=_square(m))
        # Tract-unaware verification of the same calls claims eligibility.
        forged = impl["verify"](other.calls)
        assert forged.is_fully_verified()
        return impl["export"]([], forged, str(out / "deed.csv"), tract_results=[(other, forged)])

    got = _differential(tmp_path, scenario)
    assert got["outcome"][0] == "ValueError"
    assert "no parcel boundary tract" in got["outcome"][1]
    assert got["files"] == {}
