"""Tests for bearing_converter.py - Critical coordinate calculations."""

import math
from pathlib import Path

import pytest
from mp_models import (
    DESCRIPTION_ROLES_CHECK,
    DESCRIPTION_ROLES_NOTE,
    EASEMENT_TRACT_NOTE,
    EXCEPTION_TRACT_NOTE,
)

from metesparser.bearing_converter import BearingConverter
from metesparser.closure_checker import ClosureChecker
from metesparser.csv_builder import CSVBuilder
from metesparser.models import DeedCall, Point


class TestQuadrantParsing:
    """Test parsing of quadrant bearings from text."""

    def test_parse_nde_format(self):
        """Parse N 45° E format."""
        result = BearingConverter.parse_quadrant_bearing("N 45° E")
        assert result == ("N", 45.0, "E")

    def test_parse_with_minutes(self):
        """Parse N 45°30' E format."""
        result = BearingConverter.parse_quadrant_bearing("N 45°30' E")
        c1, deg, c2 = result
        assert c1 == "N"
        assert math.isclose(deg, 45.5, abs_tol=0.000001)
        assert c2 == "E"

    def test_parse_with_seconds(self):
        """Parse N 45°30'15\" E format."""
        result = BearingConverter.parse_quadrant_bearing("N 45°30'15\" E")
        c1, deg, c2 = result
        assert c1 == "N"
        assert math.isclose(deg, 45.504167, abs_tol=0.000001)
        assert c2 == "E"

    def test_parse_all_quadrants(self):
        """Parse all four quadrants."""
        assert BearingConverter.parse_quadrant_bearing("N 33°20' E") == (
            "N",
            pytest.approx(33 + 20 / 60, abs=1e-6),
            "E",
        )
        assert BearingConverter.parse_quadrant_bearing("S 56°40' W") == (
            "S",
            pytest.approx(56 + 40 / 60, abs=1e-6),
            "W",
        )
        assert BearingConverter.parse_quadrant_bearing("S 45° E") == ("S", 45.0, "E")
        assert BearingConverter.parse_quadrant_bearing("N 90° W") == ("N", 90.0, "W")

    def test_parse_no_minutes(self):
        """Parse bearing with no minutes/seconds."""
        result = BearingConverter.parse_quadrant_bearing("S 45° W")
        assert result == ("S", 45.0, "W")

    def test_parse_invalid_format(self):
        """Return None for invalid formats."""
        assert BearingConverter.parse_quadrant_bearing("North 45 East") is None
        assert BearingConverter.parse_quadrant_bearing("southwesterly") is None
        assert BearingConverter.parse_quadrant_bearing("") is None

    def test_parse_comma_between_minutes_and_seconds(self):
        """GPT-5 sometimes inserts comma between minutes and seconds."""
        result = BearingConverter.parse_quadrant_bearing("S 56°40', 00\" W")
        assert result is not None
        assert result[0] == "S"
        assert math.isclose(result[1], 56 + 40 / 60, abs_tol=1e-6)
        assert result[2] == "W"

    def test_parse_comma_no_space_between_minutes_and_seconds(self):
        """Comma without space between minutes and seconds."""
        result = BearingConverter.parse_quadrant_bearing("N 33°20',00\" W")
        assert result is not None
        assert result[0] == "N"
        assert math.isclose(result[1], 33 + 20 / 60, abs_tol=1e-6)
        assert result[2] == "W"


