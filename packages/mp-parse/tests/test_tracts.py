"""Tests for tract splitting logic."""

import pytest
from mp_models import TractType
from mp_parse.calls import extract_calls
from mp_parse.normalizer import normalize_legal_description
from mp_parse.tracts import find_tract_markers, split_into_tracts


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
        text = "BEGINNING at a point THENCE N 45\u00b000' E 100 feet to the POINT OF BEGINNING."
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


class TestSplitOnMarkersExceptDetection:
    """split_on_markers assigns correct TractType from preceding text."""

    def test_except_preceding_marker_gets_exception_type(self):
        text = (
            "TRACT 1: BEGINNING at a point... THENCE N 45\u00b000' E 100 feet "
            "to the POINT OF BEGINNING. "
            "EXCEPT TRACT 2: BEGINNING at a point... THENCE S 45\u00b000' E 200 feet "
            "to the POINT OF BEGINNING."
        )
        result = split_into_tracts(text)
        assert len(result) == 2
        assert result[1][2] == TractType.EXCEPTION


class TestExtractCallsMultiTract:
    """extract_calls returns Tract objects when multi-tract patterns detected."""

    def test_returns_tracts_for_tract_markers(self):
        text = (
            "TRACT #1: BEGINNING at a point THENCE North 45 degrees 00 minutes 00 seconds East, "
            "a distance of 100.00 feet to a point; THENCE South 45 degrees 00 minutes 00 seconds East, "
            "a distance of 100.00 feet to a point; THENCE South 45 degrees 00 minutes 00 seconds West, "
            "a distance of 100.00 feet to a point; THENCE North 45 degrees 00 minutes 00 seconds West, "
            "a distance of 100.00 feet to the POINT OF BEGINNING. "
            "TRACT #2: BEGINNING at a point THENCE South 45 degrees 00 minutes 00 seconds East, "
            "a distance of 50.00 feet to a point; THENCE South 45 degrees 00 minutes 00 seconds West, "
            "a distance of 50.00 feet to a point; THENCE North 45 degrees 00 minutes 00 seconds West, "
            "a distance of 50.00 feet to a point; THENCE North 45 degrees 00 minutes 00 seconds East, "
            "a distance of 50.00 feet to the POINT OF BEGINNING."
        )
        calls, tracts = extract_calls(text)
        assert len(tracts) == 2
        assert tracts[0].label == "Tract 1"
        assert tracts[1].label == "Tract 2"
        # Course numbering resets per tract
        assert tracts[0].calls[0].course == 1
        assert tracts[1].calls[0].course == 1

    def test_single_tract_returns_empty_tracts(self):
        text = (
            "THENCE North 45 degrees 00 minutes 00 seconds East, "
            "a distance of 100.00 feet to a point; THENCE South 45 degrees 00 minutes 00 seconds East, "
            "a distance of 100.00 feet to the POINT OF BEGINNING."
        )
        calls, tracts = extract_calls(text)
        assert tracts == []
        assert len(calls) == 2

    def test_except_clause_returns_tracts(self):
        text = (
            "THENCE North 45 degrees 00 minutes 00 seconds East, a distance of 100.00 feet; "
            "THENCE South 45 degrees 00 minutes 00 seconds East, a distance of 100.00 feet; "
            "THENCE South 45 degrees 00 minutes 00 seconds West, a distance of 100.00 feet; "
            "THENCE North 45 degrees 00 minutes 00 seconds West, a distance of 100.00 feet "
            "EXCEPT THENCE South 10 degrees 00 minutes 00 seconds East, a distance of 50.00 feet; "
            "THENCE South 10 degrees 00 minutes 00 seconds West, a distance of 50.00 feet"
        )
        calls, tracts = extract_calls(text)
        assert len(tracts) >= 2
        types = [t.tract_type for t in tracts]
        assert TractType.MAIN in types
        assert TractType.EXCEPTION in types

    def test_exception_calls_marked(self):
        """Exception tract calls should have is_exception=True."""
        text = (
            "THENCE North 45 degrees 00 minutes 00 seconds East, a distance of 100.00 feet; "
            "THENCE South 45 degrees 00 minutes 00 seconds East, a distance of 100.00 feet "
            "EXCEPT THENCE South 10 degrees 00 minutes 00 seconds East, a distance of 50.00 feet"
        )
        calls, tracts = extract_calls(text)
        exception_tracts = [t for t in tracts if t.tract_type == TractType.EXCEPTION]
        assert len(exception_tracts) >= 1
        for exc_tract in exception_tracts:
            for call in exc_tract.calls:
                assert call.is_exception is True


