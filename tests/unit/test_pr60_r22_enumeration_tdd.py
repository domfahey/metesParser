"""Round 22: one course-list header grammar, robust and linear enumeration detection.

A course-list header ('THENCE [along ...] the following [N] courses [and distances]
[along ...][, to wit | viz]:') is recognized by one shared grammar for both header
removal and enumeration detection, so every enumerated course is extracted with
the deed's numbering. Ordinal words enumerate only as a sequence of two or more
starting at First after a real header; THENCE inside a course outside the list
is never re-split; a counted header without its enumeration is flagged, never
silently accepted; and detection runs once per tract in linear time.
"""

from __future__ import annotations

import time

import mp_parse.metadata as package_metadata
import pytest
from mp_parse.metadata import analyze_course_lists as package_analyze
from mp_parse.metadata import split_into_calls as package_split

import metesparser.text_parser as monolith_text_parser
from metesparser.call_extractor import CallExtractor
from metesparser.text_parser import TextParser
from metesparser.text_parser import analyze_course_lists as monolith_analyze
from tests.fixtures.package_parser import extract_calls as package_extract_calls

EXTRACTORS = {"package": package_extract_calls, "monolith": CallExtractor.extract_calls}
SPLITTERS = {"package": package_split, "monolith": TextParser.split_into_calls}
ANALYZERS = {"package": package_analyze, "monolith": monolith_analyze}
MODULES = {"package": package_metadata, "monolith": monolith_text_parser}
IMPLS = sorted(EXTRACTORS)
STRICT = pytest.mark.parametrize("strict", [True, False], ids=["strict", "non-strict"])

HEADERS = {
    "plain": "THENCE the following four courses and distances:",
    "tail-along": "THENCE the following four courses and distances along said road:",
    "lead-along": "THENCE along said road the following four courses and distances:",
    "to-wit": "THENCE the following four courses and distances, to wit:",
    "viz": "THENCE the following four courses, viz:",
    "by-paren-count": "THENCE by the following four (4) courses and distances;",
    "with-calls": "THENCE with the line of lands of Smith, the following 4 calls:",
    "lines": "THENCE along Route 9 the following four lines:",
    "uncounted": "THENCE the following courses and distances:",
}
STYLES = {
    "paren": lambda n: f"({n})",
    "paren-right": lambda n: f"{n})",
    "dot": lambda n: f"{n}.",
    "ordinal": lambda n: ["First,", "Second,", "Third,", "Fourth,"][n - 1],
}
COURSES = ["due North 100.00 feet", "due East 100.00 feet", "due South 100.00 feet"]
LAST = "due West 100.00 feet to the point of beginning."


def _inline(header: str, style) -> str:
    body = "; ".join(f"{style(n)} {course}" for n, course in enumerate(COURSES, start=1))
    return f"BEGINNING at a point; {header} {body}; {style(4)} {LAST}"


def _run(impl, text, strict):
    skipped: list = []
    calls = EXTRACTORS[impl](text, strict=strict, skipped_courses=skipped)
    return calls, skipped


@pytest.mark.parametrize("impl", IMPLS)
@STRICT
@pytest.mark.parametrize("style", sorted(STYLES))
@pytest.mark.parametrize("header", sorted(HEADERS))
def test_every_header_variant_and_enumerator_style_yields_all_courses(impl, strict, style, header):
    calls, skipped = _run(impl, _inline(HEADERS[header], STYLES[style]), strict)
    assert [c.course for c in calls] == [1, 2, 3, 4]
    assert [c.bearing_azimuth_deg_from_north for c in calls] == [0.0, 90.0, 180.0, 270.0]
    assert [c.distance_ft for c in calls] == [100.0] * 4
    assert skipped == []


