"""Tests for standalone utility scripts."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path


def _load_audit_module():
    """Import the audit_gt_vs_md script as a module."""
    spec = importlib.util.spec_from_file_location(
        "audit_gt_vs_md",
        Path(__file__).parent.parent.parent / "scripts" / "audit_gt_vs_md.py",
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestAuditGtVsMdCardinalPattern:
    """The audit script's CARDINAL_ONLY_PATTERN should match the canonical
    pattern from call_extractor.py for consistency."""

    def test_canonical_pattern_matches_wardly_compounds(self) -> None:
        """The canonical _CARDINAL_ONLY_PATTERN handles 'wardly' suffix on
        compound directions."""
        from metesparser.call_extractor import _CARDINAL_ONLY_PATTERN

        assert _CARDINAL_ONLY_PATTERN.fullmatch("northeastwardly")
        assert _CARDINAL_ONLY_PATTERN.fullmatch("southwestwardly")
        assert _CARDINAL_ONLY_PATTERN.fullmatch("northwestwardly")
        assert _CARDINAL_ONLY_PATTERN.fullmatch("southeastwardly")

    def test_audit_script_pattern_matches_wardly_compounds(self) -> None:
        """The audit script's CARDINAL_ONLY_PATTERN should also match
        compound+wardly forms for consistency with canonical pattern."""
        mod = _load_audit_module()
        pattern: re.Pattern[str] = mod.CARDINAL_ONLY_PATTERN

        assert pattern.search("Northeastwardly")
        assert pattern.search("Southwestwardly")
        assert pattern.search("Northwestwardly")
        assert pattern.search("Southeastwardly")

    def test_audit_script_pattern_matches_all_canonical_forms(self) -> None:
        """Every form matched by the canonical pattern should also be matched
        by the audit script's pattern."""
        mod = _load_audit_module()
        audit_pattern: re.Pattern[str] = mod.CARDINAL_ONLY_PATTERN

        all_forms = [
            "north",
            "south",
            "east",
            "west",
            "northeast",
            "northwest",
            "southeast",
            "southwest",
            "northerly",
            "southerly",
            "easterly",
            "westerly",
            "northeasterly",
            "northwesterly",
            "southeasterly",
            "southwesterly",
            "northwardly",
            "southwardly",
            "eastwardly",
            "westwardly",
            "northeastwardly",
            "northwestwardly",
            "southeastwardly",
            "southwestwardly",
        ]

        for form in all_forms:
            assert audit_pattern.search(form), f"Audit pattern should match '{form}'"


