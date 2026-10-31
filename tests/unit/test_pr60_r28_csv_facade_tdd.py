"""PR #60 round 28: the monolith CSV builder is an ``mp_export.csv_writer`` facade.

``CSVBuilder`` converts monolith models through ``package_bridge`` and delegates to
the package writer instead of duplicating it. A differential exports and imports the
same calls through both implementations and compares every written file byte for
byte (CSV, metadata, verification summary, audit JSON/HTML) and every import result
or error. A legacy 21-column row carrying curve fields records that its curve type
was not stated, so a historical spiral read back as a circular arc is visible.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import mp_export.csv_writer as package_writer
import mp_models
import pytest

from metesparser import models as monolith_models
from metesparser.closure_checker import ClosureChecker
from metesparser.csv_builder import CSVBuilder

LEGACY_NOTE = "curve type not recorded (legacy CSV); treated as circular"
LEGACY_HEADER = package_writer.LEGACY_FIELDNAMES

IMPLS: dict[str, dict[str, Any]] = {
    "package": {
        "m": mp_models,
        "verify": __import__("mp_verify").verify_closure,
        "export": package_writer.export_verified_csv,
        "calls_to_csv": package_writer.calls_to_csv,
        "ld_to_csv": package_writer.legal_description_to_csv,
        "to_row": package_writer._call_to_row,
        "read_text": package_writer.csv_text_to_calls,
        "read_file": package_writer.csv_to_calls,
    },
    "monolith": {
        "m": monolith_models,
        "verify": ClosureChecker.verify_closure,
        "export": CSVBuilder.export_verified_csv,
        "calls_to_csv": CSVBuilder.calls_to_csv,
        "ld_to_csv": CSVBuilder.legal_description_to_csv,
        "to_row": CSVBuilder._call_to_row,
        "read_text": CSVBuilder.csv_text_to_calls,
        "read_file": CSVBuilder.csv_to_calls,
    },
}


# --- Fixtures built identically from either model module -----------------------


def _square(m, start=1, side=100.0):
    return [
        m.DeedCall(
            course=start + i,
            direction_text=f"{d} {side}",
            bearing_azimuth_deg_from_north=a,
            distance_ft=side,
            along="Southerly line of Pennbrook Drive" if i == 0 else None,
            monument_type="iron_pin" if i == 1 else None,
            notes="note, with comma" if i == 2 else None,
        )
        for i, (d, a) in enumerate((("N", 0.0), ("E", 90.0), ("S", 180.0), ("W", 270.0)))
    ]


def _curve(m, curve_type=None, notes=None):
    return m.DeedCall(
        course=1,
        direction_text="along a curve to the right",
        distance_ft=49.5,
        curve_type=curve_type,
        curve_dir="right",
        radius_ft=100.0,
        arc_length_ft=50.0,
        chord_bearing="N 45°00'00\" E",
        chord_length_ft=49.5,
        notes=notes,
    )


def _legal_description(m, calls):
    return m.LegalDescription(
        calls=calls,
        pob_description="the Point of Beginning",
        source_doc="deed.pdf",
        page=3,
        basis_of_bearing="NAD83",
        stated_area_sq_ft=10000.0,
        clauses=[m.DeedClause(clause_type="subject_to", text="easements of record")],
        subdivision_ref=m.SubdivisionReference(lot="7", block="B", subdivision_name="Oaks"),
        witness_trees=["oak 12in"],
    )


def _audit(m, skipped=()):
    return m.AuditContext(
        run_metadata=m.RunMetadata(
            parser_version="0.6.0",
            llm_provider="none",
            llm_model="none",
            prompt_hash="0" * 64,
            timestamp_utc=datetime(2026, 10, 30, tzinfo=UTC),
            source_pdf="deed.pdf",
            cache_enabled=False,
        ),
        call_audits=[m.CallAudit(course=1, source_excerpt="N 100", flags=["x"])],
        skipped_courses=list(skipped),
    )


def _skip(m, course=9, tract_label=None):
    return m.SkippedCourse(
        course=course,
        source_course=course,
        source_excerpt="garbled",
        error_type="E",
        error="e",
        tract_label=tract_label,
    )


def _files(directory: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(directory.iterdir())}


def _run(impl: str, tmp_path: Path, scenario) -> dict[str, Any]:
    """Run a scenario in a per-implementation directory; capture files and outcome."""
    out = tmp_path / impl
    out.mkdir()
    try:
        value = scenario(IMPLS[impl], out)
        outcome: Any = ("ok", [Path(p).name for p in value] if isinstance(value, list) else None)
    except ValueError as exc:
        outcome = ("ValueError", str(exc))
    return {"outcome": outcome, "files": _files(out)}


def _differential(tmp_path: Path, scenario) -> dict[str, Any]:
    package = _run("package", tmp_path, scenario)
    monolith = _run("monolith", tmp_path, scenario)
    assert monolith == package
    return package


# --- Differential: monolith output == package output ---------------------------


def test_verified_export_with_metadata_and_audit_is_identical(tmp_path):
    def scenario(impl, out):
        m = impl["m"]
        ld = _legal_description(m, _square(m))
        result = impl["verify"](ld.calls, stated_area_sq_ft=10000.0)
        return impl["export"](ld.calls, result, str(out / "deed.csv"), ld, audit_context=_audit(m))

    got = _differential(tmp_path, scenario)
    assert got["outcome"] == ("ok", ["deed_verified.csv"])
    assert set(got["files"]) == {
        "deed_verified.csv",
        "deed_verified.metadata.txt",
        "deed_verified.verification.txt",
        "deed_verified.audit.json",
        "deed_verified.audit.html",
    }


def test_verified_export_without_legal_description_is_identical(tmp_path):
    def scenario(impl, out):
        calls = _square(impl["m"])
        return impl["export"](calls, impl["verify"](calls), str(out / "deed.csv"))

    assert _differential(tmp_path, scenario)["outcome"] == ("ok", ["deed_verified.csv"])


def test_multi_tract_export_with_unverified_tract_is_identical(tmp_path):
    def scenario(impl, out):
        m = impl["m"]
        good = m.Tract(
            label="Tract A", tract_type=m.TractType.MAIN, role_basis="heading", calls=_square(m)
        )
        broken = _square(m, start=5)
        broken[3] = broken[3].model_copy(update={"distance_ft": 90.0})
        bad = m.Tract(
            label="Tract B", tract_type=m.TractType.EXCEPTION, role_basis="heading", calls=broken
        )
        results = impl["verify"]([], tracts=[good, bad])
        pairs = [(good, results[0]), (bad, results[1])]
        return impl["export"]([], results[0], str(out / "deed.csv"), tract_results=pairs)

    got = _differential(tmp_path, scenario)
    assert got["outcome"] == ("ok", ["deed_verified_tract1.csv"])
    assert b"Not verified" in got["files"]["deed_verified.verification.txt"]


@pytest.mark.parametrize("where", ["explicit", "audit", "tract"])
def test_skipped_courses_block_export_identically(tmp_path, where):
    def scenario(impl, out):
        m = impl["m"]
        calls = _square(m)
        tracts = []
        if where == "tract":
            tracts = [
                m.Tract(
                    label="A", tract_type=m.TractType.MAIN, calls=calls, skipped_courses=[_skip(m)]
                )
            ]
        ld = m.LegalDescription(calls=calls, tracts=tracts)
        return impl["export"](
            calls,
            impl["verify"](calls),
            str(out / "deed.csv"),
            ld,
            audit_context=_audit(m, [_skip(m)]) if where == "audit" else None,
            skipped_courses=[_skip(m)] if where == "explicit" else None,
        )

    got = _differential(tmp_path, scenario)
    assert got["outcome"][0] == "ValueError"
    assert got["files"] == {}


@pytest.mark.parametrize(
    "tamper",
    ["failed", "mismatched_result", "mismatched_calls", "no_tract_verified"],
)
def test_export_gate_rejects_identically(tmp_path, tamper):
    def scenario(impl, out):
        m = impl["m"]
        calls = _square(m)
        result = impl["verify"](calls)
        ld = None
        if tamper == "failed":
            result = result.model_copy(update={"warnings": ["bad"]})
        elif tamper == "mismatched_result":
            result = result.model_copy(update={"area_sq_ft": 1.0})
        elif tamper == "mismatched_calls":
            ld = m.LegalDescription(calls=_square(m, side=50.0))
        else:
            bad = result.model_copy(update={"warnings": ["bad"]})
            tract = m.Tract(
                label="A", tract_type=m.TractType.MAIN, role_basis="heading", calls=calls
            )
            return impl["export"](calls, bad, str(out / "d.csv"), tract_results=[(tract, bad)])
        return impl["export"](calls, result, str(out / "d.csv"), ld)

    got = _differential(tmp_path, scenario)
    assert got["outcome"][0] == "ValueError"
    assert got["files"] == {}


def test_raw_exports_and_stale_sidecar_cleanup_are_identical(tmp_path):
    def scenario(impl, out):
        m = impl["m"]
        for name in ("x_verified.verification.txt", "x_verified.metadata.txt"):
            (out / name).write_text("stale")
        impl["calls_to_csv"](_square(m) + [_curve(m, "spiral")], str(out / "x_verified.csv"))
        impl["ld_to_csv"](_legal_description(m, _square(m)), str(out / "ld.csv"))
        impl["calls_to_csv"](_square(m), str(out / "meta.csv"), {"source_doc": "a", "x": None})

    got = _differential(tmp_path, scenario)
    assert set(got["files"]) == {
        "x_verified.csv",
        "ld.csv",
        "ld.metadata.txt",
        "meta.csv",
        "meta.metadata.txt",
    }
    assert got["files"]["meta.csv"].splitlines()[0].decode().split(",") == (
        package_writer.FIELDNAMES
    )


def _csv_text(rows, header) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=header, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def _import_cases(m, to_row):
    rows = [to_row(c) for c in [*_square(m), _curve(m, "spiral", notes="stated")]]
    bad = [dict(r) for r in rows]
    bad[1]["distance_ft"] = "abc"
    bad[3]["course"] = ""
    return {
        "current": (_csv_text(rows, package_writer.FIELDNAMES), {}),
        "legacy": (_csv_text(rows, LEGACY_HEADER), {}),
        "strict_invalid": (_csv_text(bad, package_writer.FIELDNAMES), {}),
        "non_strict_unrecorded": (_csv_text(bad, package_writer.FIELDNAMES), {"strict": False}),
        "non_strict_recorded": (
            _csv_text(bad, package_writer.FIELDNAMES),
            {"strict": False, "rejected_rows": []},
        ),
    }


@pytest.mark.parametrize(
    "case",
    ["current", "legacy", "strict_invalid", "non_strict_unrecorded", "non_strict_recorded"],
)
@pytest.mark.parametrize("source", ["text", "file"])
def test_import_results_are_identical(tmp_path, case, source):
    outcomes = {}
    for impl, fns in IMPLS.items():
        text, kwargs = _import_cases(fns["m"], fns["to_row"])[case]
        try:
            if source == "text":
                calls = fns["read_text"](text, **kwargs)
            else:
                path = tmp_path / f"{impl}.csv"
                path.write_text(text)
                calls = fns["read_file"](str(path), **kwargs)
            outcomes[impl] = (
                "ok",
                [(c.model_dump(), sorted(c.model_fields_set)) for c in calls],
                kwargs.get("rejected_rows"),
            )
        except ValueError as exc:
            outcomes[impl] = ("ValueError", str(exc), repr(exc.__cause__)[:60])
    assert outcomes["monolith"] == outcomes["package"]
    if case == "non_strict_recorded":
        assert [n for n, _ in outcomes["package"][2]] == [3, 5]


def test_monolith_import_returns_monolith_models():
    text = _csv_text([CSVBuilder._call_to_row(c) for c in _square(monolith_models)], LEGACY_HEADER)
    calls = CSVBuilder.csv_text_to_calls(text)
    assert all(type(c) is monolith_models.DeedCall for c in calls)
    assert CSVBuilder.FIELDNAMES == package_writer.FIELDNAMES


# --- Delegation spies ----------------------------------------------------------


def test_csv_builder_delegates_to_package_writer(monkeypatch, tmp_path):
    seen: list[str] = []
    for name in (
        "export_verified_csv",
        "calls_to_csv",
        "legal_description_to_csv",
        "csv_text_to_calls",
        "csv_to_calls",
        "_call_to_row",
    ):
        real = getattr(package_writer, name)

        def spy(*args, _real=real, _name=name, **kwargs):
            seen.append(_name)
            return _real(*args, **kwargs)

        monkeypatch.setattr(package_writer, name, spy)

    m = monolith_models
    calls = _square(m)
    ld = _legal_description(m, calls)
    CSVBuilder.export_verified_csv(
        calls,
        ClosureChecker.verify_closure(calls, stated_area_sq_ft=10000.0),
        str(tmp_path / "a.csv"),
        ld,
    )
    CSVBuilder.calls_to_csv(calls, str(tmp_path / "b.csv"))
    CSVBuilder.legal_description_to_csv(ld, str(tmp_path / "c.csv"))
    CSVBuilder.csv_to_calls(str(tmp_path / "b.csv"))
    CSVBuilder.csv_text_to_calls((tmp_path / "b.csv").read_text())
    CSVBuilder._call_to_row(calls[0])
    assert set(seen) == {
        "export_verified_csv",
        "calls_to_csv",
        "legal_description_to_csv",
        "csv_text_to_calls",
        "csv_to_calls",
        "_call_to_row",
    }


# --- Legacy 21-column curve rows record the circular assumption ----------------


@pytest.mark.parametrize("impl", IMPLS)
def test_legacy_curved_row_notes_circular_assumption(impl):
    fns = IMPLS[impl]
    m = fns["m"]
    rows = [fns["to_row"](c) for c in [_curve(m, "spiral"), *_square(m, start=2)]]
    loaded = fns["read_text"](_csv_text(rows, LEGACY_HEADER))
    assert loaded[0].curve_type is None
    assert loaded[0].notes == LEGACY_NOTE
    # Straight legacy rows state no curve, so nothing is assumed about them.
    assert loaded[3].notes == "note, with comma"
    assert all(c.notes in (None, "note, with comma") for c in loaded[1:])


@pytest.mark.parametrize("impl", IMPLS)
def test_legacy_note_is_joined_to_existing_notes(impl):
    fns = IMPLS[impl]
    m = fns["m"]
    row = fns["to_row"](_curve(m, notes="per plat"))
    loaded = fns["read_text"](_csv_text([row], LEGACY_HEADER))
    assert loaded[0].notes == f"per plat; {LEGACY_NOTE}"


@pytest.mark.parametrize("impl", IMPLS)
def test_current_header_blank_curve_type_adds_no_note(impl):
    fns = IMPLS[impl]
    m = fns["m"]
    row = fns["to_row"](_curve(m))
    loaded = fns["read_text"](_csv_text([row], package_writer.FIELDNAMES))
    assert loaded[0].curve_type is None
    assert loaded[0].notes is None


@pytest.mark.parametrize("impl", IMPLS)
def test_legacy_note_survives_reexport_without_duplication(impl, tmp_path):
    fns = IMPLS[impl]
    m = fns["m"]
    row = fns["to_row"](_curve(m))
    first = fns["read_text"](_csv_text([row], LEGACY_HEADER))
    path = tmp_path / "again.csv"
    fns["calls_to_csv"](first, str(path))
    again = fns["read_file"](str(path))
    assert again[0].notes == LEGACY_NOTE
    # Re-importing the same legacy row text does not stack the note either.
    legacy_again = fns["read_text"](_csv_text([fns["to_row"](first[0])], LEGACY_HEADER))
    assert legacy_again[0].notes == LEGACY_NOTE