class TestNeighbourReferencesAreNotMarkers:
    """Bug #69: references to adjoining parcels/tracts must not split a parcel."""

    def test_neighbour_parcel_references_stay_one_tract(self):
        text = (
            "BEGINNING at the northeast corner of Parcel 2; "
            "THENCE S 0° W 100 ft along the line of Parcel 3; "
            "THENCE W 100 ft; THENCE N 100 ft; "
            "THENCE E 100 ft to the POINT OF BEGINNING."
        )
        assert [label for _t, label, _k in split_into_tracts(text)] == ["Tract 1"]
        calls, tracts = extract_calls(text)
        assert tracts == []
        assert len(calls) == 4


_PT = " THENCE N 45°00' E 100 feet to the POINT OF BEGINNING. "
_SQ = "; thence N 10 E 100 feet to the point of beginning."

# (case id, text, expected heading labels). Every marker case from earlier review
# rounds lives here so that one structural rule is checked against all of them.
_MARKER_CASES = [
    # --- headings ---------------------------------------------------------
    (
        "tract-hash-colon",
        f"TRACT #1: BEGINNING at a point...{_PT}TRACT #2: BEGINNING at a point...{_PT}",
        ["Tract 1", "Tract 2"],
    ),
    (
        "tract-letter",
        f"TRACT A: BEGINNING at a point...{_PT}TRACT B: BEGINNING at a point...{_PT}",
        ["Tract A", "Tract B"],
    ),
    (
        "parcel-number",
        f"PARCEL 1: BEGINNING at a point...{_PT}PARCEL 2: BEGINNING at a point...{_PT}",
        ["Parcel 1", "Parcel 2"],
    ),
    (
        "tract-roman",
        f"TRACT III: BEGINNING at a point...{_PT}TRACT IV: BEGINNING at a point...{_PT}",
        ["Tract III", "Tract IV"],
    ),
    (
        "tract-no-punct",
        f"TRACT 1 BEGINNING at a point...{_PT}TRACT 2 BEGINNING at a point...{_PT}",
        ["Tract 1", "Tract 2"],
    ),
    (
        "except-tract",
        f"TRACT 1: BEGINNING at a point...{_PT}EXCEPT TRACT 2: BEGINNING at a point...{_PT}",
        ["Tract 1", "Tract 2"],
    ),
    (
        "newline-separated",
        "PARCEL A BEGINNING at a point THENCE N 100 ft to the POINT OF BEGINNING.\nPARCEL B BEGINNING at a point THENCE S 100 ft to the POINT OF BEGINNING.",
        ["Parcel A", "Parcel B"],
    ),
    (
        "after-follows-colon",
        "A tract of land described as follows: TRACT 1 BEGINNING at a point THENCE N 100 ft to the POINT OF BEGINNING. TRACT 2 BEGINNING at a point THENCE S 100 ft to the POINT OF BEGINNING.",
        ["Tract 1", "Tract 2"],
    ),
    (
        "merged-after-prose",
        "TRACT 1 BEGINNING at a point THENCE N 100 ft to the POINT OF BEGINNING, containing 1 acre more or less PARCEL 2 BEGINNING at a point THENCE S 100 ft to the POINT OF BEGINNING.",
        ["Tract 1", "Parcel 2"],
    ),
    (
        "after-semicolon",
        "PARCEL 1: BEGINNING at a point THENCE N 100 ft to the POINT OF BEGINNING; PARCEL 2 BEGINNING at a point THENCE S 100 ft to the POINT OF BEGINNING.",
        ["Parcel 1", "Parcel 2"],
    ),
    (
        "standalone-after-of",
        "Schedule A description of\nPARCEL 1\nBEGINNING at a point",
        ["Parcel 1"],
    ),
    ("standalone-after-being", "land being\nTRACT 2\nBEGINNING at a point", ["Tract 2"]),
    ("standalone-after-in", "lands in\nTract 3\nBeginning at a point", ["Tract 3"]),
    ("together-with", "TOGETHER WITH\nPARCEL 2\nBEGINNING at a point", ["Parcel 2"]),
    (
        "ocr-wrapped-heading-line",
        f"PARCEL 1\nBEGINNING at a stake{_SQ} containing 1 acre\nPARCEL 2\nBEGINNING at a pin{_SQ}",
        ["Parcel 1", "Parcel 2"],
    ),
    (
        "unclosed-first-tract",
        "TRACT 1\nBEGINNING at a stake; thence N 10 E 100 feet to the stake first mentioned.\nTRACT 2\nBEGINNING at a pin",
        ["Tract 1", "Tract 2"],
    ),
    ("hyphen-id-line", "PARCEL A-1\nBEGINNING at a stake", ["Parcel A-1"]),
    ("hyphen-id-colon", "PARCEL A-1: BEGINNING at a stake", ["Parcel A-1"]),
    ("colon-beginning", "PARCEL 1: BEGINNING at a stake", ["Parcel 1"]),
    ("spaced-dash", "TRACT 2 - BEGINNING at a stake", ["Tract 2"]),
    ("em-dash", "TRACT 2 — BEGINNING at a stake", ["Tract 2"]),
    ("roman-period-start", "Parcel II.\nBeing the same land conveyed", ["Parcel II"]),
    (
        "roman-period-after-sentence",
        f"PARCEL I: BEGINNING at a stake{_SQ} Parcel II. Being the same land",
        ["Parcel I", "Parcel II"],
    ),
    ("tract-no", "described as follows:\n\nTRACT NO. 1\n\nBEGINNING at a point", ["Tract 1"]),
    ("spelled-number", "described as follows:\n\nTRACT TWO\nBeginning at a point", ["Tract TWO"]),
    ("number-letter-id", "place of beginning.\nTRACT #2B: BEGINNING at a point", ["Tract 2B"]),
    ("markdown-heading", "### TRACT #3\nBEGINNING at a point", ["Tract 3"]),
    (
        "markdown-heading-after-unterminated-calls",
        "BEGINNING at a stake; THENCE N 10 E 100 feet to the POINT OF BEGINNING\n## TRACT #2\nBEING UNIT B",
        ["Tract 2"],
    ),
    ("colon-being", "page 405.\nTRACT #2: BEING the same lands", ["Tract 2"]),
    (
        "ocr-displaced-colon-heading",
        "BEGINNING at a point in the line of Kings Highway East\nTRACT #2:\n(formerly Main Street) said point",
        ["Tract 2"],
    ),
    # --- references and preamble wording -----------------------------------
    (
        "tract-or-parcel-of-land",
        f"ALL THAT CERTAIN TRACT OR PARCEL OF LAND SITUATE IN THE TOWNSHIP BEGINNING at an iron pin{_PT}",
        [],
    ),
    ("being-all-that-tract", f"BEING ALL THAT TRACT IN THE TOWNSHIP{_PT}", []),
    (
        "tract-situate",
        f"ALL THAT CERTAIN TRACT SITUATE IN THE TOWNSHIP OF HADDONFIELD BEGINNING at an iron pin{_PT}",
        [],
    ),
    ("tract-is-described", f"SAID TRACT IS DESCRIBED AS FOLLOWS{_PT}", []),
    ("parcel-of-land", f"ALL THAT CERTAIN PARCEL OF LAND SITUATE IN THE COUNTY{_PT}", []),
    ("tract-conveyed", f"THE TRACT CONVEYED BY DEED BOOK 1234 PAGE 567{_PT}", []),
    ("parcel-info-header", "    Parcel Info\n    Property Type  Tax Dist.", []),
    (
        "neighbour-parcels",
        "BEGINNING at the northeast corner of Parcel 2; THENCE S 0 W 100 ft along the line of Parcel 3; THENCE W 100 ft to the POINT OF BEGINNING.",
        [],
    ),
    (
        "lot-of-tract",
        "BEGINNING at the corner of Lot 5 of Tract 4567; THENCE N 100 ft along Lot 6 of Tract 4567; THENCE E 100 ft to the POINT OF BEGINNING.",
        [],
    ),
    (
        "ocr-wrapped-reference",
        "BEGINNING at the northeast corner of\nParcel 2; THENCE S 0 W 100 ft along the line of\nParcel 3; THENCE W 100 ft to the POINT OF BEGINNING.",
        [],
    ),
    (
        "hyphen-id-reference",
        "PARCEL 1: BEGINNING at a corner of Parcel A-1, thence N 10 ft",
        ["Parcel 1"],
    ),
    (
        "in-reference",
        "TRACT 1: BEGINNING at a point in Tract 4567\nBEGINNING at a stake",
        ["Tract 1"],
    ),
    (
        "within-reference",
        "TRACT 1: BEGINNING at a point within Tract 4567\nBEGINNING at a stake",
        ["Tract 1"],
    ),
    (
        "being-reference",
        "TRACT 1: BEGINNING at a point being Tract 4567\nBEGINNING at a stake",
        ["Tract 1"],
    ),
    (
        "in-reference-line-break",
        "TRACT 1: BEGINNING at a point lying in\nTract 4567\nBEGINNING at a stake",
        ["Tract 1"],
    ),
    ("inline-reference-then", "of Parcel 2 then N 10 ft", []),
    (
        "caps-area-sentence-after-tract",
        "TRACT 1: BEGINNING AT A PIN; THENCE N 10\u00b0 E 100 FEET; THENCE S 80\u00b0 E 100 FEET TO THE PLACE OF BEGINNING. TRACT 1 CONTAINING 0.23 ACRES. TRACT 2: BEGINNING AT A PIN; THENCE N 10\u00b0 E 50 FEET TO THE PLACE OF BEGINNING.",
        ["Tract 1", "Tract 2"],
    ),
    (
        "caps-parcel-excepted",
        f"PARCEL 1: BEGINNING AT A PIN{_SQ} PARCEL 2 IS EXCEPTED THEREFROM.",
        ["Parcel 1"],
    ),
    (
        "caps-tract-containing",
        f"TRACT 1: BEGINNING at a pin{_SQ} TRACT 1 CONTAINING 0.23 ACRES",
        ["Tract 1"],
    ),
    (
        "caps-tract-herein",
        f"TRACT 1: BEGINNING at a pin{_SQ} TRACT 2 HEREIN DESCRIBED",
        ["Tract 1"],
    ),
    (
        "pob-opener-stays-open",
        "TRACT 1\nPOINT OF BEGINNING at a stake; thence N 10 E 100 feet along the line of\nTract 4567\nthence S 10 W 100 feet",
        ["Tract 1"],
    ),
    (
        "place-opener-stays-open",
        "TRACT 1\nplace of BEGINNING at a stake; thence N 10 E 100 feet along the line of\nTract 4567\nthence S 10 W 100 feet",
        ["Tract 1"],
    ),
    (
        "shown-as-on-a-plan",
        f"PARCEL 1\nBEGINNING at a corner of land shown as\nParcel 2 on a plan of lots{_SQ}",
        ["Parcel 1"],
    ),
    (
        "shown-as-before-beginning",
        "being land shown as\nParcel 2 on a plan of lots, BEGINNING at a stake",
        [],
    ),
    (
        "known-as-on-said-map",
        f"PARCEL 1\nBEGINNING at a corner of lands known as\nTract 4567 on said map{_SQ}\nPARCEL 2\nBEGINNING at a stake",
        ["Parcel 1", "Parcel 2"],
    ),
    (
        "smith-and-parcel-thence",
        f"PARCEL 1\nBEGINNING at a stake in line of lands of Smith and\nParcel 2 thence N 10 E 100 feet{_SQ}",
        ["Parcel 1"],
    ),
    (
        "lot-in-tract-wrapped",
        "BEGINNING at the corner of Lot 12, in\nTract 4567\nthence N 10 E 100 feet",
        [],
    ),
    ("lot-in-tract-trailing", "being Lot 12, in\nTract 4567\n", []),
    ("reference-period", "THENCE along the line of Parcel 3. THENCE S 10 W 100 feet", []),
    ("known-as-period", "being the land known as Parcel 2.", []),
    ("tract-comma-thence", "BEGINNING at Lot 5 in Block 2, Tract 4567, thence N 10 E", []),
    ("reference-colon-open", "BEGINNING at a stake, corner to Parcel 2: thence N 10 E", []),
    (
        "glued-hyphen-reference",
        "PARCEL 1: BEGINNING at a corner of Tract 2-B, thence N 10 E",
        ["Parcel 1"],
    ),
    ("as-shown", "TRACT 1: BEGINNING at a point\nParcel 2 as shown on a map", ["Tract 1"]),
    ("place-of-beginning-opener", "TRACT 1 place of BEGINNING at a stake", ["Tract 1"]),
    (
        "all-that-opener",
        f"TRACT 1: BEGINNING at a stake{_SQ}\nTRACT 2\nALL THAT certain lot",
        ["Tract 1", "Tract 2"],
    ),
    ("word-not-id", "TRACT ADJOINING the lands of Smith", []),
    (
        "paren-then-newline",
        "...to the point of beginning.\nPARCEL 2 (Tax ID 12-34)\nBEGINNING at a pin",
        ["Parcel 2"],
    ),
    (
        "paren-then-beginning",
        "...to the point of beginning.\nPARCEL 2 (Tax ID 12-34) BEGINNING at a pin",
        ["Parcel 2"],
    ),
    ("comma-beginning", "TRACT 2, BEGINNING at a pin", ["Tract 2"]),
    ("paren-comma-beginning", "TRACT 2 (Lot 5), BEGINNING at a pin", ["Tract 2"]),
    ("comma-thence-ref", "of Parcel 2, thence N 10 E 100 feet", []),
    ("comma-on-a-plan", "BEGINNING at Lot 5, Tract 4567, on a plan of lots", []),
    ("paren-prose-ref", "corner of Parcel 2 (see plan) thence N 10 E", []),
    ("paren-then-prose", "...beginning.\nPARCEL 2 (Tax ID 12-34) as shown on a map", []),
    # --- titlecase BEING after an ID is a recital, not a heading -----------
    (
        "titlecase-being-recital-sentence",
        "BEGINNING at a pin; thence N 10° E 100 feet to the POINT OF BEGINNING. Tract 2 being the same land conveyed to John Smith",
        [],
    ),
    (
        "titlecase-being-part-of-after-break",
        "PARCEL 1: BEGINNING at a stake; thence N 10 E 100 feet to the POINT OF BEGINNING. Parcel 2 being part of lands of Jones",
        ["Parcel 1"],
    ),
    ("titlecase-being-part-of-start", "Parcel 2 being part of lands of Jones", []),
    # --- uppercase BEING heading style is still a heading --------------------
    (
        "uppercase-being-heading-same-line",
        "BEGINNING at a stake; THENCE N 10 E 100 feet to the POINT OF BEGINNING.\nTRACT 2 BEING UNIT B",
        ["Tract 2"],
    ),
    (
        "uppercase-being-same-land-recital",
        "BEGINNING at a stake; THENCE N 10 E 100 feet to the POINT OF BEGINNING. TRACT 2 BEING THE SAME LAND CONVEYED TO JOHN SMITH",
        [],
    ),
    # --- uppercase marker in heading position followed by heading prose --------
    (
        "uppercase-tract-situate-after-period",
        f"TRACT 1: BEGINNING at a stake{_SQ} containing 1 acre. TRACT 2 Situate in the Township of X, BEGINNING at a pin{_SQ}",
        ["Tract 1", "Tract 2"],
    ),
    (
        "uppercase-parcel-spelled-being-all",
        f"PARCEL ONE: BEGINNING at a stake{_SQ}\nPARCEL TWO being all that lot BEGINNING at a pin{_SQ}",
        ["Parcel ONE", "Parcel TWO"],
    ),
    (
        "uppercase-parcel-two-at-start",
        f"PARCEL TWO being all that lot BEGINNING at a pin{_SQ}",
        ["Parcel TWO"],
    ),
    (
        "uppercase-tract-after-semicolon-situate",
        f"TRACT 1: BEGINNING at a stake{_SQ[:-1]}; TRACT 2 SITUATE IN THE BOROUGH OF Y BEGINNING at a pin{_SQ}",
        ["Tract 1", "Tract 2"],
    ),
    (
        "uppercase-markdown-heading-prose",
        f"## PARCEL B lying in the County of Z\nBEGINNING at a pin{_SQ}",
        ["Parcel B"],
    ),
    (
        "uppercase-reference-of-subdivision",
        "BEGINNING at a pin; THENCE N 10 E 100 feet to the POINT OF BEGINNING. TRACT 2 of the Smith subdivision adjoins on the north.",
        [],
    ),
    (
        "uppercase-reference-as-shown",
        "BEGINNING at a pin; THENCE N 10 E 100 feet to the POINT OF BEGINNING. PARCEL 2 as shown on a plan of lots.",
        [],
    ),
    (
        "uppercase-reference-on-said-map",
        "BEGINNING at a pin; THENCE N 10 E 100 feet to the POINT OF BEGINNING. TRACT 4567 on said map is excepted.",
        [],
    ),
    (
        "uppercase-reference-in-said",
        "BEGINNING at a pin; THENCE N 10 E 100 feet to the POINT OF BEGINNING. TRACT 4567 IN SAID SUBDIVISION",
        [],
    ),
    (
        "uppercase-reference-per-plan",
        "BEGINNING at a pin; THENCE N 10 E 100 feet to the POINT OF BEGINNING. PARCEL 2 PER PLAN OF LOTS",
        [],
    ),
    (
        "uppercase-mid-sentence-stays-reference",
        "BEGINNING at a corner of TRACT 2 situate in the Township; THENCE N 10 E 100 feet to the POINT OF BEGINNING.",
        [],
    ),
    (
        "uppercase-in-open-description-after-reference-word",
        "TRACT 1: BEGINNING at a point lying in\nTRACT 4567 Situate in the Township\nthence N 10 E 100 feet",
        ["Tract 1"],
    ),
    (
        "titlecase-situate-after-period-stays-reference",
        "BEGINNING at a pin; THENCE N 10 E 100 feet to the POINT OF BEGINNING. Tract 2 situate in the Township of X",
        [],
    ),
    # --- heading position + description opener before any course (any case) -----
    (
        "r15-titlecase-being-all-that-after-period",
        "Parcel 1: BEGINNING at a stake; THENCE N 10° E 100 feet to the place of beginning. Parcel 2 being all that lot BEGINNING at a pin; THENCE S 5° E 50 feet",
        ["Parcel 1", "Parcel 2"],
    ),
    (
        "r15-titlecase-situate-after-semicolon",
        f"Parcel 1: BEGINNING at a stake{_SQ[:-1]}; Parcel 2 Situate in the Township; BEGINNING at a pin{_SQ}",
        ["Parcel 1", "Parcel 2"],
    ),
    (
        "r15-lowercase-situate-after-period",
        f"tract 1: BEGINNING at a stake{_SQ} tract 2 situate in the Township of X, BEGINNING at a pin{_SQ}",
        ["Tract 1", "Tract 2"],
    ),
    (
        "r15-lowercase-lying-and-being-newline",
        f"parcel 1: BEGINNING at a stake{_SQ}\nparcel 2 lying and being in the Borough of Y, COMMENCING at a pin{_SQ}",
        ["Parcel 1", "Parcel 2"],
    ),
    (
        "r15-titlecase-being-all-that-newline",
        f"Tract 1: BEGINNING at a stake{_SQ}\nTract 2 being all that lot BEGINNING at a pin{_SQ}",
        ["Tract 1", "Tract 2"],
    ),
    (
        "r15-titlecase-at-text-start",
        f"Parcel 2 Situate in the Township; BEGINNING at a pin{_SQ}",
        ["Parcel 2"],
    ),
    (
        "r15-titlecase-after-colon-all-that",
        f"described as follows: Parcel 2 lying and being in X, ALL THAT lot BEGINNING at a pin{_SQ}",
        ["Parcel 2"],
    ),
    (
        "r15-reference-of-before-opener-stays-reference",
        f"BEGINNING at a stake{_SQ} Parcel 2 of the Smith plan, BEGINNING at a pin{_SQ}",
        [],
    ),
    (
        "r15-reference-in-said-before-opener-stays-reference",
        f"BEGINNING at a stake{_SQ} Parcel 2 in said subdivision, BEGINNING at a pin{_SQ}",
        [],
    ),
    (
        "r15-course-before-opener-stays-reference",
        f"BEGINNING at a stake{_SQ} Parcel 2 adjoins; thence N 10 E 5 feet to the point of beginning.",
        [],
    ),
    (
        "r15-open-description-reference-stays-reference",
        "TRACT 1: BEGINNING at a point; thence N 10 E 5 feet; the line of. Parcel 2 situate in X, BEGINNING at a pin",
        ["Tract 1"],
    ),
    # --- 'NO' prefix must be a standalone token ---------------------------------
    ("no-prefix-not-word-start", "TRACT 1: Beginning x. TRACT NOW.", ["Tract 1"]),
    ("no-prefix-not-word-start-parcel", "PARCEL 1: Beginning x. PARCEL NOT.", ["Parcel 1"]),
    ("no-prefix-space", "described as follows:\n\nTRACT NO 2\nBEGINNING at a point", ["Tract 2"]),
    ("no-prefix-hash", "described as follows:\n\nTRACT NO #3\nBEGINNING at a point", ["Tract 3"]),
    (
        "no-prefix-glued-period",
        "described as follows:\n\nPARCEL NO.4: BEGINNING at a point",
        ["Parcel 4"],
    ),
]