@pytest.mark.parametrize("impl", IMPLS)
@STRICT
@pytest.mark.parametrize("style", sorted(STYLES))
@pytest.mark.parametrize("header", sorted(HEADERS))
def test_header_variants_with_newline_courses(impl, strict, style, header):
    enumerator = STYLES[style]
    body = "\n".join(f"{enumerator(n)} {c};" for n, c in enumerate(COURSES, start=1))
    text = f"BEGINNING at a point;\n{HEADERS[header]}\n{body}\n{enumerator(4)} {LAST}"
    calls, skipped = _run(impl, text, strict)
    assert [c.course for c in calls] == [1, 2, 3, 4]
    assert skipped == []


# --- finding 1: header with a trailing qualifier ----------------------------------


@pytest.mark.parametrize("impl", IMPLS)
@STRICT
def test_trailing_qualifier_header_keeps_inline_course_two(impl, strict):
    text = (
        "BEGINNING at a point; THENCE the following three courses and distances along said "
        "road: (1) due North 100.00 feet; (2) North 90 degrees East 50.00 feet; "
        "(3) due South 100.00 feet to a point; THENCE due West 50.00 feet to the beginning."
    )
    calls, skipped = _run(impl, text, strict)
    assert [(c.course, c.bearing_azimuth_deg_from_north, c.distance_ft) for c in calls] == [
        (1, 0.0, 100.0),
        (2, 90.0, 50.0),
        (3, 180.0, 100.0),
        (4, 270.0, 50.0),
    ]
    assert skipped == []


# --- finding 2: header removal and enumeration share one grammar --------------------


@pytest.mark.parametrize("impl", IMPLS)
@STRICT
def test_leading_qualifier_header_is_a_marker_not_course_one(impl, strict):
    text = (
        "BEGINNING at a point; THENCE due North 100.00 feet to a stake; "
        "THENCE along said road the following two courses and distances: "
        "(1) due East 50.00 feet; (2) due South 100.00 feet to a pipe; "
        "THENCE due West 50.00 feet to the point of beginning."
    )
    calls, skipped = _run(impl, text, strict)
    assert [c.course for c in calls] == [1, 2, 3, 4]
    assert [c.bearing_azimuth_deg_from_north for c in calls] == [0.0, 90.0, 180.0, 270.0]
    assert skipped == []


@pytest.mark.parametrize("impl", IMPLS)
@pytest.mark.parametrize("header", sorted(HEADERS))
def test_every_header_is_a_course_list_marker(impl, header):
    marker = MODULES[impl].COURSE_LIST_MARKER
    assert marker.fullmatch(HEADERS[header])
    assert marker.fullmatch(HEADERS[header].removeprefix("THENCE "))


@pytest.mark.parametrize("impl", IMPLS)
@pytest.mark.parametrize(
    "text",
    [
        "along the following line of Smith North 10 degrees East 100.00 feet",
        "the following course North 10 degrees East 100.00 feet",
        "North 10 degrees East 100.00 feet following the fence",
        "along the following courses of the creek North 10 degrees East 100 feet",
    ],
)
def test_course_text_is_never_a_marker(impl, text):
    assert not MODULES[impl].COURSE_LIST_MARKER.fullmatch(text)


# --- finding 3: ordinal words ---------------------------------------------------------


ORDINAL_PROSE = (
    "BEGINNING at a point; THENCE first North 0 degrees East 100.00 feet to a stake; "
    "THENCE second, along the Second Street line, North 90 degrees East 50.00 feet to a pipe."
)


@pytest.mark.parametrize("impl", IMPLS)
def test_ordinal_after_bare_thence_is_verbatim_deed_wording(impl):
    parts = SPLITTERS[impl](ORDINAL_PROSE)
    assert parts == [
        "first North 0 degrees East 100.00 feet to a stake",
        "second, along the Second Street line, North 90 degrees East 50.00 feet to a pipe",
    ]


@pytest.mark.parametrize("impl", IMPLS)
@STRICT
def test_ordinal_after_bare_thence_still_extracts_both_courses(impl, strict):
    calls, skipped = _run(impl, ORDINAL_PROSE, strict)
    assert [c.course for c in calls] == [1, 2]
    assert [c.distance_ft for c in calls] == [100.0, 50.0]
    assert skipped == []


