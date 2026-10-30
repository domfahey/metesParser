"""Curve element lengths keep their stated value in every supported unit spelling.

Chord lead lengths, chord lengths after the chord bearing and radial lengths share
one length-with-unit grammar (feet, ft, ft., foot marks, meters/metres/m and the
other units the distance converter supports). A unitless number directly after an
explicit curve-element label is that element in the deed's distance unit; an
unlabelled unitless number is never read as a length.
"""

import pytest
from mp_models import ConversionFactors
from mp_parse.calls import ARC_COMPUTED_NOTE, extract_calls, extract_single_call
from mp_verify.closure import verify_closure

M = ConversionFactors.METER_TO_FEET

# A closed half-disc: east 200 ft, then a 180 degree curve back along a 200 ft chord.
HALF_DISC = (
    "thence N 90°00'00\" E 200.00 feet; thence along a curve to the right having a "
    "radius of 100.00 feet, a central angle of 180°00'00\", a chord of {chord} bearing "
    "S 90°00'00\" W to the point of beginning."
)

LEAD_CHORDS = [
    ("200.00 feet", 200.0),
    ("200.00 foot", 200.0),
    ("200.00 ft", 200.0),
    ("200.00 ft.", 200.0),
    ("200.00 FT", 200.0),
    ("200.00'", 200.0),
    ("200.00′", 200.0),
    ("200.00 feet,", 200.0),
    ("60.96 meters", 60.96 * M),
    ("60.96 metres", 60.96 * M),
    ("60.96 m", 60.96 * M),
    ("12.1212 rods", 12.1212 * 16.5),
    ("3.0303 chains", 3.0303 * 66.0),
]


def _calls(text: str, distance_unit: str = "feet"):
    calls, _ = extract_calls(text, distance_unit, strict=False)
    return calls


@pytest.mark.parametrize(("chord", "feet"), LEAD_CHORDS)
def test_chord_length_before_the_bearing_is_read_in_every_unit(chord, feet):
    calls = _calls(HALF_DISC.format(chord=chord))
    curve = calls[-1]
    assert curve.chord_bearing == "S 90°00'00\" W"
    # The chord bearing is never taken as the tangent.
    assert curve.bearing_azimuth_deg_from_north is None
    assert curve.chord_length_ft == pytest.approx(feet, abs=1e-6)
    assert verify_closure(calls).misclosure_ft < 0.01


@pytest.mark.parametrize(("chord", "feet"), LEAD_CHORDS)
def test_single_call_chord_lead_length_is_converted_to_feet(chord, feet):
    call = extract_single_call(
        "thence along a curve to the right having a radius of 100.00 feet, a central "
        f"angle of 180°00'00\", a chord of {chord} bearing S 90°00'00\" W to a point",
        1,
    )
    assert call is not None
    assert call.chord_bearing == "S 90°00'00\" W"
    assert call.chord_length_ft == pytest.approx(feet, abs=1e-6)


def test_comma_grouped_chord_lead_length():
    call = extract_single_call(
        "thence along a curve to the right having a radius of 1,000.00 feet, a central "
        "angle of 73°44'23\", a chord of 1,200.00' bearing N 50°00'00\" E to a point",
        1,
    )
    assert call is not None
    assert call.chord_bearing == "N 50°00'00\" E"
    assert call.chord_length_ft == pytest.approx(1200.0)


TRAILING_CHORDS = [
    ("87.16 feet", 87.16),
    ("87.16 ft", 87.16),
    ("87.16 ft.", 87.16),
    ("87.16'", 87.16),
    ("87.16′", 87.16),
    (", 87.16 feet", 87.16),
    (", 87.16'", 87.16),
    ("26.57 meters", 26.57 * M),
    (", 26.57 metres", 26.57 * M),
    (", 26.57 m", 26.57 * M),
    ("5.2824 rods", 5.2824 * 16.5),
]


