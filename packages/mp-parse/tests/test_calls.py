"""Tests for mp_parse.calls -- call extraction functions."""

from __future__ import annotations


class TestExtractCalls:
    def test_basic_four_sided_parcel(self) -> None:
        from mp_parse.calls import extract_calls

        text = (
            "BEGINNING at an iron pin; thence South 56 degrees 40 minutes West, "
            "150.00 feet to an iron pin; thence North 33 degrees 20 minutes West, "
            "125.00 feet to an iron pin; thence North 56 degrees 40 minutes East, "
            "150.00 feet to an iron pin; thence South 33 degrees 20 minutes East, "
            "125.00 feet to the POINT OF BEGINNING."
        )
        calls, _ = extract_calls(text)
        assert len(calls) >= 4
        assert calls[0].course == 1

    def test_course_numbers_sequential(self) -> None:
        from mp_parse.calls import extract_calls

        text = (
            "BEGINNING at an iron pin; thence South 56 degrees 40 minutes West, "
            "150.00 feet to an iron pin; thence North 33 degrees 20 minutes West, "
            "125.00 feet to an iron pin; thence North 56 degrees 40 minutes East, "
            "150.00 feet to an iron pin; thence South 33 degrees 20 minutes East, "
            "125.00 feet to the POINT OF BEGINNING."
        )
        calls, _ = extract_calls(text)
        for i, call in enumerate(calls):
            assert call.course == i + 1

    def test_bearing_quadrant_extracted(self) -> None:
        from mp_parse.calls import extract_calls

        text = (
            "BEGINNING at an iron pin; thence South 56 degrees 40 minutes West, "
            "150.00 feet to an iron pin; thence North 33 degrees 20 minutes West, "
            "125.00 feet to the POINT OF BEGINNING."
        )
        calls, _ = extract_calls(text)
        assert calls[0].bearing_quadrant is not None
        assert "S" in calls[0].bearing_quadrant
        assert "W" in calls[0].bearing_quadrant

    def test_distance_extracted(self) -> None:
        from mp_parse.calls import extract_calls

        text = (
            "BEGINNING at an iron pin; thence South 56 degrees 40 minutes West, "
            "150.00 feet to an iron pin; thence North 33 degrees 20 minutes West, "
            "125.00 feet to the POINT OF BEGINNING."
        )
        calls, _ = extract_calls(text)
        assert calls[0].distance_ft == 150.00
        assert calls[1].distance_ft == 125.00

    def test_azimuth_computed(self) -> None:
        from mp_parse.calls import extract_calls

        text = (
            "BEGINNING at an iron pin; thence South 56 degrees 40 minutes West, "
            "150.00 feet to an iron pin; thence North 33 degrees 20 minutes West, "
            "125.00 feet to the POINT OF BEGINNING."
        )
        calls, _ = extract_calls(text)
        # S 56 deg 40' W -> 180 + 56.667 = 236.667
        assert calls[0].bearing_azimuth_deg_from_north is not None
        assert 236.0 < calls[0].bearing_azimuth_deg_from_north < 237.0

    def test_monument_classified(self) -> None:
        from mp_parse.calls import extract_calls

        text = (
            "BEGINNING at an iron pin; thence South 56 degrees 40 minutes West, "
            "150.00 feet to an iron pin; thence North 33 degrees 20 minutes West, "
            "125.00 feet to the POINT OF BEGINNING."
        )
        calls, _ = extract_calls(text)
        assert calls[0].monument_type == "iron_pin"

    def test_skips_beginning_text(self) -> None:
        """BEGINNING preamble should not produce a call."""
        from mp_parse.calls import extract_calls

        text = (
            "BEGINNING at an iron pin on the south side; thence North 45 degrees East, "
            "100.00 feet to a point; thence South 45 degrees East, "
            "100.00 feet to the POINT OF BEGINNING."
        )
        calls, _ = extract_calls(text)
        # Should not start with a "BEGINNING" call
        for call in calls:
            assert not call.direction_text.upper().startswith("BEGINNING")

    def test_empty_text_returns_empty(self) -> None:
        from mp_parse.calls import extract_calls

        calls, _ = extract_calls("")
        assert calls == []


