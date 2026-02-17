"""Tests for tract splitting logic."""

import pytest
from mp_models import TractType
from mp_parse.tracts import split_into_tracts


class TestExplicitTractMarkers:
    """Priority 1: TRACT #N, TRACT A, PARCEL N markers."""

    def test_tract_numbered(self):
        text = (
            "TRACT #1: BEGINNING at a point... THENCE N 45\u00b000' E 100 feet "
            "to the POINT OF BEGINNING. "
            "TRACT #2: BEGINNING at a point... THENCE S 45\u00b000' E 200 feet "
            "to the POINT OF BEGINNING."
        )
        result = split_into_tracts(text)
        assert len(result) == 2
        assert result[0][1] == "Tract 1"
        assert result[0][2] == TractType.MAIN
        assert result[1][1] == "Tract 2"
        assert result[1][2] == TractType.MAIN

    def test_tract_lettered(self):
        text = (
            "TRACT A: BEGINNING at a point... THENCE N 45\u00b000' E 100 feet "
            "to the POINT OF BEGINNING. "
            "TRACT B: BEGINNING at a point... THENCE S 45\u00b000' E 200 feet "
            "to the POINT OF BEGINNING."
        )
        result = split_into_tracts(text)
        assert len(result) == 2
        assert result[0][1] == "Tract A"
        assert result[1][1] == "Tract B"

    def test_parcel_numbered(self):
        text = (
            "PARCEL 1: BEGINNING at a point... THENCE N 45\u00b000' E 100 feet "
            "to the POINT OF BEGINNING. "
            "PARCEL 2: BEGINNING at a point... THENCE S 45\u00b000' E 200 feet "
            "to the POINT OF BEGINNING."
        )
        result = split_into_tracts(text)
        assert len(result) == 2
        assert result[0][1] == "Parcel 1"
        assert result[1][1] == "Parcel 2"

    def test_tract_without_hash(self):
        text = (
            "TRACT 1 BEGINNING at a point... THENCE N 45\u00b000' E 100 feet "
            "to the POINT OF BEGINNING. "
            "TRACT 2 BEGINNING at a point... THENCE S 45\u00b000' E 200 feet "
            "to the POINT OF BEGINNING."
        )
        result = split_into_tracts(text)
        assert len(result) == 2


class TestMultipleBeginningBlocks:
    """Priority 2: Multiple BEGINNING blocks."""

    def test_two_beginning_blocks(self):
        text = (
            "BEGINNING at an iron pin THENCE N 45\u00b000' E 100 feet; "
            "THENCE S 45\u00b000' E 100 feet; "
            "THENCE S 45\u00b000' W 100 feet; "
            "THENCE N 45\u00b000' W 100 feet to the POINT OF BEGINNING. "
            "ALSO BEGINNING at a concrete monument THENCE S 45\u00b000' E 200 feet; "
            "THENCE S 45\u00b000' W 200 feet; "
            "THENCE N 45\u00b000' W 200 feet; "
            "THENCE N 45\u00b000' E 200 feet to the POINT OF BEGINNING."
        )
        result = split_into_tracts(text)
        assert len(result) == 2

    def test_single_beginning_block_no_split(self):
        text = (
            "BEGINNING at a point THENCE N 45\u00b000' E 100 feet "
            "to the POINT OF BEGINNING."
        )
        result = split_into_tracts(text)
        assert len(result) == 1

    def test_except_beginning_block(self):
        text = (
            "BEGINNING at an iron pin THENCE N 45\u00b000' E 100 feet; "
            "THENCE S 45\u00b000' E 100 feet to the POINT OF BEGINNING. "
            "EXCEPT BEGINNING at another pin THENCE S 10\u00b000' E 50 feet; "
            "THENCE S 10\u00b000' W 50 feet to the POINT OF BEGINNING."
        )
        result = split_into_tracts(text)
        assert len(result) == 2
        types = [r[2] for r in result]
        assert TractType.EXCEPTION in types


class TestExceptAlsoFallback:
    """Priority 3: EXCEPT/ALSO fallback (no BEGINNING blocks)."""

    def test_except_clause_without_beginning(self):
        text = (
            "THENCE N 45\u00b000' E 100 feet; THENCE S 45\u00b000' E 100 feet "
            "EXCEPT THENCE S 10\u00b000' E 50 feet"
        )
        result = split_into_tracts(text)
        assert len(result) == 2
        types = [r[2] for r in result]
        assert TractType.MAIN in types
        assert TractType.EXCEPTION in types


class TestSingleTract:
    """Single-tract deeds pass through unchanged."""

    def test_simple_single_tract(self):
        text = "THENCE N 45\u00b000' E 100 feet to the POINT OF BEGINNING."
        result = split_into_tracts(text)
        assert len(result) == 1
        assert result[0][1] == "Tract 1"
        assert result[0][2] == TractType.MAIN

    def test_return_type(self):
        text = "THENCE N 45\u00b000' E 100 feet."
        result = split_into_tracts(text)
        assert isinstance(result, list)
        text_val, label, tract_type = result[0]
        assert isinstance(text_val, str)
        assert isinstance(label, str)
        assert isinstance(tract_type, TractType)
