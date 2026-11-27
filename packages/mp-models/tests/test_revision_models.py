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
    with pytest.raises(ValueError, match="valid string"):
        RevisionCallDraft(
            call_id="c", occurrence_id="o", tract_id="t", document_id="d", raw_fields={"notes": 3}
        )
    with pytest.raises(ValueError, match="source quote must not be blank"):
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
    for update, expected_match in (
        ({"schema_version": "2.0"}, "Input should be '1.0', '1.1' or '1.2'"),
        ({"generation": True}, "valid integer"),
        ({"parent_revision_id": "r"}, "cannot be its own parent"),
        ({"tracts": data["tracts"] * 2}, "duplicate tract occurrence identity"),
    ):
        with pytest.raises(ValueError, match=expected_match):
            DashboardRevision.model_validate(data | update)


def test_revision_validation_guards_unicode_drafts_corridors_and_template():
    import json
    from pathlib import Path

    from mp_models.dashboard import DashboardBundle
    from mp_models.revisions import (
        RevisionComparison,
        RevisionCorridor,
        RevisionPreparedCall,
        bind_baseline,
        revision_template,
    )

    # Valid source ref accepted; lone surrogates rejected in scalar string and nested Any fields.
    base_draft = {"call_id": "c1", "occurrence_id": "o1", "tract_id": "t1", "document_id": "d1"}
    ref = RevisionSourceRef(page_id="p1", quote="North 100 ft")
    assert ref.quote == "North 100 ft"
    with pytest.raises(ValueError, match="unicode string"):
        RevisionSourceRef(page_id="p1", quote="\ud800")
    with pytest.raises(ValueError, match="Unicode scalar values"):
        RevisionPreparedCall(
            id="c1",
            occurrence_id="o1",
            tract_id="t1",
            document_id="d1",
            source_status="recorded",
            original_source={"k": ["\ud800"]},
        )

    # RevisionCallDraft guards: unsupported raw field, both structured+raw, add without structured, remove with raw.
    with pytest.raises(ValueError, match="unsupported revision raw field"):
        RevisionCallDraft(**base_draft, raw_fields={"unknown": "1"})
    with pytest.raises(ValueError, match="not both"):
        RevisionCallDraft(
            **base_draft, structured_input={"distance_ft": "10"}, raw_fields={"notes": "x"}
        )
    with pytest.raises(ValueError, match="complete structured input"):
        RevisionCallDraft(**base_draft, action="add")
    with pytest.raises(ValueError, match="explicit remove cannot also edit"):
        RevisionCallDraft(**base_draft, action="remove", raw_fields={"notes": "x"})

    # DashboardRevision guards: dup edit call_id, dup call in tract order, corridors require 1.2, dup corridor id.
    tract = {
        "id": "t",
        "occurrence_id": "o",
        "document_ids": ["d"],
        "label": "same",
        "call_order": ["c1"],
    }
    rev_base = {
        "id": "r",
        "baseline": {"id": "baseline", "bundle_sha256": "0" * 64},
        "label": "test",
        "tracts": [tract],
    }
    with pytest.raises(ValueError, match="duplicate edited call identity"):
        DashboardRevision.model_validate(
            rev_base
            | {
                "edits": [
                    base_draft | {"raw_fields": {"notes": "a"}},
                    base_draft | {"raw_fields": {"notes": "b"}},
                ]
            }
        )
    with pytest.raises(ValueError, match="duplicate call identity in tract"):
        DashboardRevision.model_validate(
            rev_base | {"tracts": [tract | {"call_order": ["c1", "c1"]}]}
        )
    corridor = RevisionCorridor(id="cor1", raw_request_json="{}")
    with pytest.raises(ValueError, match="revision schema 1.2"):
        DashboardRevision.model_validate(rev_base | {"corridors": [corridor]})
    with pytest.raises(ValueError, match="duplicate revision corridor identity"):
        DashboardRevision.model_validate(
            rev_base | {"schema_version": "1.2", "corridors": [corridor, corridor]}
        )

    # RevisionComparison requires XOR of comparison and unavailable_reason.
    with pytest.raises(ValueError, match="result or unavailable reason"):
        RevisionComparison(id="cmp", revision_id="r")
    assert (
        RevisionComparison(
            id="cmp", revision_id="r", unavailable_reason="missing"
        ).unavailable_reason
        == "missing"
    )

    # bind_baseline & revision_template produce deterministic baseline-bound templates.
    fixture = Path(__file__).parents[2] / "mp-review/tests/fixtures/dashboard-absolute.json"
    bundle = DashboardBundle.model_validate(json.loads(fixture.read_text()))
    baseline = bind_baseline(bundle)
    assert len(baseline.bundle_sha256) == 64
    tmpl = revision_template(bundle, revision_id="rev-a", generation=1)
    assert tmpl.baseline == baseline
    assert len(tmpl.tracts) == len(bundle.occurrences)
