"""Synthetic source-ledger validation and deterministic stage regressions."""

import json
from pathlib import Path

import pytest
from mp_models.dashboard import DashboardBundle, PreparedDashboard
from mp_review.dashboard import prepare_dashboard, validate_prepared_dashboard
from pydantic import ValidationError

FIXTURES = Path(__file__).parent / "fixtures"


def data(kind="absolute"):
    return json.loads((FIXTURES / f"dashboard-{kind}.json").read_text())


def bundle(kind="absolute"):
    return DashboardBundle.model_validate(data(kind))


def test_absolute_record_calculation_and_verbatim_quotes():
    original = bundle()
    prepared = prepare_dashboard(original)
    result = prepared.calculations[0]
    assert result.engine_verified and result.engine_status == "checks_passed"
    assert result.misclosure_ft < 1e-10
    assert result.area_sq_ft == pytest.approx(5000)
    assert result.perimeter_ft == 300
    assert original.calls[0].quote == "  Course 1: 100 feet.  "
    assert original.occurrences[0].transcript.startswith("  BEGINNING")
    assert isinstance(original.calls, tuple)
    with pytest.raises(ValidationError):
        original.calls[0].quote = "modified"


def test_relative_geometry_does_not_invent_recorded_azimuths():
    original = bundle("relative")
    prepared = prepare_dashboard(original)
    result = prepared.calculations[0]
    assert result.geometry_status == "analyzed"
    assert result.area_sq_ft == pytest.approx(5000)
    assert result.misclosure_ft < 1e-10
    assert not result.engine_verified and not result.verified_export_eligible
    assert result.engine_status == "needs_review"
    assert all(c.call.bearing_azimuth_deg_from_north is None for c in original.calls)
    assert result.stated_angle_sum_deg == pytest.approx(360)


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda d: d["calls"][0].update(page_id="missing"), "cross-occurrence"),
        (lambda d: d["pages"][0].update(document_id="missing"), "unknown document"),
        (lambda d: d["pages"][0].update(id="doc-one"), "globally unique"),
        (lambda d: d["scenarios"][0]["edits"][0].update(call_id="missing"), "cross-occurrence"),
        (lambda d: d["evidence"][0].update(call_id="missing"), "cross-occurrence"),
        (lambda d: d["calculations"][0]["frame"].update(units="meters"), "ft"),
        (lambda d: d["pages"][0].update(image="javascript:alert(1)"), "embedded"),
        (lambda d: d["pages"][0].update(image_sha256="0" * 64), "SHA256"),
        (lambda d: d["scenarios"][0]["edits"][0].update(distance_ft=float("inf")), "finite"),
    ],
)
def test_invalid_ledgers_are_rejected(mutation, match):
    value = data()
    mutation(value)
    with pytest.raises(ValidationError, match=match):
        DashboardBundle.model_validate(value)


def test_unknown_call_and_uncertain_reading_are_not_verified():
    value = data()
    value["calls"][0].update(
        reading_status="unknown", reading_note="First digit obscured", call=None
    )
    prepared = prepare_dashboard(DashboardBundle.model_validate(value))
    assert prepared.calculations[0].geometry_status == "blocked"
    assert not prepared.calculations[0].engine_verified
    value = data()
    value["calls"][0].update(reading_status="uncertain", reading_note="Faint type")
    prepared = prepare_dashboard(DashboardBundle.model_validate(value))
    assert prepared.calculations[0].geometry_status == "analyzed"
    assert prepared.calculations[0].engine_verified
    assert not prepared.calculations[0].verified_export_eligible
    assert not prepared.manifest.source_review_complete


def test_missing_page_and_unattested_review_do_not_become_complete():
    value = data()
    value["documents"][0]["expected_page_count"] = 2
    prepared = prepare_dashboard(DashboardBundle.model_validate(value))
    assert not prepared.manifest.source_review_complete
    assert prepared.calculations[0].engine_verified
    assert not prepared.calculations[0].verified_export_eligible
    value = data()
    del value["occurrences"][0]["source_review_status"]
    prepared = prepare_dashboard(DashboardBundle.model_validate(value))
    assert not prepared.manifest.source_review_complete


