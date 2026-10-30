"""Round 14: one chord/radial clause grammar shared by course stripping and capture.

SUBJECT (chord | radius point | radial [line|bearing] | center [point] [of the curve]
| radius) + optional LINK (of which | to which | which | that | whose) + VERB (bears |
bearing [of|is] | lies | is), followed by a bearing in any accepted course form
(including decimal seconds). Every row runs through the package and the monolith,
via ``extract_calls`` and ``extract_single_call``.
"""

from __future__ import annotations

import time

import pytest
from mp_bearing.azimuth import bearing_to_azimuth
from mp_parse.calls import _normalize_bearing_forms as package_normalize
from mp_parse.calls import extract_single_call as package_single_call

from metesparser.call_extractor import CallExtractor
from metesparser.call_extractor import _normalize_bearing_forms as monolith_normalize
from tests.fixtures.package_parser import extract_calls as package_extract_calls

CLOSING = "; THENCE due South 50 feet; THENCE due West 50 feet to the point of beginning."


def _via_calls(extract):
    return lambda text: extract(text + CLOSING, strict=True)[0]


def _via_single(extract):
    return lambda text: extract(text, 1)


ENTRY_POINTS = {
    "package-calls": _via_calls(package_extract_calls),
    "monolith-calls": _via_calls(CallExtractor.extract_calls),
    "package-single": _via_single(package_single_call),
    "monolith-single": _via_single(CallExtractor.extract_single_call),
}


@pytest.fixture(params=sorted(ENTRY_POINTS))
def parse(request):
    return ENTRY_POINTS[request.param]


# Radius 100, arc 52.36 -> delta 30 deg; chord 51.76 = 2 R sin 15.
CURVE = (
    "Thence along a curve to the right having a radius of 100.00 feet and an arc "
    "length of 52.36 feet, {clause} to a point"
)

# (clause, chord bearing azimuth, chord length)
CHORD_ROWS = [
    ("the chord which bears N 45° E 51.76 feet", 45.0, 51.76),
    ("the chord that bears N 45° E 51.76 feet", 45.0, 51.76),
    ("the chord of which bears N 45° E, 51.76 feet", 45.0, 51.76),
    ("the chord bears N 45° E 51.76 feet", 45.0, 51.76),
    ("the chord bearing N 45° E 51.76 feet", 45.0, 51.76),
    ("a chord bearing of N 45° E 51.76 feet", 45.0, 51.76),
    ("the chord whose bearing is N 45° E 51.76 feet", 45.0, 51.76),
    ("the chord which bears North 45 degrees East 51.76 feet", 45.0, 51.76),
    ("the chord bears N 45-00-00 E 51.76 feet", 45.0, 51.76),
    ("the chord is N 45° E, 51.76 feet", 45.0, 51.76),
    ("the chord bears S 45°30'15.5\" E 51.76 feet", 180 - (45 + 30 / 60 + 15.5 / 3600), 51.76),
    ("the chord which bears S 45°30'15\" E 51.76 feet", 180 - (45 + 30 / 60 + 15 / 3600), 51.76),
    ("the chord bears N 45° E", 45.0, None),
    ("a chord bearing of N 45° E and a chord length of 51.76 feet", 45.0, 51.76),
    ("the chord bears N 45° E for a distance of 51.76 feet", 45.0, 51.76),
    # An arc length after the chord bearing is never the chord length.
    ("the chord bears N 45° E, an arc of 52.36 feet", 45.0, None),
]


@pytest.mark.parametrize(("clause", "chord_az", "chord_len"), CHORD_ROWS)
def test_chord_clause_records_chord_and_no_tangent(parse, clause, chord_az, chord_len):
    call = parse(CURVE.format(clause=clause))
    assert call is not None
    assert call.chord_bearing is not None
    assert bearing_to_azimuth(call.chord_bearing) == pytest.approx(chord_az, abs=1e-9)
    assert call.chord_length_ft == chord_len
    # The chord is never the tangent, and no tangent is derived (round 21).
    assert call.bearing_azimuth_deg_from_north is None


RADIAL_ROWS = [
    "the radius point of which bears S 10°00'00\" E",  # reference phrasing (fc69e95)
    "the center of said curve bears S 10°00'00\" E",
    "the center of the curve bears S 10°00'00\" E",
    "the centre of said curve lies S 10°00'00\" E",
    "the radius point lies S 10°00'00\" E",
    "the radius point is S 10°00'00\" E",
    "a radial line to which bears S 10°00'00\" E",
    "the center point of which bears S 10°00'00\" E",
    "the center point which bears S 10°00'00\" E",
    "whose radius bears S 10°00'00\" E",
    "the radius of which bears S 10°00'00\" E",
    "on a radial bearing of S 10°00'00\" E",
    "the radial line of S 10°00'00\" E",
    "the centre lies South 10 degrees 00 minutes 00 seconds East",
    "the radius point bears S 10°00'00.0\" E",
]


