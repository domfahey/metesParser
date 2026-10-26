"""Validation boundaries for explicitly sourced local-angle inputs."""

import pytest
from mp_models import (
    LocalFrame,
    RelativeAnalysisResult,
    RelativeConstraint,
    RelativeCourse,
    RelativeDescription,
    RelativeSource,
)
from pydantic import ValidationError

SOURCE = {"reference": "book:1/page:2", "quote": "as written"}


def valid_description():
    return {
        "frame": {"name": "local", "first_azimuth_deg": 0, "origin": [0, 0], "orientation": "cw"},
        "courses": [{"course_id": str(i), "distance_ft": 100, "source": SOURCE} for i in range(3)],
        "constraints": [
            {
                "constraint_id": "a",
                "kind": "interior",
                "from_course": "0",
                "to_course": "1",
                "angle_deg": 60,
                "source": SOURCE,
            }
        ],
    }


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 0, True, "100"])
def test_distance_must_be_positive_finite_numeric(value):
    with pytest.raises(ValidationError):
        RelativeCourse(course_id="a", distance_ft=value, source=SOURCE)


@pytest.mark.parametrize("field", ["reference", "quote"])
def test_blank_source_is_rejected_but_verbatim_whitespace_is_preserved(field):
    with pytest.raises(ValidationError):
        RelativeSource(**{**SOURCE, field: " \n "})
    assert (
        RelativeSource(**{**SOURCE, field: "  original\n "}).model_dump()[field] == "  original\n "
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "90"])
def test_local_frame_rejects_nonfinite_or_nonnumeric_heading(value):
    data = valid_description()["frame"]
    data["first_azimuth_deg"] = value
    with pytest.raises(ValidationError):
        LocalFrame.model_validate(data)


@pytest.mark.parametrize("field", ["name", "first_azimuth_deg", "origin", "orientation"])
def test_local_frame_is_explicit(field):
    data = valid_description()["frame"]
    del data[field]
    with pytest.raises(ValidationError):
        LocalFrame.model_validate(data)


@pytest.mark.parametrize("value", [0, 360, -90, float("nan"), float("inf"), True, "90"])
def test_interior_angle_validation(value):
    data = valid_description()["constraints"][0]
    data["angle_deg"] = value
    with pytest.raises(ValidationError):
        RelativeConstraint.model_validate(data)


def test_constraints_reject_inapplicable_fields():
    data = valid_description()["constraints"][0]
    data["parallel_direction"] = "same"
    with pytest.raises(ValidationError):
        RelativeConstraint.model_validate(data)


@pytest.mark.parametrize(
    "mutation",
    ["duplicate_course", "duplicate_constraint", "dangling", "same_course", "nonadjacent_angle"],
)
def test_description_rejects_invalid_references(mutation):
    data = valid_description()
    if mutation == "duplicate_course":
        data["courses"][1]["course_id"] = "0"
    elif mutation == "duplicate_constraint":
        data["constraints"].append(data["constraints"][0].copy())
    elif mutation == "dangling":
        data["constraints"][0]["to_course"] = "missing"
    elif mutation == "same_course":
        data["constraints"][0]["to_course"] = "0"
    elif mutation == "nonadjacent_angle":
        data["constraints"][0]["to_course"] = "2"
    with pytest.raises(ValidationError):
        RelativeDescription.model_validate(data)


@pytest.mark.parametrize("field", ["engine_verified", "verified_export_eligible"])
def test_relative_result_cannot_claim_engine_verification(field):
    with pytest.raises(ValidationError):
        RelativeAnalysisResult(
            description=valid_description(), status="unresolved", **{field: True}
        )
