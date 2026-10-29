"""Actual Chromium checks; run explicitly with make test-dashboard-browser."""

import json
import os
from pathlib import Path

import pytest
from mp_export.dashboard_html import render_dashboard
from mp_models.dashboard import DashboardBundle
from mp_verify.dashboard import calculate_dashboard

pytestmark = pytest.mark.skipif(
    os.environ.get("METESPARSER_BROWSER_TESTS") != "1",
    reason="Explicit browser target installs/preflights Chromium",
)
ROOT = Path(__file__).resolve().parents[2]
SCREENSHOTS = ROOT / "output/playwright/plot-validation"


def fixture_data():
    return json.loads(
        (ROOT / "packages/mp-review/tests/fixtures/dashboard-absolute.json").read_text()
    )


def overlay_data():
    value = fixture_data()
    value["schema_version"] = "1.1"
    value["calculations"][0]["frame"]["foot_definition"] = "international_ft"
    value["scenes"] = [
        {
            "id": "map-scene",
            "name": "Synthetic feet",
            "kind": "local",
            "units": "international_ft",
            "basis": "local",
        }
    ]
    value["map_sources"] = [
        {
            "id": "map-source",
            "label": "Supplied synthetic map",
            "sha256": "a" * 64,
            "filename": "supplied.json",
            "native_units": "international_ft",
        }
    ]
    value["vector_layers"] = [
        {
            "id": "tax-map",
            "label": "Synthetic context",
            "scene_id": "map-scene",
            "source_id": "map-source",
            "geometry_type": "Polygon",
            "coordinates": [
                [[990, 1990], [1120, 1990], [1120, 2130], [990, 2130], [990, 1990]],
                [[1020, 2020], [1030, 2020], [1030, 2030], [1020, 2030], [1020, 2020]],
            ],
        }
    ]
    prepared = calculate_dashboard(DashboardBundle.model_validate(value))
    value["placements"] = [
        {
            "id": "deed-placement",
            "calculation_id": "calc-one",
            "geometry_hash": prepared.plots.geometries[0].geometry_hash,
            "scene_id": "map-scene",
            "rotation_deg": 0,
            "translation": [1000, 2000],
            "status": "approximate",
            "rationale": "Synthetic context only",
        }
    ]
    return value


@pytest.fixture
def open_dashboard(tmp_path):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        contexts = []
        SCREENSHOTS.mkdir(parents=True, exist_ok=True)

        def open_page(value=None, width=1200, theme="light"):
            # Copy the HTML by itself: source directories are never available to the browser.
            delivery = tmp_path / f"standalone-{len(contexts)}.html"
            delivery.write_text(
                render_dashboard(
                    calculate_dashboard(DashboardBundle.model_validate(value or fixture_data()))
                )
            )
            context = browser.new_context(
                viewport={"width": width, "height": 900}, color_scheme=theme
            )
            contexts.append(context)
            remote = []
            errors = []

            def intercept(route):
                if route.request.url.startswith(("http:", "https:")):
                    remote.append(route.request.url)
                    route.abort()
                else:
                    route.continue_()

            context.route("**/*", intercept)
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(delivery.as_uri())
            page.wait_for_function(
                "!document.getElementById('scenario-status').textContent.includes('Loading')"
            )
            page._dashboard_remote = remote
            page._dashboard_errors = errors
            return page

        yield open_page
        for context in contexts:
            context.close()
        browser.close()


@pytest.mark.parametrize(
    "width,theme", [(1200, "light"), (1200, "dark"), (400, "light"), (400, "dark")]
)
def test_offline_source_selection_keyboard_and_responsive_plot(
    open_dashboard, width, theme, tmp_path
):
    page = open_dashboard(width=width, theme=theme)
    course = page.locator('[data-plot-call="call-one"]')
    course.focus()
    course.press("Enter")
    assert page.locator("#source-viewer").evaluate("node => node.open")
    assert "Synthetic deed" in page.locator("#viewer-label").inner_text()
    assert page.locator(".selected-source-crop").get_attribute("alt") == "Synthetic first distance"
    assert page.locator('[data-call-row="call-one"]').evaluate(
        "node => node.classList.contains('selected-call')"
    )
    page.locator("#viewer-close").click()
    assert course.evaluate("node => node === document.activeElement")
    assert page.locator("body").evaluate("node => node.scrollWidth <= window.innerWidth")
    page.locator("#plot-gap-detail summary").click()
    assert "not a recorded course" in page.locator("#plot-gap-detail").inner_text()
    page.locator("#workbench").screenshot(path=str(SCREENSHOTS / f"plot-{width}-{theme}.png"))
    assert page._dashboard_remote == []
    assert page._dashboard_errors == []