def test_relative_input_cannot_substitute_distance_or_bearing():
    for field, value in [("distance_ft", 99), ("recorded_bearing_azimuth_deg_from_north", 45)]:
        source = data("relative")
        source["calculations"][0]["relative"]["courses"][0][field] = value
        with pytest.raises(ValidationError, match="preserve recorded"):
            DashboardBundle.model_validate(source)


def test_layout_and_scenario_changes_reuse_calculations(tmp_path):
    initial = prepare_dashboard(bundle(), cache_dir=tmp_path)
    value = data()
    value["title"] = "New layout title"
    value["scenarios"][0]["edits"][0]["distance_ft"] = 101
    changed = prepare_dashboard(DashboardBundle.model_validate(value), cache_dir=tmp_path)
    assert changed.manifest.cache_reused
    assert changed.calculations == initial.calculations
    assert changed.manifest.source_review_hash == initial.manifest.source_review_hash
    assert changed.manifest.calculation_input_hash == initial.manifest.calculation_input_hash
    assert changed.manifest.presentation_hash != initial.manifest.presentation_hash


def test_source_or_assumption_changes_invalidate_calculations(tmp_path):
    initial = prepare_dashboard(bundle(), cache_dir=tmp_path)
    value = data()
    value["calls"][0]["call"]["distance_ft"] = 100.5
    changed = prepare_dashboard(DashboardBundle.model_validate(value), cache_dir=tmp_path)
    assert not changed.manifest.cache_reused
    assert changed.manifest.source_review_hash != initial.manifest.source_review_hash
    assert changed.calculations[0].misclosure_ft == pytest.approx(0.5)
    value["calculations"][0]["assumptions"] = ["Additional explicit assumption"]
    assumption = prepare_dashboard(DashboardBundle.model_validate(value), cache_dir=tmp_path)
    assert not assumption.manifest.cache_reused
    assert assumption.manifest.source_review_hash == changed.manifest.source_review_hash
    assert assumption.manifest.calculation_input_hash != changed.manifest.calculation_input_hash


def test_tampered_stage_hash_causes_recomputation(tmp_path):
    initial = prepare_dashboard(bundle(), cache_dir=tmp_path)
    stage = json.loads((tmp_path / "calculations.json").read_text())
    stage[0]["area_sq_ft"] = 123
    (tmp_path / "calculations.json").write_text(json.dumps(stage))
    repaired = prepare_dashboard(bundle(), cache_dir=tmp_path)
    assert not repaired.manifest.cache_reused
    assert repaired.calculations == initial.calculations


def test_prepared_flags_are_freshly_validated():
    prepared = prepare_dashboard(bundle())
    value = prepared.model_dump(mode="json")
    value["calculations"][0]["area_sq_ft"] = 123
    with pytest.raises(ValueError, match="deterministic"):
        validate_prepared_dashboard(PreparedDashboard.model_validate(value))
    assert validate_prepared_dashboard(prepared) == prepared


def test_empty_call_ledger_cannot_claim_complete_source_review():
    value = data()
    value.update(calls=[], evidence=[], scenarios=[])
    prepared = prepare_dashboard(DashboardBundle.model_validate(value))
    assert not prepared.manifest.source_review_complete
    assert not prepared.calculations[0].source_review_complete


def test_contradictory_review_attestation_is_rejected():
    value = data()
    value["occurrences"][0]["reading_status"] = "uncertain"
    with pytest.raises(ValidationError, match="reviewed occurrence"):
        DashboardBundle.model_validate(value)


def test_scenario_cannot_borrow_another_occurrences_evidence_silently():
    value = data()
    value["occurrences"].append({**value["occurrences"][0], "id": "occ-two"})
    value["evidence"].append(
        {**value["evidence"][0], "id": "evidence-two", "occurrence_id": "occ-two", "call_id": None}
    )
    value["scenarios"][0]["edits"][0]["evidence_ids"] = ["evidence-two"]
    with pytest.raises(ValidationError, match="cross-occurrence evidence"):
        DashboardBundle.model_validate(value)


