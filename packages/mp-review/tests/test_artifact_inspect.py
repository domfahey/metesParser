"""Inventory real producer artifacts without executing a workflow or trusting hashes alone."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from mp_models import DeedCall
from mp_review.api import review_file

SOURCE_FIXTURES = Path(__file__).parent / "fixtures/source_handoff"


def sha(value):
    return hashlib.sha256(value).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def inspect(root, stage="review"):
    from mp_review.artifact_inspect import inspect_artifacts

    return inspect_artifacts(root, requested_stage=stage)


def nodes(result, kind):
    return [a for a in result["artifacts"] if a["kind"] == kind]


def codes(node):
    return {reason["code"] for reason in node["reasons"]}


@pytest.fixture
def chain(tmp_path):
    shutil.copytree(SOURCE_FIXTURES, tmp_path, dirs_exist_ok=True)
    result = review_file(tmp_path / "description-a.txt", output_dir=tmp_path / "review-a")
    assert result["status"] != "error"
    return tmp_path


def rewrite_manifest(directory, name):
    manifest_path = directory / "review-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["artifacts"][name] = sha((directory / name).read_bytes())
    write_json(manifest_path, manifest)


def test_unchanged_source_selection_review_chain_is_reusable(chain):
    before = {str(p.relative_to(chain)): p.read_bytes() for p in chain.rglob("*") if p.is_file()}
    result = inspect(chain)
    assert result["status"] == "needs_review"
    assert result["earliest_invalid_stage"] is None
    assert nodes(result, "acquisition")[0]["status"] == "present_valid"
    assert nodes(result, "selection")[0]["status"] == "present_valid"
    review = nodes(result, "review")[0]
    assert review["status"] == "present_valid"
    assert review["dependency_ids"] == [nodes(result, "selection")[0]["id"]]
    assert review["recorded_canonical_status"] in {"checks_passed", "needs_review"}
    assert {
        str(p.relative_to(chain)): p.read_bytes() for p in chain.rglob("*") if p.is_file()
    } == before
    assert (
        next(s for s in result["stages"] if s["stage"] == "render-map")["status"] == "not_requested"
    )


@pytest.mark.parametrize(
    "name,earliest",
    [("original.bin", "convert"), ("source-text.txt", "convert"), ("description-a.txt", "extract")],
)
def test_changed_source_invalidates_only_declared_descendants(chain, name, earliest):
    path = chain / name
    path.write_bytes(path.read_bytes() + b" changed")
    result = inspect(chain)
    assert result["earliest_invalid_stage"] == earliest
    review = nodes(result, "review")[0]
    assert review["local_status"] == "present_valid"
    assert review["status"] == "blocked"
    assert "upstream_invalid" in codes(review)


@pytest.mark.parametrize("name", ["calls.json", "verification.json", "audit.json"])
def test_changed_review_bytes_are_stale(chain, name):
    path = chain / "review-a" / name
    path.write_bytes(path.read_bytes() + b"\n")
    node = nodes(inspect(chain), "review")[0]
    assert node["status"] == "stale"
    assert "artifact_hash_mismatch" in codes(node)


@pytest.mark.parametrize("name", ["calls.json", "verification.json", "audit.json"])
def test_self_consistent_tampered_review_is_invalid_after_semantic_replay(chain, name):
    directory = chain / "review-a"
    payload = json.loads((directory / name).read_bytes())
    if name == "calls.json":
        payload[0]["distance_ft"] += 1
    elif name == "verification.json":
        payload["misclosure_ft"] += 1
    else:
        payload["call_audits"] = []
        assert json.loads((directory / name).read_bytes())["call_audits"]
    write_json(directory / name, payload)
    rewrite_manifest(directory, name)
    node = nodes(inspect(chain), "review")[0]
    assert node["status"] == "invalid"
    assert "replay_mismatch" in codes(node)


def test_algorithm_version_change_is_stale(chain):
    path = chain / "review-a/review-manifest.json"
    data = json.loads(path.read_bytes())
    data["engine_version"] = "future-incompatible"
    write_json(path, data)
    node = nodes(inspect(chain), "review")[0]
    assert node["status"] == "stale"
    assert "algorithm_version_mismatch" in codes(node)


@pytest.mark.parametrize("key", ["parameters", "replay_version"])
def test_missing_replay_parameters_remain_unverifiable(chain, key):
    path = chain / "review-a/review-manifest.json"
    data = json.loads(path.read_bytes())
    del data[key]
    write_json(path, data)
    node = nodes(inspect(chain), "review")[0]
    assert node["status"] == "unverifiable"
    assert "replay_parameters_unavailable" in codes(node)


@pytest.mark.parametrize("kind", ["json", "csv"])
def test_direct_call_input_uses_recorded_kind_despite_source_txt_name(tmp_path, kind):
    call = DeedCall(
        course=1, direction_text="East", distance_ft=100, bearing_azimuth_deg_from_north=90
    )
    source = tmp_path / ("calls." + kind)
    if kind == "json":
        write_json(source, [call.model_dump(mode="json")])
    else:
        from mp_export.csv_writer import calls_to_csv

        calls_to_csv([call], str(source))
    review_file(source, output_dir=tmp_path / "review")
    result = inspect(tmp_path, "verify")
    assert result["earliest_invalid_stage"] is None
    assert nodes(result, "review")[0]["status"] == "present_valid"
    assert nodes(result, "review")[0]["dependency_ids"] == []
    assert next(s for s in result["stages"] if s["stage"] == "convert")["status"] == "not_requested"


def test_legacy_review_does_not_infer_input_kind_from_source_txt(chain):
    (chain / "review-a/review-manifest.json").unlink()
    node = nodes(inspect(chain), "review")[0]
    assert node["status"] == "unverifiable"
    assert "legacy_review_manifest" in codes(node)


def test_repeated_same_byte_candidates_do_not_choose_newest_or_first_occurrence(chain):
    path = chain / "description-selection.json"
    data = json.loads(path.read_bytes())
    candidate = dict(data["candidates"][0], id="candidate-historic", role="historical")
    data["candidates"].append(candidate)
    write_json(path, data)
    node = nodes(inspect(chain), "review")[0]
    assert node["local_status"] == "present_valid"
    assert node["status"] == "unverifiable"
    assert "ambiguous_source_occurrence" in codes(node)
    assert node["dependency_ids"] == []
    assert inspect(chain)["recommendations"][0]["command"] is None


def test_missing_original_preserves_individually_replayed_review(chain):
    (chain / "original.bin").unlink()
    result = inspect(chain)
    assert nodes(result, "acquisition")[0]["status"] == "unverifiable"
    assert nodes(result, "review")[0]["local_status"] == "present_valid"
    assert nodes(result, "review")[0]["status"] == "unverifiable"


def test_explicit_nested_bundle_root_does_not_adopt_siblings(chain, tmp_path_factory):
    outer = tmp_path_factory.mktemp("outer")
    nested = outer / "matter" / "bundle"
    nested.parent.mkdir()
    shutil.copytree(chain, nested)
    sibling = outer / "matter" / "sibling"
    sibling.mkdir()
    (sibling / "review-manifest.json").write_text("garbage")
    assert inspect(nested)["earliest_invalid_stage"] is None
    assert inspect(outer)["artifacts"] == []


@pytest.mark.parametrize("reference", ["../source.txt", "/etc/passwd"])
def test_manifest_reference_cannot_escape_its_confined_bundle(chain, reference):
    path = chain / "review-a/review-manifest.json"
    data = json.loads(path.read_bytes())
    data["input"]["path"] = reference
    write_json(path, data)
    node = nodes(inspect(chain), "review")[0]
    assert node["status"] == "invalid"
    assert "unsafe_path" in codes(node)


def test_linked_manifest_or_artifact_is_not_read(chain):
    source = chain / "review-a/calls.json"
    retained = chain / "original-calls.json"
    source.rename(retained)
    source.symlink_to(retained)
    node = nodes(inspect(chain), "review")[0]
    assert node["status"] == "invalid"
    assert "unsafe_path" in codes(node)


def test_unknown_manifest_version_is_invalid_inventory_not_invocation_error(chain):
    path = chain / "review-a/review-manifest.json"
    data = json.loads(path.read_bytes())
    data["schema_version"] = "8.0"
    write_json(path, data)
    result = inspect(chain)
    assert result["status"] == "needs_review"
    assert nodes(result, "review")[0]["status"] == "invalid"
    assert "unknown_schema_version" in codes(nodes(result, "review")[0])


def test_recommendation_uses_current_unambiguous_input_and_new_output(chain):
    path = chain / "review-a/calls.json"
    path.write_bytes(path.read_bytes() + b"\n")
    (chain / "review-next").mkdir()
    before = set(chain.rglob("*"))
    result = inspect(chain)
    command = next(r["command"] for r in result["recommendations"] if r["command"] is not None)
    assert command["arguments"][0] == "review"
    assert str(chain / "description-a.txt") in command["arguments"]
    output = Path(command["arguments"][command["arguments"].index("--output-dir") + 1])
    assert not output.exists()
    assert set(chain.rglob("*")) == before


def test_inspection_never_calls_provider_preparation_or_verified_export(chain, monkeypatch):
    from mp_review import api, webmap

    def forbidden(*a, **k):
        pytest.fail("Inspector must not stage, export, or project")

    monkeypatch.setattr(api, "export_verified_csv", forbidden)
    monkeypatch.setattr(webmap, "prepare_web_map", forbidden)
    monkeypatch.setattr(Path, "mkdir", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    assert inspect(chain)["earliest_invalid_stage"] is None


@pytest.mark.parametrize("kind", ["file", "missing"])
def test_explicit_bundle_root_must_be_existing_directory(chain, kind):
    result = inspect(chain / ("description-a.txt" if kind == "file" else "missing"))
    assert result["status"] == "error"
    assert result["errors"][0]["code"] == "invalid_bundle_root"


def test_unknown_requested_destination_is_an_invocation_error(chain):
    result = inspect(chain, "run-everything")
    assert result["status"] == "error"
    assert result["errors"][0]["code"] == "invalid_requested_stage"


def test_direct_calls_without_saved_results_are_usable_inputs_without_acquisition(tmp_path):
    write_json(
        tmp_path / "calls.json",
        [
            {
                "course": 1,
                "direction_text": "East",
                "bearing_azimuth_deg_from_north": 90,
                "distance_ft": 100,
            }
        ],
    )
    result = inspect(tmp_path, "verify")
    assert nodes(result, "direct_input")[0]["status"] == "present_valid"
    assert result["earliest_invalid_stage"] == "verify"
    command = result["recommendations"][0]["command"]
    assert command["arguments"][0] == "verify"
    assert str(tmp_path / "calls.json") in command["arguments"]
    assert not nodes(result, "acquisition")


def test_recorded_json_under_source_txt_does_not_get_wrong_text_cli_recommendation(tmp_path):
    source = tmp_path / "original.json"
    write_json(
        source,
        [
            {
                "course": 1,
                "direction_text": "East",
                "distance_ft": 100,
                "bearing_azimuth_deg_from_north": 90,
            }
        ],
    )
    review_file(source, output_dir=tmp_path / "review")
    source.unlink()
    path = tmp_path / "review/calls.json"
    path.write_bytes(path.read_bytes() + b"\n")
    result = inspect(tmp_path)
    assert result["recommendations"][0]["command"] is None


def test_dropped_uncertainty_invalidates_selection_reuse(chain):
    path = chain / "source-acquisition.json"
    acquisition = json.loads(path.read_bytes())
    acquisition["uncertainties"] = [
        {
            "id": "unknown-exhibit",
            "description": "Referenced source exhibit is unavailable",
            "page_ids": [],
        }
    ]
    write_json(path, acquisition)
    selection_path = chain / "description-selection.json"
    selection = json.loads(selection_path.read_bytes())
    selection["acquisition_sha256"] = sha(path.read_bytes())
    write_json(selection_path, selection)
    node = nodes(inspect(chain), "selection")[0]
    assert node["status"] == "invalid"
    assert "uncertainty_dropped" in codes(node)


@pytest.fixture
def dashboard_bundle(tmp_path):
    from mp_models.dashboard import DashboardBundle
    from mp_review.dashboard import dashboard_file, prepare_dashboard

    source = json.loads((Path(__file__).parent / "fixtures/dashboard-absolute.json").read_bytes())
    source["schema_version"] = "1.1"
    source["calculations"][0]["frame"]["foot_definition"] = "international_ft"
    prepared = prepare_dashboard(DashboardBundle.model_validate(source))
    source["scenes"] = [
        {
            "id": "map-frame",
            "name": "Synthetic local map",
            "kind": "local",
            "units": "international_ft",
        }
    ]
    source["map_sources"] = [{"id": "map-source", "label": "Synthetic source", "sha256": "0" * 64}]
    source["vector_layers"] = [
        {
            "id": "map-vector",
            "label": "Synthetic polygon",
            "source_id": "map-source",
            "scene_id": "map-frame",
            "geometry_type": "Polygon",
            "coordinates": [[[0, 0], [100, 0], [100, 50], [0, 50], [0, 0]]],
        }
    ]
    source["placements"] = [
        {
            "id": "placement-a",
            "calculation_id": source["calculations"][0]["id"],
            "geometry_hash": prepared.plots.geometries[0].geometry_hash,
            "scene_id": "map-frame",
            "translation": [0, 0],
            "rationale": "Explicit synthetic placement",
        }
    ]
    path = tmp_path / "bundle.json"
    write_json(path, source)
    result = dashboard_file(path, tmp_path / "dashboard")
    assert result["status"] == "needs_review", result
    return tmp_path


def test_unchanged_dashboard_is_locally_valid(dashboard_bundle):
    result = inspect(dashboard_bundle, "dashboard")
    assert result["earliest_invalid_stage"] is None
    for kind in (
        "dashboard_calculations",
        "dashboard_plot",
        "prepared_map",
        "placement",
        "dashboard",
    ):
        assert nodes(result, kind)[0]["status"] == "present_valid"


@pytest.mark.parametrize(
    "change,changed_kind,reason",
    [
        (
            lambda d: d["vector_layers"][0]["coordinates"][0][1].__setitem__(0, 100.2),
            "prepared_map",
            "map_input_mismatch",
        ),
        (lambda d: d.update(title="Different display title"), "dashboard", "presentation_changed"),
        (
            lambda d: d["placements"][0].update(translation=[50, 60]),
            "placement",
            "placement_input_mismatch",
        ),
    ],
)
def test_map_and_presentation_changes_preserve_calculations(
    dashboard_bundle, change, changed_kind, reason
):
    path = dashboard_bundle / "dashboard/source.json"
    data = json.loads(path.read_bytes())
    change(data)
    write_json(path, data)
    result = inspect(dashboard_bundle, "dashboard")
    assert nodes(result, "dashboard_calculations")[0]["status"] == "present_valid"
    assert nodes(result, "dashboard_plot")[0]["status"] == "present_valid"
    assert reason in codes(nodes(result, changed_kind)[0])
    closure = inspect(dashboard_bundle, "verify")
    assert closure["earliest_invalid_stage"] is None


def test_missing_dashboard_html_cannot_invalidate_independent_math(dashboard_bundle):
    (dashboard_bundle / "dashboard/dashboard.html").unlink()
    result = inspect(dashboard_bundle, "verify")
    assert result["earliest_invalid_stage"] is None
    assert nodes(result, "dashboard_calculations")[0]["status"] == "present_valid"
    assert nodes(result, "dashboard")[0]["status"] == "missing"


def test_invalid_map_schema_cannot_invalidate_independent_math(dashboard_bundle):
    path = dashboard_bundle / "dashboard/source.json"
    data = json.loads(path.read_bytes())
    data["vector_layers"][0]["source_id"] = "absent-source"
    write_json(path, data)
    result = inspect(dashboard_bundle, "verify")
    assert result["earliest_invalid_stage"] is None
    assert nodes(result, "dashboard_calculations")[0]["status"] == "present_valid"
    assert nodes(result, "prepared_map")[0]["status"] == "invalid"


def test_description_comparison_placement_does_not_invalidate_core_math(tmp_path):
    from mp_models.dashboard import DashboardBundle
    from mp_review.dashboard import dashboard_file, prepare_dashboard

    source = json.loads((Path(__file__).parent / "fixtures/dashboard-comparison.json").read_bytes())
    prepared = prepare_dashboard(DashboardBundle.model_validate(source))
    source["scenes"] = [
        {
            "id": "comparison-scene",
            "name": "Synthetic scene",
            "kind": "local",
            "units": "international_ft",
        }
    ]
    source["placements"] = [
        {
            "id": f"comparison-placement-{index}",
            "calculation_id": calculation["id"],
            "geometry_hash": prepared.plots.geometries[index].geometry_hash,
            "scene_id": "comparison-scene",
            "translation": [index * 200, 0],
            "rationale": "Explicit synthetic placement",
        }
        for index, calculation in enumerate(source["calculations"])
    ]
    spec = source["description_comparison_specs"][0]
    spec.update(
        scene_id="comparison-scene",
        left_placement_id="comparison-placement-0",
        right_placement_id="comparison-placement-1",
    )
    path = tmp_path / "bundle.json"
    write_json(path, source)
    assert dashboard_file(path, tmp_path / "dashboard")["status"] == "needs_review"

    calculations = nodes(inspect(tmp_path, "verify"), "dashboard_calculations")[0]
    assert calculations["status"] == "present_valid"


def test_dashboard_source_change_stales_math_even_when_old_placement_rejected(dashboard_bundle):
    path = dashboard_bundle / "dashboard/source.json"
    data = json.loads(path.read_bytes())
    data["calls"][0]["call"]["distance_ft"] += 1
    write_json(path, data)
    node = nodes(inspect(dashboard_bundle, "verify"), "dashboard_calculations")[0]
    assert node["status"] in {"stale", "invalid"}
    assert "source_review_mismatch" in codes(node)


def test_new_plot_manifest_is_replayed_from_exact_source(tmp_path):
    from mp_review.plot import plot_file

    source = tmp_path / "calls.json"
    write_json(
        source,
        [
            {
                "course": 1,
                "direction_text": "East",
                "distance_ft": 100,
                "bearing_azimuth_deg_from_north": 90,
            }
        ],
    )
    assert plot_file(source, tmp_path / "plot", input_format="calls")["status"] == "needs_review"
    node = nodes(inspect(tmp_path, "plot"), "plot")[0]
    assert node["status"] == "present_valid"


@pytest.mark.parametrize(
    "stage,display_kind", [("review", "review_display"), ("plot", "plot_display")]
)
@pytest.mark.parametrize("change,expected", [("changed", "stale"), ("missing", "missing")])
def test_saved_display_freshness_is_separate_from_replayed_geometry(
    tmp_path, stage, display_kind, change, expected
):
    from mp_review.plot import plot_file

    source = tmp_path / "source.json"
    write_json(
        source,
        [
            {
                "course": 1,
                "direction_text": "East",
                "distance_ft": 100,
                "bearing_azimuth_deg_from_north": 90,
            }
        ],
    )
    output = tmp_path / stage
    if stage == "review":
        assert review_file(source, output_dir=output)["status"] != "error"
        display = output / "review.html"
    else:
        assert plot_file(source, output, input_format="calls")["status"] != "error"
        display = output / "plot.html"

    if change == "changed":
        display.write_text("tampered display", encoding="utf-8")
    else:
        display.unlink()

    result = inspect(tmp_path, stage)
    core_kind = stage
    core = nodes(result, core_kind)[0]
    presentation = nodes(result, display_kind)[0]
    stage_result = next(item for item in result["stages"] if item["stage"] == stage)
    assert core["status"] == "present_valid"
    assert presentation["status"] == expected
    assert stage_result["status"] == expected


def test_fabricated_plot_request_fails_even_with_consistent_hashes(tmp_path):
    from mp_models.plot_request import PlotRequest
    from mp_review.plot import plot_file
    from mp_verify.plot import prepare_plot

    source = tmp_path / "calls.json"
    write_json(
        source,
        [
            {
                "course": 1,
                "direction_text": "East",
                "distance_ft": 100,
                "bearing_azimuth_deg_from_north": 90,
            }
        ],
    )
    plot_file(source, tmp_path / "plot", input_format="calls")
    directory = tmp_path / "plot"
    request = json.loads((directory / "plot-input.json").read_bytes())
    request["calls"][0]["call"]["distance_ft"] = 999
    fabricated = prepare_plot(PlotRequest.model_validate(request))
    write_json(directory / "plot-input.json", fabricated.request.model_dump(mode="json"))
    write_json(directory / "plot-geometry.json", fabricated.geometry.model_dump(mode="json"))
    manifest = json.loads((directory / "plot-manifest.json").read_bytes())
    manifest.update(
        plot_input_sha256=sha((directory / "plot-input.json").read_bytes()),
        plot_geometry_sha256=sha((directory / "plot-geometry.json").read_bytes()),
        input_hash=fabricated.input_hash,
        geometry_hash=fabricated.geometry.geometry_hash,
    )
    write_json(directory / "plot-manifest.json", manifest)
    node = nodes(inspect(tmp_path, "plot"), "plot")[0]
    assert node["status"] == "invalid"
    assert "replay_mismatch" in codes(node)


@pytest.fixture
def online_bundle(chain):
    from mp_models.plot import PlotPlacement, PlotScene
    from mp_models.plot_request import PlotCall, PlotRequest
    from mp_models.webmap import StandaloneWebMapInput, WebMapRequest
    from mp_review.online_map import render_map_file
    from mp_verify.plot import prepare_plot

    plot = prepare_plot(
        PlotRequest(
            title="Explicit synthetic plot",
            calculation_id="survey",
            foot_definition="international_ft",
            calls=(
                PlotCall(
                    id="c1",
                    call=DeedCall(
                        course=1,
                        direction_text="East",
                        distance_ft=100,
                        bearing_azimuth_deg_from_north=90,
                    ),
                ),
            ),
        )
    )
    scene = PlotScene(
        id="grid", name="Explicit scene", kind="projected", crs="EPSG:3857", units="m"
    )
    placement = PlotPlacement(
        id="placed",
        calculation_id="survey",
        geometry_hash=plot.geometry.geometry_hash,
        scene_id="grid",
        translation=(1000, 2000),
        rationale="Synthetic explicit placement",
        position_evidence=("Supplied point",),
        orientation_evidence=("Supplied rotation",),
    )
    source = StandaloneWebMapInput(
        title="Synthetic map", plots=(plot,), scenes=(scene,), placements=(placement,)
    )
    path = chain / "map-input.json"
    write_json(path, source.model_dump(mode="json"))
    result = render_map_file(path, chain / "online", online_map=WebMapRequest(scene_id="grid"))
    assert result["status"] == "needs_review", result
    return chain


def test_intact_standalone_map_reuses_pure_provenance_without_provider(online_bundle, monkeypatch):
    from mp_review import webmap

    monkeypatch.setattr(
        webmap, "prepare_web_map", lambda *a, **k: pytest.fail("No projection/provider preparation")
    )
    result = inspect(online_bundle, "render-map")
    assert result["earliest_invalid_stage"] is None
    assert nodes(result, "online_map")[0]["status"] == "present_valid"
    assert not nodes(result, "online_map")[0]["dependency_ids"]


@pytest.mark.parametrize("filename", ["source-map.json", "web-map-request.json", "online-map.html"])
def test_map_only_changes_leave_review_usable(online_bundle, filename):
    path = online_bundle / "online" / filename
    if filename == "online-map.html":
        path.write_bytes(path.read_bytes() + b" changed")
    else:
        data = json.loads(path.read_bytes())
        if filename == "source-map.json":
            data["scenes"][0]["name"] = "Changed map scene"
        else:
            data["view"]["zoom"] = 12
        write_json(path, data)
    result = inspect(online_bundle, "review")
    assert result["earliest_invalid_stage"] is None
    assert nodes(result, "review")[0]["status"] == "present_valid"
    assert nodes(result, "online_map")[0]["status"] in {"stale", "invalid"}


def test_online_display_manifest_cannot_drop_promised_views(online_bundle):
    path = online_bundle / "online/web-map-manifest.json"
    data = json.loads(path.read_bytes())
    del data["files"]["map-evidence.html"]
    write_json(path, data)
    node = nodes(inspect(online_bundle, "render-map"), "online_map")[0]
    assert node["status"] == "invalid"
    assert "display_file_inventory_mismatch" in codes(node)


def test_unchanged_diagnosis_and_changed_source_dependency(chain):
    from mp_models.diagnostics import ClosureDiagnosticRequest, diagnostic_input_hash
    from mp_review.diagnostics import diagnose_closure_file

    request = json.loads((Path(__file__).parent / "fixtures/diagnostics/request.json").read_bytes())
    acquisition = json.loads((chain / "source-acquisition.json").read_bytes())
    for call in request["calls"]:
        call["source_refs"] = [
            {
                "source_id": "source-1",
                "source_sha256": acquisition["sources"][0]["sha256"],
                "occurrence_id": "candidate-a",
            }
        ]
    from mp_models.diagnostics import DiagnosticCall

    request["input_sha256"] = diagnostic_input_hash(
        tuple(DiagnosticCall.model_validate(c) for c in request["calls"])
    )
    request = ClosureDiagnosticRequest.model_validate(request)
    path = chain / "diagnosis-input.json"
    write_json(path, request.model_dump(mode="json"))
    diagnose_closure_file(path, chain / "diagnosis")
    node = nodes(inspect(chain), "diagnostics")[0]
    assert node["status"] == "present_valid"
    assert node["dependency_ids"]
    original = chain / "original.bin"
    original.write_bytes(original.read_bytes() + b" mutation")
    changed = nodes(inspect(chain), "diagnostics")[0]
    assert changed["local_status"] == "present_valid"
    assert changed["status"] == "blocked"


@pytest.fixture
def composition_bundle(tmp_path):
    from mp_review.compose import compose_map_file
    from mp_review.plot import plot_file

    source = tmp_path / "calls.json"
    write_json(
        source,
        [
            {
                "course": 1,
                "direction_text": "East",
                "distance_ft": 100,
                "bearing_azimuth_deg_from_north": 90,
            }
        ],
    )
    plot_file(source, tmp_path / "plot", input_format="calls")
    layer = tmp_path / "layer.json"
    write_json(
        layer,
        {
            "scenes": [
                {
                    "id": "grid",
                    "name": "Grid",
                    "kind": "projected",
                    "crs": "EPSG:3857",
                    "units": "m",
                }
            ]
        },
    )
    result = compose_map_file(tmp_path / "plot", tmp_path / "composed", layers=[layer])
    assert result["status"] == "needs_review", result
    return tmp_path


def test_composition_is_replayed_from_declared_retained_inputs(composition_bundle):
    node = nodes(inspect(composition_bundle, "render-map"), "composition")[0]
    assert node["status"] == "present_valid"


def test_fabricated_composition_cannot_be_certified_by_self_consistent_geometry_hash(
    composition_bundle,
):
    from mp_models.plot_request import PlotRequest
    from mp_verify.plot import prepare_plot

    directory = composition_bundle / "composed"
    value = json.loads((directory / "map-input.json").read_bytes())
    value["plots"][0]["request"]["calls"][0]["call"]["distance_ft"] = 999
    fabricated = prepare_plot(PlotRequest.model_validate(value["plots"][0]["request"]))
    value["plots"][0] = fabricated.model_dump(mode="json")
    write_json(directory / "map-input.json", value)
    manifest = json.loads((directory / "composition-manifest.json").read_bytes())
    manifest["geometry_hashes"] = {
        fabricated.request.calculation_id: fabricated.geometry.geometry_hash
    }
    write_json(directory / "composition-manifest.json", manifest)
    node = nodes(inspect(composition_bundle, "render-map"), "composition")[0]
    assert node["status"] == "invalid"
    assert "composition_replay_mismatch" in codes(node)


@pytest.fixture
def comparison_bundle(tmp_path):
    from mp_models.comparison import ComparisonRequest
    from mp_verify.comparison import compare_descriptions

    def description(id, callid):
        return {
            "id": id,
            "plot": {
                "title": id,
                "calculation_id": id,
                "foot_definition": "international_ft",
                "calls": [
                    {
                        "id": callid,
                        "call": {
                            "course": 1,
                            "direction_text": "East",
                            "distance_ft": 100,
                            "bearing_azimuth_deg_from_north": 90,
                        },
                    }
                ],
            },
            "bearing_basis": {"label": "Unknown basis"},
        }

    request = ComparisonRequest.model_validate(
        {
            "left": description("old", "left-a"),
            "right": description("new", "right-a"),
            "tolerances": {
                "length": 0.1,
                "displacement": 0.1,
                "position": 0.1,
                "linear_unit": "international_ft",
                "bearing_deg": 0.01,
                "source_references": ["Declared synthetic comparison criteria"],
            },
        }
    )
    directory = tmp_path / "comparison"
    directory.mkdir()
    write_json(directory / "comparison-request.json", request.model_dump(mode="json"))
    result = compare_descriptions(request)
    write_json(directory / "comparison.json", result.model_dump(mode="json"))
    write_json(
        directory / "comparison-manifest.json",
        {
            "schema_version": "1.0",
            "artifact_kind": "description_comparison",
            "algorithm_version": result.algorithm_version,
            "request_file": "comparison-request.json",
            "result_file": "comparison.json",
            "request_sha256": sha((directory / "comparison-request.json").read_bytes()),
            "result_sha256": sha((directory / "comparison.json").read_bytes()),
            "input_hash": result.input_hash,
            "left_id": "old",
            "right_id": "new",
        },
    )
    return tmp_path


def test_comparison_is_replayed_without_acquisition_or_dashboard(comparison_bundle):
    result = inspect(comparison_bundle, "compare-descriptions")
    assert result["earliest_invalid_stage"] is None
    node = nodes(result, "comparison")[0]
    assert node["status"] == "present_valid"
    assert node["recorded_canonical_status"] is None
    assert node["dependency_ids"] == []


def test_comparison_fabrication_fails_despite_consistent_hash(comparison_bundle):
    directory = comparison_bundle / "comparison"
    result = json.loads((directory / "comparison.json").read_bytes())
    result["boundary_established"] = True
    write_json(directory / "comparison.json", result)
    manifest = json.loads((directory / "comparison-manifest.json").read_bytes())
    manifest["result_sha256"] = sha((directory / "comparison.json").read_bytes())
    write_json(directory / "comparison-manifest.json", manifest)
    node = nodes(inspect(comparison_bundle, "compare-descriptions"), "comparison")[0]
    assert node["status"] == "invalid"
    assert "replay_mismatch" in codes(node)


def test_online_map_tracks_unique_declared_plot_identity(tmp_path):
    from mp_models.plot_request import PreparedPlot
    from mp_models.webmap import StandaloneWebMapInput, WebMapRequest
    from mp_review.online_map import render_map_file
    from mp_review.plot import plot_file

    source = tmp_path / "calls.json"
    write_json(
        source,
        [
            {
                "course": 1,
                "direction_text": "East",
                "distance_ft": 100,
                "bearing_azimuth_deg_from_north": 90,
            }
        ],
    )
    output = tmp_path / "plot"
    plot_file(source, output, input_format="calls")
    manifest = json.loads((output / "plot-manifest.json").read_bytes())
    plot = PreparedPlot.model_validate(
        {
            "request": json.loads((output / "plot-input.json").read_bytes()),
            "geometry": json.loads((output / "plot-geometry.json").read_bytes()),
            "input_hash": manifest["input_hash"],
        }
    )
    map_input = StandaloneWebMapInput.model_validate(
        {
            "title": "Supplied plot display",
            "plots": [plot.model_dump(mode="json")],
            "scenes": [
                {
                    "id": "grid",
                    "name": "Grid",
                    "kind": "projected",
                    "crs": "EPSG:3857",
                    "units": "m",
                }
            ],
        }
    )
    path = tmp_path / "map-input.json"
    write_json(path, map_input.model_dump(mode="json"))
    assert (
        render_map_file(path, tmp_path / "online", online_map=WebMapRequest(scene_id="grid"))[
            "status"
        ]
        == "needs_review"
    )
    node = nodes(inspect(tmp_path, "render-map"), "online_map")[0]
    assert node["status"] == "present_valid"
    assert node["dependency_ids"] == ["plot:plot/plot-manifest.json"]
    retained = output / "source.json"
    retained.write_bytes(retained.read_bytes() + b" changed")
    changed = nodes(inspect(tmp_path, "render-map"), "online_map")[0]
    assert changed["local_status"] == "present_valid"
    assert changed["status"] == "blocked"


@pytest.fixture
def integrated_comparison_bundle(tmp_path):
    from mp_review.dashboard import dashboard_file

    source = json.loads((Path(__file__).parent / "fixtures/dashboard-comparison.json").read_bytes())
    path = tmp_path / "comparison-bundle.json"
    write_json(path, source)
    assert dashboard_file(path, tmp_path / "dashboard")["status"] == "needs_review"
    return tmp_path


def test_integrated_dashboard_comparison_is_discovered_and_reused_without_maps(
    integrated_comparison_bundle,
):
    root = integrated_comparison_bundle
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    result = inspect(root, "compare-descriptions")
    assert result["earliest_invalid_stage"] is None
    comparison = nodes(result, "comparison")[0]
    assert comparison["path"] == "dashboard/description-comparisons.json"
    assert comparison["status"] == "present_valid"
    assert comparison["recorded_canonical_status"] is None
    assert comparison["dependency_ids"] == [nodes(result, "dashboard_calculations")[0]["id"]]
    assert {
        str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
    } == before


def test_integrated_dashboard_comparison_tamper_is_invalid_despite_self_consistent_hash(
    integrated_comparison_bundle,
):
    from mp_verify.dashboard import _hash

    root = integrated_comparison_bundle
    path = root / "dashboard/description-comparisons.json"
    data = json.loads(path.read_bytes())
    data[0]["comparison"]["boundary_established"] = True
    write_json(path, data)
    manifest_path = root / "dashboard/stage-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["description_comparisons_output_hash"] = _hash(data)
    write_json(manifest_path, manifest)
    result = inspect(root, "compare-descriptions")
    node = nodes(result, "comparison")[0]
    assert node["status"] == "invalid"
    assert "comparison_replay_mismatch" in codes(node)
    assert result["earliest_invalid_stage"] == "compare-descriptions"
    assert result["required_inputs"]
    assert any(
        "DashboardBundle" in requirement and "dashboard/source.json" in requirement
        for requirement in result["required_inputs"]
    )
    assert any(
        "no standalone ComparisonRequest" in requirement
        for requirement in result["required_inputs"]
    )
    assert result["recommendations"][0]["command"] is None
    dashboard = inspect(root, "dashboard")
    assert nodes(dashboard, "dashboard")[0]["status"] == "blocked"
    assert dashboard["earliest_invalid_stage"] == "compare-descriptions"
    assert inspect(root, "verify")["earliest_invalid_stage"] is None


def test_integrated_dashboard_changed_comparison_spec_is_stale_and_resumes_comparison(
    integrated_comparison_bundle,
):
    root = integrated_comparison_bundle
    path = root / "dashboard/source.json"
    source = json.loads(path.read_bytes())
    source["description_comparison_specs"][0]["tolerances"]["length"] = 0.2
    write_json(path, source)
    result = inspect(root, "compare-descriptions")
    assert nodes(result, "comparison")[0]["status"] == "stale"
    assert "comparison_input_mismatch" in codes(nodes(result, "comparison")[0])
    assert result["earliest_invalid_stage"] == "compare-descriptions"
    assert inspect(root, "verify")["earliest_invalid_stage"] is None


def test_unplaced_dashboard_comparison_has_no_optional_map_dependency(integrated_comparison_bundle):
    root = integrated_comparison_bundle
    path = root / "dashboard/source.json"
    source = json.loads(path.read_bytes())
    source["vector_layers"] = [
        {"id": "bad-map-layer", "source_id": "unknown", "scene_id": "unknown"}
    ]
    write_json(path, source)
    result = inspect(root, "compare-descriptions")
    assert nodes(result, "prepared_map")[0]["status"] == "invalid"
    assert nodes(result, "comparison")[0]["status"] == "present_valid"
    assert result["earliest_invalid_stage"] is None


@pytest.mark.parametrize(
    "change,expected",
    [("missing", "missing"), ("changed_bytes", "stale"), ("missing_hash", "unverifiable")],
)
def test_integrated_dashboard_comparison_missing_or_changed_stage_never_reuses(
    integrated_comparison_bundle, change, expected
):
    root = integrated_comparison_bundle
    path = root / "dashboard/description-comparisons.json"
    if change == "missing":
        path.unlink()
    elif change == "changed_bytes":
        payload = json.loads(path.read_bytes())
        payload[0]["comparison"]["limitations"].append("Changed saved evidence")
        write_json(path, payload)
    else:
        manifest_path = root / "dashboard/stage-manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        manifest["description_comparisons_input_hash"] = None
        write_json(manifest_path, manifest)
    result = inspect(root, "compare-descriptions")
    assert nodes(result, "comparison")[0]["status"] == expected
    assert result["earliest_invalid_stage"] == "compare-descriptions"
    assert inspect(root, "verify")["earliest_invalid_stage"] is None


def test_placed_dashboard_comparison_has_explicit_position_dependencies(tmp_path):
    from mp_models.dashboard import DashboardBundle
    from mp_review.dashboard import dashboard_file, prepare_dashboard

    source = json.loads((Path(__file__).parent / "fixtures/dashboard-comparison.json").read_bytes())
    fresh = prepare_dashboard(DashboardBundle.model_validate(source))
    source["scenes"] = [
        {
            "id": "comparison-scene",
            "name": "Synthetic local scene",
            "kind": "local",
            "units": "international_ft",
        }
    ]
    for side in ("left", "right"):
        source["description_comparison_specs"][0][side + "_bearing_basis"] = {
            "label": "Declared synthetic survey grid",
            "identity": "synthetic-grid",
            "source_references": ["Declared synthetic survey reference"],
        }
    source["map_sources"] = [
        {
            "id": "comparison-context-source",
            "label": "Supplied synthetic context",
            "sha256": "a" * 64,
            "native_units": "international_ft",
        }
    ]
    source["vector_layers"] = [
        {
            "id": "comparison-context",
            "label": "Synthetic context polygon",
            "scene_id": "comparison-scene",
            "source_id": "comparison-context-source",
            "geometry_type": "Polygon",
            "coordinates": [[[-10, -10], [110, -10], [110, 110], [-10, 110], [-10, -10]]],
        }
    ]
    source["placements"] = [
        {
            "id": "placed-" + g.calculation_id,
            "calculation_id": g.calculation_id,
            "geometry_hash": g.geometry_hash,
            "scene_id": "comparison-scene",
            "rationale": "Explicit synthetic origin",
        }
        for g in fresh.plots.geometries
    ]
    source["description_comparison_specs"][0].update(
        scene_id="comparison-scene",
        left_placement_id="placed-calc-one",
        right_placement_id="placed-calc-two",
    )
    path = tmp_path / "bundle.json"
    write_json(path, source)
    assert dashboard_file(path, tmp_path / "dashboard")["status"] == "needs_review"
    saved = json.loads((tmp_path / "dashboard/description-comparisons.json").read_bytes())
    assert saved[0]["comparison"]["pairs"][0]["position"]["outcome"] == "agree"
    result = inspect(tmp_path, "compare-descriptions")
    comparison = nodes(result, "comparison")[0]
    assert comparison["status"] == "present_valid"
    assert set(comparison["dependency_ids"]) == {
        nodes(result, kind)[0]["id"]
        for kind in ("dashboard_calculations", "dashboard_plot", "prepared_map", "placement")
    }
    retained = json.loads((tmp_path / "dashboard/source.json").read_bytes())
    retained["placements"][0]["translation"] = [1, 2]
    write_json(tmp_path / "dashboard/source.json", retained)
    after = inspect(tmp_path, "compare-descriptions")
    assert nodes(after, "comparison")[0]["status"] == "stale"
    assert after["earliest_invalid_stage"] == "render-map"
    assert inspect(tmp_path, "verify")["earliest_invalid_stage"] is None


def test_stage_summaries_preserve_actual_reasons_artifact_owners_and_dependencies(chain):
    (chain / "original.bin").write_bytes(b"changed original source")
    result = inspect(chain)
    review = nodes(result, "review")[0]
    selection = nodes(result, "selection")[0]
    stage = next(s for s in result["stages"] if s["stage"] == "review")
    assert stage["status"] == "blocked"
    assert stage["dependency_ids"] == review["dependency_ids"]
    assert stage["reasons"]
    assert all(reason["artifact_id"] == review["id"] for reason in stage["reasons"])
    assert any(reason["dependency_id"] == selection["id"] for reason in stage["reasons"])
    assert len(stage["dependency_ids"]) == len(set(stage["dependency_ids"]))
    assert len(stage["reasons"]) == len({json.dumps(r, sort_keys=True) for r in stage["reasons"]})
    assert result == inspect(chain)
    for summary in result["stages"]:
        if summary["status"] == "not_requested":
            assert summary["reasons"] == [] and summary["dependency_ids"] == []


def test_valid_stage_summaries_have_no_invented_reasons(chain):
    result = inspect(chain)
    for stage in result["stages"]:
        assert stage["reasons"] == []


def test_missing_requested_stage_has_explicit_inventory_reason(tmp_path):
    result = inspect(tmp_path, "compare-descriptions")
    stage = next(s for s in result["stages"] if s["stage"] == "compare-descriptions")
    assert stage["status"] == "missing"
    assert stage["dependency_ids"] == []
    assert stage["reasons"][0]["code"] == "requested_stage_missing"
    assert stage["reasons"][0]["artifact_id"] is None


def test_causal_restart_ignores_unrelated_invalid_artifacts_and_is_stable(
    integrated_comparison_bundle,
):
    root = integrated_comparison_bundle
    unrelated = root / "unrelated-review"
    unrelated.mkdir()
    write_json(unrelated / "review-manifest.json", {"schema_version": "unknown"})
    source_path = root / "dashboard/source.json"
    source = json.loads(source_path.read_bytes())
    source["vector_layers"] = [
        {"id": "bad-map-layer", "source_id": "unknown", "scene_id": "unknown"}
    ]
    write_json(source_path, source)
    result = inspect(root, "dashboard")
    assert nodes(result, "review")[0]["status"] == "invalid"
    assert next(s for s in result["stages"] if s["stage"] == "review")["status"] == "not_requested"
    assert result["earliest_invalid_stage"] == "render-map"
    assert result == inspect(root, "dashboard")
    # Two independent relevant failures retain the same deterministic cause priority.
    from mp_verify.dashboard import _hash

    comparison_path = root / "dashboard/description-comparisons.json"
    comparison = json.loads(comparison_path.read_bytes())
    comparison[0]["comparison"]["boundary_established"] = True
    write_json(comparison_path, comparison)
    manifest_path = root / "dashboard/stage-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["description_comparisons_output_hash"] = _hash(comparison)
    write_json(manifest_path, manifest)
    multiple = inspect(root, "dashboard")
    assert nodes(multiple, "comparison")[0]["status"] == "invalid"
    assert nodes(multiple, "prepared_map")[0]["status"] == "invalid"
    assert multiple["earliest_invalid_stage"] == "render-map"
    assert multiple == inspect(root, "dashboard")
    assert inspect(root, "compare-descriptions")["earliest_invalid_stage"] == "compare-descriptions"