class TestAuditFallbackExtraction:
    """Tests for the Step 2b fallback when BEGINNING is garbled/missing."""

    def test_fallback_extracts_calls_without_beginning(self) -> None:
        """When BEGINNING is garbled but closure language and thence exist,
        the fallback should extract calls via thence-splitting."""
        mod = _load_audit_module()
        md_text = (
            "Some preamble text.\n"
            "BEGINNiNn at a garbled point;\n"
            "thence North 45 degrees 00 minutes East 100.00 feet to a stake;\n"
            "thence South 45 degrees 00 minutes East 100.00 feet to a stake;\n"
            "thence South 45 degrees 00 minutes West 100.00 feet to a stake;\n"
            "thence North 45 degrees 00 minutes West 100.00 feet to the place of beginning."
        )
        calls = mod.extract_calls_from_md(md_text)
        assert len(calls) == 4
        assert calls[0]["distance_ft"] == 100.00

    def test_fallback_excludes_preamble(self) -> None:
        """The fallback should anchor to the first thence, not include
        preamble text that could produce false bearing matches."""
        mod = _load_audit_module()
        md_text = (
            "North 10 degrees 00 minutes East 999.00 feet preamble text.\n"
            "BEGINNiNn at a garbled point;\n"
            "thence South 30 degrees 00 minutes West 50.00 feet to a stake;\n"
            "thence North 30 degrees 00 minutes East 50.00 feet to the point of beginning."
        )
        calls = mod.extract_calls_from_md(md_text)
        assert len(calls) == 2
        # Should NOT include the preamble bearing/distance
        assert calls[0]["distance_ft"] == 50.00

    def test_no_fallback_when_no_closure_language(self) -> None:
        """When neither BEGINNING nor closure language exists,
        return empty list."""
        mod = _load_audit_module()
        md_text = "Just some random deed text with no legal description."
        calls = mod.extract_calls_from_md(md_text)
        assert calls == []

    def test_markdown_bold_beginning_matched(self) -> None:
        """BEGINNING_PATTERN should match **BEGINNING** (bold) and
        *BEGINNING* (italic) markdown markers."""
        mod = _load_audit_module()
        assert mod.BEGINNING_PATTERN.search("**BEGINNING** at a stone")
        assert mod.BEGINNING_PATTERN.search("**BEGINNING** in the Northwesterly line")
        # Italic markdown (single asterisk)
        assert mod.BEGINNING_PATTERN.search("*BEGINNING* at a stone")
        # Still matches without any markers
        assert mod.BEGINNING_PATTERN.search("BEGINNING at a stone")

    def test_page_wrap_extracts_all_calls(self) -> None:
        """When BEGINNING is after closure in the file (reversed page order),
        the extraction should wrap around and find all calls."""
        mod = _load_audit_module()
        # Simulate reversed-page MD: calls 2-3 + closure at top, BEGINNING + call 1 at bottom
        md_text = (
            "(2) Westwardly along said line 112.96 feet to a point; thence\n"
            "(3) Southwardly along said boundary 95.00 feet to the place of beginning.\n"
            "\n"
            "Some deed boilerplate text in the middle.\n"
            "\n"
            "**BEGINNING** at a point in the Westerly line; thence\n"
            "(1) Northwardly along the line 95.00 feet to a point; thence\n"
        )
        calls = mod.extract_calls_from_md(md_text)
        assert len(calls) == 3
        # Verify correct order: call 1 first (from BEGINNING section), then 2, then 3
        assert calls[0]["distance_ft"] == 95.00
        assert calls[1]["distance_ft"] == 112.96
        assert calls[2]["distance_ft"] == 95.00

    def test_page_wrap_uses_last_closure_before_beginning(self) -> None:
        """When multiple closures exist before BEGINNING in reversed-page text,
        the page wrap should use the LAST closure (closest to BEGINNING),
        not the first one."""
        mod = _load_audit_module()
        # Two POB_CLOSE matches before BEGINNING — the page wrap should use
        # the second (closest to BEGINNING), not the first.
        md_text = (
            "said property returns to the point of beginning.\n"
            "\n"
            "(2) Eastwardly along said line 50.00 feet to a point; thence\n"
            "(3) Southwardly 75.00 feet to the place of beginning.\n"
            "\n"
            "**BEGINNING** at a stake; thence\n"
            "(1) Northwardly 75.00 feet to a point; thence\n"
        )
        calls = mod.extract_calls_from_md(md_text)
        assert len(calls) == 3
        assert calls[0]["distance_ft"] == 75.00
        assert calls[1]["distance_ft"] == 50.00
        assert calls[2]["distance_ft"] == 75.00

    def test_no_beginning_not_flagged_when_fallback_recovers_calls(self) -> None:
        """The NO_BEGINNING issue should NOT be raised when the fallback
        successfully extracted calls (n_md > 0)."""
        mod = _load_audit_module()
        # The audit_deed function needs GT and MD files, so test the logic
        # directly: when n_gt > 0 and n_md > 0, NO_BEGINNING should not fire
        md_text = (
            "BEGINNiNn garbled;\n"
            "thence North 45 degrees 00 minutes East 100.00 feet;\n"
            "thence South 45 degrees 00 minutes West 100.00 feet to the place of beginning."
        )
        calls = mod.extract_calls_from_md(md_text)
        # Fallback should find calls
        assert len(calls) > 0
        # BEGINNING_PATTERN should NOT match the garbled text
        assert not mod.BEGINNING_PATTERN.search(md_text)