class TestQuadrantToAzimuth:
    """Test quadrant bearing to azimuth conversion."""

    def test_ne_quadrant(self):
        """N θ E → azimuth = θ."""
        azimuth = BearingConverter.quadrant_to_azimuth("N", 45.0, "E")
        assert azimuth == 45.0

        azimuth = BearingConverter.quadrant_to_azimuth("N", 33.333333, "E")
        assert math.isclose(azimuth, 33.333333, abs_tol=0.000001)

    def test_se_quadrant(self):
        """S θ E → azimuth = 180 - θ."""
        azimuth = BearingConverter.quadrant_to_azimuth("S", 45.0, "E")
        assert azimuth == 135.0

        azimuth = BearingConverter.quadrant_to_azimuth("S", 56.666667, "E")
        assert math.isclose(azimuth, 123.333333, abs_tol=0.000001)

    def test_sw_quadrant(self):
        """S θ W → azimuth = 180 + θ."""
        azimuth = BearingConverter.quadrant_to_azimuth("S", 45.0, "W")
        assert azimuth == 225.0

        azimuth = BearingConverter.quadrant_to_azimuth("S", 56.666667, "W")
        assert math.isclose(azimuth, 236.666667, abs_tol=0.000001)

    def test_nw_quadrant(self):
        """N θ W → azimuth = 360 - θ."""
        azimuth = BearingConverter.quadrant_to_azimuth("N", 45.0, "W")
        assert azimuth == 315.0

        azimuth = BearingConverter.quadrant_to_azimuth("N", 33.333333, "W")
        assert math.isclose(azimuth, 326.666667, abs_tol=0.000001)

    def test_cardinal_directions(self):
        """Test exact cardinal directions."""
        assert BearingConverter.quadrant_to_azimuth("N", 0.0, "E") == 0.0
        assert BearingConverter.quadrant_to_azimuth("N", 90.0, "E") == 90.0
        assert BearingConverter.quadrant_to_azimuth("S", 0.0, "E") == 180.0
        assert BearingConverter.quadrant_to_azimuth("N", 90.0, "W") == 270.0

    def test_modulo_360(self):
        """Azimuth should wrap around at 360°."""
        azimuth = BearingConverter.quadrant_to_azimuth("N", 0.0, "W")
        assert azimuth == 0.0


class TestDeltaCalculations:
    """Test dx, dy calculations for traverse."""

    def test_north_bearing(self):
        """0° (North) → dx=0, dy=distance."""
        dx, dy = BearingConverter.calculate_deltas(0.0, 100.0)
        assert math.isclose(dx, 0.0, abs_tol=0.000001)
        assert math.isclose(dy, 100.0, abs_tol=0.000001)

    def test_east_bearing(self):
        """90° (East) → dx=distance, dy=0."""
        dx, dy = BearingConverter.calculate_deltas(90.0, 100.0)
        assert math.isclose(dx, 100.0, abs_tol=0.000001)
        assert math.isclose(dy, 0.0, abs_tol=0.000001)

    def test_south_bearing(self):
        """180° (South) → dx=0, dy=-distance."""
        dx, dy = BearingConverter.calculate_deltas(180.0, 100.0)
        assert math.isclose(dx, 0.0, abs_tol=0.000001)
        assert math.isclose(dy, -100.0, abs_tol=0.000001)

    def test_west_bearing(self):
        """270° (West) → dx=-distance, dy=0."""
        dx, dy = BearingConverter.calculate_deltas(270.0, 100.0)
        assert math.isclose(dx, -100.0, abs_tol=0.000001)
        assert math.isclose(dy, 0.0, abs_tol=0.000001)

    def test_ne_45_degrees(self):
        """45° (NE) → dx=dy=distance/√2."""
        dx, dy = BearingConverter.calculate_deltas(45.0, 100.0)
        expected = 100.0 / math.sqrt(2)
        assert math.isclose(dx, expected, abs_tol=0.000001)
        assert math.isclose(dy, expected, abs_tol=0.000001)

    def test_real_world_bearing(self):
        """Test N 33°20' E (33.333333°) for 60 ft."""
        azimuth = BearingConverter.quadrant_to_azimuth("N", 33.333333, "E")
        dx, dy = BearingConverter.calculate_deltas(azimuth, 60.0)
        assert math.isclose(dx, 32.970538, abs_tol=1e-4)
        assert math.isclose(dy, 50.129269, abs_tol=1e-4)


