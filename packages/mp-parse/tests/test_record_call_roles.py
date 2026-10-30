"""Record calls: one identification pass, never read as the course, kept verbatim.

A record call restates the course as an earlier deed, plan or record gave it: a
bracketed group holding a course bearing or a labelled length ("(deed N 44° E)",
"[N 44° E 99 feet deed]", "(recorded as 600.00 feet)", nested brackets included),
or a pair or length labelled "(R)", "per deed" or "of record" beside the course's
own value. It is identified before any bearing, tangent, chord, radial, length or
curve element is read and is removed from that reading, on a straight course or a
curve alike:

- a record value never becomes the course's bearing, tangent, chord or distance;
- when what remains states no bearing the course is cardinal only (or has no
  tangent), and when it states no length the course fails closed;
- a fragment's only labelled pair, with no other direction or measured value, is
  its course (as on ``main``); its bearing and length come from that one pair;
- with (R)/(M) labels the measured (or unlabelled) value is the course;
- record wording is kept verbatim (balanced brackets included) in notes.

``CASES`` is the corpus, shared with the monolith facade test
(``tests/unit/test_pr60_r41_record_calls_tdd.py``). Each case asserts the course
values and the complete notes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import NamedTuple

import pytest
from mp_models import AuditContext, DeedCall, RunMetadata, SkippedCourse
from mp_parse import extract_calls, extract_single_call
from mp_parse.calls import MultipleCoursesError, _scan_record_calls, enrich_calls_with_azimuths

POB = "BEGINNING at a point; "
CLOSING = "; THENCE S 45° W 100 feet to the point of beginning."
STRICT = pytest.mark.parametrize("strict", [True, False], ids=["strict", "non-strict"])
CURVE = "thence along a curve to the right having a radius of 100 feet, an arc length of 50 feet"
CHORD_NOTE = "tangent bearing not stated - curve positioned by chord and delta in verification"
CARDINAL = "incomplete bearing - cardinal only"
MISSING = "Missing boundary course distance"
NOT_GIVEN = object()


class Course(NamedTuple):
    """The fragment parses as one course with these values and exactly these notes."""

    fragment: str
    azimuth: float | None
    distance: float | None
    notes: str | None
    chord: tuple[str, float] | None = None
    along: object = NOT_GIVEN


class Fails(NamedTuple):
    """The fragment fails closed: no course is invented from a record value."""

    fragment: str
    error: type[ValueError]
    match: str


CASES: dict[str, Course | Fails] = {
    # --- Bracketed record calls on a straight course (round 40) ---
    "paren-deed-bearing": Course(
        "thence N 45° E (deed N 44° E) 100 feet", 45.0, 100.0, "record call: (deed N 44° E)"
    ),
    "paren-record-bearing": Course(
        "thence N 45° E (record N 44° E) 100.00 feet to a pin",
        45.0,
        100.0,
        "record call: (record N 44° E)",
    ),
    "bracketed-deed": Course(
        "thence N 45° E 100 feet [N 44° E 99 feet deed] to a pin",
        45.0,
        100.0,
        "record call: [N 44° E 99 feet deed]",
    ),
    "paren-record-distance": Course(
        "thence N 45° E 100.00 feet (deed 99.5 feet) to a pin",
        45.0,
        100.0,
        "record call: (deed 99.5 feet)",
    ),
    "paren-formerly": Course(
        "thence N 45° E 100 feet (formerly N 44° E 99 feet) to a pin",
        45.0,
        100.0,
        "record call: (formerly N 44° E 99 feet)",
    ),
    "paren-recorded-as-distance": Course(
        "thence due North 599.89 feet (recorded as 600.00 feet) to a point",
        0.0,
        599.89,
        "record call: (recorded as 600.00 feet)",
    ),
    "paren-recorded-as-course": Course(
        "thence North 58 degrees 12 minutes 10 seconds East 233.30 feet "
        "(recorded as North 58 degrees 12 10 East 233.33 feet) to a point",
        58.0 + 12.0 / 60.0 + 10.0 / 3600.0,
        233.30,
        "record call: (recorded as North 58 degrees 12 10 East 233.33 feet)",
    ),
    # Finding 5 (regression): a bracketed record distance, like the round one.
    "bracketed-record-distance": Course(
        "thence N 45° E 100 feet [deed 99.5 feet] to a pin",
        45.0,
        100.0,
        "record call: [deed 99.5 feet]",
    ),
    # Finding 6: a record distance in brackets, either order of the labels.
    "paren-formerly-distance": Course(
        "thence N 45° E 100 feet (formerly 99 feet) to a pin",
        45.0,
        100.0,
        "record call: (formerly 99 feet)",
    ),
    "M-then-paren-R-distance": Course(
        "thence N 45° E 100.05 feet (M) (100 feet R) to a pin",
        45.0,
        100.05,
        "record call: (100 feet R)",
    ),
    "R-then-paren-M-distance": Course(
        "thence N 45° E 100 feet (R) (100.05 feet M) to a pin",
        45.0,
        100.05,
        "record call: 100 feet (R)",
    ),
    "R-then-M-distance": Course(
        "thence N 45° E 100 feet (R), 100.05 feet (M) to a pin",
        45.0,
        100.05,
        "record call: 100 feet (R)",
    ),
    "M-then-R-distance": Course(
        "thence N 45° E 100.05 feet (M), 100 feet (R) to a pin",
        45.0,
        100.05,
        "record call: 100 feet (R)",
    ),
    # Finding 10: nested brackets are one balanced record call.
    "nested-bracket-bearing": Course(
        "thence N 45° E (deed [N 44° E] 99 feet) 100 feet to a pin",
        45.0,
        100.0,
        "record call: (deed [N 44° E] 99 feet)",
    ),
    "nested-paren-length": Course(
        "thence N 45° E 100 feet (deed N 44° E (99 feet)) to a pin",
        45.0,
        100.0,
        "record call: (deed N 44° E (99 feet))",
    ),
    # --- Labelled pairs (round 40) ---
    "lone-per-deed": Course("thence N 45° E 100 feet per deed to a pin", 45.0, 100.0, None),
    "lone-of-record": Course("thence N 45° E 100 feet of record to a pin", 45.0, 100.0, None),
    "lone-R": Course("thence N 45° E 100 feet (R) to a pin", 45.0, 100.0, None),
    "R-then-M": Course(
        "thence N 45°10' E 100.00 feet (R), N 45°05' E 100.05 feet (M) to a pin",
        45.0 + 5.0 / 60.0,
        100.05,
        "record call: N 45°10' E 100.00 feet (R)",
    ),
    "M-then-R": Course(
        "thence N 45°05' E 100.05 feet (M), N 45°10' E 100.00 feet (R) to a pin",
        45.0 + 5.0 / 60.0,
        100.05,
        "record call: N 45°10' E 100.00 feet (R)",
    ),
    "labelled-beside-measured": Course(
        "thence N 45° E 100 feet, N 45°10' E 100.5 feet (R), to a point",
        45.0,
        100.0,
        "record call: N 45°10' E 100.5 feet (R)",
    ),
    "being-of-record": Course(
        "thence N 45° E 100 feet, being N 45°10' E 100.5 feet of record, to a point",
        45.0,
        100.0,
        "record call: N 45°10' E 100.5 feet of record",
    ),
    "per-record-before": Course(
        "thence N 45° E 100 feet, per record N 45°10' E 100.5 feet, to a point",
        45.0,
        100.0,
        "record call: per record N 45°10' E 100.5 feet",
    ),
    # A record pair inside "along" is kept whole there: the course's own length is
    # never stripped out of it.
    "record-in-along-same-length": Course(
        "thence N 45° E 100 feet along Main Street, N 44° E 100 feet per deed, to a pin",
        45.0,
        100.0,
        "record call: N 44° E 100 feet per deed",
        along="Main Street, N 44° E 100 feet per deed",
    ),
    "record-in-along-same-bearing": Course(
        "thence N 45° E 100 feet along Main Street, N 45° E 99.5 feet per deed, to a pin",
        45.0,
        100.0,
        "record call: N 45° E 99.5 feet per deed",
        along="Main Street, N 45° E 99.5 feet per deed",
    ),
    # --- Finding 2: a cardinal-only course never takes the record bearing ---
    "cardinal-paren-deed": Course(
        "thence Northeasterly (deed N 44° E) 100 feet to a pin",
        None,
        100.0,
        f"{CARDINAL}; record call: (deed N 44° E)",
    ),
    "cardinal-bracketed-deed": Course(
        "thence Northeasterly 100 feet [N 44° E 99 feet deed] to a pin",
        None,
        100.0,
        f"{CARDINAL}; record call: [N 44° E 99 feet deed]",
    ),
    "cardinal-per-deed-bearing": Course(
        "thence Northeasterly 100 feet per deed N 44° E to a pin",
        None,
        100.0,
        f"{CARDINAL}; record call: per deed N 44° E",
    ),
    # --- Finding 1 (regression): a curve never takes a record tangent or chord ---
    "curve-chord-with-record": Course(
        f"{CURVE}, chord bearing N 45° E 49.9 feet (deed N 44° E 49.8 feet) to a pin",
        None,
        50.0,
        f"{CHORD_NOTE}; record call: (deed N 44° E 49.8 feet)",
        chord=("N 45° E", 49.9),
    ),
    "curve-chord-with-other-quadrant-record": Course(
        f"{CURVE}, chord bearing N 45° E 49.9 feet (deed S 44° E 49.8 feet) to a pin",
        None,
        50.0,
        f"{CHORD_NOTE}; record call: (deed S 44° E 49.8 feet)",
        chord=("N 45° E", 49.9),
    ),
    "curve-record-bearing-only": Course(
        f"{CURVE} (deed N 44° E) to a pin",
        None,
        50.0,
        "incomplete bearing; record call: (deed N 44° E)",
    ),
    # Finding 7: with R and M chords the measured chord is the chord.
    "curve-R-then-M-chord": Course(
        f"{CURVE}, chord bearing N 45° E 49.9 feet (R), chord bearing N 45°05' E 49.95 feet (M)"
        " to a pin",
        None,
        50.0,
        f"{CHORD_NOTE}; record call: chord bearing N 45° E 49.9 feet (R)",
        chord=("N 45°05' E", 49.95),
    ),
    "curve-M-then-R-chord": Course(
        f"{CURVE}, chord bearing N 45°05' E 49.95 feet (M), chord bearing N 45° E 49.9 feet (R)"
        " to a pin",
        None,
        50.0,
        f"{CHORD_NOTE}; record call: chord bearing N 45° E 49.9 feet (R)",
        chord=("N 45°05' E", 49.95),
    ),
    "curve-lone-R-chord": Course(
        f"{CURVE}, chord bearing N 45° E 49.9 feet (R) to a pin",
        None,
        50.0,
        CHORD_NOTE,
        chord=("N 45° E", 49.9),
    ),
    # --- Not record calls ---
    "road-width": Course(
        "thence N 45° E 100 feet along Main Street (50 feet wide) to a pin",
        45.0,
        100.0,
        None,
        along="Main Street (50 feet wide)",
    ),
    "formerly-road-width": Course(
        "thence N 45° E 100 feet along Main Street (formerly Caldwell Avenue - 100.00 feet wide)",
        45.0,
        100.0,
        None,
    ),
    # Not a record call, but an excluded length is never dropped: noted verbatim.
    "see-plan-length": Course(
        "thence N 45° E 100 feet to a point (see plan 12 feet) in the road",
        45.0,
        100.0,
        "parenthetical: (see plan 12 feet)",
    ),
    "tie": Course(
        "thence N 45° E 100 feet to a pin, which bears N 10° E 5 feet from a stone",
        45.0,
        100.0,
        None,
    ),
    # --- Fail closed: the course states no value of its own ---
    # Finding 3: an unlabelled bearing without length never borrows a labelled pair's.
    "bearing-then-R-pair": Fails(
        "thence N 45° E to a pin, N 44° E 99 feet (R)", ValueError, MISSING
    ),
    "bearing-along-then-per-deed-pair": Fails(
        "thence N 45° E along Main Street, N 44° E 99 feet per deed, to a pin",
        ValueError,
        MISSING,
    ),
    # Finding 4: a record distance is never the course length.
    "record-distance-only": Fails("thence N 45° E (deed 99 feet) to a pin", ValueError, MISSING),
    "per-deed-distance-only": Fails(
        "thence N 45° E (99 feet per deed) to a pin", ValueError, MISSING
    ),
    "trailing-record-distance-only": Fails(
        "thence N 45° E to a pin (record 99 feet)", ValueError, MISSING
    ),
    "record-course-only": Fails(
        "thence N 45° E (deed N 44° E 99 feet) to a pin", ValueError, MISSING
    ),
    # A numeral restatement is not a record call (``test_non_record_groups``); the
    # unit belongs to the written number, which is not read, as on ``main``.
    "numeral-restatement": Fails(
        "thence N 45° E one hundred (100) feet to a pin", ValueError, MISSING
    ),
    # --- Merged courses still fail closed ---
    "merged-courses": Fails(
        "thence N 45° E 100 feet, N 50° E 80 feet to a pin",
        MultipleCoursesError,
        "fragment contains multiple courses",
    ),
    "merged-R-courses": Fails(
        "thence N 45° E 100 feet (R), N 50° E 80 feet (R) to a pin",
        MultipleCoursesError,
        "fragment contains multiple courses",
    ),
    "merged-per-deed-courses": Fails(
        "thence N 45° E 100 feet per deed, N 50° E 80 feet per deed to a pin",
        MultipleCoursesError,
        "fragment contains multiple courses",
    ),
}
COURSES = sorted(name for name, case in CASES.items() if isinstance(case, Course))
FAILS = sorted(name for name, case in CASES.items() if isinstance(case, Fails))


def assert_course(call: DeedCall | None, case: Course) -> None:
    assert call is not None
    if case.azimuth is None:
        assert call.bearing_azimuth_deg_from_north is None
    else:
        assert call.bearing_azimuth_deg_from_north == pytest.approx(case.azimuth)
    assert call.distance_ft == pytest.approx(case.distance)
    assert call.notes == case.notes
    if case.chord is None:
        assert call.chord_bearing is None
    else:
        assert (call.chord_bearing, call.chord_length_ft) == (
            case.chord[0],
            pytest.approx(case.chord[1]),
        )
    if case.along is not NOT_GIVEN:
        assert call.along == case.along


@pytest.mark.parametrize("name", COURSES)
def test_single_call(name: str) -> None:
    case = CASES[name]
    assert isinstance(case, Course)
    assert_course(extract_single_call(case.fragment, 1), case)


@STRICT
@pytest.mark.parametrize("name", COURSES)
def test_course_in_description(name: str, strict: bool) -> None:
    case = CASES[name]
    assert isinstance(case, Course)
    calls, _ = extract_calls(POB + case.fragment + CLOSING, strict=strict)
    assert len(calls) == 2
    assert_course(calls[0], case)
    assert calls[1].notes is None


@pytest.mark.parametrize("name", FAILS)
def test_single_call_fails_closed(name: str) -> None:
    case = CASES[name]
    assert isinstance(case, Fails)
    with pytest.raises(case.error, match=case.match):
        extract_single_call(case.fragment, 1)


@pytest.mark.parametrize("name", FAILS)
def test_description_fails_closed(name: str) -> None:
    case = CASES[name]
    assert isinstance(case, Fails)
    with pytest.raises(ValueError, match=case.match):
        extract_calls(POB + case.fragment + CLOSING, strict=True)
    skipped: list[SkippedCourse] = []
    calls, _ = extract_calls(POB + case.fragment + CLOSING, strict=False, skipped_courses=skipped)
    assert [s.course for s in skipped] == [1]
    assert case.match in skipped[0].error
    assert [c.course for c in calls] == [2]


@pytest.mark.parametrize("name", COURSES)
def test_audit_names_the_noted_record_calls(name: str) -> None:
    case = CASES[name]
    assert isinstance(case, Course)
    audit = AuditContext(
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
    extract_calls(POB + case.fragment + CLOSING, strict=True, audit_context=audit)
    first = audit.call_audits[0]
    noted = [part for part in (case.notes or "").split("; ") if part.startswith("record call: ")]
    assert [d.value for d in first.decisions if d.field == "record_call"] == [
        part.removeprefix("record call: ") for part in noted
    ]


@pytest.mark.parametrize(
    "fragment",
    [
        "thence N 45° E one hundred (100) feet to a pin",
        "thence N 45° E 100 feet along Main Street (50 feet wide) to a pin",
        "thence N 45° E 100 feet along Main Street (formerly Caldwell Avenue - 100.00 feet wide)",
        "thence N 45° E 100 feet to a point (see plan 12 feet) in the road",
        "thence N 45° E 100 feet (1) to a point (R=100.00') in the road",
    ],
)
def test_non_record_groups(fragment: str) -> None:
    scan = _scan_record_calls(fragment)
    assert scan.records == ()
    assert scan.reading == fragment


def test_merged_courses_still_split_in_description() -> None:
    text = POB + "thence N 45° E 100 feet; N 50° E 80 feet to a pin" + CLOSING
    calls, _ = extract_calls(text, strict=True)
    assert [c.distance_ft for c in calls] == [100.0, 80.0, 100.0]


def test_tie_wording_stays_in_to() -> None:
    call = extract_single_call(CASES["tie"].fragment, 1)
    assert call is not None
    assert call.to == "a pin, which bears N 10° E 5 feet from a stone"


# --- enrich_calls_with_azimuths keeps every note but the incomplete-bearing one ---
RECORD_WITH_SEMICOLON = "record call: (deed N 44° E; 99 feet)"


@pytest.mark.parametrize(
    ("notes", "kept"),
    [
        (f"{CARDINAL}; {RECORD_WITH_SEMICOLON}", RECORD_WITH_SEMICOLON),
        (
            f"meander / approximate; incomplete bearing; chord bearing not read: 'N 45 E'; "
            f"{RECORD_WITH_SEMICOLON}; record call: per deed N 44° E",
            "meander / approximate; chord bearing not read: 'N 45 E'; "
            f"{RECORD_WITH_SEMICOLON}; record call: per deed N 44° E",
        ),
        ("incomplete bearing", None),
        ("meander / approximate", "meander / approximate"),
    ],
)
def test_due_cardinal_enrichment_keeps_notes(notes: str, kept: str | None) -> None:
    call = DeedCall(course=1, direction_text="due North", distance_ft=100.0, notes=notes)
    (enriched,) = enrich_calls_with_azimuths([call])
    assert enriched.bearing_azimuth_deg_from_north == pytest.approx(0.0)
    assert enriched.notes == kept