@pytest.mark.parametrize("normalize", [False, True], ids=["raw", "normalized"])
@pytest.mark.parametrize(
    ("text", "labels"),
    [pytest.param(text, labels, id=case_id) for case_id, text, labels in _MARKER_CASES],
)
def test_tract_heading_markers(text, labels, normalize):
    """A marker is a heading only when its own structure ends the heading unit."""
    if normalize:
        text = normalize_legal_description(text)
    assert [label for _pos, label, _kind in find_tract_markers(text)] == labels


_LEADING = (
    "BEGINNING at an iron pin; THENCE North 45 degrees 00 minutes 00 seconds East, "
    "a distance of 100.00 feet to a point; THENCE South 45 degrees 00 minutes 00 seconds East, "
    "a distance of 100.00 feet to a point; THENCE South 45 degrees 00 minutes 00 seconds West, "
    "a distance of 100.00 feet to a point; THENCE North 45 degrees 00 minutes 00 seconds West, "
    "a distance of 100.00 feet to the POINT OF BEGINNING"
)
_TRACT2 = (
    "## TRACT #2\nBEING UNIT B. BEGINNING at a pin; THENCE North 10 degrees 00 minutes 00 seconds East, "
    "a distance of 50.00 feet to a point; THENCE South 80 degrees 00 minutes 00 seconds East, "
    "a distance of 50.00 feet to a point; THENCE South 10 degrees 00 minutes 00 seconds West, "
    "a distance of 50.00 feet to a point; THENCE North 80 degrees 00 minutes 00 seconds West, "
    "a distance of 50.00 feet to the POINT OF BEGINNING."
)


