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
    for changes in ({"calls": ()}, {"calls": (record(), record())}, {"foot_definition": "m"}):
        data = {"title": "supplied", "calls": (record(),)} | changes
        with pytest.raises(ValidationError):
            PlotRequest.model_validate(data)
