"""Text after the closing course is not course material."""

import pytest
from mp_parse.calls import extract_calls
from mp_verify.closure import verify_closure

BASE = (
    "BEGINNING at a point; THENCE N 10°00'00\" E 100 feet; THENCE S 80°00'00\" E 100 feet; "
    "THENCE S 10°00'00\" W 100 feet; THENCE N 80°00'00\" W 100 feet to the point of beginning"
)
LIST = "(1) Rights of parties in possession, if any.\n(2) Easements of record."
NUMBERED = [
    f"{BASE}.\nSubject to the following:\n{LIST}",
    f"{BASE}. Subject to the following: (1) Rights of parties in possession, if any. "
    "(2) Easements of record.",
    f"{BASE}.\nTogether with the following:\n{LIST}",
    f"{BASE}.\nUnder and subject to:\n{LIST}",
    f"{BASE}.\nBEING the same premises as:\n{LIST}",
]


@pytest.mark.parametrize("text", NUMBERED)
@pytest.mark.parametrize("strict", [True, False])
def test_numbered_list_after_closing_course_is_not_courses(text, strict):
    skips = []
    calls, _ = extract_calls(text, strict=strict, skipped_courses=skips)
    assert len(calls) == 4
    assert skips == []
    assert verify_closure(calls).geometry_verified


def test_trailing_list_with_real_course_still_fails_closed():
    text = f"{BASE}.\nSubject to:\n(1) Easement N 45 E 50 feet.\n(2) Rights."
    with pytest.raises(ValueError, match="Malformed course"):
        extract_calls(text, strict=True)
    skips = []
    calls, _ = extract_calls(text, strict=False, skipped_courses=skips)
    assert len(calls) == 4
    assert len(skips) == 1
    assert not verify_closure(calls, skipped_courses=skips).geometry_verified


def test_numbered_courses_before_closing_course_unchanged():
    text = (
        "1. THENCE N 10°00'00\" E 100 feet\n2. THENCE S 80°00'00\" E 100 feet\n"
        "3. THENCE S 10 W 100 feet\n4. THENCE N 80°00'00\" W 100 feet "
        "to the point of beginning"
    )
    with pytest.raises(ValueError, match="Malformed course"):
        extract_calls(text, strict=True)


@pytest.mark.parametrize("strict", [True, False])
def test_form_text_after_point_and_place_of_beginning_is_not_courses(strict):
    text = (
        "BEGINNING at a point; THENCE\n(1) N 10°00'00\" E 100 feet to a point; thence\n"
        "(2) S 80°00'00\" E 100 feet to a point; thence\n(3) S 10°00'00\" W 100 feet to a point; thence\n"
        "(4) N 80°00'00\" W 100 feet to the point and place of beginning.\n\n"
        "Without limiting the foregoing, all covenants of record.\n"
        "TOTAL EXEMPTION FROM FEE (See Instruction #8) Deponent states east of nothing."
    )
    skips = []
    calls, _ = extract_calls(text, strict=strict, skipped_courses=skips)
    assert len(calls) == 4
    assert skips == []
