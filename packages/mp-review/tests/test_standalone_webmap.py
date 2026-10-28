"""Standalone geographic display retains supplied evidence without a dashboard."""

import math

import pytest
from mp_models import DeedCall
from mp_models.plot import MapSource, PlotPlacement, PlotScene, VectorLayer
from mp_models.plot_request import PlotCall, PlotRequest
from mp_models.webmap import StandaloneWebMapInput, WebMapOptions
from mp_review.webmap import prepare_web_map
from mp_verify.plot import prepare_plot
from mp_verify.webmap import normalize_web_map_context, validate_web_map_artifact
from pydantic import ValidationError


def standalone(*, foot="international_ft", placed=True, references=False):
    plot = prepare_plot(
        PlotRequest(
            title="Supplied description",
            calculation_id="survey",
            foot_definition=foot,
            calls=(
                PlotCall(
                    id="course-a",
                    call=DeedCall(
                        course=1,
                        direction_text="East 100 feet",
                        bearing_azimuth_deg_from_north=90,
                        distance_ft=100,
                    ),
                    occurrence_id="actual-occurrence" if references else None,
                    page_id="actual-page" if references else None,
                    source_reference="Recorded Book 10 page 12" if references else None,
                ),
            ),
        )
    )
    placement = PlotPlacement(
        id="anchor",
        calculation_id="survey",
        geometry_hash=plot.geometry.geometry_hash,
        scene_id="grid",
        translation=(1000, 2000),
        rationale="User supplied control",
        position_evidence=("User supplied position",),
        orientation_evidence=("Approximate rotation supplied",),
    )
    return StandaloneWebMapInput(
        title="Standalone",
        plots=(plot,),
        scenes=(PlotScene(id="grid", name="Grid", kind="projected", crs="EPSG:3857", units="m"),),
        placements=(placement,) if placed else (),
    )


def render(value):
    return prepare_web_map(value, scene_id="grid", options=WebMapOptions()).artifact


def test_standalone_without_dashboard_has_independent_coordinates_and_real_refs():
    value = standalone(references=True)
    assert value.plots[0].geometry.occurrence_id is None
    result = render(value)
    course = next(f for f in result.features if f.properties.kind == "recorded_course")
    assert course.geometry.coordinates[-1][0] == pytest.approx(math.degrees(1030.48 / 6378137))
    assert course.properties.call_id == "course-a"
    assert course.properties.page_id == "actual-page"
    assert course.properties.occurrence_id == "actual-occurrence"
    assert value.plots[0].request.calls[0].source_reference == "Recorded Book 10 page 12"
    assert validate_web_map_artifact(value, result) == result
    assert normalize_web_map_context(value).title == "Standalone"


@pytest.mark.parametrize(
    "field", ["scenario_id", "baseline_geometry_hash", "baseline_placement_id", "evidence_ids"]
)
def test_standalone_rejects_dashboard_evidence_fields(field):
    value = standalone()
    data = value.model_dump(mode="json")
    data["placements"][0][field] = {
        "scenario_id": "s",
        "baseline_geometry_hash": "a" * 64,
        "baseline_placement_id": "b",
        "evidence_ids": ["invented"],
    }[field]
    with pytest.raises(ValidationError):
        StandaloneWebMapInput.model_validate(data)


def test_standalone_refuses_referenced_without_orientation_frame():
    data = standalone().model_dump(mode="json")
    data["placements"][0]["status"] = "referenced"
    with pytest.raises(ValidationError, match="referenced"):
        StandaloneWebMapInput.model_validate(data)


@pytest.mark.parametrize("field", ["plots", "placements"])
def test_standalone_rejects_stale_geometry_and_placement(field):
    value = standalone()
    if field == "plots":
        plot = value.plots[0]
        forged = plot.model_copy(
            update={"geometry": plot.geometry.model_copy(update={"area_sq_ft": 999.0})}
        )
        value = value.model_copy(update={"plots": (forged,)})
    else:
        value = value.model_copy(
            update={
                "placements": (value.placements[0].model_copy(update={"geometry_hash": "a" * 64}),)
            }
        )
    with pytest.raises(ValueError, match="freshly|stale"):
        render(value)


@pytest.mark.parametrize(
    "foot,placed,code",
    [("unknown_ft", True, "unknown_units"), ("international_ft", False, "missing_placement")],
)
def test_standalone_missing_units_or_placement_omits_geography(foot, placed, code):
    value = standalone(foot=foot, placed=placed)
    artifact = render(value)
    assert artifact.availability == "unavailable"
    assert not artifact.features
    assert artifact.unavailable[0].code == code
    assert validate_web_map_artifact(value, artifact) == artifact