@pytest.mark.parametrize(
    "kind", ["wrong_course", "fabricated_course_quote", "fabricated_constraint_quote"]
)
def test_relative_evidence_must_match_the_referenced_source(kind):
    value = data("relative")
    relative = value["calculations"][0]["relative"]
    if kind == "wrong_course":
        relative["courses"][0]["source"]["reference"] = "call-two"
    elif kind == "fabricated_course_quote":
        relative["courses"][0]["source"]["quote"] = "fabricated 999 feet"
    else:
        relative["constraints"][0]["source"]["quote"] = "fabricated 45 degrees"
    with pytest.raises(ValidationError, match="source|quote"):
        DashboardBundle.model_validate(value)


def test_self_consistent_forged_cache_is_rejected(tmp_path):
    from mp_verify.dashboard import _hash

    initial = prepare_dashboard(bundle(), cache_dir=tmp_path)
    stage = json.loads((tmp_path / "calculations.json").read_text())
    stage[0]["area_sq_ft"] = 123
    (tmp_path / "calculations.json").write_text(json.dumps(stage))
    manifest = json.loads((tmp_path / "stage-manifest.json").read_text())
    manifest["calculation_output_hash"] = _hash(stage)
    (tmp_path / "stage-manifest.json").write_text(json.dumps(manifest))
    repaired = prepare_dashboard(bundle(), cache_dir=tmp_path)
    assert repaired.calculations == initial.calculations
    assert not repaired.manifest.cache_reused


def test_unreviewed_perfect_geometry_keeps_engine_and_source_status_separate():
    value = data()
    value["occurrences"][0]["source_review_status"] = "unreviewed"
    prepared = prepare_dashboard(DashboardBundle.model_validate(value))
    result = prepared.calculations[0]
    assert result.engine_verified and result.engine_status == "checks_passed"
    assert not result.source_review_complete and not result.verified_export_eligible
    assert result.checks and isinstance(result.checks, tuple)
    assert {check.status for check in result.checks} == {"passed", "not_applicable"}
    assert prepare_dashboard(bundle("relative")).calculations[0].checks == ()