class TestExtractDirection:
    def test_quadrant_bearing(self) -> None:
        from mp_parse.calls import extract_direction

        # Standard DMS notation matches the QUADRANT_PATTERN
        result = extract_direction("S 56°40' W, 150.00 feet")
        assert "S" in result
        assert "W" in result

    def test_cardinal_words_direction(self) -> None:
        from mp_parse.calls import extract_direction

        # "South ... degrees ... minutes ... West" matched as cardinal "south"
        # until the text is normalized by standardize_cardinal_directions
        result = extract_direction("South 56 degrees 40 minutes West, 150.00 feet")
        assert result == "south"

    def test_cardinal_direction(self) -> None:
        from mp_parse.calls import extract_direction

        result = extract_direction("northerly along the road 100.00 feet")
        assert result == "northerly"

    def test_empty_for_no_direction(self) -> None:
        from mp_parse.calls import extract_direction

        result = extract_direction("100.00 feet along the fence")
        assert result == ""

    def test_packed_dms(self) -> None:
        from mp_parse.calls import extract_direction

        result = extract_direction("N 46.1631° E")
        # Should be converted to standard DMS format
        assert "N" in result
        assert "E" in result


class TestExtractCurveInfo:
    def test_basic_curve(self) -> None:
        from mp_parse.calls import extract_curve_info

        text = (
            "curve to the right, radius of 250.00 feet, delta angle of 30 degrees "
            "15 minutes, arc length of 132.00 feet"
        )
        info = extract_curve_info(text)
        assert info.get("direction") == "right"
        assert info.get("radius_ft") is not None
        assert abs(info["radius_ft"] - 250.0) < 0.01

    def test_no_curve_returns_empty(self) -> None:
        from mp_parse.calls import extract_curve_info

        info = extract_curve_info("South 56 degrees 40 minutes West, 150.00 feet")
        assert info == {}

    def test_chord_bearing(self) -> None:
        from mp_parse.calls import extract_curve_info

        text = (
            "curve to the left, radius of 500.00 feet, delta angle of 20 degrees, "
            "arc length of 174.53 feet, the chord of which bears S 34°57' E"
        )
        info = extract_curve_info(text)
        assert info.get("chord_bearing") is not None
        assert "S" in info["chord_bearing"]

    def test_chord_bearing_phrasing(self) -> None:
        from mp_parse.calls import extract_curve_info

        info = extract_curve_info(
            "a curve to the right, radius of 50 feet, delta angle of 90 degrees, "
            "chord bearing North 45\u00b0 East 70.71 feet"
        )
        assert info["chord_bearing"] == "N 45\u00b0 E"
        assert info["chord_length_ft"] == 70.71

    def test_non_tangent_detection(self) -> None:
        from mp_parse.calls import extract_curve_info

        text = "non-tangent curve to the right, radius of 300.00 feet, delta angle of 15 degrees"
        info = extract_curve_info(text)
        assert info.get("non_tangent") is True

    def test_radial_bearing_detection(self) -> None:
        from mp_parse.calls import extract_curve_info

        text = (
            "curve to the right, radial line bears N 45°00' E, "
            "radius of 300.00 feet, delta angle of 15 degrees"
        )
        info = extract_curve_info(text)
        assert info.get("non_tangent") is True
        assert info.get("radial_bearing") is not None

    def test_compound_curve_type(self) -> None:
        from mp_parse.calls import extract_curve_info

        text = (
            "curve to the right at a point of compound curvature, "
            "radius of 400.00 feet, delta angle of 10 degrees"
        )
        info = extract_curve_info(text)
        assert info.get("curve_type") == "compound"

    def test_reverse_curve_type(self) -> None:
        from mp_parse.calls import extract_curve_info

        text = (
            "curve to the left at the point of reverse curvature, "
            "radius of 400.00 feet, delta angle of 10 degrees"
        )
        info = extract_curve_info(text)
        assert info.get("curve_type") == "reverse"


class TestExtractDistanceAlternate:
    def test_apostrophe_distance(self) -> None:
        from mp_parse.calls import extract_distance_alternate

        result = extract_distance_alternate("125.26' along the road")
        assert abs(result - 125.26) < 0.01

    def test_feet_unit(self) -> None:
        from mp_parse.calls import extract_distance_alternate

        result = extract_distance_alternate("250.00 feet along the road")
        assert abs(result - 250.0) < 0.01

    def test_no_distance_returns_zero(self) -> None:
        from mp_parse.calls import extract_distance_alternate

        result = extract_distance_alternate("along the road to a point")
        assert result == 0.0