def test_zoom_pan_fit_reset_and_scale_do_not_change_geometry(open_dashboard):
    page = open_dashboard()
    plot = page.locator('[data-baseline-plot="calc-one"]')
    initial = plot.get_attribute("viewBox")
    course = page.locator('[data-baseline-layer="calc-one"]').inner_html()
    scale = float(plot.get_attribute("data-scale-length"))
    page.locator("#plot-zoom-in").click()
    assert plot.get_attribute("viewBox") != initial
    assert float(plot.get_attribute("data-scale-length")) <= scale
    plot.focus()
    before_pan = plot.get_attribute("viewBox")
    plot.press("ArrowRight")
    assert plot.get_attribute("viewBox") != before_pan
    plot.scroll_into_view_if_needed()
    before_drag = plot.get_attribute("viewBox")
    bounds = plot.bounding_box()
    page.mouse.move(bounds["x"] + bounds["width"] - 12, bounds["y"] + bounds["height"] - 12)
    page.mouse.down()
    page.mouse.move(bounds["x"] + bounds["width"] - 42, bounds["y"] + bounds["height"] - 32)
    page.mouse.up()
    assert plot.get_attribute("viewBox") != before_drag
    assert plot.evaluate(
        "node => Math.abs(Number(node.dataset.scalePixels)/Number(node.dataset.scaleLength)-Math.min(node.getBoundingClientRect().width/node.viewBox.baseVal.width,node.getBoundingClientRect().height/node.viewBox.baseVal.height)) < .001"
    )
    page.locator("#plot-fit").click()
    assert plot.get_attribute("viewBox") == initial
    page.locator("#plot-zoom-out").click()
    page.locator("#plot-reset").click()
    assert plot.get_attribute("viewBox") == initial
    assert page.locator('[data-baseline-layer="calc-one"]').inner_html() == course


def test_map_controls_scenario_edit_and_reset_preserve_frozen_placement(open_dashboard, tmp_path):
    page = open_dashboard(overlay_data())
    record = page.locator('[data-baseline-layer="calc-one"]').inner_html()
    findings = page.locator("#findings").inner_html()
    transcript = page.locator("#transcript-occ-one").inner_text()
    scenario = page.locator('[data-scenario-layer="calc-one"]')
    before = scenario.locator("path").get_attribute("d")
    assert scenario.get_attribute("data-translation") == "[1000,2000]"
    page.locator(".map-provenance summary").click()
    page.locator('[data-layer-toggle="tax-map"]').uncheck()
    assert page.locator('[data-map-layer="tax-map"]').is_hidden()
    page.locator('[data-layer-toggle="tax-map"]').check()
    opacity = page.locator('[data-layer-opacity="tax-map"]')
    opacity.focus()
    opacity.press("Home")
    for _ in range(4):
        opacity.press("ArrowRight")
    assert (
        page.locator('[data-map-layer="tax-map"]').evaluate("node => node.style.opacity") == "0.2"
    )
    assert page.locator(".map-polygon").get_attribute("fill-rule") == "evenodd"
    page.locator("#scenario-select").select_option("scenario-one")
    assert scenario.locator("path").get_attribute("d") != before
    assert scenario.get_attribute("data-translation") == "[1000,2000]"
    field = page.get_by_label("call-one: Distance in feet", exact=True)
    field.fill("invalid")
    assert field.get_attribute("aria-invalid") == "true"
    assert "Correct the highlighted invalid input" in page.locator("#scenario-status").inner_text()
    page.locator("#reset-record").click()
    assert scenario.locator("path").get_attribute("d") == before
    assert page.locator('[data-baseline-layer="calc-one"]').inner_html() == record
    assert page.locator("#findings").inner_html() == findings
    assert page.locator("#transcript-occ-one").inner_text() == transcript
    page.locator('[data-baseline-plot="calc-one"]').screenshot(
        path=str(SCREENSHOTS / "placed-vector.png")
    )
    assert page._dashboard_remote == []
    assert page._dashboard_errors == []


