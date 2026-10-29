"""Web-map validation must check feature-set completeness and coordinate consistency (#67)."""

import importlib.util
from pathlib import Path

import pytest
from mp_models.webmap import WebMapOptions, WebMapPoint
from mp_review.webmap import prepare_web_map
from mp_verify.webmap import validate_web_map_artifact

_spec = importlib.util.spec_from_file_location(
    "_webmap_fixtures", Path(__file__).with_name("test_webmap.py")
)
_fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixtures)
mapped = _fixtures.mapped


def _open_end(data):
    data["calls"][3]["call"]["distance_ft"] = 49


def _partial(data):
    data["calls"][1]["call"]["bearing_azimuth_deg_from_north"] = None


def _build(edit=None):
    prepared = mapped(edit=edit)
    artifact = prepare_web_map(prepared, scene_id="grid", options=WebMapOptions()).artifact
    return prepared, artifact


def _without(artifact, predicate):
    kept = tuple(f for f in artifact.features if not predicate(f))
    assert len(kept) < len(artifact.features)
    return artifact.model_copy(update={"features": kept})


def _replace_first(artifact, kind, update):
    features = []
    done = False
    for feature in artifact.features:
        if not done and feature.properties.kind == kind:
            feature = feature.model_copy(update={"geometry": update(feature.geometry)})
            done = True
        features.append(feature)
    assert done
    return artifact.model_copy(update={"features": tuple(features)})


def _shift_last(geometry):
    coords = list(geometry.coordinates)
    coords[-1] = (coords[-1][0] + 0.001, coords[-1][1])
    return type(geometry)(coordinates=tuple(coords))


def _shift_first(geometry):
    coords = list(geometry.coordinates)
    coords[0] = (coords[0][0] + 0.001, coords[0][1])
    return type(geometry)(coordinates=tuple(coords))


def test_untampered_artifacts_validate():
    for edit in (None, _open_end, _partial):
        prepared, artifact = _build(edit)
        assert validate_web_map_artifact(prepared, artifact) == artifact


def test_removed_closure_gap_is_rejected():
    prepared, artifact = _build(_open_end)
    forged = _without(artifact, lambda f: f.properties.kind == "closure_gap")
    assert forged.availability == "ready"
    with pytest.raises(ValueError, match="incomplete"):
        validate_web_map_artifact(prepared, forged)


def test_removed_course_is_rejected():
    prepared, artifact = _build()
    forged = _without(artifact, lambda f: f.properties.call_id == "call-two")
    with pytest.raises(ValueError, match="incomplete"):
        validate_web_map_artifact(prepared, forged)


def test_removed_pob_is_rejected():
    prepared, artifact = _build()
    forged = _without(artifact, lambda f: f.properties.kind == "pob")
    with pytest.raises(ValueError, match="incomplete"):
        validate_web_map_artifact(prepared, forged)


def test_duplicate_course_is_rejected():
    prepared, artifact = _build()
    course = next(f for f in artifact.features if f.properties.kind == "recorded_course")
    dup = course.model_copy(update={"id": "course:duplicate"})
    forged = artifact.model_copy(update={"features": (*artifact.features, dup)})
    with pytest.raises(ValueError, match="incomplete"):
        validate_web_map_artifact(prepared, forged)


def test_silently_dropped_calculation_requires_unavailable_record():
    prepared, artifact = _build()
    forged = artifact.model_copy(
        update={"features": (), "availability": "unavailable", "bounds": None}
    )
    with pytest.raises(ValueError, match="incomplete"):
        validate_web_map_artifact(prepared, forged)


def test_partial_geometry_requires_its_unavailable_claim():
    prepared, artifact = _build(_partial)
    assert artifact.availability == "partial"
    forged = artifact.model_copy(update={"unavailable": (), "availability": "ready"})
    with pytest.raises(ValueError, match="incomplete"):
        validate_web_map_artifact(prepared, forged)


def test_moved_pob_is_rejected():
    prepared, artifact = _build()
    forged = _replace_first(
        artifact,
        "pob",
        lambda g: WebMapPoint(coordinates=(g.coordinates[0] + 0.001, g.coordinates[1])),
    )
    with pytest.raises(ValueError, match="coordinate"):
        validate_web_map_artifact(prepared, forged)


def test_moved_course_vertex_breaks_chain():
    prepared, artifact = _build()
    forged = _replace_first(artifact, "recorded_course", _shift_last)
    with pytest.raises(ValueError, match="coordinate"):
        validate_web_map_artifact(prepared, forged)


def test_moved_gap_endpoint_is_rejected():
    prepared, artifact = _build(_open_end)
    forged = _replace_first(artifact, "closure_gap", _shift_first)
    with pytest.raises(ValueError, match="coordinate"):
        validate_web_map_artifact(prepared, forged)
