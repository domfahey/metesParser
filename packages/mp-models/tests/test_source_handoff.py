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


@pytest.mark.parametrize(
    ("value", "expected_match"),
    [
        (True, "valid integer"),
        (1.5, "valid integer"),
        ("2", "valid integer"),
        (0, "greater than or equal to 1"),
        (-1, "greater than or equal to 1"),
    ],
)
def test_source_page_count_cannot_be_coerced(value, expected_match):
    with pytest.raises(ValidationError, match=expected_match):
        SourceReference(id="source-1", path="source.pdf", page_count=value)


@pytest.mark.parametrize("kwargs", [{}, {"path": "source.pdf", "attachment_id": "attached"}])
def test_source_requires_one_explicit_reference(kwargs):
    with pytest.raises(ValidationError, match="exactly one local path or opaque attachment ID"):
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
    with pytest.raises(ValidationError, match="Instance is frozen"):
        source.sha256 = "0" * 64
    raw = fixture("source-acquisition.json")
    raw["accuracy_verified"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SourceAcquisitionRecord.model_validate(raw)


@pytest.mark.parametrize(
    ("change", "expected_match"),
    [
        (lambda d: d.update(read_pages=["page-1", "page-1"]), "duplicate read_pages"),
        (lambda d: d.update(unreadable_pages=["page-1"]), "both read and unreadable"),
        (lambda d: d.update(supplied_pages=["page-1"]), "must have been supplied"),
        (lambda d: d["page_map"][1].update(page=1), "duplicate source page number"),
        (
            lambda d: d.update(
                uncertainties=[{"id": "u-1", "description": "unknown", "page_ids": ["absent"]}]
            ),
            "dangling uncertainty page ID",
        ),
        (
            lambda d: d.update(
                uncertainties=[{"id": "u-1", "description": "unknown", "source_id": "absent"}]
            ),
            "dangling uncertainty source ID",
        ),
    ],
)
def test_dangling_duplicate_and_contradictory_page_declarations_are_invalid(change, expected_match):
    raw = fixture("source-acquisition.json")
    change(raw)
    with pytest.raises(ValidationError, match=expected_match):
        SourceAcquisitionRecord.model_validate(raw)


def test_missing_pages_are_distinct_from_supplied_pages():
    raw = fixture("source-acquisition.json")
    raw["sources"][0]["page_count"] = 3
    raw["missing_pages"] = [{"id": "page-missing", "source_id": "source-1", "page": 3}]
    assert SourceAcquisitionRecord.model_validate(raw).missing_pages[0].id == "page-missing"
    raw["missing_pages"][0]["page"] = 2
    with pytest.raises(ValidationError, match="duplicate source page number"):
        SourceAcquisitionRecord.model_validate(raw)


def test_source_handoff_path_unicode_page_and_span_guards():
    from mp_models.source_handoff import SelectionSpan, SourcePage

    # Invalid local paths (absolute, parent traversal, backslash, colon, NUL).
    for bad_path in ("/abs/file.pdf", "../up.pdf", "a\\b.pdf", "C:file.pdf", "a\x00b.pdf"):
        with pytest.raises(ValidationError, match="root-relative POSIX paths"):
            SourceReference(id="s1", path=bad_path)

    # Lone surrogate rejected in scalar strings and nested tuple/list fields.
    with pytest.raises(ValidationError, match="unicode string"):
        SourceUncertainty(id="u1", description="\ud800")
    sel_surrogate = fixture("description-selection.json")
    sel_surrogate["candidates"][0]["separators"] = ["\ud800"]
    with pytest.raises(ValidationError, match="Unicode scalar values"):
        DescriptionSelectionRecord.model_validate(sel_surrogate)

    # SourcePage end_line < start_line rejected.
    with pytest.raises(ValidationError, match="end_line precedes start_line"):
        SourcePage(id="p1", source_id="s1", page=1, start_line=10, end_line=5)

    # SelectionSpan decreasing bytes/lines rejected.
    with pytest.raises(ValidationError, match="increasing bytes and nondecreasing lines"):
        SelectionSpan(page_id="p1", start_byte=10, end_byte=10, start_line=1, end_line=1)

    # Acquisition reference checks: dangling source_id, page > page_count, overlapping lines,
    # dangling page in supplied_pages, uncertainty page/source disagreement.
    raw = fixture("source-acquisition.json")
    raw["page_map"][0]["source_id"] = "missing-src"
    with pytest.raises(ValidationError, match="dangling source ID"):
        SourceAcquisitionRecord.model_validate(raw)

    raw = fixture("source-acquisition.json")
    raw["sources"][0]["page_count"] = 1
    with pytest.raises(ValidationError, match="exceeds known page count"):
        SourceAcquisitionRecord.model_validate(raw)

    raw = fixture("source-acquisition.json")
    raw["page_map"][1]["start_line"] = raw["page_map"][0]["end_line"]
    with pytest.raises(ValidationError, match="line ranges overlap"):
        SourceAcquisitionRecord.model_validate(raw)

    raw = fixture("source-acquisition.json")
    raw["supplied_pages"].append("unknown-page")
    with pytest.raises(ValidationError, match="dangling page ID in supplied_pages"):
        SourceAcquisitionRecord.model_validate(raw)

    raw = fixture("source-acquisition.json")
    raw["sources"].append({"id": "source-2", "path": "other.pdf"})
    raw["uncertainties"] = [
        {"id": "u1", "description": "mismatch", "source_id": "source-2", "page_ids": ["page-1"]}
    ]
    with pytest.raises(ValidationError, match="page and source references disagree"):
        SourceAcquisitionRecord.model_validate(raw)

    # DescriptionCandidate wrong separator count and overlapping spans.
    sel = fixture("description-selection.json")
    sel["candidates"][0]["separators"] = []
    with pytest.raises(ValidationError, match="explicit separator"):
        DescriptionSelectionRecord.model_validate(sel)

    sel = fixture("description-selection.json")
    sel["candidates"][0]["spans"][1]["start_byte"] = sel["candidates"][0]["spans"][0]["start_byte"]
    with pytest.raises(ValidationError, match="ordered and nonoverlapping"):
        DescriptionSelectionRecord.model_validate(sel)
