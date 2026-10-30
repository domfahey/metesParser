"""PR #60 round 36: CSV import validates the header itself.

``csv_text_to_calls`` / ``csv_to_calls`` accept the exact current 22-field header or the
legacy 21-field header; any other header (e.g. only four columns) is rejected with a
ValueError naming missing and unexpected columns, for the package, the monolith
``CSVBuilder`` facade and the ``metesparser verify`` CLI. Tract/skip helpers are
computed once per export, not per tract.
"""

from __future__ import annotations

import mp_export.csv_writer as package_writer
import pytest

from metesparser.csv_builder import CSVBuilder

PARTIAL = (
    "course,direction_text,bearing_azimuth_deg_from_north,distance_ft\n"
    "1,N 0 E,0,100\n2,N 90 E,90,100\n3,S 0 E,180,100\n4,S 90 W,270,100\n"
)


def _impls():
    return {
        "package": (package_writer.csv_text_to_calls, package_writer.csv_to_calls),
        "monolith": (CSVBuilder.csv_text_to_calls, CSVBuilder.csv_to_calls),
    }


@pytest.mark.parametrize("name", ["package", "monolith"])
def test_partial_column_csv_is_rejected_naming_columns(name, tmp_path):
    from_text, from_file = _impls()[name]
    with pytest.raises(ValueError, match="missing") as err:
        from_text(PARTIAL)
    assert "curve_type" in str(err.value)
    path = tmp_path / "p.csv"
    path.write_text(PARTIAL)
    with pytest.raises(ValueError, match="missing"):
        from_file(str(path))


@pytest.mark.parametrize("name", ["package", "monolith"])
def test_unexpected_and_reordered_columns_are_rejected(name):
    from_text, _ = _impls()[name]
    header = [*package_writer.FIELDNAMES, "surprise"]
    with pytest.raises(ValueError, match="unexpected.*surprise"):
        from_text(",".join(header) + "\n")
    swapped = list(package_writer.FIELDNAMES)
    swapped[0], swapped[1] = swapped[1], swapped[0]
    with pytest.raises(ValueError, match="order"):
        from_text(",".join(swapped) + "\n")


@pytest.mark.parametrize("name", ["package", "monolith"])
def test_current_and_legacy_headers_are_accepted(name):
    from_text, _ = _impls()[name]
    assert from_text(",".join(package_writer.FIELDNAMES) + "\n") == []
    assert from_text(",".join(package_writer.LEGACY_FIELDNAMES) + "\n") == []


def test_cli_verify_rejects_partial_column_csv(tmp_path):
    from metesparser.cli import verify_command

    path = tmp_path / "partial.csv"
    path.write_text(PARTIAL)
    with pytest.raises(SystemExit) as failure:
        verify_command(str(path))
    assert failure.value.code == 1


def test_known_tracts_and_skips_computed_once(monkeypatch, tmp_path):
    from mp_models import DeedCall, LegalDescription, Tract
    from mp_verify import verify_closure

    def square():
        return [
            DeedCall(
                course=i + 1,
                direction_text=text,
                bearing_azimuth_deg_from_north=float(az),
                distance_ft=100.0,
            )
            for i, (az, text) in enumerate(
                [(0, "N 0 E"), (90, "N 90 E"), (180, "S 0 E"), (270, "S 90 W")]
            )
        ]

    tracts = [Tract(label=f"T{i}", tract_type="main", calls=square()) for i in (1, 2)]
    legal = LegalDescription(calls=tracts[0].calls, tracts=tracts)
    results = [(t, verify_closure(t.calls)) for t in tracts]
    n = {"known": 0, "skips": 0}
    orig_known, orig_skips = package_writer._known_tracts, package_writer._labelled_skips

    def known(*a, **k):
        n["known"] += 1
        return orig_known(*a, **k)

    def skips(*a, **k):
        n["skips"] += 1
        return orig_skips(*a, **k)

    monkeypatch.setattr(package_writer, "_known_tracts", known)
    monkeypatch.setattr(package_writer, "_labelled_skips", skips)
    package_writer.export_verified_csv(
        legal.calls,
        results[0][1],
        str(tmp_path / "o.csv"),
        legal_desc=legal,
        tract_results=results,
    )
    assert n == {"known": 1, "skips": 1}
