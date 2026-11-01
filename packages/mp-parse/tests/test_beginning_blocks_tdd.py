"""A BEGINNING block closes only after its own courses; no course text is dropped."""

import json
from pathlib import Path

import pytest
from mp_models import TractType
from mp_parse.calls import extract_calls
from mp_parse.normalizer import normalize_legal_description
from mp_parse.tracts import UNLABELLED_TRACT_LABEL, find_beginning_blocks, split_into_tracts
from mp_verify.closure import verify_closure

_BLOCK_1 = (
    "BEGINNING at a point in the line of Elm Street; "
    "THENCE N 20°00' E 100 feet; THENCE S 70°00' E 100 feet; "
    "THENCE S 20°00' W 100 feet; THENCE N 70°00' W 100 feet "
    "to the POINT OF BEGINNING. "
)
# The block's only point-of-beginning mentions before its courses are preamble.
_BLOCK_2 = (
    "BEGINNING at a point in the line of Oak Road, said point of beginning being "
    "distant 50 feet from Elm Street, and from said point of beginning running "
    "thence N 20°00' E 50 feet; thence S 70°00' E 50 feet; "
    "thence S 20°00' W 50 feet; thence N 70°00' W 50 feet to the point of beginning."
)
# Same block without any closing point-of-beginning after its courses.
_BLOCK_2_UNCLOSED = (
    "BEGINNING at a point in the line of Oak Road, said point of beginning being "
    "distant 50 feet from Elm Street, and from said point of beginning running "
    "thence N 20°00' E 50 feet; thence S 70°00' E 50 feet; "
    "thence S 20°00' W 50 feet; thence N 70°00' W 50 feet to the place first named. "
)
_BLOCK_3 = (
    "BEGINNING at a stake; THENCE N 10°00' E 30 feet; THENCE S 80°00' E 30 feet; "
    "THENCE S 10°00' W 30 feet; THENCE N 80°00' W 30 feet to the POINT OF BEGINNING."
)


class TestPreamblePointOfBeginningIsNotAClosure:
    def test_block_closes_after_its_courses(self):
        text = _BLOCK_1 + _BLOCK_2
        blocks = find_beginning_blocks(text)
        assert len(blocks) == 2
        assert text[blocks[1][0] : blocks[1][1]].rstrip().endswith("point of beginning")

    def test_repro_splits_into_two_closing_tracts(self):
        segments = split_into_tracts(_BLOCK_1 + _BLOCK_2)
        assert [label for _t, label, _k in segments] == ["Tract 1", "Tract 2"]
        calls, tracts = extract_calls(_BLOCK_1 + _BLOCK_2)
        assert len(calls) == 8
        assert [len(t.calls) for t in tracts] == [4, 4]
        areas = []
        for tract in tracts:
            result = verify_closure(tract.calls)
            assert result.misclosure_ft < 0.01
            areas.append(round(result.area_sq_ft))
        assert areas == [10000, 2500]

    def test_unclosed_preamble_block_is_kept_not_dropped(self):
        text = _BLOCK_1 + _BLOCK_2_UNCLOSED + _BLOCK_3
        segments = split_into_tracts(text)
        assert [label for _t, label, _k in segments] == [
            "Tract 1",
            UNLABELLED_TRACT_LABEL,
            "Tract 2",
        ]
        assert "Oak Road" in segments[1][0]
        assert segments[1][2] == TractType.MAIN
        calls, tracts = extract_calls(text)
        assert [len(t.calls) for t in tracts] == [4, 4, 4]
        assert len(calls) == 12

    def test_course_text_after_last_block_is_kept(self):
        text = _BLOCK_1 + _BLOCK_3 + " " + _BLOCK_2_UNCLOSED
        segments = split_into_tracts(text)
        assert [label for _t, label, _k in segments] == [
            "Tract 1",
            "Tract 2",
            UNLABELLED_TRACT_LABEL,
        ]

    def test_unplaceable_course_text_between_blocks_fails_closed(self):
        text = _BLOCK_1 + "thence North along said line. " + _BLOCK_3
        skipped: list = []
        _calls, tracts = extract_calls(text, strict=False, skipped_courses=skipped)
        assert [t.label for t in tracts] == ["Tract 1", UNLABELLED_TRACT_LABEL, "Tract 2"]
        assert tracts[1].calls == []
        assert len(tracts[1].skipped_courses) == 1
        assert skipped == tracts[1].skipped_courses
        with pytest.raises(ValueError):
            extract_calls(text)

    def test_gap_without_courses_is_not_a_tract(self):
        text = _BLOCK_1 + "SCHEDULE A-2 219 BERLIN ROAD, CHERRY HILL. " + _BLOCK_3
        segments = split_into_tracts(text)
        # "SCHEDULE A-2" heads the second description; the header gap is no tract.
        assert [label for _t, label, _k in segments] == ["Unlabelled tract", "Schedule A-2"]


_BERLIN = (
    Path(__file__).resolve().parents[3]
    / "sample_deeds"
    / "219 Berlin Rd - Deed Image (12799 - 00118).ground_truth.json"
)


@pytest.mark.parametrize("field", ["expected_legal_description", "expected_normalized_text"])
@pytest.mark.parametrize("normalize", [False, True])
def test_219_berlin_rd_keeps_every_schedule(field, normalize):
    if not _BERLIN.exists():
        pytest.skip("sample deed ground truth not available")
    truth = json.loads(_BERLIN.read_text())
    text = truth[field]
    if normalize:
        text = normalize_legal_description(text)
    calls, tracts = extract_calls(text, strict=False, skipped_courses=[])
    # Schedule A-1 (6, with its two announced ties), A-2 (16: the lot and its easement),
    # A-3 (4), A-4 (4).
    assert [len(t.calls) for t in tracts] == [6, 16, 4, 4]
    assert [c.distance_ft for c in calls] == [
        c.get("printed_distance_ft", c["distance_ft"]) for c in truth["expected_calls"]
    ]
    assert len(calls) == truth["critical_assertions"]["num_calls"]["expected"]
