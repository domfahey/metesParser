"""Deterministic Chromium adapter acceptance; no live-provider or WebGL claim."""

import hashlib
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("METESPARSER_MAPBOX_BROWSER_TESTS") != "1",
    reason="Run the explicit deterministic Mapbox browser target",
)


def connect(page):
    # A synthetic, noncredential public-token shaped value is never provider-valid.
    page.locator("#map-token").fill("pk.synthetic.browser-control")
    page.get_by_test_id("map-connect").click()
    page.wait_for_function("() => window.__maps.length === 1 && window.__maps[0].layers.length > 0")


def unchanged(page):
    assert (
        hashlib.sha256(page.locator("#online-map-data").text_content().encode()).hexdigest()
        == page._baseline_hash
    )
    assert page._errors == []


@pytest.mark.parametrize("width", [1200, 390])
def test_no_activation_before_connect_and_keyboard_source_fallback(open_online, width):
    page = open_online(width=width)
    assert page._external == []
    assert page.evaluate("window.__maps.length") == 0
    assert page.evaluate("localStorage.length + sessionStorage.length") == 0
    button = page.locator('[data-map-call="call-one"]')
    button.focus()
    button.press("Enter")
    assert button.get_attribute("aria-pressed") == "true"
    assert "Course 1: 100 feet." in page.get_by_test_id("map-source-panel").inner_text()
    trigger = page.get_by_role("button", name="Open original source page")
    trigger.click()
    assert page.locator("#map-page-dialog").evaluate("node => node.open")
    assert page.get_by_alt_text("Original source page 1").count() == 1
    page.get_by_role("button", name="Close source page").click()
    assert trigger.evaluate("node => node === document.activeElement")
    assert page.locator("body").evaluate("node => node.scrollWidth <= innerWidth")
    assert page._external == []
    unchanged(page)


@pytest.mark.parametrize("token", ["", "sk.synthetic-rejected", "pk.invalid token"])
def test_invalid_token_is_cleared_without_activation(open_online, token):
    page = open_online()
    page.locator("#map-token").fill(token)
    page.get_by_test_id("map-connect").click()
    assert "public Mapbox token" in page.get_by_test_id("map-status").inner_text()
    assert page.locator("#map-token").input_value() == ""
    assert page.evaluate("window.__maps.length") == 0
    assert page._external == []
    unchanged(page)


def test_layers_opacity_styles_selection_disconnect_and_retry(open_online):
    page = open_online()
    connect(page)
    ids = page.evaluate("window.__maps[0].layers.map(item => item.id)")
    assert ids[0].startswith("review-")
    assert ids[1:] == [
        "review-parcel_context",
        "review-recorded_course",
        "review-course-labels",
        "review-pob",
        "review-closure_gap",
        "review-selection",
    ]
    assert page.locator("#map-token").input_value() == ""
    assert page.evaluate("[localStorage.length, sessionStorage.length]") == [0, 0]
    for value in (0, 0.5, 1):
        page.locator("#map-opacity").evaluate(
            "(node, value) => { node.value = value; node.dispatchEvent(new Event('input', {bubbles:true})); }",
            value,
        )
        assert page.evaluate("window.__maps[0].layers[0].paint['raster-opacity']") == value
    page.locator('[data-map-layer="recorded_course"]').uncheck()
    page.locator('[data-map-call="call-one"]').click()
    for style in ("standard-satellite", "standard", "standard-satellite", "standard"):
        page.get_by_test_id("map-style").select_option(style)
        assert page.evaluate("window.__maps[0].layers.map(item => item.id)") == ids
        assert (
            page.evaluate("window.__maps[0].getLayer('review-recorded_course').layout.visibility")
            == "none"
        )
        assert (
            page.evaluate("window.__maps[0].getLayer('review-course-labels').layout.visibility")
            == "none"
        )
        assert (
            page.evaluate(
                "window.__maps[0].getSource('review-selection').data.features[0].properties.call_id"
            )
            == "call-one"
        )
    assert page.evaluate(
        "Object.values(window.__maps[0].handlers).every(items => items.length === 1)"
    )
    page.evaluate("window.__maps[0].fire('click', {point:{x:1,y:1}})")
    assert page.locator('[data-map-call="call-one"]').get_attribute("aria-pressed") == "true"
    page.get_by_test_id("map-disconnect").click()
    assert page.evaluate(
        "window.__maps[0].removed && window.__maps[0].accessToken === '' && window.mapboxgl.accessToken === ''"
    )
    page.locator("#map-token").fill("pk.synthetic.retry")
    page.get_by_test_id("map-connect").click()
    page.wait_for_function("() => window.__maps.length === 2 && window.__maps[1].layers.length > 0")
    assert page.evaluate("window.__maps.filter(item => !item.removed).length") == 1
    assert page._external == []
    unchanged(page)