class TestLeadingTractBeforeFirstMarker:
    def test_leading_calls_kept_as_unlabelled_tract(self):
        result = split_into_tracts(f"{_LEADING}\n{_TRACT2}")
        assert [label for _t, label, _k in result] == ["Unlabelled tract", "Tract 2"]
        assert "THENCE" in result[0][0]
        assert result[0][2] == TractType.MAIN

    def test_preamble_without_calls_still_dropped(self):
        result = split_into_tracts(f"Schedule A recital\nDeed Book 1\n{_TRACT2}")
        assert [label for _t, label, _k in result] == ["Tract 2"]

    def test_thence_noise_before_marker_not_a_tract(self):
        pre = "Grantor thence colspan=3 First Party thence in Southeasterly direction"
        result = split_into_tracts(f"{pre}\n{_TRACT2}")
        assert [label for _t, label, _k in result] == ["Tract 2"]

    def test_extract_calls_keeps_leading_tract(self):
        from mp_parse.calls import extract_calls

        _flat, tracts = extract_calls(f"{_LEADING}\n{_TRACT2}")
        assert [t.label for t in tracts] == ["Unlabelled tract", "Tract 2"]
        assert len(tracts[0].calls) == 4

    @pytest.mark.parametrize(
        "pre",
        [
            "THENCE with said line S 10\u00b0 W 50 feet to a pin",
            "THENCE along a curve to the right having a radius of 50 feet",
            "THENCE along the line of Smith by a curve to the left, radius 40 feet",
            "THENCE by lands of Jones N 10 E 50 feet to a pin",
        ],
    )
    def test_broader_thence_courses_kept_as_unlabelled(self, pre):
        result = split_into_tracts(f"{pre}\n{_TRACT2}")
        assert [label for _t, label, _k in result] == ["Unlabelled tract", "Tract 2"]

    @pytest.mark.parametrize(
        "pre",
        [
            "Grantor thence colspan=3 First Party",
            "thence in Southeasterly direction",
            "thence along colspan=3 rowspan=2",
        ],
    )
    def test_dropped_thence_text_logs_warning(self, pre):
        from structlog.testing import capture_logs

        with capture_logs() as logs:
            result = split_into_tracts(f"{pre}\n{_TRACT2}")
        assert [label for _t, label, _k in result] == ["Tract 2"]
        assert any(e["log_level"] == "warning" and "dropping" in e["event"].lower() for e in logs)


