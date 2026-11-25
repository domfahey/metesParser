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

    def test_spelled_out_bearing_with_minutes_seconds_comma_parses(self) -> None:
        """Bug #49: comma between minutes and seconds should not break bearing parse."""
        import math

        from mp_parse.calls import extract_calls

        text = (
            "BEGINNING at a point; "
            "thence North 71 degrees 54 minutes, 20 seconds West 69.17 feet to a point; "
            "thence South 71 degrees 54 minutes, 20 seconds East 69.17 feet to the point of beginning."
        )
        calls, _ = extract_calls(text)

        assert len(calls) == 2
        assert calls[0].bearing_quadrant is not None
        assert calls[0].bearing_azimuth_deg_from_north is not None
        assert math.isclose(calls[0].bearing_azimuth_deg_from_north, 288.0944, abs_tol=0.001)

    def test_inline_tie_in_courses_before_numbered_calls_marked(self) -> None:
        """Bug #50: preamble tie-in courses should be separated and flagged."""
        from mp_parse.calls import extract_calls

        text = (
            "BEGINNING at a point which is located at the following two courses and distances "
            "from the intersection of the Southwesterly line of Ellis Street (66 feet wide) "
            "with the Southeasterly line of Walnut Street (60 feet wide); "
            "thence South 71 degrees 54 minutes 50 seconds East along the Southwesterly line "
            "of Ellis Street 122.55 feet to a point. "
            "South 18 degrees 05 minutes 10 seconds West 123.00 feet to the point and place of beginning; "
            "thence (1) South 18 degrees 05 minutes 10 seconds West 82.00 feet to a point; "
            "thence (2) North 71 degrees 54 minutes 50 seconds West 122.55 feet to a point; "
            "thence (3) North 18 degrees 05 minutes 10 seconds East 82.00 feet to a point; "
            "thence (4) South 71 degrees 54 minutes 50 seconds East 122.55 feet to the point and place of beginning."
        )
        calls, _ = extract_calls(text)

        assert len(calls) == 6
        assert calls[0].is_tie_in is True
        assert calls[1].is_tie_in is True
        assert all(not c.is_tie_in for c in calls[2:])

    def test_multiline_tract3_inline_tie_in_courses_and_closure(self) -> None:
        """Bug #50: multi-line Tract 3 with newlines around (1)-(4) extracts 6 calls."""
        import math

        from mp_parse.calls import extract_calls

        text = (
            "Tract No. 3\n"
            "BEGINNING at a point which is located at the following two courses and distances "
            "from the intersection of the Southwesterly line of Ellis Street (66 feet wide) "
            "with the Southeasterly line of Walnut Street (60 feet wide); thence\n\n"
            "South 71 degrees 54 minutes 50 seconds East along the Southwesterly line of Ellis Street "
            "122.55 feet to a point. South 18 degrees 05 minutes 10 seconds West 123.00 feet to the "
            "point and place of beginning; thence\n\n"
            "(1) South 18 degrees 05 minutes 10 seconds West 82.00 feet to a point; thence\n"
            "(2) North 71 degrees 54 minutes 50 seconds West 53.36 feet to a point; thence\n"
            "(3) North 18 degrees 17 minutes 22 seconds East 82.00 feet to a point; thence\n"
            "(4) South 71 degrees 54 minutes 50 seconds East 53.19 feet to the point and place of beginning."
        )
        calls, _ = extract_calls(text)

        assert len(calls) == 6
        assert calls[0].is_tie_in is True
        assert math.isclose(calls[0].distance_ft, 122.55, abs_tol=0.01)
        assert calls[1].is_tie_in is True
        assert math.isclose(calls[1].distance_ft, 123.00, abs_tol=0.01)
        assert [round(c.distance_ft, 2) for c in calls[2:]] == [82.00, 53.36, 82.00, 53.19]
        assert all(not c.is_tie_in for c in calls[2:])


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