@pytest.mark.parametrize("kind", ["partial", "arc"])
def test_partial_and_arc_baselines_remain_visible_without_browser_editing(
    open_dashboard, kind, tmp_path
):
    value = fixture_data()
    value["scenarios"] = []
    if kind == "partial":
        value["calls"][1]["call"]["bearing_azimuth_deg_from_north"] = None
    else:
        value["calls"] = value["calls"][:1]
        value["calls"][0]["call"].update(curve_dir="right", radius_ft=100, delta_deg=90)
    page = open_dashboard(value)
    assert page.locator('[data-baseline-plot="calc-one"]').is_visible()
    assert page.locator('[data-plot-call="call-one"]').evaluate(
        "node => node.getTotalLength() > 0 && getComputedStyle(node).stroke !== 'none'"
    )
    assert page.locator('[data-plot-call="call-two"]').count() == 0
    if kind == "partial":
        assert page.locator('[data-unresolved-call="call-two"]').count() == 1
    else:
        assert "A 100 100" in page.locator('[data-plot-call="call-one"]').get_attribute("d")
    assert "Unresolved browser scenario" in page.locator("#scenario-status").inner_text()
    page.locator('[data-baseline-plot="calc-one"]').screenshot(
        path=str(SCREENSHOTS / f"{kind}.png")
    )
    assert page._dashboard_remote == []
    assert page._dashboard_errors == []


def test_occurrence_switch_restores_its_own_frozen_scene(open_dashboard):
    import copy

    value = overlay_data()
    occurrence = copy.deepcopy(value["occurrences"][0])
    occurrence.update(id="occ-two", version_label="Independent second occurrence")
    value["occurrences"].append(occurrence)
    for source in list(value["calls"]):
        item = copy.deepcopy(source)
        item.update(id="copy-" + source["id"], occurrence_id="occ-two")
        value["calls"].append(item)
    calculation = copy.deepcopy(value["calculations"][0])
    calculation.update(id="calc-two", occurrence_id="occ-two")
    value["calculations"].append(calculation)
    page = open_dashboard(value)
    first = page.locator('[data-baseline-plot="calc-one"]')
    second = page.locator('[data-baseline-plot="calc-two"]')
    initial = first.locator("[data-scenario-layer] path").get_attribute("d")
    page.locator("#calculation-select").select_option("calc-two")
    assert first.is_hidden()
    assert second.is_visible()
    assert second.locator("[data-map-layer]").count() == 0
    assert second.locator("[data-scenario-layer]").get_attribute("data-translation") == "[0,0]"
    page.locator("#calculation-select").select_option("calc-one")
    assert first.is_visible()
    assert second.is_hidden()
    assert first.locator("[data-scenario-layer] path").get_attribute("d") == initial
    assert first.locator("[data-scenario-layer]").get_attribute("data-translation") == "[1000,2000]"


def test_raster_outer_edges_follow_pixel_center_affine_and_controls(open_dashboard, tmp_path):
    value = overlay_data()
    import base64
    import hashlib
    import struct
    import zlib

    def chunk(kind, payload):
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload))
        )

    raw = b"\0\x30\x70\x90\xee\xee\xee\0\xee\xee\xee\x30\x70\x90"
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    digest = hashlib.sha256(png).hexdigest()
    value["map_sources"].append(
        {
            "id": "scan-source",
            "label": "Synthetic supplied scan",
            "filename": "synthetic.png",
            "sha256": digest,
            "native_units": "international_ft",
        }
    )
    value["raster_layers"] = [
        {
            "id": "scan",
            "label": "Synthetic scan",
            "scene_id": "map-scene",
            "source_id": "scan-source",
            "mime_type": "image/png",
            "width": 2,
            "height": 2,
            "sha256": digest,
            "data_base64": base64.b64encode(png).decode(),
            "registration": {"matrix": [0, 40, 1040, 40, 0, 2040], "method": "supplied_affine"},
        }
    ]
    page = open_dashboard(value)
    image = page.locator('[data-raster-layer="scan"]')
    assert image.count() == 1
    assert image.get_attribute("x") == "-0.5"
    assert image.get_attribute("y") == "-0.5"
    corners = image.evaluate(
        "node => [[-.5,-.5],[1.5,1.5]].map(([x,y])=>{const p=new DOMPoint(x,y).matrixTransform(node.getCTM()).matrixTransform(node.ownerSVGElement.getCTM().inverse());return [p.x,p.y];})"
    )
    assert corners[0] == pytest.approx([1020, -2020], abs=0.001)
    assert corners[1] == pytest.approx([1100, -2100], abs=0.001)
    before = page.locator('[data-baseline-layer="calc-one"]').inner_html()
    page.locator(".map-provenance summary").click()
    page.locator('[data-layer-toggle="scan"]').uncheck()
    assert page.locator('[data-map-layer="scan"]').is_hidden()
    assert page.locator('[data-map-layer="tax-map"]').is_visible()
    page.locator('[data-layer-toggle="scan"]').check()
    opacity = page.locator('[data-layer-opacity="scan"]')
    opacity.focus()
    opacity.press("Home")
    opacity.press("ArrowRight")
    assert page.locator('[data-map-layer="scan"]').evaluate("node=>node.style.opacity") == "0.05"
    assert page.locator('[data-baseline-layer="calc-one"]').inner_html() == before
    opacity.press("End")
    page.locator('[data-baseline-plot="calc-one"]').screenshot(path=str(SCREENSHOTS / "raster.png"))
    assert page._dashboard_remote == []
    assert page._dashboard_errors == []