def test_extract_calls_all_caps_area_sentence_does_not_add_tract():
    from mp_parse.calls import extract_calls

    text = (
        "TRACT 1: BEGINNING AT A PIN; THENCE N 10\u00b0 E 100 FEET; THENCE S 80\u00b0 E 100 FEET "
        "TO THE PLACE OF BEGINNING. TRACT 1 CONTAINING 0.23 ACRES. "
        "TRACT 2: BEGINNING AT A PIN; THENCE N 10\u00b0 E 50 FEET; THENCE S 80\u00b0 E 50 FEET "
        "TO THE PLACE OF BEGINNING."
    )
    _flat, tracts = extract_calls(text)
    assert [t.label for t in tracts] == ["Tract 1", "Tract 2"]


def test_repeated_label_without_calls_folds_into_previous_tract():
    # A same-label marker the word list does not recognise must not split.
    text = (
        "TRACT 1: BEGINNING at a pin; THENCE N 10 E 100 feet to the POINT OF BEGINNING. "
        "TRACT 1 WHOSEVER 0.23 ACRES. "
        "TRACT 2: BEGINNING at a pin; THENCE N 10 E 50 feet to the POINT OF BEGINNING."
    )
    result = split_into_tracts(text)
    assert [label for _t, label, _k in result] == ["Tract 1", "Tract 2"]
    assert "WHOSEVER" in result[0][0]


