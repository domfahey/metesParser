"""Tests for 'due cardinal' bearing extraction and enrichment.

Three Wayne County MI deeds use 'due North', 'due South', 'due East',
'due West' bearings.  These must be:
  1. Recognized by extract_direction() as valid directions
  2. Extracted as calls by extract_single_call() / extract_calls()
  3. Enriched with correct azimuths by enrich_calls_with_azimuths()
  4. NOT flagged as 'incomplete bearing'
"""

from __future__ import annotations

import pytest
from mp_parse.calls import (
    enrich_calls_with_azimuths,
    extract_calls,
    extract_direction,
    extract_single_call,
)


class TestExtractDirectionDueCardinal:
    """extract_direction() should recognise 'due {cardinal}' as a direction."""

    def test_due_north(self) -> None:
        result = extract_direction("thence due North 120.59 feet")
        assert result is not None
        assert result != ""
        assert "north" in result.lower()

    def test_due_south(self) -> None:
        result = extract_direction("thence due South 599.89 feet")
        assert result is not None
        assert result != ""
        assert "south" in result.lower()

    def test_due_east(self) -> None:
        result = extract_direction("thence due East 256.40 feet")
        assert result is not None
        assert result != ""
        assert "east" in result.lower()

    def test_due_west(self) -> None:
        result = extract_direction("thence due west 134.64 feet")
        assert result is not None
        assert result != ""
        assert "west" in result.lower()


class TestExtractSingleCallDueCardinal:
    """extract_single_call() should produce a DeedCall with azimuth for due-cardinal bearings."""

    def test_due_north_call(self) -> None:
        call = extract_single_call("due North 120.59 feet", course=1)
        assert call is not None
        assert call.distance_ft == pytest.approx(120.59)
        assert call.bearing_azimuth_deg_from_north == pytest.approx(0.0)
        assert call.notes is None or "incomplete" not in (call.notes or "")

    def test_due_south_call(self) -> None:
        call = extract_single_call("due South 599.89 feet", course=1)
        assert call is not None
        assert call.distance_ft == pytest.approx(599.89)
        assert call.bearing_azimuth_deg_from_north == pytest.approx(180.0)
        assert call.notes is None or "incomplete" not in (call.notes or "")

    def test_due_east_call(self) -> None:
        call = extract_single_call("due East 256.40 feet", course=1)
        assert call is not None
        assert call.distance_ft == pytest.approx(256.40)
        assert call.bearing_azimuth_deg_from_north == pytest.approx(90.0)
        assert call.notes is None or "incomplete" not in (call.notes or "")

    def test_due_west_call(self) -> None:
        call = extract_single_call("due west 134.64 feet", course=1)
        assert call is not None
        assert call.distance_ft == pytest.approx(134.64)
        assert call.bearing_azimuth_deg_from_north == pytest.approx(270.0)
        assert call.notes is None or "incomplete" not in (call.notes or "")

    def test_due_south_with_feet(self) -> None:
        """Uppercase cardinal with abbreviated unit remains a complete due course."""
        call = extract_single_call("DUE SOUTH 599.89 FT", course=1)

        assert call is not None
        assert call.distance_ft == pytest.approx(599.89)
        assert call.bearing_azimuth_deg_from_north == pytest.approx(180.0)

    def test_due_cardinal_direction_text_preserved(self) -> None:
        """The direction_text should reflect 'due North' rather than just 'north'."""
        call = extract_single_call("due North 120.59 feet", course=1)
        assert call is not None
        assert call.direction_text == "due north"