def test_dashboard_file_requires_new_output_and_preserves_exact_input(tmp_path):
    import hashlib

    from mp_review.dashboard import dashboard_file

    source = tmp_path / "original.json"
    raw = (FIXTURES / "dashboard-absolute.json").read_bytes() + b"\n  \n"
    source.write_bytes(raw)
    existing = tmp_path / "existing"
    existing.mkdir()
    sentinel = existing / "dashboard.html"
    sentinel.write_text("preserve me")
    rejected = dashboard_file(source, existing)
    assert rejected["status"] == "error"
    assert sentinel.read_text() == "preserve me"
    assert list(existing.iterdir()) == [sentinel]
    directory = tmp_path / "new"
    result = dashboard_file(source, directory)
    assert result["status"] != "error", result
    assert (directory / "source.json").read_bytes() == raw
    assert result["input"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert source.read_bytes() == raw


def test_dashboard_file_accepts_symlinked_input_without_modifying_original(tmp_path):
    from mp_review.dashboard import dashboard_file

    source = tmp_path / "link.json"
    source.symlink_to(FIXTURES / "dashboard-absolute.json")
    output = tmp_path / "new"
    original = source.read_bytes()
    result = dashboard_file(source, output)
    assert result["status"] != "error", result
    assert source.is_symlink()
    assert source.read_bytes() == original
    assert (output / "source.json").read_bytes() == original


def test_intentional_symlink_parent_output_root_preserves_real_input(tmp_path):
    from mp_review.dashboard import dashboard_file

    actual = tmp_path / "actual"
    actual.mkdir()
    source = actual / "input.json"
    original = (FIXTURES / "dashboard-absolute.json").read_bytes()
    source.write_bytes(original)
    alias = tmp_path / "alias"
    alias.symlink_to(actual, target_is_directory=True)
    result = dashboard_file(alias / "input.json", alias / "output")
    assert result["status"] != "error", result
    assert (actual / "output" / "source.json").read_bytes() == original
    assert source.read_bytes() == original
    assert (actual / "output" / "dashboard.html").exists()


def test_render_manifest_tracks_renderer_without_invalidating_calculation_cache(
    tmp_path, monkeypatch
):
    import hashlib

    import mp_export.dashboard_html as renderer
    from mp_review.dashboard import dashboard_file

    cache = tmp_path / "cache"
    source = FIXTURES / "dashboard-absolute.json"
    first = dashboard_file(source, tmp_path / "one", cache_dir=cache)
    assert first["status"] != "error", first
    first_manifest = json.loads((tmp_path / "one" / "render-manifest.json").read_text())
    assert first_manifest["renderer_sha256"] == renderer.renderer_fingerprint()
    assert (
        first_manifest["html_sha256"]
        == hashlib.sha256((tmp_path / "one" / "dashboard.html").read_bytes()).hexdigest()
    )
    monkeypatch.setattr(renderer, "renderer_fingerprint", lambda: "f" * 64)
    second = dashboard_file(source, tmp_path / "two", cache_dir=cache)
    assert second["status"] != "error", second
    second_manifest = json.loads((tmp_path / "two" / "render-manifest.json").read_text())
    assert second_manifest["renderer_sha256"] == "f" * 64
    assert first_manifest["presentation_hash"] == second_manifest["presentation_hash"]
    assert (
        first["manifest"]["calculation_input_hash"] == second["manifest"]["calculation_input_hash"]
    )
    assert second["cache_reused"]


def test_certain_reading_requires_a_parsed_call():
    value = data()
    value["calls"][0]["call"] = None
    with pytest.raises(ValidationError, match="certain reading requires"):
        DashboardBundle.model_validate(value)


@pytest.mark.parametrize("stated_area", [None, 1.0])
def test_unavailable_exception_area_is_unknown_in_dashboard(stated_area):
    value = data()
    value["calls"].append(
        {
            "id": "call-exception",
            "occurrence_id": "occ-one",
            "page_id": "page-one",
            "quote": "Exception: northwardly ten feet",
            "reading_status": "certain",
            "call": {
                "course": 5,
                "direction_text": "northwardly",
                "distance_ft": 10,
                "is_exception": True,
            },
        }
    )
    value["calculations"][0]["stated_area_sq_ft"] = stated_area
    result = prepare_dashboard(DashboardBundle.model_validate(value)).calculations[0]
    assert result.area_sq_ft is None
    assert not result.engine_verified
    area_check = next(check for check in result.checks if check.name == "area_reasonableness")
    assert area_check.inputs["area_available"] is False
    if stated_area is not None:
        assert area_check.status == "blocked"


def test_diagnostic_cache_is_revalidated_and_old_manifests_safely_miss(tmp_path):
    first = prepare_dashboard(bundle(), cache_dir=tmp_path)
    assert prepare_dashboard(bundle(), cache_dir=tmp_path).manifest.cache_reused
    stage = json.loads((tmp_path / "diagnostics.json").read_text())
    stage[0]["baseline"]["residual"]["magnitude_ft"] = 123
    (tmp_path / "diagnostics.json").write_text(json.dumps(stage))
    repaired = prepare_dashboard(bundle(), cache_dir=tmp_path)
    assert not repaired.manifest.cache_reused
    assert repaired.diagnostics == first.diagnostics
    manifest = json.loads((tmp_path / "stage-manifest.json").read_text())
    manifest["calculator_version"] = "dashboard-1.0.2"
    manifest.pop("diagnostics_input_hash")
    manifest.pop("diagnostics_output_hash")
    (tmp_path / "stage-manifest.json").write_text(json.dumps(manifest))
    assert not prepare_dashboard(bundle(), cache_dir=tmp_path).manifest.cache_reused


def test_chord_only_curve_perimeter_is_unknown_in_dashboard():
    value = data()
    value["calls"][1]["call"] = {
        "course": 2,
        "direction_text": "curve to the right",
        "distance_ft": 50,
        "bearing_azimuth_deg_from_north": 90,
        "curve_dir": "right",
        "radius_ft": 100,
        "chord_bearing": "N 90°00' E",
        "chord_length_ft": 50,
    }
    result = prepare_dashboard(DashboardBundle.model_validate(value)).calculations[0]
    assert result.geometry_status == "analyzed"
    assert result.perimeter_ft is None
    assert result.precision_denominator is None
    assert result.area_sq_ft is None
    assert not result.engine_verified
