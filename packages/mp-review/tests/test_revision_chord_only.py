"""Revisions on deeds containing chord-only curves (radius + chord, no delta/arc)."""

import json
from pathlib import Path

import pytest
from mp_models.dashboard import DashboardBundle
from mp_models.revisions import revision_template
from mp_review.revisions import import_revision, load_revision, publish_revision

CHORD_ONLY = {
    "course": 2,
    "direction_text": "curve to the right",
    "distance_ft": 50,
    "bearing_azimuth_deg_from_north": None,
    "curve_dir": "right",
    "radius_ft": 100,
    "chord_bearing": "N 90°00' E",
    "chord_length_ft": 50,
    "is_indefinite": True,
    "notes": "curve delta/arc not stated - positioned by chord only",
}


@pytest.fixture
def bundle():
    data = json.loads((Path(__file__).parent / "fixtures/dashboard-absolute.json").read_text())
    data["calls"][1]["call"] = CHORD_ONLY
    return DashboardBundle.model_validate(data)


def _revision(bundle, call_id, **edit):
    data = revision_template(bundle, revision_id="alternative").model_dump(mode="json")
    if "structured_input" in edit:
        data["schema_version"] = "1.1"
    data["edits"] = [
        {
            "call_id": call_id,
            "occurrence_id": "occ-one",
            "tract_id": "parcel-one",
            "document_id": "doc-one",
            "rationale": "Check page 1.",
            **edit,
        }
    ]
    return data


def _chord_only_prepared(prepared):
    item = next(c for c in prepared.prepared_calls if c.id == "call-two")
    assert item.call is not None and item.call.is_chord_only_curve()
    return item.call


def test_unrelated_edit_on_deed_with_chord_only_call_publishes(bundle, tmp_path):
    data = _revision(bundle, "call-one", raw_fields={"notes": "annotation"})
    prepared = import_revision(bundle, data)
    assert prepared.errors == ()
    assert prepared.state == "parsed"
    assert not prepared.exportable
    call = _chord_only_prepared(prepared)
    assert call.chord_length_ft == 50 and call.delta_deg is None and call.arc_length_ft is None
    plot = prepared.current_geometry[0].plot.geometry
    assert [u.call_id for u in plot.unresolved] == ["call-two"]
    assert "positioned by chord only" in plot.unresolved[0].reason
    result = publish_revision(bundle, data, tmp_path)
    assert result["save_state"] == "published"
    assert load_revision(bundle, tmp_path / "alternative") == prepared


def test_structured_seed_of_chord_only_call_is_accepted_unchanged(bundle):
    # The browser editor seeds this structured input from the parser-produced call.
    seeded = {
        "geometry_type": "circular_arc",
        "role": "boundary",
        "orientation": "supplied",
        "bearing_format": "decimal_azimuth",
        "distance_unit": "feet",
        "distance_value": "50",
        "radius_value": "100",
        "chord_length_value": "50",
        "chord_bearing_value": "N 90°00' E",
        "chord_bearing_format": "quadrant_dms",
        "curve_dir": "right",
        "delta_format": "decimal_degrees",
        "is_indefinite": "true",
    }
    prepared = import_revision(bundle, _revision(bundle, "call-two", structured_input=seeded))
    assert prepared.errors == ()
    assert prepared.state == "parsed"
    call = _chord_only_prepared(prepared)
    assert call.radius_ft == pytest.approx(100.0)
    assert call.chord_length_ft == pytest.approx(50.0)
    assert call.distance_ft == pytest.approx(50.0)
    assert call.delta_deg is None and call.arc_length_ft is None
