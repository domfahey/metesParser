"""PR #60 round 39: spiral chord positioning agrees with verification; clean curve errors."""

from __future__ import annotations

import csv
import io

import pytest
from mp_export.csv_writer import FIELDNAMES, _call_to_row, csv_text_to_calls
from mp_parse.calls import extract_calls
from mp_verify import verify_closure
from mp_verify.traverse import effective_indefinite

SPIRAL = (
    "THENCE along a spiral curve to the right having a length of 100 feet, "
    "a chord bearing of N 45° E and a chord of 99.9 feet"
)
CHORD_ONLY = (
    "THENCE along a curve to the right having a radius of 100 feet, "
    "a chord bearing of N 45° E and a chord of 99.9 feet"
)
SQUARE_REST = [
    "THENCE S 45° E 100 feet",
    "THENCE S 45° W 100 feet",
    "THENCE N 45° W 100 feet",
]


def _csv(calls):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDNAMES, lineterminator="\n")
    w.writeheader()
    for c in calls:
        w.writerow(_call_to_row(c))
    return buf.getvalue()


@pytest.mark.parametrize("first", [SPIRAL, CHORD_ONLY])
def test_chord_positioned_text_and_csv_paths_agree(first):
    parsed = extract_calls(" ".join([first, *SQUARE_REST]), strict=False)[0]
    assert len(parsed) == 4
    reread = csv_text_to_calls(_csv(parsed))
    assert parsed[0].is_indefinite is False
    assert parsed[0].is_indefinite == reread[0].is_indefinite
    assert effective_indefinite(parsed[0]) == effective_indefinite(reread[0])
    assert not effective_indefinite(parsed[0])
    assert verify_closure(parsed).warnings == verify_closure(reread).warnings
    assert not any("indefinite" in w for w in verify_closure(parsed).warnings)


NO_DIRECTION = (
    "THENCE along a curve concave to the north having a radius of 100 feet "
    "and an arc length of 50 feet"
)


def test_missing_curve_direction_strict_raises_clean_error():
    with pytest.raises(ValueError, match=r"Malformed course 1") as info:
        extract_calls(NO_DIRECTION, strict=True)
    msg = str(info.value)
    assert "curve direction" in msg
    assert "validation error" not in msg.lower()
    assert "pydantic" not in msg.lower()


def test_missing_curve_direction_non_strict_records_clean_skip():
    skipped = []
    calls, *_ = extract_calls(NO_DIRECTION, strict=False, skipped_courses=skipped)
    assert calls == []
    assert len(skipped) == 1
    assert skipped[0].error_type != "ValidationError"
    assert "curve direction" in skipped[0].error
    assert "validation error" not in skipped[0].error.lower()