class TestCurveCalculations:
    """Test curve property calculations."""

    def test_arc_length_90_degree_curve(self):
        """L = R × Δ for 90° curve."""
        props = BearingConverter.calculate_curve_properties(100.0, delta_deg=90.0)
        expected = 100.0 * math.radians(90.0)
        assert math.isclose(props["arc_length_ft"], expected, abs_tol=1e-6)

    def test_arc_length_45_degree_curve(self):
        """L = R × Δ for 45° curve."""
        props = BearingConverter.calculate_curve_properties(100.0, delta_deg=45.0)
        expected = 100.0 * math.radians(45.0)
        assert math.isclose(props["arc_length_ft"], expected, abs_tol=1e-6)

    def test_chord_length_90_degree(self):
        """Chord = 2R × sin(Δ/2) for 90° curve."""
        props = BearingConverter.calculate_curve_properties(100.0, delta_deg=90.0)
        expected = 2 * 100.0 * math.sin(math.radians(90.0) / 2)
        assert math.isclose(props["chord_length_ft"], expected, abs_tol=1e-6)

    def test_chord_length_small_angle(self):
        """For small angles, chord ≈ arc."""
        radius = 1000.0
        delta = 1.0
        props = BearingConverter.calculate_curve_properties(radius, delta_deg=delta)
        chord = props["chord_length_ft"]
        arc = props["arc_length_ft"]
        assert abs(chord - arc) < 0.01

    def test_chord_bearing_left_curve(self):
        """Chord bearing = tangent - Δ/2 for left curve."""
        chord_az = BearingConverter.calculate_chord_bearing(90.0, 90.0, "left")
        assert math.isclose(chord_az, 45.0, abs_tol=0.000001)

    def test_chord_bearing_right_curve(self):
        """Chord bearing = tangent + Δ/2 for right curve."""
        chord_az = BearingConverter.calculate_chord_bearing(90.0, 90.0, "right")
        assert math.isclose(chord_az, 135.0, abs_tol=0.000001)

    def test_chord_bearing_wraps_at_360(self):
        """Chord bearing wraps correctly at 360°."""
        chord_az = BearingConverter.calculate_chord_bearing(10.0, 40.0, "left")
        assert math.isclose(chord_az, 350.0, abs_tol=0.000001)


class TestCurveEndpoint:
    """Test curve endpoint calculation."""

    def test_90_degree_left_curve_from_north(self):
        """90° left curve of radius 100 ft from North (0°) ends at (-100, +100)."""
        start = Point(x=0.0, y=0.0)
        endpoint = BearingConverter.compute_curve_endpoint(start, 0.0, 100.0, 90.0, "left")

        assert endpoint.x == pytest.approx(-100.0, abs=1e-6)
        assert endpoint.y == pytest.approx(100.0, abs=1e-6)

    def test_90_degree_right_curve_from_north(self):
        """90° right curve of radius 100 ft from North (0°) ends at (+100, +100)."""
        start = Point(x=0.0, y=0.0)
        endpoint = BearingConverter.compute_curve_endpoint(start, 0.0, 100.0, 90.0, "right")

        assert endpoint.x == pytest.approx(100.0, abs=1e-6)
        assert endpoint.y == pytest.approx(100.0, abs=1e-6)

    def test_180_degree_curve(self):
        """180° left curve of radius 50 ft from North ends at (-100, 0)."""
        start = Point(x=0.0, y=0.0)
        endpoint = BearingConverter.compute_curve_endpoint(start, 0.0, 50.0, 180.0, "left")

        assert endpoint.x == pytest.approx(-100.0, abs=1e-6)
        assert endpoint.y == pytest.approx(0.0, abs=1e-6)


class TestIntegrationQuadrantToDeltas:
    """Integration tests: quadrant bearing → azimuth → deltas."""

    def test_n33e_60ft(self):
        """N 33°20' E, 60.00 feet (from test parcel)."""
        parsed = BearingConverter.parse_quadrant_bearing("N 33°20' E")
        assert parsed is not None
        c1, decimal, c2 = parsed

        assert math.isclose(decimal, 33 + 20 / 60, abs_tol=1e-6)

        azimuth = BearingConverter.quadrant_to_azimuth(c1, decimal, c2)
        assert math.isclose(azimuth, 33 + 20 / 60, abs_tol=1e-6)

        dx, dy = BearingConverter.calculate_deltas(azimuth, 60.0)
        assert math.isclose(dx, 32.970539, abs_tol=1e-4)
        assert math.isclose(dy, 50.129269, abs_tol=1e-4)

    def test_s56w_125ft(self):
        """S 56°40' W, 125.00 feet (from test parcel)."""
        parsed = BearingConverter.parse_quadrant_bearing("S 56°40' W")
        assert parsed is not None
        c1, decimal, c2 = parsed

        assert math.isclose(decimal, 56 + 40 / 60, abs_tol=1e-6)

        azimuth = BearingConverter.quadrant_to_azimuth(c1, decimal, c2)
        assert math.isclose(azimuth, 236 + 40 / 60, abs_tol=1e-6)

        dx, dy = BearingConverter.calculate_deltas(azimuth, 125.0)
        assert math.isclose(dx, -104.435976, abs_tol=1e-4)
        assert math.isclose(dy, -68.688622, abs_tol=1e-4)


