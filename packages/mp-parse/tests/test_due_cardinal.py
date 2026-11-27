"""Tests for 'due cardinal' bearing extraction and enrichment.

Three recorded deeds use 'due North', 'due South', 'due East',
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
        assert extract_direction("thence due North 120.59 feet") == "due north"

    def test_due_south(self) -> None:
        assert extract_direction("thence due South 599.89 feet") == "due south"

    def test_due_east(self) -> None:
        assert extract_direction("thence due East 256.40 feet") == "due east"

    def test_due_west(self) -> None:
        assert extract_direction("thence due west 134.64 feet") == "due west"


class TestExtractSingleCallDueCardinal:
    """extract_single_call() should produce a DeedCall with exact azimuth and no incomplete note."""

    @pytest.mark.parametrize(
        ("text", "expected_dist", "expected_az"),
        [
            ("due North 120.59 feet", 120.59, 0.0),
            ("due South 599.89 feet", 599.89, 180.0),
            ("due East 256.40 feet", 256.40, 90.0),
            ("due west 134.64 feet", 134.64, 270.0),
            ("DUE SOUTH 599.89 FT", 599.89, 180.0),
        ],
    )
    def test_due_cardinal_call_extracts_exact_azimuth_without_incomplete_note(
        self, text: str, expected_dist: float, expected_az: float
    ) -> None:
        call = extract_single_call(text, course=1)
        assert call is not None
        assert call.distance_ft == pytest.approx(expected_dist)
        assert call.bearing_azimuth_deg_from_north == pytest.approx(expected_az)
        assert call.notes is None

    def test_due_cardinal_direction_text_preserved(self) -> None:
        """The direction_text should reflect 'due North' rather than just 'north'."""
        call = extract_single_call("due North 120.59 feet", course=1)
        assert call is not None
        assert call.direction_text == "due north"


class TestExtractCallsDueCardinal:
    """extract_calls() should produce complete call lists for real due-cardinal deeds."""

    def test_deed_50233_4_calls(self) -> None:
        """Deed 50233-01191: 4 calls expected (was 2 -- due South/North dropped)."""
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
        assert len(due_south_calls) == 1, "Expected exactly 1 due South call"
        assert due_south_calls[0].distance_ft == pytest.approx(599.89)

        due_north_calls = [
            c for c in calls if c.bearing_azimuth_deg_from_north == pytest.approx(0.0)
        ]
        assert len(due_north_calls) == 1, "Expected exactly 1 due North call"
        assert due_north_calls[0].distance_ft == pytest.approx(599.89)

    def test_deed_50248_4_calls(self) -> None:
        """Deed 50248-00913: 4 calls expected (was 2 -- due west/East dropped)."""
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
        assert len(due_west_calls) == 1, "Expected exactly 1 due west call"
        assert due_west_calls[0].distance_ft == pytest.approx(134.64)

        due_east_calls = [
            c for c in calls if c.bearing_azimuth_deg_from_north == pytest.approx(90.0)
        ]
        assert len(due_east_calls) == 1, "Expected exactly 1 due East call"
        assert due_east_calls[0].distance_ft == pytest.approx(256.40)

    def test_deed_50872_4_calls_with_azimuth(self) -> None:
        """Deed 50872-00130: 4 calls, last one 'due North' must have azimuth 0.0."""
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
        assert last_call.notes is None


class TestEnrichCallsDueCardinal:
    """enrich_calls_with_azimuths() should enrich un-resolved due-cardinal calls."""

    def test_enrichment_adds_azimuth_and_clears_incomplete_note(self) -> None:
        from mp_models import DeedCall

        call = DeedCall(
            course=1,
            direction_text="due North",
            bearing_azimuth_deg_from_north=None,
            distance_ft=120.59,
            notes="incomplete bearing - cardinal only",
        )
        enriched = enrich_calls_with_azimuths([call])
        assert len(enriched) == 1
        assert enriched[0].bearing_azimuth_deg_from_north == pytest.approx(0.0)
        assert enriched[0].notes is None
