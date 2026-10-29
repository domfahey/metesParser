"""Browser-only synthetic inputs; never use property sources or persist credentials."""

import hashlib
import json
import os
import socket
import threading
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from mp_export.online_map_html import render_online_map
from mp_models.dashboard import DashboardBundle
from mp_models.webmap import MapboxViewOptions, WebMapOptions
from mp_review.dashboard import prepare_dashboard
from mp_review.webmap import prepare_web_map

ROOT = Path(__file__).resolve().parents[4]


def synthetic_map(*, two_rasters=False, poor_checkpoint=False, raster_labels=None):
    """Use supplied projected placement and an asymmetric registered synthetic scan."""
    from io import BytesIO

    from mp_models.plot import PlotScene
    from mp_models.raster import RasterControl
    from mp_review.raster_registration import image_layer, supplied_affine
    from PIL import Image

    data = json.loads(
        (ROOT / "packages/mp-review/tests/fixtures/dashboard-absolute.json").read_text()
    )
    data["schema_version"] = "1.1"
    data["scenarios"] = []
    data["calculations"][0]["frame"]["foot_definition"] = "international_ft"
    initial = prepare_dashboard(DashboardBundle.model_validate(data))
    x, y = -8236050, 4975300  # Known land coordinate; all evidence is synthetic.
    data["scenes"] = [
        {"id": "grid", "name": "Synthetic", "kind": "projected", "units": "m", "crs": "EPSG:3857"}
    ]
    data["placements"] = [
        {
            "id": "placement",
            "calculation_id": "calc-one",
            "geometry_hash": initial.plots.geometries[0].geometry_hash,
            "scene_id": "grid",
            "rotation_deg": 0,
            "translation": [x, y],
            "status": "approximate",
            "rationale": "Synthetic browser control",
        }
    ]
    stream = BytesIO()
    image = Image.new("RGBA", (8, 8), (240, 80, 20, 180))
    image.putpixel((0, 0), (0, 200, 50, 255))
    image.save(stream, format="PNG")
    controls = ()
    if poor_checkpoint:
        controls = tuple(
            RasterControl(id=identifier, pixel=pixel, scene=scene, role=role)
            for identifier, pixel, scene, role in (
                ("fit-a", (0, 0), (x - 10, y + 35), "fit"),
                ("fit-b", (7, 0), (x + 25, y + 35), "fit"),
                ("fit-c", (0, 7), (x - 10, y), "fit"),
                ("check", (7, 7), (x + 35, y), "checkpoint"),
            )
        )
    layer, source = image_layer(
        stream.getvalue(),
        scene=PlotScene.model_validate(data["scenes"][0]),
        registration=supplied_affine((5, 0, x - 10, 0, -5, y + 35), controls),
        filename="synthetic.png",
    )
    data["map_sources"] = [source.model_dump(mode="json")]
    data["raster_layers"] = [layer.model_dump(mode="json")]
    if two_rasters:
        second = BytesIO()
        Image.new("RGBA", (8, 8), (20, 80, 240, 180)).save(second, format="PNG")
        second_layer, second_source = image_layer(
            second.getvalue(),
            scene=PlotScene.model_validate(data["scenes"][0]),
            registration=supplied_affine((5, 0, x - 10, 0, -5, y + 35)),
            filename="blue-scan.png",
        )
        data["map_sources"].append(second_source.model_dump(mode="json"))
        data["raster_layers"].append(second_layer.model_dump(mode="json"))
    if raster_labels is not None:
        assert len(raster_labels) == len(data["raster_layers"])
        for raster, label in zip(data["raster_layers"], raster_labels, strict=True):
            raster["label"] = label
            next(source for source in data["map_sources"] if source["id"] == raster["source_id"])[
                "label"
            ] = label
    data["vector_layers"] = [
        {
            "id": "parcel",
            "label": "Synthetic parcel",
            "scene_id": "grid",
            "source_id": source.id,
            "geometry_type": "Polygon",
            "coordinates": [
                [
                    [x - 10, y - 10],
                    [x + 40, y - 10],
                    [x + 40, y + 40],
                    [x - 10, y + 40],
                    [x - 10, y - 10],
                ]
            ],
        }
    ]
    prepared = prepare_dashboard(DashboardBundle.model_validate(data))
    result = prepare_web_map(prepared, scene_id="grid", options=WebMapOptions())
    return prepared, result


