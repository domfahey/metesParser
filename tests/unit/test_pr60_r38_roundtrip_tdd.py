"""PR #60 round 38: the cardinal-vs-chord conflict survives a CSV round trip.

``is_indefinite`` is not a CSV column, so verification must re-derive a cardinal
word/chord conflict from persisted fields even when chord and sweep determine the
direction. Rejected CSV rows are reported by the physical line where the record starts.
"""

from __future__ import annotations

import pytest
from mp_export.csv_writer import _call_to_row, csv_text_to_calls
from mp_parse.calls import extract_calls
from mp_verify import verify_closure
from mp_verify.traverse import analyze_courses, effective_indefinite

TEXT = (
    "THENCE northeasterly along a curve to the right having a radius of 100 feet, "
    "an arc length of 50 feet, a chord bearing of S 10° W and a chord of 49.74 feet"
)


def _csv(calls):
    import csv
    import io

    from mp_export.csv_writer import FIELDNAMES

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDNAMES, lineterminator="\n")
    w.writeheader()
    for c in calls:
        w.writerow(_call_to_row(c))
    return buf.getvalue()


def test_cardinal_chord_conflict_survives_csv_round_trip():
    parsed = extract_calls(TEXT, strict=False)[0]
    assert parsed and effective_indefinite(parsed[0])
    reread = csv_text_to_calls(_csv(parsed))
    assert reread[0].is_indefinite is False
    assert effective_indefinite(reread[0]) is True
    assert analyze_courses(reread)[1][0].direction_conflict is True
    a = verify_closure(parsed).warnings
    b = verify_closure(reread).warnings
    assert a == b


def test_consistent_cardinal_is_not_a_conflict():
    text = TEXT.replace("northeasterly", "southwesterly")
    parsed = extract_calls(text, strict=False)[0]
    reread = csv_text_to_calls(_csv(parsed))
    assert not effective_indefinite(parsed[0])
    assert not effective_indefinite(reread[0])


def test_rejected_row_reports_physical_line_after_multiline_cell():
    good = _csv(extract_calls("THENCE N 10° E 100 feet", strict=False)[0])
    header, row, *_ = good.splitlines()
    cells = row.split(",")
    notes = header.split(",").index("notes")
    multi = list(cells)
    multi[notes] = '"a\nb\nc"'
    bad = ",".join(cells[:-1])  # wrong width
    text = "\n".join([header, ",".join(multi), bad]) + "\n"
    rejected: list[tuple[int, str]] = []
    csv_text_to_calls(text, strict=False, rejected_rows=rejected)
    # header line 1; first record starts line 2 and spans 3 lines; bad record starts line 5.
    assert [n for n, _ in rejected] == [5]
    with pytest.raises(ValueError, match=r"invalid CSV row 5"):
        csv_text_to_calls(text)
