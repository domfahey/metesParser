"""Independent exception tracts must not cancel or invent net area."""

import math

import pytest
from mp_models import DeedCall as PackageCall
from mp_verify import verify_closure

from metesparser.closure_checker import ClosureChecker
from metesparser.models import DeedCall as MonolithCall


@pytest.fixture(
    params=[(PackageCall, verify_closure), (MonolithCall, ClosureChecker.verify_closure)]
)
def geometry(request):
    return request.param


def _square(call_type, size, *, start=1, reverse=False, exception=False):
    bearings = [0, 270, 180, 90] if reverse else [0, 90, 180, 270]
    return [
        call_type(
            course=i + start,
            direction_text="boundary",
            distance_ft=size,
            bearing_azimuth_deg_from_north=azimuth,
            is_exception=exception,
        )
        for i, azimuth in enumerate(bearings)
    ]


@pytest.mark.parametrize(
    "reverse_first,reverse_second", [(False, False), (False, True), (True, False), (True, True)]
)
def test_exception_areas_are_independent_of_each_tract_winding(
    geometry, reverse_first, reverse_second
):
    call_type, verify = geometry
    calls = _square(call_type, 100)
    calls += _square(call_type, 10, start=5, exception=True, reverse=reverse_first)
    calls += _square(call_type, 20, start=9, exception=True, reverse=reverse_second)
    result = verify(calls)
    assert result.closure_passed
    assert result.area_sq_ft == pytest.approx(9500)
    assert result.area_acres == pytest.approx(9500 / 43560)


def test_open_exception_does_not_create_a_net_area(geometry):
    call_type, verify = geometry
    calls = _square(call_type, 100)
    calls += _square(call_type, 10, start=5, exception=True)[:2]
    result = verify(calls)
    assert result.closure_passed
    assert not result.is_fully_verified()
    assert result.area_sq_ft == 0
    assert any(
        "exception" in warning.lower() and "does not close" in warning.lower()
        for warning in result.warnings
    )


def test_incomplete_exception_does_not_report_main_area_as_net(geometry):
    call_type, verify = geometry
    calls = _square(call_type, 100)
    calls.append(call_type(course=5, direction_text="northerly", distance_ft=10, is_exception=True))
    result = verify(calls)
    assert result.area_sq_ft == 0
    assert not result.is_fully_verified()
    assert any("incomplete bearing" in warning.lower() for warning in result.warnings)


def test_closed_then_open_exception_does_not_publish_partial_net_area(geometry):
    call_type, verify = geometry
    calls = _square(call_type, 100)
    calls += _square(call_type, 10, start=5, exception=True)
    calls += _square(call_type, 20, start=9, exception=True)[:2]
    result = verify(calls)
    assert result.area_sq_ft == 0
    assert any("does not close" in warning for warning in result.warnings)


def test_curved_exception_tracts_do_not_cancel(geometry):
    call_type, verify = geometry
    calls = _square(call_type, 100)
    for course, radius, direction in [(5, 10, "left"), (6, 20, "right")]:
        calls.append(
            call_type(
                course=course,
                direction_text="full circle",
                distance_ft=2 * math.pi * radius,
                bearing_azimuth_deg_from_north=0,
                is_exception=True,
                curve_dir=direction,
                radius_ft=radius,
                delta_deg=360,
                arc_length_ft=2 * math.pi * radius,
            )
        )
    result = verify(calls)
    assert result.area_sq_ft == pytest.approx(10000 - 500 * math.pi)


def test_exception_tie_in_is_not_an_area_edge(geometry):
    call_type, verify = geometry
    calls = _square(call_type, 100)
    calls.append(
        call_type(
            course=5,
            direction_text="tie in",
            distance_ft=100,
            bearing_azimuth_deg_from_north=90,
            is_exception=True,
            is_tie_in=True,
        )
    )
    calls += _square(call_type, 10, start=6, exception=True)
    assert verify(calls).area_sq_ft == pytest.approx(9900)