class TestAuditTotalDistance:
    """A course that passes a monument records the full course length as its distance."""

    def test_total_distance_beats_intermediate_distance(self) -> None:
        mod = _load_audit_module()
        md_text = (
            "BEGINNING at a stone; thence "
            "North 53 degrees 41 minutes 15 seconds East, passing over stone 292.51 feet "
            "from Haddon Avenue and continuing said course a total distance of 307.52 feet "
            "to a stake; thence "
            "South 53 degrees 41 minutes 15 seconds West, passing over stone 15.83 feet "
            "from beginning of this course total distance of 336.25 feet "
            "to place of beginning."
        )
        calls = mod.extract_calls_from_md(md_text)
        assert [call["distance_ft"] for call in calls] == [307.52, 336.25]


class TestAuditMultiTract:
    """101-111 Kings Highway E: marked tracts, exceptions, tie lines and mixed bearings."""

    def test_comma_separated_dms_bearing(self) -> None:
        mod = _load_audit_module()
        match = mod.BEARING_PATTERN.search("North 29 degrees, 23 minutes, 50 seconds West")
        assert match is not None
        assert match.groups() == ("N", "29", "23", "50", "W")

    def test_distance_includes_inches_and_skips_widths_and_offsets(self) -> None:
        mod = _load_audit_module()
        assert mod.extract_distance("Southeastwardly 92 feet, 4 inches to a point") == (92 + 4 / 12)
        assert mod.extract_distance(
            "along the aforesaid 10 feet wide alley, a distance of 148.10 feet"
        ) == (148.10)
        assert mod.extract_distance(
            "distant 10 feet Northeastwardly therefrom measured at right angles thereto "
            "158 feet 8 inches, more or less"
        ) == (158 + 8 / 12)

    def test_restated_place_of_beginning_does_not_close_the_block(self) -> None:
        mod = _load_audit_module()
        md_text = (
            "STARTING at a point; thence in a Northwesterly direction a distance of 148.10 "
            "feet to a point which last mentioned point is the place of beginning on the lands "
            "hereby being described; and continuing thence in a Northwesterly direction a "
            "distance of 12 feet; thence in a Northeasterly direction a distance of 50 feet "
            "to the place of beginning."
        )
        calls = mod.extract_calls_from_md(md_text)
        assert [call["distance_ft"] for call in calls] == [148.10, 12, 50]

    def test_marked_tracts_keep_cardinal_only_blocks_and_exceptions(self) -> None:
        mod = _load_audit_module()
        md_text = (
            "TRACT #1: BEGINNING at a point; thence (1) North 29 degrees, 23 minutes West "
            "72.64 feet; thence (2) Southwestwardly 107.03 feet to the place of beginning.\n"
            "TRACT #2: BEGINNING at a point; thence Southwestwardly 117.61 feet; thence "
            "Northwestwardly 138.43 feet to the place of beginning.\n"
            "EXCEPTING THEREOUT: BEGINNING on the Northwesterly side of Main Street; thence "
            "South 61 degrees 5 minutes West 50 feet; thence Northwardly 147.60 feet to "
            "beginning."
        )
        calls = mod.extract_calls_from_md(md_text, n_gt=7)
        assert [call["distance_ft"] for call in calls] == [
            72.64,
            107.03,
            117.61,
            138.43,
            50,
            147.60,
        ]

    def test_place_of_beginning_on_the_lands_is_not_a_block_start(self) -> None:
        mod = _load_audit_module()
        assert not mod.BLOCK_START_PATTERN.search("is the place of beginning on the lands")
        assert mod.BLOCK_START_PATTERN.search("BEGINNING on the Northwesterly side")


class TestAuditMain:
    def test_main_reports_skipped_deeds(self, tmp_path, monkeypatch, capsys) -> None:
        """A PDF without its md/ground-truth pair is reported as SKIP, not a crash."""
        mod = _load_audit_module()
        (tmp_path / "1 Main St - Deed Image (1 - 1).pdf").write_bytes(b"")
        monkeypatch.setattr(mod, "SAMPLE_DIR", tmp_path)

        mod.main()

        out = capsys.readouterr().out
        assert "GT AUDIT: 0 PASS / 0 FAIL / 1 SKIP out of 1" in out
        assert "1 Main St: 0/1 pass (0%) | 0 fail | 1 skip" in out


