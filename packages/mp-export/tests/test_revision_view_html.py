"""Offline revision view retains raw evidence and isolated reusable plots."""

import base64
import json
import os
from html.parser import HTMLParser
from pathlib import Path

import pytest
from mp_export.revision_html import render_revision
from mp_models.dashboard import DashboardBundle
from mp_models.revisions import revision_template
from mp_review.revisions import import_revision

ROOT = Path(__file__).resolve().parents[3]


def fixture(draft=False):
    bundle = DashboardBundle.model_validate_json(
        (ROOT / "packages/mp-review/tests/fixtures/dashboard-absolute.json").read_bytes()
    )
    data = revision_template(
        bundle, revision_id="view-revision", label="Selected <alternative>"
    ).model_dump(mode="json")
    data["edits"] = [
        {
            "call_id": "call-one",
            "occurrence_id": "occ-one",
            "tract_id": "parcel-one",
            "document_id": "doc-one",
            "raw_fields": {
                "notes": "  </script><img src=x onerror=alert(1)>\n",
                "distance_ft": "unresolved" if draft else "101",
            },
        }
    ]
    return bundle, import_revision(bundle, data)


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.frames = []
        self.download = None
        self.remote = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "iframe":
            self.frames.append(attrs)
        if attrs.get("download") == "revision.json":
            self.download = attrs.get("href")
        for name in ("src", "href"):
            value = attrs.get(name, "")
            if value.startswith(("http:", "https:")):
                self.remote.append(value)


def test_rendered_view_links_original_selected_raw_and_exact_download():
    bundle, prepared = fixture()
    raw = (json.dumps(prepared.revision.model_dump(mode="json"), indent=3) + "\n").encode()
    rendered = render_revision(bundle, prepared, draft_bytes=raw)
    parsed = Page()
    parsed.feed(rendered)
    assert base64.b64decode(parsed.download.split(",", 1)[1]) == raw
    assert len(parsed.frames) == 2  # current and separately labeled baseline fallback
    assert all(frame["sandbox"] == "allow-scripts" for frame in parsed.frames)
    assert all("record-geometry" in frame["srcdoc"] for frame in parsed.frames)
    assert "Selected &lt;alternative&gt;" in rendered
    assert "&lt;/script&gt;&lt;img src=x onerror=alert(1)&gt;" in rendered
    assert not parsed.remote
    assert "Original source" in rendered and "Selected call" in rendered
    assert "raw_input" in rendered and "page-one" in rendered
    assert "<h3>Selected call</h3><p>Course 1:" in rendered
    assert "&lt;p&gt;Course" not in rendered


def test_draft_never_presents_last_valid_as_current_geometry():
    bundle, prepared = fixture(draft=True)
    rendered = render_revision(bundle, prepared)
    parsed = Page()
    parsed.feed(rendered)
    assert len(parsed.frames) == 1
    assert parsed.frames[0]["data-revision-id"] == "baseline"
    assert "Current geometry unavailable" in rendered
    assert "Last valid geometry" in rendered
    assert "unresolved" in rendered


@pytest.mark.skipif(
    os.environ.get("METESPARSER_BROWSER_TESTS") != "1", reason="Explicit offline browser gate"
)
@pytest.mark.parametrize("with_corridor", [False, True])
def test_srcdoc_csp_plot_controls_and_download_in_chromium(tmp_path, with_corridor):
    from playwright.sync_api import sync_playwright

    bundle, prepared = corridor_fixture() if with_corridor else fixture()
    raw = json.dumps(prepared.revision.model_dump(mode="json"), indent=3).encode()
    target = tmp_path / "revision.html"
    target.write_text(render_revision(bundle, prepared, draft_bytes=raw))
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        errors = []
        requests = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: requests.append(request.url))
        page.goto(target.as_uri())
        frame = page.locator('iframe[data-view="current"]').content_frame
        plot = frame.locator("#plot")
        page.locator('iframe[data-view="last-valid"]').content_frame.locator("#plot").wait_for(
            state="visible"
        )
        initial = plot.get_attribute("viewBox")
        frame.get_by_role("button", name="Zoom in", exact=True).click()
        assert plot.get_attribute("viewBox") != initial
        if with_corridor:
            corridor = page.locator('iframe[data-view="corridor-boundary"]').content_frame
            corridor_plot = corridor.locator("#plot")
            corridor_initial = corridor_plot.get_attribute("viewBox")
            corridor.get_by_role("button", name="Zoom in", exact=True).click()
            assert corridor_plot.get_attribute("viewBox") != corridor_initial
        with page.expect_download() as download:
            page.get_by_role("link", name="Download draft", exact=True).click()
        assert Path(download.value.path()).read_bytes() == raw
        assert not errors
        assert not any(url.startswith(("http:", "https:")) for url in requests)
        page.locator('iframe[data-view="last-valid"]').scroll_into_view_if_needed()
        page.locator("#current-geometry").screenshot(path=str(tmp_path / "revision-current.png"))
        page.locator("#last-valid-geometry").screenshot(
            path=str(tmp_path / "revision-last-valid.png")
        )
        page.screenshot(path=str(tmp_path / "revision-view.png"), full_page=True)
        browser.close()


