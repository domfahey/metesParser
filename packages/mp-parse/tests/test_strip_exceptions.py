"""Tests for strip exception detection and removal in mp_parse.metadata.

Strip exceptions are uniform-width exclusions like "except the East 20 feet
deeded for roadway" that should NOT be parsed as metes-and-bounds traverse
calls.  They describe area deductions, not surveyed courses.

TDD: tests written first, then implementation in metadata.py.
"""

from __future__ import annotations


class TestDetectStripExceptions:
    """detect_strip_exceptions(text) returns structured data for each strip."""

    def test_except_east_20_feet_roadway(self) -> None:
        """Deed 50512-00525: 'except the East 20 feet deeded for roadway'."""
        from mp_parse.metadata import detect_strip_exceptions

        text = (
            "thence North 89 degrees 48 minutes 45 seconds East, 214 feet "
            "along a line parallel to the South line of said Section 13 to "
            "a point of beginning, except the East 20 feet deeded for roadway."
        )
        result = detect_strip_exceptions(text)
        assert len(result) == 1
        strip = result[0]
        assert strip["direction"] == "East"
        assert strip["width_ft"] == 20.0
        assert strip["purpose"] == "roadway"
        assert "except the East 20 feet deeded for roadway" in strip["original_text"]

    def test_except_south_30_feet_thereof(self) -> None:
        """Deed 50795-01269: 'except the South 30 feet thereof'."""
        from mp_parse.metadata import detect_strip_exceptions

        text = (
            "thence South 2 degrees 56 minutes 20 seconds East 324.0 feet "
            "to the Point of Beginning, except the South 30 feet thereof."
        )
        result = detect_strip_exceptions(text)
        assert len(result) == 1
        strip = result[0]
        assert strip["direction"] == "South"
        assert strip["width_ft"] == 30.0
        assert strip["original_text"] is not None

    def test_subject_to_easement_west_30_feet(self) -> None:
        """Deed 50872: 'Subject to an Easement for Private Road Purposes over the West 30 Feet thereof'."""
        from mp_parse.metadata import detect_strip_exceptions

        text = (
            "due North 120.59 feet to the Point of Beginning. "
            "Subject to an Easement for Private Road Purposes over the West 30 Feet thereof."
        )
        result = detect_strip_exceptions(text)
        assert len(result) == 1
        strip = result[0]
        assert strip["direction"] == "West"
        assert strip["width_ft"] == 30.0
        assert "easement" in strip["purpose"].lower() or "road" in strip["purpose"].lower()

    def test_less_and_except(self) -> None:
        """'LESS AND EXCEPT the North 15 feet thereof'."""
        from mp_parse.metadata import detect_strip_exceptions

        text = "to the point of beginning, LESS AND EXCEPT the North 15 feet thereof."
        result = detect_strip_exceptions(text)
        assert len(result) == 1
        strip = result[0]
        assert strip["direction"] == "North"
        assert strip["width_ft"] == 15.0

    def test_excepting_therefrom(self) -> None:
        """'excepting therefrom the West 25 feet'."""
        from mp_parse.metadata import detect_strip_exceptions

        text = "to the point of beginning, excepting therefrom the West 25 feet."
        result = detect_strip_exceptions(text)
        assert len(result) == 1
        strip = result[0]
        assert strip["direction"] == "West"
        assert strip["width_ft"] == 25.0

    def test_case_insensitivity(self) -> None:
        """Pattern matching should be case-insensitive."""
        from mp_parse.metadata import detect_strip_exceptions

        text = "EXCEPT THE EAST 20 FEET DEEDED FOR ROADWAY."
        result = detect_strip_exceptions(text)
        assert len(result) == 1
        assert result[0]["direction"] == "East"
        assert result[0]["width_ft"] == 20.0

    def test_no_strip_exception_in_normal_text(self) -> None:
        """Regular metes-and-bounds calls should NOT be detected as strips."""
        from mp_parse.metadata import detect_strip_exceptions

        text = (
            "thence North 00 degrees 04 minutes West 80 feet to a point; "
            "thence South 89 degrees 48 minutes West 214 feet to a point"
        )
        result = detect_strip_exceptions(text)
        assert result == []

    def test_regular_exception_with_metes_calls_not_detected(self) -> None:
        """Exception clauses containing full metes calls should NOT be stripped.

        Only simple uniform-width strips (no bearing + distance traverse
        calls inside the exception) should be detected.
        """
        from mp_parse.metadata import detect_strip_exceptions

        text = (
            "EXCEPT BEGINNING at the NE corner; thence South 45 degrees "
            "East 100 feet; thence South 45 degrees West 100 feet; thence "
            "North 45 degrees West 100 feet; thence North 45 degrees East "
            "100 feet to the point of beginning."
        )
        result = detect_strip_exceptions(text)
        assert result == []

    def test_multiple_strip_exceptions(self) -> None:
        """Multiple strip exceptions in a single text."""
        from mp_parse.metadata import detect_strip_exceptions

        text = (
            "to the point of beginning, except the East 20 feet deeded for "
            "roadway and except the North 10 feet thereof."
        )
        result = detect_strip_exceptions(text)
        assert len(result) == 2
        directions = {s["direction"] for s in result}
        assert directions == {"East", "North"}

    def test_empty_text(self) -> None:
        """Empty string returns empty list."""
        from mp_parse.metadata import detect_strip_exceptions

        assert detect_strip_exceptions("") == []

    def test_abbreviated_direction(self) -> None:
        """Abbreviated cardinal directions like N, S, E, W."""
        from mp_parse.metadata import detect_strip_exceptions

        text = "except the E 20 feet deeded for roadway."
        result = detect_strip_exceptions(text)
        assert len(result) == 1
        assert result[0]["direction"] == "East"
        assert result[0]["width_ft"] == 20.0

    def test_ft_abbreviation(self) -> None:
        """'ft' abbreviation instead of 'feet'."""
        from mp_parse.metadata import detect_strip_exceptions

        text = "except the South 30 ft thereof."
        result = detect_strip_exceptions(text)
        assert len(result) == 1
        assert result[0]["width_ft"] == 30.0

    def test_decimal_width(self) -> None:
        """Decimal width like '20.5 feet'."""
        from mp_parse.metadata import detect_strip_exceptions

        text = "except the East 20.5 feet thereof."
        result = detect_strip_exceptions(text)
        assert len(result) == 1
        assert result[0]["width_ft"] == 20.5

    def test_purpose_extraction_for_roadway(self) -> None:
        """Purpose field captures 'roadway' when stated."""
        from mp_parse.metadata import detect_strip_exceptions

        text = "except the East 20 feet deeded for roadway."
        result = detect_strip_exceptions(text)
        assert len(result) == 1
        assert result[0]["purpose"] is not None
        assert "roadway" in result[0]["purpose"].lower()

    def test_purpose_none_when_not_stated(self) -> None:
        """Purpose is None when no reason given (e.g., 'thereof')."""
        from mp_parse.metadata import detect_strip_exceptions

        text = "except the South 30 feet thereof."
        result = detect_strip_exceptions(text)
        assert len(result) == 1
        assert result[0]["purpose"] is None

    def test_full_legal_50512(self) -> None:
        """Full legal description from deed 50512-00525 ground truth."""
        from mp_parse.metadata import detect_strip_exceptions

        text = (
            "Beginning at a point being North 00 degrees 04 minutes West, "
            "1042 feet from the Southeast corner of Section 13, Town 1 South, "
            "Range 9 East, City of Sampleton, Sample County, Michigan; thence "
            "North 00 degrees 04 minutes West, 80 feet to a point; thence "
            "South 89 degrees 48 minutes 45 seconds West, 214 feet along "
            "a line parallel to the South line of said Section 13 to a point; "
            "thence South 00 degrees 04 minutes East, 80 feet to a point; "
            "thence North 89 degrees 48 minutes 45 seconds East, 214 feet "
            "along a line parallel to the South line of said Section 13 to "
            "a point of beginning, except the East 20 feet deeded for roadway."
        )
        result = detect_strip_exceptions(text)
        assert len(result) == 1
        assert result[0]["direction"] == "East"
        assert result[0]["width_ft"] == 20.0

    def test_full_legal_50795(self) -> None:
        """Full legal description from deed 50795-01269 ground truth."""
        from mp_parse.metadata import detect_strip_exceptions

        text = (
            "That part of the Northeast 1/4 of Section 16, described as: "
            "Beginning at a point distant North 2 degrees 56 minutes 20 seconds "
            "West 955.85 feet along the East line of Section and South 87 degrees "
            "03 minutes West 1782.0 feet from the East 1/4 corner of Section 16, "
            "and proceeding thence South 87 degrees 03 minutes 40 seconds West "
            "138.0 feet; thence North 2 degrees 56 minutes 20 seconds West 324.0 "
            "feet; thence North 87 degrees 03 minutes 40 seconds East 138.0 feet; "
            "thence South 2 degrees 56 minutes 20 seconds East 324.0 feet to the "
            "Point of Beginning, except the South 30 feet thereof."
        )
        result = detect_strip_exceptions(text)
        assert len(result) == 1
        assert result[0]["direction"] == "South"
        assert result[0]["width_ft"] == 30.0