@pytest.mark.parametrize("clause", RADIAL_ROWS)
def test_radial_clause_records_radial_bearing_not_course(parse, clause):
    call = parse(CURVE.format(clause=clause + ","))
    assert call is not None
    assert call.radial_bearing is not None
    assert bearing_to_azimuth(call.radial_bearing) == pytest.approx(170.0)
    assert call.non_tangent is True
    # The radial bearing is never the course tangent (no chord or tangent stated).
    assert call.bearing_azimuth_deg_from_north is None
    assert call.chord_bearing is None


def test_radial_clause_with_tangent_statement_stays_tangent(parse):
    call = parse(
        "Thence along a curve to the right, tangent to the last course, having a radius "
        "of 100.00 feet, the center of said curve bears S 10°00'00\" E, an arc length of "
        "52.36 feet"
    )
    assert call.radial_bearing is not None
    assert call.non_tangent is False


# Straight courses whose words resemble a clause subject: the course bearing is kept
# and nothing is recorded as a chord or radial bearing.
NEGATIVE_ROWS = [
    ("Thence along the center of Main Street N 45°00'00\" E 100.00 feet", 45.0),
    ("Thence along the center line N 45° E 100.00 feet", 45.0),
    ("Thence along the centerline of said road which bears N 45° E 100.00 feet", 45.0),
    ("Thence along the center of the road bearing N 45° E 100.00 feet", 45.0),
    ("Thence N 45° E 100.00 feet to the radius point of a curve", 45.0),
    ("Thence N 45° E 100.00 feet to the center of said curve", 45.0),
    ("Thence N 45° E 100.00 feet, the radius is 100 feet", 45.0),
    ("Thence along a radial line bearing S 10° E 50.00 feet", 170.0),
    ("Thence S 45°30'15.5\" E 100.00 feet", 180 - (45 + 30 / 60 + 15.5 / 3600)),
]


@pytest.mark.parametrize(("text", "azimuth"), NEGATIVE_ROWS)
def test_non_clause_wording_keeps_course_bearing(parse, text, azimuth):
    call = parse(text)
    assert call is not None
    assert call.bearing_azimuth_deg_from_north == pytest.approx(azimuth)
    assert call.chord_bearing is None
    assert call.radial_bearing is None


def test_radius_point_without_bearing_on_curve_records_nothing(parse):
    call = parse(
        "Thence along a curve to the right having a radius of 100.00 feet and an arc "
        "length of 52.36 feet, the chord which bears N 45° E 51.76 feet to the radius "
        "point of a curve"
    )
    assert call.radial_bearing is None
    assert call.bearing_azimuth_deg_from_north is None
    assert call.chord_bearing is not None


def _bearing_heavy_text(tokens: int) -> str:
    # Mixes every normalization path: dashed, d/m, marked words and labels.
    pieces = [
        "thence N 45-30-15 E 10 feet,",
        "Lot N 12-3 E",
        "N 45d30m E",
        "North 34 degrees 02' 00\" West",
        "and S 10-20 W",
    ]
    filler = "along lands now or formerly of Smith"
    return " ".join(f"{pieces[i % len(pieces)]} {filler}" for i in range(tokens))


@pytest.mark.parametrize("normalize", [package_normalize, monolith_normalize])
def test_normalization_is_fast_and_linear_in_text_length(normalize):
    text = _bearing_heavy_text(500)
    assert len(text) >= 20_000
    start = time.perf_counter()
    normalize(text)
    assert time.perf_counter() - start < 0.5

    def timed(value: str) -> float:
        best = float("inf")
        for _ in range(3):
            start = time.perf_counter()
            normalize(value)
            best = min(best, time.perf_counter() - start)
        return best

    # Doubling the text roughly doubles the time (quadratic would quadruple it).
    assert timed(_bearing_heavy_text(2000)) < 3.0 * timed(_bearing_heavy_text(1000)) + 0.01


def test_clause_grammar_is_shared_by_package_and_monolith():
    from mp_parse import calls as package

    from metesparser import call_extractor as monolith

    for name in ("_CHORD_PREFIX_PATTERN", "_RADIAL_PREFIX_PATTERN", "_CHORD_LENGTH_AFTER_BEARING"):
        assert getattr(package, name).pattern == getattr(monolith, name).pattern


@pytest.mark.parametrize(
    "pattern_name",
    [
        "_IDENTIFIER_BEFORE",
        "_DASHED_BEARING_CONTEXT",
        "_BEARING_DEGREE_PREFIX",
        "_ALONG_RADIAL_PATTERN",
    ],
)
def test_bounded_tail_check_equals_full_prefix_search(pattern_name):
    from mp_parse import calls as package

    from metesparser import call_extractor as monolith

    texts = [
        "Lot N 12-3 E",
        "thence  N 45-30 E",
        "x" * 200 + " instrument.   N 1-2 E",
        "Parcel A N 12-3 E",
        "the chord bears N 45° E",
        "along   said radial line",
        "N 45-30 E",
        "(N 45-30 E",
        "  N 45-30 E",
        "lot" + " " * 40 + "N",
    ]
    for module in (package, monolith):
        pattern = getattr(module, pattern_name)
        for text in texts:
            for end in range(len(text) + 1):
                assert module._ends_with(pattern, text, end) == bool(pattern.search(text[:end])), (
                    text,
                    end,
                )