def test_standalone_overlay_only_retains_real_source_and_can_render():
    source = MapSource(
        id="county", label="County", sha256="a" * 64, url="https://example.com/parcels"
    )
    layer = VectorLayer(
        id="parcel",
        label="Parcel",
        source_id=source.id,
        scene_id="grid",
        geometry_type="Polygon",
        coordinates=(((1000, 2000), (1100, 2000), (1100, 2100), (1000, 2000)),),
    )
    value = StandaloneWebMapInput(
        title="Overlay", scenes=standalone().scenes, map_sources=(source,), vector_layers=(layer,)
    )
    artifact = render(value)
    assert artifact.availability == "ready"
    assert artifact.features[0].properties.source_id == "county"
    assert validate_web_map_artifact(value, artifact) == artifact


@pytest.mark.parametrize("mutation", ["title", "source", "placement", "call"])
def test_standalone_hashes_reject_changed_inputs(mutation):
    value = standalone()
    artifact = render(value)
    data = value.model_dump(mode="json")
    if mutation == "title":
        data["title"] = "Renamed"
    elif mutation == "source":
        data["map_sources"] = [{"id": "county", "label": "County", "sha256": "b" * 64}]
    elif mutation == "placement":
        data["placements"][0]["translation"] = [1001, 2000]
    else:
        data["plots"][0]["request"]["calls"][0]["source_reference"] = "new reference"
        plot = prepare_plot(PlotRequest.model_validate(data["plots"][0]["request"]))
        data["plots"] = [plot.model_dump(mode="json")]
        data["placements"][0]["geometry_hash"] = plot.geometry.geometry_hash
    changed = StandaloneWebMapInput.model_validate(data)
    with pytest.raises(ValueError, match="input hashes"):
        validate_web_map_artifact(changed, artifact)


def test_standalone_call_page_binding_cannot_be_forged():
    value = standalone(references=True)
    artifact = render(value)
    feature = artifact.features[0]
    changed = feature.model_copy(
        update={"properties": feature.properties.model_copy(update={"page_id": "wrong"})}
    )
    with pytest.raises(ValueError, match="call binding"):
        validate_web_map_artifact(
            value, artifact.model_copy(update={"features": (changed, *artifact.features[1:])})
        )


def test_standalone_unique_ids_include_calls_and_calculations():
    data = standalone().model_dump(mode="json")
    data["scenes"][0]["id"] = "course-a"
    data["placements"] = []
    with pytest.raises(ValidationError, match="unique"):
        StandaloneWebMapInput.model_validate(data)


def test_standalone_rejects_unknown_layer_source():
    data = standalone().model_dump(mode="json")
    data["vector_layers"] = [
        {
            "id": "context",
            "label": "Context",
            "source_id": "missing",
            "scene_id": "grid",
            "geometry_type": "Polygon",
            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
        }
    ]
    with pytest.raises(ValidationError, match="unknown"):
        StandaloneWebMapInput.model_validate(data)


def test_standalone_placement_precision_loss_is_rejected():
    value = standalone()
    placement = value.placements[0].model_copy(update={"translation": (1e18, 1e18)})
    with pytest.raises(ValueError, match="precision"):
        render(value.model_copy(update={"placements": (placement,)}))


def test_standalone_partial_calls_never_add_a_bridge_or_unknown_bearing():
    value = standalone()
    first = value.plots[0].request.calls[0]
    unknown = PlotCall(
        id="unknown", call=DeedCall(course=2, direction_text="southwesterly", distance_ft=10)
    )
    last = PlotCall(
        id="last",
        call=DeedCall(
            course=3, direction_text="North", bearing_azimuth_deg_from_north=0, distance_ft=10
        ),
    )
    plot = prepare_plot(value.plots[0].request.model_copy(update={"calls": (first, unknown, last)}))
    placement = value.placements[0].model_copy(
        update={"geometry_hash": plot.geometry.geometry_hash}
    )
    value = value.model_copy(update={"plots": (plot,), "placements": (placement,)})
    artifact = render(value)
    assert [
        f.properties.call_id for f in artifact.features if f.properties.kind == "recorded_course"
    ] == [first.id]
    assert not any(f.properties.kind == "closure_gap" for f in artifact.features)
    assert artifact.availability == "partial"
    assert validate_web_map_artifact(value, artifact) == artifact