class TestAuditEmptyGroundTruth:
    MD = (
        "BEGINNING at a point; thence North 10 degrees 00 minutes 00 seconds East 100 feet; "
        "thence South 10 degrees 00 minutes 00 seconds West 100 feet to the point of beginning."
    )

    def _write(self, tmp_path, md_text: str, calls: list[dict[str, object]]) -> str:
        base = "1 Main St - Deed Image (1 - 1)"
        (tmp_path / f"{base}.md").write_text(md_text)
        (tmp_path / f"{base}.ground_truth.json").write_text(json.dumps({"expected_calls": calls}))
        return base

    def test_empty_ground_truth_with_md_courses_fails(self, tmp_path, monkeypatch) -> None:
        mod = _load_audit_module()
        monkeypatch.setattr(mod, "SAMPLE_DIR", tmp_path)
        result = mod.audit_deed(self._write(tmp_path, self.MD, []))
        assert result["status"] == "FAIL"
        assert result["issues"] == ["EMPTY_GT: GT has no calls but MD extracted=2"]

    def test_empty_ground_truth_without_md_courses_passes(self, tmp_path, monkeypatch) -> None:
        mod = _load_audit_module()
        monkeypatch.setattr(mod, "SAMPLE_DIR", tmp_path)
        result = mod.audit_deed(self._write(tmp_path, "See Schedule A attached hereto", []))
        assert result["status"] == "PASS"


class TestAuditSchedules:
    """219 Berlin Rd 12799-00118: schedule attachments and trailing-thence courses."""

    def test_schedule_city_is_not_a_schedule_c_section(self) -> None:
        mod = _load_audit_module()
        assert not mod.EXHIBIT_PATTERN.search("SEE ATTACHED SCHEDULE\n    City, Town")
        assert mod.EXHIBIT_PATTERN.search("SCHEDULE C")
        assert mod.EXHIBIT_PATTERN.search('EXHIBIT "A"')

    def test_said_point_of_beginning_in_preamble_does_not_close_the_block(self) -> None:
        mod = _load_audit_module()
        md_text = (
            "BEGINNING at a point, said point of beginning being also distant 24.75 feet "
            "from the center line, and from said point of beginning, proceeding thence "
            "North 50 degrees 45 minutes 00 seconds East, a distance of 416.57 feet; thence "
            "South 32 degrees 36 minutes 00 seconds East, a distance of 300.07 feet to said "
            "point of beginning."
        )
        calls = mod.extract_calls_from_md(md_text)
        assert [call["distance_ft"] for call in calls] == [416.57, 300.07]

    def test_course_ending_in_thence_after_preamble_is_kept(self) -> None:
        mod = _load_audit_module()
        md_text = (
            "Beginning at a point said point being the following two courses and distances "
            "from the intersection of White Horse Road with Burnt Mill Road.\n\n"
            "North 40 Degrees 41 Minutes 31 Seconds East a distance of 483.13 feet to a point "
            "thence;\n\n"
            "North 59 Degrees 29 Minutes 19 Seconds West a distance of 17.78 feet to a point "
            "thence;\n\n"
            "South 59 Degrees 29 Minutes 19 Seconds East a distance of 250.44 feet to point "
            "and place of beginning."
        )
        calls = mod.extract_calls_from_md(md_text)
        assert [call["distance_ft"] for call in calls] == [483.13, 17.78, 250.44]


