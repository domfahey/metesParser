"""Standalone map views preserve supplied evidence without dashboard attestations."""

import base64
import hashlib
import html
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from mp_export.online_map_html import online_renderer_fingerprint, render_online_map
from mp_models import DeedCall
from mp_models.plot import MapSource, PlotScene
from mp_models.plot_request import PlotCall, PlotRequest
from mp_models.raster import RasterLayer, RasterRegistration
from mp_models.webmap import (
    MapboxViewOptions,
    StandaloneWebMapInput,
    WebMapArtifact,
    WebMapOptions,
)
from mp_verify.plot import prepare_plot
from mp_verify.webmap import normalize_web_map_context

ROOT = Path(__file__).resolve().parents[3]
UNSAFE = '</script><img src=x onerror="window.injected=true">&'
PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg=="


def supplied():
    image_hash = hashlib.sha256(base64.b64decode(PNG)).hexdigest()
    plot = prepare_plot(
        PlotRequest(
            title="Supplied plot",
            foot_definition="international_ft",
            calls=(
                PlotCall(
                    id="call-one",
                    source_reference="Book 10 page 12 " + UNSAFE,
                    page_id="actual-page-reference",
                    call=DeedCall(
                        course=1,
                        direction_text="Easterly " + UNSAFE,
                        distance_ft=100,
                    ),
                ),
            ),
        )
    )
    return StandaloneWebMapInput(
        title="Supplied map " + UNSAFE,
        plots=(plot,),
        scenes=(PlotScene(id="scene", name="Local scene", kind="local", units="m"),),
        map_sources=(
            MapSource(
                id="scan-source",
                label="Original scan " + UNSAFE,
                filename="scan.png",
                sha256=image_hash,
                native_units="pixel",
            ),
        ),
        raster_layers=(
            RasterLayer(
                id="scan",
                label="Original scan " + UNSAFE,
                source_id="scan-source",
                scene_id="scene",
                mime_type="image/png",
                width=1,
                height=1,
                sha256=image_hash,
                data_base64=PNG,
                registration=RasterRegistration(
                    method="supplied_affine", matrix=(1, 0, 0, 0, 1, 0)
                ),
            ),
        ),
    )