def test_diagnostic_candidates_preserve_baseline_reset_and_source_occurrence(open_dashboard):
    value = fixture_data()
    value["calls"][0]["call"]["distance_ft"] = 100.5
    page = open_dashboard(value)
    baseline = page.locator("#baseline-diagnostics")
    scenario = page.locator("#scenario-diagnostics")
    baseline_html = baseline.inner_html()
    frozen = page.locator("#dashboard-data").text_content()
    assert "0.500" in baseline.inner_text()
    assert (
        baseline.locator('[data-diagnostic-call="call-one"]').get_attribute("data-distance-rank")
        == "1"
    )
    assert (
        baseline.locator('[data-diagnostic-call="call-three"]').get_attribute("data-distance-rank")
        == "1"
    )
    candidate = baseline.locator('[data-diagnostic-source="call-one"]')
    candidate.focus()
    candidate.press("Enter")
    assert page.locator("#source-viewer").evaluate("node => node.open")
    assert "call-one" in page.locator(".selected-source-detail").inner_text()
    assert page.locator(".selected-source-crop").get_attribute("alt") == "Synthetic first distance"
    page.locator("#viewer-close").click()
    page.locator('input[aria-label="call-one: Distance in feet"]').fill("100")
    assert "direction ranking unavailable" in scenario.inner_text().lower()
    assert baseline.inner_html() == baseline_html
    page.locator("#reset-record").click()
    assert "0.500" in scenario.inner_text()
    assert baseline.inner_html() == baseline_html
    assert page.locator("#dashboard-data").text_content() == frozen
    assert page._dashboard_errors == []
    assert page._dashboard_remote == []


def test_diagnostic_source_button_selects_current_occurrence_page(open_dashboard):
    import copy

    value = fixture_data()
    value["documents"][0]["expected_page_count"] = 2
    page_two = copy.deepcopy(value["pages"][0])
    page_two.update(id="page-two", number=2, label="Second occurrence source")
    value["pages"].append(page_two)
    occurrence = copy.deepcopy(value["occurrences"][0])
    occurrence.update(id="occ-two", version_label="Second occurrence", page_ids=["page-two"])
    value["occurrences"].append(occurrence)
    for original in list(value["calls"]):
        call = copy.deepcopy(original)
        call.update(id="copy-" + original["id"], occurrence_id="occ-two", page_id="page-two")
        value["calls"].append(call)
    calc = copy.deepcopy(value["calculations"][0])
    calc.update(id="calc-two", occurrence_id="occ-two")
    value["calculations"].append(calc)
    evidence = copy.deepcopy(value["evidence"][0])
    evidence.update(
        id="evidence-two",
        occurrence_id="occ-two",
        page_id="page-two",
        call_id="copy-call-one",
        label="Second occurrence crop",
    )
    value["evidence"].append(evidence)
    page = open_dashboard(value)
    page.locator("#calculation-select").select_option("calc-two")
    candidate = page.locator('#scenario-diagnostics [data-diagnostic-source="copy-call-one"]')
    candidate.click()
    assert "page 2" in page.locator("#viewer-label").inner_text()
    assert "copy-call-one" in page.locator(".selected-source-detail").inner_text()
    assert page.locator(".selected-source-crop").get_attribute("alt") == "Second occurrence crop"
    page.locator("#viewer-close").click()
    page.locator("#reset-record").click()
    page.locator('#baseline-diagnostics [data-diagnostic-source="copy-call-one"]').click()
    assert "page 2" in page.locator("#viewer-label").inner_text()
    assert page._dashboard_errors == []
