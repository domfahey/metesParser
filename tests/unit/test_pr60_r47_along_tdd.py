"""PR #60 round 47: along/notes never duplicate or damage source wording, in any word order."""

from __future__ import annotations

import itertools
import re

import pytest
from mp_parse.calls import extract_calls

from metesparser.call_extractor import CallExtractor

BEARING = "N 45° E"
LENGTH = "100 feet"
RECORD = "(deed N 44° E 101 feet)"
MEASURED = "(measured 100 feet)"
PAREN = "(a 10 foot easement)"
WIDE = "(50 feet wide)"
PASSING = "(passing a pin at 50 feet)"
PASSING_PLAIN = ", passing a pin at 50 feet,"
ALONG = "the line of Smith"

ORDERS = {
    "along-bearing-length": "thence along {a} {b} {l}{x} to a pin",
    "bearing-along-length": "thence {b} along {a} {l}{x} to a pin",
    "bearing-length-along": "thence {b} {l} along {a}{x} to a pin",
}
EXTRAS = {
    "record": RECORD,
    "paren": PAREN,
    "wide": WIDE,
    "passing": PASSING,
    "passing-plain": PASSING_PLAIN,
}


def _text(order: str, extras: tuple[str, ...]) -> str:
    extra = "".join(e if e.startswith(",") else " " + e for e in (EXTRAS[n] for n in extras))
    return ORDERS[order].format(a=ALONG, b=BEARING, l=LENGTH, x=extra)


def _call(text: str):
    calls = extract_calls("BEGINNING at a pin; " + text + ".", strict=False)
    calls = calls[0] if isinstance(calls, tuple) else calls
    assert len(calls) == 1, text
    return calls[0]


def _balanced(text: str) -> bool:
    depth = 0
    for char in text:
        depth += char in "(["
        depth -= char in ")]"
        if depth < 0:
            return False
    return depth == 0


def _groups(text: str) -> list[str]:
    return re.findall(r"\(([^()]*)\)", text)


def test_passing_bracket_ends_at_its_closing_bracket() -> None:
    call = _call(f"thence along {ALONG} {BEARING} {LENGTH} {PASSING} to a pin")
    assert call.along == ALONG
    assert call.to == "a pin"
    assert call.notes == "passing call: passing a pin at 50 feet"


def test_record_call_is_not_part_of_along_when_along_leads() -> None:
    call = _call(f"thence along {ALONG} {BEARING} {LENGTH} {RECORD} to a pin")
    assert call.along == ALONG
    assert call.notes == f"record call: {RECORD}"


@pytest.mark.parametrize("order", list(ORDERS))
def test_record_and_passing_leave_along_in_every_order(order: str) -> None:
    for name in ("record", "passing"):
        call = _call(_text(order, (name,)))
        assert call.along == ALONG, (order, name, call.along)


@pytest.mark.parametrize("order", list(ORDERS))
def test_word_order_does_not_change_along_or_notes(order: str) -> None:
    for names in itertools.chain.from_iterable(
        itertools.combinations(EXTRAS, size) for size in (1, 2)
    ):
        if sum(name.startswith("passing") for name in names) > 1:
            continue
        call = _call(_text(order, names))
        base = _call(_text("bearing-length-along", names))
        assert (call.along, call.to, sorted((call.notes or "").split("; "))) == (
            base.along,
            base.to,
            sorted((base.notes or "").split("; ")),
        ), (order, names)


@pytest.mark.parametrize("order", list(ORDERS))
def test_no_wording_is_duplicated_or_damaged(order: str) -> None:
    for size in (0, 1, 2, 3):
        for names in itertools.combinations(EXTRAS, size):
            if sum(name.startswith("passing") for name in names) > 1:
                continue
            text = _text(order, names)
            call = _call(text)
            along, to, notes = call.along or "", call.to or "", call.notes or ""
            where = (text, along, to, notes)
            assert _balanced(along) and _balanced(to), where
            assert not along.endswith(("(", "[")), where
            parts = [
                re.sub(r"^(?:record call|passing call|parenthetical): ", "", p)
                for p in notes.split("; ")
                if p
            ]
            for part in parts:
                wording = part.strip("()")
                assert not (wording and wording in along), where
            for group in _groups(text):
                found = "\x00".join((along, to, notes)).count(group)
                assert found == 1, (group, found, *where)


def test_monolith_facade_matches_package() -> None:
    text = f"BEGINNING at a pin; thence along {ALONG} {BEARING} {LENGTH} {PASSING} to a pin."
    call = CallExtractor.extract_calls(text)[0]
    assert (call.along, call.notes) == (ALONG, "passing call: passing a pin at 50 feet")


@pytest.mark.parametrize(
    "text",
    [
        f"thence {BEARING} {MEASURED} along {ALONG} to a pin",
        f"thence along {ALONG} {MEASURED} {BEARING} to a pin",
        f"thence {BEARING} along {ALONG} {MEASURED} to a pin",
    ],
)
def test_measured_length_is_the_course_not_along_in_any_order(text: str) -> None:
    call = _call(text)
    assert (call.along, call.distance_ft) == (ALONG, 100.0)


def test_bracket_with_other_wording_and_passing_is_noted_once() -> None:
    text = f"thence along {ALONG} {BEARING} {LENGTH} (see plan, passing a pin at 50 feet) to a pin"
    call = _call(text)
    assert call.along == ALONG
    assert call.notes == "passing call: see plan, passing a pin at 50 feet"


def test_passing_after_qualifier_is_not_in_along() -> None:
    call = _call(f"thence {BEARING} parallel to {ALONG} {LENGTH}{PASSING_PLAIN} to a pin")
    assert call.along == f"parallel to {ALONG}"
    assert call.notes == "passing call: passing a pin at 50 feet"