class TestBearingEdgeCasesAndEnrichment:
    """High-signal math and edge-case tests for BearingConverter."""

    @pytest.mark.parametrize("bearing", ["N 90°01' E", "S 90°00'01\" W"])
    def test_parse_quadrant_bearing_rejects_angles_over_90_degrees(self, bearing: str) -> None:
        assert BearingConverter.parse_quadrant_bearing(bearing) is None

    @pytest.mark.parametrize(
        ("c1", "c2"),
        [("E", "W"), ("N", "S"), ("E", "N"), ("X", "Y")],
    )
    def test_quadrant_to_azimuth_rejects_invalid_cardinal_combinations(
        self, c1: str, c2: str
    ) -> None:
        with pytest.raises(ValueError, match="Invalid cardinal combination"):
            BearingConverter.quadrant_to_azimuth(c1, 45.0, c2)

    @pytest.mark.parametrize(
        ("direction", "expected"),
        [
            ("due North", 0.0),
            ("due n", 0.0),
            ("Due EAST", 90.0),
            ("due E", 90.0),
            ("due South", 180.0),
            ("DUE S", 180.0),
            ("due West", 270.0),
            ("  due w  ", 270.0),
            ("North", None),
            ("due northwest", None),
            ("southwesterly", None),
            ("", None),
        ],
    )
    def test_due_cardinal_to_azimuth(self, direction: str, expected: float | None) -> None:
        assert BearingConverter.due_cardinal_to_azimuth(direction) == expected

    def test_bearing_to_azimuth_returns_none_for_unparseable_text(self) -> None:
        assert BearingConverter.bearing_to_azimuth("S 56°40'30\" W") == pytest.approx(236.675)
        assert BearingConverter.bearing_to_azimuth("southwesterly") is None
        assert BearingConverter.bearing_to_azimuth("N 90°01' E") is None

    @pytest.mark.parametrize(
        ("azimuth", "expected"),
        [
            (0.0, "N 0°00' E"),
            (45.5, "N 45°30' E"),
            (90.0, "N 90°00' E"),
            (135.0, "S 45°00' E"),
            (180.0, "S 0°00' E"),
            (225.0, "S 45°00' W"),
            (236.675, "S 56°40'30.0\" W"),
            (270.0, "S 90°00' W"),
            (315.0, "N 45°00' W"),
            (360.0, "N 0°00' E"),
            (-45.0, "N 45°00' W"),
            (405.0, "N 45°00' E"),
        ],
    )
    def test_azimuth_to_quadrant_all_quadrants_and_boundaries(
        self, azimuth: float, expected: str
    ) -> None:
        assert BearingConverter.azimuth_to_quadrant(azimuth) == expected

    @pytest.mark.parametrize("bad_azimuth", [True, float("nan"), float("inf"), float("-inf")])
    def test_azimuth_to_quadrant_rejects_non_finite_or_bool(self, bad_azimuth: float) -> None:
        with pytest.raises(ValueError, match="Azimuth must be finite"):
            BearingConverter.azimuth_to_quadrant(bad_azimuth)

    def test_enrich_call_with_azimuth_from_quadrant_and_due_cardinal(self) -> None:
        quad_call = DeedCall(
            course=1,
            direction_text="S 56°40'30\" W",
            bearing_quadrant="S 56°40'30\" W",
            distance_ft=100.0,
        )
        enriched = BearingConverter.enrich_call_with_azimuth(quad_call)
        assert enriched.bearing_azimuth_deg_from_north == pytest.approx(236.675)

        unparseable_quad = DeedCall(
            course=2,
            direction_text="southwesterly",
            bearing_quadrant="not a bearing",
            distance_ft=50.0,
        )
        assert BearingConverter.enrich_call_with_azimuth(unparseable_quad) is unparseable_quad

        due_with_incomplete_note = DeedCall(
            course=3,
            direction_text="due North",
            distance_ft=75.0,
            notes="incomplete bearing - cardinal only",
        )
        enriched_due = BearingConverter.enrich_call_with_azimuth(due_with_incomplete_note)
        assert enriched_due.bearing_azimuth_deg_from_north == 0.0
        assert enriched_due.notes is None

        due_with_other_note = DeedCall(
            course=4,
            direction_text="due East",
            distance_ft=80.0,
            notes="along highway",
        )
        enriched_other = BearingConverter.enrich_call_with_azimuth(due_with_other_note)
        assert enriched_other.bearing_azimuth_deg_from_north == 90.0
        assert enriched_other.notes == "along highway"

        cardinal_only = DeedCall(
            course=5,
            direction_text="southwesterly",
            distance_ft=60.0,
            notes="incomplete bearing - cardinal only",
        )
        assert BearingConverter.enrich_call_with_azimuth(cardinal_only) is cardinal_only

        already_populated = DeedCall(
            course=6,
            direction_text="N 45° E",
            bearing_quadrant="N 45° E",
            bearing_azimuth_deg_from_north=45.0,
            distance_ft=60.0,
        )
        assert BearingConverter.enrich_call_with_azimuth(already_populated) is already_populated

    @pytest.mark.parametrize(
        ("direction_text", "expected_azimuth", "note"),
        [
            ("due North", 0.0, "incomplete bearing - cardinal only"),
            ("due East", 90.0, "incomplete bearing"),
            ("due South", 180.0, "incomplete bearing - ambiguous decimal degrees"),
        ],
    )
    def test_enrich_due_cardinal_clears_only_incomplete_bearing_note(
        self, direction_text: str, expected_azimuth: float, note: str
    ) -> None:
        call = DeedCall(
            course=1,
            direction_text=direction_text,
            distance_ft=100.0,
            notes=note,
        )
        enriched = BearingConverter.enrich_call_with_azimuth(call)
        assert enriched.bearing_azimuth_deg_from_north == expected_azimuth
        assert enriched.notes is None

    @pytest.mark.parametrize(
        ("initial_notes", "expected_notes"),
        [
            (
                f"incomplete bearing - cardinal only; {DESCRIPTION_ROLES_NOTE}",
                DESCRIPTION_ROLES_NOTE,
            ),
            (
                f"{DESCRIPTION_ROLES_NOTE}; incomplete bearing - cardinal only",
                DESCRIPTION_ROLES_NOTE,
            ),
            (
                f"incomplete bearing - cardinal only; {EASEMENT_TRACT_NOTE}",
                EASEMENT_TRACT_NOTE,
            ),
            (
                f"incomplete bearing - cardinal only; {EXCEPTION_TRACT_NOTE}",
                EXCEPTION_TRACT_NOTE,
            ),
            (
                "meander / approximate; incomplete bearing - cardinal only; "
                "record call: (deed N 44° E; 99 feet)",
                "meander / approximate; record call: (deed N 44° E; 99 feet)",
            ),
            (
                "along incomplete fence line",
                "along incomplete fence line",
            ),
        ],
    )
    def test_enrich_due_cardinal_preserves_blocking_and_verbatim_notes(
        self, initial_notes: str, expected_notes: str
    ) -> None:
        call = DeedCall(
            course=1,
            direction_text="due North",
            distance_ft=100.0,
            notes=initial_notes,
        )
        enriched = BearingConverter.enrich_call_with_azimuth(call)
        assert enriched.bearing_azimuth_deg_from_north == 0.0
        assert enriched.notes == expected_notes

    def test_enrich_due_cardinal_preserves_role_gate_through_closure_and_export(
        self, tmp_path: Path
    ) -> None:
        calls = [
            DeedCall(
                course=1,
                direction_text="due North",
                distance_ft=100.0,
                notes=f"incomplete bearing - cardinal only; {DESCRIPTION_ROLES_NOTE}",
            ),
            DeedCall(
                course=2,
                direction_text="due East",
                distance_ft=100.0,
                notes=DESCRIPTION_ROLES_NOTE,
            ),
            DeedCall(
                course=3,
                direction_text="due South",
                distance_ft=100.0,
                notes=DESCRIPTION_ROLES_NOTE,
            ),
            DeedCall(
                course=4,
                direction_text="due West",
                distance_ft=100.0,
                notes=DESCRIPTION_ROLES_NOTE,
            ),
        ]

        enriched_calls = [BearingConverter.enrich_call_with_azimuth(call) for call in calls]
        assert enriched_calls[0].bearing_azimuth_deg_from_north == 0.0
        assert enriched_calls[0].notes == DESCRIPTION_ROLES_NOTE

        result = ClosureChecker.verify_closure(enriched_calls)
        assert result.closure_passed is True
        assert result.is_fully_verified() is False
        assert result.geometry_verified is False
        role_checks = [c for c in result.checks if c.name == DESCRIPTION_ROLES_CHECK]
        assert len(role_checks) == 1
        assert role_checks[0].status == "blocked"
        assert role_checks[0].reason == "roles_need_review"

        with pytest.raises(
            ValueError,
            match="Cannot export verified CSV:.*description roles need review",
        ):
            CSVBuilder.export_verified_csv(
                enriched_calls,
                result,
                str(tmp_path / "out.csv"),
            )