class TestExtractCallsDueCardinal:
    """extract_calls() should produce complete call lists for real due-cardinal deeds."""

    def test_miwayn_50233_4_calls(self) -> None:
        """MIWAYN-50233-01191: 4 calls expected (was 2 -- due South/North dropped)."""
        text = (
            "beginning at a point on the North line of Section 14, "
            "distant North 89 degrees 20 minutes 37 seconds East 250.00 feet "
            "from the North 1/4 corner of Section 14, and proceeding "
            "thence along the North line of Section 14, "
            "North 89 degrees 20 minutes 37 seconds East 600.00 feet; "
            "thence due South 599.89 feet; "
            "thence South 89 degrees 20 minutes 37 seconds West 600.00 feet; "
            "thence due North 599.89 feet to the point of beginning"
        )
        calls, _tracts = extract_calls(text)
        assert len(calls) == 4, (
            f"Expected 4 calls, got {len(calls)}: {[c.direction_text for c in calls]}"
        )

        # Verify azimuths of the due-cardinal calls
        due_south_calls = [
            c for c in calls if c.bearing_azimuth_deg_from_north == pytest.approx(180.0)
        ]
        assert len(due_south_calls) >= 1, "Missing due South call"

        due_north_calls = [
            c for c in calls if c.bearing_azimuth_deg_from_north == pytest.approx(0.0)
        ]
        assert len(due_north_calls) >= 1, "Missing due North call"

    def test_miwayn_50248_4_calls(self) -> None:
        """MIWAYN-50248-00913: 4 calls expected (was 2 -- due west/East dropped)."""
        text = (
            "beginning at a point distant South 00 degrees 44 minutes 00 seconds West "
            "180.00 feet from the Northeast corner of Lot 206 and proceeding "
            "thence South 00 degrees 44 minutes 00 seconds West 213.00 feet; "
            "thence due west 134.64 feet; "
            "thence North 29 degrees 12 minutes 00 seconds West 243.98 feet; "
            "thence due East 256.40 feet to the point of beginning"
        )
        calls, _tracts = extract_calls(text)
        assert len(calls) == 4, (
            f"Expected 4 calls, got {len(calls)}: {[c.direction_text for c in calls]}"
        )

        due_west_calls = [
            c for c in calls if c.bearing_azimuth_deg_from_north == pytest.approx(270.0)
        ]
        assert len(due_west_calls) >= 1, "Missing due west call"

        due_east_calls = [
            c for c in calls if c.bearing_azimuth_deg_from_north == pytest.approx(90.0)
        ]
        assert len(due_east_calls) >= 1, "Missing due East call"

    def test_miwayn_50872_4_calls_with_azimuth(self) -> None:
        """MIWAYN-50872-00130: 4 calls, last one 'due North' must have azimuth 0.0."""
        text = (
            "thence South 89 degrees 58 minutes 45 seconds East 256.93 feet; "
            "thence South 0 degrees 03 minutes 15 seconds East 120.64 feet; "
            "thence along the Northerly line of J.F. Ferry Subdivision No. 2, "
            "North 89 degrees 58 minutes 00 seconds West 257.04 feet; "
            "thence along the center line of said Hubbell Ave., due North 120.59 feet "
            "to the Point of Beginning"
        )
        calls, _tracts = extract_calls(text)
        assert len(calls) == 4, (
            f"Expected 4 calls, got {len(calls)}: {[c.direction_text for c in calls]}"
        )

        last_call = calls[-1]
        assert last_call.bearing_azimuth_deg_from_north == pytest.approx(0.0)
        assert last_call.distance_ft == pytest.approx(120.59)
        assert last_call.notes is None or "incomplete" not in (last_call.notes or "")


class TestEnrichCallsDueCardinal:
    """enrich_calls_with_azimuths() should handle due-cardinal calls."""

    def test_enrichment_adds_azimuth_to_due_cardinal(self) -> None:
        """If extract_single_call already sets azimuth, enrichment should preserve it."""
        call = extract_single_call("due North 120.59 feet", course=1)
        assert call is not None
        enriched = enrich_calls_with_azimuths([call])
        assert len(enriched) == 1
        assert enriched[0].bearing_azimuth_deg_from_north == pytest.approx(0.0)


class TestDueCardinalNotIncomplete:
    """Due-cardinal bearings should NOT be flagged as 'incomplete bearing'."""

    @pytest.mark.parametrize(
        "text",
        [
            "due North 100.00 feet",
            "due South 200.00 feet",
            "due East 300.00 feet",
            "due West 400.00 feet",
        ],
    )
    def test_no_incomplete_note(self, text: str) -> None:
        call = extract_single_call(text, course=1)
        assert call is not None
        if call.notes:
            assert "incomplete" not in call.notes, f"Unexpected 'incomplete' note: {call.notes}"