@pytest.mark.parametrize(("length", "feet"), TRAILING_CHORDS)
def test_chord_length_after_the_chord_bearing_is_read_in_every_unit(length, feet):
    sep = "" if length.startswith(",") else " "
    call = extract_single_call(
        "thence along a curve to the right having a radius of 50.00 feet, an arc length "
        f"of 87.27 feet and a chord bearing N 50°00'00\" E{sep}{length} to a point",
        1,
    )
    assert call is not None
    assert call.chord_bearing == "N 50°00'00\" E"
    assert call.chord_length_ft == pytest.approx(feet, abs=1e-6)
    # The chord is never the course length; the stated arc is.
    assert call.arc_length_ft == pytest.approx(87.27)
    assert call.distance_ft == pytest.approx(87.27)
    assert "ambiguous" not in (call.notes or "")


@pytest.mark.parametrize("unit", ["meters", "metres", "m"])
def test_metric_curve_keeps_every_element_in_its_unit(unit):
    text = (
        f"thence along a curve to the right having a radius of 15.24 {unit}, an arc "
        f"length of 26.60 {unit} and a chord bearing N 50°00'00\" E, 26.57 {unit} "
        "to a point"
    )
    for call in (extract_single_call(text, 1), _calls(text)[0]):
        assert call is not None
        assert call.radius_ft == pytest.approx(15.24 * M)
        assert call.arc_length_ft == pytest.approx(26.60 * M)
        assert call.chord_length_ft == pytest.approx(26.57 * M)
        assert call.distance_ft == pytest.approx(26.60 * M)
        assert "ambiguous" not in (call.notes or "")


def test_radial_radius_after_bearing_in_meters():
    call = extract_single_call(
        "thence along a non-tangent curve to the left, the radius point of which bears "
        "N 10°00'00\" E 15.24 metres, an arc length of 26.60 metres to a point",
        1,
    )
    assert call is not None
    assert call.radius_ft == pytest.approx(15.24 * M)
    assert call.arc_length_ft == pytest.approx(26.60 * M)


CURVE = (
    "thence along a curve to the right having a radius of 50.00 feet, a central "
    "angle of 100°00'00\", {element} to a point"
)


@pytest.mark.parametrize(
    "element",
    ["an arc length of 87.27", "an arc distance of 87.27", "a length of arc of 87.27"],
)
def test_unitless_labelled_arc_is_kept_not_computed(element):
    text = CURVE.format(element=element)
    for call in (extract_single_call(text, 1), _calls(text)[0]):
        assert call is not None
        assert call.arc_length_ft == pytest.approx(87.27)
        assert call.distance_ft == pytest.approx(87.27)
        assert ARC_COMPUTED_NOTE not in (call.notes or "")


@pytest.mark.parametrize("element", ["a chord length of 87.16", "a chord distance of 87.16"])
def test_unitless_labelled_chord_is_kept(element):
    text = CURVE.format(element=element)
    for call in (extract_single_call(text, 1), _calls(text)[0]):
        assert call is not None
        assert call.chord_length_ft == pytest.approx(87.16)
        # The chord is never the course length; the arc is computed and disclosed.
        assert ARC_COMPUTED_NOTE in (call.notes or "")


def test_unitless_labelled_lengths_use_the_deed_distance_unit():
    text = CURVE.format(element="an arc length of 26.60").replace("50.00 feet", "15.24")
    call = extract_single_call(text, 1, distance_unit="meters")
    assert call is not None
    assert call.radius_ft == pytest.approx(15.24 * M)
    assert call.arc_length_ft == pytest.approx(26.60 * M)
    assert call.distance_ft == pytest.approx(26.60 * M)


def test_unitless_radius_is_still_accepted():
    call = extract_single_call(
        "thence along a curve to the right having a radius of 50.00, an arc length of "
        "87.27 feet to a point",
        1,
    )
    assert call is not None
    assert call.radius_ft == pytest.approx(50.0)
    assert call.arc_length_ft == pytest.approx(87.27)


def test_unlabelled_unitless_number_is_not_a_length():
    call = extract_single_call(CURVE.format(element="87.27"), 1)
    assert call is not None
    assert call.arc_length_ft is None
    assert ARC_COMPUTED_NOTE in (call.notes or "")
