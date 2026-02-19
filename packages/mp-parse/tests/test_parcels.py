"""Tests for multi-parcel deed separation.

TDD tests for split_into_parcels() and detect_parcel_markers().
"""

from __future__ import annotations

from mp_parse.parcels import detect_parcel_markers, split_into_parcels

# ---------------------------------------------------------------------------
# Full legal description from deed 50146-01291 ground truth
# ---------------------------------------------------------------------------
MULTI_PARCEL_TEXT = (
    "The land referred to in this commitment is described as follows: "
    "Township of Sample, County of Sample, State of Michigan\n\n"
    "Parcel A (Northern Tract of land): \n\n"
    "A parcel of land located in the Southwest 1/4 of Section 12, Town 3 South, "
    "Range 8 East, Sample Township, Sample County, Michigan, more particularly "
    "described as follows:\n"
    "Commencing at the Southwest 1/4 of Section 12, Town 3 South, Range 8 East, "
    "Sample Township, Sample County, Michigan; thence along the West line of said "
    "Section 12 and the centreline of Haggerty Road (120 feet wide), North 02 degrees "
    "23 minutes 55 seconds West 640.19 feet to the North Right-of-Way line of Old Tyler "
    "Road (variable width); thence along said North Right-of-Way line North 89 degrees "
    "08 minutes 49 seconds East 942.89 feet to the point of beginning; thence North 00 "
    "degrees 11 minutes 02 seconds East 318.96 feet; thence North 89 degrees 09 minutes "
    "29 seconds East 551.39 feet to a point on the Westerly Right-of-Way of I- 275, said "
    "point also being a point on a non-tangential curve to the left; thence along a non- "
    "tangential curve to the left, having a length of 265.54 feet, a Radius of 4039.72 "
    "feet, an interior angle of 3 degrees 45 minutes 58 seconds, Chord bearing South 19 "
    "degrees 19 minutes 34 seconds East 265.49 feet; thence South 89 degrees 08 minutes "
    "49 seconds West 121.61 feet; thence South 00 degrees 51 minutes 11 seconds East "
    "40.00 feet; thence South 89 degrees 08 minutes 49 seconds West 75.90 feet; thence "
    "South 01 degrees 52 minutes 46 seconds East 26.99 feet; thence South 89 degrees 08 "
    "minutes 49 seconds West 282.00 feet; thence along a non- tangential curve to the "
    "left, having a length of 118.23 feet, a Radius of 75.00 feet, an interior angle of "
    "90 degrees 19 minutes 04 seconds, Chord bearing North 80 degrees 59 minutes 50 "
    "seconds West 106.36 feet; thence along a reverse curve to the right, having a length "
    "of 61.00 feet, a Radius of 99.00 feet, an interior angle of 35 degrees 18 minutes "
    "11 seconds, Chord bearing South 71 degrees 29 minutes 43 seconds West 60.04 feet; "
    "thence South 89 degrees 08 minutes 49 seconds West 0.25 feet to the point of "
    "beginning.\n\n"
    "Re: 9059 Samuel Barton Drive Tax Item No. 83-047-99-0002-701\n\n"
    "Parcel B (Southern Tract of land): A parcel of land located in the Southwest 1/4 "
    "of Section 12 Town 3 South, Range 8 East, Sample Township, Sample County, "
    "Michigan, more particularly described as follows: Commencing at the Southwest 1/4 "
    "of Section 12, Town 3 South, Range 8 East, Sample Township, Sample County, "
    "Michigan; thence along the West line of said Section 12 and the centerline of "
    "Haggerty Road (120 feet wide), North 02 degrees 23 minutes 55 seconds West 574.17 "
    "feet to the South Right-of-Way line of Old Tyler Road (variable width); thence "
    "along said South Right-of-Way line North 89 degrees 08 minutes 49 seconds East "
    "704.61 (surveyed as 704.60) feet to the point of beginning; thence along said "
    "Right-of-Way line North 89 degrees 08 minutes 49 seconds East 198.97 feet; thence "
    "along a curve to the right, having a length of 97.08 feet, a Radius of 135.00 "
    "feet, an interior angle of 41 degrees 12 minutes 14 seconds, Chord bearing South "
    "70 degrees 15 minutes 04 seconds East 95.01 feet; thence along a reverse curve to "
    "the left, having a length of 217.54 feet, a Radius of 75.00 feet, an interior "
    "angle of 166 degrees 11 minutes 22 seconds, Chord bearing North 47 degrees 15 "
    "minutes 23 seconds East 148.91 feet; thence North 89 degrees 08 minutes 49 seconds "
    "East 282.00 feet; thence North 01 degrees 52 minutes 46 seconds West 26.99 feet; "
    "thence North 89 degrees 08 minutes 49 seconds East 75.90 feet; thence North 00 "
    "degrees 51 minutes 11 seconds West 40.00 feet; thence North 89 degrees 08 minutes "
    "49 seconds East 121.61 feet to a point on the Westerly Right-of-Way line of I-275, "
    "said point also being a point on a non-tangential curve to the left; thence along a "
    "non-tangential curve to the left, having a length of 346.10 feet, a Radius of "
    "4039.72 feet, an interior angle of 4 degrees 54 minutes 32 seconds, Chord bearing "
    "South 23 degrees 39 minutes 49 seconds East 346.00 feet; thence South 66 degrees "
    "15 minutes 33 seconds West 692.41 feet; thence South 74 degrees 32 minutes 14 "
    "seconds West 294.02 feet; thence South 87 degrees 18 minutes 53 seconds West 77.58 "
    "feet; thence North 02 degrees 08 minutes 34 seconds West 532.02 feet to the point "
    "of beginning.\n\n"
    "Re: 40000 Ricardo Drive Tax Item No. 83-047-99-0007-702\n\n"
    "Combine Legal Description: A parcel of land located in the Southwest 1/4 of "
    "Section 12, Town 3 South, Range 8 East, Sample Township, Sample County, "
    "Michigan, more particularly described as follows: Commencing at the Southwest 1/4 "
    "of Section 12, Town 3 South, Range 8 East, Sample Township, Sample County, "
    "Michigan; thence along the West line of said Section 12 and the centreline of "
    "Haggerty Road (120 feet wide), North 02 degrees 23 minutes 55 seconds West 574.17 "
    "feet to the South right of way line of Old Tyler Road (variable width); thence "
    "along said South right of way line North 89 degrees 08 minutes 49 seconds East "
    "704.60 feet for the point of beginning; thence along said right of way line North "
    "89 degrees 08 minutes 49 seconds East 198.97 feet; thence along a curve to the "
    "right, having a length of 97.08 feet, a radius of 135.00 feet, an interior angle "
    "of 41 degrees 12 minutes 14 seconds, chord bearing South 70 degrees 15 minutes 04 "
    "seconds East 95.01 feet; thence along a reverse curve to the left, having a length "
    "of 335.77 feet, a radius of 75.00 feet, an interior angle of 256 degrees 30 "
    "minutes 26 seconds, chord bearing North 02 degrees 05 minutes 50 seconds East "
    "117.79 feet; thence along a reverse curve to the right, having a length of 61.00 "
    "feet a radius of 99.00 feet, an interior angle of 35 degrees 18 minutes 11 "
    "seconds, chord bearing South 71 degrees 29 minutes 43 seconds West 60.04 feet; "
    "thence South 89 degrees 08 minutes 49 seconds West 0.25 feet; thence North 00 "
    "degrees 11 minutes 02 seconds East 318.96 feet; thence North 89 degrees 09 minutes "
    "29 seconds East 551.39 feet to a point on the Westerly right of way line of I-275, "
    "said point also being a point on a non-tangential curve to the left; thence along "
    "the Westerly right of way line of I-275 and a non- tangential curve to the left, "
    "having a length of 611.64 feet, a radius of 4039.72 feet, an interior angle of 8 "
    "degrees 40 minutes 30 seconds, chord bearing South 21 degrees 46 minutes 50 "
    "seconds East 611.06 feet; thence South 66 degrees 15 minutes 33 seconds West "
    "692.41 feet; thence South 74 degrees 32 minutes 14 seconds West 294.02 feet; "
    "thence South 87 degrees 18 minutes 53 seconds West 77.58 feet; thence North 02 "
    "degrees 08 minutes 34 seconds West 532.02 feet to the point of beginning."
)