class TestAuditLetteredTieCourses:
    """36 Kresson: tie courses (A) and (B) reach a point of beginning that more courses follow."""

    EXCEPTION = (
        "BEGINNING at a point along a line common with Lot 13A, said point being the following "
        "courses and distances from the intersection of Willard Avenue with Kresson Road\n\n"
        "(A) Along the said row line of Kresson Road North 73 degrees 30 minutes 00 seconds West "
        "a distance of 509.1 feet to a point common to said Lots 13 and 13B, thence;\n\n"
        "(B) Along line common to said Lots 13 and 13A South 16 degrees 30 minutes 00 seconds "
        "West a distance of 27.00 feet to a point and place of beginning{after_b}\n\n"
        "(1) South 73 degrees 30 minutes 00 seconds East a distance of 10.00 feet to a point, "
        "thence;\n\n"
        "(2) North 16 degrees 30 minutes 00 seconds East a distance of 47.00 feet to a point and "
        "place of BEGINNING.\n\nNOTE: Lot and Block shown for informational purposes only."
    )

    def test_lettered_tie_courses_and_following_courses_are_extracted(self) -> None:
        mod = _load_audit_module()
        for after_b in (", thence;", "."):
            calls = mod.extract_calls_from_md(self.EXCEPTION.format(after_b=after_b))
            assert [call["distance_ft"] for call in calls] == [509.1, 27.0, 10.0, 47.0], after_b

    def test_lot_s_mid_line_is_not_a_course_marker(self) -> None:
        mod = _load_audit_module()
        assert not mod.CALL_NUM_PATTERN.search("NOTE: Being Lot(s) 4, Block: 423.01")
        assert mod.CALL_NUM_PATTERN.search("\n(A) Along the said row line")


class TestAuditRepeatedDescriptions:
    def test_repeated_description_is_counted_once(self) -> None:
        """2 Walnut 10239-1279: an attached certification repeats Exhibit A word for word."""
        mod = _load_audit_module()
        lot = (
            "BEGINNING at a point in the Westerly line of Walnut Street; thence Westerly 51.00 "
            "feet; thence Southerly 177.97 feet to the point and place of beginning."
        )
        md_text = f"# EXHIBIT A\n\n{lot}\n\n# Exhibit B\nCertification of Trust\n\n{lot}\n"
        calls = mod.extract_calls_from_md(md_text)
        assert [call["distance_ft"] for call in calls] == [51.0, 177.97]


class TestAuditExhibitReferences:
    """One Centennial Square: the deed body refers to Exhibit A and to a recording page."""

    MD = (
        'SEE EXHIBIT "A" ATTACHED HERETO AND MADE A PART HEREOF.\n\n'
        "BEING the same premises recorded in Deed Book 4795, beginning at page 618.\n\n"
        'EXHIBIT "A"\n\n'
        "BEGINNING at a point in the Northwesterly line of Euclid Avenue; thence\n"
        "(1) North 49 degrees 06 minutes 30 seconds East a distance of 213.26 feet; thence\n"
        "(2) Along lands of the Port Authority curving to the right with a radius of 5933.53 "
        "feet, an arc distance of 344.93 feet to a point; thence\n"
        "(3) South 21 degrees 01 minutes 53 seconds East a distance of 285.44 feet to the "
        "point and place of beginning."
    )

    def test_exhibit_reference_and_recording_page_are_skipped(self) -> None:
        mod = _load_audit_module()
        assert mod.find_preferred_text(self.MD).startswith('EXHIBIT "A"\n')
        assert not mod.BLOCK_START_PATTERN.search("Deed Book 4795, beginning at page 618")

    def test_curve_length_is_its_arc(self) -> None:
        mod = _load_audit_module()
        calls = mod.extract_calls_from_md(self.MD)
        assert [call["distance_ft"] for call in calls] == [213.26, 344.93, 285.44]


