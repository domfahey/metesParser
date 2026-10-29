"""Chromium comparison selection and scenario/reset nonmutation checks."""

import json
import os
from pathlib import Path

import pytest
from mp_export.dashboard_html import render_dashboard
from mp_models.dashboard import DashboardBundle
from mp_verify.dashboard import calculate_dashboard

pytestmark = pytest.mark.skipif(
    os.environ.get("METESPARSER_BROWSER_TESTS") != "1", reason="Explicit browser target required"
)
ROOT = Path(__file__).resolve().parents[2]


def test_comparison_source_versions_and_reset_preserve_records(tmp_path):
    from playwright.sync_api import sync_playwright

    raw = json.loads(
        (ROOT / "packages/mp-review/tests/fixtures/dashboard-comparison.json").read_bytes()
    )
    output = tmp_path / "comparison.html"
    output.write_text(render_dashboard(calculate_dashboard(DashboardBundle.model_validate(raw))))
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(output.as_uri())
        page.wait_for_function(
            "!document.getElementById('scenario-status').textContent.includes('Loading')"
        )
        baseline = page.locator("#dashboard-data").text_content()
        findings = page.locator("#findings").inner_html()
        comparison = page.locator("#description-comparisons").inner_html()
        section = page.locator("#description-comparisons")
        section.locator('[data-comparison-source="call-one"]').first.click()
        assert "Synthetic page 1" in page.locator("#viewer-label").text_content()
        assert "original iron pipe" in page.locator(".selected-source-detail").text_content()
        page.locator("#viewer-close").click()
        section.locator('[data-comparison-source="call-one-v2"]').first.click()
        assert "Synthetic version two page" in page.locator("#viewer-label").text_content()
        assert "replacement iron pin" in page.locator(".selected-source-detail").text_content()
        page.locator("#viewer-close").click()
        page.select_option("#scenario-select", "scenario-one")
        assert "100.5" in page.locator("#call-body input").first.input_value()
        page.click("#reset-record")
        assert page.locator("#call-body input").first.input_value() == "100"
        assert page.locator("#dashboard-data").text_content() == baseline
        assert page.locator("#findings").inner_html() == findings
        assert page.locator("#description-comparisons").inner_html() == comparison
        assert not errors
        browser.close()
