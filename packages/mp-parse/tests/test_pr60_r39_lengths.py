"""Length-reading gaps: leading-decimal numbers, inch-only courses, tabular curve labels.

A leading-decimal number (".5") is a number only where it starts at a word
boundary; it never starts inside another number or after a letter/period. A course
stated wholly in inches is a length only directly after the bearing and where the
measurement ends (never a preposition "in", monument size or object size). Tabular
curve labels (R=, L=, Delta=, CB=, CH=/C=) are read through the same grammar as
the spelled-out curve elements; unlabelled values are never guessed.
"""

from __future__ import annotations

import pytest
from mp_parse.calls import extract_calls, extract_single_call
from mp_parse.units import LENGTH_NUMBER, parse_number

_PREFIX = "THENCE N 45° E "


@pytest.mark.parametrize(
    ("text", "feet"),
    [
        (".5 feet", 0.5),
        (".75 feet", 0.75),
        ("0.5 feet", 0.5),
        ("100.5 feet", 100.5),
        ("100 feet", 100.0),
    ],
)
def test_leading_decimal_course_length(text: str, feet: float) -> None:
    assert extract_single_call(_PREFIX + text, 1).distance_ft == pytest.approx(feet)


@pytest.mark.parametrize(
    "text",
    ["1.2.3 feet", "100.5.5 feet", "100 .5 feet", ".5.3 feet", "feet.5 feet", "100,.5 feet"],
)
def test_leading_decimal_never_starts_inside_another_number(text: str) -> None:
    import re

    for match in re.finditer(LENGTH_NUMBER, text):
        assert match.group(0) in ("100", "1", "5")  # never '.2', '.3', '.5' fragments
        assert not match.group(0).startswith(".")
    with pytest.raises(ValueError):
        extract_single_call(_PREFIX + text, 1)


def test_leading_decimal_parse_number() -> None:
    assert parse_number(".5") == 0.5
    assert parse_number(".75") == 0.75


def test_leading_decimal_not_after_degree_or_minute_mark() -> None:
    import re

    for text in ("N 45\u00b0 .5", "N 45\u00b030'.5"):
        assert not [m for m in re.finditer(LENGTH_NUMBER, text) if m.group(0).startswith(".")]


def test_sentence_period_before_number_is_not_leading_decimal() -> None:
    call = extract_single_call(_PREFIX + "100 feet. 5 acres more", 1)
    assert call.distance_ft == pytest.approx(100.0)


@pytest.mark.parametrize(
    ("text", "feet"),
    [
        ("12 inches", 1.0),
        ("100 inches", 100 / 12),
        ("1 inch", 1 / 12),
        ("6 in.", 0.5),
        ("12 inches to a point", 1.0),
        ("12 inches, to a point", 1.0),
        ('12" to a point', 1.0),
        ('24"', 2.0),
        (".5 inches", 0.5 / 12),
    ],
)
def test_course_wholly_in_inches(text: str, feet: float) -> None:
    assert extract_single_call(_PREFIX + text, 1).distance_ft == pytest.approx(feet)


@pytest.mark.parametrize(
    "text",
    [
        "to an 8 inch oak tree",
        "to a 12 inch oak",
        'to a 1" iron pipe',
        "to a 1.5 inch iron pipe",
        "in a northerly direction",
        "6 in a northerly direction",
        "12 inches iron pipe",
        "100 feet in a northerly direction",
    ],
)
def test_inch_guards_still_hold(text: str) -> None:
    if text.startswith("100 feet") or text.startswith("12 inches iron"):
        try:
            call = extract_single_call(_PREFIX + text, 1)
        except ValueError:
            return
        assert call.distance_ft == pytest.approx(100.0)
        return
    with pytest.raises(ValueError):
        extract_single_call(_PREFIX + text, 1)


def test_dms_seconds_mark_is_not_an_inch_length() -> None:
    with pytest.raises(ValueError):
        extract_single_call("THENCE N 45°30'15\" E", 1)


_SPELLED = (
    "THENCE along a curve to the right, with a radius of 100.00 feet, a delta of "
    "30°00'00\", an arc length of 52.36 feet, a chord bearing of N 60°00'00\" E "
    "and a chord of 51.76 feet"
)


def _curve_fields(call):
    return (
        call.distance_ft,
        call.curve_dir,
        call.radius_ft,
        call.delta_deg,
        call.arc_length_ft,
        call.chord_bearing,
        call.chord_length_ft,
        call.bearing_quadrant,
        call.curve_type,
    )


@pytest.mark.parametrize(
    "tabular",
    [
        "THENCE along a curve to the right, R=100.00', L=52.36', Δ=30°00'00\", "
        "CB=N 60°00'00\" E, CH=51.76'",
        "THENCE along a curve to the right, R=100.00', L=52.36', Δ=30°00'00\", "
        "CB=N 60°00'00\" E, C=51.76'",
        "THENCE along a curve to the right, R = 100.00 feet, L = 52.36 feet, "
        "Δ = 30°00'00\", CB = N 60°00'00\" E, CH = 51.76 feet",
        "THENCE along a curve to the right, CH=51.76', CB=N 60°00'00\" E, "
        "Δ=30°00'00\", L=52.36', R=100.00'",
        "THENCE along a curve to the right, R=100.00', L=52.36', "
        "Δ=30°00'00\", CB=N 60°00'00\" E, CH=51.76'.",
    ],
)
def test_tabular_curve_equals_spelled_out(tabular: str) -> None:
    got = extract_single_call(tabular, 1)
    expected = extract_single_call(_SPELLED, 1)
    assert _curve_fields(got) == _curve_fields(expected)
    assert got.radius_ft == 100.0
    assert got.chord_length_ft == 51.76
    assert got.direction_text.startswith("THENCE along a curve")


def test_tabular_curve_without_units_uses_deed_unit() -> None:
    call = extract_single_call(
        "THENCE along a curve to the left, R=200.00, L=104.72, Δ=30°00'00\", "
        "CB=S 30°00'00\" W, CH=103.53",
        1,
    )
    assert call.radius_ft == 200.0
    assert call.arc_length_ft == 104.72
    assert call.chord_length_ft == 103.53


def test_delta_d_label_is_not_read_as_delta() -> None:
    call = extract_single_call(
        "THENCE along a curve to the right, R=100.00', L=52.36', D=30°00'00\"", 1
    )
    assert call.delta_deg is None
    assert call.arc_length_ft == 52.36


def test_unlabelled_values_never_guessed() -> None:
    with pytest.raises(ValueError):
        extract_single_call("THENCE along a curve to the right, 100.00', 52.36', 30°", 1)


def test_labels_inside_words_are_not_labels() -> None:
    with pytest.raises(ValueError):
        extract_single_call("THENCE along a curve to the right, SR=100.00', XL=52.36'", 1)


def test_tabular_curve_in_full_description_closes_like_spelled_out() -> None:
    def build(curve: str) -> list:  # type: ignore[type-arg]
        """Return the calls of a closed description holding ``curve``."""
        text = (
            "BEGINNING at a pin; "
            + curve
            + "; thence S 80°00' W 100.00 feet to a pin; thence N 10° W 50 feet "
            "to the point of beginning."
        )
        return extract_calls(text)[0]

    assert [_curve_fields(c) for c in build(_SPELLED.replace("THENCE ", "thence "))] == [
        _curve_fields(c)
        for c in build(
            "thence along a curve to the right, R=100.00', L=52.36', Δ=30°00'00\", "
            "CB=N 60°00'00\" E, CH=51.76'"
        )
    ]
