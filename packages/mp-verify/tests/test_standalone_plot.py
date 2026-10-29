"""Standalone plotting is advisory geometry without document-review inventions."""

import math

import pytest
from mp_models import DeedCall
from mp_models.plot_request import PlotCall, PlotRequest
from mp_verify.plot import prepare_plot


def rectangle() -> PlotRequest:
    return PlotRequest(
        title="Rectangle",
        calls=tuple(
            PlotCall(
                id=f"c{i}",
                call=DeedCall(
                    course=i,
                    direction_text="supplied",
                    distance_ft=d,
                    bearing_azimuth_deg_from_north=a,
                ),
                source_reference=f"row {i}",
            )
            for i, (a, d) in enumerate([(90, 100), (180, 50), (270, 100), (0, 50)], 1)
        ),
    )


def test_rectangle_uses_analytic_endpoints_and_never_invents_sources():
    prepared = prepare_plot(rectangle())
    geometry = prepared.geometry
    for actual, expected in zip(
        [p.end for p in geometry.primitives], [(100, 0), (100, -50), (0, -50), (0, 0)], strict=True
    ):
        assert actual == pytest.approx(expected, abs=1e-10)
    assert geometry.area_sq_ft == pytest.approx(5000)
    assert geometry.perimeter_ft == pytest.approx(300)
    assert geometry.misclosure_ft == pytest.approx(0, abs=1e-10)
    assert geometry.occurrence_id is None
    assert all(p.page_id is None for p in geometry.primitives)
    assert prepare_plot(prepared.request).geometry == geometry


def test_open_gap_is_retained_and_missing_middle_stops_prefix():
    request = rectangle()
    opened = request.model_copy(update={"calls": request.calls[:-1]})
    assert prepare_plot(opened).geometry.misclosure_ft == pytest.approx(50)
    missing = request.calls[1].call.model_copy(update={"bearing_azimuth_deg_from_north": None})
    partial = request.model_copy(
        update={
            "calls": (
                request.calls[0],
                request.calls[1].model_copy(update={"call": missing}),
                *request.calls[2:],
            )
        }
    )
    geometry = prepare_plot(partial).geometry
    assert len(geometry.primitives) == 1
    assert len(geometry.unresolved) == 3
    assert geometry.misclosure_ft is None
    assert geometry.area_sq_ft is None


def test_supported_arc_is_not_replaced_by_chord():
    request = PlotRequest(
        title="Arc",
        calls=(
            PlotCall(
                id="arc",
                call=DeedCall(
                    course=1,
                    direction_text="right arc",
                    distance_ft=math.pi * 50,
                    bearing_azimuth_deg_from_north=0,
                    curve_dir="right",
                    radius_ft=100,
                    delta_deg=90,
                ),
            ),
        ),
    )
    primitive = prepare_plot(request).geometry.primitives[0]
    assert primitive.kind == "arc"
    assert primitive.end == pytest.approx((100, 100))
    assert primitive.center == pytest.approx((100, 0))


def test_prepare_freshly_validates_model_copy():
    with pytest.raises(ValueError):
        prepare_plot(rectangle().model_copy(update={"calls": ()}))


def test_preserves_supplied_quotes_and_rejects_tampered_prepared():
    from mp_verify.plot import validate_prepared_plot

    request = rectangle()
    record = request.calls[0].model_copy(update={"quote": "  exact wording\n "})
    request = request.model_copy(update={"calls": (record, *request.calls[1:])})
    prepared = prepare_plot(request)
    assert prepared.request.calls[0].quote == "  exact wording\n "
    forged = prepared.model_copy(
        update={"geometry": prepared.geometry.model_copy(update={"area_sq_ft": 1})}
    )
    with pytest.raises(ValueError, match="freshly calculated"):
        validate_prepared_plot(forged)
    assert validate_prepared_plot(prepared) == prepared


def test_unknown_source_call_stops_without_invented_displacement():
    request = rectangle()
    request = request.model_copy(
        update={"calls": (PlotCall(id="unknown", call=None), *request.calls)}
    )
    result = prepare_plot(request)
    assert result.geometry.completeness == "unresolved"
    assert result.geometry.primitives == ()
    assert len(result.geometry.unresolved) == 5


def test_presentation_title_changes_input_hash_but_not_geometry():
    original = prepare_plot(rectangle())
    renamed = prepare_plot(original.request.model_copy(update={"title": "Display title changed"}))
    assert renamed.input_hash != original.input_hash
    assert renamed.geometry.geometry_hash == original.geometry.geometry_hash
    assert renamed.geometry == original.geometry


def test_unrepresentable_short_step_stays_unresolved():
    request = PlotRequest(
        title="Numerical range",
        calls=tuple(
            PlotCall(
                id=f"call-{i}",
                call=DeedCall(
                    course=i,
                    direction_text="east",
                    distance_ft=d,
                    bearing_azimuth_deg_from_north=90,
                ),
            )
            for i, d in enumerate([1e20, 1], 1)
        ),
    )
    geometry = prepare_plot(request).geometry
    assert geometry.completeness == "partial"
    assert len(geometry.primitives) == 1
    assert "precision" in geometry.unresolved[0].reason
    assert geometry.misclosure_ft is None
