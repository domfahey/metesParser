"""Public source contracts preserve evidence rather than coercing it."""

import json
from pathlib import Path

import pytest
from mp_models.source_handoff import (
    DescriptionSelectionRecord,
    SourceAcquisitionRecord,
    SourceReference,
    SourceUncertainty,
)
from pydantic import ValidationError

FIXTURES = Path(__file__).parents[2] / "mp-review/tests/fixtures/source_handoff"


def fixture(name):
    return json.loads((FIXTURES / name).read_bytes())


def test_acquisition_preserves_request_whitespace_and_unknown_facts():
    raw = fixture("source-acquisition.json")
    raw.update(request="  actual request\r\n", model=None)
    raw["sources"][0]["page_count"] = None
    result = SourceAcquisitionRecord.model_validate(raw)
    assert result.request == "  actual request\r\n"
    assert result.model is None
    assert result.sources[0].page_count is None
    assert result.model_dump(mode="json") == raw


def test_selection_preserves_wording_separators_and_candidate_roles():
    raw = fixture("description-selection.json")
    result = DescriptionSelectionRecord.model_validate(raw)
    assert result.candidates[0].closing_words == "ft\r\n"
    assert result.candidates[0].separators == ("\n",)
    assert result.candidates[0].role == "operative"
    assert result.model_dump(mode="json") == raw


@pytest.mark.parametrize("value", [True, 1.5, "2", 0, -1])
def test_source_page_count_cannot_be_coerced(value):
    with pytest.raises(ValidationError):
        SourceReference(id="source-1", path="source.pdf", page_count=value)


@pytest.mark.parametrize("kwargs", [{}, {"path": "source.pdf", "attachment_id": "attached"}])
def test_source_requires_one_explicit_reference(kwargs):
    with pytest.raises(ValidationError):
        SourceReference(id="source-1", **kwargs)


def test_attachment_id_is_opaque_even_if_it_looks_like_a_path():
    assert (
        SourceReference(id="source-1", attachment_id="../opaque:attachment").attachment_id
        == "../opaque:attachment"
    )


def test_document_uncertainty_does_not_need_invented_page_or_field():
    uncertainty = SourceUncertainty(id="u-1", description="Exhibit identity unknown")
    assert uncertainty.page_ids == ()
    assert uncertainty.source_id is None
    assert uncertainty.affected_field is None


def test_models_are_immutable_and_reject_unknown_accuracy_claims():
    source = SourceReference(id="source-1", path="source.pdf")
    with pytest.raises(ValidationError):
        source.sha256 = "0" * 64
    raw = fixture("source-acquisition.json")
    raw["accuracy_verified"] = True
    with pytest.raises(ValidationError):
        SourceAcquisitionRecord.model_validate(raw)


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update(read_pages=["page-1", "page-1"]),
        lambda d: d.update(unreadable_pages=["page-1"]),
        lambda d: d.update(supplied_pages=["page-1"]),
        lambda d: d["page_map"][1].update(page=1),
        lambda d: d.update(
            uncertainties=[{"id": "u-1", "description": "unknown", "page_ids": ["absent"]}]
        ),
        lambda d: d.update(
            uncertainties=[{"id": "u-1", "description": "unknown", "source_id": "absent"}]
        ),
    ],
)
def test_dangling_duplicate_and_contradictory_page_declarations_are_invalid(change):
    raw = fixture("source-acquisition.json")
    change(raw)
    with pytest.raises(ValidationError):
        SourceAcquisitionRecord.model_validate(raw)


def test_missing_pages_are_distinct_from_supplied_pages():
    raw = fixture("source-acquisition.json")
    raw["sources"][0]["page_count"] = 3
    raw["missing_pages"] = [{"id": "page-missing", "source_id": "source-1", "page": 3}]
    assert SourceAcquisitionRecord.model_validate(raw).missing_pages[0].id == "page-missing"
    raw["missing_pages"][0]["page"] = 2
    with pytest.raises(ValidationError):
        SourceAcquisitionRecord.model_validate(raw)
