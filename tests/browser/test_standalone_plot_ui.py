"""Offline Chromium behavior for the reusable standalone plot artifact."""

import os

import pytest
from mp_export.plot_html import render_plot
from mp_models.deed_call import DeedCall
from mp_models.plot_request import PlotCall, PlotRequest
from mp_verify.plot import prepare_plot

pytestmark = pytest.mark.skipif(
    os.environ.get("METESPARSER_BROWSER_TESTS") != "1",
    reason="Explicit browser target installs/preflights Chromium",
)


@pytest.mark.parametrize("width,theme", [(1200, "light"), (400, "dark")])
def test_source_selection_view_controls_and_offline_delivery(tmp_path, width, theme):
    from playwright.sync_api import sync_playwright

    request = PlotRequest(
        title="Standalone synthetic parcel",
        calls=tuple(
            PlotCall(
                id=f"course-{index}",
                quote=f"Original wording {index}",
                call=DeedCall(
                    course=index,
                    direction_text="Recorded course",
                    bearing_azimuth_deg_from_north=bearing,
                    distance_ft=100,
                ),
            )
            for index, bearing in enumerate([0, 90, 180, 270], 1)
        ),
    )
    prepared = prepare_plot(request)
    original_input = prepared.model_dump_json()
    delivery = tmp_path / "plot.html"
    delivery.write_text(render_plot(prepared))
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context(viewport={"width": width, "height": 900}, color_scheme=theme)
        requests, errors = [], []

        def intercept(route):
            if route.request.url.startswith(("http:", "https:")):
                requests.append(route.request.url)
                route.abort()
            else:
                route.continue_()

        context.route("**/*", intercept)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(delivery.as_uri())
        path = page.locator('[data-plot-call="course-1"]')
        assert path.evaluate("node => node.getTotalLength()") == pytest.approx(100)
        path.focus()
        path.press("Enter")
        assert page.locator('[data-call-row="course-1"]').evaluate(
            "node => node.classList.contains('selected')"
        )
        assert "Original wording 1" in page.locator("#source-status").inner_text()
        page.locator('button[data-source-call="course-2"]').click()
        assert page.locator('[data-plot-call="course-2"]').get_attribute("aria-pressed") == "true"
        plot = page.locator("#plot")
        initial = plot.get_attribute("viewBox")
        geometry = page.locator("#record-geometry").inner_html()
        page.locator("#plot-zoom-in").click()
        assert plot.get_attribute("viewBox") != initial
        plot.focus()
        plot.press("ArrowRight")
        pan = plot.get_attribute("viewBox")
        plot.press("ArrowDown")
        assert plot.get_attribute("viewBox") != pan
        plot.scroll_into_view_if_needed()
        box = plot.bounding_box()
        page.mouse.move(box["x"] + box["width"] - 10, box["y"] + box["height"] - 10)
        page.mouse.down()
        page.mouse.move(box["x"] + box["width"] - 40, box["y"] + box["height"] - 30)
        page.mouse.up()
        assert plot.get_attribute("viewBox") != pan
        page.locator("#plot-fit").click()
        assert plot.get_attribute("viewBox") == initial
        page.locator("#plot-zoom-out").click()
        page.locator("#plot-reset").click()
        assert plot.get_attribute("viewBox") == initial
        page.locator("#plot-labels").uncheck()
        assert page.locator(".course-label").first.is_hidden()
        assert page.locator("#record-geometry").inner_html() == geometry
        assert page.locator("body").evaluate("node => node.scrollWidth <= window.innerWidth")
        assert "ft" in page.locator("#plot-scale").inner_text()
        assert page.locator("img").count() == 0
        assert requests == []
        assert errors == []
        context.close()
        browser.close()
    assert prepared.model_dump_json() == original_input
