"""Offline renderer safety and independent browser/Python numerical agreement."""

import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest
from mp_export.dashboard_html import _check_outcomes, render_dashboard, renderer_fingerprint
from mp_models.closure import CheckResult
from mp_models.dashboard import DashboardBundle
from mp_verify.dashboard import calculate_dashboard

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "packages/mp-review/tests/fixtures"
SCRIPT = ROOT / "packages/mp-export/src/mp_export/dashboard_assets/dashboard.js"


def bundle_data(kind="absolute"):
    return json.loads((FIXTURES / f"dashboard-{kind}.json").read_text())


def prepare(data=None):
    return calculate_dashboard(DashboardBundle.model_validate(data or bundle_data()))


def browser_math(expression, payload):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed to execute independent browser math")
    source = (
        "const math = require(process.argv[1]);"
        "const input = JSON.parse(require('fs').readFileSync(0,'utf8'));"
        f"process.stdout.write(JSON.stringify({expression}));"
    )
    result = subprocess.run(
        [node, "-e", source, str(SCRIPT)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


class ResourceParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.resources = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name == "src" or (tag == "link" and name == "href"):
                self.resources.append(value)


def test_deterministic_offline_render_preserves_record_and_six_sections():
    prepared = prepare()
    before = prepared.model_dump_json()
    result = render_dashboard(prepared)
    assert render_dashboard(prepared) == result
    assert prepared.model_dump_json() == before
    for section in ("findings", "evidence", "workbench", "records", "sources", "method"):
        assert f'id="{section}"' in result
    assert 'data-record-occurrence="occ-one"' in result
    assert prepared.manifest.source_review_hash in result
    assert "Source review: <strong>complete</strong>" in result
    assert "verified-export control" in result
    assert 'id="reset-record"' in result
    parser = ResourceParser()
    parser.feed(result)
    assert parser.resources
    assert all(not value or value.startswith("data:image/") for value in parser.resources)
    assert "@import" not in result
    assert "eval(" not in result


def test_absent_optional_record_fields_render_blank():
    rendered = render_dashboard(prepare())
    assert "<td>None<br>None</td>" not in rendered
    assert "<td><br></td>" in rendered


def test_unsafe_source_text_cannot_escape_html_or_json_script():
    data = bundle_data()
    payload = '</script><img src=x onerror="alert(1)">&\u2028'
    data["title"] = payload
    data["occurrences"][0]["transcript"] = "  " + payload + "\n"
    data["calls"][0]["quote"] = payload
    result = render_dashboard(prepare(data))
    assert payload not in result
    assert "&lt;/script&gt;&lt;img src=x" in result
    match = re.search(
        r'<script type="application/json" id="dashboard-data">(.*?)</script>', result, re.S
    )
    assert match is not None
    embedded = match[1]
    assert "<" not in embedded and "&" not in embedded
    assert json.loads(embedded)["bundle"]["title"] == payload
    assert result.count("</script>") == 2


def test_missing_assets_and_expected_pages_remain_explicit():
    data = bundle_data()
    data["documents"][0]["expected_page_count"] = 2
    for item in [data["pages"][0], data["evidence"][0]]:
        item["image"] = item["image_sha256"] = None
    result = render_dashboard(prepare(data))
    assert "Expected pages not supplied: 2" in result
    assert "Source image unavailable" in result
    assert "Evidence image unavailable" in result
    assert "Source review: incomplete" in result


@pytest.mark.parametrize(
    "image",
    [
        "https://example.test/image.png",
        "javascript:alert(1)",
        "data:image/svg+xml;base64,PHN2Zy8+",
        "data:image/png;base64,aGVsbG8=",
    ],
)
def test_unsafe_and_broken_asset_inputs_rejected(image):
    prepared = prepare()
    bad_page = prepared.bundle.pages[0].model_copy(update={"image": image})
    forged_bundle = prepared.bundle.model_copy(update={"pages": (bad_page,)})
    with pytest.raises(ValueError):
        render_dashboard(prepared.model_copy(update={"bundle": forged_bundle}))


def test_forged_prepared_results_rejected():
    prepared = prepare()
    result = prepared.calculations[0].model_copy(update={"misclosure_ft": 123.0})
    with pytest.raises(ValueError):
        render_dashboard(prepared.model_copy(update={"calculations": (result,)}))


def test_render_is_identical_for_cold_and_warm_stage_cache():
    cold = prepare()
    warm = cold.model_copy(
        update={"manifest": cold.manifest.model_copy(update={"cache_reused": True})}
    )
    rendered = render_dashboard(cold)
    assert rendered == render_dashboard(warm)
    assert '"cache_reused"' not in rendered


@pytest.mark.parametrize("status", ["passed", "failed", "not_applicable", "blocked"])
def test_canonical_check_outcomes_preserve_all_four_statuses(status):
    check = CheckResult(
        name="Angles", status=status, reason=f"reason-{status}", detail="<source detail>"
    )
    rendered = _check_outcomes((check,), "canonical")
    assert f'data-check-status="{status}">{status}</td>' in rendered
    assert f"reason-{status}" in rendered
    assert "&lt;source detail&gt;" in rendered
    if status != "passed":
        assert 'data-check-status="passed"' not in rendered


def test_relative_analysis_does_not_claim_canonical_checks_ran():
    rendered = render_dashboard(prepare(bundle_data("relative")))
    assert "Canonical checks were not run by relative analysis" in rendered


def test_renderer_fingerprint_captures_asset_changes_separately(tmp_path, monkeypatch):
    import mp_export.dashboard_html as renderer

    assert re.fullmatch(r"[a-f0-9]{64}", renderer_fingerprint())
    assert renderer_fingerprint() == renderer_fingerprint()
    for name in ("dashboard.css", "dashboard.js"):
        (tmp_path / name).write_bytes((renderer._ASSETS / name).read_bytes())
    monkeypatch.setattr(renderer, "_ASSETS", tmp_path)
    before = renderer_fingerprint()
    (tmp_path / "dashboard.css").write_text("body { color: navy; }")
    assert renderer_fingerprint() != before


@pytest.mark.parametrize("kind", ["absolute", "relative"])
@pytest.mark.parametrize("extra", [0.0, 0.5])
def test_independent_javascript_math_agrees_with_python(kind, extra):
    data = bundle_data(kind)
    data["calls"][0]["call"]["distance_ft"] += extra
    if kind == "relative":
        relative = data["calculations"][0]["relative"]
        relative["courses"][0]["distance_ft"] += extra
        relative["frame"]["first_azimuth_deg"] = 37.25
        relative["frame"]["origin"] = [1200.0, -250.0]
    prepared = prepare(data)
    result = browser_math(
        "math.calculateScenario(input.calculations[0], input.calls)",
        prepared.bundle.model_dump(mode="json"),
    )
    expected = prepared.calculations[0]
    for key in (
        "misclosure_ft",
        "misclosure_x_ft",
        "misclosure_y_ft",
        "area_sq_ft",
        "perimeter_ft",
    ):
        assert result[key] == pytest.approx(getattr(expected, key), abs=0.001)
    for point, reference in zip(result["points"], expected.points, strict=True):
        assert point == pytest.approx([reference.x, reference.y], abs=0.001)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "NaN",
        "Infinity",
        "1e2",
        "0x10",
        "12 ft",
        "45°60′",
        "N 90°00′01″ E",
        "S 45°3.5′2″ W",
        "N 45 trailing E",
        "360",
    ],
)
def test_javascript_rejects_malformed_or_nonfinite_bearings(text):
    result = browser_math(
        "(() => { try { math.parseBearing(input); return false; } catch (_) { return true; } })()",
        text,
    )
    assert result is True


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("236.675", 236.675),
        ("S 56°40'30\" W", 236.675),
        ("N 45°30′ E", 45.5),
        ("N 90° E", 90.0),
        ("N 0 W", 0.0),
    ],
)
def test_javascript_supported_bearings(text, expected):
    assert browser_math("math.parseBearing(input)", text) == pytest.approx(expected)


