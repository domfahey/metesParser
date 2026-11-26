"""Standalone plotting inputs cannot attest that anybody read or verified a deed."""

import pytest
from mp_models import DeedCall, PlotCall, PlotRequest
from pydantic import ValidationError


def record():
    return PlotCall(
        id="call-one",
        call=DeedCall(
            course=1,
            direction_text="northwardly",
            distance_ft=10,
            notes="incomplete bearing - cardinal only",
        ),
        quote="  Verbatim wording\n",
        source_reference=" file.json item 1 ",
    )


def test_optional_sources_stay_unknown_and_verbatim_evidence_is_preserved():
    call = record()
    request = PlotRequest(title="Supplied calls", calls=(call,))
    assert request.foot_definition == "unknown_ft"
    assert call.page_id is None
    assert call.occurrence_id is None
    assert call.call.bearing_azimuth_deg_from_north is None
    assert call.quote == "  Verbatim wording\n"
    assert call.source_reference == " file.json item 1 "


@pytest.mark.parametrize("field", ["engine_verified", "source_review_complete", "reading_status"])
def test_input_cannot_inject_review_or_verification_flags(field):
    data = {"title": "supplied", "calls": [record().model_dump(mode="json")], field: True}
    with pytest.raises(ValidationError, match="Extra inputs"):
        PlotRequest.model_validate(data)


def test_duplicate_ids_empty_calls_and_meter_label_are_rejected():
    for changes, expected_match in (
        ({"calls": ()}, "at least 1 item"),
        ({"calls": (record(), record())}, "plot call IDs must be unique"),
        ({"foot_definition": "m"}, "foot_definition must identify feet"),
    ):
        data = {"title": "supplied", "calls": (record(),)} | changes
        with pytest.raises(ValidationError, match=expected_match):
            PlotRequest.model_validate(data)


def test_blank_title_and_mismatched_relative_courses_rejected():
    from mp_models import LocalFrame, RelativeCourse, RelativeDescription, RelativeSource

    with pytest.raises(ValidationError, match="title must not be blank"):
        PlotRequest(title="   ", calls=(record(),))

    src = RelativeSource(reference="p1", quote="q")
    rel = RelativeDescription(
        frame=LocalFrame(name="L", first_azimuth_deg=0.0, origin=(0.0, 0.0), orientation="cw"),
        courses=tuple(
            RelativeCourse(course_id=f"c{i}", distance_ft=10.0, source=src) for i in (1, 2, 3)
        ),
        constraints=(),
    )
    # Count mismatch (1 call vs 3 relative courses).
    with pytest.raises(ValidationError, match="correspond in order"):
        PlotRequest(title="t", calls=(record(),), relative=rel)

    # Matching count but call distance differs from relative course.
    three_calls = tuple(
        PlotCall(
            id=f"c{i}",
            call=DeedCall(course=i, direction_text="northwardly", distance_ft=20.0),
        )
        for i in (1, 2, 3)
    )
    with pytest.raises(ValidationError, match="differs from its supplied straight plot call"):
        PlotRequest(title="t", calls=three_calls, relative=rel)
