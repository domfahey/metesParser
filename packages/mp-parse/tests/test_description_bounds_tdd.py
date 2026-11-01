"""The course region of a description: preamble and trailing text are not courses.

A tract's courses start at the first fragment stating a complete course (or right
after its BEGINNING/COMMENCING block) and end at the closing course, the fragment
returning to the point of beginning anywhere in its text. Text outside that
region is not course material unless it states a complete course, which still
fails closed.
"""

import pytest
from mp_parse.calls import _states_complete_course, extract_calls
from mp_parse.metadata import extract_distance
from mp_verify.closure import verify_closure

COURSES = (
    "1) Along Elm Street, N 10°00'00\" E, a distance of 100.00 feet to a point; thence\n"
    "2) Along Lot 3, S 80°00'00\" E, a distance of 100.00 feet to a point; thence\n"
    "3) Along Lot 4, S 10°00'00\" W, a distance of 100.00 feet to a point; thence\n"
    "4) Along Oak Road, N 80°00'00\" W, a distance of 100.00 feet to the point and place "
    "of beginning."
)
BEGINNING = "BEGINNING at the corner of Elm Street and Oak Road; thence\n"
# The same courses separated only by THENCE.
THENCE_COURSES = "".join(line.split(") ", 1)[1] + "\n" for line in COURSES.splitlines())
# Recording-office cover sheet text before the description, as OCR'd markdown.
COVER = (
    '<th>Recording thence colspan="2">Official Use Only</th> <td>Recording Fee</td> '
    "<td>$83.00</td> <td>No. of Pages</td> <td>5</td> Block No. 129, Lot No. 2. "
    "The legal description is attached hereto\n"
)
# Affidavit text following the closing course in the same fragment and after it.
AFFIDAVIT = (
    " BEING COMMONLY KNOWN AS 20 E. Redman Avenue, Haddonfield, NJ\n"
    "thence PARTY OR LEGAL REPRESENTATIVE (See Instructions # 3 and #4 on reverse side) "
    "Deponent, being duly sworn according to law upon his/her oath, deposes and says "
    "that he/she is the S 2 party; thence FULL EXEMPTION FROM FEE (See Instruction #6 on "
    "reverse side) Deponent states that this deed transaction is fully exempt."
)


def _extract(text: str, strict: bool):
    skips: list = []
    calls, tracts = extract_calls(text, strict=strict, skipped_courses=skips)
    return calls, tracts, skips


def _closes(calls, skips) -> bool:
    return verify_closure(calls, skipped_courses=skips).is_fully_verified()


@pytest.mark.parametrize("strict", [True, False])
class TestClosingFragmentWithTrailingText:
    def test_trailing_text_in_the_closing_fragment_ends_the_description(self, strict):
        calls, _, skips = _extract(BEGINNING + THENCE_COURSES + AFFIDAVIT, strict)
        assert [c.course for c in calls] == [1, 2, 3, 4]
        assert skips == []
        assert _closes(calls, skips)

    def test_closing_fragment_is_cut_at_the_closing_sentence(self, strict):
        calls, _, _ = _extract(BEGINNING + THENCE_COURSES + AFFIDAVIT, strict)
        assert "COMMONLY KNOWN" not in (calls[-1].to or "")
        assert "Deponent" not in (calls[-1].to or "")

    def test_real_course_after_the_closing_sentence_still_fails_closed(self, strict):
        text = (
            BEGINNING
            + THENCE_COURSES.rstrip()
            + " The drive then runs N 45°00'00\" E 50.00 feet beyond."
        )
        # The cut-off remainder is kept as a fifth course, so the tract fails closure.
        calls, _, skips = _extract(text, strict)
        assert len(calls) + len(skips) == 5
        assert calls[3].to == "the point and place of beginning"
        assert not _closes(calls, skips)


@pytest.mark.parametrize("strict", [True, False])
class TestPreambleBeforeTheFirstCourse:
    def test_cover_sheet_before_numbered_courses_is_not_a_course(self, strict):
        calls, _, skips = _extract(COVER + COURSES, strict)
        assert [c.course for c in calls] == [1, 2, 3, 4]
        assert skips == []
        assert _closes(calls, skips)

    def test_cover_sheet_and_trailing_affidavit_together(self, strict):
        calls, _, skips = _extract(COVER + THENCE_COURSES + AFFIDAVIT, strict)
        assert [c.course for c in calls] == [1, 2, 3, 4]
        assert skips == []
        assert _closes(calls, skips)

    def test_preamble_stating_a_complete_course_still_fails_closed(self, strict):
        text = "Recital thence the lot fronts N 45°00'00\" E 50.00 feet on Main Street\n" + COURSES
        # Stated before the first course, it is still course material: kept as a
        # course (or a skip) so the description does not verify.
        calls, _, skips = _extract(text, strict)
        assert len(calls) + len(skips) == 5
        assert calls[0].course == 1 or skips[0].course == 1
        assert not _closes(calls, skips)

    def test_malformed_course_after_beginning_still_fails_closed(self, strict):
        text = (
            "BEGINNING at a stake; THENCE along the creek to a stone; "
            "THENCE N 10°00'00\" E 100 feet; THENCE S 80°00'00\" E 100 feet; "
            "THENCE S 10°00'00\" W 100 feet; THENCE N 80°00'00\" W 100 feet "
            "to the point of beginning."
        )
        if strict:
            with pytest.raises(ValueError, match="Malformed course 1"):
                extract_calls(text, strict=True)
            return
        calls, _, skips = _extract(text, strict)
        assert [s.course for s in skips] == [1]
        assert not _closes(calls, skips)


@pytest.mark.parametrize(
    "distance",
    [
        "3 US survey feet",
        "2 engineer chains",
        "15 engineer links",
        "2 arpents",
        "4 toises",
        "1 furlong",
        "12.5 metres",
        "40 rods",
        "5 perch",
    ],
)
def test_complete_course_reads_every_supported_unit(distance):
    assert _states_complete_course(f"N 45 E {distance}")


def test_bearing_minutes_are_not_a_course_distance():
    assert not _states_complete_course("bearing N 45°30' E along the fence")


@pytest.mark.parametrize(
    ("text", "expected"), [("5 perch", (5.0, "perches")), ("5 perches", (5.0, "perches"))]
)
def test_singular_perch_is_a_length_unit(text, expected):
    assert extract_distance(f"N 45 E {text} to a stone") == expected