@pytest.mark.parametrize("mode", ["ambiguous", "insufficient", "contradictory"])
def test_javascript_does_not_resolve_ambiguous_or_contradictory_turns(mode):
    data = prepare(bundle_data("relative")).bundle.model_dump(mode="json")
    constraints = data["calculations"][0]["relative"]["constraints"]
    if mode == "ambiguous":
        constraints[0].update(kind="perpendicular", angle_deg=None, turn=None)
    elif mode == "insufficient":
        constraints[:] = constraints[:1]
    else:
        constraints[0]["angle_deg"] = 91
    result = browser_math(
        "(() => { try { math.calculateScenario(input.calculations[0],input.calls); return false; } catch (_) { return true; } })()",
        data,
    )
    assert result is True


def test_javascript_does_not_mutate_record_inputs():
    data = prepare(bundle_data("relative")).bundle.model_dump(mode="json")
    result = browser_math(
        "(() => { const before = JSON.stringify(input); math.calculateScenario(input.calculations[0],input.calls); return JSON.stringify(input) === before; })()",
        data,
    )
    assert result is True


@pytest.mark.parametrize("orientation", ["cw", "ccw"])
def test_javascript_reflex_and_reverse_traversal_agree_with_python(orientation):
    data = bundle_data("relative")
    data["evidence"] = []
    data["scenarios"] = []
    relative = data["calculations"][0]["relative"]
    relative["frame"].update(
        orientation=orientation, first_azimuth_deg=23.0, origin=[1024.0, -97.0]
    )
    data["calls"] = []
    relative["courses"] = []
    relative["constraints"] = []
    for index, distance in enumerate([2.0, 1.0, 1.0, 1.0, 1.0, 2.0]):
        course_id = f"leg-{index}"
        source = {"reference": course_id, "quote": f"Course {index}: {distance} feet"}
        data["calls"].append(
            {
                "id": course_id,
                "occurrence_id": "occ-one",
                "page_id": "page-one",
                "quote": source["quote"],
                "reading_status": "certain",
                "call": {
                    "course": index + 1,
                    "direction_text": "direction unknown",
                    "distance_ft": distance,
                },
            }
        )
        relative["courses"].append(
            {"course_id": course_id, "distance_ft": distance, "source": source}
        )
        relative["constraints"].append(
            {
                "constraint_id": f"corner-{index}",
                "kind": "interior",
                "from_course": course_id,
                "to_course": f"leg-{(index + 1) % 6}",
                "angle_deg": 270.0 if index == 2 else 90.0,
                "source": source,
            }
        )
    prepared = prepare(data)
    result = browser_math(
        "math.calculateScenario(input.calculations[0],input.calls)",
        prepared.bundle.model_dump(mode="json"),
    )
    expected = prepared.calculations[0]
    assert result["area_sq_ft"] == pytest.approx(expected.area_sq_ft, abs=0.001)
    assert result["misclosure_ft"] == pytest.approx(expected.misclosure_ft, abs=0.001)
    assert result["computed_closing_angle_deg"] == pytest.approx(
        expected.computed_closing_angle_deg
    )
    assert result["stated_angle_sum_deg"] == pytest.approx(720)


