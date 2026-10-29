"""Pinned actual-SDK integration in token-free testMode; not live visual acceptance."""

import hashlib
import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("METESPARSER_MAPBOX_BROWSER_TESTS") != "1",
    reason="Run the explicit deterministic Mapbox browser target",
)
ROOT = Path(__file__).resolve().parents[4]


def sdk_script():
    descriptor = json.loads(
        (ROOT / "packages/mp-export/src/mp_export/dashboard_assets/mapbox-sdk.json").read_text()
    )
    cache = ROOT / ".uv-cache/mapbox" / ("v" + descriptor["version"])
    for name, spec in descriptor["files"].items():
        path = cache / name
        assert path.is_file(), "Pinned Mapbox SDK missing; run explicit SDK setup before the gate"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == spec["sha256"], (
            "Pinned Mapbox cache hash mismatch"
        )
    return (
        (cache / "mapbox-gl.js").read_text()
        + """
    window.__realMaps = [];
    window.__sdkErrorCount = 0;
    const localStyle = color => ({version:8, sources:{}, imports:[{id:'basemap', data:{
      version:8, schema:{show3dObjects:{type:'boolean', default:false}}, sources:{}, layers:[]
    }}], layers:[{id:'baseline', type:'background', paint:{'background-color':color}}]});
    const ActualMap = window.mapboxgl.Map;
    window.mapboxgl.Map = class extends ActualMap {
      constructor(options) {
        // Exercise the production renderer against real SDK sources/layers/worker/CSP.
        // Local style and token-free testMode deliberately cannot prove live visuals.
        super({...options, accessToken: '', testMode: true, localFontFamily: 'sans-serif',
          style: localStyle('#e6e3da')});
        this.on('error', () => window.__sdkErrorCount++);
        window.__realMaps.push(this);
      }
      setStyle(style, options) { return super.setStyle(localStyle('#dce6da'), options); }
    };
    """
    )


def test_pinned_sdk_local_style_sources_worker_and_reload(open_online):
    page = open_online(stub=False, init=sdk_script(), serve=True)
    assert page._external == []
    page.locator("#map-token").fill("pk.synthetic.local-sdk")
    page.get_by_test_id("map-connect").click()
    page.wait_for_function(
        "() => window.__realMaps.length === 1 && !!window.__realMaps[0].getLayer('review-selection')",
        timeout=15000,
    )
    assert page.evaluate("window.__realMaps[0].getProjection().name") == "mercator"
    assert (
        page.evaluate("window.__realMaps[0].getSource('review-recorded_course').type") == "geojson"
    )
    assert (
        page.evaluate("window.__realMaps[0].getStyle().layers.map(layer => layer.id)")[0]
        == "baseline"
    )
    page.locator('[data-map-call="call-one"]').click()
    assert (
        page.evaluate(
            "window.__realMaps[0].getSource('review-selection').serialize().data.features[0].properties.call_id"
        )
        == "call-one"
    )
    for style in ("standard-satellite", "standard"):
        page.get_by_test_id("map-style").select_option(style)
        page.wait_for_function(
            "() => !!window.__realMaps[0].getLayer('review-selection')", timeout=15000
        )
        assert (
            page.evaluate(
                "window.__realMaps[0].getStyle().layers.filter(layer => layer.id === 'review-recorded_course').length"
            )
            == 1
        )
    page.wait_for_function(
        "() => document.querySelector('[data-testid=map-status]').textContent.startsWith('Map connected')",
        timeout=15000,
    )
    assert page.evaluate("window.__sdkErrorCount") == 0
    assert page.evaluate("window.__realMaps[0].isSourceLoaded('review-recorded_course')")
    assert page._external == []
    assert page._errors == []
    page.get_by_test_id("map-disconnect").click()
    assert page.locator("#map-token").input_value() == ""
