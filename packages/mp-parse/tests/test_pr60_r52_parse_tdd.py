"""PR #60 round 52: adjoiner "along with" and structural sentence ends.

(Round 52 #1, generic encumbrance recitals, is in ``test_tract_classification_corpus``.)

2. "along with" inside a course before its destination is adjoiner wording ("THENCE
   along with the Northerly side of Main Street N 0° E 100 feet", "S 90° E 100 feet
   along with said road to a pin"). It is the conveyancing phrase only before a
   conveyancing object ("all improvements", "the hereditaments", "the right to ...")
   or opening a sentence of its own. A together-with deed clause never spans a THENCE.
3. A period before a paragraph break, a markdown heading or bullet, or an HTML tag ends
   its sentence, and a note's extent stops at a paragraph break or markdown/HTML
   structure even without a period: an unapplied exception never runs over the form
   after it.
"""

from __future__ import annotations

import pytest
from mp_models import unapplied_exceptions
from mp_parse import extract_calls
from mp_parse.metadata import breaks_at_period, ends_sentence, extract_deed_clauses

ALONG_WITH = (
    "BEGINNING at a pin; THENCE along with the Northerly side of Main Street "
    "N 0°00'00\" E 100 feet to a pin; THENCE S 90° E 100 feet along with said road to a "
    "pin; THENCE S 0° W 100 feet to a pin; THENCE N 90° W 100 feet to the point of "
    "beginning."
)
SQUARE = (
    "BEGINNING at a pin; thence N 0° E 100 feet to a pin; thence S 90° E 100 feet to a pin; "
    "thence S 0° W 100 feet to a pin; thence N 90° W 100 feet to the point of beginning."
)


# --- 2. adjoiner "along with" ----------------------------------------------------------


def test_along_with_inside_a_course_is_adjoiner_wording() -> None:
    calls, tracts = extract_calls(ALONG_WITH)
    assert not tracts
    assert [(c.along, c.to, c.distance_ft, c.notes) for c in calls] == [
        ("the Northerly side of Main Street", "a pin", 100.0, None),
        ("said road", "a pin", 100.0, None),
        (None, "a pin", 100.0, None),
        (None, "the point of beginning", 100.0, None),
    ]


def test_adjoiner_along_with_is_no_deed_clause() -> None:
    assert extract_deed_clauses(ALONG_WITH) == []


@pytest.mark.parametrize(
    "conveyance",
    [
        "along with all improvements thereon",
        "along with all the improvements thereon",
        "along with the hereditaments and appurtenances thereunto belonging",
        "along with appurtenances",
        "along with all rights of the grantor",
        "along with the right to use the driveway",
        "along with the privilege of passage",
        "along with all and singular the buildings",
        "along with the buildings thereon",
    ],
)
def test_along_with_a_conveyancing_object_is_conveyancing(conveyance: str) -> None:
    text = SQUARE[:-1] + "; " + conveyance + "."
    calls = extract_calls(text)[0]
    assert [(c.along, c.notes) for c in calls] == [(None, None)] * 4
    assert calls[-1].to == "the point of beginning"
    assert [(c.clause_type, c.text) for c in extract_deed_clauses(text)] == [
        ("together_with", conveyance)
    ]


def test_along_with_opening_its_own_sentence_after_the_closure_is_conveyancing() -> None:
    text = f"{SQUARE} Along with a ten foot wide driveway shared with Lot 6."
    calls = extract_calls(text)[0]
    assert [(c.along, c.notes) for c in calls] == [(None, None)] * 4
    assert [(c.clause_type, c.text) for c in extract_deed_clauses(text)] == [
        ("together_with", "Along with a ten foot wide driveway shared with Lot 6")
    ]


def test_together_with_clause_never_spans_a_thence() -> None:
    text = (
        "BEGINNING at a pin; thence N 0° E 100 feet to a pin, together with the right to "
        "use the driveway; thence S 90° E 100 feet to a pin; thence S 0° W 100 feet to a "
        "pin; thence N 90° W 100 feet to the point of beginning."
    )
    assert [(c.clause_type, c.text) for c in extract_deed_clauses(text)] == [
        ("together_with", "together with the right to use the driveway")
    ]


# --- 3. structural sentence ends ---------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "a spouse.\n\n### B. BLIND",
        "a spouse.\n\nnext paragraph",
        "a spouse. ### B. BLIND",
        "a spouse.\n- [ ] Grantor(s) legally blind.",
        "a spouse. - [ ] Grantor(s) legally blind.",
        "a spouse.</td></tr>",
        "a spouse. <tr><td>",
        "a spouse. | next cell |",
        "Main St.\n\n### B. BLIND",
    ],
)
def test_period_before_structure_ends_the_sentence(text: str) -> None:
    index = text.index(".")
    assert ends_sentence(text, index)
    assert breaks_at_period(text, index)


@pytest.mark.parametrize(
    "text",
    ["John A. Smith", "Main St. and", "1.5 feet", "a spouse. - and so on", "Lot No. # 5"],
)
def test_period_inside_a_sentence_still_does_not_end_it(text: str) -> None:
    assert not ends_sentence(text, text.index("."))


EXCEPTION = "except a portion previously conveyed to the county"
FORMS = {
    "markdown": "\n\n### B. BLIND (See Instruction #8)\n\n- [ ] Grantor(s) legally blind.*\n"
    "- [ ] One- or two-family residential premises.",
    "html": "</td></tr>\n</table>\n\n### B. BLIND (See Instruction #8)\n\n<table>\n  <tr><td>"
    "[ ] Grantor(s) legally blind.*</td></tr>",
}


@pytest.mark.parametrize("form", sorted(FORMS))
@pytest.mark.parametrize("period", [".", ""])
def test_unapplied_exception_stops_before_the_form_after_it(form: str, period: str) -> None:
    text = f"{SQUARE} No fee is due {EXCEPTION}{period}{FORMS[form]}"
    calls = extract_calls(text, strict=False, skipped_courses=[])[0]
    assert len(calls) == 4
    assert [w for c in calls for w in unapplied_exceptions(c.notes)] == [EXCEPTION]


@pytest.mark.parametrize("form", sorted(FORMS))
def test_conditional_except_in_a_form_is_not_an_exception(form: str) -> None:
    text = f"{SQUARE} Owners must all qualify except in the case of a spouse.{FORMS[form]}"
    calls = extract_calls(text, strict=False, skipped_courses=[])[0]
    assert len(calls) == 4
    assert [w for c in calls for w in unapplied_exceptions(c.notes)] == []


def test_along_with_after_the_closing_course_is_conveyancing() -> None:
    calls = extract_calls(SQUARE[:-1] + "; along with a shared driveway.")[0]
    assert [(c.along, c.notes) for c in calls] == [(None, None)] * 4
    assert calls[-1].to == "the point of beginning"
    # Adjoiner wording naming a line after the closure still fails closed.
    with pytest.raises(ValueError, match="not attached"):
        extract_calls(SQUARE[:-1] + "; along with the line of Smith.")