@pytest.mark.parametrize("impl", IMPLS)
def test_single_ordinal_after_header_is_not_an_enumeration(impl):
    text = (
        "BEGINNING at a point; THENCE the following courses: first North 0 degrees East "
        "100.00 feet to a stake; THENCE due East 50.00 feet to a pipe."
    )
    assert ANALYZERS[impl](text).lists == ()
    assert "first North 0 degrees East 100.00 feet to a stake" in SPLITTERS[impl](text)[0]


@pytest.mark.parametrize("impl", IMPLS)
def test_ordinal_sequence_must_start_at_first(impl):
    text = (
        "BEGINNING at a point; THENCE the following courses: Second, due North 100.00 feet; "
        "Third, due East 50.00 feet to a pipe."
    )
    assert ANALYZERS[impl](text).lists == ()


# --- finding 5: re-split only within the enumerated region --------------------------


THENCE_INSIDE_OUTSIDE_COURSE = (
    "BEGINNING at a point; THENCE the following two courses and distances: "
    "(1) due North 100.00 feet; (2) due East 100.00 feet to a stake;\n"
    "3. due South 100.00 feet to a point, thence running with said line of lands of Smith;\n"
    "4. due West 100.00 feet to the point of beginning."
)


@pytest.mark.parametrize("impl", IMPLS)
def test_thence_inside_a_course_outside_the_list_is_not_split(impl):
    parts = SPLITTERS[impl](THENCE_INSIDE_OUTSIDE_COURSE)
    assert parts[-2] == (
        "due South 100.00 feet to a point, thence running with said line of lands of Smith"
    )
    assert len(parts) == 5  # header marker + four courses


@pytest.mark.parametrize("impl", IMPLS)
@STRICT
def test_thence_inside_a_course_outside_the_list_extracts_four_courses(impl, strict):
    calls, skipped = _run(impl, THENCE_INSIDE_OUTSIDE_COURSE, strict)
    assert [c.course for c in calls] == [1, 2, 3, 4]
    assert [c.distance_ft for c in calls] == [100.0] * 4
    assert skipped == []


# --- counted headers are never silently accepted --------------------------------------


UNENUMERATED = (
    "BEGINNING at a point; THENCE the following two courses and distances: "
    "due North 100.00 feet; due East 100.00 feet to a stake; "
    "THENCE due South 100.00 feet to the point of beginning."
)


FOLLOWING_SEMICOLON = (
    "BEGINNING at a pin; THENCE the following two courses and distances: "
    "North 10 degrees East 100 feet; South 80 degrees East 100 feet; "
    "THENCE South 5 degrees West 50 feet to the point of beginning."
)
FOLLOWING_THENCE = (
    "BEGINNING at a pin; THENCE along Main Street the following two courses: "
    "THENCE North 10 degrees East 100 feet; THENCE South 80 degrees East 100 feet; "
    "THENCE South 5 degrees West 50 feet to the point of beginning."
)


@pytest.mark.parametrize("impl", IMPLS)
@STRICT
@pytest.mark.parametrize("text", [UNENUMERATED, FOLLOWING_SEMICOLON, FOLLOWING_THENCE])
def test_counted_header_without_enumeration_is_satisfied_by_following_courses(impl, strict, text):
    calls, skipped = _run(impl, text, strict)
    assert skipped == []
    assert len(calls) == 3
    assert ANALYZERS[impl](text).mismatches == ()


FEWER_REMAIN = (
    "BEGINNING at a pin; THENCE the following three courses and distances: "
    "North 10 degrees East 100 feet; South 80 degrees East 100 feet to the point of beginning."
)