class TestRemoveStripExceptions:
    """remove_strip_exceptions(text) returns cleaned text with strips removed."""

    def test_removes_except_east_20_feet(self) -> None:
        """Strip exception text is removed, leaving clean legal description."""
        from mp_parse.metadata import remove_strip_exceptions

        text = (
            "thence North 89 degrees 48 minutes 45 seconds East, 214 feet "
            "to a point of beginning, except the East 20 feet deeded for roadway."
        )
        result = remove_strip_exceptions(text)
        assert "except the East 20 feet" not in result.lower()
        assert "214 feet" in result

    def test_removes_except_south_30_feet(self) -> None:
        from mp_parse.metadata import remove_strip_exceptions

        text = (
            "thence South 2 degrees 56 minutes 20 seconds East 324.0 feet "
            "to the Point of Beginning, except the South 30 feet thereof."
        )
        result = remove_strip_exceptions(text)
        assert "except the South 30 feet" not in result.lower()
        assert "324.0 feet" in result

    def test_removes_subject_to_easement(self) -> None:
        from mp_parse.metadata import remove_strip_exceptions

        text = (
            "due North 120.59 feet to the Point of Beginning. "
            "Subject to an Easement for Private Road Purposes over the West 30 Feet thereof."
        )
        result = remove_strip_exceptions(text)
        assert "West 30 Feet" not in result
        assert "120.59 feet" in result

    def test_removes_less_and_except(self) -> None:
        from mp_parse.metadata import remove_strip_exceptions

        text = "to the point of beginning, LESS AND EXCEPT the North 15 feet thereof."
        result = remove_strip_exceptions(text)
        assert "LESS AND EXCEPT" not in result
        assert "North 15 feet" not in result

    def test_preserves_text_without_strips(self) -> None:
        """Text without strip exceptions is returned unchanged (modulo whitespace)."""
        from mp_parse.metadata import remove_strip_exceptions

        text = "thence North 100 feet to an iron pin; thence East 50 feet to a stake."
        result = remove_strip_exceptions(text)
        assert "North 100 feet" in result
        assert "East 50 feet" in result

    def test_does_not_remove_metes_exception(self) -> None:
        """Exception clauses with full metes calls should NOT be removed."""
        from mp_parse.metadata import remove_strip_exceptions

        text = (
            "to the point of beginning. EXCEPT BEGINNING at the NE corner; "
            "thence South 45 degrees East 100 feet; thence South 45 degrees "
            "West 100 feet to the point of beginning."
        )
        result = remove_strip_exceptions(text)
        # The metes-based exception should still be present
        assert "EXCEPT" in result
        assert "South 45 degrees East 100 feet" in result

    def test_empty_text(self) -> None:
        from mp_parse.metadata import remove_strip_exceptions

        assert remove_strip_exceptions("") == ""

    def test_removes_excepting_therefrom(self) -> None:
        from mp_parse.metadata import remove_strip_exceptions

        text = "to the point of beginning, excepting therefrom the West 25 feet."
        result = remove_strip_exceptions(text)
        assert "West 25 feet" not in result

    def test_full_legal_50512_cleaned(self) -> None:
        """Full deed 50512-00525 legal description is cleaned correctly."""
        from mp_parse.metadata import remove_strip_exceptions

        text = (
            "Beginning at a point being North 00 degrees 04 minutes West, "
            "1042 feet from the Southeast corner of Section 13, Town 1 South, "
            "Range 9 East, City of Sampleton, Sample County, Michigan; thence "
            "North 00 degrees 04 minutes West, 80 feet to a point; thence "
            "South 89 degrees 48 minutes 45 seconds West, 214 feet along "
            "a line parallel to the South line of said Section 13 to a point; "
            "thence South 00 degrees 04 minutes East, 80 feet to a point; "
            "thence North 89 degrees 48 minutes 45 seconds East, 214 feet "
            "along a line parallel to the South line of said Section 13 to "
            "a point of beginning, except the East 20 feet deeded for roadway."
        )
        result = remove_strip_exceptions(text)
        assert "except the East 20 feet" not in result.lower()
        # All 4 actual traversal calls should remain
        assert "North 00 degrees 04 minutes West, 80 feet" in result
        assert "South 89 degrees 48 minutes 45 seconds West, 214 feet" in result
        assert "South 00 degrees 04 minutes East, 80 feet" in result
        assert "North 89 degrees 48 minutes 45 seconds East, 214 feet" in result

    def test_multiple_strip_removal(self) -> None:
        """Multiple strip exceptions are all removed."""
        from mp_parse.metadata import remove_strip_exceptions

        text = (
            "to the point of beginning, except the East 20 feet deeded for "
            "roadway and except the North 10 feet thereof."
        )
        result = remove_strip_exceptions(text)
        assert "East 20 feet" not in result
        assert "North 10 feet" not in result
