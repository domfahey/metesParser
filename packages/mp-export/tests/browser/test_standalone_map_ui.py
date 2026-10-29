"""Standalone writer and offline fallback acceptance without provider requests."""

import hashlib
import os
import socket
import threading
from io import BytesIO
from urllib.parse import urlsplit

import pytest
from mp_models import DeedCall
from mp_models.plot import MapSource, PlotPlacement, PlotScene
from mp_models.plot_request import PlotCall, PlotRequest
from mp_models.raster import RasterLayer, RasterRegistration
from mp_models.webmap import StandaloneWebMapInput, WebMapRequest
from mp_review.map_preview import create_preview_server
from mp_review.online_map import render_map_file
from mp_verify.plot import prepare_plot

pytestmark = pytest.mark.skipif(
    os.environ.get("METESPARSER_MAPBOX_BROWSER_TESTS") != "1",
    reason="Run the explicit deterministic Mapbox browser target",
)

QUOTE = 'Original "course" <script>window.injected=true</script> & source words'


def supplied_map():
    """Only synthetic calls, scan and declared transform; no document reading."""
    import base64

    from PIL import Image

    plot = prepare_plot(
        PlotRequest(
            title="Supplied standalone parcel",
            calculation_id="boundary",
            foot_definition="international_ft",
            calls=tuple(
                PlotCall(
                    id=f"call-{number}",
                    quote=QUOTE if number == 1 else f"Original course {number}",
                    source_reference="Supplied Book 10 page 12",
                    page_id="supplied-page-reference" if number == 1 else None,
                    call=DeedCall(
                        course=number,
                        direction_text="Recorded direction",
                        bearing_azimuth_deg_from_north=bearing,
                        distance_ft=100,
                    ),
                )
                for number, bearing in enumerate((0, 90, 180, 270), 1)
            ),
        )
    )
    stream = BytesIO()
    Image.new("RGBA", (2, 2), (10, 80, 220, 128)).save(stream, format="PNG")
    content = stream.getvalue()
    digest = hashlib.sha256(content).hexdigest()
    x, y = -8236050, 4975300
    return StandaloneWebMapInput(
        title="Standalone synthetic map",
        plots=(plot,),
        scenes=(
            PlotScene(
                id="grid", name="Synthetic grid", kind="projected", crs="EPSG:3857", units="m"
            ),
        ),
        map_sources=(
            MapSource(
                id="scan-source",
                label="Supplied synthetic scan",
                filename="scan.png",
                sha256=digest,
                native_units="pixel",
            ),
        ),
        raster_layers=(
            RasterLayer(
                id="scan",
                label="Supplied synthetic scan",
                source_id="scan-source",
                scene_id="grid",
                width=2,
                height=2,
                mime_type="image/png",
                sha256=digest,
                data_base64=base64.b64encode(content).decode(),
                registration=RasterRegistration(
                    method="supplied_affine", matrix=(10, 0, x, 0, -10, y)
                ),
            ),
        ),
        placements=(
            PlotPlacement(
                id="placement",
                calculation_id="boundary",
                geometry_hash=plot.geometry.geometry_hash,
                scene_id="grid",
                translation=(x, y),
                rationale="Synthetic supplied transform",
            ),
        ),
    )


@pytest.fixture
def standalone_preview(tmp_path):
    value = supplied_map()
    original = value.model_dump_json()
    path = tmp_path / "map-input.json"
    path.write_text(original)
    directory = tmp_path / "display"
    result = render_map_file(path, directory, online_map=WebMapRequest(scene_id="grid"))
    assert result["status"] == "needs_review", result
    assert result["engine_verified"] is False and result["source_review_complete"] is False
    assert (directory / "map-evidence.html").is_file()
    assert not (directory / "dashboard.html").exists()
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    server = create_preview_server(directory, port=port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://localhost:{port}", directory, value
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert value.model_dump_json() == original


@pytest.mark.parametrize("width", [1200, 390])
def test_standalone_source_selection_and_served_offline_fallback(standalone_preview, width):
    from playwright.sync_api import sync_playwright

    origin, directory, value = standalone_preview
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context(viewport={"width": width, "height": 900})
        requests, errors = [], []

        def intercept(route):
            if route.request.url.startswith(("http:", "https:")) and urlsplit(
                route.request.url
            ).hostname not in {"localhost", "127.0.0.1"}:
                requests.append("external")
                route.abort()
            else:
                route.continue_()

        context.route("**/*", intercept)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        response = page.goto(origin + "/online-map.html")
        assert response.status == 200
        payload = page.locator("#online-map-data").text_content()
        page.locator('[data-map-call="call-1"]').click()
        source = page.get_by_test_id("map-source-panel")
        assert source.locator(".source-quote").inner_text() == QUOTE
        assert "Supplied Book 10 page 12" in source.inner_text()
        assert "Reading status unavailable" in source.inner_text()
        assert "undefined" not in source.inner_text()
        assert source.locator("button").count() == 0
        assert not page.evaluate("Boolean(window.injected)")
        assert page.locator("#online-map-data").text_content() == payload
        link = page.get_by_test_id("offline-link")
        assert link.get_attribute("href") == "map-evidence.html"
        link.click()
        page.wait_for_url(origin + "/map-evidence.html")
        assert "Source review not supplied" in page.locator("main").inner_text()
        assert page.locator("img").evaluate("img => img.naturalWidth") == 2
        frame = page.frame_locator("iframe")
        assert frame.locator('[data-call-row="call-1"] blockquote').inner_text() == QUOTE
        frame.locator('[data-call-row="call-1"] button').click()
        assert frame.locator('[data-call-row="call-1"]').evaluate(
            "row => row.classList.contains('selected')"
        )
        assert "local feet" in frame.locator("#plot-scale").inner_text()
        assert not page.evaluate("Boolean(window.injected)")
        assert not requests and not errors
        assert page.request.get(origin + "/source-map.json").status == 404
        assert page.request.get(origin + "/web-map-request.json").status == 404
        assert value.plots[0].request.calls[0].quote == QUOTE
        assert not (directory / "dashboard.html").exists()
        browser.close()