@pytest.fixture
def open_online(tmp_path):
    from playwright.sync_api import sync_playwright

    prepared, result = synthetic_map()
    before = prepared.model_dump_json(), result.artifact.model_dump_json()
    html = render_online_map(prepared, result.artifact, view=MapboxViewOptions())
    delivery = tmp_path / "online-map.html"
    delivery.write_text(html)
    for name, contents in result.assets:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
    from mp_export.dashboard_html import render_dashboard
    from mp_review.map_preview import create_preview_server

    (tmp_path / "dashboard.html").write_text(render_dashboard(prepared))
    files = [delivery, tmp_path / "dashboard.html", *(tmp_path / name for name, _ in result.assets)]
    (tmp_path / "web-map-manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "files": {
                    str(path.relative_to(tmp_path)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in files
                },
            }
        )
    )
    # Resolve an ephemeral port, then enforce the production localhost/allowlist policy.
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    if os.environ.get("METESPARSER_MAPBOX_LIVE_TESTS") == "1":
        port = int(os.environ.get("MAPBOX_PREVIEW_PORT", "8765"))
    server = create_preview_server(tmp_path, port=port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        contexts = []

        def open_page(
            *,
            width=1200,
            stub=True,
            init=None,
            unavailable=False,
            missing_page=False,
            live=False,
            serve=False,
            two_rasters=False,
            poor_checkpoint=False,
            raster_labels=None,
        ):
            context = browser.new_context(viewport={"width": width, "height": 900})
            contexts.append(context)
            if stub:
                context.add_init_script(path=Path(__file__).with_name("mapbox_stub.js"))
            if init:
                context.add_init_script(script=init)
            requests, errors, provider_statuses = [], [], {}

            def intercept(route):
                if route.request.url.startswith(("http:", "https:")) and urlsplit(
                    route.request.url
                ).hostname not in {"localhost", "127.0.0.1"}:
                    # Deliberately never store a raw URL, query, token, trace, HAR or video.
                    requests.append("external")
                    if live:
                        route.continue_()
                    else:
                        route.abort()
                else:
                    route.continue_()

            context.route("**/*", intercept)
            page = context.new_page()
            page.on("pageerror", lambda _: errors.append("pageerror"))

            def record_response(response):
                parsed = urlsplit(response.url)
                if parsed.hostname not in {"api.mapbox.com", "events.mapbox.com"}:
                    return
                category = (
                    "sdk"
                    if "/mapbox-gl-js/" in parsed.path
                    else "style"
                    if "/styles/" in parsed.path
                    else "provider-data"
                )
                key = f"{parsed.hostname}/{category}/{response.status}"
                provider_statuses[key] = provider_statuses.get(key, 0) + 1

            page.on("response", record_response)
            if two_rasters or poor_checkpoint or raster_labels is not None:
                multi, multi_map = synthetic_map(
                    two_rasters=two_rasters,
                    poor_checkpoint=poor_checkpoint,
                    raster_labels=raster_labels,
                )
                multi_path = tmp_path / "multi.html"
                multi_path.write_text(
                    render_online_map(multi, multi_map.artifact, view=MapboxViewOptions())
                )
                for name, content in multi_map.assets:
                    asset = tmp_path / name
                    asset.parent.mkdir(parents=True, exist_ok=True)
                    asset.write_bytes(content)
                page.goto(multi_path.as_uri())
            elif unavailable or missing_page:
                local = prepared.bundle.model_dump(mode="json")
                if unavailable:
                    local["placements"] = []
                    local["raster_layers"] = []
                    local["vector_layers"] = []
                if missing_page:
                    for source_page in local["pages"]:
                        source_page["image"] = None
                        source_page["image_sha256"] = None
                off = prepare_dashboard(DashboardBundle.model_validate(local))
                missing = prepare_web_map(off, scene_id="grid", options=WebMapOptions())
                missing_path = tmp_path / "unavailable.html"
                missing_path.write_text(
                    render_online_map(off, missing.artifact, view=MapboxViewOptions())
                )
                page.goto(missing_path.as_uri())
            else:
                page.goto(
                    f"http://localhost:{port}/online-map.html" if serve else delivery.as_uri()
                )
            page._provider_statuses = provider_statuses
            page._external = requests
            page._errors = errors
            page._baseline_hash = hashlib.sha256(
                page.locator("#online-map-data").text_content().encode()
            ).hexdigest()
            return page

        yield open_page
        for context in contexts:
            context.close()
        browser.close()
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    assert before == (prepared.model_dump_json(), result.artifact.model_dump_json())