@pytest.mark.parametrize(
    ("text", "label", "fragment"),
    [
        (
            "TRACT ONE: BEGINNING at a pin; thence N 10° E 100 feet to the point of beginning. "
            "Tract One: 1.2 acres more or less.",
            "Tract ONE",
            "1.2 acres",
        ),
        (
            "PARCEL TWO: BEGINNING at a pin; thence N 10° E 100 feet to the point of beginning. "
            "Parcel Two: subject to easements of record.",
            "Parcel TWO",
            "subject to easements",
        ),
    ],
    ids=["tract-one-titlecase-repeat", "parcel-two-titlecase-repeat"],
)
def test_repeated_label_differing_only_in_case_folds_into_first(text, label, fragment):
    result = split_into_tracts(text)
    assert [lbl for _t, lbl, _k in result] == [label]
    assert fragment in result[0][0]


# --- "TRACT n: BEING the same lands ..." recitals (15 E Euclid Ave) --------------

_T1 = (
    "TRACT #1: BEGINNING in the line of Euclid Avenue; thence Southwestwardly 80 feet; "
    "thence Northwestwardly 142 feet. "
)
_T1_OCR = _T1.replace("#1", "#l")
_T2 = (
    "TRACT #2: BEGINNING at a point; and extends thence (1) Westwardly 10 feet; "
    "thence (2) Northwardly 142 feet to the point of beginning. "
)
_R1 = (
    "TRACT #1: BEING the same lands and premises which became vested in A by deed from B "
    "recorded in Book 2321 page 405. "
)
_R2 = (
    "TRACT #2:BEING the same lands and premises which became vested in C by deed from D "
    "in Deed Book 2427 at page 224. "
)
_R1_COURSE = (
    "TRACT #1: BEING the same premises conveyed to A by deed recorded in Book 1, lying "
    "Northerly of Euclid Avenue and thence Westerly of Turnley Avenue. "
)

