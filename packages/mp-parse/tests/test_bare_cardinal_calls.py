"""Tests for bare cardinal + distance normalization (MIWAYN-50058-00465).

Bare cardinal patterns like "thence S 289.81 feet" (no degree notation)
should be normalized to "thence due South 289.81 feet" so the existing
due-cardinal extraction logic in calls.py can handle them.

Also tests `&` and `and` as call separators between bearings.
"""

from __future__ import annotations

from mp_parse.calls import extract_calls
from mp_parse.normalizer import (
    expand_assessor_abbreviations,
    normalize_legal_description,
)


class TestBareCardinalNormalization:
    """expand_assessor_abbreviations() converts bare cardinal+distance to due cardinal."""

    def test_thence_s_distance(self) -> None:
        """'thence S 289.81 feet' -> 'thence due South 289.81 feet'."""
        result = expand_assessor_abbreviations("thence S 289.81 feet")
        assert "due South" in result
        assert "289.81" in result

    def test_thence_w_distance(self) -> None:
        """'thence W 199.44 feet' -> 'thence due West 199.44 feet'."""
        result = expand_assessor_abbreviations("thence W 199.44 feet")
        assert "due West" in result
        assert "199.44" in result

    def test_thence_n_distance(self) -> None:
        """'thence N 45.00 feet' -> 'thence due North 45.00 feet'."""
        result = expand_assessor_abbreviations("thence N 45.00 feet")
        assert "due North" in result
        assert "45.00" in result

    def test_thence_e_distance(self) -> None:
        """'thence E 100.50 feet' -> 'thence due East 100.50 feet'."""
        result = expand_assessor_abbreviations("thence E 100.50 feet")
        assert "due East" in result
        assert "100.50" in result

    def test_thence_south_word_distance(self) -> None:
        """'thence South 289.81 feet' -> 'thence due South 289.81 feet'."""
        result = expand_assessor_abbreviations("thence South 289.81 feet")
        assert "due South" in result
        assert "289.81" in result

    def test_thence_west_word_distance(self) -> None:
        """'thence West 199.44 feet' -> 'thence due West 199.44 feet'."""
        result = expand_assessor_abbreviations("thence West 199.44 feet")
        assert "due West" in result
        assert "199.44" in result

    def test_thence_north_word_distance(self) -> None:
        """'thence North 45.00 feet' -> 'thence due North 45.00 feet'."""
        result = expand_assessor_abbreviations("thence North 45.00 feet")
        assert "due North" in result
        assert "45.00" in result

    def test_thence_east_word_distance(self) -> None:
        """'thence East 100.50 feet' -> 'thence due East 100.50 feet'."""
        result = expand_assessor_abbreviations("thence East 100.50 feet")
        assert "due East" in result
        assert "100.50" in result

    def test_integer_distance(self) -> None:
        """'thence S 100 feet' -> 'thence due South 100 feet' (no decimal)."""
        result = expand_assessor_abbreviations("thence S 100 feet")
        assert "due South" in result
        assert "100" in result

    def test_no_unit_suffix(self) -> None:
        """'thence S 289.81' (no unit) should still be normalized."""
        result = expand_assessor_abbreviations("thence S 289.81")
        assert "due South" in result
        assert "289.81" in result


class TestBareCardinalNotFalsePositive:
    """Quadrant bearings with degree notation must NOT be modified."""

    def test_full_quadrant_bearing_unchanged(self) -> None:
        """'thence S 69° 53' 23\" W 82.00 feet' should NOT get 'due' inserted."""
        text = "thence S 69° 53' 23\" W 82.00 feet"
        result = expand_assessor_abbreviations(text)
        assert "due" not in result.lower()

    def test_nw_quadrant_bearing_unchanged(self) -> None:
        """'thence N 00° 32' 30\" W 128.78 feet' should NOT be modified."""
        text = "thence N 00° 32' 30\" W 128.78 feet"
        result = expand_assessor_abbreviations(text)
        assert "due" not in result.lower()

    def test_ne_quadrant_bearing_unchanged(self) -> None:
        """'thence N 15° 21' 23\" E 49.18 feet' should NOT be modified."""
        text = "thence N 15° 21' 23\" E 49.18 feet"
        result = expand_assessor_abbreviations(text)
        assert "due" not in result.lower()

    def test_bearing_with_degrees_word_unchanged(self) -> None:
        """'thence S 45 degrees 30 minutes E' should NOT be modified."""
        text = "thence S 45 degrees 30 minutes E 100 feet"
        result = expand_assessor_abbreviations(text)
        assert "due" not in result.lower()

    def test_northerly_unchanged(self) -> None:
        """Cardinal-ly directions like 'northerly' should not be touched."""
        text = "thence northerly 90 feet"
        result = expand_assessor_abbreviations(text)
        assert "due" not in result.lower()

    def test_southwesterly_unchanged(self) -> None:
        """Compound cardinals like 'southwesterly' should not be touched."""
        text = "thence southwesterly 50 feet"
        result = expand_assessor_abbreviations(text)
        assert "due" not in result.lower()