@pytest.mark.parametrize("kind", ["exterior", "perpendicular", "parallel"])
def test_javascript_explicit_constraint_kinds_agree_with_python(kind):
    data = bundle_data("relative")
    constraints = data["calculations"][0]["relative"]["constraints"]
    if kind == "exterior":
        for constraint in constraints:
            constraint.update(
                kind="exterior", angle_deg=270.0, exterior_convention="interior_complement"
            )
    elif kind == "perpendicular":
        for constraint in constraints:
            constraint.update(kind="perpendicular", angle_deg=None, turn="right")
    else:
        data["occurrences"][0]["transcript"] += "Parallel, opposite direction\n"
        constraints[:] = [
            constraints[0],
            {
                "constraint_id": "parallel-a",
                "kind": "parallel",
                "from_course": "call-one",
                "to_course": "call-three",
                "parallel_direction": "opposite",
                "source": {"reference": "page-one", "quote": "Parallel, opposite direction"},
            },
            {
                "constraint_id": "parallel-b",
                "kind": "parallel",
                "from_course": "call-two",
                "to_course": "call-four",
                "parallel_direction": "opposite",
                "source": {"reference": "page-one", "quote": "Parallel, opposite direction"},
            },
        ]
    prepared = prepare(data)
    result = browser_math(
        "math.calculateScenario(input.calculations[0],input.calls)",
        prepared.bundle.model_dump(mode="json"),
    )
    expected = prepared.calculations[0]
    assert result["misclosure_ft"] == pytest.approx(expected.misclosure_ft, abs=0.001)
    assert result["area_sq_ft"] == pytest.approx(expected.area_sq_ft, abs=0.001)
