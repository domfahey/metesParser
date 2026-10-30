"""Round 20: enumerated courses run inline after a course-list header are split.

'THENCE the following four courses and distances: (1) ...; (2) ...' on one line
must yield every numbered course, never just the first. Enumerators split only
as a sequence starting at 1 and rising by 1 after a header or THENCE; a header
count that disagrees with the courses found is flagged, never silently accepted.
"""

from __future__ import annotations

import pytest

from metesparser.call_extractor import CallExtractor
from tests.fixtures.package_parser import extract_calls as package_extract_calls

EXTRACTORS = {"package": package_extract_calls, "monolith": CallExtractor.extract_calls}
IMPLS = sorted(EXTRACTORS)
STRICT = pytest.mark.parametrize("strict", [True, False], ids=["strict", "non-strict"])

HEADER = "THENCE the following four courses and distances:"
INLINE = (
    "BEGINNING at a point; " + HEADER + " (1) due North 100.00 feet; (2) due East 100.00 feet; "
    "(3) due South 100.00 feet; (4) due West 100.00 feet to the point of beginning."
)


def _run(impl, text, strict):
    skipped: list = []
    calls = EXTRACTORS[impl](text, strict=strict, skipped_courses=skipped)
    return calls, skipped


@pytest.mark.parametrize("impl", IMPLS)
@STRICT
def test_inline_parenthesised_courses_after_header_are_all_extracted(impl, strict):
    calls, skipped = _run(impl, INLINE, strict)
    assert [c.course for c in calls] == [1, 2, 3, 4]
    assert [c.distance_ft for c in calls] == [100.0] * 4
    assert [c.bearing_azimuth_deg_from_north for c in calls] == [0.0, 90.0, 180.0, 270.0]
    assert skipped == []


@pytest.mark.parametrize("impl", IMPLS)
@STRICT
def test_newline_separated_variant_is_unchanged(impl, strict):
    text = INLINE.replace("; (", ";\n(").replace(": (1)", ":\n(1)")
    calls, skipped = _run(impl, text, strict)
    assert [c.course for c in calls] == [1, 2, 3, 4]
    assert skipped == []


@pytest.mark.parametrize("impl", IMPLS)
@STRICT
@pytest.mark.parametrize("style", ["{n})", "{n}."], ids=["paren-right", "dot"])
def test_other_enumerator_styles_inline(impl, strict, style):
    text = INLINE
    for n in range(1, 5):
        text = text.replace(f"({n})", style.format(n=n))
    calls, skipped = _run(impl, text, strict)
    assert [c.course for c in calls] == [1, 2, 3, 4]
    assert [c.distance_ft for c in calls] == [100.0] * 4
    assert skipped == []


@pytest.mark.parametrize("impl", IMPLS)
@STRICT
def test_ordinal_words_inline(impl, strict):
    text = (
        "BEGINNING at a point; THENCE the following two courses and distances: "
        "First, due North 100.00 feet; Second, due East 100.00 feet to the point of beginning."
    )
    calls, skipped = _run(impl, text, strict)
    assert [c.course for c in calls] == [1, 2]
    assert skipped == []


@pytest.mark.parametrize("impl", IMPLS)
def test_header_count_mismatch_raises_in_strict(impl):
    text = INLINE.replace("four courses", "five courses")
    with pytest.raises(ValueError, match="five|5"):
        EXTRACTORS[impl](text, strict=True, skipped_courses=[])


@pytest.mark.parametrize("impl", IMPLS)
@pytest.mark.parametrize("word", ["five", "three", "5", "three (3)"])
def test_header_count_mismatch_is_flagged_non_strict(impl, word):
    text = INLINE.replace("four courses", f"{word} courses")
    calls, skipped = _run(impl, text, False)
    assert [c.course for c in calls] == [1, 2, 3, 4]
    assert [s.error_type for s in skipped] == ["CourseCountMismatch"]
    assert skipped[0].course == 5
    assert "4" in skipped[0].error


@pytest.mark.parametrize("impl", IMPLS)
def test_header_count_mismatch_without_sink_raises_non_strict(impl):
    text = INLINE.replace("four courses", "five courses")
    with pytest.raises(ValueError):
        EXTRACTORS[impl](text, strict=False)


@pytest.mark.parametrize("impl", IMPLS)
@STRICT
def test_matching_count_and_uncounted_header_are_not_flagged(impl, strict):
    for header in (HEADER, HEADER.replace("four ", ""), HEADER.replace("four", "four (4)")):
        calls, skipped = _run(impl, INLINE.replace(HEADER, header), strict)
        assert len(calls) == 4 and skipped == []


@pytest.mark.parametrize("impl", IMPLS)
@STRICT
@pytest.mark.parametrize(
    "text",
    [
        "BEGINNING at a point; THENCE due North 100.00 feet along Lot (2) to a stake; "
        "THENCE due East 50.00 feet to a pipe.",
        "BEGINNING at a point; THENCE due North 100.00 feet (Tax ID 12-34) to a stake; "
        "THENCE due East 50.00 feet to a pipe.",
        "BEGINNING at a point; THENCE due North 100.00 feet (100.00 feet) to a stake; "
        "THENCE due East 50.00 feet to a pipe.",
        "BEGINNING at a point; THENCE due North 100.00 feet along Lot (1) and (2) to a stake; "
        "THENCE due East 50.00 feet to a pipe.",
    ],
    ids=["lot", "tax-id", "paren-distance", "lot-1-and-2"],
)
def test_non_enumerator_parentheticals_do_not_split(impl, strict, text):
    calls, skipped = _run(impl, text, strict)
    assert [c.course for c in calls] == [1, 2]
    assert [c.distance_ft for c in calls] == [pytest.approx(100.0), pytest.approx(50.0)]
    assert skipped == []


@pytest.mark.parametrize("impl", IMPLS)
@STRICT
def test_out_of_sequence_numbers_after_header_do_not_split(impl, strict):
    text = (
        "BEGINNING at a point; THENCE the following courses and distances: "
        "due North 100.00 feet along Lot (2) to a stake; THENCE due East 50.00 feet to a pipe."
    )
    calls, _ = _run(impl, text, strict)
    assert [c.distance_ft for c in calls] == [pytest.approx(100.0), pytest.approx(50.0)]
