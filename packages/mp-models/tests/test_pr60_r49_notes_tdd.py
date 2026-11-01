"""PR #60 round 49: a verbatim note never swallows a following fixed note."""

from __future__ import annotations

import itertools
import random

from mp_models import (
    FIXED_NOTE_PREFIXES,
    FIXED_NOTES,
    LEGACY_CURVE_NOTE,
    UNAPPLIED_EXCEPTION_NOTE_PREFIX,
    VERBATIM_NOTE_PREFIXES,
    split_notes,
    unapplied_exceptions,
)


def test_fixed_note_after_unapplied_exception_is_not_part_of_it() -> None:
    notes = (
        f"{UNAPPLIED_EXCEPTION_NOTE_PREFIX}EXCEPT the North 10 feet thereof; {LEGACY_CURVE_NOTE}"
    )
    assert unapplied_exceptions(notes) == ["EXCEPT the North 10 feet thereof"]
    assert split_notes(notes) == [
        f"{UNAPPLIED_EXCEPTION_NOTE_PREFIX}EXCEPT the North 10 feet thereof",
        LEGACY_CURVE_NOTE,
    ]


def test_fixed_note_containing_semicolon_stays_whole() -> None:
    note = "curve positioned by stated tangent and chord; arc not stated"
    assert note in FIXED_NOTES
    assert split_notes(f"meander / approximate; {note}; incomplete bearing") == [
        "meander / approximate",
        note,
        "incomplete bearing",
    ]


def test_registered_notes_round_trip() -> None:
    verbatim = [
        f"{prefix}{wording}"
        for prefix in VERBATIM_NOTE_PREFIXES
        for wording in ("plain wording", "wording; with semicolon; and more", "a; b")
    ]
    parameterized = [f"{prefix}sample" for prefix in FIXED_NOTE_PREFIXES]
    pool = [*FIXED_NOTES, *parameterized, *verbatim]
    rng = random.Random(49)
    cases = [list(pair) for pair in itertools.permutations(pool, 2)]
    cases += [rng.sample(pool, rng.randint(3, 8)) for _ in range(500)]
    for parts in cases:
        assert split_notes("; ".join(parts)) == parts, parts