@pytest.mark.parametrize("impl", IMPLS)
def test_counted_header_with_fewer_courses_remaining_raises_strict(impl):
    with pytest.raises(ValueError, match="states 3 courses but 2 were found"):
        EXTRACTORS[impl](FEWER_REMAIN, strict=True, skipped_courses=[])


@pytest.mark.parametrize("impl", IMPLS)
def test_counted_header_with_fewer_courses_remaining_is_flagged_non_strict(impl):
    _calls, skipped = _run(impl, FEWER_REMAIN, False)
    assert "CourseCountMismatch" in [s.error_type for s in skipped]
    assert ANALYZERS[impl](FEWER_REMAIN).mismatches == ((3, 2),)


@pytest.mark.parametrize("impl", IMPLS)
def test_enumerated_list_keeps_exact_count_rule(impl):
    text = (
        "BEGINNING at a point; THENCE the following three courses: (1) due North 100.00 feet; "
        "(2) due East 50.00 feet; THENCE due South 100.00 feet to the point of beginning."
    )
    assert ANALYZERS[impl](text).mismatches == ((3, 2),)


@pytest.mark.parametrize("impl", IMPLS)
@STRICT
def test_header_inside_an_enclosing_numbered_list_is_satisfied(impl, strict):
    # Shape of 89 Haddon Ave (4732-544): deed-numbered courses continue after the header.
    text = (
        "BEGINNING at a point; thence (1) due North 100.00 feet to a stake; thence "
        "(2) due East 50.00 feet to a stone; thence along the line of lands of Hinski, "
        "the following two courses and distances; thence (3) due South 50.00 feet to a point "
        "in the same; thence (4) due South 50.00 feet to a point; thence (5) due West "
        "50.00 feet to the point of beginning."
    )
    calls, skipped = _run(impl, text, strict)
    assert [c.course for c in calls] == [1, 2, 3, 4, 5]
    assert skipped == []


@pytest.mark.parametrize("impl", IMPLS)
def test_consecutive_lists_do_not_merge(impl):
    text = (
        "BEGINNING at a point; THENCE the following two courses: (1) due North 100.00 feet; "
        "(2) due East 50.00 feet; THENCE the following two courses: (1) due South 100.00 feet; "
        "(2) due West 50.00 feet to the point of beginning."
    )
    analysis = ANALYZERS[impl](text)
    assert [len(course_list.enumerators) for course_list in analysis.lists] == [2, 2]
    assert analysis.mismatches == ()


# --- finding 4: computed once per tract, linear time ------------------------------------


@pytest.mark.parametrize("impl", IMPLS)
def test_enumeration_detection_runs_once_per_tract(impl, monkeypatch):
    # The monolith TextParser delegates course-list analysis to mp_parse.metadata.
    module = package_metadata
    original = module._course_enumerations
    seen: list[str] = []

    def spy(text):
        seen.append(text)
        return original(text)

    monkeypatch.setattr(module, "_course_enumerations", spy)
    calls, _ = _run(impl, _inline(HEADERS["plain"], STYLES["paren"]), True)
    assert len(calls) == 4
    assert len(seen) == 1


def _long_text(courses: int) -> str:
    body = "; ".join(f"({n % 900 + 1}) due North 1.00 feet to a stake" for n in range(courses))
    plain = "; ".join("THENCE due East 1.00 feet to a stake" for _ in range(courses))
    return f"BEGINNING at a point; {plain}; THENCE (1) due North 1.00 feet; {body}."


def _elapsed(fn, text: str) -> float:
    best = float("inf")
    for _ in range(3):
        started = time.perf_counter()
        fn(text)
        best = min(best, time.perf_counter() - started)
    return best


@pytest.mark.parametrize("impl", IMPLS)
def test_enumeration_detection_scales_linearly(impl):
    analyze = ANALYZERS[impl]
    small = _elapsed(analyze, _long_text(250))
    large = _elapsed(analyze, _long_text(1000))
    # Quadratic work grows 16x for 4x the text; linear work about 4x.
    assert large < small * 8 + 0.01