# ===========================================================================
# detect_parcel_markers tests
# ===========================================================================


class TestDetectParcelMarkers:
    """Tests for detect_parcel_markers()."""

    def test_detects_parcel_a_and_b_lettered(self) -> None:
        """Detect 'Parcel A' and 'Parcel B' markers in sample text."""
        markers = detect_parcel_markers(MULTI_PARCEL_TEXT)
        labels = [m["label"] for m in markers]
        assert "Parcel A" in labels
        assert "Parcel B" in labels

    def test_detects_combined_description_marker(self) -> None:
        """Detect 'Combine Legal Description' marker in sample text."""
        markers = detect_parcel_markers(MULTI_PARCEL_TEXT)
        labels = [m["label"] for m in markers]
        # The ground truth says "Combine Legal Description:" (without 'd')
        assert any("combine" in label.lower() or "combined" in label.lower() for label in labels)

    def test_marker_positions_are_ascending(self) -> None:
        """Markers should appear in ascending position order."""
        markers = detect_parcel_markers(MULTI_PARCEL_TEXT)
        positions = [m["position"] for m in markers]
        assert positions == sorted(positions)

    def test_marker_types_are_lettered(self) -> None:
        """Parcel A/B markers should have marker_type 'lettered'."""
        markers = detect_parcel_markers(MULTI_PARCEL_TEXT)
        lettered = [m for m in markers if m["label"] in ("Parcel A", "Parcel B")]
        assert len(lettered) == 2
        for m in lettered:
            assert m["marker_type"] == "lettered"

    def test_combined_marker_type(self) -> None:
        """Combined Legal Description markers should have marker_type 'combined'."""
        markers = detect_parcel_markers(MULTI_PARCEL_TEXT)
        combined = [m for m in markers if "combine" in m["label"].lower()]
        assert len(combined) == 1
        assert combined[0]["marker_type"] == "combined"

    def test_numbered_parcels(self) -> None:
        """Detect 'Parcel 1:', 'Parcel 2:' numbered markers."""
        text = (
            "Legal description follows:\n"
            "Parcel 1: Lot 1, Block 2.\n"
            "Parcel 2: Lot 3, Block 4.\n"
            "Parcel 3: Lot 5, Block 6."
        )
        markers = detect_parcel_markers(text)
        labels = [m["label"] for m in markers]
        assert "Parcel 1" in labels
        assert "Parcel 2" in labels
        assert "Parcel 3" in labels
        for m in markers:
            assert m["marker_type"] == "numbered"

    def test_dash_separated_parcels(self) -> None:
        """Detect 'PARCEL A -' and 'PARCEL B -' markers."""
        text = "PARCEL A - Description of first parcel.\nPARCEL B - Description of second parcel."
        markers = detect_parcel_markers(text)
        labels = [m["label"] for m in markers]
        assert "Parcel A" in labels or "PARCEL A" in labels
        assert "Parcel B" in labels or "PARCEL B" in labels

    def test_also_marker(self) -> None:
        """Detect 'ALSO:' as parcel marker."""
        text = "Description of first parcel.\nALSO: Description of second parcel."
        markers = detect_parcel_markers(text)
        labels = [m["label"] for m in markers]
        assert any("also" in label.lower() for label in labels)

    def test_also_described_as_marker(self) -> None:
        """Detect 'ALSO DESCRIBED AS:' as parcel marker."""
        text = "Description of first parcel.\nALSO DESCRIBED AS: Second description."
        markers = detect_parcel_markers(text)
        labels = [m["label"] for m in markers]
        assert any("also" in label.lower() for label in labels)

    def test_together_with_marker(self) -> None:
        """Detect 'TOGETHER WITH:' as appurtenant parcel marker."""
        text = "Main parcel description.\nTOGETHER WITH: an easement over..."
        markers = detect_parcel_markers(text)
        labels = [m["label"] for m in markers]
        assert any("together" in label.lower() for label in labels)

    def test_no_markers_returns_empty(self) -> None:
        """Text with no parcel markers returns an empty list."""
        text = "A single parcel beginning at the NW corner thence S 45 degrees E 100 feet."
        markers = detect_parcel_markers(text)
        assert markers == []

    def test_case_insensitivity(self) -> None:
        """Markers should be detected regardless of case."""
        text = "parcel a: First parcel.\nPARCEL B: Second parcel.\nParcel C: Third parcel."
        markers = detect_parcel_markers(text)
        assert len(markers) == 3

    def test_combined_legal_description_with_d(self) -> None:
        """Detect 'Combined Legal Description:' (with the 'd')."""
        text = "Parcel A: First.\nParcel B: Second.\nCombined Legal Description: Aggregate."
        markers = detect_parcel_markers(text)
        labels = [m["label"] for m in markers]
        assert any("combined" in label.lower() or "combine" in label.lower() for label in labels)

    def test_three_markers_in_sample(self) -> None:
        """The sample text should produce exactly 3 markers."""
        markers = detect_parcel_markers(MULTI_PARCEL_TEXT)
        assert len(markers) == 3


