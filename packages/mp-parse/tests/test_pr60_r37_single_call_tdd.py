"""extract_single_call returns None only for BEGINNING clauses; strip widths use shared grammar."""

from __future__ import annotations

import pytest
from mp_parse.calls import extract_calls, extract_single_call
from mp_parse.metadata import detect_strip_exceptions, remove_strip_exceptions


def test_unread_length_raises() -> None:
    with pytest.raises(ValueError, match="No usable course"):
        extract_single_call("thence to a point 100 feet", 1)


@pytest.mark.parametrize(
    "text", ["thence N 95° E 100 feet to a point", "thence N 95-30' E 100 feet to a point"]
)
def test_out_of_range_bearing_forms_are_consistent(text: str) -> None:
    call = extract_single_call(text, 1)
    assert call is not None
    assert call.bearing_azimuth_deg_from_north is None
    assert "incomplete bearing" in call.notes


@pytest.mark.parametrize("text", ["BEGINNING at a point", "commencing at a stone", "POB"])
def test_beginning_clauses_return_none(text: str) -> None:
    assert extract_single_call(text, 1) is None


def test_extract_calls_still_fails_closed_on_unusable_course() -> None:
    text = "thence N 10° E 100 feet to a point; thence to a point 100 feet"
    with pytest.raises(ValueError, match="Malformed course"):
        extract_calls(text, strict=True)
    skipped: list = []
    calls, _ = extract_calls(text, strict=False, skipped_courses=skipped)
    assert len(calls) == 1 and len(skipped) == 1


@pytest.mark.parametrize(
    ("text", "width"),
    [
        ("except the East 20 1/2 feet thereof", 20.5),
        ("except the North 1,200 feet", 1200.0),
        ("except the South 30 feet thereof", 30.0),
    ],
)
def test_strip_widths_use_shared_number_grammar(text: str, width: float) -> None:
    found = detect_strip_exceptions(text)
    assert [item["width_ft"] for item in found] == [width]
    assert "except" not in remove_strip_exceptions(text).lower()
