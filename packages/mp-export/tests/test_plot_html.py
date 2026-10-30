"""Standalone, offline plots preserve sourced calls and analytic geometry."""

import re
from html.parser import HTMLParser

import pytest
from mp_export.plot_html import render_plot
from mp_models.deed_call import DeedCall
from mp_models.plot_request import PlotCall, PlotRequest
from mp_verify.plot import prepare_plot


def request(**changes):
    values = {
        "title": "Synthetic boundary",
        "calls": tuple(
            PlotCall(
                id=f"call-{index}",
                call=DeedCall(
                    course=index,
                    direction_text="Recorded course",
                    bearing_azimuth_deg_from_north=bearing,
                    distance_ft=distance,
                ),
                quote=f"Original course {index}",
                **(
                    {"page_id": "page-one", "source_reference": "deed.pdf, p. 1"}
                    if index == 1
                    else {}
                ),
            )
            for index, (bearing, distance) in enumerate(
                [(0, 100), (90, 50), (180, 100), (270, 49.8)], 1
            )
        ),
    }
    values.update(changes)
    return PlotRequest(**values)


class Resources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        self.urls.extend(
            value for key, value in attrs if key == "src" or (tag == "link" and key == "href")
        )


def test_known_coordinates_open_closure_annotation_and_stable_input():
    prepared = prepare_plot(request())
    before = prepared.model_dump_json()
    output = render_plot(prepared)
    assert output == render_plot(prepared)
    assert prepared.model_dump_json() == before
    path = re.search(r'<path[^>]*data-plot-call="call-1"[^>]*\sd="([^"]+)"', output)[1]
    assert path == "M 0 -0 L 0 -100"
    assert 'class="plot-gap"' in output
    assert "0.200 ft" in output
    assert "not a recorded course" in output
    assert "POB" in output and "Local +Y" in output
    assert prepared.input_hash in output


def test_source_table_and_missing_page_references_are_honest():
    output = render_plot(prepare_plot(request()))
    assert 'data-call-row="call-1"' in output
    assert 'data-source-call="call-1"' in output
    assert 'data-page-id="page-one"' in output
    assert "deed.pdf, p. 1" in output
    assert "Source reference unavailable" in output
    assert "Original course 4" in output
    assert "<img" not in output
    assert "review complete" not in output.lower()


def test_incomplete_chain_renders_only_prefix_and_never_closure_gap():
    value = request()
    calls = list(value.calls)
    calls[1] = calls[1].model_copy(update={"call": None})
    output = render_plot(prepare_plot(value.model_copy(update={"calls": tuple(calls)})))
    assert 'data-plot-call="call-1"' in output
    assert 'data-plot-call="call-2"' not in output
    assert 'data-plot-call="call-3"' not in output
    assert 'data-unresolved-call="call-2"' in output
    assert 'class="plot-gap"' not in output
    assert "partial" in output
    assert "Full-parcel closure and area unavailable" in output


def test_analytic_quarter_arc_is_not_a_chord():
    call = PlotCall(
        id="curve",
        call=DeedCall(
            course=1,
            direction_text="Right curve",
            distance_ft=157.07963267948966,
            bearing_azimuth_deg_from_north=0,
            curve_dir="right",
            radius_ft=100,
            delta_deg=90,
        ),
    )
    output = render_plot(prepare_plot(request(calls=(call,))))
    path = re.search(r'data-plot-call="curve"[^>]*\sd="([^"]+)"', output)[1]
    arc = re.search(r"A ([^ ]+) ([^ ]+) 0 0 1 ([^ ]+) ([^ ]+)", path)
    assert list(map(float, arc.groups())) == pytest.approx([100, 100, 100, -100], abs=0.001)
    assert "Z" not in path


def test_forged_geometry_and_bypassed_request_validation_rejected():
    prepared = prepare_plot(request())
    primitive = prepared.geometry.primitives[0].model_copy(update={"end": (999, 999)})
    geometry = prepared.geometry.model_copy(
        update={"primitives": (primitive,) + prepared.geometry.primitives[1:]}
    )
    with pytest.raises(ValueError):
        render_plot(prepared.model_copy(update={"geometry": geometry}))
    forged = prepared.request.model_copy(update={"schema_version": "made-up"})
    with pytest.raises(ValueError):
        render_plot(prepared.model_copy(update={"request": forged}))


def test_source_text_is_escaped_and_no_assets_or_data_execute():
    payload = '</script><img src=x onerror="alert(1)">&\u2028'
    value = request(title=payload)
    first = value.calls[0].model_copy(update={"quote": payload, "source_reference": payload})
    output = render_plot(
        prepare_plot(value.model_copy(update={"calls": (first,) + value.calls[1:]}))
    )
    assert payload not in output
    assert "&lt;/script&gt;&lt;img src=x" in output
    assert output.count("</script>") == 1
    parser = Resources()
    parser.feed(output)
    assert parser.urls == []
    assert "@import" not in output and "fetch(" not in output and "eval(" not in output
    assert "scenario-select" not in output


def test_excluded_tie_in_row_does_not_claim_supported_boundary_geometry():
    value = request()
    tie = value.calls[0].model_copy(
        update={"id": "tie", "call": value.calls[0].call.model_copy(update={"is_tie_in": True})}
    )
    output = render_plot(prepare_plot(value.model_copy(update={"calls": (tie,) + value.calls})))
    row = re.search(r'<tr data-call-row="tie".*?</tr>', output, re.S)[0]
    assert "Tie-in excluded from boundary" in row
    assert "Supported geometry" not in row
    assert 'data-plot-call="tie"' not in output


def _chord_only_request():
    def line(i, bearing):
        return PlotCall(
            id=f"call-{i}",
            call=DeedCall(
                course=i,
                direction_text="Recorded course",
                bearing_azimuth_deg_from_north=bearing,
                distance_ft=100,
            ),
            quote=f"Course {i}",
        )

    curve = PlotCall(
        id="call-2",
        call=DeedCall(
            course=2,
            direction_text="curve",
            curve_dir="right",
            radius_ft=100,
            distance_ft=50,
            chord_bearing="N 90°00'00\" E",
            chord_length_ft=50,
        ),
        quote="Course 2",
    )
    return PlotRequest(title="Chord only", calls=(line(1, 0), curve, line(3, 180), line(4, 270)))


def test_chord_only_partial_notice_does_not_claim_prefix_only():
    prepared = prepare_plot(_chord_only_request())
    assert prepared.geometry.completeness == "partial"
    assert len(prepared.geometry.primitives) == 3
    notice = re.search(r'<p class="notice">(.*?)</p>', render_plot(prepared))[1]
    assert "anchored prefix" not in notice
    assert "call-2" in notice
    assert "chord" in notice
