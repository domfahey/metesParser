"""PR #60 round 24: spiral double-entry, tract skips on single export, shared skip helper."""

from __future__ import annotations

import mp_export.csv_writer as package_writer
import mp_models
import mp_verify.closure as package_closure
import pytest
from mp_export import export_verified_csv as package_export
from mp_verify.checks import compare_double_entry as package_compare
from mp_verify.closure import verify_closure as package_verify

from metesparser import models as monolith_models
from metesparser.closure_checker import ClosureChecker
from metesparser.csv_builder import CSVBuilder

IMPLS = {
    "package": (mp_models, package_compare, package_verify, package_export),
    "monolith": (
        monolith_models,
        ClosureChecker.compare_double_entry,
        ClosureChecker.verify_closure,
        CSVBuilder.export_verified_csv,
    ),
}


def _spiral(m, bearing="N 20° E", length=100.0, curve_type="spiral", **extra):
    return m.DeedCall(
        course=1,
        direction_text="recorded",
        chord_bearing=bearing,
        distance_ft=length,
        chord_length_ft=length,
        curve_type=curve_type,
        **extra,
    )


def _square(m):
    return [
        m.DeedCall(
            course=i + 1,
            direction_text="recorded",
            bearing_azimuth_deg_from_north=a,
            distance_ft=100.0,
        )
        for i, a in enumerate((0.0, 90.0, 180.0, 270.0))
    ]


def _skip(m, course=5, tract_label=None):
    return m.SkippedCourse(
        course=course,
        source_course=course,
        source_excerpt="x",
        error_type="E",
        error="e",
        tract_label=tract_label,
    )


@pytest.mark.parametrize("impl", IMPLS)
def test_chord_only_spiral_chord_bearing_is_compared(impl):
    m, compare, _, _ = IMPLS[impl]
    found = compare([_spiral(m, "N 20° E")], [_spiral(m, "S 70° W")])
    assert any("Chord bearing" in d for d in found)


@pytest.mark.parametrize("impl", IMPLS)
def test_chord_only_spiral_chord_length_is_compared(impl):
    m, compare, _, _ = IMPLS[impl]
    found = compare([_spiral(m, length=100.0)], [_spiral(m, length=150.0)])
    assert any("Chord length" in d for d in found)


@pytest.mark.parametrize("impl", IMPLS)
def test_curve_type_mismatch_is_reported(impl):
    m, compare, _, _ = IMPLS[impl]
    kwargs = {"radius_ft": 200.0, "curve_dir": "left", "delta_deg": 28.0}
    a = _spiral(m, **kwargs)
    b = _spiral(m, curve_type="simple", **kwargs)
    assert any("Curve type" in d for d in compare([a], [b]))


@pytest.mark.parametrize("impl", IMPLS)
def test_identical_chord_only_spirals_agree(impl):
    m, compare, _, _ = IMPLS[impl]
    assert compare([_spiral(m)], [_spiral(m)]) == []


@pytest.mark.parametrize("impl", IMPLS)
def test_single_export_honours_tract_skipped_courses(impl, tmp_path):
    m, _, verify, export = IMPLS[impl]
    calls = _square(m)
    tract = m.Tract(label="A", tract_type=m.TractType.MAIN, calls=calls, skipped_courses=[_skip(m)])
    ld = m.LegalDescription(calls=calls, tracts=[tract])
    result = verify(ld.calls)
    assert result.is_fully_verified()
    with pytest.raises(ValueError):
        export(ld.calls, result, str(tmp_path / "x.csv"), ld)
    assert not (tmp_path / "x_verified.csv").exists()


@pytest.mark.parametrize("impl", IMPLS)
def test_single_export_without_skips_still_writes(impl, tmp_path):
    m, _, verify, export = IMPLS[impl]
    calls = _square(m)
    tract = m.Tract(label="A", tract_type=m.TractType.MAIN, calls=calls)
    ld = m.LegalDescription(calls=calls, tracts=[tract])
    export(ld.calls, verify(ld.calls), str(tmp_path / "x.csv"), ld)
    assert (tmp_path / "x_verified.csv").exists()


def test_skips_for_tract_routing():
    m = mp_models
    own, mine, other, unplaced = _skip(m, 1), _skip(m, 2, "A"), _skip(m, 3, "B"), _skip(m, 4, "Z")
    ta = m.Tract(label="A", tract_type=m.TractType.MAIN, calls=[], skipped_courses=[own])
    tb = m.Tract(label="B", tract_type=m.TractType.MAIN, calls=[])
    got = package_closure.skips_for_tract(ta, [ta, tb], [mine, other, unplaced, own])
    assert got == [own, mine, unplaced]


def test_exporters_and_verifier_use_shared_helper(monkeypatch, tmp_path):
    seen: list[str] = []
    real = package_closure.skips_for_tract

    def spy(*args, **kwargs):
        seen.append("x")
        return real(*args, **kwargs)

    for target, name in (
        (package_closure, "skips_for_tract"),
        # The monolith CSVBuilder delegates to the package writer's routing.
        (package_writer, "skips_for_tract"),
    ):
        monkeypatch.setattr(target, name, spy)
    m = mp_models
    tracts = [m.Tract(label="A", tract_type=m.TractType.MAIN, calls=_square(m))]
    results = package_verify([], tracts=tracts)
    assert seen
    n = len(seen)
    package_export([], results[0], str(tmp_path / "p.csv"), tract_results=[(tracts[0], results[0])])
    assert len(seen) > n
    n = len(seen)
    mt = [
        monolith_models.Tract(
            label="A", tract_type=monolith_models.TractType.MAIN, calls=_square(monolith_models)
        )
    ]
    mr = ClosureChecker.verify_closure([], tracts=mt)
    CSVBuilder.export_verified_csv(
        [], mr[0], str(tmp_path / "m.csv"), tract_results=[(mt[0], mr[0])]
    )
    assert len(seen) > n
