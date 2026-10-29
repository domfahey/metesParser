"""Real source/model materialization, with evaluator evidence outside candidates."""

import hashlib
import json
from pathlib import Path

import pytest
from pypdf import PdfReader

from scripts.skill_evals import CATALOG, materialize

ROOT = Path(__file__).parents[2]
CASES = {case["id"]: case for case in json.loads(CATALOG.read_text())}
INTAKE_CASES = [
    "document-to-plot-requested-stop",
    "plottability-lot-block-comma-list",
    "closing-subset-unreadable-middle",
    "document-plot-exception-after-pob",
    "document-plot-missing-continuation",
    "document-plot-duplicate-course",
    "document-plot-cardinal-only",
    "document-plot-missing-numbered-course",
    "multi-tract-independent-results-and-resume",
    "guided-raster-no-deed-placement",
]


def prepared(tmp_path, case_id):
    candidate, evaluator = tmp_path / case_id / "candidate", tmp_path / case_id / "evaluator"
    materialize(case_id, candidate, evaluator)
    manifest = json.loads((candidate / "manifest.json").read_text())
    rubric = json.loads((evaluator / "rubric.json").read_text())
    assert manifest["artifacts"]
    for entry in manifest["artifacts"]:
        data = (candidate / entry["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
        for criterion in rubric["criteria"]:
            assert criterion["id"].encode() not in data
    request = json.loads((candidate / "request.json").read_text())
    assert not {"expected", "must_not", "criteria", "required_actions"} & request.keys()
    assert not list(candidate.rglob("rubric.json"))
    return candidate, evaluator, manifest


@pytest.mark.parametrize("case_id", INTAKE_CASES)
def test_all_document_and_guided_cases_materialize_complete_real_inputs(tmp_path, case_id):
    candidate, _, manifest = prepared(tmp_path, case_id)
    case = CASES[case_id]
    if case_id == "guided-raster-no-deed-placement":
        from mp_models.plot_request import PreparedPlot
        from mp_models.raster import RasterControl
        from mp_review.raster_registration import fit_affine
        from PIL import Image

        controls = json.loads((candidate / "artifacts/source-1.json").read_text())
        registration = fit_affine(
            tuple(RasterControl.model_validate(v) for v in controls["controls"])
        )
        assert registration.fit_rms == pytest.approx(0, abs=1e-12)
        assert registration.checkpoint_rms == pytest.approx(5)
        assert registration.status == "approximate"
        with Image.open(candidate / "artifacts/source-2.png") as scan:
            assert scan.size == (20, 20)
        plot = PreparedPlot.model_validate_json(
            (candidate / "artifacts/source-3.json").read_bytes()
        )
        assert plot.geometry.completeness == "complete"
        assert "placement" not in plot.model_dump()
    else:
        text = (candidate / "artifacts/source-1.txt").read_bytes()
        if "document_text" in case["input"]:
            assert text == case["input"]["document_text"].encode()
        else:
            assert text == (CATALOG.parent / case["input"]["fixture_file"]).read_bytes()
        pdf = next(candidate / a["path"] for a in manifest["artifacts"] if a["kind"] == "pdf")
        reader = PdfReader(pdf)
        assert len(reader.pages) == (3 if "multi-tract" in case_id else 1)
        assert all(not page.extract_text() for page in reader.pages)


def test_multitract_followup_is_hidden_until_second_turn_and_does_not_replace_original(tmp_path):
    candidate, evaluator, _ = prepared(tmp_path, "multi-tract-independent-results-and-resume")
    original = (candidate / "artifacts/source-1.txt").read_bytes()
    followup = evaluator / "followup-inputs/tract-b-page-2.txt"
    assert followup.is_file()
    assert b"[illegible]" in original and b"[illegible]" not in followup.read_bytes()
    followup_manifest = json.loads((evaluator / "followup-manifest.json").read_text())
    assert followup_manifest["turn"] == 2
    assert (
        hashlib.sha256(followup.read_bytes()).hexdigest()
        == followup_manifest["artifacts"][0]["sha256"]
    )
    assert not list(candidate.rglob("tract-b-page-2.txt"))


@pytest.mark.parametrize(
    "case_id,availability",
    [("corridor-taper-and-cap", "supported"), ("corridor-overlapping-widths", "unsupported")],
)
def test_corridor_fixtures_execute_real_independent_engine(tmp_path, case_id, availability):
    from mp_models.corridor import CorridorRequest
    from mp_verify.corridor import analyze_corridor

    candidate, _, _ = prepared(tmp_path, case_id)
    request = CorridorRequest.model_validate_json(
        (candidate / "artifacts/source-1.json").read_bytes()
    )
    result = analyze_corridor(request)
    assert result.availability == availability
    assert not result.verified_export_eligible
    if availability == "supported":
        assert result.request.widths[0].left_start != result.request.widths[0].left_end
        assert result.error.total_bound <= request.error_budget.max_error
        assert result.centerline.geometry.primitives[0].kind == "arc"
    else:
        assert result.boundary is None and result.polygon is None


def test_supplied_plss_fixture_executes_with_actual_reference_bytes(tmp_path):
    import base64

    from mp_models.plss import PLSSDerivationRequest
    from mp_verify.plss import derive_plss

    candidate, _, _ = prepared(tmp_path, "plss-supplied-reference")
    request = PLSSDerivationRequest.model_validate_json(
        (candidate / "artifacts/source-1.json").read_bytes()
    )
    assert (
        hashlib.sha256(base64.b64decode(request.dataset.source.data_base64)).hexdigest()
        == request.dataset.source.sha256
    )
    result = derive_plss(request)
    assert result.availability == "computed"
    assert result.area_scene_units_squared == pytest.approx(1600)
    assert not result.boundary_established and not result.verified_export_eligible


def test_absent_plss_reference_materializes_source_without_invented_dataset(tmp_path):
    from mp_models.plss import PLSSDerivationRequest

    candidate, _, manifest = prepared(tmp_path, "plss-no-reference-no-nominal-section")
    assert [a["kind"] for a in manifest["artifacts"]] == ["document-text"]
    with pytest.raises(ValueError):
        PLSSDerivationRequest.model_validate(json.loads((candidate / "request.json").read_text()))


def test_delivery_fixture_contains_published_replayable_inputs_and_executes_export(tmp_path):
    from mp_models.dashboard import DashboardBundle
    from mp_models.delivery import DeliveryRequest
    from mp_review.delivery import prepare_delivery, publish_delivery

    candidate, _, _ = prepared(tmp_path, "export-published-revision-package")
    info = json.loads((candidate / "artifacts/source-1.json").read_text())
    bundle = DashboardBundle.model_validate_json((candidate / info["bundle"]).read_bytes())
    request = DeliveryRequest.model_validate_json((candidate / info["request"]).read_bytes())
    revision_dir = candidate / info["revision_dir"]
    snapshot = prepare_delivery(bundle, revision_dir, request)
    assert snapshot.canonical_verification == "not_requested"
    assert not snapshot.verified_export_eligible
    assert all(o.source_review_status == "unreviewed" for o in bundle.occurrences)
    response = publish_delivery(bundle, revision_dir, request, tmp_path / "delivery")
    assert response["status"] == "needs_review"
    assert {"drawing.svg", "drawing.pdf", "drawing.dxf"} <= response["artifacts"].keys()


@pytest.mark.parametrize(
    "skill,model_path",
    [
        ("plot-corridor", "mp_models.corridor:CorridorRequest"),
        ("plot-plss-reference", "mp_models.plss:PLSSDerivationRequest"),
        ("export-review-package", "mp_models.delivery:DeliveryRequest"),
    ],
)
def test_packaged_schemas_and_examples_match_authoritative_runtime_models(skill, model_path):
    import importlib

    module, cls = model_path.split(":")
    model = getattr(importlib.import_module(module), cls)
    references = ROOT / "plugins/metesparser/skills" / skill / "references"
    schema = json.loads((references / "request.schema.json").read_text())
    assert schema == model.model_json_schema()
    model.model_validate_json((references / "example.json").read_bytes())