@pytest.mark.parametrize("failure", ["401", "403", "network", "style"])
def test_provider_errors_are_sanitized_and_local_records_remain(open_online, failure):
    page = open_online()
    connect(page)
    page.evaluate(
        "failure => window.__maps[0].fire('error', {error: new Error(failure + ' pk.synthetic.private-error')})",
        failure,
    )
    status = page.get_by_test_id("map-status").inner_text()
    assert "unavailable" in status and "pk." not in status
    assert "pk.synthetic" not in page.locator("body").inner_text()
    page.locator('[data-map-call="call-one"]').click()
    assert "Course 1: 100 feet." in page.get_by_test_id("map-source-panel").inner_text()
    assert page.get_by_test_id("offline-link").get_attribute("href") == "dashboard.html"
    unchanged(page)


def test_webgl_loss_and_unsupported_recover_without_duplicates(open_online):
    page = open_online()
    connect(page)
    page.evaluate("window.__maps[0].fire('webglcontextlost')")
    assert "WebGL context lost" in page.get_by_test_id("map-status").inner_text()
    assert page.evaluate("window.__maps[0].removed")
    page.evaluate("window.mapboxgl.supported = () => false")
    page.locator("#map-token").fill("pk.synthetic.unsupported")
    page.get_by_test_id("map-connect").click()
    page.wait_for_function(
        "() => document.querySelector('[data-testid=map-status]').textContent.includes('Map unavailable')"
    )
    assert page.evaluate("window.__maps.length") == 1
    unchanged(page)


def test_sdk_blocked_network_and_timeout_clear_token_and_allow_retry(open_online):
    page = open_online(stub=False)
    assert page._external == []
    page.locator("#map-token").fill("pk.synthetic.blocked")
    page.get_by_test_id("map-connect").click()
    page.wait_for_function(
        "() => document.querySelector('[data-testid=map-status]').textContent.includes('Map unavailable')"
    )
    assert len(page._external) > 0
    assert page.locator("#map-token").input_value() == ""
    assert page.get_by_test_id("map-connect").is_enabled()
    unchanged(page)
    waiting = open_online(
        init="window.__timers=[]; const saved=setTimeout; window.setTimeout=(fn, delay, ...rest) => delay===30000 ? (window.__timers.push(fn), 1) : saved(fn,delay,...rest)"
    )
    # Hold SDK resolution so the real application timeout controls teardown.
    waiting.evaluate("delete window.mapboxgl")
    waiting.route("https://api.mapbox.com/**", lambda route: None)
    waiting.locator("#map-token").fill("pk.synthetic.timeout")
    waiting.get_by_test_id("map-connect").click()
    waiting.evaluate("window.__timers[0]()")
    assert "timed out" in waiting.get_by_test_id("map-status").inner_text()
    assert waiting.get_by_test_id("map-connect").is_enabled()
    assert waiting.locator("#map-token").input_value() == ""


def test_missing_geographic_placement_retains_sources_without_guess(open_online):
    page = open_online(unavailable=True)
    assert "unavailable" in page.get_by_test_id("map-status").inner_text()
    page.locator("#map-token").fill("pk.synthetic.unavailable")
    page.get_by_test_id("map-connect").click()
    assert page.evaluate("window.__maps.length") == 0
    page.locator('[data-map-call="call-one"]').click()
    assert "Geographic course unavailable" in page.get_by_test_id("map-source-panel").inner_text()
    assert page._external == []
    unchanged(page)


def test_missing_source_image_is_explicit_in_panel_and_dialog(open_online):
    page = open_online(missing_page=True)
    page.locator('[data-map-call="call-one"]').click()
    assert "Source image unavailable" in page.get_by_test_id("map-source-panel").inner_text()
    page.get_by_role("button", name="Open original source page").click()
    assert "no image was supplied" in page.locator("#map-page-content").inner_text()
    assert page.locator("#map-page-content img").count() == 0
    unchanged(page)


def test_layer_setup_failure_cannot_be_announced_as_connected(open_online):
    page = open_online()
    page.evaluate(
        "() => { window.mapboxgl.Map.prototype.addLayer = () => { throw new Error('synthetic setup failure'); }; }"
    )
    page.locator("#map-token").fill("pk.synthetic.layer-failure")
    page.get_by_test_id("map-connect").click()
    page.wait_for_function("() => window.__maps.length === 1")
    page.evaluate("window.__maps[0].fire('style.load')")
    page.evaluate("window.__maps[0].fire('idle')")
    assert "could not load review layers" in page.get_by_test_id("map-status").inner_text()
    assert "Map connected" not in page.get_by_test_id("map-status").inner_text()
    unchanged(page)


def test_style_load_does_not_claim_ready_while_visible_tiles_are_missing(open_online):
    page = open_online()
    connect(page)
    page.evaluate(
        "() => { const map=window.__maps[0]; map.tilesMissing=true; map.fire('style.load'); map.fire('idle'); }"
    )
    assert "Waiting for visible tiles" in page.get_by_test_id("map-status").inner_text()
    assert "Map connected" not in page.get_by_test_id("map-status").inner_text()
    page.evaluate("() => { const map=window.__maps[0]; map.tilesMissing=false; map.fire('idle'); }")
    assert "Map connected" in page.get_by_test_id("map-status").inner_text()
    unchanged(page)