class TestAuditPrintedValues:
    """A misprinted course records its intended value and the printed value the markdown shows."""

    MD = (
        "BEGINNING at a point; thence South 64 degrees 22 minutes 25 seconds West, 229.89 feet "
        "to a point; thence North 46 degrees 46 minutes 25 seconds West, 59.30 feet to the point "
        "and place of beginning."
    )

    def _audit(self, tmp_path, monkeypatch, first_call: dict[str, object]) -> dict[str, object]:
        mod = _load_audit_module()
        monkeypatch.setattr(mod, "SAMPLE_DIR", tmp_path)
        base = "26 Chews Landing Rd - Deed Image (1 - 1)"
        calls = [first_call, {"bearing_azimuth_deg_from_north": 313.2264, "distance_ft": 59.30}]
        (tmp_path / f"{base}.md").write_text(self.MD)
        (tmp_path / f"{base}.ground_truth.json").write_text(json.dumps({"expected_calls": calls}))
        return mod.audit_deed(base)

    def test_printed_value_is_compared_with_the_markdown(self, tmp_path, monkeypatch) -> None:
        result = self._audit(
            tmp_path,
            monkeypatch,
            {
                "bearing_azimuth_deg_from_north": 244.3736,
                "distance_ft": 299.89,
                "printed_distance_ft": 229.89,
            },
        )
        assert result["status"] == "PASS", result["issues"]

    def test_intended_value_without_printed_value_fails(self, tmp_path, monkeypatch) -> None:
        result = self._audit(
            tmp_path,
            monkeypatch,
            {"bearing_azimuth_deg_from_north": 244.3736, "distance_ft": 299.89},
        )
        assert result["issues"] == ["DISTANCE_C1: GT=299.89ft, MD=229.89ft (diff=70.00ft)"]


class TestAuditTractReferences:
    def test_tract_reference_does_not_cut_an_unclosed_description(self) -> None:
        """89 Haddon 4455-174: "boundary line of Tract #1 of Haddonfield Estates" is a reference."""
        mod = _load_audit_module()
        md_text = (
            "BEGINNING at a point in the former Southeasterly boundary line of Tract #1 of "
            "Haddonfield Estates; running thence (1) North 54 degrees 44 minutes 05 seconds East, "
            "a distance of 141.73 feet to a point; thence (2) South 19 degrees 58 minutes 30 "
            "seconds West, a distance of 146.44 feet to a found field stone [page unreadable]\n\n"
            "TRACT #2: other land"
        )
        calls = mod.extract_calls_from_md(md_text)
        assert [call["distance_ft"] for call in calls] == [141.73, 146.44]


class TestAuditNearRepeatedDescriptions:
    LOT = (
        "BEGINNING at a corner formed by the intersection of the Southwest line of {street} Street "
        "(66 feet wide) with the Northwesterly line of Walnut Street (60 feet wide), which corner "
        "forms an interior angle of 90 degrees; and extending thence in a northwesterly direction "
        "along the Southwesterly line of {street} Street a distance of {d1} feet to a point corner "
        "to lands now or late of Henry E. Uber and wife; thence in a Southwesterly direction and at "
        "right angles to Ellis Street and along the line of lands now or late of Uber a distance of "
        "125 feet; thence in a Northwesterly direction and at right angles to the last course and "
        "along the line of lands now or late of Uber a distance of 42.79 feet to a point corner to "
        "lands now or late of Isaac Nicholson; thence in a Southwesterly direction and at right "
        "angles to the last course a distance of 172 feet to a point; thence in a Southeasterly "
        "direction and at right angles to the last course a distance of {d5} feet; thence in a "
        "Northeasterly direction along the Northwesterly line of Walnut Street a distance of "
        "248.31 feet to the place of beginning."
    )

    def test_ocr_noisy_repeat_is_counted_once(self) -> None:
        """2 Walnut 10239-1268: the certification's copy reads "Elis" and "81 52"."""
        mod = _load_audit_module()
        first = self.LOT.format(street="Ellis", d1="265.21", d5="81.52")
        copy = self.LOT.format(street="Elis", d1="265.21", d5="81 52")
        calls = mod.extract_calls_from_md(f"{first}\n\nCertification of Trust\n\n{copy}")
        assert [call["distance_ft"] for call in calls] == [
            265.21,
            125.0,
            42.79,
            172.0,
            81.52,
            248.31,
        ]

    def test_similar_parcels_with_different_distances_are_kept(self) -> None:
        mod = _load_audit_module()
        lot_a = self.LOT.format(street="Ellis", d1="265.21", d5="81.52")
        lot_b = self.LOT.format(street="Ellis", d1="200.00", d5="60.00")
        calls = mod.extract_calls_from_md(f"{lot_a}\n\n{lot_b}")
        assert len(calls) == 12
