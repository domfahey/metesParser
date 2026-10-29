"""Saved alternatives preserve identity, exact drafts and publish atomically."""

import json
from pathlib import Path

import pytest
from mp_models.dashboard import DashboardBundle
from mp_models.revisions import revision_template
from mp_review.revisions import import_revision, load_revision, publish_revision


@pytest.fixture
def bundle():
    return DashboardBundle.model_validate_json(
        (Path(__file__).parent / "fixtures/dashboard-absolute.json").read_text()
    )


def edit(bundle, revision_id="alternative", **raw):
    data = revision_template(bundle, revision_id=revision_id).model_dump(mode="json")
    data["edits"] = [
        {
            "call_id": "call-one",
            "occurrence_id": "occ-one",
            "tract_id": "parcel-one",
            "document_id": "doc-one",
            "raw_fields": raw,
            "rationale": "  Check page 1.\n",
        }
    ]
    return data


def test_invalid_partial_bearing_and_note_survive_exactly(bundle, tmp_path):
    data = edit(bundle, bearing_azimuth_deg_from_north="N 12° ", notes="  annotation\n")
    prepared = import_revision(bundle, data)
    assert prepared.state == "draft"
    assert prepared.current_geometry == ()
    assert prepared.last_valid_geometry[0].revision_id == "baseline"
    assert prepared.revision.edits[0].raw_fields == data["edits"][0]["raw_fields"]
    result = publish_revision(bundle, data, tmp_path)
    assert result["save_state"] == "published"
    recovered = load_revision(bundle, tmp_path / "alternative")
    assert recovered == prepared
    assert recovered.revision.edits[0].rationale == "  Check page 1.\n"


def test_annotation_only_and_valid_bearing_are_advisory(bundle):
    prepared = import_revision(bundle, edit(bundle, notes="  only annotation  "))
    assert prepared.state == "parsed"
    assert prepared.current_geometry
    assert not prepared.canonical_status_changed
    prepared = import_revision(bundle, edit(bundle, bearing_azimuth_deg_from_north="N 45° E"))
    assert prepared.parsed_edits[0].bearing_azimuth_deg_from_north == 45
    assert not prepared.exportable