class TestMarkTieInCalls:
    def test_no_poc_returns_unchanged(self) -> None:
        from mp_models import DeedCall
        from mp_parse.calls import mark_tie_in_calls

        calls = [
            DeedCall(course=1, direction_text="N 45°00' E", distance_ft=100.0),
            DeedCall(course=2, direction_text="S 45°00' E", distance_ft=100.0),
        ]
        result = mark_tie_in_calls(calls, poc_description=None)
        assert all(not c.is_tie_in for c in result)

    def test_marks_calls_before_pob(self) -> None:
        from mp_models import DeedCall
        from mp_parse.calls import mark_tie_in_calls

        calls = [
            DeedCall(
                course=1,
                direction_text="N 45°00' E",
                distance_ft=100.0,
                to="the point of beginning",
            ),
            DeedCall(course=2, direction_text="S 45°00' E", distance_ft=100.0),
        ]
        result = mark_tie_in_calls(calls, poc_description="a reference point")
        assert result[0].is_tie_in is True
        assert result[1].is_tie_in is False


class TestEnrichCallsWithAzimuths:
    def test_adds_missing_azimuth(self) -> None:
        from mp_models import DeedCall
        from mp_parse.calls import enrich_calls_with_azimuths

        calls = [
            DeedCall(
                course=1,
                direction_text="N 45°00' E",
                bearing_quadrant="N 45°00' E",
                distance_ft=100.0,
                bearing_azimuth_deg_from_north=None,
            ),
        ]
        result = enrich_calls_with_azimuths(calls)
        assert result[0].bearing_azimuth_deg_from_north is not None
        assert abs(result[0].bearing_azimuth_deg_from_north - 45.0) < 0.01

    def test_preserves_existing_azimuth(self) -> None:
        from mp_models import DeedCall
        from mp_parse.calls import enrich_calls_with_azimuths

        calls = [
            DeedCall(
                course=1,
                direction_text="N 45°00' E",
                bearing_quadrant="N 45°00' E",
                distance_ft=100.0,
                bearing_azimuth_deg_from_north=45.0,
            ),
        ]
        result = enrich_calls_with_azimuths(calls)
        assert result[0].bearing_azimuth_deg_from_north == 45.0


class TestChordBearingNotTangent:
    CURVE = (
        "thence along a curve to the right having a radius of 100.00 feet, "
        "a delta of 90°00'00\", an arc length of 157.08 feet, chord bears {chord} 141.42 feet"
    )

    def test_abbreviated_and_spelled_chord_agree(self) -> None:
        from mp_parse.calls import extract_single_call

        a = extract_single_call(self.CURVE.format(chord="N 45°00'00\" E"), 1)
        b = extract_single_call(self.CURVE.format(chord="North 45°00'00\" East"), 1)
        assert a is not None and b is not None
        assert a.bearing_azimuth_deg_from_north == b.bearing_azimuth_deg_from_north
        assert abs(a.bearing_azimuth_deg_from_north) < 1e-6
        assert a.bearing_quadrant is None
        assert "derived from chord bearing" in (a.notes or "")

    def test_separate_tangent_bearing_kept(self) -> None:
        from mp_parse.calls import extract_single_call

        text = (
            "thence N 10°00'00\" E along a curve to the right having a radius of 100.00 feet, "
            "a delta of 90°00'00\", an arc length of 157.08 feet, chord bears N 55°00'00\" E 141.42 feet"
        )
        c = extract_single_call(text, 1)
        assert c is not None
        assert c.bearing_azimuth_deg_from_north == 10.0


class TestChordDegreesNeverDelta:
    ARC_CHORD = (
        "thence along a curve to the right having a radius of 100.00 feet, an arc length of "
        "50.00 feet, the chord of which bears N 45°00'00\" E 49.00 feet{along} to a point"
    )

    def test_chord_bearing_degrees_are_not_delta(self) -> None:
        from mp_parse.calls import extract_curve_info

        assert extract_curve_info(self.ARC_CHORD.format(along="")).get("delta_deg") is None

    def test_tangent_from_arc_radius_delta_with_along_text(self) -> None:
        import math

        from mp_parse.calls import extract_single_call

        expected = 45.0 - math.degrees(0.5) / 2.0
        for along in ("", " along the Northerly line of Pennbrook Drive"):
            c = extract_single_call(self.ARC_CHORD.format(along=along), 1)
            assert c is not None
            assert abs(c.bearing_azimuth_deg_from_north - expected) < 1e-9
            assert c.delta_deg is None
            assert "delta computed from arc length and radius" in (c.notes or "")


def test_radial_bearing_clause_is_not_a_stated_tangent():
    from mp_parse.calls import _without_radial_bearing

    stripped = _without_radial_bearing("curve whose radius point bears S 10° W, radius 500 feet")
    assert "S 10" not in stripped
    assert "radius 500 feet" in stripped
