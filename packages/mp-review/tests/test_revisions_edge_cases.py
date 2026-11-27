"""High-signal validation, relative-edit, corridor-inventory, and immutability tests for revisions."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest
from mp_models.dashboard import DashboardBundle
from mp_models.revisions import revision_template
from mp_review.revisions import (
    import_revision,
    load_revision,
    publish_revision,
)

FIXTURES = Path(__file__).parent / "fixtures"
PLUGIN = Path(__file__).resolve().parents[3] / "plugins/metesparser"


def _abs_bundle() -> DashboardBundle:
    return DashboardBundle.model_validate_json((FIXTURES / "dashboard-absolute.json").read_text())


def _rel_bundle() -> DashboardBundle:
    return DashboardBundle.model_validate_json((FIXTURES / "dashboard-relative.json").read_text())


def _edit(bundle: DashboardBundle, revision_id: str = "rev-1", **raw: str) -> dict:
    data = revision_template(bundle, revision_id=revision_id).model_dump(mode="json")
    data["edits"] = [
        {
            "call_id": bundle.calls[0].id,
            "occurrence_id": bundle.occurrences[0].id,
            "tract_id": bundle.parcels[0].id,
            "document_id": bundle.documents[0].id,
            "raw_fields": raw,
            "rationale": "Test rationale.",
        }
    ]
    return data


def _structured_add(
    bundle: DashboardBundle, structured_input: dict[str, str], revision_id: str = "rev-add"
) -> dict:
    data = revision_template(bundle, revision_id=revision_id).model_dump(mode="json")
    data["schema_version"] = "1.1"
    data["tracts"][0]["call_order"].append("call-added")
    data["edits"] = [
        {
            "action": "add",
            "call_id": "call-added",
            "occurrence_id": bundle.occurrences[0].id,
            "tract_id": bundle.parcels[0].id,
            "document_id": bundle.documents[0].id,
            "structured_input": structured_input,
            "rationale": "Test structured input.",
        }
    ]
    return data


def test_number_and_angle_bounds_and_format_guardrails():
    bundle = _abs_bundle()
    for field, value, expected_error in (
        ("bearing_azimuth_deg_from_north", "N 95° E", "Invalid quadrant bearing"),
        ("distance_ft", "9" * 400, "finite"),
        ("distance_ft", "0", "positive"),
        ("bearing_azimuth_deg_from_north", "360", "below 360"),
    ):
        prepared = import_revision(bundle, _edit(bundle, **{field: value}))
        assert prepared.state == "draft"
        assert any(expected_error in err.message for err in prepared.errors), prepared.errors

    rel_bundle = _rel_bundle()
    interior = next(
        c for c in rel_bundle.calculations[0].relative.constraints if c.kind == "interior"
    )
    rel_data = revision_template(rel_bundle, revision_id="rel-ang-360").model_dump(mode="json")
    rel_data["edits"] = [
        {
            "call_id": interior.to_course,
            "occurrence_id": rel_bundle.occurrences[0].id,
            "tract_id": rel_bundle.parcels[0].id,
            "document_id": rel_bundle.documents[0].id,
            "raw_fields": {"interior_angle_deg": "360"},
            "rationale": "Out-of-bounds interior angle.",
        }
    ]
    prepared_rel = import_revision(rel_bundle, rel_data)
    assert prepared_rel.state == "draft"
    assert any("Interior angle" in err.message for err in prepared_rel.errors), prepared_rel.errors

    base_line = {
        "geometry_type": "line",
        "role": "boundary",
        "orientation": "supplied",
        "distance_value": "100",
        "distance_unit": "feet",
    }
    for bad_angle, expected_error in (
        ({"bearing_format": "quadrant_dms", "bearing_value": "45.0"}, "N/S and E/W"),
        ({"bearing_format": "packed_dms_azimuth", "bearing_value": "360.0000"}, "Packed azimuth"),
    ):
        prepared = import_revision(bundle, _structured_add(bundle, {**base_line, **bad_angle}))
        assert prepared.state == "draft"
        assert any(expected_error in err.message for err in prepared.errors), prepared.errors


def test_structured_call_validation_for_annotations_lines_and_curves():
    bundle = _abs_bundle()
    base_line = {
        "geometry_type": "line",
        "role": "boundary",
        "orientation": "supplied",
        "bearing_format": "decimal_azimuth",
        "bearing_value": "90",
        "distance_value": "100",
        "distance_unit": "feet",
    }

    for structured_input, expected_error in (
        ({**base_line, "rogue": "1"}, "Unsupported structured fields"),
        ({**base_line, "role": "mystery"}, "supported course role"),
        ({**base_line, "radial_bearing_value": "45"}, "Radial-bearing"),
        ({"geometry_type": "annotation", "role": "boundary"}, "reference or intentionally omitted"),
        (
            {"geometry_type": "annotation", "role": "reference", "distance_value": "10"},
            "discard geometric input",
        ),
        ({**base_line, "geometry_type": "spline"}, "Unsupported geometry type"),
        ({**base_line, "bearing_value": ""}, "complete supplied bearing"),
        ({**base_line, "orientation": "guessed"}, "supplied or inherited_tangent"),
        ({**base_line, "is_exception": "yes"}, "explicit true or false"),
        ({**base_line, "is_tie_in": "true"}, "Tie-in flag conflicts"),
        ({**base_line, "curve_dir": "right"}, "discard curve evidence"),
    ):
        prepared = import_revision(bundle, _structured_add(bundle, structured_input))
        assert prepared.state == "draft"
        assert any(expected_error in err.message for err in prepared.errors), prepared.errors

    base_arc = {
        "geometry_type": "circular_arc",
        "role": "boundary",
        "orientation": "supplied",
        "bearing_format": "decimal_azimuth",
        "bearing_value": "0",
        "curve_dir": "right",
        "radius_value": "100",
        "distance_unit": "feet",
    }
    chord_arc = {
        **base_arc,
        "bearing_value": "",
        "chord_length_value": "50",
        "chord_bearing_format": "decimal_azimuth",
        "chord_bearing_value": "45",
        "distance_value": "99",
    }
    packed_arc = {
        **base_arc,
        "delta_format": "packed_dms",
        "delta_value": "90.0000",
        "distance_value": "157.07963",
    }

    for structured_input, expected_error in (
        ({**base_arc, "curve_dir": "straight"}, "left/right"),
        (base_arc, "radius and sweep or arc length"),
        (chord_arc, "conflicts with supplied chord length"),
        (
            {**base_arc, "radius_value": "10", "arc_length_value": "62.83185307179586"},
            "Full circles",
        ),
        ({**packed_arc, "distance_value": "200"}, "conflicts with supplied circular arc length"),
    ):
        prepared = import_revision(bundle, _structured_add(bundle, structured_input))
        assert prepared.state == "draft"
        assert any(expected_error in err.message for err in prepared.errors), prepared.errors

    # Packed DMS central angle succeeds & matching distance_value is preserved
    prepared_ok = import_revision(bundle, _structured_add(bundle, packed_arc))
    assert prepared_ok.state == "parsed", prepared_ok.errors
    added = next(c for c in prepared_ok.prepared_calls if c.id == "call-added")
    assert added.call is not None and added.role == "boundary"
    assert added.call.delta_deg == pytest.approx(90.0)
    assert added.call.distance_ft == pytest.approx(157.07963)


def test_identity_validation_and_unresolved_source_call_patches():
    bundle = _abs_bundle()

    # Missing/wrong occurrence in tract inventory
    missing_tract = revision_template(bundle, revision_id="r1").model_dump(mode="json")
    missing_tract["tracts"][0]["occurrence_id"] = "occ-wrong"
    with pytest.raises(ValueError, match="Complete tract inventory"):
        import_revision(bundle, missing_tract)

    # Source correction cannot remove an entire tract
    rm_tract = revision_template(bundle, revision_id="r2").model_dump(mode="json")
    rm_tract["kind"] = "source_correction"
    rm_tract["tracts"][0]["action"] = "remove"
    with pytest.raises(ValueError, match="tract removal"):
        import_revision(bundle, rm_tract)

    # Tract parcel/document mismatch
    bad_tract = revision_template(bundle, revision_id="r3").model_dump(mode="json")
    bad_tract["tracts"][0]["id"] = "wrong-parcel"
    with pytest.raises(ValueError, match="document/parcel identity"):
        import_revision(bundle, bad_tract)

    # Added call with wrong tract_id
    bad_add = revision_template(bundle, revision_id="r4").model_dump(mode="json")
    bad_add["schema_version"] = "1.1"
    bad_add["tracts"][0]["call_order"].append("call-new")
    bad_add["edits"] = [
        {
            "action": "add",
            "call_id": "call-new",
            "occurrence_id": "occ-one",
            "tract_id": "wrong-parcel",
            "document_id": "doc-one",
            "structured_input": {
                "geometry_type": "line",
                "role": "boundary",
                "orientation": "supplied",
                "bearing_format": "decimal_azimuth",
                "bearing_value": "90",
                "distance_value": "10",
                "distance_unit": "feet",
            },
            "rationale": "Added",
        }
    ]
    with pytest.raises(ValueError, match="Added call document/tract/occurrence"):
        import_revision(bundle, bad_add)

    # Unknown page_id on edit
    bad_page = _edit(bundle, distance_ft="100")
    bad_page["edits"][0]["page_id"] = "missing-page"
    with pytest.raises(ValueError, match="cross-document source page"):
        import_revision(bundle, bad_page)

    # Removed tract cannot contain call edits
    edit_on_removed = _edit(bundle, distance_ft="100")
    edit_on_removed["tracts"][0]["action"] = "remove"
    with pytest.raises(ValueError, match="Removed tract cannot also contain call edits"):
        import_revision(bundle, edit_on_removed)

    # Unknown evidence_id on edit
    bad_ev = _edit(bundle, distance_ft="100")
    bad_ev["edits"][0]["evidence_ids"] = ["no-such-ev"]
    with pytest.raises(ValueError, match="Unknown or cross-call source evidence"):
        import_revision(bundle, bad_ev)

    # Unknown page_id in source_refs
    bad_ref = _edit(bundle, distance_ft="100")
    bad_ref["edits"][0]["source_refs"] = [{"page_id": "missing-page", "quote": "q"}]
    with pytest.raises(ValueError, match="cross-occurrence source page"):
        import_revision(bundle, bad_ref)

    # Retained tract with all calls removed produces draft error ("No calls remain")
    all_removed = revision_template(bundle, revision_id="r-empty").model_dump(mode="json")
    all_removed["tracts"][0]["call_order"] = []
    all_removed["edits"] = [
        {
            "action": "remove",
            "call_id": c.id,
            "occurrence_id": "occ-one",
            "tract_id": "parcel-one",
            "document_id": "doc-one",
            "rationale": "Removed",
        }
        for c in bundle.calls
    ]
    empty_prepared = import_revision(bundle, all_removed)
    assert empty_prepared.state == "draft"
    assert any("No calls remain" in e.message for e in empty_prepared.errors)

    # Unresolved source call (call=None) cannot accept numerical patches; baseline plot error caught
    raw_bundle = bundle.model_dump(mode="json")
    raw_bundle["calls"][0]["call"] = None
    raw_bundle["calls"][0]["reading_status"] = "uncertain"
    raw_bundle["calls"][0]["reading_note"] = "illegible"
    unresolved_bundle = DashboardBundle.model_validate(raw_bundle)
    patched = import_revision(unresolved_bundle, _edit(unresolved_bundle, distance_ft="50"))
    assert patched.state == "draft"
    assert any("Unresolved source call" in e.message for e in patched.errors)
    assert patched.last_valid_geometry == ()


def test_relative_edits_angle_guards_and_placement_comparison_invalidation():
    rel_bundle = _rel_bundle()

    # Valid relative distance + interior_angle_deg edit
    rel_data = revision_template(rel_bundle, revision_id="rel-edit").model_dump(mode="json")
    # Find a course with a unique interior constraint
    interior = next(
        c for c in rel_bundle.calculations[0].relative.constraints if c.kind == "interior"
    )
    rel_data["edits"] = [
        {
            "call_id": interior.to_course,
            "occurrence_id": rel_bundle.occurrences[0].id,
            "tract_id": rel_bundle.parcels[0].id,
            "document_id": rel_bundle.documents[0].id,
            "raw_fields": {"distance_ft": "105", "interior_angle_deg": "90"},
            "rationale": "Adjust relative course.",
        }
    ]
    prepared = import_revision(rel_bundle, rel_data)
    assert prepared.state == "parsed", prepared.errors
    assert prepared.current_geometry

    # Bearing edit on relative tract -> draft error
    bad_bearing = revision_template(rel_bundle, revision_id="rel-b").model_dump(mode="json")
    bad_bearing["edits"] = [
        {
            "call_id": interior.to_course,
            "occurrence_id": rel_bundle.occurrences[0].id,
            "tract_id": rel_bundle.parcels[0].id,
            "document_id": rel_bundle.documents[0].id,
            "raw_fields": {"bearing_azimuth_deg_from_north": "45"},
            "rationale": "Try bearing.",
        }
    ]
    res_b = import_revision(rel_bundle, bad_bearing)
    assert res_b.state == "draft"
    assert any("relative angular constraint" in e.message for e in res_b.errors)

    # Reorder on relative tract -> draft error
    reordered = revision_template(rel_bundle, revision_id="rel-r").model_dump(mode="json")
    reordered["tracts"][0]["call_order"] = list(reversed(reordered["tracts"][0]["call_order"]))
    res_r = import_revision(rel_bundle, reordered)
    assert res_r.state == "draft"
    assert any("remove/reorder" in e.message for e in res_r.errors)

    # Interior angle edit on course without an interior constraint -> draft error
    rel_raw = rel_bundle.model_dump(mode="json")
    rel_raw["calculations"][0]["relative"]["constraints"] = [
        c
        for c in rel_raw["calculations"][0]["relative"]["constraints"]
        if c["to_course"] != "call-one"
    ]
    open_rel_bundle = DashboardBundle.model_validate(rel_raw)
    no_int = revision_template(open_rel_bundle, revision_id="rel-ni").model_dump(mode="json")
    no_int["edits"] = [
        {
            "call_id": "call-one",
            "occurrence_id": open_rel_bundle.occurrences[0].id,
            "tract_id": open_rel_bundle.parcels[0].id,
            "document_id": open_rel_bundle.documents[0].id,
            "raw_fields": {"interior_angle_deg": "90"},
            "rationale": "No interior constraint on first course.",
        }
    ]
    res_ni = import_revision(open_rel_bundle, no_int)
    assert res_ni.state == "draft"
    assert any("explicit interior constraint" in e.message for e in res_ni.errors)

    # Interior angle edit on non-relative (absolute) tract -> draft error
    abs_bundle = _abs_bundle()
    abs_ang = import_revision(abs_bundle, _edit(abs_bundle, interior_angle_deg="90"))
    assert abs_ang.state == "draft"
    assert any("explicit relative interior constraint" in e.message for e in abs_ang.errors)

    # Placement-dependent description comparison is marked unavailable on revision
    comp_raw = json.loads((FIXTURES / "dashboard-comparison.json").read_text())
    comp_raw["schema_version"] = "1.1"
    comp_raw["scenes"] = [
        {"id": "s1", "name": "S", "kind": "local", "units": "unknown_ft", "basis": "local"}
    ]
    comp_raw["description_comparison_specs"][0]["scene_id"] = "s1"
    comp_bundle = DashboardBundle.model_validate(comp_raw)
    comp_rev = import_revision(comp_bundle, revision_template(comp_bundle, revision_id="comp-r"))
    assert comp_rev.comparisons[0].unavailable_reason is not None
    assert "placement-dependent" in comp_rev.comparisons[0].unavailable_reason


def test_corridor_inventory_edges_and_last_valid_parent_mismatch():
    bundle = _abs_bundle()
    cor_data = json.loads((PLUGIN / "skills/plot-corridor/references/example.json").read_text())
    cor_data["error_budget"]["max_error"] = 0.1
    corridor_raw = json.dumps(cor_data)
    corridor_obj = json.loads(corridor_raw)
    cid = corridor_obj["id"]

    # 1. Corridor request ID != stable revision corridor ID rejected
    bad_id = revision_template(bundle, revision_id="c1").model_dump(mode="json")
    bad_id["schema_version"] = "1.2"
    bad_id["corridors"] = [{"id": "other-id", "action": "retain", "raw_request_json": corridor_raw}]
    with pytest.raises(ValueError, match="stable revision ID"):
        import_revision(bundle, bad_id)

    # 2. Root revision cannot remove a corridor
    root_rm = revision_template(bundle, revision_id="c2").model_dump(mode="json")
    root_rm["schema_version"] = "1.2"
    root_rm["corridors"] = [{"id": cid, "action": "remove", "raw_request_json": corridor_raw}]
    with pytest.raises(ValueError, match="parent corridor definition"):
        import_revision(bundle, root_rm)

    # 3. Parent with NO corridors: child still cannot remove a corridor
    parent_empty = import_revision(bundle, revision_template(bundle, revision_id="p-empty"))
    child_rm = revision_template(bundle, revision_id="c3").model_dump(mode="json")
    child_rm.update(schema_version="1.2", generation=1, parent_revision_id="p-empty")
    child_rm["corridors"] = [{"id": cid, "action": "remove", "raw_request_json": corridor_raw}]
    with pytest.raises(ValueError, match="parent corridor definition"):
        import_revision(bundle, child_rm, last_valid=parent_empty)

    # 4. Mismatched parent_revision_id vs last_valid fails closed
    wrong_parent = revision_template(bundle, revision_id="c-wrong").model_dump(mode="json")
    wrong_parent["parent_revision_id"] = "someone-else"
    with pytest.raises(ValueError, match="explicit parent revision"):
        import_revision(bundle, wrong_parent, last_valid=parent_empty)

    # 5. Parent WITH corridor:
    parent_c = revision_template(bundle, revision_id="p-cor").model_dump(mode="json")
    parent_c["schema_version"] = "1.2"
    parent_c["corridors"] = [{"id": cid, "action": "retain", "raw_request_json": corridor_raw}]
    parent_prep = import_revision(bundle, parent_c)

    # Child downgrading to schema 1.1 rejected
    child_11 = revision_template(bundle, revision_id="c-11").model_dump(mode="json")
    child_11.update(schema_version="1.1", generation=1, parent_revision_id="p-cor")
    with pytest.raises(ValueError, match="schema 1.2"):
        import_revision(bundle, child_11, last_valid=parent_prep)

    # Child editing corridor to malformed JSON stays isolated draft
    child_draft = revision_template(bundle, revision_id="c-draft").model_dump(mode="json")
    child_draft.update(schema_version="1.2", generation=1, parent_revision_id="p-cor")
    child_draft["corridors"] = [{"id": cid, "action": "retain", "raw_request_json": "{bad-json"}]
    draft_prep = import_revision(bundle, child_draft, last_valid=parent_prep)
    assert draft_prep.corridor_results[0].state == "draft"

    # Child removing corridor, then grandchild trying to reuse removed ID rejected
    child_removed = revision_template(bundle, revision_id="c-rm").model_dump(mode="json")
    child_removed.update(schema_version="1.2", generation=1, parent_revision_id="p-cor")
    child_removed["corridors"] = [{"id": cid, "action": "remove", "raw_request_json": corridor_raw}]
    removed_prep = import_revision(bundle, child_removed, last_valid=parent_prep)

    grandchild_reuse = revision_template(bundle, revision_id="c-reuse").model_dump(mode="json")
    grandchild_reuse.update(schema_version="1.2", generation=2, parent_revision_id="c-rm")
    grandchild_reuse["corridors"] = [
        {"id": cid, "action": "retain", "raw_request_json": corridor_raw}
    ]
    with pytest.raises(ValueError, match="Removed corridor identity cannot be reused"):
        import_revision(bundle, grandchild_reuse, last_valid=removed_prep)


def test_write_once_symlinks_source_correction_remove_and_load_tamper_checks(tmp_path, monkeypatch):
    bundle = _abs_bundle()

    # publish_revision refuses symlinked artifact target inside revision directory
    sym_store = tmp_path / "sym-file-store"
    sym_rev_dir = sym_store / "sym-file"
    sym_rev_dir.mkdir(parents=True)
    real_file = tmp_path / "real.json"
    real_file.write_bytes(b"{}")
    (sym_rev_dir / "pending.json").symlink_to(real_file)
    res_sym_file = publish_revision(
        bundle, revision_template(bundle, revision_id="sym-file"), sym_store
    )
    assert res_sym_file["save_state"] == "failed"
    assert any("Symlink" in e for e in res_sym_file["errors"])

    # publish_revision cleans up temp file if fsync fails during atomic write
    fsync_store = tmp_path / "fsync-store"
    monkeypatch.setattr(os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("fsync failed")))
    res_fsync = publish_revision(
        bundle, revision_template(bundle, revision_id="fsync-rev"), fsync_store
    )
    assert res_fsync["save_state"] == "failed"
    assert any("fsync failed" in e for e in res_fsync["errors"])
    assert list((fsync_store / "fsync-rev").iterdir()) == []
    monkeypatch.undo()

    # publish_revision detects os.link FileExistsError race with conflicting bytes
    race_store = tmp_path / "race-store"
    real_link = os.link

    def racing_link(src, dst):
        Path(dst).write_bytes(b"winner")
        raise FileExistsError

    monkeypatch.setattr(os, "link", racing_link)
    res_race = publish_revision(
        bundle, revision_template(bundle, revision_id="race-rev"), race_store
    )
    assert res_race["save_state"] == "failed"
    assert any("artifact conflict" in e for e in res_race["errors"])
    monkeypatch.setattr(os, "link", real_link)

    # Source correction with a removed call (`if call.removed: continue`)
    sc = revision_template(bundle, revision_id="sc-rm").model_dump(mode="json")
    sc["kind"] = "source_correction"
    sc["tracts"][0]["call_order"].remove("call-four")
    sc["edits"] = [
        {
            "action": "remove",
            "call_id": "call-four",
            "occurrence_id": "occ-one",
            "tract_id": "parcel-one",
            "document_id": "doc-one",
            "source_refs": [{"page_id": "page-one", "quote": "omit call four"}],
            "rationale": "Duplicate transcription removed.",
        }
    ]
    store = tmp_path / "store"
    pub = publish_revision(bundle, sc, store)
    assert pub["save_state"] == "published", pub
    src_calls = json.loads((store / "sc-rm/source-calls.json").read_text())
    assert len(src_calls["revised_calls"]) == 3

    # publish_revision refuses symlink root and symlink revision dir
    link_root = tmp_path / "link-root"
    link_root.symlink_to(store, target_is_directory=True)
    assert (
        publish_revision(bundle, revision_template(bundle, revision_id="x1"), link_root)[
            "save_state"
        ]
        == "failed"
    )

    (store / "sym-rev").symlink_to(store / "sc-rm", target_is_directory=True)
    assert (
        publish_revision(bundle, revision_template(bundle, revision_id="sym-rev"), store)[
            "save_state"
        ]
        == "failed"
    )

    # load_revision security & integrity checks
    with pytest.raises(ValueError, match="unavailable or unsafe"):
        load_revision(bundle, tmp_path / "nonexistent")
    with pytest.raises(ValueError, match="unavailable or unsafe"):
        load_revision(bundle, store / "sym-rev")

    # Publish clean revision to mutate for load_revision tamper checks
    clean_store = tmp_path / "clean"
    rev = revision_template(bundle, revision_id="clean-1")
    assert publish_revision(bundle, rev, clean_store)["save_state"] == "published"
    rdir = clean_store / "clean-1"

    def _copy_rev(name: str) -> Path:
        dst = tmp_path / name
        shutil.copytree(rdir, dst)
        return dst

    # Symlink manifest.json
    d1 = _copy_rev("d-sym-manifest")
    ext_m = tmp_path / "ext-m.json"
    ext_m.write_bytes((d1 / "manifest.json").read_bytes())
    (d1 / "manifest.json").unlink()
    (d1 / "manifest.json").symlink_to(ext_m)
    with pytest.raises(ValueError, match="Unsafe revision manifest"):
        load_revision(bundle, d1)

    # Unsafe artifact name in manifest
    d2 = _copy_rev("d-bad-name")
    m = json.loads((d2 / "manifest.json").read_text())
    m["artifacts"]["../evil.json"] = "0" * 64
    (d2 / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(ValueError, match="Unsafe revision artifact name"):
        load_revision(bundle, d2)

    # Missing artifact listed in manifest
    d3 = _copy_rev("d-missing-art")
    (d3 / "pending.json").unlink()
    with pytest.raises(ValueError, match="incomplete or unsafe artifact"):
        load_revision(bundle, d3)

    # Manifest revision_id / hash mismatch (while revision.json hash matches)
    d4 = _copy_rev("d-id-mismatch")
    m = json.loads((d4 / "manifest.json").read_text())
    m["revision_hash"] = "0" * 64
    (d4 / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(ValueError, match="identity/hash mismatch"):
        load_revision(bundle, d4)

    # Parent cycle guard via on-disk two-revision cycle (rev-a <-> rev-b)
    from mp_verify.dashboard import _hash

    cycle_store = tmp_path / "cycle-store"
    cycle_store.mkdir()
    for rev_id, parent_id in (("rev-a", "rev-b"), ("rev-b", "rev-a")):
        cdir = cycle_store / rev_id
        shutil.copytree(rdir, cdir)
        rev_obj = json.loads((cdir / "revision.json").read_text())
        rev_obj["id"] = rev_id
        rev_obj["parent_revision_id"] = parent_id
        rev_obj["generation"] = 1
        rev_bytes = json.dumps(rev_obj, indent=2, sort_keys=True).encode() + b"\n"
        (cdir / "revision.json").write_bytes(rev_bytes)
        cm = json.loads((cdir / "manifest.json").read_text())
        cm["revision_id"] = rev_id
        cm["generation"] = 1
        cm["revision_hash"] = _hash(rev_obj)
        cm["artifacts"]["revision.json"] = hashlib.sha256(rev_bytes).hexdigest()
        (cdir / "manifest.json").write_text(json.dumps(cm))
    with pytest.raises(ValueError, match="cycle"):
        load_revision(bundle, cycle_store / "rev-a")

    # Extra artifact in manifest inventory mismatch (valid file + valid hash)
    d5 = _copy_rev("d-inv-mismatch")
    extra_bytes = b"{}"
    (d5 / "extra.json").write_bytes(extra_bytes)
    m = json.loads((d5 / "manifest.json").read_text())
    m["artifacts"]["extra.json"] = hashlib.sha256(extra_bytes).hexdigest()
    (d5 / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(ValueError, match="inventory mismatch"):
        load_revision(bundle, d5)

    # Artifact bytes differ from fresh deterministic replay (hash updated in manifest!)
    d6 = _copy_rev("d-replay-diff")
    tampered_pending = b'{"tampered": true}'
    (d6 / "pending.json").write_bytes(tampered_pending)
    m = json.loads((d6 / "manifest.json").read_text())
    m["artifacts"]["pending.json"] = hashlib.sha256(tampered_pending).hexdigest()
    (d6 / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(ValueError, match="deterministic replay"):
        load_revision(bundle, d6)
