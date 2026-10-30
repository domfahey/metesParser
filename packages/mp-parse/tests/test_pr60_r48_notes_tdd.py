"""PR #60 round 48: notes are read by prefix; offsets are never course lengths.

1. Record-call notes are selected by prefix (``split_notes``), never as "the last
   notes": a passing call noted after a record call is not record wording.
2. A record call (or alternative length) after the destination is blanked from
   ``to``: its wording appears only in notes.
3. An offset ("parallel to and 10 feet from X", "10 feet from and parallel to X",
   "10 feet (measured) at right angles from X", "10 feet northerly of and parallel
   with X") is never the course length.
4. A ';'-separated passing call belongs to the course before it; other stated
   wording there that no field keeps fails the course closed, never dropped.

Invariant over generated word orders: every piece of source wording appears
exactly once across along/to/notes, audited record calls equal the noted record
calls, and the course distance is always the course length.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime

import pytest
from mp_models import AuditContext, RunMetadata, SkippedCourse, split_notes
from mp_parse import extract_calls, extract_single_call
from mp_parse.calls import (
    _noted_record_calls,
    _restore_verbatim_records,
    _SourceMap,
    _with_boundary_notes,
)
from mp_parse.metadata import split_call_fragments

POB = "BEGINNING at a point; "
CLOSING = "; thence S 45° E 100 feet to the point of beginning."
RECORD_PREFIX = "record call: "


def _audit() -> AuditContext:
    return AuditContext(
        run_metadata=RunMetadata(
            parser_version="1.0.0",
            llm_provider="none",
            llm_model="none",
            prompt_hash="x",
            timestamp_utc=datetime.now(UTC),
            source_pdf="deed.pdf",
            cache_enabled=False,
        )
    )


def _first(fragment: str, audit: AuditContext | None = None):
    skipped: list[SkippedCourse] = []
    calls, _ = extract_calls(
        POB + fragment + CLOSING, strict=False, skipped_courses=skipped, audit_context=audit
    )
    first = [call for call in calls if call.course == 1]
    assert first, (fragment, [s.error for s in skipped])
    return first[0]


def _audited_records(audit: AuditContext) -> list[str]:
    return [d.value for d in audit.call_audits[0].decisions if d.field == "record_call"]


def _noted_records(notes: str | None) -> list[str]:
    return [
        p.removeprefix(RECORD_PREFIX) for p in split_notes(notes) if p.startswith(RECORD_PREFIX)
    ]


# --- 1. notes are read by prefix --------------------------------------------------


def test_passing_call_after_record_call_is_not_audited_as_record_wording() -> None:
    audit = _audit()
    call = _first(
        "thence N 45° E (deed N 44° E) 100 feet, passing a pipe at 50 feet, to a pin", audit
    )
    assert call.notes == "record call: (deed N 44° E); passing call: passing a pipe at 50 feet"
    assert _audited_records(audit) == ["(deed N 44° E)"]


def test_noted_record_calls_selects_by_prefix_anywhere() -> None:
    notes = (
        "parenthetical: (calc. 101 feet); record call: (deed N 44° E); "
        "passing call: passing a pipe at 50 feet; record call: (R 99 feet)"
    )
    assert _noted_record_calls(notes) == ["(deed N 44° E)", "(R 99 feet)"]
    assert _noted_record_calls("passing call: passing a pipe at 50 feet") == []
    assert _noted_record_calls(None) == []


def test_boundary_notes_keep_passing_call_notes_whole() -> None:
    call = extract_single_call(
        "thence N 45° E (deed N 44° E) 100 feet, passing a pipe at 50 feet, to a pin", 1
    )
    assert call is not None
    exception = "exception not applied: EXCEPTING the West 10 feet thereof"
    [updated] = _with_boundary_notes([call], [exception])
    assert split_notes(updated.notes) == [
        exception,
        "record call: (deed N 44° E)",
        "passing call: passing a pipe at 50 feet",
    ]
    assert _noted_record_calls(updated.notes) == ["(deed N 44° E)"]


def test_restored_record_wording_keeps_a_later_passing_note() -> None:
    source = "thence N 45° E (deed N 44°  10' E) 100 feet, passing a pipe at 50 feet, to a pin"
    tract = "thence N 45° E (deed N 44°10' E) 100 feet, passing a pipe at 50 feet, to a pin"
    call = extract_single_call(tract, 1)
    assert call is not None
    [restored] = _restore_verbatim_records([call], tract, _SourceMap(source, tract))
    assert split_notes(restored.notes) == [
        "record call: (deed N 44°  10' E)",
        "passing call: passing a pipe at 50 feet",
    ]


def test_restored_record_wording_in_a_description_is_audited() -> None:
    audit = _audit()
    call = _first(
        "thence N 45° E (deed N 44° 10' E) 100 feet, passing a pipe at 50 feet, to a pin", audit
    )
    assert _noted_records(call.notes) == _audited_records(audit)
    assert "passing call: passing a pipe at 50 feet" in split_notes(call.notes)


# --- 2. record wording after the destination is only in notes ----------------------


@pytest.mark.parametrize(
    ("fragment", "note"),
    [
        ("thence N 45° E 100 feet to a pin (deed 99 feet)", "record call: (deed 99 feet)"),
        ("thence N 45° E 100 feet to a pin (record N 44° E)", "record call: (record N 44° E)"),
        (
            "thence N 45° E 100 feet to a pin (calculated 101 feet)",
            "parenthetical: (calculated 101 feet)",
        ),
        (
            "thence N 45° E 100 feet to a point (see plan 12 feet) in the road",
            "parenthetical: (see plan 12 feet)",
        ),
    ],
)
def test_record_wording_after_destination_is_not_in_to(fragment: str, note: str) -> None:
    call = _first(fragment)
    assert call.to in ("a pin", "a point in the road")
    assert call.notes == note
    assert (call.distance_ft, call.bearing_azimuth_deg_from_north) == (100.0, 45.0)


def test_description_parenthetical_after_destination_stays_in_to() -> None:
    call = _first("thence N 45° E 100 feet to a pin in Main Street (50 feet wide)")
    assert call.to == "a pin in Main Street (50 feet wide)"
    assert call.notes is None


# --- 3. offsets are never course lengths ------------------------------------------

OFFSET_CLAUSES = [
    "parallel to and 10 feet from Main Street",
    "parallel with and 10 feet from Main Street",
    "parallel to and 10 feet distant from Main Street",
    "parallel with and 10 feet distant from Main Street",
    "10 feet from and parallel to Main Street",
    "10 feet from and parallel with Main Street",
    "10 feet distant from and parallel with Main Street",
    "10 feet measured at right angles from Main Street",
    "10 feet (measured) at right angles from Main Street",
    "10 feet northerly of and parallel with Main Street",
    "10 feet southwesterly of and parallel to Main Street",
    "10 feet distant from Main Street",
]


@pytest.mark.parametrize("offset", OFFSET_CLAUSES)
@pytest.mark.parametrize(
    "template",
    [
        "thence N 45° E along a line {o} 100 feet to a pin",
        "thence N 45° E 100 feet along a line {o} to a pin",
        "thence along a line {o} N 45° E 100 feet to a pin",
    ],
)
def test_offset_is_never_the_course_length(template: str, offset: str) -> None:
    call = _first(template.format(o=offset))
    assert call.distance_ft == 100.0
    assert call.along == f"a line {offset}"
    assert call.notes is None


def test_reviewer_offset_case_reads_the_course_length() -> None:
    call = _first(
        "thence N 45° E along a line parallel to and 10 feet from Main Street 100 feet to a pin"
    )
    assert (call.distance_ft, call.along, call.to) == (
        100.0,
        "a line parallel to and 10 feet from Main Street",
        "a pin",
    )


def test_offset_right_after_an_unjoined_length_stays_ambiguous() -> None:
    with pytest.raises(ValueError, match="course length ambiguous"):
        extract_single_call("thence N 45° E 100 feet 50 feet distant from Main Street to a pin", 1)


# --- 4. a ';'-separated passing call belongs to the course before it ---------------

PASSING_AFTER_SEMICOLON = {
    "thence": (
        "BEGINNING at a point; thence N 45° E 100 feet to a pin; passing a monument at 30 feet; "
        "thence S 45° E 100 feet to the point of beginning."
    ),
    "semicolon-only": (
        "BEGINNING at a point; N 45° E 100 feet to a pin; passing a monument at 30 feet; "
        "S 45° E 100 feet to the point of beginning."
    ),
    "multi-course-fragment": (
        "BEGINNING at a point; thence N 45° E 100 feet to a pin; passing a monument at 30 feet; "
        "S 45° E 100 feet to the point of beginning."
    ),
    "numbered": (
        "BEGINNING at a point;\n1. N 45° E 100 feet to a pin; passing a monument at 30 feet;\n"
        "2. S 45° E 100 feet to the point of beginning."
    ),
}


@pytest.mark.parametrize("name", sorted(PASSING_AFTER_SEMICOLON))
def test_passing_call_after_semicolon_is_noted_on_the_course_before_it(name: str) -> None:
    skipped: list[SkippedCourse] = []
    calls, _ = extract_calls(PASSING_AFTER_SEMICOLON[name], strict=False, skipped_courses=skipped)
    assert skipped == []
    assert [(c.course, c.distance_ft, c.to, c.notes) for c in calls] == [
        (1, 100.0, "a pin", "passing call: passing a monument at 30 feet"),
        (2, 100.0, "the point of beginning", None),
    ]


def test_semicolon_passing_fragment_joins_the_course_before_it() -> None:
    fragments = split_call_fragments(PASSING_AFTER_SEMICOLON["semicolon-only"])
    assert [f.text for f in fragments if not f.preamble] == [
        "N 45° E 100 feet to a pin; passing a monument at 30 feet",
        "S 45° E 100 feet to the point of beginning",
    ]


def test_passing_fragment_with_no_course_before_it_is_not_attached() -> None:
    fragments = split_call_fragments("passing a monument at 30 feet; N 45° E 100 feet to a pin")
    assert [f.text for f in fragments] == [
        "passing a monument at 30 feet",
        "N 45° E 100 feet to a pin",
    ]


def test_unattached_stated_wording_after_semicolon_fails_closed() -> None:
    fragment = (
        "thence N 45° E 100 feet to a pin; along a line parallel to and 10 feet from Main Street"
    )
    with pytest.raises(ValueError, match="course wording after ';' not attached"):
        extract_single_call(fragment, 1)
    with pytest.raises(ValueError, match="not attached"):
        extract_calls(POB + fragment + CLOSING, strict=True)
    skipped: list[SkippedCourse] = []
    calls, _ = extract_calls(POB + fragment + CLOSING, strict=False, skipped_courses=skipped)
    assert [s.course for s in skipped] == [1]
    assert [c.course for c in calls] == [2]


@pytest.mark.parametrize(
    "tail",
    [
        "; and extends",
        # A witness reference is description metadata (witness trees), not course wording.
        "; a large hickory bears S 45° W 50 feet",
    ],
)
def test_non_course_wording_after_semicolon_does_not_fail_the_course(tail: str) -> None:
    call = _first("thence N 45° E 100 feet to a pin" + tail)
    assert (call.distance_ft, call.to, call.notes) == (100.0, "a pin", None)


# --- invariant over generated word orders ------------------------------------------

# (inserted wording, the source wording that must appear exactly once)
PIECES = {
    "record-length": ("(deed 99 feet)", "deed 99 feet"),
    "record-bearing": ("(record N 44° E)", "record N 44° E"),
    "passing": ("passing a pipe at 50 feet", "passing a pipe at 50 feet"),
    "parenthetical": ("(calculated 101 feet)", "calculated 101 feet"),
    "offset": (
        "along a line parallel to and 10 feet from Main Street",
        "parallel to and 10 feet from Main Street",
    ),
}
POSITIONS = ("before-bearing", "after-bearing", "after-length", "after-terminus", "after-semicolon")
# An adjoiner after the destination behind ';' is attached to no field: it fails closed.
FAILS_CLOSED = {("offset", "after-semicolon")}


def _insert(wording: str, position: str) -> str:
    passing = wording.startswith("passing")
    lead, trail = (", ", ",") if passing else (" ", "")
    if position == "after-terminus":
        return lead + wording
    if position == "after-semicolon":
        return "; " + wording
    if position == "before-bearing":
        return f" {wording}{trail}"
    return f"{lead}{wording}{trail}"


def _fragment(placed: dict[str, str]) -> str:
    slots = dict.fromkeys(POSITIONS, "")
    for name, position in placed.items():
        slots[position] += _insert(PIECES[name][0], position)
    return (
        f"thence{slots['before-bearing']} N 45° E{slots['after-bearing']} 100 feet"
        f"{slots['after-length']} to a pin{slots['after-terminus']}{slots['after-semicolon']}"
    )


def _assert_invariant(placed: dict[str, str]) -> None:
    fragment = _fragment(placed)
    audit = _audit()
    call = _first(fragment, audit)
    fields = [call.along or "", call.to or "", *split_notes(call.notes)]
    for name in placed:
        wording = PIECES[name][1]
        assert sum(field.count(wording) for field in fields) == 1, (fragment, fields)
    assert _noted_records(call.notes) == _audited_records(audit), fragment
    assert (call.distance_ft, call.bearing_azimuth_deg_from_north) == (100.0, 45.0), fragment
    assert (call.to or "").startswith("a pin"), fragment


SINGLES = [
    (name, position)
    for name, position in itertools.product(PIECES, POSITIONS)
    if (name, position) not in FAILS_CLOSED
]


@pytest.mark.parametrize(("name", "position"), SINGLES)
def test_each_piece_appears_exactly_once(name: str, position: str) -> None:
    _assert_invariant({name: position})


PAIRS = [
    ((first, p1), (second, p2))
    for first, second in itertools.combinations(PIECES, 2)
    for p1, p2 in itertools.permutations(POSITIONS, 2)
    if (first, p1) not in FAILS_CLOSED and (second, p2) not in FAILS_CLOSED
]


@pytest.mark.parametrize(("first", "second"), PAIRS)
def test_each_piece_of_a_pair_appears_exactly_once(
    first: tuple[str, str], second: tuple[str, str]
) -> None:
    _assert_invariant(dict([first, second]))


@pytest.mark.parametrize(("name", "position"), sorted(FAILS_CLOSED))
def test_unattachable_piece_fails_closed(name: str, position: str) -> None:
    with pytest.raises(ValueError, match="not attached"):
        extract_single_call(_fragment({name: position}), 1)