# (case id, text, expected tract labels, {label: recital fragment its text keeps})
_RECITAL_SPLIT_CASES = [
    (
        "recitals-after-descriptions",
        _T1 + _T2 + _R1 + _R2,
        ["Tract 1", "Tract 2"],
        {"Tract 1": "Book 2321", "Tract 2": "Book 2427"},
    ),
    # OCR read the first heading "#l": the unmatched recital is dropped, never a tract.
    (
        "ocr-label-recital-dropped",
        _T1_OCR + _T2 + _R1 + _R2,
        ["Tract l", "Tract 2"],
        {"Tract 2": "Book 2427"},
    ),
    # Course words (even "thence Westerly") inside a recital are not boundary calls.
    (
        "recital-with-course-words",
        _T1 + _T2 + _R1_COURSE,
        ["Tract 1", "Tract 2"],
        {"Tract 1": "Turnley"},
    ),
    (
        "ocr-label-recital-with-course-words-dropped",
        _T1_OCR + _T2 + _R1_COURSE,
        ["Tract l", "Tract 2"],
        {},
    ),
    # A recital before the description with the same label folds into it.
    (
        "recital-before-description",
        _R1 + _T1 + _T2,
        ["Tract 1", "Tract 2"],
        {"Tract 1": "Book 2321"},
    ),
    # A recital-only deed keeps its tract: there is no described tract to fold into.
    ("recital-only", _R1, ["Tract 1"], {"Tract 1": "Book 2321"}),
    (
        "recitals-only",
        _R1 + _R2,
        ["Tract 1", "Tract 2"],
        {"Tract 1": "Book 2321", "Tract 2": "Book 2427"},
    ),
]