# ===========================================================================
# split_into_parcels tests
# ===========================================================================


class TestSplitIntoParcels:
    """Tests for split_into_parcels()."""

    def test_sample_splits_into_three_parcels(self) -> None:
        """The sample deed should split into 3 parcels."""
        parcels = split_into_parcels(MULTI_PARCEL_TEXT)
        assert len(parcels) == 3

    def test_sample_parcel_labels(self) -> None:
        """The sample parcels should have correct labels."""
        parcels = split_into_parcels(MULTI_PARCEL_TEXT)
        labels = [p["label"] for p in parcels]
        assert labels[0] == "Parcel A"
        assert labels[1] == "Parcel B"
        # "Combine Legal Description" or "Combined Legal Description"
        assert "combine" in labels[2].lower() or "combined" in labels[2].lower()

    def test_sample_parcel_types(self) -> None:
        """The sample parcels A and B are primary, combined is combined."""
        parcels = split_into_parcels(MULTI_PARCEL_TEXT)
        assert parcels[0]["parcel_type"] == "primary"
        assert parcels[1]["parcel_type"] == "primary"
        assert parcels[2]["parcel_type"] == "combined"

    def test_sample_parcel_a_contains_point_of_beginning(self) -> None:
        """Parcel A text should contain 'point of beginning'."""
        parcels = split_into_parcels(MULTI_PARCEL_TEXT)
        parcel_a = parcels[0]
        assert "point of beginning" in parcel_a["text"].lower()

    def test_sample_parcel_b_contains_point_of_beginning(self) -> None:
        """Parcel B text should contain 'point of beginning'."""
        parcels = split_into_parcels(MULTI_PARCEL_TEXT)
        parcel_b = parcels[1]
        assert "point of beginning" in parcel_b["text"].lower()

    def test_sample_combined_contains_point_of_beginning(self) -> None:
        """Combined parcel text should contain 'point of beginning'."""
        parcels = split_into_parcels(MULTI_PARCEL_TEXT)
        combined = parcels[2]
        assert "point of beginning" in combined["text"].lower()

    def test_sample_parcel_a_mentions_640(self) -> None:
        """Parcel A uses 640.19 feet in its commencing clause."""
        parcels = split_into_parcels(MULTI_PARCEL_TEXT)
        assert "640.19" in parcels[0]["text"]

    def test_sample_parcel_b_mentions_574(self) -> None:
        """Parcel B uses 574.17 feet in its commencing clause."""
        parcels = split_into_parcels(MULTI_PARCEL_TEXT)
        assert "574.17" in parcels[1]["text"]

    def test_sample_parcels_do_not_overlap(self) -> None:
        """No parcel text should contain content from another parcel's unique data."""
        parcels = split_into_parcels(MULTI_PARCEL_TEXT)
        # Parcel A has "640.19" but Parcel B should not
        assert "640.19" not in parcels[1]["text"]
        assert "640.19" not in parcels[2]["text"]

    def test_single_parcel_returns_one_entry(self) -> None:
        """Text without parcel markers returns a single parcel."""
        text = (
            "A parcel of land beginning at the NW corner thence S 45 degrees "
            "E 100 feet to the point of beginning."
        )
        parcels = split_into_parcels(text)
        assert len(parcels) == 1
        assert parcels[0]["label"] == "Parcel 1"
        assert parcels[0]["parcel_type"] == "primary"
        assert parcels[0]["text"] == text

    def test_numbered_parcels(self) -> None:
        """Numbered parcels (Parcel 1:, Parcel 2:) are split correctly."""
        text = (
            "Legal description:\n"
            "Parcel 1: Beginning at the NW corner thence South 100 feet.\n"
            "Parcel 2: Beginning at the SW corner thence East 200 feet."
        )
        parcels = split_into_parcels(text)
        assert len(parcels) == 2
        assert parcels[0]["label"] == "Parcel 1"
        assert parcels[1]["label"] == "Parcel 2"

    def test_also_creates_additional_parcel(self) -> None:
        """'ALSO:' creates an additional parcel with 'additional' type."""
        text = (
            "A parcel beginning at the NW corner thence South 100 feet.\n"
            "ALSO: A second parcel beginning at the SW corner."
        )
        parcels = split_into_parcels(text)
        assert len(parcels) == 2
        also_parcel = [p for p in parcels if "also" in p["label"].lower()]
        assert len(also_parcel) == 1
        assert also_parcel[0]["parcel_type"] == "additional"

    def test_together_with_creates_appurtenant_parcel(self) -> None:
        """'TOGETHER WITH:' creates an appurtenant parcel."""
        text = "Main parcel description here.\nTOGETHER WITH: an easement for ingress and egress."
        parcels = split_into_parcels(text)
        assert len(parcels) == 2
        tw_parcel = [p for p in parcels if "together" in p["label"].lower()]
        assert len(tw_parcel) == 1
        assert tw_parcel[0]["parcel_type"] == "appurtenant"

    def test_case_insensitive_splitting(self) -> None:
        """Splitting works regardless of case."""
        text = "parcel a: First parcel text.\nparcel b: Second parcel text."
        parcels = split_into_parcels(text)
        assert len(parcels) == 2

    def test_empty_text_returns_single_empty_parcel(self) -> None:
        """Empty text returns a single parcel with the empty string."""
        parcels = split_into_parcels("")
        assert len(parcels) == 1
        assert parcels[0]["text"] == ""

    def test_parcel_text_is_stripped(self) -> None:
        """Parcel text should be stripped of leading/trailing whitespace."""
        text = "Parcel A:   Lots of space here.   \nParcel B:   More space here.   "
        parcels = split_into_parcels(text)
        for p in parcels:
            assert p["text"] == p["text"].strip()

    def test_sample_combined_has_611_64(self) -> None:
        """Combined description has the aggregate curve (611.64 feet) not found in A or B."""
        parcels = split_into_parcels(MULTI_PARCEL_TEXT)
        combined = parcels[2]
        assert "611.64" in combined["text"]
        # 611.64 should NOT be in Parcel A or B
        assert "611.64" not in parcels[0]["text"]
        assert "611.64" not in parcels[1]["text"]

    def test_dash_separated_splitting(self) -> None:
        """PARCEL A - and PARCEL B - delimiters work."""
        text = "PARCEL A - First lot described here.\nPARCEL B - Second lot described here."
        parcels = split_into_parcels(text)
        assert len(parcels) == 2

    def test_parcel_dict_keys(self) -> None:
        """Each parcel dict has the expected keys."""
        parcels = split_into_parcels(MULTI_PARCEL_TEXT)
        for p in parcels:
            assert "label" in p
            assert "text" in p
            assert "parcel_type" in p