def unavailable(value):
    context = normalize_web_map_context(value)
    options = WebMapOptions()
    digest = hashlib.sha256(
        json.dumps(options.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return WebMapArtifact(
        scene_id="scene",
        input_hashes=context.input_hashes,
        options=options,
        options_sha256=digest,
        availability="unavailable",
    )


def test_standalone_shell_preserves_actual_calls_without_reading_or_page_claims():
    value = supplied()
    rendered = render_online_map(value, unavailable(value), view=MapboxViewOptions())
    payload = re.search(
        r'<script type="application/json" id="online-map-data">(.*?)</script>', rendered, re.S
    )[1]
    bundle = json.loads(payload)["bundle"]
    assert bundle["pages"] == []
    assert (
        bundle["calls"][0]["source_reference"] == value.plots[0].request.calls[0].source_reference
    )
    assert bundle["calls"][0]["call"]["bearing_azimuth_deg_from_north"] is None
    assert "reading_status" not in bundle["calls"][0]
    assert "source_review_complete" not in bundle
    assert 'href="map-evidence.html"' in rendered
    assert 'href="dashboard.html"' not in rendered
    assert "<" not in payload and "&" not in payload
    assert html.escape(UNSAFE) in rendered
    assert "No verified status is granted" in rendered


def test_offline_evidence_preserves_original_scan_registration_and_local_plot():
    from mp_export import render_map_evidence

    value = supplied()
    before = value.model_dump_json()
    rendered = render_map_evidence(value)
    assert rendered == render_map_evidence(value)
    assert value.model_dump_json() == before
    assert f'src="data:image/png;base64,{PNG}"' in rendered
    assert "supplied_affine" in rendered and "integer_pixel_centers" in rendered
    assert "checkpoint_rms" in rendered and "null" in rendered
    assert "Source review not supplied" in rendered
    assert "No verified status is granted" in rendered
    assert UNSAFE not in rendered
    assert 'sandbox="allow-scripts"' in rendered
    assert "allow-same-origin" not in rendered
    embedded = html.unescape(re.search(r'srcdoc="(.*?)"', rendered, re.S)[1])
    assert "Unresolved bearing" in embedded
    assert html.escape(value.plots[0].request.calls[0].source_reference) in embedded
    assert "<script src=" not in rendered and "<link " not in rendered
    assert "connect-src &#x27;none&#x27;" in rendered


def test_offline_evidence_omits_exif_oriented_raster_with_reason():
    import io

    from mp_export import render_map_evidence
    from mp_models.raster import RASTER_ORIENTATION_MESSAGE
    from PIL import Image

    image = Image.new("RGB", (1, 1))
    exif = Image.Exif()
    exif[274] = 6
    stream = io.BytesIO()
    image.save(stream, format="JPEG", exif=exif.tobytes())
    data = stream.getvalue()
    value = supplied()
    digest = hashlib.sha256(data).hexdigest()
    layer = value.raster_layers[0].model_copy(
        update={
            "mime_type": "image/jpeg",
            "sha256": digest,
            "data_base64": base64.b64encode(data).decode(),
        }
    )
    source = value.map_sources[0].model_copy(update={"sha256": digest, "filename": "scan.jpg"})
    value = value.model_copy(update={"raster_layers": (layer,), "map_sources": (source,)})
    rendered = render_map_evidence(value)
    assert "raster_orientation" in rendered
    assert html.escape(RASTER_ORIENTATION_MESSAGE) in rendered
    assert "data:image/jpeg;base64" not in rendered


def test_offline_evidence_rejects_stale_plot_before_rendering():
    from mp_export import render_map_evidence

    value = supplied()
    changed = value.plots[0].model_copy(update={"input_hash": "0" * 64})
    with pytest.raises(ValueError, match="freshly|stale"):
        render_map_evidence(value.model_copy(update={"plots": (changed,)}))


def test_fingerprint_changes_with_offline_evidence_renderer_and_plot_assets(monkeypatch):
    original = Path.read_bytes
    before = online_renderer_fingerprint()
    for filename in ("map_evidence_html.py", "plot_html.py", "plot_svg.py", "plot.js", "plot.css"):
        with monkeypatch.context() as patch:
            patch.setattr(
                Path,
                "read_bytes",
                lambda path, target=filename: original(path)
                + (b" " if path.name == target else b""),
            )
            assert online_renderer_fingerprint() != before


def test_source_selection_without_reading_status_or_page_uses_actual_reference():
    node = shutil.which("node")
    assert node
    script = (ROOT / "packages/mp-export/src/mp_export/dashboard_assets/online_map.js").read_text()
    function = (
        "function selectCall(callId) {"
        + script.split("function selectCall(callId) {", 1)[1].split(
            '\n  document.querySelectorAll("[data-map-call]")', 1
        )[0]
    )
    harness = """
const assert = require('node:assert/strict');
let selected=null, map=null;
const bundle={pages:[],calls:[{id:'course',quote:'',source_reference:'Book 10 page 12',call:{direction_text:'East 100 feet'}}]};
const artifact={features:[]};
const panel={items:[],replaceChildren(){this.items=[]}};
const text=(tag,content,parent)=>{const e={tag,content,addEventListener(){}};parent.items.push(e);return e};
const document={querySelectorAll(){return []}};
const showPage=()=>{throw Error('No source page supplied')};
"""
    assertions = """
selectCall('course');
const textContent=panel.items.map(e=>e.content).join(' ');
assert(textContent.includes('Book 10 page 12'));
assert(textContent.includes('East 100 feet'));
assert(textContent.includes('Reading status unavailable'));
assert(!textContent.includes('undefined'));
assert(!panel.items.some(e=>e.tag==='button'));
"""
    subprocess.run(
        [node, "-e", harness + function + assertions], check=True, capture_output=True, text=True
    )