class TestAmpersandAndSeparator:
    """The `&` and `and` between bearings should be normalized to `thence`."""

    def test_ampersand_between_bearings(self) -> None:
        """'113.41 feet & N 69° 53' 23\" E 109.98 feet' -> inserts 'thence'."""
        text = "N 48° 03' 44\" E 113.41 feet & N 69° 53' 23\" E 109.98 feet"
        result = expand_assessor_abbreviations(text)
        assert "thence" in result.lower()

    def test_and_between_bearings(self) -> None:
        """'49.18 feet and N 48° 03' 44\" E 113.41 feet' -> inserts 'thence'."""
        text = "N 15° 21' 23\" E 49.18 feet and N 48° 03' 44\" E 113.41 feet"
        result = expand_assessor_abbreviations(text)
        # The 'and' should become 'thence' between the two bearings
        assert result.lower().count("thence") >= 1


class TestMIWAYN50058FullText:
    """Integration test: full MIWAYN-50058-00465 text should yield 7 calls."""

    FULL_TEXT = (
        "Commencing at the NE corner of Lot 13 of Newman Orchards a subdivision "
        "of part of the NW 36 of Sec. 19 and proceeding th. S 69° 53' 23\" W "
        "82.00 ft. to the POB, proceeding th. S 289.81 ft. th. W 199.44 ft. to "
        "a point on the easterly right of way line of Rawsonville Rd. th. along "
        "said line N 00° 32' 30\" W 128.78 ft. to a point on the southerly right "
        "of way line of the I-94 Expressway th. along said line N 15° 21' 23\" E "
        "49.18 ft. and N 48° 03' 44\" E. 113.41 ft. & N 69° 53' 23\" E 109.98 "
        "feet to the point of beginning"
    )

    def test_normalization_produces_thence_segments(self) -> None:
        """After normalization, there should be at least 7 'thence' occurrences."""
        result = normalize_legal_description(self.FULL_TEXT)
        thence_count = result.lower().count("thence")
        assert thence_count >= 7, (
            f"Expected >= 7 'thence' segments, got {thence_count}. Normalized text: {result}"
        )

    def test_extract_calls_yields_7(self) -> None:
        """extract_calls() should produce 7 calls from the full deed text."""
        calls, _tracts = extract_calls(self.FULL_TEXT)
        assert len(calls) == 7, (
            f"Expected 7 calls, got {len(calls)}: "
            f"{[(c.course, c.direction_text, c.distance_ft) for c in calls]}"
        )

    def test_bare_south_call_has_azimuth_180(self) -> None:
        """The bare 'S 289.81 ft' call should have azimuth 180.0 (due South)."""
        calls, _tracts = extract_calls(self.FULL_TEXT)
        south_calls = [
            c
            for c in calls
            if c.bearing_azimuth_deg_from_north is not None
            and abs(c.bearing_azimuth_deg_from_north - 180.0) < 0.01
        ]
        assert len(south_calls) >= 1, (
            f"Missing due South call. Calls: "
            f"{[(c.course, c.direction_text, c.bearing_azimuth_deg_from_north) for c in calls]}"
        )

    def test_bare_west_call_has_azimuth_270(self) -> None:
        """The bare 'W 199.44 ft' call should have azimuth 270.0 (due West)."""
        calls, _tracts = extract_calls(self.FULL_TEXT)
        west_calls = [
            c
            for c in calls
            if c.bearing_azimuth_deg_from_north is not None
            and abs(c.bearing_azimuth_deg_from_north - 270.0) < 0.01
        ]
        assert len(west_calls) >= 1, (
            f"Missing due West call. Calls: "
            f"{[(c.course, c.direction_text, c.bearing_azimuth_deg_from_north) for c in calls]}"
        )

    def test_last_call_closes_to_pob(self) -> None:
        """The final call should reference 'point of beginning'."""
        calls, _tracts = extract_calls(self.FULL_TEXT)
        assert len(calls) >= 1
        last = calls[-1]
        assert last.to is not None
        assert "beginning" in last.to.lower() or "pob" in last.to.lower()
