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


@pytest.mark.parametrize(
    ("value", "expected_match"),
    [
        (float("nan"), "finite number"),
        (float("inf"), "finite number"),
        (-1, "greater than 0"),
        (0, "greater than 0"),
        (True, "must be a number, not a boolean"),
        ("100", "valid number"),
    ],
)
def test_distance_must_be_positive_finite_numeric(value, expected_match):
    with pytest.raises(ValidationError, match=expected_match):
        RelativeCourse(course_id="a", distance_ft=value, source=SOURCE)


@pytest.mark.parametrize("field", ["reference", "quote"])
def test_blank_source_is_rejected_but_verbatim_whitespace_is_preserved(field):
    with pytest.raises(ValidationError, match="source reference and quote must not be blank"):
        RelativeSource(**{**SOURCE, field: " \n "})
    assert (
        RelativeSource(**{**SOURCE, field: "  original\n "}).model_dump()[field] == "  original\n "
    )


@pytest.mark.parametrize(
    ("value", "expected_match"),
    [
        (float("nan"), "finite number"),
        (float("inf"), "finite number"),
        (True, "must be a number, not a boolean"),
        ("90", "valid number"),
    ],
)
def test_local_frame_rejects_nonfinite_or_nonnumeric_heading(value, expected_match):
    data = valid_description()["frame"]
    data["first_azimuth_deg"] = value
    with pytest.raises(ValidationError, match=expected_match):
        LocalFrame.model_validate(data)


@pytest.mark.parametrize("field", ["name", "first_azimuth_deg", "origin", "orientation"])
def test_local_frame_is_explicit(field):
    data = valid_description()["frame"]
    del data[field]
    with pytest.raises(ValidationError, match=rf"{field}[\s\S]*Field required"):
        LocalFrame.model_validate(data)


@pytest.mark.parametrize(
    ("value", "expected_match"),
    [
        (0, "greater than 0"),
        (360, "less than 360"),
        (-90, "greater than 0"),
        (float("nan"), "finite number"),
        (float("inf"), "finite number"),
        (True, "must be a number, not a boolean"),
        ("90", "valid number"),
    ],
)
def test_interior_angle_validation(value, expected_match):
    data = valid_description()["constraints"][0]
    data["angle_deg"] = value
    with pytest.raises(ValidationError, match=expected_match):
        RelativeConstraint.model_validate(data)


def test_constraints_reject_inapplicable_fields():
    data = valid_description()["constraints"][0]
    data["parallel_direction"] = "same"
    with pytest.raises(
        ValidationError, match="angle constraints cannot include turn or parallel_direction"
    ):
        RelativeConstraint.model_validate(data)


@pytest.mark.parametrize(
    ("mutation", "expected_match"),
    [
        ("duplicate_course", "course_id values must be unique"),
        ("duplicate_constraint", "constraint_id values must be unique"),
        ("dangling", "unknown course"),
        ("same_course", "connect distinct courses"),
        ("nonadjacent_angle", "connect successive boundary courses"),
    ],
)
def test_description_rejects_invalid_references(mutation, expected_match):
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
    with pytest.raises(ValidationError, match=expected_match):
        RelativeDescription.model_validate(data)


@pytest.mark.parametrize("field", ["engine_verified", "verified_export_eligible"])
def test_relative_result_cannot_claim_engine_verification(field):
    with pytest.raises(ValidationError, match="Input should be False"):
        RelativeAnalysisResult(
            description=valid_description(), status="unresolved", **{field: True}
        )


def test_relative_blank_identifiers_and_constraint_kind_mismatch_guards():
    with pytest.raises(ValidationError, match="must be named"):
        LocalFrame(name="   ", first_azimuth_deg=0, origin=(0, 0), orientation="cw")
    with pytest.raises(ValidationError, match="course_id must not be blank"):
        RelativeCourse(course_id="   ", distance_ft=10, source=SOURCE)
    with pytest.raises(ValidationError, match="must not be blank"):
        RelativeConstraint(
            constraint_id="  ",
            kind="parallel",
            from_course="0",
            to_course="1",
            source=SOURCE,
        )
    # Interior/exterior without angle_deg; interior with exterior_convention.
    with pytest.raises(ValidationError, match="require angle_deg"):
        RelativeConstraint(
            constraint_id="k1", kind="interior", from_course="0", to_course="1", source=SOURCE
        )
    with pytest.raises(ValidationError, match="only valid for exterior"):
        RelativeConstraint(
            constraint_id="k1",
            kind="interior",
            from_course="0",
            to_course="1",
            angle_deg=90,
            exterior_convention="interior_complement",
            source=SOURCE,
        )
    # Parallel/perpendicular disallow angle_deg, turn (for parallel), and parallel_direction (for perpendicular).
    with pytest.raises(ValidationError, match="accept angle fields"):
        RelativeConstraint(
            constraint_id="k1",
            kind="parallel",
            from_course="0",
            to_course="1",
            angle_deg=90,
            source=SOURCE,
        )
    with pytest.raises(ValidationError, match="not turn"):
        RelativeConstraint(
            constraint_id="k1",
            kind="parallel",
            from_course="0",
            to_course="1",
            turn="left",
            source=SOURCE,
        )
    with pytest.raises(ValidationError, match="not parallel_direction"):
        RelativeConstraint(
            constraint_id="k1",
            kind="perpendicular",
            from_course="0",
            to_course="1",
            parallel_direction="same",
            source=SOURCE,
        )
