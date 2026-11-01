"""PR #60 round 47: call notes split only at a known note prefix."""

from __future__ import annotations

from mp_models import (
    PASSING_CALL_NOTE_PREFIX,
    RECORD_CALL_NOTE_PREFIX,
    SEPARATE_EASEMENT_NOTE_PREFIX,
    UNAPPLIED_EXCEPTION_NOTE_PREFIX,
    split_notes,
    unapplied_exceptions,
)


def test_unapplied_exception_wording_with_semicolon_is_kept_whole() -> None:
    notes = (
        "incomplete bearing - cardinal only; "
        f"{UNAPPLIED_EXCEPTION_NOTE_PREFIX}EXCEPTING the West 10 feet thereof; conveyed to the County; "
        f"{UNAPPLIED_EXCEPTION_NOTE_PREFIX}EXCEPT the North 5 feet thereof; "
        f"{RECORD_CALL_NOTE_PREFIX}N 10 E 100 feet; deed"
    )
    assert unapplied_exceptions(notes) == [
        "EXCEPTING the West 10 feet thereof; conveyed to the County",
        "EXCEPT the North 5 feet thereof",
    ]


def test_split_notes_splits_only_before_known_prefixes() -> None:
    notes = (
        "meander / approximate; incomplete bearing; "
        f"{PASSING_CALL_NOTE_PREFIX}a pin; found; "
        f"{SEPARATE_EASEMENT_NOTE_PREFIX}ALSO an easement: BEGINNING; thence N 5 E 20 feet; "
        f"{UNAPPLIED_EXCEPTION_NOTE_PREFIX}SAVE AND EXCEPT the West 10 feet thereof"
    )
    assert split_notes(notes) == [
        "meander / approximate",
        "incomplete bearing",
        f"{PASSING_CALL_NOTE_PREFIX}a pin; found",
        f"{SEPARATE_EASEMENT_NOTE_PREFIX}ALSO an easement: BEGINNING; thence N 5 E 20 feet",
        f"{UNAPPLIED_EXCEPTION_NOTE_PREFIX}SAVE AND EXCEPT the West 10 feet thereof",
    ]
    assert "; ".join(split_notes(notes)) == notes
    assert split_notes(None) == [] and split_notes("") == []
