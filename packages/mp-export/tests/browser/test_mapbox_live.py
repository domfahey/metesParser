"""Opt-in actual provider visual gate; no token, trace, HAR, video or raw URL output."""

import io
import json
import os
from pathlib import Path

import pytest
from PIL import Image

pytestmark = pytest.mark.skipif(
    os.environ.get("METESPARSER_MAPBOX_LIVE_TESTS") != "1",
    reason="Live provider gate requires explicit opt-in and runtime public token",
)
ROOT = Path(__file__).resolve().parents[4]

HOOK = """(() => {
  let sdk;
  Object.defineProperty(window, 'mapboxgl', {configurable:true,
    get: () => sdk, set: value => {
      const Actual = value.Map;
      value.Map = class extends Actual {
        constructor(options) { super(options); window.__liveMap = this; }
      };
      sdk = value;
    }
  });
})();"""


def test_live_standard_satellite_visible_composition_attribution_and_sources(open_online):
    token = os.environ.get("MAPBOX_PUBLIC_TOKEN") or os.environ.get("MAPBOX_ACCESS_TOKEN", "")
    if not token.startswith("pk.") or any(character.isspace() for character in token):
        pytest.fail(
            "Live provider prerequisite missing: supply a public token through MAPBOX_PUBLIC_TOKEN or MAPBOX_ACCESS_TOKEN",
            pytrace=False,
        )
    page = open_online(stub=False, init=HOOK, serve=True, live=True)
    assert page._external == []
    try:
        # Evaluate avoids Playwright fill call logs that can include submitted values.
        page.evaluate(
            "value => { document.getElementById('map-token').value = value; document.getElementById('map-connection').requestSubmit(); }",
            token,
        )
    except Exception:
        pytest.fail(
            "Live provider connection interaction failed (details suppressed)", pytrace=False
        )
    finally:
        token = ""
    try:
        for style in ("standard", "standard-satellite"):
            page.get_by_test_id("map-style").select_option(style)
            page.wait_for_function(
                "() => document.querySelector('[data-testid=map-status]').textContent.startsWith('Map connected')",
                timeout=45000,
            )
            assert page.locator("#map-token").input_value() == ""
            assert page.locator(".mapboxgl-ctrl-attrib").count() == 1
            assert page.locator("a.mapboxgl-ctrl-logo").count() == 1

            # Real visible pixels, rather than source existence, prove overlay composition.
            def rendered_pixels():
                # Wait for a complete draw after controls change and exclude attribution UI.
                page.evaluate(
                    "() => new Promise(resolve => { const map=window.__liveMap; map.once('idle', resolve); map.triggerRepaint(); })"
                )
                image = Image.open(io.BytesIO(page.locator("#online-map").screenshot())).convert(
                    "RGB"
                )
                return image.crop((20, 20, image.width - 20, image.height - 70))

            pixels = rendered_pixels()
            rgb = list(pixels.getdata())
            blue = sum(abs(r) < 20 and abs(g - 105) < 20 and abs(b - 172) < 20 for r, g, b in rgb)
            orange = sum(r > b + 35 and r > g + 15 for r, g, b in rgb)
            assert blue > 30, "Recorded blue deed must be visibly composited"
            assert orange > 100, "Registered asymmetric scan must be visibly composited"
            # Remove every evidence layer, not just courses/scans, to isolate actual tiles.
            controls = page.locator("[data-map-layer]")
            for control in controls.all():
                control.uncheck()
            page.evaluate(
                "window.__liveMap.setLayoutProperty('review-selection', 'visibility', 'none')"
            )
            base = rendered_pixels()
            assert base.tobytes() != pixels.tobytes(), "Evidence must change the actual visible map"
            assert len(set(base.getdata())) > 200, (
                "Actual provider basemap must have visible detail away from controls"
            )
            for control in controls.all():
                control.check()
            page.evaluate(
                "window.__liveMap.setLayoutProperty('review-selection', 'visibility', 'visible')"
            )
            rendered_pixels()
            output = ROOT / "output/playwright/mapbox-live"
            output.mkdir(parents=True, exist_ok=True)
            page.locator("#online-map").screenshot(path=str(output / f"synthetic-{style}.png"))
        button = page.locator('[data-map-call="call-one"]')
        button.focus()
        button.press("Enter")
        assert button.get_attribute("aria-pressed") == "true"
        assert "Course 1: 100 feet." in page.get_by_test_id("map-source-panel").inner_text()
        assert page._external, "Actual provider requests are required in the live lane"
        assert page._errors == []
        assert any(key.endswith("/200") for key in page._provider_statuses)
        (output / "status-counts.json").write_text(
            json.dumps(page._provider_statuses, sort_keys=True)
        )
        page.get_by_test_id("map-disconnect").click()
        assert page.locator("#map-token").input_value() == ""
    except Exception:
        # Provider/browser exceptions may contain authenticated URLs; suppress all raw dumps.
        pytest.fail(
            "Live Mapbox visual/source acceptance failed; inspect the safe map-only screenshots and connection status manually",
            pytrace=False,
        )
