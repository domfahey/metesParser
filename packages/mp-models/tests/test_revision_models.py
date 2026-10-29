"""Revision envelopes retain exact input while rejecting malformed structure."""

import pytest
from mp_models.revisions import DashboardRevision, RevisionCallDraft, RevisionSourceRef


def test_revision_draft_retains_whitespace_and_rejects_nonstrings():
    draft = RevisionCallDraft(
        call_id="c",
        occurrence_id="o",
        tract_id="t",
        document_id="d",
        raw_fields={"notes": "  text\n", "distance_ft": "1."},
        rationale=" \n",
    )
    assert draft.raw_fields["notes"] == "  text\n"
    assert draft.rationale == " \n"
    with pytest.raises(ValueError):
        RevisionCallDraft(
            call_id="c", occurrence_id="o", tract_id="t", document_id="d", raw_fields={"notes": 3}
        )
    with pytest.raises(ValueError):
        RevisionSourceRef(page_id="p", quote="  ")


def test_revision_structure_rejects_unknown_schema_duplicate_and_self_parent():
    data = {
        "id": "r",
        "baseline": {"id": "baseline", "bundle_sha256": "0" * 64},
        "label": "test",
        "tracts": [
            {
                "id": "t",
                "occurrence_id": "o",
                "document_ids": ["d"],
                "label": "same",
                "call_order": ["c"],
            }
        ],
    }
    assert DashboardRevision.model_validate(data).schema_version == "1.0"
    for update in (
        {"schema_version": "2.0"},
        {"generation": True},
        {"parent_revision_id": "r"},
        {"tracts": data["tracts"] * 2},
    ):
        with pytest.raises(ValueError):
            DashboardRevision.model_validate(data | update)