def test_tampered_baseline_late_generation_and_malformed_fail(bundle):
    data = edit(bundle, distance_ft="100")
    data["baseline"]["bundle_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="baseline"):
        import_revision(bundle, data)
    data = edit(bundle, distance_ft="100")
    with pytest.raises(ValueError, match="revision"):
        import_revision(bundle, data, expected_revision_id="newer")
    with pytest.raises(ValueError, match="generation"):
        import_revision(bundle, data, expected_generation=2)
    data["made_up"] = True
    with pytest.raises(ValueError):
        import_revision(bundle, data)


def test_immutable_publish_and_incomplete_manifest(bundle, tmp_path, monkeypatch):
    import mp_review.revisions as api

    data = edit(bundle, distance_ft="101")
    original = api._write_once

    def fail(path, content):
        if path.name == "manifest.json":
            raise OSError("interrupted publication")
        return original(path, content)

    monkeypatch.setattr(api, "_write_once", fail)
    assert publish_revision(bundle, data, tmp_path)["save_state"] == "failed"
    with pytest.raises(ValueError, match="incomplete"):
        load_revision(bundle, tmp_path / "alternative")
    monkeypatch.setattr(api, "_write_once", original)
    assert publish_revision(bundle, data, tmp_path)["save_state"] == "published"
    assert publish_revision(bundle, data, tmp_path)["save_state"] == "published"
    data["edits"][0]["raw_fields"]["distance_ft"] = "102"
    assert publish_revision(bundle, data, tmp_path)["save_state"] == "failed"
    assert (
        load_revision(bundle, tmp_path / "alternative").revision.edits[0].raw_fields["distance_ft"]
        == "101"
    )


def test_missing_call_is_not_deletion_and_source_requires_evidence(bundle):
    data = edit(bundle, distance_ft="101")
    data["tracts"][0]["call_order"].pop()
    with pytest.raises(ValueError, match="explicit remove"):
        import_revision(bundle, data)
    data = edit(bundle, distance_ft="101")
    data["kind"] = "source_correction"
    with pytest.raises(ValueError, match="source"):
        import_revision(bundle, data)
    data["edits"][0]["source_refs"] = [{"page_id": "page-one", "quote": "100 feet"}]
    assert import_revision(bundle, data).source_changes


def test_tampered_published_artifact_rejected(bundle, tmp_path):
    assert (
        publish_revision(bundle, edit(bundle, distance_ft="101"), tmp_path)["save_state"]
        == "published"
    )
    (tmp_path / "alternative" / "revision.json").write_text("{}")
    with pytest.raises(ValueError, match="hash"):
        load_revision(bundle, tmp_path / "alternative")


def _two_tracts(bundle):
    data = bundle.model_dump(mode="json")
    groups = (
        "documents",
        "pages",
        "parcels",
        "occurrences",
        "calls",
        "evidence",
        "calculations",
        "scenarios",
    )
    ids = {item["id"] for group in groups for item in data[group]}

    def remap(value):
        if isinstance(value, str):
            return "second-" + value if value in ids else value
        if isinstance(value, list):
            return [remap(x) for x in value]
        if isinstance(value, dict):
            return {k: remap(v) for k, v in value.items()}
        return value

    for group in groups:
        data[group] += remap(data[group])
    # Names are deliberately identical; only immutable IDs distinguish ownership.
    return DashboardBundle.model_validate(data)


def test_second_tract_failure_retry_and_rename_reorder_keep_identity(bundle, tmp_path, monkeypatch):
    import mp_review.revisions as api

    bundle = _two_tracts(bundle)
    prior = revision_template(bundle, revision_id="prior").model_dump(mode="json")
    assert publish_revision(bundle, prior, tmp_path)["save_state"] == "published"
    data = revision_template(bundle, revision_id="next").model_dump(mode="json")
    data["tracts"].reverse()
    data["tracts"][0]["label"] = "Renamed only"
    data["tracts"][0]["call_order"].reverse()
    original = api._write_once
    first_tract = f"tract-{data['tracts'][0]['occurrence_id']}.json"
    second_tract = f"tract-{data['tracts'][1]['occurrence_id']}.json"

    def fail(path, content):
        if path.name == second_tract:
            raise OSError("second emitted tract failed")
        return original(path, content)

    monkeypatch.setattr(api, "_write_once", fail)
    assert publish_revision(bundle, data, tmp_path)["save_state"] == "failed"
    assert (tmp_path / "next" / first_tract).is_file()
    assert not (tmp_path / "next" / second_tract).exists()
    assert not (tmp_path / "next" / "manifest.json").exists()
    assert load_revision(bundle, tmp_path / "prior").revision.id == "prior"
    with pytest.raises(ValueError, match="incomplete"):
        load_revision(bundle, tmp_path / "next")
    monkeypatch.setattr(api, "_write_once", original)
    assert publish_revision(bundle, data, tmp_path)["save_state"] == "published"
    loaded = load_revision(bundle, tmp_path / "next")
    assert loaded.revision.tracts[0].occurrence_id == "second-occ-one"
    assert loaded.revision.tracts[0].call_order[0] == "second-call-four"
    assert len(list((tmp_path / "next").glob("tract-*.json"))) == 2
    assert len(loaded.current_geometry) == 2


def test_parent_last_valid_geometry_separate_from_invalid_current(bundle, tmp_path):
    parent = edit(bundle, revision_id="parent", distance_ft="101")
    assert publish_revision(bundle, parent, tmp_path)["save_state"] == "published"
    draft = edit(bundle, revision_id="draft", distance_ft="10.")
    draft["edits"][0]["raw_fields"]["bearing_azimuth_deg_from_north"] = "S "
    draft["parent_revision_id"] = "parent"
    assert publish_revision(bundle, draft, tmp_path)["save_state"] == "published"
    loaded = load_revision(bundle, tmp_path / "draft")
    assert loaded.state == "draft"
    assert loaded.current_geometry == ()
    assert loaded.last_valid_geometry[0].revision_id == "parent"
    assert loaded.last_valid_geometry[0].plot.request.calls[0].call.distance_ft == 101
    assert loaded.revision.edits[0].raw_fields["distance_ft"] == "10."


def test_explicit_remove_not_retry_duplication_and_stale_save_isolated(bundle, tmp_path):
    data = revision_template(_two_tracts(bundle), revision_id="removed").model_dump(mode="json")
    data["tracts"][1]["action"] = "remove"
    result = publish_revision(_two_tracts(bundle), data, tmp_path)
    assert result["save_state"] == "published"
    assert len(load_revision(_two_tracts(bundle), tmp_path / "removed").current_geometry) == 1
    assert publish_revision(_two_tracts(bundle), data, tmp_path)["save_state"] == "published"
    older = edit(bundle, revision_id="older", distance_ft="101")
    newer = edit(bundle, revision_id="newer", distance_ft="102")
    assert publish_revision(bundle, newer, tmp_path)["save_state"] == "published"
    assert publish_revision(bundle, older, tmp_path)["save_state"] == "published"
    assert (
        load_revision(bundle, tmp_path / "newer").revision.edits[0].raw_fields["distance_ft"]
        == "102"
    )


def test_duplicate_json_nonfinite_unknown_and_cross_identity_rejected(bundle):
    from mp_review.revisions import import_revision

    data = edit(bundle, distance_ft="1")
    with pytest.raises(ValueError, match="[Dd]uplicate"):
        import_revision(
            bundle, json.dumps(data).replace('"generation": 0', '"generation": 0, "generation": 1')
        )
    data["edits"][0]["document_id"] = "wrong-document"
    with pytest.raises(ValueError, match="identity"):
        import_revision(bundle, data)
    data = edit(bundle, distance_ft="NaN")
    assert import_revision(bundle, data).state == "draft"
    data["edits"][0]["raw_fields"]["made_up"] = "something"
    with pytest.raises(ValueError):
        import_revision(bundle, data)


def test_correction_artifacts_retain_both_readings_without_source_review(bundle, tmp_path):
    data = edit(bundle, distance_ft="101")
    data["kind"] = "source_correction"
    data["edits"][0]["source_refs"] = [{"page_id": "page-one", "quote": "  101 feet  "}]
    result = publish_revision(bundle, data, tmp_path)
    assert result["save_state"] == "published"
    evidence = json.loads((tmp_path / "alternative" / "correction-evidence.json").read_text())
    assert evidence["changes"][0]["previous_quote"] == bundle.calls[0].quote
    assert evidence["changes"][0]["revised_quote"] == "  101 feet  "
    calls = json.loads((tmp_path / "alternative" / "source-calls.json").read_text())
    assert len(calls["revised_calls"]) == 4
    assert calls["revised_calls"][0]["call"]["distance_ft"] == 101
    assert calls["source_review_status"] == "unreviewed"
    assert calls["canonical_verification"] == "not_requested"
    assert load_revision(bundle, tmp_path / "alternative").revision.kind == "source_correction"


def test_manifest_schema_and_pending_raw_draft_integrity(bundle, tmp_path):
    data = edit(bundle, bearing_azimuth_deg_from_north="N ")
    assert publish_revision(bundle, data, tmp_path)["save_state"] == "published"
    path = tmp_path / "alternative"
    pending = json.loads((path / "pending.json").read_text())
    assert pending["revision"]["edits"][0]["raw_fields"]["bearing_azimuth_deg_from_north"] == "N "
    manifest = json.loads((path / "manifest.json").read_text())
    manifest["generation"] = False
    (path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="schema"):
        load_revision(bundle, path)


def test_revision_comparisons_recompute_and_invalid_draft_cannot_reuse_old_comparison():
    bundle = DashboardBundle.model_validate_json(
        (Path(__file__).parent / "fixtures/dashboard-comparison.json").read_text()
    )
    data = revision_template(bundle, revision_id="comparison-alternative").model_dump(mode="json")
    parsed = import_revision(bundle, data)
    assert parsed.comparisons[0].comparison is not None
    assert not parsed.comparisons[0].comparison.boundary_established
    call = bundle.calls[0]
    tract = next(t for t in data["tracts"] if t["occurrence_id"] == call.occurrence_id)
    data["edits"] = [
        {
            "call_id": call.id,
            "occurrence_id": call.occurrence_id,
            "tract_id": tract["id"],
            "document_id": tract["document_ids"][0],
            "raw_fields": {"distance_ft": "bad"},
        }
    ]
    invalid = import_revision(bundle, data)
    assert invalid.comparisons[0].comparison is None
    assert invalid.comparisons[0].unavailable_reason


def structured_line(bearing="90", distance="50", **extra):
    raw = {
        "geometry_type": "line",
        "role": "boundary",
        "orientation": "supplied",
        "bearing_format": "decimal_azimuth",
        "bearing_value": bearing,
        "distance_value": distance,
        "distance_unit": "feet",
    }
    raw.update(extra)
    return raw


def added(bundle, **raw):
    data = revision_template(bundle, revision_id="inserted").model_dump(mode="json")
    data["schema_version"] = "1.1"
    data["tracts"][0]["call_order"] = ["call-one", "inserted-east", "call-three", "call-four"]
    data["edits"] = [
        {
            "call_id": "call-two",
            "occurrence_id": "occ-one",
            "tract_id": "parcel-one",
            "document_id": "doc-one",
            "action": "remove",
        },
        {
            "call_id": "inserted-east",
            "occurrence_id": "occ-one",
            "tract_id": "parcel-one",
            "document_id": "doc-one",
            "action": "add",
            "structured_input": structured_line(**raw),
        },
    ]
    return data


def test_insert_remove_reorder_preserves_ids_and_original_source(bundle):
    data = added(bundle)
    baseline = bundle.model_dump(mode="json")
    prepared = import_revision(bundle, data)
    assert prepared.state == "parsed"
    geometry = prepared.current_geometry[0].plot
    assert geometry.geometry.misclosure_ft == pytest.approx(0, abs=1e-10)
    assert [c.id for c in geometry.request.calls] == [
        "call-one",
        "inserted-east",
        "call-three",
        "call-four",
    ]
    assert [c.call.course for c in geometry.request.calls] == [1, 2, 3, 4]
    inserted = next(c for c in prepared.prepared_calls if c.id == "inserted-east")
    assert inserted.source_status == "hypothetical"
    assert inserted.quote is None and inserted.original_source is None
    removed = next(c for c in prepared.prepared_calls if c.id == "call-two")
    assert removed.removed and removed.original_source["quote"] == bundle.calls[1].quote
    data["tracts"][0]["call_order"] = ["call-four", "call-three", "inserted-east", "call-one"]
    reordered = import_revision(bundle, data)
    assert reordered.state == "parsed"
    assert [c.call.course for c in reordered.current_geometry[0].plot.request.calls] == [1, 2, 3, 4]
    assert bundle.model_dump(mode="json") == baseline


@pytest.mark.parametrize(
    "format,value,extra,expected",
    [
        ("decimal_azimuth", "45.3020", {}, 45.302),
        ("packed_dms_azimuth", "45.3020", {}, 45 + 30 / 60 + 20 / 3600),
        ("quadrant_dms", "S 45°30'20\" W", {}, 225 + 30 / 60 + 20 / 3600),
        (
            "quadrant_packed_dms",
            "45.3020",
            {"quadrant_ns": "S", "quadrant_ew": "W"},
            225 + 30 / 60 + 20 / 3600,
        ),
    ],
)
def test_explicit_angle_formats(bundle, format, value, extra, expected):
    data = added(bundle)
    data["edits"][1]["structured_input"].update(bearing_format=format, bearing_value=value, **extra)
    prepared = import_revision(bundle, data)
    assert prepared.state == "parsed"
    call = next(c for c in prepared.prepared_calls if c.id == "inserted-east")
    assert call.call.bearing_azimuth_deg_from_north == pytest.approx(expected)


def test_partial_curve_and_unknown_units_save_reopen_exactly(bundle, tmp_path):
    data = added(bundle)
    raw = {
        "geometry_type": "circular_arc",
        "role": "boundary",
        "orientation": "supplied",
        "bearing_format": "decimal_azimuth",
        "bearing_value": "90",
        "distance_unit": "unknown",
        "radius_value": " 10.",
        "delta_value": "180",
        "delta_format": "decimal_degrees",
        "curve_dir": "left",
        "notes": "  preserve partial curve\n",
    }
    data["edits"][1]["structured_input"] = raw
    result = publish_revision(bundle, data, tmp_path)
    assert result["save_state"] == "published"
    loaded = load_revision(bundle, tmp_path / "inserted")
    assert loaded.state == "draft" and not loaded.current_geometry
    assert loaded.revision.edits[1].structured_input == raw


def test_inserted_source_correction_requires_evidence(bundle):
    data = added(bundle)
    data["kind"] = "source_correction"
    with pytest.raises(ValueError, match="source"):
        import_revision(bundle, data)
    for item in data["edits"]:
        item["rationale"] = "Page 1 corrects selected course"
        item["source_refs"] = [{"page_id": "page-one", "quote": "East 50 feet"}]
    prepared = import_revision(bundle, data)
    assert prepared.state == "parsed"
    inserted = next(c for c in prepared.prepared_calls if c.id == "inserted-east")
    assert inserted.quote == "East 50 feet" and inserted.source_status == "source_correction"
    assert not prepared.canonical_status_changed


def arc_revision(bundle, **arc_updates):
    data = revision_template(bundle, revision_id="arc-revision").model_dump(mode="json")
    data["schema_version"] = "1.1"
    data["tracts"][0]["call_order"] = ["new-arc", "new-close"]
    data["edits"] = [
        {
            "call_id": c.id,
            "occurrence_id": "occ-one",
            "tract_id": "parcel-one",
            "document_id": "doc-one",
            "action": "remove",
        }
        for c in bundle.calls
    ]
    arc = {
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
    }
    arc.update(arc_updates)
    for cid, raw in [
        ("new-arc", arc),
        ("new-close", structured_line(bearing="270", distance="20")),
    ]:
        data["edits"].append(
            {
                "call_id": cid,
                "occurrence_id": "occ-one",
                "tract_id": "parcel-one",
                "document_id": "doc-one",
                "action": "add",
                "structured_input": raw,
            }
        )
    return data


def test_analytic_semicircle_retains_arc_instead_of_chord(bundle):
    import math

    prepared = import_revision(bundle, arc_revision(bundle))
    assert prepared.state == "parsed", prepared.errors
    geometry = prepared.current_geometry[0].plot.geometry
    assert geometry.primitives[0].kind == "arc"
    assert geometry.primitives[0].length_ft == pytest.approx(10 * math.pi)
    assert geometry.area_sq_ft == pytest.approx(50 * math.pi)
    assert geometry.misclosure_ft == pytest.approx(0, abs=1e-10)


@pytest.mark.parametrize(
    "extra",
    [
        {"arc_length_value": "20"},
        {"chord_length_value": "25"},
        {"chord_bearing_value": "0", "chord_bearing_format": "decimal_azimuth"},
        {"delta_value": "360"},
        {"delta_value": "450"},
        {"radius_value": ""},
        {"delta_format": "guess"},
        {"curve_type": "spiral"},
    ],
)
def test_conflicting_or_unsupported_curve_remains_raw_draft(bundle, extra):
    data = arc_revision(bundle, **extra)
    prepared = import_revision(bundle, data)
    assert prepared.state == "draft" and not prepared.current_geometry
    assert prepared.revision.edits[4].structured_input == data["edits"][4]["structured_input"]


def test_metric_conversion_uses_declared_survey_foot_and_unknown_blocks(bundle):
    data = bundle.model_dump(mode="json")
    data["calculations"][0]["frame"]["foot_definition"] = "us_survey_ft"
    survey = DashboardBundle.model_validate(data)
    request = added(survey)
    request["edits"][1]["structured_input"].update(distance_unit="meters", distance_value="30.48")
    prepared = import_revision(survey, request)
    assert prepared.state == "parsed"
    inserted = next(c for c in prepared.prepared_calls if c.id == "inserted-east")
    assert inserted.call.distance_ft == pytest.approx(99.9998)
    request = added(bundle)
    request["edits"][1]["structured_input"].update(distance_unit="meters", distance_value="30.48")
    assert import_revision(bundle, request).state == "draft"


def test_annotations_and_reference_roles_are_retained_without_geometry(bundle):
    data = added(bundle)
    data["tracts"][0]["call_order"].append("annotation")
    data["edits"].append(
        {
            "call_id": "annotation",
            "occurrence_id": "occ-one",
            "tract_id": "parcel-one",
            "document_id": "doc-one",
            "action": "add",
            "structured_input": {
                "geometry_type": "annotation",
                "role": "reference",
                "notes": "  tree found\n",
            },
        }
    )
    prepared = import_revision(bundle, data)
    assert prepared.state == "parsed"
    assert len(prepared.current_geometry[0].plot.geometry.primitives) == 4
    assert next(c for c in prepared.prepared_calls if c.id == "annotation").call is None
    assert prepared.revision.edits[-1].structured_input["notes"] == "  tree found\n"


def test_inherited_orientation_requires_adjacent_supported_call(bundle):
    data = added(bundle)
    data["edits"][1]["structured_input"].update(orientation="inherited_tangent", bearing_value="")
    prepared = import_revision(bundle, data)
    assert prepared.state == "parsed"
    assert (
        next(
            c for c in prepared.prepared_calls if c.id == "inserted-east"
        ).call.bearing_azimuth_deg_from_north
        == 0
    )
    data["tracts"][0]["call_order"] = ["inserted-east", "call-one", "call-three", "call-four"]
    assert import_revision(bundle, data).state == "draft"


def test_selector_flags_and_unsupported_inputs_remain_exact_drafts(bundle, tmp_path):
    data = added(bundle)
    raw = data["edits"][1]["structured_input"]
    raw.update(bearing_format="  uncertain format\n", is_meander="not-known", notes="  original  ")
    assert publish_revision(bundle, data, tmp_path)["save_state"] == "published"
    restored = load_revision(bundle, tmp_path / "inserted")
    assert restored.state == "draft"
    assert restored.revision.edits[1].structured_input == raw


def test_tie_and_omitted_roles_retain_evidence_outside_boundary(bundle):
    data = added(bundle)
    for cid, role in [("tie", "tie_in"), ("reference", "reference"), ("omitted", "omitted")]:
        raw = structured_line(bearing="45", distance="17")
        raw["role"] = role
        data["tracts"][0]["call_order"].insert(0, cid)
        data["edits"].append(
            {
                "call_id": cid,
                "occurrence_id": "occ-one",
                "tract_id": "parcel-one",
                "document_id": "doc-one",
                "action": "add",
                "structured_input": raw,
            }
        )
    prepared = import_revision(bundle, data)
    assert prepared.state == "parsed", prepared.errors
    assert len(prepared.prepared_calls) == 8  # four boundary, three excluded, one removed
    geometry = prepared.current_geometry[0].plot.geometry
    assert len(geometry.primitives) == 4
    assert geometry.area_sq_ft == pytest.approx(5000)
    assert next(c for c in prepared.prepared_calls if c.id == "tie").call.is_tie_in


def test_inheritance_cannot_jump_excluded_source_or_removed_course(bundle):
    data = added(bundle)
    data["edits"][1]["structured_input"].update(orientation="inherited_tangent", bearing_value="")
    data["tracts"][0]["call_order"].insert(1, "reference")
    data["edits"].append(
        {
            "call_id": "reference",
            "occurrence_id": "occ-one",
            "tract_id": "parcel-one",
            "document_id": "doc-one",
            "action": "add",
            "structured_input": {
                "geometry_type": "annotation",
                "role": "reference",
                "notes": "reference only",
            },
        }
    )
    assert import_revision(bundle, data).state == "draft"
    # An existing source call cannot inherit from a different preceding source course.
    data = revision_template(bundle, revision_id="wrong-sequence").model_dump(mode="json")
    data["schema_version"] = "1.1"
    data["tracts"][0]["call_order"] = ["call-one", "call-three", "call-four"]
    data["edits"] = [
        {
            "call_id": "call-two",
            "occurrence_id": "occ-one",
            "tract_id": "parcel-one",
            "document_id": "doc-one",
            "action": "remove",
        },
        {
            "call_id": "call-three",
            "occurrence_id": "occ-one",
            "tract_id": "parcel-one",
            "document_id": "doc-one",
            "structured_input": structured_line(bearing="", orientation="inherited_tangent"),
        },
    ]
    assert import_revision(bundle, data).state == "draft"


def test_schema_one_preserves_existing_patch_only_contract(bundle):
    data = added(bundle)
    data["schema_version"] = "1.0"
    with pytest.raises(ValueError, match="1.1"):
        import_revision(bundle, data)


def test_added_call_explicit_tombstone_preserves_prior_raw_input(bundle, tmp_path):
    data = added(bundle)
    assert publish_revision(bundle, data, tmp_path)["save_state"] == "published"
    data["id"] = "removed-inserted"
    data["parent_revision_id"] = "inserted"
    data["tracts"][0]["call_order"].remove("inserted-east")
    data["edits"][1]["action"] = "remove"
    assert publish_revision(bundle, data, tmp_path)["save_state"] == "published"
    loaded = load_revision(bundle, tmp_path / "removed-inserted")
    assert loaded.state == "parsed"
    tombstone = next(c for c in loaded.prepared_calls if c.id == "inserted-east")
    assert tombstone.removed and tombstone.original_source is None
    assert loaded.revision.edits[1].structured_input["distance_value"] == "50"
    assert all(c.id != "inserted-east" for c in loaded.current_geometry[0].plot.request.calls)
    assert load_revision(bundle, tmp_path / "inserted").current_geometry[
        0
    ].plot.geometry.misclosure_ft == pytest.approx(0, abs=1e-10)


def test_added_identity_cannot_reuse_document_id(bundle):
    data = added(bundle)
    data["tracts"][0]["call_order"][1] = "doc-one"
    data["edits"][1]["call_id"] = "doc-one"
    with pytest.raises(ValueError, match="distinct stable"):
        import_revision(bundle, data)


def test_packed_tangent_and_chord_have_independent_quadrant_selectors(bundle):
    import math

    data = arc_revision(
        bundle,
        bearing_format="quadrant_packed_dms",
        bearing_value="45.0000",
        quadrant_ns="N",
        quadrant_ew="E",
        chord_bearing_format="quadrant_packed_dms",
        chord_bearing_value="45.0000",
        chord_quadrant_ns="S",
        chord_quadrant_ew="E",
    )
    data["edits"][5]["structured_input"].update(bearing_value="315")
    prepared = import_revision(bundle, data)
    assert prepared.state == "parsed", prepared.errors
    arc = prepared.current_geometry[0].plot.geometry.primitives[0]
    assert arc.start_tangent_deg == pytest.approx(45)
    assert arc.end == pytest.approx((10 * math.sqrt(2), -10 * math.sqrt(2)))
    assert prepared.current_geometry[0].plot.geometry.misclosure_ft == pytest.approx(0, abs=1e-10)
    raw = next(c for c in prepared.prepared_calls if c.id == "new-arc").raw_input
    assert raw["quadrant_ns"] == "N" and raw["chord_quadrant_ns"] == "S"


def test_partial_prefixed_quadrant_cannot_fall_back_to_shared_selector(bundle):
    data = arc_revision(
        bundle,
        bearing_format="quadrant_packed_dms",
        bearing_value="45.0000",
        quadrant_ns="N",
        quadrant_ew="E",
        chord_bearing_format="quadrant_packed_dms",
        chord_bearing_value="45.0000",
        chord_quadrant_ns="S",
    )
    prepared = import_revision(bundle, data)
    assert prepared.state == "draft"
    assert "chord_quadrant_ns" in prepared.revision.edits[4].structured_input


def test_legacy_shared_packed_chord_quadrants_keep_prior_meaning(bundle):
    data = arc_revision(
        bundle,
        bearing_format="quadrant_packed_dms",
        bearing_value="10.0000",
        quadrant_ns="N",
        quadrant_ew="E",
        delta_value="20",
        chord_bearing_format="quadrant_packed_dms",
        chord_bearing_value="20.0000",
    )
    prepared = import_revision(bundle, data)
    assert prepared.state == "parsed", prepared.errors
    arc = prepared.current_geometry[0].plot.geometry.primitives[0]
    assert arc.start_tangent_deg == pytest.approx(10)
    assert arc.sweep_deg == pytest.approx(20)
    raw = prepared.revision.edits[4].structured_input
    assert "chord_quadrant_ns" not in raw and raw["quadrant_ns"] == "N"


def test_decimal_chord_serialization_keeps_redundant_orientation_precision(bundle):
    import math

    tangent = 10.123456789
    data = arc_revision(
        bundle,
        bearing_value=str(tangent),
        delta_value="20",
        chord_bearing_format="decimal_azimuth",
        chord_bearing_value=str(tangent + 10),
    )
    prepared = import_revision(bundle, data)
    assert prepared.state == "parsed", prepared.errors
    arc = prepared.current_geometry[0].plot.geometry.primitives[0]
    assert arc.start_tangent_deg == pytest.approx(tangent, abs=1e-12)
    chord = 20 * math.sin(math.radians(10))
    expected = (
        chord * math.sin(math.radians(tangent + 10)),
        chord * math.cos(math.radians(tangent + 10)),
    )
    assert arc.end == pytest.approx(expected, abs=1e-12)


def test_delayed_rejected_save_retains_newer_edit_other_document_and_exact_retry(
    bundle, tmp_path, monkeypatch
):
    """Delay a real old writer, publish newer contexts, reject, then retry only its own ID."""
    import threading
    import time

    import mp_review.revisions as api

    store = tmp_path / "revision-store"
    old = edit(bundle, revision_id="older-delay", distance_ft="101")
    newer = edit(
        bundle,
        revision_id="newer-edit",
        distance_ft=" 102.00 ",
        notes="  Newer edit while prior save waits\n",
    )
    newer["generation"] = old["generation"] + 1
    other_data = _two_tracts(bundle).model_dump(mode="json")
    for group in (
        "documents",
        "pages",
        "parcels",
        "occurrences",
        "calls",
        "evidence",
        "calculations",
        "scenarios",
    ):
        other_data[group] = [item for item in other_data[group] if item["id"].startswith("second-")]
    other_data["title"] = "Independent other document"
    other_bundle = DashboardBundle.model_validate(other_data)
    other = revision_template(
        other_bundle, revision_id="other-document", baseline_id="other-baseline"
    )
    entered, release = threading.Event(), threading.Event()
    timing = {}
    results = []
    original = api._write_once

    def reject_delayed_old_writer(path, content):
        if path.parent.name == old["id"] and path.name == "tract-occ-one.json":
            timing["started"] = time.monotonic()
            entered.set()
            if not release.wait(timeout=10):
                raise OSError("Test writer release deadline exceeded")
            timing["elapsed"] = time.monotonic() - timing["started"]
            raise OSError("Delayed old save explicitly rejected")
        return original(path, content)

    monkeypatch.setattr(api, "_write_once", reject_delayed_old_writer)
    writer = threading.Thread(
        target=lambda: results.append(publish_revision(bundle, old, store)), daemon=True
    )
    writer.start()
    try:
        assert entered.wait(timeout=5), "Old save did not reach the controlled writer"
        assert not (store / old["id"] / "manifest.json").exists()
        assert publish_revision(bundle, newer, store)["save_state"] == "published"
        assert publish_revision(other_bundle, other, store)["save_state"] == "published"
        # This is an actual publication delay, distinct from the browser File.text import test.
        remaining = max(0.0, 2.6 - (time.monotonic() - timing["started"]))
        assert not release.wait(timeout=remaining)
    finally:
        release.set()
        writer.join(timeout=10)
    assert not writer.is_alive()
    assert timing["elapsed"] >= 2.6
    assert results[0]["save_state"] == "failed"
    assert "explicitly rejected" in results[0]["errors"][0]
    assert not (store / old["id"] / "manifest.json").exists()
    with pytest.raises(ValueError, match="incomplete"):
        load_revision(bundle, store / old["id"])
    current = load_revision(bundle, store / newer["id"])
    assert current.revision.generation == 1
    assert current.revision.edits[0].raw_fields == newer["edits"][0]["raw_fields"]
    independent = load_revision(other_bundle, store / other.id)
    assert independent.revision.baseline == other.baseline
    assert independent.revision.tracts[0].document_ids == ("second-doc-one",)

    def retained_bytes(directory):
        return {
            path.relative_to(directory).as_posix(): path.read_bytes()
            for path in directory.rglob("*")
            if path.is_file()
        }

    newer_bytes = retained_bytes(store / newer["id"])
    other_bytes = retained_bytes(store / other.id)
    monkeypatch.setattr(api, "_write_once", original)
    assert publish_revision(bundle, old, store)["save_state"] == "published"
    assert publish_revision(bundle, old, store)["save_state"] == "published"
    recovered = load_revision(bundle, store / old["id"])
    assert recovered.revision.id == old["id"] and recovered.revision.generation == 0
    assert recovered.revision.edits[0].raw_fields["distance_ft"] == "101"
    assert len(list((store / old["id"]).glob("tract-*.json"))) == 1
    assert retained_bytes(store / newer["id"]) == newer_bytes
    assert retained_bytes(store / other.id) == other_bytes
    assert load_revision(bundle, store / newer["id"]) == current
    assert load_revision(other_bundle, store / other.id) == independent


def test_added_call_and_tombstone_parse_and_save_under_schema_1_2(bundle, tmp_path):
    data = added(bundle)
    data["schema_version"] = "1.2"
    prepared = import_revision(bundle, data)
    assert prepared.state == "parsed"
    assert any(c.id == "inserted-east" for c in prepared.prepared_calls)
    assert publish_revision(bundle, data, tmp_path)["save_state"] == "published"
    loaded = load_revision(bundle, tmp_path / "inserted")
    assert loaded.state == "parsed"
    assert loaded.revision.schema_version == "1.2"
    data["id"] = "removed-inserted"
    data["parent_revision_id"] = "inserted"
    data["tracts"][0]["call_order"].remove("inserted-east")
    data["edits"][1]["action"] = "remove"
    assert publish_revision(bundle, data, tmp_path)["save_state"] == "published"
    tombstone = load_revision(bundle, tmp_path / "removed-inserted")
    assert tombstone.state == "parsed"
    assert all(c.id != "inserted-east" for c in tombstone.current_geometry[0].plot.request.calls)
