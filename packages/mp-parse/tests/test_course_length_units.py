"""Course lengths share the curve-element unit vocabulary (metres, m, foot marks)."""

import pytest
from mp_models import ConversionFactors
from mp_parse.calls import extract_calls
from mp_parse.metadata import extract_distance

M = ConversionFactors.METER_TO_FEET

CASES = [
    ("100.00 metres", 100.0 * M),
    ("100.00 meters", 100.0 * M),
    ("100.00 m", 100.0 * M),
    ("100.00 m along", 100.0 * M),
    ("100.00 M", 100.0 * M),
    ("100.00'", 100.0),
    ("100.00′", 100.0),
    ("100.00 ft.", 100.0),
    ("100.00 feet", 100.0),
]


@pytest.mark.parametrize(("text", "feet"), CASES)
def test_extract_distance_reads_unit(text, feet):
    value, unit = extract_distance(f"N 45°00'00\" E {text} to a pin")
    assert ConversionFactors.convert_to_feet(value, unit) == pytest.approx(feet, rel=1e-6)


@pytest.mark.parametrize(("text", "feet"), CASES)
def test_extract_calls_line_reads_unit(text, feet):
    calls, _ = extract_calls(f"thence N 45°00'00\" E {text} to a pin;", strict=False)
    assert len(calls) == 1
    assert calls[0].distance_ft == pytest.approx(feet, rel=1e-6)


def test_metric_curve_with_only_course_length():
    calls, _ = extract_calls(
        "thence along a curve to the right having a radius of 50.00 metres, "
        "a delta of 30°00'00\", N 45°00'00\" E 25.88 metres to a pin;",
        strict=False,
    )
    assert len(calls) == 1
    assert calls[0].distance_ft == pytest.approx(25.88 * M, rel=1e-6)


@pytest.mark.parametrize(
    "text",
    [
        "N 45° 30m E 100 feet",
        "N 45°30m E 100 feet",
        "N 45° 30' E 100 feet",
        "N 45° 30' 15\" E 100 feet",
        "N 45° 30' 15'' E 100 feet",
    ],
)
def test_bearing_minutes_and_seconds_never_a_length(text):
    value, unit = extract_distance(f"{text} to a pin")
    assert ConversionFactors.convert_to_feet(value, unit) == pytest.approx(100.0)
    calls, _ = extract_calls(f"thence {text} to a pin;", strict=False)
    assert calls[0].distance_ft == pytest.approx(100.0)