def test_revision_arc_uses_shared_analytic_svg_path():
    bundle, _ = fixture()
    data = revision_template(bundle, revision_id="curve-view").model_dump(mode="json")
    data["schema_version"] = "1.1"
    data["edits"] = [
        {
            "call_id": "call-one",
            "occurrence_id": "occ-one",
            "tract_id": "parcel-one",
            "document_id": "doc-one",
            "structured_input": {
                "geometry_type": "circular_arc",
                "role": "boundary",
                "orientation": "supplied",
                "bearing_format": "decimal_azimuth",
                "bearing_value": "0",
                "distance_unit": "feet",
                "radius_value": "10",
                "delta_format": "decimal_degrees",
                "delta_value": "180",
                "curve_dir": "right",
            },
        }
    ]
    prepared = import_revision(bundle, data)
    assert prepared.state == "parsed"
    page = Page()
    page.feed(render_revision(bundle, prepared))
    assert " A " in page.frames[0]["srcdoc"]
    assert prepared.current_geometry[0].plot.geometry.primitives[0].kind == "arc"


def corridor_fixture(raw=None):
    bundle, _ = fixture()
    data = revision_template(bundle, revision_id="corridor-view").model_dump(mode="json")
    data["schema_version"] = "1.2"
    if raw is None:
        request = json.loads(
            (ROOT / "plugins/metesparser/skills/plot-corridor/references/example.json").read_text()
        )
        request["id"] = "retained-corridor"
        raw = json.dumps(request, indent=3) + "\n"
    data["corridors"] = [{"id": "retained-corridor", "action": "retain", "raw_request_json": raw}]
    return bundle, import_revision(bundle, data)


def test_revision_view_displays_saved_corridor_geometry_and_lossless_definition():
    bundle, prepared = corridor_fixture()
    rendered = render_revision(bundle, prepared)
    page = Page()
    page.feed(rendered)
    frames = [frame for frame in page.frames if frame["data-view"].startswith("corridor-")]
    assert {frame["data-view"] for frame in frames} == {
        "corridor-centerline",
        "corridor-boundary",
    }
    assert all(frame["data-revision-id"] == "corridor-view" for frame in frames)
    assert "Saved corridor definitions" in rendered
    assert "retained-corridor" in rendered and "linear_taper" in rendered
    assert "construction error" in rendered
    assert not page.remote
    downloaded = json.loads(base64.b64decode(page.download.split(",", 1)[1]))
    assert downloaded["corridors"] == prepared.revision.model_dump(mode="json")["corridors"]


def test_unresolved_corridor_view_retains_escaped_raw_input_without_boundary_plot():
    raw = "  { incomplete </script><img src=x onerror=alert(1)>\n"
    bundle, prepared = corridor_fixture(raw)
    rendered = render_revision(bundle, prepared)
    page = Page()
    page.feed(rendered)
    assert not any(frame["data-view"].startswith("corridor-") for frame in page.frames)
    assert "Corridor geometry unavailable" in rendered
    assert "&lt;/script&gt;&lt;img src=x onerror=alert(1)&gt;" in rendered
    assert "<img src=x" not in rendered