@pytest.mark.parametrize("normalize", [False, True], ids=["raw", "normalized"])
@pytest.mark.parametrize(
    ("text", "labels", "contains"),
    [case[1:] for case in _RECITAL_SPLIT_CASES],
    ids=[case[0] for case in _RECITAL_SPLIT_CASES],
)
def test_being_the_same_recital_never_forms_its_own_tract(text, labels, contains, normalize):
    if normalize:
        text = normalize_legal_description(text)
    result = split_into_tracts(text)
    assert [label for _t, label, _k in result] == labels
    by_label = {label: segment for segment, label, _k in result}
    for label, fragment in contains.items():
        assert fragment in by_label[label]


def test_unmatched_recital_drop_is_logged():
    from structlog.testing import capture_logs

    with capture_logs() as logs:
        split_into_tracts(_T1_OCR + _T2 + _R1 + _R2)
    assert any(e["log_level"] == "warning" and "recital" in e["event"].lower() for e in logs)


def test_15_euclid_7433_sample_matches_ground_truth_tract_count():
    # Ground truth: 2 tracts (Tract #1 with 2 calls, Tract #2 with 4 calls).
    from pathlib import Path

    md = (
        Path(__file__).resolve().parents[3]
        / "sample_deeds"
        / "15 E Euclid Ave - Deed Image (7433 - 466).md"
    )
    if not md.exists():
        pytest.skip("sample deed markdown not available")
    text = md.read_text()
    for source in (text, normalize_legal_description(text)):
        assert len(split_into_tracts(source)) == 2


class TestStructuralHeadingWithoutTerminator:
    def test_titlecase_parcel_with_prose_before_opener_is_separate_tract(self):
        text = (
            "Parcel 1: BEGINNING at a stake; THENCE North 10 degrees 00 minutes 00 seconds East "
            "100.00 feet to a point; THENCE East 100.00 feet to a point; THENCE South 100.00 feet "
            "to a point; THENCE West 100.00 feet to the place of beginning. "
            "Parcel 2 being all that lot BEGINNING at a pin; THENCE South 5 degrees 00 minutes "
            "00 seconds East 50.00 feet to a point; THENCE West 50.00 feet to a point; "
            "THENCE North 50.00 feet to a point; THENCE East 50.00 feet to the place of beginning."
        )
        labels = [label for _t, label, _k in split_into_tracts(text)]
        assert labels == ["Parcel 1", "Parcel 2"]
        calls, tracts = extract_calls(text)
        assert len(calls) == 8
        assert [(t.label, len(t.calls)) for t in tracts] == [("Parcel 1", 4), ("Parcel 2", 4)]


# --- Recital course distances use the shared length-unit vocabulary ----------------


@pytest.mark.parametrize("unit", ["furlongs", "arpents", "US survey feet", "engineer chains"])
def test_recital_with_course_in_shared_unit_matches_feet(unit):
    def recital(distance_unit: str) -> str:
        return (
            "TRACT #1: BEING the same lands and premises which became vested in A by deed "
            f"recorded in Book 2321 page 405, thence N 10 E 2 {distance_unit} to the point "
            "of beginning. "
        )

    from mp_parse.tracts import _is_title_recital

    # A course with a measured distance is a boundary call, never a title recital.
    assert not _is_title_recital(recital("feet"))
    assert not _is_title_recital(recital(unit))


def test_recital_with_bearing_minutes_only_states_no_course():
    from mp_parse.tracts import _is_title_recital

    recital = (
        "TRACT #1: BEING the same lands and premises which became vested in A by deed "
        "recorded in Book 2321 page 405, thence N 45 30' E. "
    )
    assert _is_title_recital(recital)
